#!/usr/bin/env python3
"""
TJL (Trend Join Long) Backtest — Futu Real-Time Data
Uses Futu OpenD (HK.XXXXX format) for live HK stock data.
"""
import futu as ft
import pandas as pd
import numpy as np
import time
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
PMH_BUF = 0.70   # HKD buffer above PMH
ATR_SL   = 1.5   # SL = entry - ATR_SL * ATR
ATR_TP   = 3.0   # TP = entry + ATR_TP * ATR
ATR_PERIOD = 14
WARMUP    = 60   # bars before starting signal checks

TICKERS_RAW = ["09618","03690","01211","02259","02899","02828","03308","03033"]
TICKERS     = [f"HK.{t}" for t in TICKERS_RAW]

def futu_ohlcv(code, ktype=ft.KLType.K_DAY, count=250):
    """Fetch daily OHLCV from Futu OpenD. Returns DataFrame or None."""
    ret, df, _ = quote_ctx.request_history_kline(code, ktype=ktype, max_count=count)
    if ret != 0 or df is None or df.empty:
        return None
    df = df.sort_values('time_key').reset_index(drop=True)
    df = df.rename(columns={'time_key': 'date'})
    df['date'] = pd.to_datetime(df['date'])
    return df

def calc_emas(df):
    df['EMA9']  = df['close'].ewm(span=9,  adjust=False).mean()
    df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    return df

def calc_atr(df, period=ATR_PERIOD):
    high  = df['high'].values
    low   = df['low'].values
    close = df['close'].values
    trs = []
    for i in range(1, len(high)):
        tr = max(high[i] - low[i],
                 abs(high[i] - close[i-1]),
                 abs(low[i]  - close[i-1]))
        trs.append(tr)
    # Pad first row with NaN
    atr = [np.nan] + pd.Series(trs).rolling(period).mean().tolist()
    df['ATR'] = atr
    return df

def futu_realtime_quote(code):
    """Get current real-time quote from Futu."""
    ret, df = quote_ctx.get_stock_quote([code])
    if ret != 0 or df is None or df.empty:
        return None
    return df.iloc[0]

print(f"{'='*70}")
print(f"  TJL Backtest — Futu Real-Time Data")
print(f"  {datetime.now(HKT).strftime('%Y-%m-%d %H:%M HKT')}")
print(f"{'='*70}\n")

# Connect once
quote_ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
time.sleep(0.5)  # let connection settle

results    = []
all_trades = []

for ticker_raw, ticker_futu in zip(TICKERS_RAW, TICKERS):
    print(f"[{ticker_raw}] Fetching data from Futu...", end=" ", flush=True)

    df = futu_ohlcv(ticker_futu, count=300)
    if df is None or len(df) < 80:
        print(f"FAILED (only {len(df) if df is not None else 0} bars)")
        results.append({"Ticker": ticker_raw, "Status": "NO DATA"})
        continue

    df = calc_emas(df)
    df = calc_atr(df)
    closes = df['close'].values
    highs  = df['high'].values
    ema9   = df['EMA9'].values
    ema20  = df['EMA20'].values
    ema50  = df['EMA50'].values
    atr    = df['ATR'].values

    print(f"{len(df)} bars OK | Running backtest...")

    trades     = []
    in_trade   = False
    entry_price = entry_date = sl_price = tp_price = None

    for i in range(WARMUP, len(df)):
        price    = closes[i]
        date_val = df['date'].iloc[i]
        e9, e20, e50, a = ema9[i], ema20[i], ema50[i], atr[i]

        if np.isnan(e9) or np.isnan(e20) or np.isnan(e50) or np.isnan(a):
            continue

        if not in_trade:
            # ── Entry signals ─────────────────────────────────────────────
            # 1. Bullish EMA stack
            if not (e9 > e20 > e50):
                continue
            # 2. Price within 1.5% of EMA9 (pullback zone)
            if abs(price - e9) / e9 > 0.015:
                continue
            # 3. Above PMH: use prior 5-day high as proxy
            pmh = highs[max(0, i-5):i].max()
            if price < pmh + PMH_BUF:
                continue

            # ── Execute trade ─────────────────────────────────────────────
            in_trade    = True
            entry_price = price
            entry_date  = date_val
            sl_price    = price - ATR_SL * a
            tp_price    = price + ATR_TP * a

        else:
            # ── Exit checks ────────────────────────────────────────────────
            exit_reason = exit_price = None
            high_i = highs[i]
            low_i  = df['low'].values[i]

            if low_i  <= sl_price:
                exit_reason = "SL"; exit_price = sl_price
            elif high_i >= tp_price:
                exit_reason = "TP"; exit_price = tp_price

            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                result  = "WIN" if pnl_pct > 0.05 else ("LOSS" if pnl_pct < -0.05 else "BE")
                trades.append({
                    "Ticker":     ticker_raw,
                    "Entry Date": str(date_val.date()) if hasattr(date_val, 'date') else str(date_val),
                    "Exit Date":  str(date_val.date()) if hasattr(date_val, 'date') else str(date_val),
                    "Entry":      round(entry_price, 2),
                    "Exit":       round(exit_price, 2),
                    "PnL %":      round(pnl_pct, 2),
                    "Result":     exit_reason,
                    "ATR":        round(a, 3),
                })
                in_trade = False

    all_trades.extend(trades)
    n = len(trades)
    if n == 0:
        results.append({"Ticker": ticker_raw, "Status": "OK", "Trades": 0, "Wins": 0,
                        "Win Rate": "N/A", "Net PnL %": "N/A", "Signals": "none"})
        print(f"  → 0 trades")
        continue

    wins    = sum(1 for t in trades if t["Result"] == "WIN")
    net_pnl = sum(t["PnL %"] for t in trades)
    wr      = wins / n * 100

    results.append({
        "Ticker":    ticker_raw,
        "Status":    "OK",
        "Trades":    n,
        "Wins":      wins,
        "Losses":    n - wins,
        "Win Rate":  f"{wr:.1f}%",
        "Net PnL %": f"{net_pnl:.2f}%",
    })
    print(f"  → {n} trades | WR {wr:.0f}% | Net PnL {net_pnl:+.2f}%")

