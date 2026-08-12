#!/usr/bin/env python3
"""
TJL Backtest — TV MCP single-session
====================================
One TV session; sequentially set symbol, fetch bars, switch, repeat.
Avoids re-launching/reconnecting between tickers.
"""
import json, os, subprocess, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TV_CLI = os.environ.get("TV_CLI", "/Users/jaydensmac/.local/bin/tv")
PMH_BUF  = 0.70
ATR_SL   = 1.5
ATR_TP   = 3.0
ATR_PERIOD = 14
EMA9_WIN = 0.002
WARMUP   = 60

def log(msg):
    print(f"[{datetime.now(ET):%H:%M:%S ET}] {msg}", flush=True)

def run_tv(args, timeout=60):
    cmd = [TV_CLI] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"tv {args!r} failed ({r.returncode}): {r.stderr[:200]}")
    try:
        return json.loads(r.stdout)
    except:
        raise RuntimeError(f"tv {args!r} non-JSON: {r.stdout[:200]}")

def check_regime():
    details = []
    for sym in ("SPY", "QQQ"):
        try:
            run_tv(["symbol", sym], timeout=30)
            time.sleep(2)
            run_tv(["timeframe", "D"], timeout=20)
            time.sleep(2)
            d = run_tv(["ohlcv", "--count", "5"], timeout=60)
            bars = d.get("bars") or d.get("data") or []
            if len(bars) >= 2:
                curr = float(bars[-1]["close"])
                prev = float(bars[-2]["close"])
                details.append((sym, curr, prev, curr > prev))
        except Exception as e:
            details.append((sym, 0, 0, False))
    if details and all(d[3] for d in details): return "BULLISH", details
    elif details and any(not d[3] for d in details): return "BEARISH", details
    return "UNKNOWN", details

def fetch_bars_for_symbol(symbol, count=400):
    """Switch chart to symbol, switch to daily TF, return bars."""
    # Switch symbol
    resp = run_tv(["symbol", symbol], timeout=30)
    # Give TV extra time to actually rebind the chart
    time.sleep(8)

    # Verify chart is on right symbol by reading quote price
    try:
        q = run_tv(["quote"], timeout=15)
        actual = (q.get("symbol") or "").upper()
        log(f"    chart now on: {actual}")
    except:
        log(f"    quote check failed, continuing...")

    # Switch to daily TF
    run_tv(["timeframe", "D"], timeout=20)
    time.sleep(3)

    # Fetch bars
    data = run_tv(["ohlcv", "--count", str(count)], timeout=120)
    bars = data.get("bars") or data.get("data") or []
    if not bars:
        raise RuntimeError(f"no bars returned for {symbol}")
    last_close = float(bars[-1]["close"])
    log(f"    {symbol}: {len(bars)} bars | close={last_close:.2f}")
    return bars

def calc_emas_atr(bars):
    import pandas as pd, numpy as np
    df = pd.DataFrame(bars)
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    df["ema9"]  = c.ewm(span=9,  adjust=False).mean()
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    pc = c.shift(1)
    tr1 = h - l
    tr2 = (h - pc).abs()
    tr3 = (l - pc).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"]      = tr.rolling(ATR_PERIOD).mean()
    df["prev_high"] = h.shift(1)
    df["prev_low"]  = l.shift(1)
    return df.to_dict("records")

def fmt(ts):
    try:
        return datetime.fromtimestamp(int(ts), ET).strftime("%Y-%m-%d")
    except:
        return str(ts)[:10]

def run_backtest(symbol, bars, regime):
    import numpy as np
    closes = np.array([float(b["close"]) for b in bars])
    highs  = np.array([float(b["high"])  for b in bars])
    lows   = np.array([float(b["low"])   for b in bars])
    ema9   = np.array([float(b["ema9"])  for b in bars], dtype=float)
    ema20  = np.array([float(b["ema20"]) for b in bars], dtype=float)
    ema50  = np.array([float(b["ema50"]) for b in bars], dtype=float)
    atr    = np.array([float(b["atr"])   for b in bars], dtype=float)
    ph     = np.array([float(b["prev_high"]) for b in bars], dtype=float)
    pl     = np.array([float(b["prev_low"])  for b in bars], dtype=float)
    dates  = [b.get("time") or "" for b in bars]

    longs, shorts = [], []
    in_long = in_short = False
    e_px = e_dt = e_atr = sl = tp = 0.0

    for i in range(WARMUP, len(bars)):
        price = closes[i]
        if np.isnan(ema9[i]) or np.isnan(atr[i]): continue
        hi, lo = highs[i], lows[i]
        dt = fmt(dates[i])

        # LONG exit
        if in_long:
            ep = sl if lo <= sl else (tp if hi >= tp else None)
            if ep:
                pnl = (ep - e_px) / e_px * 100
                res = "WIN" if pnl > 0.05 else ("LOSS" if pnl < -0.05 else "BE")
                longs.append({"Ticker": symbol, "Entry Date": e_dt, "Exit Date": dt,
                             "Entry": round(e_px,3), "Exit": round(ep,3), "PnL %": round(pnl,2),
                             "Result": res, "ATR": round(e_atr,3)})
                in_long = False

        # SHORT exit
        if in_short:
            ep = sl if hi >= sl else (tp if lo <= tp else None)
            if ep:
                pnl = (e_px - ep) / e_px * 100
                res = "WIN" if pnl > 0.05 else ("LOSS" if pnl < -0.05 else "BE")
                shorts.append({"Ticker": symbol, "Entry Date": e_dt, "Exit Date": dt,
                               "Entry": round(e_px,3), "Exit": round(ep,3), "PnL %": round(pnl,2),
                               "Result": res, "ATR": round(e_atr,3)})
                in_short = False

        # LONG entry
        if not in_long and regime == "BULLISH":
            if (ema9[i] > ema20[i] > ema50[i] and
                abs(price - ema9[i]) / ema9[i] <= EMA9_WIN and
                not np.isnan(ph[i]) and price >= ph[i] + PMH_BUF):
                in_long, e_px, e_dt, e_atr = True, price, dt, atr[i]
                sl = price - ATR_SL * atr[i]
                tp = price + ATR_TP * atr[i]

        # SHORT entry
        if not in_short and regime == "BEARISH":
            if (ema9[i] < ema20[i] < ema50[i] and
                abs(price - ema9[i]) / ema9[i] <= EMA9_WIN and
                not np.isnan(pl[i]) and price <= pl[i] - PMH_BUF):
                in_short, e_px, e_dt, e_atr = True, price, dt, atr[i]
                sl = price + ATR_SL * atr[i]
                tp = price - ATR_TP * atr[i]

    return longs, shorts

