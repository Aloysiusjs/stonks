import analysis_config as acfg
from formatter_analysis import render as render_analysis


def _n(x, prefix="", suffix="", decimals=2):
    if x is None:
        return "N/A"
    return f"{prefix}{x:,.{decimals}f}{suffix}"


def _cap(x):
    if x is None:
        return "N/A"
    if x >= 1e12:
        return f"${x/1e12:.2f}T"
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    return f"${x:,.0f}"


def _pct(x):
    if x is None:
        return "N/A"
    return f"{x*100:.2f}%"


def _ticker_block(d: dict) -> str:
    """The price/metrics block for a single ticker (no header)."""
    lines = [
        f"*{d['symbol']}* ({d['name']}) — {_n(d['price'], prefix='$')}",
        f"1D Range: {_n(d['day_low'], prefix='$')} - {_n(d['day_high'], prefix='$')}  |  Avg: {_n(d['day_avg'], prefix='$')}",
        f"7D Range: {_n(d['week_low'], prefix='$')} - {_n(d['week_high'], prefix='$')}",
        f"1M Range: {_n(d['month_low'], prefix='$')} - {_n(d['month_high'], prefix='$')}",
        f"52W Range: {_n(d['fifty2_low'], prefix='$')} - {_n(d['fifty2_high'], prefix='$')}",
        f"Mkt Cap: {_cap(d['market_cap'])}",
        f"P/E (TTM): {_n(d['trailing_pe'])}  |  Fwd P/E: {_n(d['forward_pe'])}",
        f"PEGY: {_n(d['pegy'])}",
        f"EPS (TTM): {_n(d['eps'], prefix='$')}",
        f"1Y Target Est: {_n(d['target_mean'], prefix='$')}",
        f"Fwd Div & Yield: {_n(d['div_rate'], prefix='$')} ({_pct(d['div_yield'])})",
        f"Earnings Date: {d['earnings_date'] or 'N/A'}",
        f"Ex-Div Date: {d['ex_div_date'] or 'N/A'}",
    ]
    # Append the analysis block if present. render_analysis() already includes
    # the regulatory disclaimer, so it is NOT added separately here.
    res = d.get("analysis")
    if res is not None:
        lines.append(render_analysis(res))
    return "\n".join(lines)


def format_dashboard(session_label: str, rows: list[dict]) -> str:
    """
    Backward-compatible single-string version. Fine when ANALYSIS_ENABLED=0.
    With analysis on and 3 tickers this can exceed Telegram's 4096-char limit —
    prefer format_dashboard_messages() below in that case.
    session_label: 'MARKET OPEN' or 'MARKET CLOSE'.
    """
    lines = [f"*{session_label} DASHBOARD*", "_" * 28]
    for d in rows:
        lines.append("\n" + _ticker_block(d))
    return "\n".join(lines)


def format_dashboard_messages(session_label: str, rows: list[dict]) -> list[str]:
    """
    Returns a LIST of messages, each safely under Telegram's 4096-char cap.

    - Analysis OFF: one combined message (same as before), returned as a
      single-element list.
    - Analysis ON: one message per ticker (the price+analysis block for a
      single ticker fits comfortably), with the session header on the first.

    Update app.py to loop and sendMessage over this list instead of sending
    one string. See INTEGRATION note at the bottom of this file.
    """
    header = f"*{session_label} DASHBOARD*\n{'_' * 28}"

    if not acfg.ANALYSIS_ENABLED:
        return [format_dashboard(session_label, rows)]

    messages = []
    for i, d in enumerate(rows):
        block = _ticker_block(d)
        block = f"{header}\n\n{block}" if i == 0 else block
        # Hard safety: if a single block still exceeds the cap, split on lines.
        messages.extend(_split_if_needed(block))
    return messages


def _split_if_needed(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts
