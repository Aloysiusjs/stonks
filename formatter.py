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


def format_dashboard(session_label: str, rows: list[dict]) -> str:
    """session_label: 'MARKET OPEN' or 'MARKET CLOSE'."""
    lines = [f"*{session_label} DASHBOARD*", "_" * 28]
    for d in rows:
        lines.append(f"\n*{d['symbol']}* ({d['name']}) — {_n(d['price'], prefix='$')}")
        lines.append(f"1D Range: {_n(d['day_low'], prefix='$')} - {_n(d['day_high'], prefix='$')}  |  Avg: {_n(d['day_avg'], prefix='$')}")
        lines.append(f"7D Range: {_n(d['week_low'], prefix='$')} - {_n(d['week_high'], prefix='$')}")
        lines.append(f"1M Range: {_n(d['month_low'], prefix='$')} - {_n(d['month_high'], prefix='$')}")
        lines.append(f"52W Range: {_n(d['fifty2_low'], prefix='$')} - {_n(d['fifty2_high'], prefix='$')}")
        lines.append(f"Mkt Cap: {_cap(d['market_cap'])}")
        lines.append(f"P/E (TTM): {_n(d['trailing_pe'])}  |  Fwd P/E: {_n(d['forward_pe'])}")
        lines.append(f"PEGY: {_n(d['pegy'])}")
        lines.append(f"EPS (TTM): {_n(d['eps'], prefix='$')}")
        lines.append(f"1Y Target Est: {_n(d['target_mean'], prefix='$')}")
        lines.append(f"Fwd Div & Yield: {_n(d['div_rate'], prefix='$')} ({_pct(d['div_yield'])})")
        lines.append(f"Earnings Date: {d['earnings_date'] or 'N/A'}")
        lines.append(f"Ex-Div Date: {d['ex_div_date'] or 'N/A'}")
    return "\n".join(lines)
