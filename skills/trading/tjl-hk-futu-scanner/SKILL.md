---
name: tjl-hk-futu-scanner
description: "Use when running or scheduling HK-market TJL live scans via Futu OpenD, explaining the HK TJL 11-model entry/exit rules (A pullback, B momentum, C vol-spike, D RSI bounce, E 20D break, F RSI trend, G ORB, H EMA/BB/VWAP, I 63WMA swing, J 150/200 DMA, K EMA/VWAP session), posting scan results to Discord/Telegram, or ranking HK stocks by turnover and scanning the top N. Drives the existing /Users/jaydensmac/.openclaw/workspace/tjl_live_futu.py and tjl_backtest.py scripts — does not re-implement them."
version: 1.3.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [trading, hk-market, tjl, scanner, futu, ema, telegram, discord, volume, turnover]
    related_skills: [tjl-live-scanner]
---

# TJL Live Scanner — HK Market (Futu OpenD)

## Overview

TJL = "Trend-Join-Long" — same long-entry strategy as the US variant, but for
**Hong Kong stocks** via the **Futu OpenD** real-time data API. The strategy
definition is identical (EMA9/20/50 stack + 0.2% pullback to EMA9 + PMH
breakout); only the data source and timezone differ.

| Variant | Data source | Timezone | Cost | Best for |
|---|---|---|---|---|
| **HK (this skill)** | Futu OpenD | HKT (Asia/Hong_Kong) | Free (Futu brokerage required) | HK live trading, day setups |
| [US — tjl-live-scanner](../tjl-live-scanner/SKILL.md) | yfinance / iTick / TV MCP | ET | Free or paid TV | US live trading |

**Key data flow:**
1. Connect to Futu OpenD at `127.0.0.1:11111` (default; configurable)
2. Subscribe to ~35 HK tickers (mega-cap + ADRs + active names)
3. For each ticker: fetch daily K-line (80 bars) + live quote
4. Compute EMA9/20/50 stack, ATR(14), check 3 conditions
5. Output signals to stdout + JSON + (optional) Discord/Telegram

## When to Use

- User asks to **run a TJL scan on HK stocks** ("scan HK", "TJL signals HK", "Tencent setup")
- User asks to **schedule scans** ("scan every 30s during HK market hours", "send me results at HK open")
- User asks to **modify scanner parameters** ("add 09999 to the watchlist", "tighten ATR stop to 1.2×")
- User asks to **explain the strategy** ("what is TJL?", "show me the entry rules")
- User asks to **post results to Telegram/Discord**
- User asks to **backtest the HK strategy** against historical HK data

**Don't use for:**
- US market scans → use `tjl-live-scanner` skill instead
- A-share (mainland China) scans → not supported by Futu OpenD HK
- Live trading execution → this is a SCANNER, not a broker. Manual entry required.

## The Strategy (encode this verbatim)

### Entry — all three must be true (per model)

**Model A — Pullback (original TJL):**
1. **Bullish EMA stack:** `EMA9 > EMA20 > EMA50` on daily bars
2. **Pullback to EMA9:** current price within ±1.5% of EMA9 (`NEAR_EMA_PCT = 0.015`)
3. **Above PMH:** price > today's premarket high + HKD 0.70 buffer

**Model B — Momentum (HT-style):**
1. **Above SMA200:** daily close > 200-day SMA
2. **Above PMH:** price > today's premarket high
3. **Above today's HOD:** price > today's high of day

**Model C — Volume-Confirmed Pullback (added 2026-08-05):**
1. **Any EMA config:** no specific EMA stack required (catches stocks with weaker stacks)
2. **Price within ±2.0% of EMA9:** `NEAR_EMA_PCT_C = 0.020` (wider than A)
3. **Volume ≥ 2× avg20:** current volume ≥ 2× 20-day average (`VOL_SPIKE_MULT = 2.0`)
4. **Above PMH + 0.70**

**Model D — RSI Oversold Bounce (mean reversion, added 2026-08-06):**
1. **RSI crosses UP through 30** from below (oversold bounce)
2. **Near VWAP:** price within ±1.5% of VWAP
3. **Above PMH**

