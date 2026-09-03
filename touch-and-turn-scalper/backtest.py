import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date as dt_date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TP_LEVEL = 0.382
RR_RATIO  = 2.0
OR_PCT    = 0.25

def is_trading_day(d):
    return d.weekday() < 5

def last_trading_day(ref):
    d = ref - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d

def trading_days(start, end):
    days = []
    d = start
    while d <= end:
        if is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days

def fetch_month_5min(ticker, end_date):
    end_dt   = datetime.combine(end_date, datetime.min.time().replace(tzinfo=ET), ET).replace(hour=16)
    start_dt = end_dt - timedelta(days=35)
    df = ticker.history(start=start_dt, end=end_dt, interval="5m", auto_adjust=True)
    if df.empty:
        return None
    df.index = df.index.tz_convert(ET) if df.index.tz else df.index.tz_localize(ET)
    return df

def fetch_daily_atr(ticker, trade_date, period=20):
    end_dt   = datetime.combine(trade_date, datetime.min.time().replace(tzinfo=ET), ET).replace(hour=16)
    start_dt = end_dt - timedelta(days=period*2)
    df = ticker.history(start=start_dt, end=end_dt, interval="1d", auto_adjust=True)
    if df.empty or len(df) < 15:
        return None
    high = df["High"]; low = df["Low"]; close = df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return float(tr.rolling(14).mean().iloc[-1])

def get_first_candle_15min(df_5m, trade_date):
    """Aggregate 5-min bars into the first 15-min candle (09:30-09:45 ET)."""
    trade_dt = pd.Timestamp(trade_date, tz="UTC").tz_convert(ET).normalize()
    df_day = df_5m[df_5m.index.normalize() == trade_dt]
    bars = df_day[(df_day.index.hour == 9) & (df_day.index.minute < 45)]
    bars = bars.head(3)
    if bars.empty:
        return None, None, None, None
    open_  = float(bars.iloc[0]["Open"])
    high_  = float(bars["High"].max())
    low_   = float(bars["Low"].min())
    close_ = float(bars.iloc[-1]["Close"])
    return open_, high_, low_, close_

def run_backtest(symbol, trade_days_list):
    ticker = yf.Ticker(symbol)
    df_5m  = fetch_month_5min(ticker, last_trading_day(dt_date.today()))
    if df_5m is None:
        return []
    results = []
    for trade_date in trade_days_list:
        atr = fetch_daily_atr(ticker, trade_date)
        if atr is None:
            continue
        threshold = atr * OR_PCT
        candle = get_first_candle_15min(df_5m, trade_date)
        if candle[0] is None:
            continue
        open_, high_, low_, close_ = candle
        candle_range = round(high_ - low_, 4)
        is_liq = candle_range >= threshold
        if is_liq:
            direction = "LONG" if close_ < open_ else "SHORT"
            entry = low_ if direction == "LONG" else high_
            tp    = round(low_ + (high_ - low_) * TP_LEVEL, 4)
            sl_dist = abs(tp - entry) / RR_RATIO
            sl = round(entry - sl_dist, 4) if direction == "LONG" else round(entry + sl_dist, 4)
            results.append({
                "date": str(trade_date),
                "atr14": round(atr, 2),
                "threshold": round(threshold, 2),
                "candle_range": round(candle_range, 2),
                "direction": direction,
                "entry": round(entry, 2),
                "tp": round(tp, 2),
                "sl": round(sl, 2),
                "is_liquidity": True,
                "candle_open": round(open_, 2),
                "candle_close": round(close_, 2),
            })
        else:
            results.append({
                "date": str(trade_date),
                "atr14": round(atr, 2),
                "threshold": round(threshold, 2),
                "candle_range": round(candle_range, 2),
                "direction": None,
                "is_liquidity": False,
                "candle_open": round(open_, 2),
                "candle_close": round(close_, 2),
            })
    return results

# ── Run ──────────────────────────────────────────────────────────────────────
end_date  = last_trading_day(dt_date.today())
start_date = end_date - timedelta(days=40)
days = trading_days(start_date, end_date)
print(f"Period: {start_date} to {end_date}  ({len(days)} trading days)\n")

symbols = ["META", "NFLX", "TSLA", "SPY"]
all_results = {}
for sym in symbols:
    print(f"Fetching {sym}...", flush=True)
    all_results[sym] = run_backtest(sym, days)
    liq = [r for r in all_results[sym] if r["is_liquidity"]]
    print(f"  {len(liq)}/{len(all_results[sym])} liquidity-candle days")

# ── Full table ────────────────────────────────────────────────────────────────
print("\n" + "="*110)
hdr = f"{'Date':<12} {'Sym':<6} {'Dir':<6} {'Entry':>8} {'TP':>8} {'SL':>8} {'ATR':>7} {'Thresh':>7} {'Range':>7} {'Liq'}"
print(hdr)
print("-"*110)
for sym in symbols:
    print(f"\n  -- {sym} --")
    for r in all_results[sym]:
        liq = "YES" if r["is_liquidity"] else "NO "
        if r["is_liquidity"]:
            print(f"{r['date']:<12} {sym:<6} {r['direction']:<6} {r['entry']:>8.2f} {r['tp']:>8.2f} {r['sl']:>8.2f} {r['atr14']:>7.2f} {r['threshold']:>7.2f} {r['candle_range']:>7.2f} {liq}")
        else:
            print(f"{r['date']:<12} {sym:<6} {'--':<6} {'--':>8} {'--':>8} {'--':>8} {r['atr14']:>7.2f} {r['threshold']:>7.2f} {r['candle_range']:>7.2f} {liq}")

# ── Summary ────────────────────────────────────────────────────────────────────
print("\n" + "="*50)
print("\nSUMMARY\n")
print(f"{'Symbol':<8} {'Total':>6} {'Liq':>5} {'Rate':>8} {'Long':>6} {'Short':>7}")
print("-"*46)
total_all, liq_all = 0, 0
for sym in symbols:
    res = all_results[sym]
    liq_days = [r for r in res if r["is_liquidity"]]
    longs  = [r for r in liq_days if r["direction"] == "LONG"]
    shorts = [r for r in liq_days if r["direction"] == "SHORT"]
    rate = len(liq_days)/len(res)*100 if res else 0
    total_all += len(res)
    liq_all += len(liq_days)
    print(f"{sym:<8} {len(res):>6} {len(liq_days):>5} {rate:>7.1f}%  {len(longs):>5}  {len(shorts):>6}")
print("-"*46)
print(f"{'TOTAL':<8} {total_all:>6} {liq_all:>5} {liq_all/total_all*100:>7.1f}%")
