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

# Legacy: shared secret the old Render /trigger route required. The bot now runs
# entirely on the GitHub Actions runner (see run.py) with no public endpoint, so
# this is optional and unused — kept only so an old env that still sets it works.
TRIGGER_SECRET = os.getenv("TRIGGER_SECRET")

# How many minutes of slack to allow between "now" and the calendar's
# open/close time before treating a ping as off-session and skipping it.
# Keep generous since free-tier cold starts add 30-60s, and cron-job.org
# free tier isn't second-precise.
SESSION_WINDOW_MIN = int(os.getenv("SESSION_WINDOW_MIN", "20"))
