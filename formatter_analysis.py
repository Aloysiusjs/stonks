"""
formatter_analysis.py — renders an AnalysisResult into a Telegram message
section. Import this from your existing formatter.py and append the returned
block to each ticker's message.

Every rendered block ends with the mandatory regulatory disclaimer.
"""
from __future__ import annotations

import analysis_config as cfg
from earnings_engine import AnalysisResult

_TAG = {"REAL": "🟢", "HYPE": "🟡", "PRICED-IN": "🔵"}


def _pct(x: float | None) -> str:
    return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "n/a"


def render(res: AnalysisResult) -> str:
    q = res.qualitative
    f = res.fundamentals
    b = res.breakdown

    # BUSINESS MODEL
    segs = q.get("segments") or []
    seg_txt = ", ".join(
        f"{s['name']} {s['revenue_pct']}%" for s in segs
        if s.get("name") and s.get("revenue_pct") is not None
    ) or "segments n/a"

    # MOAT
    rivals = q.get("moat_rivals") or []
    disr = q.get("top_disruptor") or {}
    if disr.get("name"):
        pace = ("growing FASTER" if disr.get("growing_faster")
                else "growing slower" if disr.get("growing_faster") is False
                else "pace unclear")
        disr_txt = f"{disr['name']} ({pace})"
    else:
        disr_txt = "n/a"

    # CATALYSTS
    cats = q.get("catalysts") or []
    cat_txt = "\n".join(
        f"  {_TAG.get(c.get('tag',''), '⚪')} {c.get('event','?')} — {c.get('tag','?')}"
        for c in cats
    ) or "  n/a"

    # SENTIMENT line with honest confidence flag
    vel_note = "" if res.velocity_confident else "  ⚠️ low news coverage — velocity unreliable"

    lines = [
        "",
        "━━━━━━━━ ANALYSIS ━━━━━━━━",
        "BUSINESS MODEL",
        f"  {q.get('business_model') or 'n/a'}",
        f"  Segments: {seg_txt}",
        "",
        f"GROWTH TREND: {f.growth_trend()}",
        f"  Rev YoY: {_pct(f.revenue_yoy)} | FCF: "
        f"{'+' if (f.free_cash_flow or 0) > 0 else ''}{_fmt_big(f.free_cash_flow)} | "
        f"D/E: {f.debt_to_equity if f.debt_to_equity is not None else 'n/a'}",
        "",
        f"MOAT — rivals: {', '.join(rivals) if rivals else 'n/a'}",
        f"  #1 disruptor: {disr_txt}",
        "",
        "CATALYSTS (next 12mo)",
        cat_txt,
        "",
        f"CONVICTION: {res.conviction}/100 → {res.signal}",
        f"  fund {b['fundamental']} · sent-lvl {b['sentiment_level']} · "
        f"sent-vel {b['sentiment_velocity']}{vel_note}",
        f"  Biggest risk: {q.get('biggest_risk') or 'n/a'}",
        "",
        cfg.DISCLAIMER,
    ]
    return "\n".join(lines)


def _fmt_big(x: float | None) -> str:
    if not isinstance(x, (int, float)):
        return "n/a"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= div:
            return f"${x/div:.1f}{unit}"
    return f"${x:.0f}"
