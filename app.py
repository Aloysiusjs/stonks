"""
Free-tier architecture: Render's free Web Services spin down after ~15min
idle and don't run a persistent background scheduler. So instead of an
internal APScheduler loop, this is a plain Flask app with an HTTP endpoint
that an external free cron service (cron-job.org) hits twice a day, at
market open and market close. Each hit is idempotent-ish and self-checks
against the NYSE calendar before sending anything.
"""
import logging

import requests
from flask import Flask, request

import config
from data_fetcher import fetch_dashboard_data
from formatter import format_dashboard_messages
from market_hours import session_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("stock_bot")

app = Flask(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"


def _send_message(text: str) -> bool:
    """Send one Telegram message. Plain text (no parse_mode) so that the
    free-form LLM analysis text and company names containing _ * [ ] can't
    trigger a 400 'can't parse entities' error."""
    resp = requests.post(
        TELEGRAM_API,
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
        timeout=15,
    )
    if not resp.ok:
        log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
        return False
    return True


def send_dashboard(session_label: str):
    rows = []
    for symbol in config.TICKERS:
        try:
            rows.append(fetch_dashboard_data(symbol))
        except Exception as e:
            log.error("Failed to fetch %s: %s", symbol, e)

    if not rows:
        log.warning("No data fetched, skipping send.")
        return False

    # With the analysis add-on on, this returns one message per ticker so each
    # stays under Telegram's 4096-char cap. With ANALYSIS_ENABLED=0 it returns
    # a single combined message. Either way we loop and send each.
    messages = format_dashboard_messages(session_label, rows)

    all_ok = True
    for text in messages:
        if not _send_message(text):
            all_ok = False

    if all_ok:
        log.info("%s dashboard sent (%d message(s)).", session_label, len(messages))
    else:
        log.error("%s dashboard: one or more messages failed to send.", session_label)
    return all_ok


@app.get("/")
def health():
    # Render pings this to confirm the service is alive. Also the URL
    # your keep-warm pinger (if you add one) should hit.
    return {"status": "ok"}, 200


@app.get("/trigger")
def trigger():
    key = request.args.get("key")
    session = request.args.get("session")  # 'open' or 'close'
    if key != config.TRIGGER_SECRET:
        log.warning("Rejected trigger: bad secret.")
        return {"error": "forbidden"}, 403
    if session not in ("open", "close"):
        return {"error": "session must be 'open' or 'close'"}, 400

    should_send, reason = session_status(session)
    if not should_send:
        log.info("Skipped %s trigger: %s", session, reason)
        return {"sent": False, "reason": reason}, 200

    label = "MARKET OPEN" if session == "open" else "MARKET CLOSE"
    sent = send_dashboard(label)
    return {"sent": sent, "reason": reason}, 200


if __name__ == "__main__":
    # Local dev only. On Render, gunicorn runs this (see Procfile).
    app.run(host="0.0.0.0", port=5000, debug=True)
