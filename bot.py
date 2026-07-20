import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.constants import ParseMode

import config
import scheduler as sched_mod
from data_fetcher import fetch_dashboard_data
from formatter import format_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("stock_bot")

bot = Bot(token=config.TELEGRAM_BOT_TOKEN)


async def send_dashboard(session_label: str):
    rows = []
    for symbol in config.TICKERS:
        try:
            rows.append(fetch_dashboard_data(symbol))
        except Exception as e:
            log.error("Failed to fetch %s: %s", symbol, e)
    if not rows:
        log.warning("No data fetched, skipping send.")
        return
    text = format_dashboard(session_label, rows)
    await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)
    log.info("%s dashboard sent.", session_label)


async def on_open():
    await send_dashboard("MARKET OPEN")


async def on_close():
    await send_dashboard("MARKET CLOSE")


async def main():
    scheduler = AsyncIOScheduler()
    sched_mod.start(scheduler, lambda: asyncio.create_task(on_open()), lambda: asyncio.create_task(on_close()))
    scheduler.start()
    log.info("Bot started. Tracking: %s", ", ".join(config.TICKERS))
    # Keep the process alive
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
