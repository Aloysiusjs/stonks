import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _require("TELEGRAM_CHAT_ID")
TICKERS = [t.strip().upper() for t in _require("TICKERS").split(",") if t.strip()]
EXCHANGE_TZ = os.getenv("EXCHANGE_TZ", "America/New_York")
MARKET_CALENDAR = "XNYS"  # NYSE calendar, covers Nasdaq-listed names too for holiday purposes

# Shared secret the external cron pinger must supply — without this, anyone
# who finds your Render URL could spam your Telegram chat with API calls.
TRIGGER_SECRET = _require("TRIGGER_SECRET")

# How many minutes of slack to allow between "now" and the calendar's
# open/close time before treating a ping as off-session and skipping it.
# Keep generous since free-tier cold starts add 30-60s, and cron-job.org
# free tier isn't second-precise.
SESSION_WINDOW_MIN = int(os.getenv("SESSION_WINDOW_MIN", "20"))
