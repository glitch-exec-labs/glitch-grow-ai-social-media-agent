# Glitch Social Media Agent

Autonomous social media identity agent for [Glitch Executor](https://glitchexecutor.com).

Mines real shipped artifacts → generates short-form video → publishes to YouTube Shorts / X / Instagram Reels → manages ORM autonomously within hard guardrails.

**This is the agent that maintains Glitch Executor's social presence — built in public so you can run it on your own brand.**

---

## What it does

1. **Scout** — polls GitHub commits, MILESTONES.md diffs, and trading metrics for novel signals
2. **Script + Storyboard** — LLM generates a 60-90s short-form script and breaks it into 5-8 shots
3. **Video generation** — routes each shot to the best video model (Kling 2.0 in Phase 1; Runway, Veo 3, Hailuo in Phase 2)
4. **Assemble** — ffmpeg concatenates shots, applies brand overlay (cobra watermark + neon color grade)
5. **QC** — Gemini 2.5 Pro vision checks brand alignment before publish
6. **Telegram preview** — sends video to founder with 48h veto window; auto-publishes if no veto
7. **ORM** — monitors mentions, classifies tier, auto-responds within hard guardrails, escalates legal/severe

---

## Phase 1 scope

- Platforms: **YouTube Shorts** (live), X/Twitter video (Phase 2), Instagram Reels (Phase 2)
- Video model: **Kling 2.0** (Phase 2 adds Runway Gen-4, Veo 3, Hailuo routing)
- ORM: Twitter mention monitoring + auto-respond (positive, neutral_faq, neutral_technical)
- Approval: Telegram inline keyboard

---

## Stack

```
Python 3.11+
LangGraph          — agent workflow orchestration
LiteLLM            — multi-model LLM routing (Claude Sonnet, Gemini Flash/Pro)
FastAPI + uvicorn  — HTTP server (port 3111)
SQLModel + Alembic — async PostgreSQL
ffmpeg-python      — video assembly
python-telegram-bot — approval UX
Kling 2.0 API      — video generation
```

---

## Quick start

```bash
# 1. Clone + install
git clone https://github.com/glitch-exec-labs/glitch-social-media-agent
cd glitch-social-media-agent
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Configure
cp .env.example .env
# Fill in: KLING_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN_SIGNAL,
#          TELEGRAM_ADMIN_IDS, YOUTUBE_CLIENT_SECRETS_FILE

cp brand.config.example.json brand.config.json
# Edit: watermark_path, competitor_names, model routing

# 3. Database
createdb glitch_signal
alembic upgrade head

# 4. YouTube auth (one-time browser flow)
python -m glitch_signal.platforms.youtube --auth

# 5. Start (dry-run — no real API calls)
DISPATCH_MODE=dry_run uvicorn glitch_signal.server:app --port 3111

# 6. Trigger a scout run
curl -X POST http://127.0.0.1:3111/jobs/scout

# 7. Check health
curl http://127.0.0.1:3111/healthz
```

---

## ORM guardrails

Hard-stop phrases trigger an immediate Telegram alert and zero automated response — no LLM involved, pure rule engine:

- Financial loss mentions (`"lost $"`, `"lost ₹"`, `"money lost"`)
- Regulatory bodies (`SEC`, `SEBI`, `FINRA`)
- Legal threats (`"legal action"`, `"lawsuit"`, `"lawyer"`)
- Return guarantees (`"guarantee"`, `"certain returns"`)

Edit `brand.config.json` → `orm_guardrails.hard_stop_phrases` to update without redeploy.

---

## Telegram commands

```
/status           queue depth, last signal, cost this week
/signals          last 5 discovered signals with novelty score
/preview <id>     re-send a video preview
/approve <id>     publish immediately (skips 48h window)
/veto <id>        cancel a queued post
/orm              last 10 inbound mentions with tier
/orm_approve <id> send a pending ORM response now
/orm_veto <id>    cancel a pending ORM response
```

---

## Cost model

Phase 1 (Kling 2.0 only): ~**$1.75/video** (12 shots × 5s × $0.028/s + LLM)  
Phase 2 (mixed models): ~**$4.00/video** (2 Runway hero shots + 10 Kling shots)  
3 videos/week: ~$21–50/month

---

## Architecture

```
GitHub / Metrics / MILESTONES
         │
      [Scout] ──cron──────────────────────────────────────
         │                                               │
  [ScriptWriter]                                  [ORM Monitor]
         │                                               │
   [Storyboard]                                 [Guardrails check]
         │                                               │
  [VideoRouter]                                  [Classifier]
         │                                               │
[VideoGenerator] ──dispatches VideoJob rows──→  [Responder]
         │       scheduler polls for completion        │
  [VideoAssembler]                              auto-send / escalate
         │
  [QualityCheck]
         │
[TelegramPreview] ──48h veto window──→ [Publisher]
                                   YouTube / X / Instagram
```

LangGraph owns the synchronous reasoning chain (Scout → QC). The scheduler owns all async operations: shot polling, veto windows, ORM review windows, retry backoff.

---

## Deployment (production)

```bash
# systemd service
sudo cp ops/systemd/glitch-signal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now glitch-signal

# nginx (after setting DISPATCH_MODE=live in .env)
sudo cp ops/nginx/signal.glitchexecutor.com.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/signal.glitchexecutor.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## License

MIT — see LICENSE. Brand config (voice prompts, guardrail lists, watermark assets) is private and not included.

---

Built by [Glitch Executor](https://glitchexecutor.com) — algorithmic trading AI platform.
