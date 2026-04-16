"""Central configuration for Glitch Social Media Agent.

All settings are loaded from .env (or environment variables).
Call settings() anywhere — the result is cached after first load.
"""
from __future__ import annotations

import json
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Databases ---
    signal_db_url: str = "postgresql+asyncpg://signal:changeme@127.0.0.1:5432/glitch_signal"
    # Read-only access to glitchexecutor DB for Phase 2 Scout
    glitch_ro_url: str = ""

    # --- LLMs ---
    anthropic_api_key: str = ""
    google_api_key: str = ""
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    # --- Video models ---
    kling_api_key: str = ""
    kling_api_url: str = "https://api.klingai.com"
    runway_api_key: str = ""    # Phase 2
    veo_api_key: str = ""       # Phase 2
    hailuo_api_key: str = ""    # Phase 2

    # --- Platforms (Phase 1: YouTube) ---
    youtube_client_secrets_file: str = "credentials/youtube_client_secrets.json"
    youtube_channel_id: str = ""
    # Phase 2
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""
    twitter_bearer_token: str = ""
    ig_access_token: str = ""
    ig_user_id: str = ""

    # --- Telegram ---
    telegram_bot_token_signal: str = ""
    telegram_admin_ids: str = ""  # csv of int ids, e.g. "6280075826,123456"

    # --- Storage ---
    video_storage_path: str = "/var/lib/glitch-signal/videos"

    # --- Runtime ---
    public_base_url: str = "https://signal.glitchexecutor.com"
    dispatch_mode: str = "live"   # dry_run | live
    log_level: str = "INFO"
    scheduler_tick_ms: int = 30_000
    scheduler_stuck_after_ms: int = 300_000   # 5 min

    # --- Scout ---
    github_token: str = ""
    github_org: str = "glitch-exec-labs"
    github_repos: str = ""  # csv of repo names; empty = all org repos

    # --- Brand ---
    brand_config_path: str = "brand.config.json"

    # --- Retry windows (ms) ---
    publish_retry_1_ms: int = 1_800_000   # 30 min
    publish_retry_2_ms: int = 7_200_000   # 2 h
    orm_review_window_s: int = 7_200      # 2 h

    @property
    def admin_telegram_ids(self) -> set[int]:
        out: set[int] = set()
        for raw in (self.telegram_admin_ids or "").split(","):
            raw = raw.strip()
            if raw.isdigit():
                out.add(int(raw))
        return out

    @property
    def github_repo_list(self) -> list[str]:
        if not self.github_repos:
            return []
        return [r.strip() for r in self.github_repos.split(",") if r.strip()]

    @property
    def is_dry_run(self) -> bool:
        return self.dispatch_mode.strip().lower() == "dry_run"


@lru_cache
def settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Brand config (loaded once from brand.config.json)
# ---------------------------------------------------------------------------

_brand_config: dict | None = None


def brand_config() -> dict:
    global _brand_config
    if _brand_config is None:
        import pathlib

        path = pathlib.Path(settings().brand_config_path)
        if path.exists():
            _brand_config = json.loads(path.read_text())
        else:
            _brand_config = _default_brand_config()
    return _brand_config


def _default_brand_config() -> dict:
    return {
        "brand": {
            "name": "Glitch Social Media Agent",
            "accent_color": "#00ff88",
            "base_color": "#0a0a0f",
            "watermark_path": "assets/brand/mascot-128.png",
            "voice": "technical, direct, no marketing hype, no emoji walls",
        },
        "video_model_routing": {
            "phase": 1,
            "model_map": {
                "cinematic": "kling_2",
                "realistic": "kling_2",
                "text_in_video": "kling_2",
                "fast": "kling_2",
            },
        },
        "orm_guardrails": {
            "hard_stop_phrases": [
                "loss",
                "money lost",
                "lost $",
                "lost ₹",
                "SEC",
                "SEBI",
                "FINRA",
                "regulatory",
                "illegal",
                "guarantee",
                "promise",
                "certain returns",
                "lawyer",
                "legal action",
                "lawsuit",
            ],
            "competitor_names": [],
            "auto_respond_tiers": ["positive", "neutral_faq", "neutral_technical"],
            "review_window_seconds": {"negative_mild": 7200},
            "escalate_tiers": ["negative_severe", "legal_flag"],
            "ignore_tiers": ["spam"],
            "min_confidence_threshold": 0.7,
        },
        "platforms": {
            "youtube": {
                "privacy_status": "public",
                "default_tags": ["shorts", "algotrading", "tradingbot", "glitchexecutor"],
                "category_id": "28",
            }
        },
    }
