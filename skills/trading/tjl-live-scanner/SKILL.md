---
name: tjl-live-scanner
description: "Use when running or scheduling US-market TJL/TJS scans, explaining entry/exit rules, posting results to Discord/Telegram, or modifying scanner parameters (watchlist, ATR, EMA periods). Drives the existing /Users/jaydensmac/.openclaw/workspace/tjl_live_us.py script — does not re-implement it."
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [trading, us-market, tjl, tjs, scanner, yfinance, ema, short-selling, discord]
    related_skills: [xueqiu-discussion-hunter]
---

# TJL Live Scanner (US Market)

## Quick-Start Cheatsheet

```bash
# Run one-shot scan → Discord (auto-posts)
DISCORD_WEBHOOK_HK_TJL='https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj' \
<PY> ~/.openclaw/workspace/tjl_live_us.py

# Custom watchlist (no script edit)
US_TICKERS=AAPL,AMZN,NVDA,META,TSLA <PY> ~/.openclaw/workspace/tjl_live_us.py

# Run continuously every 60s
<PY> ~/.openclaw/workspace/tjl_live_us.py --continuous --interval 60

# Add Telegram delivery
<PY> ~/.openclaw/workspace/tjl_live_us.py --notify
```

| Question | Answer |
|---|---|
| "Does it go short?" | YES — TJS SHORT in BEARISH regime |
| "Why 0 signals today?" | 3-condition filter is strict; see "Why So Few Signals?" below |
| "Post to existing Discord thread?" | Thread ID already configured; script auto-creates one per day |
| "xueqiu predictions as backup?" | YES — see "When TJL Says Nothing" below |

---

## Overview

**TJL = Trend-Join-Long** (bullish pullback entries)
**TJS = Trend-Join-Short** (bearish rebound entries — added 2026-08-04)

| Variant | Direction | EMA stack | Entry trigger | Exit |
|---|---|---|---|---|
| **TJL LONG** | Long 🟢 | EMA9 > EMA20 > EMA50 | Within 0.2% of EMA9 + above PMH | SL=price−1.5×ATR, TP=price+3×ATR |
| **TJS SHORT** | Short 🔴 | EMA9 < EMA20 < EMA50 | Within 0.2% of EMA9 + below PML | SL=price+1.5×ATR, TP=price−3×ATR |

**Regime routing:**
- `BEARISH` (SPY↓ or QQQ↓): LONG suppressed — TJS SHORT allowed
- `BULLISH` (SPY↑ and QQQ↑): SHORT suppressed — TJL LONG allowed

**Three scripts:**

| Script | Data | Latency | Best for |
|---|---|---|---|
| `tjl_live_us_tv.py` | TradingView MCP | Real-time | Curated 3–20 names, real-time |
| `tjl_live_us.py` | yfinance | 15-min delayed | Large watchlists, free |
| `tjl_live_us_itick.py` | iTick REST | Real-time (free=5/min) | Small real-time watchlists |

---

## The Strategy

### TJL LONG Entry — all three must be true

1. **Bullish EMA stack:** `EMA9 > EMA20 > EMA50` on daily bars (80-day lookback)
2. **Pullback zone:** `|price − EMA9| / EMA9 ≤ 0.2%` (price is bouncing near EMA9)
3. **Above PMH:** `price > max(prior_day_high, premarket_high) + $0.70`

**Exit:** SL = `price − 1.5 × ATR(14)` | TP = `price + 3.0 × ATR(14)` | R:R = 1:2

### TJS SHORT Entry — all three must be true

1. **Bearish EMA stack:** `EMA9 < EMA20 < EMA50` on daily bars
2. **Rebound zone:** `|price − EMA9| / EMA9 ≤ 0.2%` (price is bouncing up toward EMA9)
3. **Below PML:** `price < min(prior_day_low, premarket_low) − $0.70`

**Exit:** SL = `price + 1.5 × ATR(14)` (stop ABOVE entry) | TP = `price − 3.0 × ATR(14)` (profit BELOW entry)

### PMH / PML Definition (Critical)

`PMH = max(prior_day_high, premarket_high)` — the overnight/high pre-market reference, NOT today's intraday high.
`PML = min(prior_day_low, premarket_low)` — the overnight/low pre-market reference, NOT today's intraday low.

The regular-session intraday high/low is excluded because:
- `price ≤ day_high` always → using `day_high` makes `above_pmh_ok` permanently False
- `price ≥ day_low` always → using `day_low` makes `below_pml_ok` permanently False

### Constants

| Constant | Value | Notes |
|---|---|---|
| `PMH_BUF` | `$0.70` | Absolute dollar buffer, not % — works for $50 and $500 stocks |
| `ATR_SL` | `1.5×` | Stop-loss distance in ATR units |
| `ATR_TP` | `3.0×` | Take-profit distance in ATR units |
| `ATR_PERIOD` | `14` | Standard ATR lookback |
| `NEAR_EMA_PCT` | `0.2%` | Pullback/rebound zone width |
| `SCAN_INTERVAL` | `30s` | Continuous loop interval |

