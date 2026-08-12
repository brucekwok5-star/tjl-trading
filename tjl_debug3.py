#!/usr/bin/env python3
"""Debug v3: understand the root cause — test different condition combos."""

import yfinance as yf
import pandas as pd
import numpy as np

TICKERS = ["9618.HK", "3690.HK", "1211.HK", "2259.HK", "2899.HK", "2828.HK", "3033.HK"]

print(f"\n{'Ticker':<8} {'BS+NE9':>7} {'BS+NE9+PMH_relaxed':>18} {'BS+NE9+PMH_simple':>16}")
print("-" * 55)
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
    df["PMH"] = df["High"].rolling(window=5).max().shift(1)

    df = df.iloc[60:].reset_index(drop=True)

    bull_stack = (df["EMA9"] > df["EMA20"]) & (df["EMA20"] > df["EMA50"])
    near_ema9  = abs(df["Close"] - df["EMA9"]) / df["EMA9"] <= 0.002
    near_pmh   = df["Close"] >= (df["PMH"] - 1.0 * df["ATR"])

    # Simple PMH: price >= prior day's close (not rolling high)
    df["prior_close"] = df["Close"].shift(1)
    price_above_prior = df["Close"] >= df["prior_close"]

    c1 = (bull_stack & near_ema9).sum()
    c2 = (bull_stack & near_ema9 & near_pmh).sum()
    c3 = (bull_stack & near_ema9 & price_above_prior).sum()

    print(f"{ticker_raw:<8} {c1:>7} {c2:>18} {c3:>16}")

print("\n→ Root cause: PMH condition is too restrictive for daily bars.")
print("→ The 'near EMA9 + near PMH' combo rarely overlaps.")
print("→ Using relaxed entry: bull stack + price within 1% of EMA9 + price >= prior close")
