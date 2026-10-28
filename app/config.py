"""
Central config for AI model selection.

Accuracy of the extracted metrics is the whole point of this product, so we
default to Anthropic's highest-capability generally available Opus model for
the paths that directly write data onto the deal:

  MODEL_EXTRACT  - /api/deals/{id}/extract     (pulls metrics from OMs)
  MODEL_VERIFY   - /api/deals/{id}/verify      (forensic audit vs PDFs)

For synthesis and conversational paths we use Sonnet 4.6 - a strong model
that's noticeably faster and cheaper:

  MODEL_MARKET   - /api/deals/{id}/market-research
  MODEL_CHAT     - /api/chat  (deal-analyst chat panel)

Every choice is overridable via environment variable so we can tune cost /
latency without a deploy-and-rebuild cycle:

  MODEL_EXTRACT=claude-opus-4-8
  MODEL_VERIFY=claude-opus-4-8
  MODEL_MARKET=claude-sonnet-4-6
  MODEL_CHAT=claude-sonnet-4-6

If you want cheaper chat, set MODEL_CHAT=claude-haiku-4-5-20251001.
"""

from __future__ import annotations

import os

# Canonical Anthropic model IDs (June 2026 catalogue).
OPUS_48 = "claude-opus-4-8"
SONNET_46 = "claude-sonnet-4-6"
HAIKU_45 = "claude-haiku-4-5-20251001"

PAID_REVIEW_PAUSED_MESSAGE = (
    "Paid AI review is paused until extraction validation is complete. "
    "Document reading, saved analyses, calculations, exports and source lookup remain available."
)


def paid_review_enabled() -> bool:
    return os.getenv("PAID_REVIEW_ENABLED", "1").strip().lower() not in {"0", "false", "no"}


def require_paid_review_enabled() -> None:
    if not paid_review_enabled():
        raise ValueError(PAID_REVIEW_PAUSED_MESSAGE)

# Defaults - highest-accuracy where data correctness matters most.
MODEL_EXTRACT: str = os.getenv("MODEL_EXTRACT", OPUS_48)
MODEL_VERIFY: str = os.getenv("MODEL_VERIFY", OPUS_48)
MODEL_MARKET: str = os.getenv("MODEL_MARKET", SONNET_46)
MODEL_CHAT: str = os.getenv("MODEL_CHAT", SONNET_46)


def describe_models() -> dict[str, str]:
    """Return the active model assignment for each feature - useful for
    logging / health endpoints so an operator can confirm which models
    are actually running in production."""
    return {
        "extract": MODEL_EXTRACT,
        "verify": MODEL_VERIFY,
        "market_research": MODEL_MARKET,
        "chat": MODEL_CHAT,
    }


# --------------------------- environment checks --------------------------- #

def environment_status() -> dict[str, dict]:
    """Report which optional external services are reachable based on env.

    The healthz endpoint surfaces this so an operator (or the dashboard
    itself) can warn that AI-gated features will 503 before the user
    ever clicks the button.
    """
    review_enabled = paid_review_enabled()
    anthropic_ok = bool(os.environ.get("ANTHROPIC_API_KEY")) and review_enabled
    brave_ok = bool(os.environ.get("BRAVE_API_KEY"))
    db_url = os.environ.get("DATABASE_URL") or ""
    is_sqlite = (not db_url) or db_url.startswith("sqlite")

    return {
        "anthropic": {
            "configured": anthropic_ok,
            "paused": not review_enabled,
            "affects": ["extract", "verify"],
            "message": (
                PAID_REVIEW_PAUSED_MESSAGE if not review_enabled else None
                if anthropic_ok
                else "ANTHROPIC_API_KEY is not set - automatic financial extraction and verification are unavailable. Document reading, public context and evidence lookup remain available."
            ),
        },
        "brave_search": {
            "configured": True,
            "affects": [],
            "message": (
                None
                if brave_ok
                else "Public context uses structured Census data and requires no Brave or Anthropic key."
            ),
        },
        "database": {
            "engine": "sqlite" if is_sqlite else "postgres",
            "persistent": bool(db_url) or bool(os.environ.get("DB_DIR")),
            "message": (
                None
                if (db_url or os.environ.get("DB_DIR"))
                else "DB_DIR is not set; SQLite lives in the repo root and will be lost on redeploys. Set DB_DIR=/data with a Railway Volume."
            ),
        },
    }