### Regime Filter

`get_regime()` checks SPY and QQQ close vs prior close:
- Both up → `BULLISH` → TJL LONG enabled, TJS SHORT suppressed
- Either down → `BEARISH` → TJS SHORT enabled, TJL LONG suppressed

**Limitation:** Regime is based on yesterday's close vs prior close — it lags during sharp intraday reversals. Do not use it as a hard veto.

---

## Why So Few Signals?

TJL/TJS is a **3-condition pullback strategy**. All three must align simultaneously:

```
Trend must exist     →  EMA9 > EMA20 > EMA50 (or < for short)
Pullback must happen →  price within 0.2% of EMA9
Breakout must confirm →  price above PMH (or below PML for short)
```

**On a typical day:**
- ~5–10% of stocks have a clean EMA stack
- Of those, only ~10–20% are pulling back to EMA9 (most gap through or trend away)
- Of those, only a subset are above/below the overnight reference level

**Expect 0–3 signals per 40-stock scan on most days.** This is normal, not a failure.

**Today's market (2026-08-04) was an extreme example:**
- SPY was BEARISH → LONG suppressed
- 19 of 42 stocks had bearish EMA stacks → TJS SHORT candidates
- 0 pulled back to within 0.2% of EMA9 — crashes gap through EMA levels, they don't consolidate
- No TJS SHORT signals fired

**When 0 signals fire in BULLISH regime:** the market is in momentum mode — stocks trending strongly, not pulling back. This is actually a bullish signal (low friction trending environment).

---

## When TJL Says Nothing — What To Do

**Option 1: Wait** — Scan again at next market open, or set up a cron job to run every 5 minutes during market hours.

**Option 2: Hunt xueqiu for trade ideas** — Run the xueqiu-discussion-hunter skill to surface retail trader predictions from Chinese finance communities. 钱朋兴 correctly called TSLA🔴/COIN🔴/MSTR🔴/RIVN🔴, 杰夫磊 called META🔴. These are directional signals with high conviction, not TJL-formatted entries — use them for directional bias, not entry timing.

```python
# Quick xueqiu hunt for your watchlist tickers
# Load skill: xueqiu-discussion-hunter
# Then run: run_hunt(target_stocks=["AAPL","NVDA","TSLA","COIN","MSTR"])
```

**Option 3: Relax one condition** — If you're seeing a clear trend but no pullback, the stock may be a "set and forget" trend ride. TJL is specifically designed to avoid false entries by requiring all 3 conditions — don't force it.

**Option 4: Check the TV variant** — `tjl_live_us_tv.py` uses SMA200 + PMH breakout (HumbledTrader recipe), which is a different, more permissive entry trigger. It may find setups the EMA-stack variant misses.

---

## Discord Delivery

The script **auto-posts a rich embed** when `DISCORD_WEBHOOK_HK_TJL` is set. Your configured webhook:

```
https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj
```

Posts use a **colored embed** (green=BULLISH, red=BEARISH) with separate LONG/SHORT fields, ticker, price, EMA9, SL, TP, and R:R per signal. A new forum thread is created each day (`US TJL Live YYYY-MM-DD`).

```bash
# Standard run → Discord embed auto-posted
DISCORD_WEBHOOK_HK_TJL='https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj' \
<PY> ~/.openclaw/workspace/tjl_live_us.py
```

**To post to an existing thread** (no new thread created):
```bash
THREAD_ID=1335968760329830411
curl -s -w "\n%{http_code}" \
  -X POST \
  "https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj?wait=true" \
  -H "Content-Type: application/json" \
  -d '{"content": "...", "thread_name": "US TJL Live 2026-08-04"}'
```

---

## Telegram Delivery

The script delivers to Discord only. For Telegram, route after the run:

```bash
<PY> ~/.openclaw/workspace/tjl_live_us.py > /tmp/tjl.log 2>&1
python3 - <<'PY'
import json, glob, os
d = json.load(open(max(glob.glob("~/tjl_live_us_*.json"), key=os.path.getmtime)))
longs = [s for s in d["signals"] if s.get("direction") == "LONG"]
shorts = [s for s in d["signals"] if s.get("direction") == "SHORT"]
regime_emoji = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(d.get("regime",""), "⚪")
lines = [f"📊 TJL — {regime_emoji} {d['regime']} | {len(d['signals'])} signals ({len(longs)}L/{len(shorts)}S)"]
for s in sorted(d["signals"], key=lambda x: -x["rr_ratio"]):
    lines.append(f"{s['ticker']} {s['direction']} R:R={s['rr_ratio']} SL={s['sl']} TP={s['tp']}")
print("\n".join(lines))
PY | hermes send --to telegram -
```

