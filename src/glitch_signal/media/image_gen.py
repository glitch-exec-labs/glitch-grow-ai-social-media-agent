"""AI image generation via fal.ai.

Primary use: LinkedIn image posts (and later Twitter/Instagram) for text brands
that want visual pairing. Generates a PNG from a prompt and returns the local
path; the publisher uploads via upload_post.upload_photos().

Default model is `fal-ai/flux/schnell` — fast (~1-2s) and cheap
(~$0.003/image). Swap via FAL_IMAGE_MODEL in .env. All calls go through a
tenacity retry so transient network/503s don't drop an image.

Outputs land under `{settings.video_storage_path}/images/{brand_id}/` with a
UUID filename. Re-runs never overwrite; each call produces a new file.
"""
from __future__ import annotations

import asyncio
import pathlib
import uuid
from typing import Literal

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from glitch_signal.config import settings

log = structlog.get_logger(__name__)

# fal.ai's FLUX models accept a named aspect ratio. Map our semantic names
# to what the SDK expects. These are the three we actually use for social.
_ASPECT_MAP: dict[str, str] = {
    "1:1":  "square_hd",          # 1024x1024 — LinkedIn default, safe everywhere
    "4:5":  "portrait_4_3",       # LinkedIn/IG portrait
    "16:9": "landscape_16_9",     # Twitter/YouTube thumbnail
}

AspectRatio = Literal["1:1", "4:5", "16:9"]


class ImageGenError(RuntimeError):
    """Raised when fal.ai returns no image or the download fails."""


async def generate_image(
    prompt: str,
    brand_id: str,
    aspect: AspectRatio = "1:1",
) -> pathlib.Path:
    """Generate an image via fal.ai, download it, return the local path.

    Raises ImageGenError on failure. DISPATCH_MODE=dry_run short-circuits with
    a placeholder path that doesn't exist on disk (caller should skip upload
    in dry-run mode anyway).
    """
    s = settings()
    if s.is_dry_run:
        log.info("image_gen.dry_run", brand_id=brand_id, prompt=prompt[:80])
        return pathlib.Path(f"/tmp/dry-run-image-{uuid.uuid4().hex[:8]}.png")

    if not s.fal_api_key:
        raise ImageGenError("FAL_API_KEY is not set")

    out_dir = pathlib.Path(s.video_storage_path) / "images" / brand_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{uuid.uuid4().hex}.png"

    image_url = await _generate_via_fal(prompt, aspect, model=s.fal_image_model)
    await _download(image_url, out_path)

    log.info(
        "image_gen.done",
        brand_id=brand_id,
        path=str(out_path),
        size_kb=out_path.stat().st_size // 1024,
    )
    return out_path


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.HTTPError, asyncio.TimeoutError, ImageGenError)),
)
async def _generate_via_fal(prompt: str, aspect: AspectRatio, model: str) -> str:
    """Call fal.ai, return the image URL. Retries on network/ImageGenError."""
    # Run the sync fal-client call off the event loop so the graph stays
    # responsive even if fal is slow.
    import fal_client

    # fal-client reads FAL_KEY from env; settings loader sets the env var at
    # startup via pydantic_settings, but to be safe we also set it here.
    import os
    if settings().fal_api_key and not os.environ.get("FAL_KEY"):
        os.environ["FAL_KEY"] = settings().fal_api_key

    image_size = _ASPECT_MAP.get(aspect, "square_hd")

    def _run() -> dict:
        return fal_client.run(
            model,
            arguments={
                "prompt": prompt,
                "image_size": image_size,
                "num_images": 1,
            },
        )

    result = await asyncio.to_thread(_run)
    images = result.get("images") or []
    if not images:
        raise ImageGenError(f"fal.ai returned no images for model={model}")

    url = images[0].get("url") if isinstance(images[0], dict) else None
    if not url:
        raise ImageGenError(f"fal.ai image had no URL: {images[0]!r}")
    return url


async def _download(url: str, out_path: pathlib.Path) -> None:
    """Stream-download an image URL to disk."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
