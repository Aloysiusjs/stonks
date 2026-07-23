# Stock Dashboard Telegram Bot — Project Context

> Handoff doc. Read this first. Supersedes any earlier PROJECT_CONTEXT.md.
> Last updated: 2026-07-23

## What this is
A Telegram bot that pushes a stock dashboard (NVDA, PLTR, AVGO) twice per
NYSE trading day — at open and close — with price metrics, fundamentals,
analyst targets, and dividend/earnings data. An "analysis add-on" layers on
LLM-generated qualitative fields plus a computed conviction score.

Repo: https://github.com/Aloysiusjs/stonks (public)
Render service: `stronks.onrender.com` (free Web Service tier)

---

## CURRENT STATE: BLOCKED — mid-migration

The bot deploys and runs, but **sends dashboards full of `N/A`** because the
data source is broken. A migration (Option A below) was agreed but NOT yet
implemented. That is the next task.

---

## THE BLOCKER: Yahoo blocks Render's IPs

`yfinance` fails completely when called from Render. Confirmed from logs:

```
429 Client Error: Too Many Requests for url:
  https://query2.finance.yahoo.com/v10/finance/quoteSummary/NVDA?...
  &crumb=Edge%3A+Too+Many+Requests
get_info failed for NVDA: Expecting value: line 1 column 1 (char 0)
$NVDA: possibly delisted; no price data found (period=7d)
```

Diagnosis: yfinance requests an auth "crumb"; Yahoo returns a rate-limit
error *instead of* a crumb, so yfinance sends the literal string
`Edge: Too Many Requests` as the crumb. Every call then fails. The
`Expecting value: line 1 column 1` errors are JSON-parsing an HTML error
page. `possibly delisted` is the same block hitting history endpoints.

**This is an IP-level block on Render's datacenter range, not user-level
throttling** — it happens on the very first request of the day. Retries,
backoff, and yfinance version bumps do NOT fix it. The same code works fine
from a laptop and from GitHub Actions runners.

### AGREED FIX — Option A: move data fetching to GitHub Actions
GitHub's runner IPs are not blocked by Yahoo (verified: a manual workflow
run succeeded). Plan: fetch data on the Actions runner instead of on Render.
Render's role shrinks dramatically or disappears.

Option B (rejected for now): switch to Finnhub / Alpha Vantage with a real
API key. More robust long-term; requires rewriting `data_fetcher.py` against
a new provider and confirming which of the 13 fields their free tier covers.

**Open design question for the migration:** does Actions post to Telegram
directly (Render becomes vestigial — simplest), or fetch-and-forward to the
Render app (keeps existing formatter/app structure)? Not yet decided.

---

## TWO OTHER CONFIRMED BUGS (fix regardless of data source)

### 1. Gunicorn worker timeout kills the analysis add-on
With `ANALYSIS_ENABLED=1`, the request dies at ~30s:
```
[CRITICAL] WORKER TIMEOUT (pid:68)
Worker (pid:68) was sent SIGKILL! Perhaps out of memory?
```
Traceback ends in `earnings_engine.py:251` → `generate_dashboard` →
`client.messages.create` (Anthropic). Cause: 3 tickers × 2 Anthropic calls
× ~9-13s each = 60-80s, versus gunicorn's default 30s timeout.

Fix: `Procfile` → `web: gunicorn app:app --timeout 120`
Also: guard `earnings_engine.analyze()` to skip Anthropic calls entirely
when `info` is empty — currently it pays for LLM calls that analyze nothing
(two calls returned `200 OK` while analyzing empty data).

Note the 512MB free instance also flagged possible OOM. Watch memory if the
add-on stays on Render.

