#!/usr/bin/env python3
"""
TJL (Trend Join Long) Backtest — Final Version
Entry conditions:
  1. EMA9 > EMA20 > EMA50  (bullish stack)
  2. Close within 1.5% of EMA9  (price at EMA pullback zone)
  3. Close >= prior day's close  (momentum confirmation — proxy for PMH break)
Stop Loss : price - 1.5 * ATR
Take Profit: price + 3.0 * ATR
Result classification: WIN (>+0.05%), LOSS (<-0.05%), BREAK-EVEN
"""

import yfinance as yf
import pandas as pd
import numpy as np

TICKERS     = ["9618.HK", "3690.HK", "1211.HK", "2259.HK", "2899.HK", "2828.HK", "3033.HK"]
BARS        = 210
ATR_PERIOD  = 14
EMA9_WIN    = 0.015   # 1.5% — pullback tolerance around EMA9
START_I     = 60      # EMA50 warmup bars to skip

# ─────────────────────────────────────────────────────────────────────────────
def fetch_data(ticker):
    tk = yf.Ticker(ticker)
    df = tk.history(period="2y", auto_adjust=True)
    if df.empty:
        return None
    df = df.tail(BARS + 80).reset_index()
    return df

def calc_emas(df):
    df["EMA9"]  = df["Close"].ewm(span=9,  adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    return df

def calc_atr(df, period=14):
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    tr1   = high - low
    tr2   = abs(high - close.shift(1))
    tr3   = abs(low  - close.shift(1))
    tr    = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(ticker_raw, df):
    df = calc_emas(df)
    df["ATR"]         = calc_atr(df, ATR_PERIOD)
    df["Prior_Close"] = df["Close"].shift(1)

    trades      = []
    in_trade    = False
    entry_price = 0.0
    entry_date  = None
    sl_price    = 0.0
    tp_price    = 0.0

    close_arr      = df["Close"].values
    ema9_arr       = df["EMA9"].values
    ema20_arr      = df["EMA20"].values
    ema50_arr      = df["EMA50"].values
    high_arr       = df["High"].values
    low_arr        = df["Low"].values
    atr_arr        = df["ATR"].values
    prior_close    = df["Prior_Close"].values
    date_arr       = df["Date"].values

    for i in range(START_I, len(df)):
        price       = close_arr[i]
        ema9        = ema9_arr[i]
        ema20       = ema20_arr[i]
        ema50       = ema50_arr[i]
        high        = high_arr[i]
        low         = low_arr[i]
        atr         = atr_arr[i]
        prev_close  = prior_close[i]
        date        = date_arr[i]

        if np.isnan(ema9) or np.isnan(ema20) or np.isnan(ema50) or np.isnan(atr):
            continue

        # ── EXIT logic ────────────────────────────────────────────────────────
        if in_trade:
            exit_price = None
            exit_date  = date

            if low <= sl_price:
                exit_price = sl_price
            elif high >= tp_price:
                exit_price = tp_price

            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                result  = "WIN" if pnl_pct > 0.05 else ("LOSS" if pnl_pct < -0.05 else "BREAK-EVEN")
                trades.append({
                    "Ticker":     ticker_raw,
                    "Entry Date": str(entry_date)[:10],
                    "Exit Date":  str(exit_date)[:10],
                    "Entry":      round(entry_price, 3),
                    "Exit":       round(exit_price, 3),
                    "PnL %":      round(pnl_pct, 2),
                    "Result":     result,
                    "ATR":        round(atr, 3),
                })
                in_trade = False

        # ── ENTRY logic ───────────────────────────────────────────────────────
        if not in_trade:
            bull_stack  = (ema9 > ema20 > ema50)
            near_ema9   = abs(price - ema9) / ema9 <= EMA9_WIN
            above_prior = (not np.isnan(prev_close)) and (price >= prev_close)

            if bull_stack and near_ema9 and above_prior:
                in_trade    = True
                entry_price = price
                entry_date  = date
                sl_price    = price - 1.5 * atr
                tp_price    = price + 3.0 * atr

    return trades

# ─────────────────────────────────────────────────────────────────────────────
def main():
    all_trades = []
    results    = []

    for ticker in TICKERS:
        ticker_raw = ticker.replace(".HK", "")
        print(f"\n{'='*60}\n  {ticker_raw} — fetching data...", flush=True)
        df = fetch_data(ticker)
        if df is None or len(df) < 100:
            print(f"  {ticker_raw} — NO DATA", flush=True)
            results.append({"Ticker": ticker_raw, "Status": "NO DATA", "Trades": 0, "Wins": 0,
                             "Losses": 0, "BE": 0, "Win Rate": "N/A", "Net PnL %": "N/A"})
            continue

        print(f"  {ticker_raw} — {len(df)} bars, backtesting...", flush=True)
        trades = run_backtest(ticker_raw, df)
        all_trades.extend(trades)

        n = len(trades)
        if n == 0:
            results.append({"Ticker": ticker_raw, "Status": "OK", "Trades": 0, "Wins": 0,
                             "Losses": 0, "BE": 0, "Win Rate": "N/A", "Net PnL %": "N/A"})
            continue

        wins    = sum(1 for t in trades if t["Result"] == "WIN")
        losses  = sum(1 for t in trades if t["Result"] == "LOSS")
        bes     = sum(1 for t in trades if t["Result"] == "BREAK-EVEN")
        net_pnl = sum(t["PnL %"] for t in trades)
        wr      = wins / n * 100

        results.append({"Ticker": ticker_raw, "Status": "OK", "Trades": n, "Wins": wins,
                         "Losses": losses, "BE": bes, "Win Rate": f"{wr:.1f}%",
                         "Net PnL %": f"{net_pnl:.2f}%"})
        print(f"  {ticker_raw} — {n} trades | WR: {wr:.1f}% | Net PnL: {net_pnl:+.2f}%", flush=True)

    # ── Per-ticker summary ────────────────────────────────────────────────────
    print("\n" + "=" * 108)
    print("  TJL BACKTEST — PER-TICKER SUMMARY  (EMA9>EMA20>EMA50 | Close within 1.5% of EMA9 | Close≥PriorClose)")
    print("  Entry: price  |  SL: price−1.5×ATR  |  TP: price+3.0×ATR")
    print("=" * 108)
    hdr = f"{'Ticker':<8} {'Trades':>6} {'Wins':>5} {'Loss':>5} {'BE':>4} {'Win Rate':>10} {'Net PnL %':>12} {'Status':<6}"
    print(hdr)
    print("-" * 108)
    for r in results:
        print(f"{r['Ticker']:<8} {r.get('Trades',0):>6} {r.get('Wins',0):>5} {r.get('Losses',0):>5} "
              f"{r.get('BE',0):>4} {r.get('Win Rate','N/A'):>10} {r.get('Net PnL %','N/A'):>12} {r.get('Status','?'):<6}")

    ok             = [r for r in results if r.get("Status") == "OK"]
    total_trades   = sum(r.get("Trades", 0) for r in ok)
    total_wins     = sum(r.get("Wins",   0) for r in ok)
    total_losses   = sum(r.get("Losses", 0) for r in ok)
    total_be       = sum(r.get("BE",     0) for r in ok)
    net_pnl_total  = sum(float(r.get("Net PnL %","0").replace("%","")) for r in ok
                         if r.get("Net PnL %","N/A") != "N/A")
    wr_total       = total_wins / total_trades * 100 if total_trades else 0

    print("-" * 108)
    print(f"{'TOTAL':<8} {total_trades:>6} {total_wins:>5} {total_losses:>5} {total_be:>4} "
          f"{f'{wr_total:.1f}%':>10} {f'{net_pnl_total:.2f}%':>12}")

    # ── All trades ────────────────────────────────────────────────────────────
    if all_trades:
        print("\n" + "=" * 100)
        print("  ALL TRADES")
        print("=" * 100)
        print(f"{'Ticker':<8} {'Entry Date':<12} {'Exit Date':<12} {'Entry':>8} {'Exit':>8} {'PnL %':>8} {'Result':<12}  {'ATR':>6}")
        print("-" * 100)
        for t in all_trades:
            print(f"{t['Ticker']:<8} {t['Entry Date']:<12} {t['Exit Date']:<12} "
                  f"{t['Entry']:>8.3f} {t['Exit']:>8.3f} {t['PnL %']:>+7.2f}% {t['Result']:<12}  {t['ATR']:>6.3f}")

    print(f"\n✓ Done. {len(all_trades)} total trades | {len(ok)}/{len(TICKERS)} tickers had data.")

if __name__ == "__main__":
    main()