Or schedule a cron to deliver every 5 minutes during market hours:

```python
cronjob(action="create",
    name="TJL US scan every 5min",
    schedule="*/5 9-16 * * mon-fri",
    prompt="Run tjl_live_us.py. Parse the JSON output. Send a oneline summary to Telegram. If regime==BEARISH lead with 🔴.",
    enabled_toolsets=["terminal"])
```

---

## Reading Output

`~/tjl_live_us_<YYYY-MM-DD>.json`:

```json
{
  "scanned_at": "2026-08-04 10:15:00 ET",
  "source": "Yahoo Finance",
  "regime": "BEARISH",
  "signals": [
    {
      "ticker": "COIN", "name": "Coinbase", "price": 142.50,
      "direction": "SHORT",
      "e9": 143.20, "e20": 145.80, "e50": 148.30,
      "atr": 5.12, "pml": 144.00,
      "sl": 150.18, "tp": 127.14, "rr_ratio": 2.0,
      "stack_ok": true, "near_ema_ok": true, "below_pml_ok": true
    }
  ],
  "longs": [], "shorts": [...],
  "debug": ["AAPL: LONG suppressed (BEARISH regime)", "NVDA: !nearEMA !belowPML", ...]
}
```

`debug` field shows per-ticker failure reasons. Look for stocks failing only 1 condition — those are closest to triggering.

---

## Script Invocation Reference

```bash
# yfinance (default 45-ticker watchlist, 15-min delay)
<PY> ~/.openclaw/workspace/tjl_live_us.py

# yfinance + Discord + Telegram
DISCORD_WEBHOOK_HK_TJL='...' <PY> ~/.openclaw/workspace/tjl_live_us.py --notify

# yfinance + custom tickers (no edit needed)
US_TICKERS=AAPL,AMZN,MSFT,NVDA,META,TSLA,COIN,MSTR,RBLX,RDDT \
  <PY> ~/.openclaw/workspace/tjl_live_us.py

# Continuous loop
<PY> ~/.openclaw/workspace/tjl_live_us.py --continuous --interval 60

# TradingView MCP (real-time, 3-ticker default, 25s/ticker)
<PY> ~/.openclaw/workspace/tjl_live_us_tv.py

# iTick REST (real-time, free tier 5/min, ~18min for 45 tickers)
<PY> ~/.openclaw/workspace/tjl_live_us_itick.py
```

---

## Known Limitations

1. **15-min delay** — yfinance free tier delays 15 minutes. For real-time entries, use `tjl_live_us_tv.py` (TV MCP) or `tjl_live_us_itick.py` (iTick real-time).

2. **Premarket data gaps** — `get_premarket_high/low()` returns None before 4:00 AM ET or on days yfinance has no 1-minute bars. PMH/PML falls back to prior day high/low. On quiet days this may make `above_pmh_ok`/`below_pml_ok` appear true when the stock actually gapped.

3. **`PMH_BUF = $0.70` is a fixed dollar amount** — it works for stocks from $50–$500. For sub-$50 stocks the buffer is large relative to price (1.4%+); for >$500 stocks it's small (0.14%). This is a known design trade-off.

4. **Regime lags intraday reversals** — based on yesterday vs prior day close, not intraday. During sharp reversals the regime flag can be wrong for the first bar.

5. **iTick free tier = 5 calls/min** — 45-ticker scan takes ~18 minutes with backoff. Don't run the default list on iTick free tier.

6. **TV MCP `tv ohlcv` omits premarket** — PMH will be 0 unless `ITICK_TOKEN` is set for fallback.

---

## Verification

**Test harness:** `~/.local/share/hermes-verify-tjl/verify_tjl_all.py` — 39 checks covering constants, EMA/ATR math, LONG/SHORT signal logic, regime routing, NaN handling, Discord payload.

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.local/share/hermes-verify-tjl/verify_tjl_all.py
```
Expected: `RESULT: 39/39 checks passed`, exit 0.

**Smoke test** (live scan, no signals expected pre-market):
```bash
DISCORD_WEBHOOK_HK_TJL='...' US_TICKERS=AAPL,TSLA,NVDA \
  ~/.hermes/hermes-agent/venv/bin/python ~/.openclaw/workspace/tjl_live_us.py
```

---

## Related Skills

- **xueqiu-discussion-hunter** — surfaces retail trade predictions from Chinese finance communities. Best for directional bias when TJL finds nothing. Covers both HK and US stocks.

## Checklist

- [ ] Interpreter import test: `/usr/bin/python3 -c "import yfinance, pandas, numpy; print('ok')"`
- [ ] One-shot scan ran successfully (check `~/tjl_live_us_<today>.json`)
- [ ] Discord embed received (check forum channel)
- [ ] Telegram delivery confirmed if requested
- [ ] No signals = normal; explained to user (3-condition strict filter)
- [ ] Surfaced 15-min delay caveat if user is making real-money decisions
