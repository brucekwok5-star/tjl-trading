#!/usr/bin/env python3
"""
TJL Backtest — TradingView MCP data source
==========================================
Uses `tv ohlcv` (TradingView Desktop MCP) for daily OHLCV data.
No 15-min yfinance delay; real-time-quality bars.

ENTRY (TJL LONG):
  1. Bullish EMA stack:  EMA9 > EMA20 > EMA50  (daily bars)
  2. Pullback zone:     |price - EMA9| / EMA9 <= 0.2%
  3. Above PMH:        price > prior_day_high + $0.70

EXIT:
  SL: price - 1.5 * ATR(14)
  TP: price + 3.0 * ATR(14)
  Result: WIN (>+0.05%), LOSS (<-0.05%), BREAK-EVEN

Regime routing (BEARISH = TJS SHORT suppressed):
  SPY up AND QQQ up  → BULLISH  (LONG allowed)
  SPY down OR QQQ down → BEARISH (LONG suppressed)

TJS SHORT (added):
  1. Bearish EMA stack:  EMA9 < EMA20 < EMA50
  2. Rebound zone:       |price - EMA9| / EMA9 <= 0.2%
  3. Below PML:         price < prior_day_low - $0.70

EXIT: SL = price + 1.5*ATR | TP = price - 3.0*ATR

Usage:
  python3 tjl_backtest_tv.py INTC META ARM QLB
  python3 tjl_backtest_tv.py INTC META ARM QLB --resolution D
  python3 tjl_backtest_tv.py INTC META ARM QLB --bars 400
"""

import json
import os
import subprocess
import sys
import time
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TV_CLI = os.environ.get("TV_CLI", "/Users/jaydensmac/.local/bin/tv")

# ── Backtest constants ────────────────────────────────────────────────────────
PMH_BUF     = 0.70        # $0.70 buffer above prior day high
ATR_SL      = 1.5         # SL distance in ATR units
ATR_TP      = 3.0         # TP distance in ATR units
ATR_PERIOD  = 14
EMA9_WIN    = 0.002      # 0.2% — pullback/rebound zone
WARMUP      = 60          # bars before starting (EMA50 warmup)

# ── Helpers ────────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)


def run_tv(args, timeout=90):
    """Run `tv <args>` and return parsed JSON."""
    cmd = [TV_CLI] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"tv {args!r} failed (exit {r.returncode}): {r.stderr[:200] or r.stdout[:200]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"tv {args!r} returned non-JSON: {r.stdout[:300]}")


def fetch_daily_bars(symbol, count=400):
    """Fetch `count` daily OHLCV bars from TradingView MCP.
    Uses `tv symbol` CLI then `tv ohlcv` for data."""
    log(f"  Fetching {count} daily bars for {symbol}...")

    # 1. Switch symbol via tv CLI
    sym_resp = run_tv(["symbol", symbol], timeout=30)
    if not sym_resp.get("success"):
        raise RuntimeError(f"symbol switch failed: {sym_resp}")

    # 2. Switch to daily TF and fetch bars via CLI
    run_tv(["timeframe", "D"], timeout=30)
    data = run_tv(["ohlcv", "--count", str(count)], timeout=120)
    if not data.get("success"):
        raise RuntimeError(f"ohlcv failed: {data}")
    bars = data.get("bars") or data.get("data") or []
    if len(bars) < 50:
        raise RuntimeError(f"only {len(bars)} bars returned")

    last_close = float(bars[-1]["close"]) if bars else 0
    last_high  = float(bars[-1]["high"])  if bars else 0
    log(f"  ✓ {symbol}: {len(bars)} bars | last_close={last_close:.2f} last_high={last_high:.2f}")
    return bars


def calc_emas_atr(bars):
    """Add EMA9, EMA20, EMA50, ATR to bars in-place. Returns list of dicts."""
    import pandas as pd
    import numpy as np

    df = pd.DataFrame(bars)
    close = df["close"].astype(float)
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)

    df["ema9"]  = close.ewm(span=9,  adjust=False).mean()
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # ATR
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low  - prev_close).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=ATR_PERIOD).mean()

    # Prior day high / low (PMH / PML proxy)
    df["prev_high"] = high.shift(1)
    df["prev_low"]  = low.shift(1)

    return df.to_dict("records")


def check_regime():
    """Determine SPY/QQQ regime using TV MCP."""
    regime_details = []
    for sym in ("SPY", "QQQ"):
        try:
            run_tv(["symbol", sym], timeout=15)
            time.sleep(3)
            run_tv(["timeframe", "D"], timeout=15)
            time.sleep(3)
            data = run_tv(["ohlcv", "--count", "5"], timeout=30)
            bars = data.get("bars") or data.get("data") or []
            if len(bars) >= 2:
                curr  = float(bars[-1]["close"])
                prev  = float(bars[-2]["close"])
                regime_details.append((sym, curr, prev, curr > prev))
        except Exception as e:
            regime_details.append((sym, 0, 0, False))

    if regime_details and all(d[3] for d in regime_details):
        return "BULLISH", regime_details
    elif regime_details and any(not d[3] for d in regime_details):
        return "BEARISH", regime_details
    return "UNKNOWN", regime_details


