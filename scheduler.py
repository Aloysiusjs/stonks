"""
Each day at 06:00 exchange-time, look up today's actual open/close
timestamps from the NYSE calendar (handles holidays + early closes,
e.g. day after Thanksgiving) and schedule two one-off jobs for that day.
If the market is closed today, nothing gets scheduled.
"""
import logging
from datetime import datetime, timedelta

import pandas_market_calendars as mcal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

import config

log = logging.getLogger(__name__)
_calendar = mcal.get_calendar(config.MARKET_CALENDAR)


def _todays_session():
    today = datetime.now().date()
    sched = _calendar.schedule(start_date=today, end_date=today)
    if sched.empty:
        return None, None
    open_ts = sched.iloc[0]["market_open"].tz_convert(config.EXCHANGE_TZ)
    close_ts = sched.iloc[0]["market_close"].tz_convert(config.EXCHANGE_TZ)
    return open_ts, close_ts


def plan_today(scheduler: AsyncIOScheduler, on_open, on_close):
    open_ts, close_ts = _todays_session()
    if open_ts is None:
        log.info("Not a trading day, no jobs scheduled.")
        return

    open_fire = open_ts + timedelta(minutes=config.OPEN_DELAY_MIN)
    close_fire = close_ts + timedelta(minutes=config.CLOSE_DELAY_MIN)

    scheduler.add_job(on_open, DateTrigger(run_date=open_fire), id="open_dashboard", replace_existing=True)
    scheduler.add_job(on_close, DateTrigger(run_date=close_fire), id="close_dashboard", replace_existing=True)
    log.info("Scheduled today: open=%s close=%s", open_fire, close_fire)


def start(scheduler: AsyncIOScheduler, on_open, on_close):
    # Plan immediately on startup (covers same-day restarts)
    plan_today(scheduler, on_open, on_close)
    # Re-plan every day at 06:00 exchange time for the next session
    scheduler.add_job(
        lambda: plan_today(scheduler, on_open, on_close),
        "cron",
        hour=6,
        minute=0,
        timezone=config.EXCHANGE_TZ,
        id="daily_planner",
        replace_existing=True,
    )
