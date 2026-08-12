#!/usr/bin/env python3
"""Debug: check why no TJL signals fire — inspect entry condition components."""

import yfinance as yf
import pandas as pd
import numpy as np

TICKERS = ["9618.HK", "3690.HK", "1211.HK", "2259.HK", "2899.HK", "2828.HK", "3033.HK"]

for ticker in TICKERS[:2]:  # debug first 2 tickers
    ticker_raw = ticker.replace(".HK", "")
    print(f"\n{'='*60}\n{ticker_raw}")
    tk = yf.Ticker(ticker)
    df = tk.history(period="2y", auto_adjust=True)
    df = df.tail(260).reset_index()

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
    df["PMH"] = df["High"].rolling(window=5).max().shift(1)

    df = df.iloc[60:].reset_index(drop=True)

    # Check how many bars pass each condition
    bull_stack  = (df["EMA9"] > df["EMA20"]) & (df["EMA20"] > df["EMA50"])
    near_ema9   = abs(df["Close"] - df["EMA9"]) / df["EMA9"] <= 0.002
    above_pmh   = df["Close"] > df["PMH"] + 0.70
    has_atr     = ~df["ATR"].isna()

    print(f"  Total bars: {len(df)}")
    print(f"  Bull stack count:    {bull_stack.sum()}")
    print(f"  Near EMA9 (0.2%) count: {near_ema9.sum()}")
    print(f"  Above PMH+0.7 count: {above_pmh.sum()}")
    print(f"  Has ATR count:       {has_atr.sum()}")

    # Find bars that pass bull_stack + near_ema9 (the strictest two)
    both = bull_stack & near_ema9
    print(f"  Bull + NearEMA9:     {both.sum()}")
    print(f"  Bull + NearEMA9 + AbovePMH: {(bull_stack & near_ema9 & above_pmh).sum()}")

    # Show price/EMA9/ATR/PMH for bars that pass bull_stack + near_ema9
    subset = df[both].copy()
    if not subset.empty:
        print(f"\n  Sample rows (Close / EMA9 / ATR / PMH / PMH+0.7):")
        for _, row in subset.head(5).iterrows():
            print(f"    {row['Date'].date()}  Close={row['Close']:.2f}  EMA9={row['EMA9']:.2f}  "
                  f"ATR={row['ATR']:.2f}  PMH={row['PMH']:.2f}  PMH+0.7={row['PMH']+0.7:.2f}")
