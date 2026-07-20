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
OPEN_DELAY_MIN = int(os.getenv("OPEN_DELAY_MIN", "1"))
CLOSE_DELAY_MIN = int(os.getenv("CLOSE_DELAY_MIN", "2"))
MARKET_CALENDAR = "XNYS"  # NYSE calendar, covers Nasdaq-listed names too for holiday purposes
