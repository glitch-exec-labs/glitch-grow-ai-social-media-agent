"""X mention sweeper — find new mentions on our owned accounts and queue
them as CommentReply rows for Discord HITL approval.

Reuses the existing CommentReply table by setting platform="upload_post_x"
so the same approve_reply / veto_reply / Discord embed code works for X
mentions exactly like it works for IG comments.

Cadence: scheduler tick should call sweep_all() every ~15 min. Cursor
state (the last seen mention id per account) is stored implicitly in
the CommentReply rows themselves — we read the highest platform_comment_id
we've already ingested per (brand_id, platform) and pass it as since_id
on the next /mentions call.

What gets queued:
  - Replies *to* one of our tweets (mention.referenced_tweet_id is set
    and points at one of our PublishedPost rows)
  - Pure mentions (someone tagged us in a fresh tweet)

What gets skipped:
  - Mentions from ourselves (own user_id)
  - Empty / retweet-only mentions
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import structlog
from sqlmodel import select

from glitch_signal.db.models import CommentReply
from glitch_signal.db.session import _session_factory
from glitch_signal.integrations.x import Mention, XClient

log = structlog.get_logger(__name__)


# (brand_id, env-prefix-for-user-id) — the user_id to fetch mentions for.
ACCOUNTS = [
    ("glitch_executor", "X_BRAND_USER_ID"),
    ("glitch_founder",  "X_FOUNDER_USER_ID"),
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def sweep_all() -> dict:
    """Run one sweep across both brand and founder X accounts."""
    summary = {"checked": 0, "new": 0, "skipped": 0, "errors": 0}
    for brand_id, env_key in ACCOUNTS:
        user_id = (os.environ.get(env_key) or "").strip()
        if not user_id:
            log.info("x_sweeper.skipped_no_user_id", brand_id=brand_id, env_key=env_key)
            continue
        try:
            stats = await _sweep_account(brand_id, user_id)
        except Exception as exc:
            log.warning(
                "x_sweeper.account_failed",
                brand_id=brand_id, error=str(exc)[:300],
            )
            summary["errors"] += 1
            continue
        for k, v in stats.items():
            summary[k] = summary.get(k, 0) + v
    log.info("x_sweeper.summary", **summary)
    return summary


# ---------------------------------------------------------------------------
# Per-account sweep
# ---------------------------------------------------------------------------

async def _sweep_account(brand_id: str, user_id: str) -> dict:
    client = XClient(brand_id)
    since_id = await _last_seen_id(brand_id)
    mentions = await client.get_mentions(user_id, since_id=since_id, max_results=50)

    stats = {"checked": len(mentions), "new": 0, "skipped": 0}
    for m in mentions:
        # Skip self-mentions (we won't reply to ourselves).
        if m.author_id == user_id:
            stats["skipped"] += 1
            continue
        if not (m.text or "").strip():
            stats["skipped"] += 1
            continue
        ok = await _ensure_comment_reply_row(brand_id=brand_id, mention=m)
        if ok:
            stats["new"] += 1
        else:
            stats["skipped"] += 1
    return stats


async def _last_seen_id(brand_id: str) -> str | None:
    """Return the highest platform_comment_id we've ever stored for this
    brand on X — passed as since_id so we don't re-ingest old mentions.
    Mention ids are sortable as strings (snowflake), so we sort lexically.
    """
    factory = _session_factory()
    async with factory() as session:
        result = await session.execute(
            select(CommentReply.platform_comment_id)
            .where(
                CommentReply.brand_id == brand_id,
                CommentReply.platform == "upload_post_x",
            )
            .order_by(CommentReply.platform_comment_id.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
    return row


async def _ensure_comment_reply_row(*, brand_id: str, mention: Mention) -> bool:
    """Insert a CommentReply row if the mention isn't already tracked.
    Returns True if a new row was created."""
    factory = _session_factory()
    async with factory() as session:
        existing = await session.execute(
            select(CommentReply.id).where(
                CommentReply.platform_comment_id == mention.id,
            )
        )
        if existing.scalar_one_or_none():
            return False
        row = CommentReply(
            id=str(uuid.uuid4()),
            brand_id=brand_id,
            platform="upload_post_x",
            published_post_id=None,
            # mention.referenced_tweet_id is the tweet they replied to —
            # often one of OUR tweets. Either way, we treat the mention
            # itself as the target row and store a pointer to the parent.
            platform_post_id=mention.referenced_tweet_id or mention.id,
            platform_comment_id=mention.id,
            commenter_handle=mention.author_username,
            commenter_name=None,
            comment_text=mention.text,
            comment_created_at=_parse_iso(mention.created_at),
            triage_tier="reply_worthy",  # operator decides via Discord
            status="new",
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(row)
        await session.commit()
    log.info(
        "x_sweeper.mention_queued",
        brand_id=brand_id, mention_id=mention.id,
        author=mention.author_username,
    )
    return True


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
