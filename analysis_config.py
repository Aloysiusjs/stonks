"""
analysis_config.py — every threshold and weight for the earnings/analysis
add-on lives here, so the scoring is auditable and backtestable in one place.

These numbers are DEFAULTS, not validated signals. Change them once you've
backtested against actual returns. The conviction score is only as meaningful
as these thresholds are.
"""
from __future__ import annotations
import os

DISCLAIMER = "Not financial advice. For educational purposes only."

# ── Fundamental health gates (from yfinance) ─────────────────────────
MIN_REVENUE_YOY = 0.10        # revenueGrowth > 10%
REQUIRE_POSITIVE_FCF = True   # freeCashflow > 0
MAX_DEBT_TO_EQUITY = 200.0    # yfinance reports D/E as a PERCENT (e.g. 45.3 = 0.45x)

# ── Sentiment ────────────────────────────────────────────────────────
SENTIMENT_WINDOW_DAYS = 7     # velocity lookback (limited by news availability)
MAX_HEADLINES = 12            # cap LLM calls per ticker per run (cost control)

# ── Conviction weights (must sum to 1.0) ─────────────────────────────
W_FUNDAMENTAL = 0.45
W_SENTIMENT_LEVEL = 0.30
W_SENTIMENT_VELOCITY = 0.25
assert abs(W_FUNDAMENTAL + W_SENTIMENT_LEVEL + W_SENTIMENT_VELOCITY - 1.0) < 1e-9

# ── Signal bands ─────────────────────────────────────────────────────
BUY_THRESHOLD = 70
AVOID_THRESHOLD = 35

# ── LLM ──────────────────────────────────────────────────────────────
ANTHROPIC_MODEL = "claude-sonnet-5"
# Set ANALYSIS_ENABLED=0 in Render env to ship the base bot without the add-on.
ANALYSIS_ENABLED = os.environ.get("ANALYSIS_ENABLED", "1") == "1"