def print_trades(label, trades):
    if not trades: return
    print(f"\n  {label}:")
    print(f"  {'Ticker':<8} {'Entry Date':<12} {'Exit Date':<12} {'Entry':>8} {'Exit':>8} {'PnL %':>8} {'Result':<8}  {'ATR':>6}")
    print("  " + "-" * 80)
    for t in sorted(trades, key=lambda x: x["Entry Date"]):
        print(f"  {t['Ticker']:<8} {t['Entry Date']:<12} {t['Exit Date']:<12} "
              f"{t['Entry']:>8.3f} {t['Exit']:>8.3f} {t['PnL %']:>+7.2f}% {t['Result']:<8}  {t['ATR']:>6.3f}")

def summary_row(label, trades):
    if not trades: return
    n = len(trades)
    w = sum(1 for t in trades if t["Result"] == "WIN")
    l = sum(1 for t in trades if t["Result"] == "LOSS")
    be = n - w - l
    net = sum(t["PnL %"] for t in trades)
    print(f"  {label}: {n} trades | WR: {w/n*100:.1f}% | Net: {net:+.2f}% | {w}W/{l}L/{be}BE")

def main():
    tickers, bars_arg = [], 400
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--bars" and i+1 < len(sys.argv):
            bars_arg = int(sys.argv[i+1]); i += 2
        elif a.startswith("-"):
            i += 1  # skip unknown flags
        else:
            tickers.append(a.strip().upper()); i += 1
    if not tickers:
        tickers = ["INTC", "META", "ARM", "QLB"]

    log("=" * 75)
    log("TJL Backtest — TV MCP (single session)")
    log(f"Tickers: {tickers} | {bars_arg} daily bars")
    log("Entry LONG : EMA9>EMA20>EMA50 + |px-EMA9|≤0.2% + px>prev_high+$0.70")
    log("Entry SHORT: EMA9<EMA20<EMA50 + |px-EMA9|≤0.2% + px<prev_low-$0.70")
    log("Exit: SL=px±1.5×ATR | TP=px±3.0×ATR")
    log("=" * 75)

    # Regime check (one time, before looping tickers)
    log("\nRegime check (SPY/QQQ)...")
    regime, rdetails = check_regime()
    log(f"  Regime: {regime}  " + "  ".join(f"{s}={c:.2f}({p:.2f}{'↑' if u else '↓'})" for s,c,p,u in rdetails))

    all_l, all_s = [], []

    for sym in tickers:
        log(f"\n{'─'*60}")
        log(f"  {sym}")
        try:
            bars = fetch_bars_for_symbol(sym, count=bars_arg)
            enriched = calc_emas_atr(bars)
            longs, shorts = run_backtest(sym, enriched, regime)
            all_l.extend(longs); all_s.extend(shorts)
            log(f"  → LONG: {len(longs)} | SHORT: {len(shorts)}")
            for t in longs+shorts:
                log(f"    {t['Entry Date']}→{t['Exit Date']}: {'LONG' if t in longs else 'SHORT'} @ {t['Entry']} | {t['PnL %']:+.2f}% ({t['Result']}) ATR={t['ATR']}")
        except Exception as e:
            log(f"  ✗ ERROR: {e}")

    print("\n" + "=" * 75)
    print("  SUMMARY")
    print("=" * 75)
    print_trades("LONG", all_l); summary_row("LONG", all_l)
    print_trades("SHORT", all_s); summary_row("SHORT", all_s)
    all_t = all_l + all_s
    if all_t:
        n = len(all_t); w = sum(1 for t in all_t if t["Result"] == "WIN")
        l = sum(1 for t in all_t if t["Result"] == "LOSS")
        be = n-w-l; net = sum(t["PnL %"] for t in all_t)
        print(f"\n  TOTAL: {n} trades | WR: {w/n*100:.1f}% | Net: {net:+.2f}% | {w}W/{l}L/{be}BE")
    print(f"\n✓ Done. Regime={regime} | {len(all_l)}L/{len(all_s)}S | tickers={tickers}")

if __name__ == "__main__":
    main()