**Model E — 20-Day High Breakout (momentum, added 2026-08-06):**
1. **Price breaks above 20-day high**
2. **Volume surge ≥ 1.5× avg20**
3. **RSI > 50** for LONG, **< 50** for SHORT

**Model F — RSI Trend Crossover (trend-following, added 2026-08-06):**
1. **LONG:** RSI crosses UP through 55 + `EMA9 > EMA20`
2. **SHORT:** RSI crosses DOWN through 45 + `EMA9 < EMA20`

**Model G — ORB / Opening Range Breakout (intraday, added 2026-08-07):**
1. **LONG:** price breaks ABOVE today's opening range high (today_high as proxy for open range)
2. **SHORT:** price breaks BELOW today's opening range low (today_low)
3. **Confirmed by:** volume ≥ 1.2× avg20 AND ATR confirms direction
4. **Always flat by EOD** (same-day exit intent)

**Model H — Gold EMA/BB/VWAP (trend intraday, added 2026-08-07):**
1. **LONG:** EMA9 crosses above Bollinger Band(20) midline AND price > EMA21 AND price > VWAP
2. **SHORT:** EMA9 crosses below BB(20) midline AND price < EMA21 AND price < VWAP

**Model I — SHM-lite / 63-WMA Swing (daily, added 2026-08-07):**
1. **LONG:** price > 63-WMA AND RSI > 50 AND price within 3% of 63-WMA (pullback to trend)
2. **SHORT:** price < 63-WMA AND RSI < 50
3. **Wider R:R:** SL = 1.5× ATR, TP = 3× ATR (2:1, swings need room)

**Model J — Follow the Money / 150-200 DMA (swing, added 2026-08-07):**
1. **LONG:** price within 2% of 150-DMA AND above 200-DMA AND vol ≥ 1.5× avg20
2. **SHORT:** price within 2% of 150-DMA AND below 200-DMA AND vol ≥ 1.5× avg20
3. **Needs ~155 bars lookback** — not active on short backtest windows

**Model K — EMA/VWAP/Bollinger Session (intraday, added 2026-08-07):**
1. Same as Model H (Gold EMA/BB/VWAP) — identical crossover logic
2. Kept as separate model for independent signal tracking

*Any of A/B/C/D/E/F/G/H/I/J/K firing = signal. SHORT signals are supported by D/E/F/G/H/I/J/K models. OR logic across all 11 models.*

### Exit

- **Models A/B/C:** `SL = price − 1.5 × ATR(14)` | `TP = price + 3.0 × ATR(14)` | R:R = 1:2
- **Models D/E/F/G/H:** `SL = price − 1.0 × ATR(14)` | `TP = price + 1.5 × ATR(14)` | R:R = 1:1.5
- **Models I:** `SL = price − 1.5 × ATR(14)` | `TP = price + 3.0 × ATR(14)` | R:R = 1:2
- **Models J:** `SL = price − 1.0 × ATR(14)` | `TP = price + 1.5 × ATR(14)` | R:R = 1:1.5

### Constants (in `tjl_live_futu.py`)

| Constant | Value | Applies to |
|---|---|---|
| `PMH_BUF` | `0.70` HKD | All models |
| `ATR_SL` | `1.5` | Models A, B, C |
| `ATR_TP` | `3.0` | Models A, B, C |
| `ATR_SL` | `1.0` | Models D, E, F |
| `ATR_TP` | `1.5` | Models D, E, F |
| `ATR_PERIOD` | `14` | All models |
| `NEAR_EMA_PCT` | `0.015` | Model A (±1.5% of EMA9) |
| `NEAR_EMA_PCT_C` | `0.020` | Model C (±2.0% of EMA9, wider) |
| `VOL_SPIKE_MULT` | `2.0` | Model C (vol ≥ 2× 20-day avg) |
| `SCAN_INTERVAL` | `30` | Seconds between scans in continuous mode |

### Regime filter

**Not included** in this script. HK market is single-session (no US-style
overnight gap), and the EMA-stack + pullback inherently filters for trending
names. Add a HSI regime check if you want a filter (e.g., skip scans when HSI
< 200-day MA).

## The Script

