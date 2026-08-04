---
name: tjl-hk-futu-scanner
description: "Use when running or scheduling HK-market TJL live scans via Futu OpenD, explaining the HK TJL entry/exit rules, posting scan results to Discord/Telegram, or modifying scanner parameters (watchlist, ATR multipliers, EMA periods). Drives the existing /Users/jaydensmac/.openclaw/workspace/tjl_live_futu.py and tjl_backtest_futu.py scripts — does not re-implement them."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [trading, hk-market, tjl, scanner, futu, ema, telegram, discord]
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

### Entry — all three must be true

1. **Bullish EMA stack:** `EMA9 > EMA20 > EMA50` on daily bars
2. **Pullback to EMA9:** current price within ±0.2% of EMA9 (`NEAR_EMA_PCT = 0.002`)
3. **Above PMH:** price > today's intraday high + HKD 0.70 buffer (`PMH_BUF = 0.70`)

### Exit

- **Stop Loss:** `price − 1.5 × ATR(14)`
- **Take Profit:** `price + 3.0 × ATR(14)`
- Fixed **R:R = 1:2** (TP multiple / SL multiple)

### Constants (in `tjl_live_futu.py`)

| Constant | Value | Purpose |
|---|---|---|
| `PMH_BUF` | `0.70` HKD | Buffer above PMH for entry |
| `ATR_SL` | `1.5` | Stop-loss ATR multiplier |
| `ATR_TP` | `3.0` | Take-profit ATR multiplier |
| `ATR_PERIOD` | `14` | ATR lookback |
| `NEAR_EMA_PCT` | `0.002` | 0.2% pullback zone |
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
| **Default watchlist** | 35 HK tickers — see `WATCHLIST` in the file (Tencent, JD, Meituan, KE, Kuaishou, BYD, AIA, PopMart, etc.) |
| **Data source** | Futu OpenD (local, must be running) |
| **CLI** | `--continuous` (loop), `--interval N` (seconds) |
| **Env overrides** | `DISCORD_WEBHOOK_HK_TJL=<url>` (Discord post), `--notify` (Telegram via Hermes gateway) |
| **Output files** | `~/tjl_live_signals_<YYYY-MM-DD>.json` (only when signals found) |
| **Timezone** | All timestamps in HKT (Asia/Hong_Kong) |

### `~/.openclaw/workspace/tjl_backtest_futu.py`

| | |
|---|---|
| **Path** | `/Users/jaydensmac/.openclaw/workspace/tjl_backtest_futu.py` |
| **Purpose** | Backtest TJL on 250 days of HK daily data |
| **Default watchlist** | 8 tickers (subset of the live list) |
| **Data source** | Futu OpenD historical K-lines |
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
# One-shot scan (35 default tickers)
python3 ~/.openclaw/workspace/tjl_live_futu.py

# Continuous loop, custom interval
python3 ~/.openclaw/workspace/tjl_live_futu.py --continuous --interval 60

# Custom watchlist (edit WATCHLIST in file, or fork a variant)
# (Futu variant doesn't have US_TICKERS env support — edit the source)

# Discord post on completion
DISCORD_WEBHOOK_HK_TJL='https://discord.com/api/webhooks/...' \
  python3 ~/.openclaw/workspace/tjl_live_futu.py

# Backtest
python3 ~/.openclaw/workspace/tjl_backtest_futu.py
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

## Common Pitfalls

1. **Futu OpenD must be running locally on port 11111** (default). If the
   script fails with `Connection refused`, start Futu OpenD and log in.

2. **The script connects synchronously and exits after each scan.** A single
   scan takes ~5-10s (one round-trip per ticker). Don't use the default
   35-ticker watchlist for sub-30s intervals — increase `--interval` to 60+.

3. **The `above_pmh_ok` check uses today's intraday high** (line 147 of
   `tjl_live_futu.py`). Same bug as the legacy US scanners: `price > today_high + 0.70`
   is impossible in practice. Same fix applies (use premarket high) but not
   yet implemented for the Futu variant.

4. **No built-in regime check.** The script scans regardless of HSI direction.
   Add a regime filter if you want to skip in bear markets.

5. **Watchlist is hardcoded** in `WATCHLIST` (line 43). The US scanners have
   `US_TICKERS` env override; the Futu variant doesn't. To add a ticker,
   edit the source.

6. **Output file is only written on signal** (`tjl_live_signals_*.json`).
   If you want a "no signals" record, wrap the run with a script that always
   writes output.

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
