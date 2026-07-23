# Stock Dashboard Telegram Bot (GitHub Actions Architecture)

Sends a full dashboard for tracked tickers twice per trading day: at the
open bell and at the close bell. The **entire** bot — fetch, format,
optional earnings analysis, and Telegram send — runs on a **GitHub Actions**
runner. There is no server and no public endpoint.

**Why not Render?** Yahoo Finance IP-blocks Render's egress, so yfinance
returned nothing there and every dashboard came back full of `N/A`. GitHub's
runner IPs are not blocked, so the data fetch has to happen on the runner.
Once all Yahoo access lives on the runner, the runner may as well post to
Telegram directly — so Render was removed entirely.

The workflow's cron drives the schedule, and the bot still checks the NYSE
calendar before sending (weekends/holidays/off-window fires are silently
skipped, no config needed).

## Files
| File | Purpose |
|---|---|
| `.github/workflows/dashboard.yml` | Cron + manual triggers; sets up Python and runs `run.py` |
| `run.py` | CLI entrypoint — gates on the session, fetches, formats, and sends |
| `market_hours.py` | Stateless NYSE calendar check (trading day? within window of open/close?) |
| `data_fetcher.py` | Pulls all metrics per ticker from Yahoo Finance |
| `formatter.py` | Builds the Telegram message text (appends the regulatory disclaimer) |
| `formatter_analysis.py` | Renders the optional earnings-analysis block |
| `earnings_engine.py` | Optional analysis add-on (fundamentals + Anthropic sentiment/qualitative) |
| `analysis_config.py` | Thresholds, weights, model, and `ANALYSIS_ENABLED` toggle |
| `config.py` | Loads env vars |

## Fields covered
1D H/L/Avg, 7D range, 1M range, 52W range, Market Cap, Trailing & Forward
P/E, PEGY (PE / (EPS growth% + div yield%)), EPS (TTM), 1Y analyst target
mean, forward dividend rate & yield, next earnings date, ex-dividend date.
With the analysis add-on on, each ticker also gets a business-model / moat /
catalysts / conviction block.

## Setup

### 1. Telegram bot + chat
- Message **@BotFather** → `/newbot` → get `TELEGRAM_BOT_TOKEN`.
- Add the bot to your destination chat, send it any message, then GET
  `https://api.telegram.org/bot<TOKEN>/getUpdates` to read `chat.id`
  (`TELEGRAM_CHAT_ID` — negative number for groups/channels).

### 2. Configure GitHub secrets & variables
In the repo: **Settings → Secrets and variables → Actions**.

**Secrets** (Secrets tab):

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `TICKERS` | e.g. `NVDA,PLTR,AVGO` |
| `ANTHROPIC_API_KEY` | required only if the analysis add-on is on |

**Variables** (Variables tab, optional):

| Variable | Value |
|---|---|
| `ANALYSIS_ENABLED` | `0` to ship the base bot without the LLM add-on (defaults to on) |

`EXCHANGE_TZ` and `SESSION_WINDOW_MIN` have sensible defaults
(`America/New_York`, `20`); set them as variables/env only to override.

### 3. Schedule
Scheduling is already defined in `.github/workflows/dashboard.yml` via `cron`.
GitHub Actions cron is **UTC only and does not observe DST** — the times are
set for EDT (summer). When the US switches to EST (~Nov–Mar), add one hour to
each UTC time as noted in the workflow comments. The bot's own
`session_status()` window check is the safety net either way, so a small cron
drift just gets absorbed.

## Verifying it works
- **Manual run:** repo → **Actions** → *Stock dashboard triggers* → **Run
  workflow** → pick `open` → confirm a dashboard arrives in Telegram and the
  run log shows real values (not `N/A`) plus `... dashboard sent`.
- **Off-hours behavior:** running `open`/`close` outside the bell window logs
  `Skipped open: outside 20min window ...` and exits cleanly — no message.
- **Local dry run** (needs Yahoo-reachable network + the secrets as env vars):
  `pip install -r requirements.txt` then `python run.py --session open`.
- The run exits non-zero only when a send actually fails, so a red run in the
  Actions tab is a real alert (and emails you by default).

## Known limitations
- **GitHub Actions cron is best-effort** and can be delayed several minutes
  under load. `SESSION_WINDOW_MIN=20` absorbs the drift; the warm-up crons
  further reduce the chance of a missed window.
- **DST is manual:** update the UTC cron times twice a year (see workflow
  comments). The window check prevents an off-time send, but a badly-timed
  cron could fall outside the window and skip.
- **Early-close days** (day after Thanksgiving, etc., ~1×/year): the close
  cron fires at 15:55 ET but the bell was ~13:00 ET, so `session_status()`
  reports "outside window" and skips. Manually run the workflow that day if
  you want a close dashboard.
- **No send-history persistence:** if a run somehow fires twice in the same
  window you could get a duplicate message. Rare; not handled by design to
  keep the bot stateless.