# ── Backtest engine ─────────────────────────────────────────────────────────────

def run_backtest(symbol, bars, regime="BULLISH"):
    """Run TJL LONG and TJS SHORT backtest on pre-fetched bars.
    Returns (long_trades, short_trades)."""
    import numpy as np

    closes    = np.array([float(b["close"])  for b in bars])
    highs     = np.array([float(b["high"])  for b in bars])
    lows      = np.array([float(b["low"])   for b in bars])
    ema9      = np.array([float(b["ema9"])  for b in bars], dtype=float)
    ema20     = np.array([float(b["ema20"]) for b in bars], dtype=float)
    ema50     = np.array([float(b["ema50"]) for b in bars], dtype=float)
    atr       = np.array([float(b["atr"])   for b in bars], dtype=float)
    prev_high = np.array([float(b["prev_high"]) for b in bars], dtype=float)
    prev_low  = np.array([float(b["prev_low"])  for b in bars], dtype=float)
    dates     = [b.get("time") or b.get("datetime") or "" for b in bars]

    def fmt_date(ts):
        if not ts:
            return ""
        try:
            return datetime.fromtimestamp(int(ts), ET).strftime("%Y-%m-%d")
        except:
            return str(ts)[:10]

    long_trades, short_trades = [], []
    in_long, in_short = False, False
    entry_px = entry_dt = entry_atr = sl = tp = 0.0

    for i in range(WARMUP, len(bars)):
        price   = closes[i]
        ema9_i  = ema9[i]
        ema20_i = ema20[i]
        ema50_i = ema50[i]
        atr_i   = atr[i]
        ph      = prev_high[i]
        pl      = prev_low[i]
        hi      = highs[i]
        lo      = lows[i]
        dt      = fmt_date(dates[i])

        if np.isnan(ema9_i) or np.isnan(ema20_i) or np.isnan(ema50_i) or np.isnan(atr_i):
            continue

        # ── LONG EXIT ──────────────────────────────────────────────────────────
        if in_long:
            exit_px = None
            if lo <= sl:
                exit_px = sl
            elif hi >= tp:
                exit_px = tp
            if exit_px is not None:
                pnl = (exit_px - entry_px) / entry_px * 100
                res = "WIN" if pnl > 0.05 else ("LOSS" if pnl < -0.05 else "BE")
                long_trades.append({
                    "Ticker": symbol, "Entry Date": entry_dt, "Exit Date": dt,
                    "Entry": round(entry_px, 3), "Exit": round(exit_px, 3),
                    "PnL %": round(pnl, 2), "Result": res,
                    "ATR": round(entry_atr, 3),
                })
                in_long = False

        # ── SHORT EXIT ────────────────────────────────────────────────────────
        if in_short:
            exit_px = None
            if hi >= sl:          # price rose to hit SL (loss for short)
                exit_px = sl
            elif lo <= tp:        # price fell to hit TP (profit for short)
                exit_px = tp
            if exit_px is not None:
                pnl = (entry_px - exit_px) / entry_px * 100
                res = "WIN" if pnl > 0.05 else ("LOSS" if pnl < -0.05 else "BE")
                short_trades.append({
                    "Ticker": symbol, "Entry Date": entry_dt, "Exit Date": dt,
                    "Entry": round(entry_px, 3), "Exit": round(exit_px, 3),
                    "PnL %": round(pnl, 2), "Result": res,
                    "ATR": round(entry_atr, 3),
                })
                in_short = False

        # ── LONG ENTRY ─────────────────────────────────────────────────────────
        if not in_long and regime == "BULLISH":
            bull_stack = (ema9_i > ema20_i > ema50_i)
            near_ema9  = (ema9_i > 0) and (abs(price - ema9_i) / ema9_i <= EMA9_WIN)
            above_pmh  = not np.isnan(ph) and (price >= ph + PMH_BUF)
            if bull_stack and near_ema9 and above_pmh:
                in_long   = True
                entry_px  = price
                entry_dt  = dt
                entry_atr = atr_i
                sl        = price - ATR_SL * atr_i
                tp        = price + ATR_TP * atr_i

        # ── SHORT ENTRY ────────────────────────────────────────────────────────
        if not in_short and regime == "BEARISH":
            bear_stack = (ema9_i < ema20_i < ema50_i)
            near_ema9  = (ema9_i > 0) and (abs(price - ema9_i) / ema9_i <= EMA9_WIN)
            below_pml  = not np.isnan(pl) and (price <= pl - PMH_BUF)
            if bear_stack and near_ema9 and below_pml:
                in_short  = True
                entry_px  = price
                entry_dt  = dt
                entry_atr = atr_i
                sl        = price + ATR_SL * atr_i   # stop ABOVE entry
                tp        = price - ATR_TP * atr_i   # profit BELOW entry

    return long_trades, short_trades


