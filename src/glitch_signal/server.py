"""FastAPI application for Glitch Social Media Agent.

Endpoints:
  GET  /healthz                    — liveness
  POST /jobs/scout                 — trigger Scout node manually
  POST /jobs/assemble/{script_id}  — trigger VideoAssembler for a script
  POST /telegram/webhook           — Telegram Update receiver
"""
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from sqlmodel import select
from telegram import Update

from glitch_signal import __version__
from glitch_signal.config import settings
from glitch_signal.db.models import ScheduledPost, Signal, VideoJob
from glitch_signal.db.session import _session_factory

log = structlog.get_logger(__name__)

app = FastAPI(
    title="Glitch Social Media Agent",
    version=__version__,
    description="Autonomous social video + ORM agent for Glitch Executor.",
)

_tg_app = None
_graph = None


@app.on_event("startup")
async def startup() -> None:
    global _tg_app, _graph

    # Build LangGraph
    from glitch_signal.agent.graph import get_graph
    _graph = get_graph()

    # Build and start Telegram bot (webhook mode)
    if settings().telegram_bot_token_signal:
        from glitch_signal.telegram.bot import build_app
        _tg_app = build_app()
        await _tg_app.initialize()
        await _tg_app.start()

    # Start scheduler
    from glitch_signal.scheduler.queue import start as start_scheduler
    start_scheduler()

    log.info("glitch_signal.started", version=__version__, port=3111)


@app.on_event("shutdown")
async def shutdown() -> None:
    from glitch_signal.scheduler.queue import stop as stop_scheduler
    stop_scheduler()

    if _tg_app:
        await _tg_app.stop()
        await _tg_app.shutdown()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> dict:
    factory = _session_factory()
    async with factory() as session:
        pending_veto_r = await session.execute(
            select(ScheduledPost).where(ScheduledPost.status == "pending_veto")
        )
        queued_r = await session.execute(
            select(ScheduledPost).where(ScheduledPost.status == "queued")
        )
        dispatching_r = await session.execute(
            select(VideoJob).where(VideoJob.status == "dispatched")
        )

    return {
        "status": "ok",
        "service": "glitch-signal",
        "version": __version__,
        "dispatch_mode": settings().dispatch_mode,
        "queue": {
            "pending_veto": len(pending_veto_r.scalars().all()),
            "queued_to_publish": len(queued_r.scalars().all()),
            "shots_in_flight": len(dispatching_r.scalars().all()),
        },
    }


# ---------------------------------------------------------------------------
# Manual triggers
# ---------------------------------------------------------------------------

@app.post("/jobs/scout")
async def job_scout(request: Request) -> dict:
    """Trigger a Scout run manually. Optionally pass {signal_id, platform} to run full pipeline."""
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    state = {
        "signal_id": body.get("signal_id", ""),
        "platform": body.get("platform", "youtube_shorts"),
        "retry_count": 0,
    }
    asyncio.create_task(_graph.ainvoke(state))
    return {"ok": True, "message": "Scout triggered in background"}


@app.post("/jobs/assemble/{script_id}")
async def job_assemble(script_id: str) -> dict:
    """Manually trigger VideoAssembler for a script where all shots are done."""
    from glitch_signal.scheduler.queue import _trigger_assembler
    asyncio.create_task(_trigger_assembler(script_id))
    return {"ok": True, "script_id": script_id}


# ---------------------------------------------------------------------------
# Telegram webhook
# ---------------------------------------------------------------------------

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> Response:
    if not _tg_app:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")

    data = await request.json()
    update = Update.de_json(data, _tg_app.bot)
    await _tg_app.process_update(update)
    return Response(status_code=200)
