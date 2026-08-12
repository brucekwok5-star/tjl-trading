#!/usr/bin/env python3
"""Debug v2: inspect what the PMH condition actually looks like for all tickers."""

import yfinance as yf
import pandas as pd
import numpy as np

TICKERS = ["9618.HK", "3690.HK", "1211.HK", "2259.HK", "2899.HK", "2828.HK", "3033.HK"]

for ticker in TICKERS:
    ticker_raw = ticker.replace(".HK", "")
    tk = yf.Ticker(ticker)
    df = tk.history(period="2y", auto_adjust=True).tail(300).reset_index()

    df["EMA9"]  = df["Close"].ewm(span=9,  adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    tr1   = high - low
    tr2   = abs(high - close.shift(1))
    tr3   = abs(low  - close.shift(1))
    tr    = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=14).mean()
    # PMH: 5-day rolling high (prior day)
    df["PMH"] = df["High"].rolling(window=5).max().shift(1)
    # Also compute: price distance from PMH (in ATR units)
    df["dist_to_pmh"] = (df["Close"] - df["PMH"]) / df["ATR"]

    df = df.iloc[60:].reset_index(drop=True)

    bull_stack = (df["EMA9"] > df["EMA20"]) & (df["EMA20"] > df["EMA50"])
    near_ema9  = abs(df["Close"] - df["EMA9"]) / df["EMA9"] <= 0.002

    # relaxed PMH: price >= PMH - 1.0*ATR (within 1 ATR of making new high)
    near_pmh_relaxed = df["Close"] >= (df["PMH"] - 1.0 * df["ATR"])

    # even more relaxed: price within 2% of PMH
    near_pmh_pct = df["Close"] >= (df["PMH"] * 0.98)

    # How many bull_stack bars also satisfy each PMH variant?
    print(f"\n{ticker_raw}: bars={len(df)}")
    print(f"  Bull stack only:             {bull_stack.sum()}")
    print(f"  Bull + NearEMA9:             {(bull_stack & near_ema9).sum()}")
    print(f"  Bull + NearEMA9 + near_PMH(relaxed, -1ATR): {(bull_stack & near_ema9 & near_pmh_relaxed).sum()}")
    print(f"  Bull + NearEMA9 + near_PMH(2% of PMH):      {(bull_stack & near_ema9 & near_pmh_pct).sum()}")

    # Show dist_to_pmh stats for bull_stack bars
    bs_df = df[bull_stack]
    if not bs_df.empty:
        print(f"  Bull-stack bars: dist_to_PMH stats (Close-PMH)/ATR:")
        print(f"    min={bs_df['dist_to_pmh'].min():.2f}, max={bs_df['dist_to_pmh'].max():.2f}, "
              f"median={bs_df['dist_to_pmh'].median():.2f}")
        # Show bars closest to PMH
        top5 = bs_df.nsmallest(5, "dist_to_pmh")[["Date","Close","EMA9","ATR","PMH","dist_to_pmh"]]
        print(f"  Top-5 closest to PMH:")
        for _, r in top5.iterrows():
            print(f"    {str(r['Date'])[:10]}  Close={r['Close']:.2f}  EMA9={r['EMA9']:.2f}  "
                  f"ATR={r['ATR']:.3f}  PMH={r['PMH']:.2f}  dist/ATR={r['dist_to_pmh']:.2f}")