### 2. Disclaimer disappears when analysis is disabled
The regulatory disclaimer ("Not financial advice. For educational purposes
only.") lives ONLY in `formatter_analysis.render()`. With
`ANALYSIS_ENABLED=0` the sent message has no disclaimer at all — a
compliance gap. Move it into `formatter.py` so it is unconditional.

---

## Architecture (as currently deployed)

```
GitHub Actions (.github/workflows/dashboard.yml)
  → warms Render service, then GET /trigger?session=open|close&key=SECRET
      → app.py (Flask on Render)
        → market_hours.py: trading day? within SESSION_WINDOW_MIN of bell?
          → data_fetcher.py: 13 metrics per ticker (yfinance)  ← BROKEN
            → earnings_engine.py: fundamentals + LLM sentiment + LLM dashboard
              → formatter.py + formatter_analysis.py: build message list
                → requests.post → Telegram sendMessage (one msg per ticker)
```

## Files
| File | Purpose |
|---|---|
| `app.py` | Flask; `/trigger` endpoint, `/` health check; sends msg list |
| `market_hours.py` | Stateless NYSE calendar + time-window check |
| `data_fetcher.py` | 13 metrics per ticker via yfinance + calls analysis |
| `formatter.py` | Base message text; `format_dashboard_messages()` → list |
| `analysis_config.py` | All thresholds/weights + `ANALYSIS_ENABLED` kill switch |
| `earnings_engine.py` | Fundamentals, LLM sentiment, LLM dashboard, conviction |
| `formatter_analysis.py` | Renders the ANALYSIS block (+ disclaimer) |
| `config.py` | Loads env vars, raises if a required one is missing |
| `Procfile` | `web: gunicorn app:app` (NEEDS `--timeout 120`) |
| `runtime.txt` | Pins Python 3.12.9 — see note below |

**`runtime.txt` vs `.python-version`:** an earlier note said Render dropped
`runtime.txt` support in favour of `.python-version`. The repo still has only
`runtime.txt`, and builds ARE succeeding on Python 3.12.9 (confirmed in build
logs). Leave it alone unless a build breaks; if it does, add `.python-version`
containing `3.12.9` BEFORE deleting `runtime.txt`.

## Env vars (Render Environment tab)
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TICKERS=NVDA,PLTR,AVGO`,
`EXCHANGE_TZ=America/New_York`, `TRIGGER_SECRET`, `SESSION_WINDOW_MIN=20`,
`ANTHROPIC_API_KEY`, `ANALYSIS_ENABLED=1`

`SESSION_WINDOW_MIN=600` is the temporary value for testing sends outside
market hours. Always restore to `20`.

GitHub repo secret: `TRIGGER_SECRET` (must match Render's value).

## Scheduling — GitHub Actions (cron-job.org is DELETED, do not resurrect)
`.github/workflows/dashboard.yml`, four weekday triggers, all UTC:
| UTC | ET (EDT) | Action |
|---|---|---|
| 13:15 | 09:15 | warm only |
| 13:25 | 09:25 | warm + **open trigger** |
| 19:45 | 15:45 | warm only |
| 19:55 | 15:55 | warm + **close trigger** |

**GitHub Actions cron is UTC-only and ignores DST.** When the US returns to
EST (~Nov), add 1 hour to all four times.

---

## Solved problems — do not re-litigate these

1. **Pandas build failure**: Render defaulted to Python 3.14, no pandas
   wheel. Fixed by pinning 3.12.9.
2. **Free plan has no Background Workers**: hence Flask + external trigger,
   not an internal APScheduler loop.
3. **cron-job.org could never work**: its max request timeout is **30s**, but
   a Render free-tier cold start takes **~47s**. Every ping was abandoned
   mid-boot, producing a confusing sequence of `429
   hibernate-rate-limited`, then `503`, then `503 no-server` headers. Much
   time was lost theorising about Render's edge throttling. **The actual
   cause was the timeout ceiling.** Replaced with GitHub Actions, which has
   no such cap. Lesson: check a tool's hard limits before reasoning about
   its error messages.
4. **Instance hours are NOT a constraint**: usage was 1.68/750 hrs. An
   all-day 10-min keep-warm would consume ~744/750 — avoid that if a second
   Render service is ever added, but it was never the failure cause.
5. **Telegram 4096-char limit**: `format_dashboard_messages()` returns a LIST
   (one message per ticker); `app.py` loops and sends each.
6. **Telegram Markdown parse errors**: `parse_mode` was REMOVED deliberately.
   LLM-generated text contains `_ * [ ]` which breaks legacy Markdown. Send
   plain text. Do not add `parse_mode` back.

## Design decisions worth preserving
- `ANALYSIS_ENABLED=0` kill switch: ships the base bot if the add-on breaks.
- Analysis wrapped in try/except in `data_fetcher.py`; failure attaches
  `None` and the formatter omits the block — never breaks price messages.
- Reuse the same `yfinance.Ticker` object across metrics + analysis (its
  `.info` is cached per-object, avoiding duplicate network calls).
- **No local ML models.** FinBERT/torch (~2GB) would OOM the 512MB free
  instance. Sentiment goes through the Anthropic API instead.
- All thresholds/weights live in `analysis_config.py` for auditability.
- COMPUTED (deterministic, trustworthy): fundamental gates, growth trend,
  conviction score + breakdown.
  INFERRED (LLM, treat as research draft): business model, segment %s, moat,
  catalyst REAL/HYPE/PRICED-IN tags, biggest risk, headline sentiment.

## Known limitations (accepted by design)
- **Sentiment velocity is weak**: no DB on free tier, so the 7-day window is
  computed within a single run from whatever news the source returns. No
  cross-day memory. Flagged as unreliable in the message when coverage is
  thin.
- **Conviction thresholds are unvalidated defaults** (revenue YoY >10%, D/E,
  the three weights). Not backtested against returns. A backtesting harness
  was offered but never built.
- **Early-close days** (~1x/year): close trigger fires at the usual time but
  the bell was hours earlier; skipped as "outside window".
- **No send-history persistence**: a double-fire could duplicate a message.

## Working style
Prefers explicit numbered steps, confirms each step's output before moving
on, reports exact error messages verbatim. Validates logic offline with
mocked data before deploying. Modular file structure maintained deliberately.