# ── Summary printer ────────────────────────────────────────────────────────────

def print_trades(trades, label):
    if not trades:
        print(f"  {label}: none")
        return
    print(f"\n  {label}:")
    print(f"  {'Ticker':<8} {'Entry Date':<12} {'Exit Date':<12} {'Entry':>8} {'Exit':>8} {'PnL %':>8} {'Result':<8}  {'ATR':>6}")
    print("  " + "-" * 80)
    for t in sorted(trades, key=lambda x: x["Entry Date"]):
        print(f"  {t['Ticker']:<8} {t['Entry Date']:<12} {t['Exit Date']:<12} "
              f"{t['Entry']:>8.3f} {t['Exit']:>8.3f} {t['PnL %']:>+7.2f}% {t['Result']:<8}  {t['ATR']:>6.3f}")


def print_summary_row(label, trades):
    if not trades:
        return
    n    = len(trades)
    wins = sum(1 for t in trades if t["Result"] == "WIN")
    loss = sum(1 for t in trades if t["Result"] == "LOSS")
    be   = n - wins - loss
    net  = sum(t["PnL %"] for t in trades)
    wr   = wins / n * 100
    print(f"  {label}: {n} trades | WR: {wr:.1f}% | Net: {net:+.2f}% | {wins}W/{loss}L/{be}BE")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TJL Backtest via TradingView MCP")
    parser.add_argument("tickers", nargs="+", help="Tickers to backtest")
    parser.add_argument("--bars", type=int, default=400, help="Daily bars to fetch (default: 400)")
    parser.add_argument("--no-regime", action="store_true", help="Skip SPY/QQQ regime check")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers]

    log("=" * 80)
    log("TJL Backtest — TradingView MCP")
    log(f"Tickers: {', '.join(tickers)} | Bars: {args.bars} daily")
    log("Entry: EMA9>EMA20>EMA50 + |price-EMA9|≤0.2% + above PMH+$0.70 (LONG)")
    log("       EMA9<EMA20<EMA50 + |price-EMA9|≤0.2% + below PML-$0.70 (SHORT)")
    log("Exit:  SL=price±1.5×ATR | TP=price±3.0×ATR")
    log("=" * 80)

    # Regime check
    regime = "BULLISH"
    if not args.no_regime:
        log("\nChecking SPY/QQQ regime...")
        regime, details = check_regime()
        detail_str = "  ".join(f"{s} curr={c:.2f} prev={p:.2f} {'↑' if u else '↓'}" for s, c, p, u in details)
        log(f"  Regime: {regime}  [{detail_str}]")
    else:
        log("\nRegime check skipped (--no-regime) — defaulting to BULLISH")

    all_long_trades, all_short_trades = [], []

    for sym in tickers:
        log(f"\n{'─'*60}")
        log(f"  {sym}")
        try:
            bars = fetch_daily_bars(sym, count=args.bars)
            log(f"  Got {len(bars)} bars — calculating EMAs/ATR...")
            enriched = calc_emas_atr(bars)
            longs, shorts = run_backtest(sym, enriched, regime=regime)
            all_long_trades.extend(longs)
            all_short_trades.extend(shorts)
            log(f"  → LONG: {len(longs)} | SHORT: {len(shorts)}")
            for direction, trades in [("LONG", longs), ("SHORT", shorts)]:
                if trades:
                    for t in trades:
                        log(f"    {t['Entry Date']} → {t['Exit Date']}: {direction} {t['Entry']}→{t['Exit']} | {t['PnL %']:+.2f}% ({t['Result']})")
        except Exception as e:
            log(f"  ✗ ERROR: {e}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)

    for direction, trades in [("LONG", all_long_trades), ("SHORT", all_short_trades)]:
        if trades:
            print_trades(trades, direction)
            print_summary_row(direction, trades)

    # Combined totals
    all_trades = all_long_trades + all_short_trades
    if all_trades:
        n    = len(all_trades)
        wins = sum(1 for t in all_trades if t["Result"] == "WIN")
        loss = sum(1 for t in all_trades if t["Result"] == "LOSS")
        be   = n - wins - loss
        net  = sum(t["PnL %"] for t in all_trades)
        wr   = wins / n * 100
        print(f"\n  TOTAL: {n} trades | WR: {wr:.1f}% | Net PnL: {net:+.2f}% | {wins}W/{loss}L/{be}BE")

    print(f"\n✓ Done. Regime={regime} | {len(all_long_trades)}L/{len(all_short_trades)}S trades.")

if __name__ == "__main__":
    main()
