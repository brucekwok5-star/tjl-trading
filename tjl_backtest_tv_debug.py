import json, subprocess, time, os
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
import pandas as pd
import numpy as np

TV_CLI = os.environ.get("TV_CLI", "/Users/jaydensmac/.local/bin/tv")
WARMUP = 60

def run_tv(args, timeout=60):
    r = subprocess.run([TV_CLI]+args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:200])
    return json.loads(r.stdout)

def fetch_bars(symbol, count=400):
    run_tv(["symbol", symbol], timeout=30)
    time.sleep(8)
    run_tv(["timeframe", "D"], timeout=20)
    time.sleep(3)
    d = run_tv(["ohlcv", "--count", str(count)], timeout=120)
    return d.get("bars") or d.get("data") or []

def condition_breakdown(symbol, bars):
    df = pd.DataFrame(bars)
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    df["ema9"]  = c.ewm(span=9,  adjust=False).mean()
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    df["atr"] = tr
    df["ph"] = h.shift(1)
    df["pl"] = l.shift(1)
    warm = df.iloc[WARMUP:].copy()

    warm["bull"]      = (warm["ema9"] > warm["ema20"]) & (warm["ema20"] > warm["ema50"])
    warm["bear"]      = (warm["ema9"] < warm["ema20"]) & (warm["ema20"] < warm["ema50"])
    warm["near"]      = (warm["ema9"] > 0) & ((warm["close"] - warm["ema9"]).abs() / warm["ema9"] <= 0.002)
    warm["above_pmh"] = warm["close"] > warm["ph"] + 0.70
    warm["below_pml"] = warm["close"] < warm["pl"] - 0.70
    warm["long_ok"]   = warm["bull"] & warm["near"] & warm["above_pmh"]
    warm["short_ok"]  = warm["bear"] & warm["near"] & warm["below_pml"]

    n = len(warm)
    print(f"  {symbol}: {n} bars after warmup | regime=BEARISH (LONG suppressed)")
    print(f"    Bull stack EMA9>EMA20>EMA50:  {int(warm['bull'].sum()):4d} bars")
    print(f"    Bear stack EMA9<EMA20<EMA50:  {int(warm['bear'].sum()):4d} bars")
    print(f"    Near EMA9 (within 0.2%):      {int(warm['near'].sum()):4d} bars")
    print(f"    Above PMH+$0.70 (LONG):       {int(warm['above_pmh'].sum()):4d} bars")
    print(f"    Below PML-$0.70 (SHORT):      {int(warm['below_pml'].sum()):4d} bars")
    print(f"    LONG  (bull+nar+pmh):         {int(warm['long_ok'].sum()):4d} bars")
    print(f"    SHORT (bear+nar+pml):          {int(warm['short_ok'].sum()):4d} bars")

    # Bars close to triggering SHORT (bear + near, missing only PML)
    close_short = warm[warm["bear"] & warm["near"] & ~warm["below_pml"]]
    if not close_short.empty:
        print(f"    Bear+Near (SHORT 2/3, missing PML): {len(close_short)} bars | top 3 closest:")
        for _, r in close_short.nlargest(3, "below_pml").iterrows():
            dt = str(r.name)[:10]
            print(f"      {dt}  close={r['close']:.2f}  ema9={r['ema9']:.2f}  "
                  f"pml={r['pl']:.2f}  pml_dist={r['close']-r['pl']:.2f}  need={r['pl']-0.70:.2f}")

    # Bars close to triggering LONG (bull + near, missing only PMH)
    close_long = warm[warm["bull"] & warm["near"] & ~warm["above_pmh"]]
    if not close_long.empty:
        print(f"    Bull+Near (LONG 2/3, missing PMH):  {len(close_long)} bars | top 3 closest:")
        for _, r in close_long.nlargest(3, "above_pmh").iterrows():
            dt = str(r.name)[:10]
            print(f"      {dt}  close={r['close']:.2f}  ema9={r['ema9']:.2f}  "
                  f"pmh={r['ph']:.2f}  pmh_dist={r['close']-r['ph']:.2f}  need>={r['ph']+0.70:.2f}")

if __name__ == "__main__":
    for sym in ["INTC", "META", "ARM", "QLB"]:
        print(f"\n{sym}:")
        try:
            bars = fetch_bars(sym, 400)
            print(f"  got {len(bars)} bars, last_close={float(bars[-1]['close']):.2f}")
            condition_breakdown(sym, bars)
        except Exception as e:
            print(f"  ERROR: {e}")
