"""LiteLLM-routed model selection.

Tiers:
  cheap  → Gemini 2.5 Flash  (novelty scoring, storyboard breakdown)
  smart  → Claude Sonnet 4.6 (script writing, ORM classification)
  heavy  → Gemini 2.5 Pro    (video QC vision, long-form reasoning)
"""
from __future__ import annotations

from dataclasses import dataclass

from glitch_signal.config import settings


@dataclass(frozen=True)
class ModelChoice:
    model: str
    kwargs: dict


def pick(tier: str = "cheap") -> ModelChoice:
    s = settings()
    if tier == "smart":
        return ModelChoice(
            model="claude-sonnet-4-6",
            kwargs={"api_key": s.anthropic_api_key},
        )
    if tier == "heavy":
        if s.vertex_project:
            return ModelChoice(
                model="vertex_ai/gemini-2.5-pro",
                kwargs={
                    "vertex_project": s.vertex_project,
                    "vertex_location": s.vertex_location,
                },
            )
        return ModelChoice(
            model="gemini/gemini-2.5-pro",
            kwargs={"api_key": s.google_api_key},
        )
    # cheap (default)
    if s.vertex_project:
        return ModelChoice(
            model="vertex_ai/gemini-2.5-flash",
            kwargs={
                "vertex_project": s.vertex_project,
                "vertex_location": s.vertex_location,
            },
        )
    return ModelChoice(
        model="gemini/gemini-2.5-flash",
        kwargs={"api_key": s.google_api_key},
    )
