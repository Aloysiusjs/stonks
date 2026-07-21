"""
Pulls all fields needed for the dashboard for a single ticker.
Returns a plain dict; missing fields are set to None so the formatter
can render 'N/A' instead of crashing on names that lack e.g. a dividend.
"""
import logging
from datetime import datetime, timezone

import yfinance as yf

import analysis_config as acfg
from earnings_engine import analyze as run_analysis

log = logging.getLogger(__name__)


def _safe_get(d: dict, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _range_over_period(ticker: yf.Ticker, period: str):
    hist = ticker.history(period=period)
    if hist.empty:
        return None, None
    return round(float(hist["Low"].min()), 2), round(float(hist["High"].max()), 2)


def _fmt_unix_date(ts):
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return None


def _next_earnings_date(ticker: yf.Ticker):
    try:
        cal = ticker.get_earnings_dates(limit=4)
        if cal is None or cal.empty:
            return None
        now = datetime.now(timezone.utc)
        future = cal[cal.index.to_pydatetime() >= now.replace(tzinfo=cal.index.tz)]
        target = future.index.min() if not future.empty else cal.index.max()
        return target.strftime("%Y-%m-%d")
    except Exception as e:
        log.warning("earnings date lookup failed: %s", e)
        return None


def fetch_dashboard_data(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)
    info = {}
    try:
        info = ticker.get_info()
    except Exception as e:
        log.error("get_info failed for %s: %s", symbol, e)

    price = _safe_get(info, "currentPrice", "regularMarketPrice")
    day_low = _safe_get(info, "dayLow", "regularMarketDayLow")
    day_high = _safe_get(info, "dayHigh", "regularMarketDayHigh")
    day_avg = round((day_low + day_high) / 2, 2) if day_low and day_high else None

    week_low, week_high = _range_over_period(ticker, "7d")
    month_low, month_high = _range_over_period(ticker, "1mo")

    fifty2_low = _safe_get(info, "fiftyTwoWeekLow")
    fifty2_high = _safe_get(info, "fiftyTwoWeekHigh")

    market_cap = _safe_get(info, "marketCap")
    trailing_pe = _safe_get(info, "trailingPE")
    forward_pe = _safe_get(info, "forwardPE")
    eps = _safe_get(info, "trailingEps")
    target_mean = _safe_get(info, "targetMeanPrice")

    div_rate = _safe_get(info, "dividendRate")          # forward annual $ dividend
    div_yield = _safe_get(info, "dividendYield")         # forward yield, fraction (e.g. 0.006)
    earnings_growth = _safe_get(info, "earningsGrowth")  # fraction, e.g. 0.25 = 25%

    # PEGY = trailing PE / (EPS growth % + dividend yield %)
    pegy = None
    if trailing_pe and earnings_growth:
        growth_pct = earnings_growth * 100
        yield_pct = (div_yield * 100) if div_yield else 0
        denom = growth_pct + yield_pct
        if denom > 0:
            pegy = round(trailing_pe / denom, 2)

    ex_div_date = _fmt_unix_date(_safe_get(info, "exDividendDate"))
    earnings_date = _next_earnings_date(ticker)

    # ── Analysis add-on ──────────────────────────────────────────────
    # Reuses the SAME `ticker` object above; yfinance caches .info on it,
    # so no extra network round-trip for get_info(). Never let the analysis
    # break the core price message — on any failure we attach None and the
    # formatter simply omits the ANALYSIS block.
    analysis = None
    if acfg.ANALYSIS_ENABLED:
        try:
            analysis = run_analysis(ticker, symbol)
        except Exception as e:
            log.error("[analysis] %s failed: %s", symbol, e)

    return {
        "symbol": symbol,
        "name": _safe_get(info, "shortName", "longName") or symbol,
        "price": price,
        "day_low": day_low,
        "day_high": day_high,
        "day_avg": day_avg,
        "week_low": week_low,
        "week_high": week_high,
        "month_low": month_low,
        "month_high": month_high,
        "fifty2_low": fifty2_low,
        "fifty2_high": fifty2_high,
        "market_cap": market_cap,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "eps": eps,
        "pegy": pegy,
        "target_mean": target_mean,
        "div_rate": div_rate,
        "div_yield": div_yield,
        "earnings_date": earnings_date,
        "ex_div_date": ex_div_date,
        "analysis": analysis,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
