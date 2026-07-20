# Stock Dashboard Telegram Bot (Render Free-Tier Architecture)

Sends a full dashboard for tracked tickers twice per trading day: at the
open bell and at the close bell. Runs as a free Render Web Service —
no persistent background process required, because Render's free plan
doesn't support Background Workers. Instead, an external free cron
service pings this app's `/trigger` endpoint at the right times, and the
app itself checks the NYSE calendar before deciding whether to actually
send (so weekends/holidays are silently skipped, no config needed).

## Files
| File | Purpose |
|---|---|
| `app.py` | Flask app — `/trigger` endpoint does the check-and-send |
| `market_hours.py` | Stateless NYSE calendar check (trading day? within window of open/close?) |
| `data_fetcher.py` | Pulls all metrics per ticker from Yahoo Finance |
| `formatter.py` | Builds the Telegram message text |
| `config.py` | Loads env vars |
| `Procfile` | Tells Render how to start the app (`gunicorn app:app`) |
| `runtime.txt` | Pins Python to 3.12.9 — pandas 2.2.2 has a prebuilt wheel for this version, avoiding a source-build failure on newer Python |

## Fields covered
1D H/L/Avg, 7D range, 1M range, 52W range, Market Cap, Trailing & Forward
P/E, PEGY (PE / (EPS growth% + div yield%)), EPS (TTM), 1Y analyst target
mean, forward dividend rate & yield, next earnings date, ex-dividend date.

## Setup

### 1. Telegram bot + chat
- Message **@BotFather** → `/newbot` → get `TELEGRAM_BOT_TOKEN`.
- Add the bot to your destination chat, send it any message, then GET
  `https://api.telegram.org/bot<TOKEN>/getUpdates` to read `chat.id`
  (`TELEGRAM_CHAT_ID` — negative number for groups/channels).

### 2. Deploy to Render as a Web Service (not Background Worker)
- Dashboard → **New +** → **Web Service** → connect this repo
- Runtime: **Python 3**
- Build Command: `pip install -r requirements.txt`
- Start Command: leave blank (Render reads `Procfile` automatically) or
  set explicitly to `gunicorn app:app`
- Plan: **Free**
- Environment variables (Environment tab):

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `TICKERS` | `NVDA,PLTR,AVGO` |
| `EXCHANGE_TZ` | `America/New_York` |
| `TRIGGER_SECRET` | any random string you make up — this guards the endpoint |
| `SESSION_WINDOW_MIN` | `20` (optional, default 20) |

Deploy. Note the service URL Render gives you, e.g.
`https://your-app.onrender.com`.

### 3. Set up the external cron pinger (cron-job.org, free)
Render's free plan spins the service down after ~15 min idle; an
incoming HTTP request wakes it (cold start ~30-60s), which is why the
external pinger — not an internal scheduler — drives the schedule.

1. Sign up free at **cron-job.org**.
2. Create job 1 — **Market Open**:
   - URL: `https://your-app.onrender.com/trigger?session=open&key=YOUR_TRIGGER_SECRET`
   - Schedule: daily, **09:25 America/New_York** (fires 5 min before the
     bell — cold start + the app's own window check absorbs the gap)
   - Timezone: set the job's timezone to `America/New_York` so it
     auto-shifts with DST — don't hardcode a fixed UTC time.
3. Create job 2 — **Market Close**:
   - URL: `https://your-app.onrender.com/trigger?session=close&key=YOUR_TRIGGER_SECRET`
   - Schedule: daily, **15:55 America/New_York**
4. Save both. cron-job.org's free tier fires on a best-effort schedule
   (not sub-second precise) — that's exactly what `SESSION_WINDOW_MIN`
   is there to absorb.

### 4. (Optional) Keep-warm pinger
Not required — the cron hits themselves wake the app. Skip this unless
you notice cold-start delays causing missed sends; if so, add a third
cron-job.org job hitting `/` every 10 min during market hours only.

## Verifying it works
- Visit `https://your-app.onrender.com/` → should return `{"status":"ok"}`.
- Manually test a send once, outside the time window, by temporarily
  widening `SESSION_WINDOW_MIN` to a large number (e.g. `600`), hitting
  `/trigger?session=open&key=...` yourself in a browser, confirming the
  Telegram message arrives, then setting `SESSION_WINDOW_MIN` back to 20.
- Check Render's **Logs** tab for `Skipped ... trigger: ...` (window
  miss) vs `... dashboard sent.` (success) after each cron-job.org fire.

## Known limitations of this free-tier design
- **Early-close days** (day after Thanksgiving, etc., ~1x/year): the
  close cron fires at 15:55 ET but the bell was actually ~13:00 ET.
  `session_status()` will report "outside window" and skip — you'd get
  no close dashboard that day. Fix if it matters to you: add a third
  cron-job.org job at the known early-close time, active only on that
  date, or manually trigger the URL that day.
- **No send-history persistence**: if cron-job.org double-fires (retries
  on a slow cold start, for example), you could get a duplicate message
  within the same window. Rare in practice; not handled by design to
  keep this free and stateless (no DB on the free tier).
- **Cold start latency**: first request after idle can take 30-60s.
  `SESSION_WINDOW_MIN=20` gives comfortable slack.

## Upgrading later
If these limitations become a problem, the cleanest fix is Render's
**Background Worker** on the Starter plan ($7/mo) with an internal
APScheduler loop — no external cron dependency, no window-matching
logic needed. Ask if you want that version.