### `~/.openclaw/workspace/tjl_live_futu.py`

| | |
|---|---|
| **Path** | `/Users/jaydensmac/.openclaw/workspace/tjl_live_futu.py` |
| **Default watchlist** | ~119 HK tickers (mega-cap + financials + utilities + properties + commerce + ADR-style names) — see `WATCHLIST` in the file |
| **Models** | 11 (A/B/C/D/E/F/G/H/I/J/K) — see "The Strategy" above |
| **Data source** | Futu OpenD (local, must be running) |
| **CLI** | `--continuous` (loop), `--interval N` (seconds) |
| **Env overrides** | `DISCORD_WEBHOOK_HK_TJL=<url>` (Discord post), `HK_TICKERS=HK.00700,HK.09988,...` (custom watchlist, comma-separated, **added 2026-08-07**), `--notify` (Telegram via Hermes gateway) |
| **Output files** | `~/tjl_live_signals_<YYYY-MM-DD>.json` (only when signals found) |
| **Timezone** | All timestamps in HKT (Asia/Hong_Kong) |

### `~/.openclaw/workspace/tjl_backtest.py`

| | |
|---|---|
| **Path** | `/Users/jaydensmac/.openclaw/workspace/tjl_backtest.py` |
| **Purpose** | Backtest Models D/E/F/G/H/I/J/K on historical HK data |
| **Default watchlist** | 8 tickers (HSI mega-caps) |
| **Data source** | Futu OpenD historical K-lines |
| **CLI** | `--daily N` (days), `--15min N`, `--5min N`, `--hold N` (bars), `--lookback N` |
| **Default** | Daily bars, 20 days, 5-bar max hold |
| **Timezone** | HKT |

## How to invoke from Hermes

### Check if Futu OpenD is running

```bash
lsof -i :11111  # should show futu opend process
```

If not running, start Futu OpenD (the user has it installed; see
`references/futu-setup.md` for install/login steps).

### Common invocations

```bash
# One-shot scan (default ~119-ticker watchlist)
/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_live_futu.py

# Continuous loop, custom interval
/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_live_futu.py --continuous --interval 60

# Custom watchlist via HK_TICKERS env (added 2026-08-07, no source edit needed)
HK_TICKERS='HK.09988,HK.00700,HK.03690,HK.00981' \
DISCORD_WEBHOOK_HK_TJL='https://discord.com/api/webhooks/...' \
  /Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_live_futu.py

# Discord post on completion
DISCORD_WEBHOOK_HK_TJL='https://discord.com/api/webhooks/...' \
  /Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_live_futu.py

# Backtest (daily, 20 days, 5-bar hold)
/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_backtest.py

# Backtest — 15-min bars, 20 days
/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_backtest.py --15min 20

# Backtest — daily, 1 year (252 days), 10-bar hold
/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_backtest.py --daily 252 --hold 10

# Backtest — 5-min bars, 20 days
/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python3 ~/.openclaw/workspace/tjl_backtest.py --5min 20
```

**Hermes-specific:** if the user wants Telegram delivery, use `--notify` (if
patched) or wrap with `hermes send` after the run (see SKILL.md of
`tjl-live-scanner` for the pattern).

## Delivery to Telegram (the user has a Hermes Telegram gateway)

The script posts to Discord via webhook. Hermes can deliver scan output to the
user's Telegram bot (chat `8370185160`) using `hermes send`. Two patterns:

### Pattern A — re-deliver after the run

```bash
# 1. Run the scan and capture the JSON
python3 ~/.openclaw/workspace/tjl_live_futu.py > /tmp/tjl_futu_run.log 2>&1

# 2. Parse signals and send a formatted Telegram message
python3 - <<'PY'
import json, glob, os
files = sorted(glob.glob(os.path.expanduser("~/tjl_live_signals_*.json")), key=os.path.getmtime)
if not files:
    print("No signals JSON found")
else:
    d = json.load(open(files[-1]))
    print(f"📊 *TJL HK Scan* — {d.get('scanned_at', '?')}")
    print(f"Source: {d.get('source', 'Futu OpenD')}")
    print(f"Signals: *{len(d.get('signals', []))}*")
    for s in d.get("signals", []):
        print(f"• `{s.get('name', '?')}` @ HKD {s.get('price', 0):.2f}  "
              f"SL {s.get('sl', 0):.2f}  TP {s.get('tp', 0):.2f}")
PY | hermes send --to telegram -
```

