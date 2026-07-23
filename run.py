#!/usr/bin/env python3
"""
run.py — GitHub Actions entrypoint for the stock dashboard bot.

Replaces the Render/Flask deployment. Yahoo Finance IP-blocks Render's egress,
so yfinance returns nothing there; GitHub's runner IPs are not blocked. All data
fetching AND the Telegram send now run directly on the runner. There is no HTTP
server anymore — the workflow invokes this once per session:

    python run.py --session {open,close,warm}

Session gating (NYSE calendar + bell-window check) is unchanged from the old
/trigger route — see market_hours.session_status(). Exit code is 0 on a
successful send OR a legitimately-skipped session (weekend/holiday/off-window),
and non-zero only when a send actually fails, so a failed run is a real alert.
"""
import argparse
import logging
import sys

import requests

import config
from data_fetcher import fetch_dashboard_data
from formatter import format_dashboard_messages
from market_hours import session_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("stock_bot")

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


def send_dashboard(session_label: str) -> bool:
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


_LABELS = {"open": "MARKET OPEN", "close": "MARKET CLOSE"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and send the stock dashboard.")
    parser.add_argument(
        "--session",
        required=True,
        choices=["open", "close", "warm"],
        help="Which session to fire. 'warm' is a no-op kept for schedule symmetry.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the market-window/trading-day gate and send now. For manual "
             "testing outside market hours — never used by the scheduled crons.",
    )
    args = parser.parse_args(argv)
    session = args.session

    # 'warm' only existed to pre-warm Render's cold start. A fresh runner has
    # nothing to warm, so it's a successful no-op.
    if session == "warm":
        log.info("warm: no-op (nothing to pre-warm on the runner).")
        return 0

    if args.force:
        log.warning("--force: bypassing session gate, sending %s now.", session)
    else:
        should_send, reason = session_status(session)
        if not should_send:
            # Not a trading day / outside the bell window is expected — not a failure.
            log.info("Skipped %s: %s", session, reason)
            return 0
        log.info("%s session confirmed (%s).", session, reason)

    ok = send_dashboard(_LABELS[session])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
