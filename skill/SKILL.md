---
name: tjl-live-scanner
description: "Use when running or scheduling US-market TJL live scans, explaining TJL entry/exit rules, posting scan results to Telegram/Discord, or modifying scanner parameters (watchlist, ATR multipliers, EMA periods). Drives the existing /Users/jaydensmac/.openclaw/workspace/tjl_live_us.py script — does not re-implement it."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [trading, us-market, tjl, scanner, yfinance, ema, telegram]
    related_skills: []
---

# TJL Live Scanner (US Market)

## Overview

TJL = "Trend-Join-Long" — a long-entry strategy for US equities. **The name refers to TWO distinct strategies** that share a PMH check but differ elsewhere:

| Variant | Daily condition | Intraday condition | Origin |
|---|---|---|---|
| **Trend Join Long** (HumbledTrader) | `curr_px > prev_daily_high AND prev_daily_close > SMA200` | `curr_px > PMH AND curr_px > today's HOD` | [humbledtrader.com](https://www.humbledtrader.com/blog/connect-claude-to-tradingview-mcp/) — real-time via TradingView |
| **Original TJL** (openclaw legacy) | `EMA9 > EMA20 > EMA50` (bullish stack) | `price within 0.2% of EMA9` (pullback) | Local file `~/.openclaw/workspace/tjl_live_us.py` — yfinance |

Three scripts cover these:
- `~/.openclaw/workspace/tjl_live_us_tv.py` — **primary**, uses TV MCP for real-time data + HumbledTrader recipe
- `~/.openclaw/workspace/tjl_live_us.py` — legacy yfinance, EMA stack + pullback
- `~/.openclaw/workspace/tjl_live_us_itick.py` — legacy iTick, same EMA stack + pullback

This skill is the **Hermes-side playbook**: how to invoke the right script, interpret its output, and deliver to the user's Telegram (already configured for chat `8370185160`).

## When to Use

- User asks to **run a TJL scan** ("scan US market", "TJL signals", "what's setting up", "check the watchlist")
- User asks to **schedule scans** ("scan every 30s during market hours", "send me results at open")
- User asks to **modify scanner parameters** ("add TICKER to the watchlist", "tighten ATR stop to 1.2×", "use 5-min EMA instead of daily")
- User asks to **explain the strategy** ("what is TJL?", "show me the entry rules")
- User asks to **post results to Telegram/Discord**

**Don't use for:**
- HK market scans (different script, different file)
- Backtesting historical TJL signals (use `tjl_backtest.py` in the same openclaw repo instead — separate concern)
- Non-yfinance data sources or non-US markets (the script is hard-coded for Yahoo Finance + US tickers)

## The Strategy (encode this verbatim)

### Entry — all three must be true

1. **Bullish EMA stack:** `EMA9 > EMA20 > EMA50` on daily bars
2. **Pullback to EMA9:** current price within ±0.2% of EMA9 (`NEAR_EMA_PCT = 0.002`)
3. **Above PMH:** price > max(prior_day_high, today's_premarket_high) + $0.70 buffer

### Exit

- **Stop Loss:** `price − 1.5 × ATR(14)`
- **Take Profit:** `price + 3.0 × ATR(14)`
- Fixed **R:R = 1:2** (TP multiple / SL multiple)

### Regime filter

- Compute SPY & QQQ daily direction (close vs previous close)
- If either is down → regime = **BEARISH** → scan still runs but `signals` are flagged for review
- If both up → regime = **BULLISH** → signals are clean

### Constants (for reference, all in `tjl_live_us.py`)

| Constant | Value | Purpose |
|---|---|---|
| `PMH_BUF` | `0.70` | $ buffer above PMH for entry |
| `ATR_SL` | `1.5` | Stop-loss ATR multiplier |
| `ATR_TP` | `3.0` | Take-profit ATR multiplier |
| `ATR_PERIOD` | `14` | ATR lookback |
| `NEAR_EMA_PCT` | `0.002` | 0.2% pullback zone |
| `SCAN_INTERVAL` | `30` | Seconds between scans in continuous mode |

## The Scripts

Three implementations exist. **The TradingView MCP variant is the primary recommendation** as of 2026-08-03 — it follows HumbledTrader's Trend Join Long recipe (SMA200 + breakout) and uses real-time data from your existing paid TV subscription.

| Script | Data source | Latency | Cost | Strategy | Best for |
|---|---|---|---|---|---|
| `~/.openclaw/workspace/tjl_live_us_tv.py` | TradingView Desktop via `tv` CLI | Real-time | Free (uses paid TV sub) | **Trend Join Long** (SMA200 + PMH breakout) — HumbledTrader recipe | Default — small/curated watchlist (3-20 tickers), real-time, no rate limits |
| `~/.openclaw/workspace/tjl_live_us.py` | yfinance | 15-min delayed | Free | **Legacy EMA stack** (EMA9/20/50 + pullback) — original openclaw script | When TV isn't running; large watchlists (S&P 500, etc.) |
| `~/.openclaw/workspace/tjl_live_us_itick.py` | iTick REST (`api.itick.io`) | Real-time | Free tier = 5 calls/min | Legacy EMA stack (same as yfinance) | Small watchlists when TV isn't available; real-time via REST |

**Two different strategies under the same "TJL" name** — they share PMH as a check but diverge everywhere else. Be explicit about which one you mean.

### TradingView MCP variant (primary)

| | |
|---|---|
| **Path** | `/Users/jaydensmac/.openclaw/workspace/tjl_live_us_tv.py` |
| **Default watchlist** | 3 tickers (AMD, NVDA, MU) — matches HumbledTrader demo |
| **Strategy** | SMA200 + breakout (Trend Join Long, HumbledTrader recipe) |
| **CLI** | `tv` (installed at `~/.local/bin/tv` via `npm link`) |
| **Prerequisites** | TradingView Desktop running with `--remote-debugging-port=9222`, an active chart tab (not welcome screen), Extended Hours enabled for PMH data |
| **Env overrides** | `US_TICKERS=AMD,NVDA,TSLA` (custom watchlist), `--tickers` flag, `--continuous` for looping |
| **Output files** | `~/tjl_watchlist_<YYYY-MM-DD>_<HHMM>ET.json` |
| **Rate limit** | None — but per-ticker cost is ~25s due to chart switching |

**Why this is now the primary recommendation:**
1. Uses your paid TV subscription (already running)
2. Real-time data (no 15-min delay, no free-tier rate limits)
3. Matches the recipe in the article the user pointed to
4. Per-ticker cost is acceptable for 3-20 name curated lists

**Don't use for S&P 500** — 503 tickers × 25s = 3.5 hours. Use yfinance instead.

### yfinance variant (legacy — keep, don't delete)

| | |
|---|---|
| **Path** | `/Users/jaydensmac/.openclaw/workspace/tjl_live_us.py` |
| **Strategy** | EMA9/20/50 stack + 0.2% pullback (original) |
| **Default watchlist** | 45 US tickers |
| **Use when** | TV isn't running, OR you want to scan >50 tickers |

### How to invoke from Hermes

**⚠️ Python env caveat:** system `python3` is 3.9 with broken numpy, and the Hermes venv's numpy is compiled for 3.11. The script works under system Python 3.9 (it has its own `yfinance` install there). Use the same interpreter the user already uses for this script — never reach into the Hermes venv or call plain `python3` from a fresh shell expecting yfinance to work.

The user's existing openclaw workflow already runs this script successfully. **Ask the user how they normally run it** (the right command is whatever their openclaw supervisor uses — likely a `launchd` plist or an openclaw runtime invocation). Don't guess at the interpreter; the script's deps may not be installed in every Python on the box.

**Quick probe** to see what works on this machine:

```bash
# Does the script's interpreter still work?
/usr/bin/python3 -c "import yfinance, pandas, numpy; print('ok')"

# Does the script run end-to-end (one-shot, fast)?
# Replace <PY> with whichever of the above succeeded:
<PY> /Users/jaydensmac/.openclaw/workspace/tjl_live_us.py 2>&1 | head -40
```

If neither works, fix the env **before** promising the user results — see `references/python-env.md`.

### Common invocations

```bash
# One-shot scan (default watchlist)
<PY> ~/.openclaw/workspace/tjl_live_us.py

# Continuous loop, custom interval
<PY> ~/.openclaw/workspace/tjl_live_us.py --continuous --interval 60

# Custom tickers via env (no script edit)
US_TICKERS=AAPL,MSFT,NVDA,TSLA <PY> ~/.openclaw/workspace/tjl_live_us.py

# Discord post on completion
DISCORD_WEBHOOK_HK_TJL='https://discord.com/api/webhooks/...' \
  <PY> ~/.openclaw/workspace/tjl_live_us.py
```

### iTick (real-time) invocations

```bash
# Token must be in env (already in ~/.hermes/.env)
<PY> ~/.openclaw/workspace/tjl_live_us_itick.py                  # default 45-ticker scan
US_TICKERS=AAPL,TSLA,NVDA \
  <PY> ~/.openclaw/workspace/tjl_live_us_itick.py                # small custom set
<PY> ~/.openclaw/workspace/tjl_live_us_itick.py --continuous     # loop, free tier = ~18min/scan
```

**Rate-limit caveat:** free iTick plan = 5 calls/min. Default scan uses 90 calls (45 tickers × 2). On the free tier, expect a full default scan to take ~18 minutes due to automatic 429 backoff. For real-time continuous monitoring, upgrade to Base ($79/mo) for 120 calls/min.

## Delivery to Telegram (the user already has a Telegram gateway)

The script only delivers to Discord via webhook. Hermes can deliver scan output to the user's Telegram bot (chat `8370185160`) using `hermes send`. Two patterns:

### Pattern A — re-deliver after the run

```bash
# 1. Run the scan and capture the JSON
<PY> ~/.openclaw/workspace/tjl_live_us.py > /tmp/tjl_run.log 2>&1

# 2. Parse signals and send a formatted Telegram message
python3 - <<'PY'
import json, glob, os
latest = max(glob.glob(os.path.expanduser("~/tjl_live_us_*.json")), key=os.path.getmtime)
d = json.load(open(latest))
lines = [
    f"📊 *TJL Scan* — {d['scanned_at']}",
    f"Regime: *{d['regime']}*",
    f"Signals: *{len(d['signals'])}*",
]
if d["signals"]:
    lines += ["", "```", f"{'Ticker':<8} {'Price':>8} {'R:R':>5}  EMA9   EMA20  EMA50", "-" * 50]
    for s in sorted(d["signals"], key=lambda x: -x["rr_ratio"]):
        lines.append(f"{s['ticker']:<8} {s['price']:>8.2f} {s['rr_ratio']:>5.1f}  {s['e9']:>6.2f}  {s['e20']:>6.2f}  {s['e50']:>6.2f}")
    lines.append("```")
print("\n".join(lines))
PY | hermes send --to telegram -
```

### Pattern B — scheduled cron job (recommended for "scan every X minutes during market hours")

Schedule with `cronjob` so results arrive on Telegram without the agent being awake:

```python
cronjob(action="create",
    name="TJL US scan every 5min during market hours",
    schedule="*/5 9-16 * * mon-fri ET",   # ET; cron uses server local time — see note below
    prompt="""Run /Users/jaydensmac/.openclaw/workspace/tjl_live_us.py once.
Parse the resulting ~/tjl_live_us_<today>.json and deliver a formatted
summary (signals table + regime + count) to the user's Telegram home channel
using hermes send. If regime == BEARISH, lead with a ⚠️ banner.
If no signals, send a single-line 'no signals' notice so the user knows
the scanner ran.""",
    enabled_toolsets=["terminal"])
```

**Schedule caveat:** cron schedules are interpreted in **server local time**. The user's macOS reports as `ET` (America/New_York) so `*/5 9-16 * * mon-fri` matches US market hours 9:30-16:00 ET on weekdays when the machine is awake. If market hours drift (DST), revisit.

## Reading output

The script writes `~/tjl_live_us_<YYYY-MM-DD>.json` after every scan:

```json
{
  "scanned_at": "2026-08-03 15:42:14 ET",
  "source": "Yahoo Finance",
  "regime": "BULLISH",
  "signals": [
    {
      "ticker": "NVDA", "name": "NVIDIA", "price": 124.85,
      "prev_close": 122.10,
      "e9": 124.61, "e20": 121.30, "e50": 115.40,
      "atr": 4.21,
      "pmh": 123.95,
      "sl": 118.54, "tp": 137.48, "rr_ratio": 2.0,
      "stack_ok": true, "near_ema_ok": true, "above_pmh_ok": true
    }
  ],
  "debug": ["META: !nearEMA !abovePMH", ...]
}
```

In continuous mode the file is **overwritten** each iteration (one snapshot per scan), not appended. To build a history of scans, tail the file or rename between runs.

## Common Pitfalls

1. **Don't call plain `python3`** from a fresh terminal and assume yfinance works. The system Python's numpy is broken (3.9 wheel, 3.11 binary). Verify the interpreter imports `yfinance, pandas, numpy` before running the script. See `references/python-env.md`.

2. **Don't edit the watchlist inside the script** for one-off changes. Use `US_TICKERS=AAPL,MSFT,...` env var instead — the script reads it (`line 327`). This keeps the default list intact for scheduled runs.

3. **Continuous mode + launchd**: the openclaw workflow already supervises the script. Don't double-supervise (don't add it to launchd AND a cron). If the user asks "make it scan every minute," check whether openclaw already does this before adding new automation.

4. **Premarket data caveat**: `get_premarket_high()` only returns data when yfinance has 1-minute bars for today. On weekends, holidays, or before 4:00 AM ET, `pmh` falls back to prior-day high and `above_pmh_ok` may be falsely true on quiet days. Mention this when reporting signals near the open.

5. **15-minute price delay** on free yfinance. Real-time entry decisions need a paid data source. The script already documents this on `line 160`; surface it to the user if they ask about timing.

6. **Regime check uses prior close, not intraday**: SPY/QQQ direction is computed from yesterday's close vs today's last available close. During sharp intraday reversals, the regime flag may lag reality by one bar. Don't rely on it alone for hard vetoes.

7. **The script posts to Discord via webhook, not Telegram.** If the user wants Telegram delivery, route through `hermes send` after the run (Pattern A above), or set up a cron job (Pattern B). Don't try to monkey-patch the script.

8. **JSON file is overwritten, not appended** in continuous mode. If the user wants a scan history, instruct them to copy the file or pipe to a different location.

## Known Issues / Strategy Logic

### The `above_pmh_ok` check can never fire on a live scan (legacy EMA-stack scanners)

In `tjl_live_us.py` and `tjl_live_us_itick.py`, the check is:

```python
day_high = quote.get('day_high') or ...   # TODAY's intraday high so far
prev_day_high = float(highs[-2])          # yesterday's daily high
pmh = max(prev_day_high, day_high)
above_pmh_ok = (price > pmh + PMH_BUF)    # PMH_BUF = 0.70
```

`day_high` is today's intraday high (so far), and `price <= day_high` always.
So `price > pmh + 0.70` requires `price > day_high + 0.70`, which is
**impossible in practice**. The strategy docstring says "prior day high or
premarket high" but the code uses today's full-session high.

**Status (2026-08-03):** Fixed in both scanners by adding a `get_premarket_high()`
fetch (04:00–09:30 ET) and changing `pmh = max(prev_day_high, premarket_high)`
(excluding regular-session day_high). iTick version uses its REST API; yfinance
version uses yfinance 1-min bars (free tier doesn't include premarket, so the
PMH will still be 0 on yfinance — use iTick or TV-MCP for real PMH data).

This means **the third condition now fires** for tickers that broke above
their pre-market high during the regular session. The strategy effectively
becomes a proper 3-condition check.

### iTick rate limits make large scans impractical on the free tier

Free tier = 5 calls/min. Default 45-ticker scan needs 90 calls = ~18 min.
S&P 500 scan would take 3+ hours. For large watchlists, use yfinance.

### iTick does not return data for ETFs (SPY/QQQ) or major indices (SPX/NDX)

The `/stock/quote` endpoint returns `data: null` for these. The iTick scanner
now falls back to **yfinance** for the regime check, so this is handled.

### TV MCP `tv ohlcv` does NOT include pre-market bars

Even when the chart visually displays pre-market (e.g., the "Pre-market"
section visible above the regular session), the `tv ohlcv` endpoint only
returns regular-session bars. So `PMH` from TV alone is always 0.

**Workaround:** TV-MCP scanner falls back to iTick REST (if `ITICK_TOKEN`
is set) for the PMH calculation. Set the env var to enable.

### TV MCP regime check is non-blocking (added 2026-08-03)

The HumbledTrader recipe doesn't include a regime check. The TV-MCP scanner
**optionally** checks SPY/QQQ direction (default ON; skip with `--no-regime`).
This adds ~2 chart-switches (~20s) per scan.

## Common Pitfalls (updated 2026-08-03)

1. **The pre-existing `parser.parse_args()()` bug in `tjl_live_us_itick.py`.**
   The `--continuous` flag NEVER WORKED before this session — it crashed with
   `'Namespace' object is not callable`. Now fixed. Use `--continuous` to loop.

2. **TV chart state gets left on whatever ticker was last checked.**
   TV-MCP scanner now restores the chart to its starting symbol at end of
   each scan. (Otherwise you'd see SPY/QQQ as your last-viewed chart after
   a regime check.)

3. **Don't use iTick for SPY/QQQ regime check.** Use yfinance or TV.

4. **Don't assume yfinance has real-time data.** 15-min delay on free tier.
   For entry timing, use TV-MCP (real-time via your paid TV subscription).

5. **Don't run S&P 500 with iTick.** Free tier = 5 calls/min × 1006 calls ≈ 3.5 hours.

## Verification

A test harness lives at `~/.local/share/hermes-verify-tjl/verify_tjl_all.py`
covering 37 checks across all 3 scanners: constants, math correctness,
retry/backoff, kline parsing, time gates, health checks, regime BULLISH/BEARISH.

Run with:
```bash
~/.hermes/hermes-agent/venv/bin/python ~/.local/share/hermes-verify-tjl/verify_tjl_all.py
```

Expected: `RESULT: 37/37 checks passed` and `exit 0`.

## Tools Provided (2026-08-03)

### `run-all.sh`
Top-level wrapper that runs all 3 scanners sequentially with the same
watchlist and prints a unified comparison report. Example:

```bash
./run-all.sh "AAPL,NVDA,TSLA" --notify    # all 3 scanners + Telegram delivery
```

### `compare_results.py`
Reads the most recent JSON output from each scanner and prints a
side-by-side per-ticker comparison table.

```bash
python3 compare_results.py            # today's scans
python3 compare_results.py 2026-08-02 # yesterday's scans
```

### `--notify` flag (all 3 scanners)
Sends scan summary to the user's Telegram home channel automatically.
Requires the Hermes Telegram gateway to be configured (already done for
chat `8370185160`).

```bash
python3 tjl_live_us.py --notify         # yfinance + Telegram
python3 tjl_live_us_itick.py --notify   # iTick + Telegram
python3 tjl_live_us_tv.py --notify      # TV-MCP + Telegram
```

### `--no-regime` flag (TV-MCP only)
Skips the optional SPY/QQQ regime check (saves ~20s).

### `ITICK_TOKEN` env var (TV-MCP only)
When set, enables iTick fallback for PMH calculation (since TV's ohlcv
omits pre-market bars). Without this, PMH will always be 0 and the
intraday_breakout check is forced false.


## Verification Checklist

- [ ] Confirmed Python interpreter can `import yfinance, pandas, numpy` before claiming the scan works
- [ ] Ran the script one-shot end-to-end and parsed `~/tjl_live_us_<today>.json`
- [ ] If Telegram delivery was requested: confirmed message arrived at chat `8370185160`
- [ ] If scheduling was requested: confirmed cron job created via `cronjob(action="create")` and reviewed with `cronjob(action="list")`
- [ ] If watchlist was modified: confirmed via the scan output's `ticker` column
- [ ] Surfaced the 15-min delay + premarket-data caveats if the user is making real-money decisions

## Reference

- `references/python-env.md` — diagnosing which Python interpreter to use, fixing the broken system numpy