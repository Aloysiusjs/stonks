"""
earnings_engine.py — the analysis add-on for the stock dashboard bot.

Design constraints inherited from the existing bot (see PROJECT_CONTEXT.md):
  - Render Free Web Service: short-lived request, ~512MB RAM. No local ML
    models (FinBERT/torch would OOM). Sentiment is done via the Anthropic API.
  - No database. "7-day sentiment velocity" is therefore approximated WITHIN
    a single run by scoring yfinance's recent news and bucketing by date.
    It cannot track drift across days the way a DB-backed version would.
    This limitation is surfaced honestly in the output.
  - yfinance is the only market-data source (free, no key).

What is COMPUTED (deterministic, auditable): fundamental gates, growth trend,
conviction score and its breakdown.
What is INFERRED (LLM over filing/news text): business model, segments, moat,
catalyst REAL/HYPE/PRICED-IN tags, biggest risk, per-headline sentiment.
Treat inferred fields as a research draft, not verified fact.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import analysis_config as cfg


# ─────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────
@dataclass
class Fundamentals:
    revenue_yoy: float | None            # fraction, 0.12 = 12%
    free_cash_flow: float | None
    debt_to_equity: float | None         # yfinance percent form (45.3 = 0.45x)
    yoy_growth_last_4q: list[float] = field(default_factory=list)  # oldest→newest

    def gates(self) -> dict[str, bool]:
        return {
            "revenue_yoy>10%": (self.revenue_yoy or 0) > cfg.MIN_REVENUE_YOY,
            "positive_fcf": (self.free_cash_flow or 0) > 0
                            if cfg.REQUIRE_POSITIVE_FCF else True,
            "debt/equity_ok": (self.debt_to_equity
                               if self.debt_to_equity is not None else 1e9)
                              < cfg.MAX_DEBT_TO_EQUITY,
        }

    def score(self) -> float:
        g = self.gates()
        return round(sum(g.values()) / len(g), 3)   # fraction of gates passed

    def growth_trend(self) -> str:
        g = self.yoy_growth_last_4q
        if len(g) < 2:
            return "INSUFFICIENT DATA"
        deltas = [b - a for a, b in zip(g, g[1:])]
        return "ACCELERATING" if sum(deltas) >= 0 else "DECELERATING"


@dataclass
class AnalysisResult:
    ticker: str
    fundamentals: Fundamentals
    sentiment_level: float               # [-1, 1]
    sentiment_velocity: float            # improvement over window
    velocity_confident: bool             # False when too little news to trust
    conviction: int                      # 0-100
    breakdown: dict
    qualitative: dict                    # LLM dashboard fields
    signal: str


# ─────────────────────────────────────────────────────────────────────
# 1. Fundamentals — from yfinance (deterministic)
# ─────────────────────────────────────────────────────────────────────
def extract_fundamentals(tkr) -> Fundamentals:
    """
    tkr: a yfinance.Ticker object (passed in so this module doesn't own the
    network call and stays unit-testable).
    Field names per yfinance .info schema — verify on first deploy with a
    real ticker, as Yahoo occasionally renames keys.
    """
    info = {}
    try:
        info = tkr.info or {}
    except Exception:
        info = {}

    revenue_yoy = info.get("revenueGrowth")           # already a fraction
    fcf = info.get("freeCashflow")
    dte = info.get("debtToEquity")

    yoy_4q = _quarterly_revenue_yoy(tkr)

    return Fundamentals(
        revenue_yoy=revenue_yoy,
        free_cash_flow=fcf,
        debt_to_equity=dte,
        yoy_growth_last_4q=yoy_4q,
    )


def _quarterly_revenue_yoy(tkr) -> list[float]:
    """
    Compute up to 4 quarters of YoY revenue growth from quarterly financials.
    YoY needs the same quarter a year earlier (4 quarters back), so this needs
    ~8 quarters of data. Returns oldest→newest. Empty list if unavailable.
    """
    try:
        qf = tkr.quarterly_financials     # DataFrame: rows=line items, cols=quarters
        if qf is None or qf.empty:
            return []
        row = None
        for label in ("Total Revenue", "TotalRevenue", "Revenue"):
            if label in qf.index:
                row = qf.loc[label]
                break
        if row is None:
            return []
        # Columns are dated, newest first. Reverse to oldest→newest.
        vals = list(row[::-1].dropna())
        if len(vals) < 5:
            return []
        yoy = []
        for i in range(4, len(vals)):
            prev = vals[i - 4]
            if prev and prev != 0:
                yoy.append(round((vals[i] - prev) / abs(prev), 4))
        return yoy[-4:]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────
# 2. Sentiment — Anthropic API (no local model)
# ─────────────────────────────────────────────────────────────────────
_SENTIMENT_PROMPT = (
    "You are a financial sentiment classifier following FinBERT conventions. "
    "Score each numbered headline on financial sentiment from -1.0 (highly "
    "bearish) to +1.0 (highly bullish); 0.0 is neutral. Judge only financially "
    "material tone (guidance, growth, margins, demand, risk). "
    "Return ONLY a JSON array of objects [{\"i\": int, \"score\": number}], "
    "nothing else.\n\nHEADLINES:\n{items}"
)


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def score_headlines(news: list[dict]) -> list[dict]:
    """
    news: [{"title": str, "ts": epoch_seconds}, ...]
    Returns the same items annotated with "score" in [-1, 1]. One batched LLM
    call (cost control). On any failure, scores default to 0.0 (neutral) so the
    bot degrades instead of crashing.
    """
    items = news[: cfg.MAX_HEADLINES]
    if not items:
        return []
    numbered = "\n".join(f"{i}. {n['title']}" for i, n in enumerate(items))
    try:
        client = _anthropic_client()
        msg = client.messages.create(
            model=cfg.ANTHROPIC_MODEL,
            max_tokens=600,
            messages=[{"role": "user",
                       "content": _SENTIMENT_PROMPT.replace("{items}", numbered)}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        scored = json.loads(raw)
        by_i = {int(o["i"]): max(-1.0, min(1.0, float(o["score"]))) for o in scored}
    except Exception:
        by_i = {}
    for i, n in enumerate(items):
        n["score"] = by_i.get(i, 0.0)
    return items


def sentiment_level_and_velocity(scored_news: list[dict]) -> tuple[float, float, bool]:
    """
    level    = mean of the most-recent-half of scores.
    velocity = mean(recent half) - mean(older half), within the news window.
    confident = we had enough dated items on both sides of the split to trust it.

    Because there's no DB, "window" = whatever news yfinance returned that falls
    inside SENTIMENT_WINDOW_DAYS. Sparse coverage → velocity is not confident.
    """
    if not scored_news:
        return 0.0, 0.0, False

    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.SENTIMENT_WINDOW_DAYS)
    windowed = [n for n in scored_news
                if n.get("ts") and datetime.fromtimestamp(n["ts"], timezone.utc) >= cutoff]
    if not windowed:
        windowed = scored_news  # fall back to whatever we have

    windowed.sort(key=lambda n: n.get("ts", 0))   # oldest→newest
    scores = [n["score"] for n in windowed]

    mid = len(scores) // 2
    recent = scores[mid:] or scores
    older = scores[:mid] or scores
    level = round(sum(recent) / len(recent), 3)
    velocity = round(sum(recent) / len(recent) - sum(older) / len(older), 3)
    confident = len(older) >= 2 and len(recent) >= 2
    return level, velocity, confident


# ─────────────────────────────────────────────────────────────────────
# 3. Qualitative dashboard — LLM over available text (inferred)
# ─────────────────────────────────────────────────────────────────────
_DASHBOARD_PROMPT = """You are an equity analyst. Using the company name, \
business description, and recent headlines below, produce a JSON object with \
EXACTLY these keys:

