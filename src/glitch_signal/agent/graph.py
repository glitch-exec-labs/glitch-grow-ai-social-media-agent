"""LangGraph StateGraph for the Glitch Social Media Agent video pipeline.

Graph flow:
  scout → script_writer → storyboard → video_router → video_generator → END
                                                                         ↑
  video_assembler → quality_check → [pass] → telegram_preview → END
                                  → [retry] → storyboard (retry_count < 2)
                                  → [escalate] → END (Telegram alert sent)

The video_generator node dispatches shots to video model APIs and returns.
The scheduler re-invokes from video_assembler when all shots complete.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from glitch_signal.agent.state import SignalAgentState
from glitch_signal.agent.nodes.scout import scout_node
from glitch_signal.agent.nodes.script_writer import script_writer_node
from glitch_signal.agent.nodes.storyboard import storyboard_node
from glitch_signal.agent.nodes.video_router import video_router_node
from glitch_signal.agent.nodes.video_generator import video_generator_node
from glitch_signal.agent.nodes.video_assembler import video_assembler_node
from glitch_signal.agent.nodes.quality_check import quality_check_node
from glitch_signal.agent.nodes.telegram_preview import telegram_preview_node


MAX_QC_RETRIES = 2


def _qc_router(state: SignalAgentState) -> str:
    if state.get("qc_passed"):
        return "pass"
    retry_count = int(state.get("retry_count") or 0)
    if retry_count < MAX_QC_RETRIES:
        return "retry"
    return "escalate"


async def _escalate_node(state: SignalAgentState) -> SignalAgentState:
    """Send Telegram alert when QC fails after max retries."""
    import structlog
    from glitch_signal.config import settings
    log = structlog.get_logger(__name__)

    asset_id = state.get("asset_id", "unknown")
    script_id = state.get("script_id", "unknown")
    qc_notes = state.get("qc_notes", "")

    msg = (
        f"QC escalation — video failed after {MAX_QC_RETRIES} retries\n"
        f"Script: {script_id[:8]}\n"
        f"Asset: {asset_id[:8]}\n"
        f"Notes: {qc_notes[:200]}"
    )
    log.error("graph.qc_escalated", script_id=script_id, asset_id=asset_id)

    if not settings().is_dry_run:
        try:
            from telegram import Bot
            bot = Bot(token=settings().telegram_bot_token_signal)
            for admin_id in settings().admin_telegram_ids:
                await bot.send_message(chat_id=admin_id, text=msg)
        except Exception as exc:
            log.error("graph.escalate_telegram_failed", error=str(exc))

    return {**state, "error": f"QC failed after {MAX_QC_RETRIES} retries: {qc_notes}"}


def build_graph() -> StateGraph:
    """Build and compile the full pipeline graph."""
    graph = StateGraph(SignalAgentState)

    # Register all nodes
    graph.add_node("scout", scout_node)
    graph.add_node("script_writer", script_writer_node)
    graph.add_node("storyboard", storyboard_node)
    graph.add_node("video_router", video_router_node)
    graph.add_node("video_generator", video_generator_node)
    graph.add_node("video_assembler", video_assembler_node)
    graph.add_node("quality_check", quality_check_node)
    graph.add_node("telegram_preview", telegram_preview_node)
    graph.add_node("escalate", _escalate_node)

    # Phase 1 pipeline: scout → ... → video_generator → END
    # (scheduler re-enters at video_assembler when shots complete)
    graph.set_entry_point("scout")
    graph.add_edge("scout", "script_writer")
    graph.add_edge("script_writer", "storyboard")
    graph.add_edge("storyboard", "video_router")
    graph.add_edge("video_router", "video_generator")
    graph.add_edge("video_generator", END)

    # Assembler branch (scheduler-triggered re-entry)
    graph.add_edge("video_assembler", "quality_check")
    graph.add_conditional_edges(
        "quality_check",
        _qc_router,
        {
            "pass": "telegram_preview",
            "retry": "storyboard",
            "escalate": "escalate",
        },
    )
    graph.add_edge("telegram_preview", END)
    graph.add_edge("escalate", END)

    return graph.compile()


# Singleton — built once per process
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
