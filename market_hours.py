"""
Stateless helpers for checking whether "now" corresponds to a real NYSE
open or close, using pandas_market_calendars (handles weekends, holidays,
and early-close days like the day after Thanksgiving automatically).

No background scheduler here — this module is called synchronously,
inside an HTTP request, by app.py, each time an external cron pinger
hits /trigger.
"""
from datetime import datetime, timedelta

import pandas_market_calendars as mcal

import config

_calendar = mcal.get_calendar(config.MARKET_CALENDAR)


def todays_session():
    """Returns (open_ts, close_ts) in EXCHANGE_TZ for today, or (None, None)
    if today is not a trading day (weekend/holiday)."""
    today = datetime.now().date()
    sched = _calendar.schedule(start_date=today, end_date=today)
    if sched.empty:
        return None, None
    open_ts = sched.iloc[0]["market_open"].tz_convert(config.EXCHANGE_TZ)
    close_ts = sched.iloc[0]["market_close"].tz_convert(config.EXCHANGE_TZ)
    return open_ts, close_ts


def session_status(session: str):
    """
    session: 'open' or 'close'.
    Returns (should_send: bool, reason: str).
    should_send is True only if today is a trading day AND now falls
    within SESSION_WINDOW_MIN minutes of the relevant bell.
    """
    open_ts, close_ts = todays_session()
    if open_ts is None:
        return False, "not a trading day (weekend or holiday)"

    target = open_ts if session == "open" else close_ts
    now = datetime.now(target.tzinfo)
    delta_min = abs((now - target).total_seconds()) / 60

    if delta_min > config.SESSION_WINDOW_MIN:
        return False, (
            f"outside {config.SESSION_WINDOW_MIN}min window "
            f"(target={target.strftime('%H:%M %Z')}, now={now.strftime('%H:%M %Z')})"
        )
    return True, f"ok, target={target.strftime('%H:%M %Z')}"