{
  "business_model": "plain English, 1-2 sentences on how they make money",
  "segments": [{"name": str, "revenue_pct": number|null}],
  "moat_rivals": [str, str, str],
  "top_disruptor": {"name": str, "growing_faster": boolean|null},
  "catalysts": [{"event": str, "tag": "REAL|HYPE|PRICED-IN"}],
  "biggest_risk": "one specific sentence, concrete not vague"
}

Rules:
- Base segment %s on known public reporting; if unsure, use null. Never invent.
- Provide 2-3 segments, top 3 rivals, catalysts over the next ~12 months.
- Output ONLY the JSON.

COMPANY: {name}
DESCRIPTION: {desc}
RECENT HEADLINES:
{headlines}
"""


def generate_dashboard(name: str, description: str, headlines: list[str]) -> dict:
    empty = {"business_model": None, "segments": [], "moat_rivals": [],
             "top_disruptor": None, "catalysts": [], "biggest_risk": None}
    try:
        client = _anthropic_client()
        prompt = (_DASHBOARD_PROMPT
                  .replace("{name}", name or "")
                  .replace("{desc}", (description or "")[:2000])
                  .replace("{headlines}", "\n".join(f"- {h}" for h in headlines[:10]) or "none"))
        msg = client.messages.create(
            model=cfg.ANTHROPIC_MODEL, max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        return {**empty, **data}
    except Exception:
        return empty


# ─────────────────────────────────────────────────────────────────────
# 4. Conviction — transparent scoring matrix (computed)
# ─────────────────────────────────────────────────────────────────────
def conviction(fund: Fundamentals, level: float, velocity: float) -> tuple[int, dict]:
    f = fund.score()                                   # 0..1
    s_level = (level + 1) / 2                           # [-1,1] → [0,1]
    # Map velocity onto 0..1 centered at 0; ±0.5 shift saturates.
    s_vel = max(0.0, min(1.0, (velocity + 0.5) / 1.0))

    raw = (cfg.W_FUNDAMENTAL * f
           + cfg.W_SENTIMENT_LEVEL * s_level
           + cfg.W_SENTIMENT_VELOCITY * s_vel)
    breakdown = {
        "fundamental": round(f, 3),
        "sentiment_level": round(s_level, 3),
        "sentiment_velocity": round(s_vel, 3),
        "weights": {"fundamental": cfg.W_FUNDAMENTAL,
                    "sentiment_level": cfg.W_SENTIMENT_LEVEL,
                    "sentiment_velocity": cfg.W_SENTIMENT_VELOCITY},
    }
    return round(raw * 100), breakdown


def signal_from(score: int) -> str:
    if score >= cfg.BUY_THRESHOLD:
        return "BUY (screen only)"
    if score <= cfg.AVOID_THRESHOLD:
        return "AVOID (screen only)"
    return "NEUTRAL"


# ─────────────────────────────────────────────────────────────────────
# 5. Orchestrator — one call per ticker
# ─────────────────────────────────────────────────────────────────────
def analyze(tkr, ticker: str) -> AnalysisResult:
    """
    tkr: yfinance.Ticker (already constructed by data_fetcher).
    Returns a fully-populated AnalysisResult. Never raises for data gaps;
    missing pieces degrade to neutral/insufficient.
    """
    fund = extract_fundamentals(tkr)

    # News for sentiment + dashboard grounding
    raw_news = []
    try:
        for item in (tkr.news or [])[: cfg.MAX_HEADLINES]:
            # yfinance news item shape varies; support both old and new layouts.
            content = item.get("content", item)
            title = content.get("title") or item.get("title")
            ts = item.get("providerPublishTime")
            if ts is None:
                pub = content.get("pubDate") or content.get("displayTime")
                ts = _parse_iso(pub)
            if title:
                raw_news.append({"title": title, "ts": ts})
    except Exception:
        raw_news = []

    scored = score_headlines(raw_news)
    level, velocity, confident = sentiment_level_and_velocity(scored)

    conv, breakdown = conviction(fund, level, velocity)

    info = {}
    try:
        info = tkr.info or {}
    except Exception:
        pass
    qualitative = generate_dashboard(
        name=info.get("longName") or ticker,
        description=info.get("longBusinessSummary") or "",
        headlines=[n["title"] for n in scored],
    )

    return AnalysisResult(
        ticker=ticker, fundamentals=fund,
        sentiment_level=level, sentiment_velocity=velocity,
        velocity_confident=confident,
        conviction=conv, breakdown=breakdown,
        qualitative=qualitative, signal=signal_from(conv),
    )


def _parse_iso(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None