quote_ctx.close()
time.sleep(0.3)

# ── Summary ────────────────────────────────────────────────────────────────────
ok  = [r for r in results if r.get("Status") == "OK"]
total_trades = sum(r["Trades"] for r in ok)
total_wins   = sum(r["Wins"]   for r in ok)
net_pnl_sum  = sum(float(r["Net PnL %"].replace("%","")) for r in ok if r.get("Net PnL %","N/A") != "N/A")
wr_total     = total_wins / total_trades * 100 if total_trades else 0

print(f"\n{'='*70}")
print(f"  TJL BACKTEST — SUMMARY (Futu Real-Time Data)")
print(f"{'='*70}")
print(f"{'Ticker':<8} {'Trades':>6} {'Wins':>5} {'Loss':>5} {'Win Rate':>10} {'Net PnL %':>10}")
print("-"*70)
for r in results:
    trades_n = r.get("Trades", 0)
    print(f"{r['Ticker']:<8} {trades_n:>6} {r.get('Wins',0):>5} {r.get('Losses',0):>5} "
          f"{r.get('Win Rate','N/A'):>10} {r.get('Net PnL %','N/A'):>10}")
print("-"*70)
print(f"{'TOTAL':<8} {total_trades:>6} {total_wins:>5} {'—':>5} {f'{wr_total:.1f}%':>10} {f'{net_pnl_sum:.2f}%':>10}")
print()

# ── All Trades ─────────────────────────────────────────────────────────────────
if all_trades:
    print(f"{'='*70}")
    print(f"  ALL TRADES")
    print(f"{'='*70}")
    print(f"{'Ticker':<8} {'Entry Date':<12} {'Exit Date':<12} {'Entry':>8} {'Exit':>8} {'PnL %':>8} {'Result':<6} ATR")
    print("-"*70)
    for t in all_trades:
        print(f"{t['Ticker']:<8} {t['Entry Date']:<12} {t['Exit Date']:<12} "
              f"{t['Entry']:>8.2f} {t['Exit']:>8.2f} {t['PnL %']:>8.2f}% {t['Result']:<6} {t['ATR']:.3f}")

    # ── Real-time current price via Futu ────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  REAL-TIME QUOTES (Futu OpenD)")
    print(f"{'='*70}")
    print(f"{'Ticker':<8} {'Last Price':>10} {'Change %':>10} {'Volume':>12}")
    print("-"*70)
    quote_ctx2 = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    time.sleep(0.3)
    ret, q = quote_ctx2.get_stock_quote(TICKERS)
    if ret == 0 and q is not None:
        for _, row in q.iterrows():
            print(f"{row['code'].replace('HK.',''):<8} {row['last_price']:>10.2f} "
                  f"{row['change_rate']:>10.2f}% {row['volume']:>12,.0f}")
    quote_ctx2.close()

print(f"\n✅ Backtest complete — {len(all_trades)} total trades across {len(ok)} tickers.")
print(f"   Data source: Futu OpenD (real-time HK market data)")