### Pattern B — native `--notify` flag

The script doesn't have `--notify` yet (the US scanners do). To add it, mirror
the pattern in `tjl_live_us.py` (see `references/futu-setup.md` for the
notification helper).

## Volume-Top-10 Workflow (added 2026-08-07)

Use case: "scan HK stocks for top turnover, then run TJL on those names".

Step 1 — Get top 10 HK stocks by turnover via Futu snapshot:

```bash
/usr/bin/python3 /tmp/hk_volume_top.py
# OR write a one-off that subscribes a curated 60+ ticker list and ranks
```

The volume script uses `get_market_snapshot()` and sorts by `turnover` (HKD).
A reference implementation lives at `/tmp/hk_volume_top.py` (created in this
session). Output columns are: code, name, last_price, change_rate (computed
from prev_close), volume, turnover.

Step 2 — Pass the top-10 codes as `HK_TICKERS` to the TJL scanner:

```bash
TOP10=$(/usr/bin/python3 /tmp/hk_volume_top.py | awk '/^[ ]*[0-9]+[ ]+HK\./ {print $2}' | tr '\n' ',' | sed 's/,$//')
DISCORD_WEBHOOK_HK_TJL='...' \
HK_TICKERS="$TOP10" \
  /usr/bin/python3 ~/.openclaw/workspace/tjl_live_futu.py
```

This is the typical workflow when the user asks "scan top N by volume" — get
turnover ranking first, then run TJL on the ranked subset.

## Common Pitfalls

1. **Use `/usr/bin/python3`, not python3.11 or venv python.** The Futu SDK
   is installed under `~/Library/Python/3.9/lib/python/site-packages/futu/`,
   which only the system Python 3.9 sees. Running with `python3.11` (the
   venv default) raises `ModuleNotFoundError: futu`.

2. **Futu OpenD must be running locally on port 11111** (default). If the
   script fails with `Connection refused`, start Futu OpenD and log in.

3. **The script connects synchronously and exits after each scan.** A single
   scan takes ~5-10s (one round-trip per ticker). For the default ~119-ticker
   watchlist, total wall time is ~10-15s. Use `--interval 60+` for continuous.

4. **`get_market_snapshot()` returns turnover in HKD directly** (no scaling).
   Sort descending by `turnover` to get top turnover names.

5. **No built-in regime check.** The script scans regardless of HSI direction.
   Add a regime filter if you want to skip in bear markets.

6. **Watchlist override** uses `HK_TICKERS` env (added 2026-08-07, mirrors
   the US variant's `US_TICKERS`). Format: comma-separated Futu codes
   (e.g. `HK.00700,HK.09988`). Names are auto-derived from the code tail.

7. **Output file is only written on signal** (`tjl_live_signals_*.json`).
   If you want a "no signals" record, wrap the run with a script that always
   writes output.

8. **Discord webhook is forum-channel** — every payload needs `thread_name`,
   otherwise it returns HTTP 400 / code 220001. Use the existing
   `~/.hermes/scripts/discord_scan_hook.sh` wrapper or post via curl with
   `{"thread_name": "...", "content": "..."}`.

## Verification

A test harness lives at `~/.local/share/hermes-verify-tjl/verify_tjl_futu.py`
(it will be created as part of this skill). Run with:

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.local/share/hermes-verify-tjl/verify_tjl_futu.py
```

The harness exercises the pure logic (math, JSON schema) without requiring
a live Futu OpenD connection. It uses the same pattern as
`verify_tjl_all.py` for the US scanners.

## Related Skills

- `tjl-live-scanner` — US market (yfinance / iTick / TV MCP variants)
- (no HK A-share skill yet — Futu OpenD doesn't support mainland China)

## See also

- `references/futu-setup.md` — installing/configuring Futu OpenD
- The US skill's `references/python-env.md` pattern is mirrored here for the
  Futu variant
