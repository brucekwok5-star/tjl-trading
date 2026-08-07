#!/usr/bin/env python3
"""
TJL HK Model Parameter Tuning Engine
====================================
Grid-searches all 11 models (A–K) across key parameters using Futu OpenD data.
Goal: maximise win rate AND signal count simultaneously.

Usage:
  python3 tjl_tuning.py                          # full grid search all models
  python3 tjl_tuning.py --models A B H           # only specific models
  python3 tjl_tuning.py --days 252                # backtest period
  python3 tjl_tuning.py --min-signals 3           # min signals per config
"""

import futu as ft
from futu.quote.open_quote_context import OpenQuoteContext, KLType
ft.OpenQuoteContext = OpenQuoteContext  # alias for compatibility
import pandas as pd
import numpy as np
import time
import sys
import json
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from itertools import product
from multiprocessing import Pool, cpu_count

HKT = ZoneInfo("Asia/Hong_Kong")

# ── Default universe (8 HSI mega-caps) ──────────────────────────────────────
TICKERS = [
    ("00005", "HK.00005"),  # HSBC
    ("00700", "HK.00700"),  # Tencent
    ("00941", "HK.00941"),  # China Mobile
    ("01299", "HK.01299"),  # AIA
    ("01810", "HK.01810"),  # Xiaomi
    ("02318", "HK.02318"),  # Ping An
    ("03690", "HK.03690"),  # Meituan
    ("09988", "HK.09988"),  # Alibaba
]

WARMUP = 160   # bars before signals are checked (150 for SMA150/200 warmup)


# ════════════════════════════════════════════════════════════════════════════
# DATA
# ════════════════════════════════════════════════════════════════════════════

def fetch_daily(code, count=300):
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    time.sleep(0.3)
    ret, df, _ = ctx.request_history_kline(code, ktype=KLType.K_DAY, max_count=count)
    ctx.close()
    if ret != 0 or df is None or df.empty:
        return None
    df = df.sort_values('time_key').reset_index(drop=True)
    df = df.rename(columns={'time_key': 'date', 'close': 'Close', 'high': 'High',
                             'low': 'Low', 'open': 'Open', 'volume': 'Volume'})
    df['Close'] = df['Close'].astype(float)
    df['High']  = df['High'].astype(float)
    df['Low']   = df['Low'].astype(float)
    return df


def calc_indicators(df):
    c = df['Close'].values
    h = df['High'].values
    l = df['Low'].values
    v = df['Volume'].values

    # EMAs
    s = pd.Series(c)
    df['EMA9']  = s.ewm(span=9,  adjust=False).mean()
    df['EMA21'] = s.ewm(span=21, adjust=False).mean()
    df['EMA20'] = s.ewm(span=20, adjust=False).mean()
    df['EMA50'] = s.ewm(span=50, adjust=False).mean()
    df['EMA63'] = s.ewm(span=63, adjust=False).mean()

    # SMAs
    df['SMA150'] = s.rolling(150).mean()
    df['SMA200'] = s.rolling(200).mean()

    # Bollinger Bands (20, 2)
    bb_mid = s.rolling(20).mean()
    bb_std = s.rolling(20).std()
    df['BB20_MID'] = bb_mid
    df['BB20_UPPER'] = bb_mid + 2 * bb_std
    df['BB20_LOWER'] = bb_mid - 2 * bb_std

    # ATR
    trs = []
    for i in range(1, len(h)):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        trs.append(tr)
    df['ATR'] = [np.nan] + pd.Series(trs).rolling(14).mean().tolist()

    # RSI(14)
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI14'] = 100 - (100 / (1 + rs))

    # RSI(14) prev for crossover detection
    df['RSI14_PREV'] = df['RSI14'].shift(1)

    # VWAP (intraday proxy: rolling 20-day close avg)
    df['VWAP'] = s.rolling(20).mean()

    # Volume avg
    df['VOL20'] = pd.Series(v).rolling(20).mean()

    # 20-day high/low
    df['HIGH20'] = pd.Series(h).rolling(20).max()
    df['LOW20']  = pd.Series(l).rolling(20).min()

    # Prior close
    df['PREV_CLOSE'] = df['Close'].shift(1)

    return df


# ════════════════════════════════════════════════════════════════════════════
# ENTRY / EXIT HELPERS
# ════════════════════════════════════════════════════════════════════════════

def series_get(df, col, i):
    v = df[col].iloc[i]
    return float(v) if not np.isnan(v) else None


def run_backtest(df, entry_fn, sl_mult, tp_mult, min_signals=0):
    """
    Generic backtest: entry_fn(df, i) returns True/False.
    Returns dict with trades and stats.
    """
    c = df['Close'].values
    h = df['High'].values
    l = df['Low'].values
    dates = df['date'].values

    trades = []
    in_trade = False
    entry_price = entry_date = sl_price = tp_price = None

    for i in range(WARMUP, len(df)):
        price = c[i]
        atr = series_get(df, 'ATR', i)
        if atr is None or atr <= 0:
            continue

        # ── EXIT ────────────────────────────────────────────────────────────
        if in_trade:
            exit_price = None
            if l[i] <= sl_price:
                exit_price = sl_price
            elif h[i] >= tp_price:
                exit_price = tp_price

            if exit_price is not None:
                pnl = (exit_price - entry_price) / entry_price * 100
                result = "WIN" if pnl > 0.05 else ("LOSS" if pnl < -0.05 else "BE")
                trades.append({
                    "Entry":  round(entry_price, 2),
                    "Exit":   round(exit_price, 2),
                    "PnL%":   round(pnl, 3),
                    "Result": result,
                    "ATR":    round(atr, 3),
                })
                in_trade = False

        # ── ENTRY ────────────────────────────────────────────────────────────
        if not in_trade:
            if entry_fn(df, i):
                in_trade    = True
                entry_price = price
                entry_date  = str(dates[i])[:10]
                sl_price    = price - sl_mult * atr
                tp_price    = price + tp_mult * atr

    n = len(trades)
    if n < min_signals:
        return None

    wins  = sum(1 for t in trades if t["Result"] == "WIN")
    losses = sum(1 for t in trades if t["Result"] == "LOSS")
    wr     = wins / n * 100 if n > 0 else 0
    avg    = np.mean([t["PnL%"] for t in trades]) if trades else 0

    return {
        "n":       n,
        "wins":    wins,
        "losses":  losses,
        "wr":      round(wr, 2),
        "avg":     round(avg, 4),
        "trades":  trades,
    }


# ════════════════════════════════════════════════════════════════════════════
# MODEL A — Pullback (EMA9>EMA20>EMA50, near EMA9, above PMH)
# ════════════════════════════════════════════════════════════════════════════
def model_a_entry(df, i, near_pct, use_pmh_proxy):
    c   = series_get(df, 'Close',     i)
    e9  = series_get(df, 'EMA9',      i)
    e20 = series_get(df, 'EMA20',     i)
    e50 = series_get(df, 'EMA50',     i)
    h20 = series_get(df, 'HIGH20',    i)
    if None in [c, e9, e20, e50]: return False
    if not (e9 > e20 > e50): return False
    if abs(c - e9) / e9 > near_pct: return False
    if use_pmh_proxy and h20 is not None and c < h20: return False
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL B — Momentum (above SMA200, above PMH, above HOD)
# ════════════════════════════════════════════════════════════════════════════
def model_b_entry(df, i, use_pmh_proxy):
    c    = series_get(df, 'Close',   i)
    sma  = series_get(df, 'SMA200',  i)
    h20  = series_get(df, 'HIGH20',  i)
    if None in [c, sma]: return False
    if c <= sma: return False
    if use_pmh_proxy and h20 is not None and c < h20: return False
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL C — Volume-Confirmed Pullback (any EMA, near EMA9, vol spike, above PMH)
# ════════════════════════════════════════════════════════════════════════════
def model_c_entry(df, i, near_pct, vol_mult, use_pmh_proxy):
    c    = series_get(df, 'Close',   i)
    e9   = series_get(df, 'EMA9',    i)
    vol  = series_get(df, 'Volume',  i)
    vol20= series_get(df, 'VOL20',   i)
    h20  = series_get(df, 'HIGH20',  i)
    if None in [c, e9, vol, vol20]: return False
    if abs(c - e9) / e9 > near_pct: return False
    if vol < vol_mult * vol20: return False
    if use_pmh_proxy and h20 is not None and c < h20: return False
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL D — RSI Oversold Bounce (RSI crosses up through threshold from below)
# ════════════════════════════════════════════════════════════════════════════
def model_d_entry(df, i, rsi_thresh, near_vwap_pct, use_pmh_proxy):
    c     = series_get(df, 'Close',    i)
    rsi   = series_get(df, 'RSI14',    i)
    rsi_p = series_get(df, 'RSI14_PREV', i)
    vwap  = series_get(df, 'VWAP',     i)
    h20   = series_get(df, 'HIGH20',   i)
    if None in [c, rsi, rsi_p, vwap]: return False
    # RSI crosses UP through threshold
    if not (rsi_p < rsi_thresh <= rsi): return False
    if abs(c - vwap) / vwap > near_vwap_pct: return False
    if use_pmh_proxy and h20 is not None and c < h20: return False
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL E — 20D High Breakout (breakout + vol surge + RSI filter)
# ════════════════════════════════════════════════════════════════════════════
def model_e_entry(df, i, vol_mult, rsi_thresh, use_pmh_proxy):
    c     = series_get(df, 'Close',    i)
    h20   = series_get(df, 'HIGH20',   i)
    vol   = series_get(df, 'Volume',   i)
    vol20 = series_get(df, 'VOL20',    i)
    rsi   = series_get(df, 'RSI14',    i)
    if None in [c, h20, vol, vol20, rsi]: return False
    if c <= h20: return False
    if vol < vol_mult * vol20: return False
    if rsi <= rsi_thresh: return False  # LONG: RSI > threshold
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL F — RSI Trend Crossover (RSI crosses + EMA confirm)
# ════════════════════════════════════════════════════════════════════════════
def model_f_entry(df, i, rsi_thresh_long, rsi_thresh_short):
    c     = series_get(df, 'Close',     i)
    e9    = series_get(df, 'EMA9',      i)
    e20   = series_get(df, 'EMA20',     i)
    rsi   = series_get(df, 'RSI14',     i)
    rsi_p = series_get(df, 'RSI14_PREV', i)
    if None in [c, e9, e20, rsi, rsi_p]: return False
    # LONG: RSI crosses up through thresh AND EMA9 > EMA20
    long_sig  = (rsi_p < rsi_thresh_long <= rsi) and (e9 > e20)
    # SHORT: RSI crosses down through thresh AND EMA9 < EMA20
    short_sig = (rsi_p > rsi_thresh_short >= rsi) and (e9 < e20)
    return long_sig or short_sig


# ════════════════════════════════════════════════════════════════════════════
# MODEL G — ORB 5-bar + Vol Confirm (open range breakout)
# ════════════════════════════════════════════════════════════════════════════
def model_g_entry(df, i, vol_mult):
    c     = series_get(df, 'Close',    i)
    h5    = series_get(df, 'HIGH20',   i)   # reuse HIGH20 as 5-bar high proxy
    l5    = series_get(df, 'LOW20',    i)   # reuse LOW20 as 5-bar low proxy
    vol   = series_get(df, 'Volume',   i)
    vol20 = series_get(df, 'VOL20',    i)
    if None in [c, h5, l5, vol, vol20]: return False
    # Breakout above 5-bar high OR breakdown below 5-bar low
    breakout = (c > h5) or (c < l5)
    if not breakout: return False
    if vol < vol_mult * vol20: return False
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL H — Gold EMA/BB/VWAP (EMA9 crosses BB midline + price > EMA21 + > VWAP)
# ════════════════════════════════════════════════════════════════════════════
def model_h_entry(df, i):
    c      = series_get(df, 'Close',    i)
    e9     = series_get(df, 'EMA9',     i)
    e21    = series_get(df, 'EMA21',    i)
    bb_mid = series_get(df, 'BB20_MID', i)
    vwap   = series_get(df, 'VWAP',     i)
    e9_p   = series_get(df, 'EMA9',      i-1) if i > 0 else None
    bb_p   = series_get(df, 'BB20_MID', i-1) if i > 0 else None
    if None in [c, e9, e21, bb_mid, vwap, e9_p, bb_p]: return False
    # EMA9 crosses ABOVE BB midline
    crossed_up = (e9_p <= bb_p) and (e9 > bb_mid)
    price_ok   = (c > e21) and (c > vwap)
    return bool(crossed_up and price_ok)


# ════════════════════════════════════════════════════════════════════════════
# MODEL I — 63-WMA Swing (price > 63-WMA + RSI > 50 + close to 63-WMA)
# ════════════════════════════════════════════════════════════════════════════
def model_i_entry(df, i, near_pct):
    c     = series_get(df, 'Close',   i)
    e63   = series_get(df, 'EMA63',   i)   # use EMA63 as proxy for 63-WMA
    rsi   = series_get(df, 'RSI14',   i)
    if None in [c, e63, rsi]: return False
    if c <= e63: return False
    if rsi <= 50: return False
    if abs(c - e63) / e63 > near_pct: return False
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL J — Follow Money (SMA150/200, price near 150-DMA)
# ════════════════════════════════════════════════════════════════════════════
def model_j_entry(df, i, near_pct, vol_mult):
    c     = series_get(df, 'Close',   i)
    sma150= series_get(df, 'SMA150',  i)
    sma200= series_get(df, 'SMA200',  i)
    vol   = series_get(df, 'Volume',  i)
    vol20 = series_get(df, 'VOL20',   i)
    if None in [c, sma150, sma200, vol, vol20]: return False
    if not (c > sma200): return False
    if abs(c - sma150) / sma150 > near_pct: return False
    if vol < vol_mult * vol20: return False
    return True


# ════════════════════════════════════════════════════════════════════════════
# MODEL K — EMA/VWAP/BB Session Filter (same as H but kept as separate model)
# ════════════════════════════════════════════════════════════════════════════
def model_k_entry(df, i):
    return model_h_entry(df, i)


# ════════════════════════════════════════════════════════════════════════════
# GRID DEFINITIONS — key params per model
# ════════════════════════════════════════════════════════════════════════════

GRIDS = {

    "A": {
        "desc": "Pullback (EMA9>EMA20>EMA50, near EMA9, PMH)",
        "params": {
            "near_pct":      [0.005, 0.010, 0.015, 0.020, 0.025, 0.030],
            "use_pmh_proxy": [True],          # keep fixed
        },
        "sl_mult": [1.5],
        "tp_mult": [3.0],
        "entry_fn": lambda df, i, p: model_a_entry(df, i, near_pct=p["near_pct"],
                                                    use_pmh_proxy=p["use_pmh_proxy"]),
    },

    "B": {
        "desc": "Momentum (above SMA200, PMH)",
        "params": {
            "use_pmh_proxy": [True],
        },
        "sl_mult": [1.5],
        "tp_mult": [3.0],
        "entry_fn": lambda df, i, p: model_b_entry(df, i, use_pmh_proxy=p["use_pmh_proxy"]),
    },

    "C": {
        "desc": "Vol-Confirmed Pullback",
        "params": {
            "near_pct":      [0.010, 0.015, 0.020, 0.025, 0.030, 0.040],
            "vol_mult":      [1.5, 2.0, 2.5, 3.0],
            "use_pmh_proxy": [True],
        },
        "sl_mult": [1.5],
        "tp_mult": [3.0],
        "entry_fn": lambda df, i, p: model_c_entry(df, i, near_pct=p["near_pct"],
                                                    vol_mult=p["vol_mult"],
                                                    use_pmh_proxy=p["use_pmh_proxy"]),
    },

    "D": {
        "desc": "RSI Oversold Bounce",
        "params": {
            "rsi_thresh":      [25, 30, 35, 40],
            "near_vwap_pct":   [0.010, 0.015, 0.020, 0.030],
            "use_pmh_proxy":   [True],
        },
        "sl_mult": [1.0],
        "tp_mult": [1.5],
        "entry_fn": lambda df, i, p: model_d_entry(df, i, rsi_thresh=p["rsi_thresh"],
                                                    near_vwap_pct=p["near_vwap_pct"],
                                                    use_pmh_proxy=p["use_pmh_proxy"]),
    },

    "E": {
        "desc": "20D High Breakout",
        "params": {
            "vol_mult":    [1.0, 1.5, 2.0, 2.5],
            "rsi_thresh": [40, 45, 50, 55],
            "use_pmh_proxy": [False],  # breakout itself is the signal
        },
        "sl_mult": [1.0],
        "tp_mult": [1.5],
        "entry_fn": lambda df, i, p: model_e_entry(df, i, vol_mult=p["vol_mult"],
                                                    rsi_thresh=p["rsi_thresh"],
                                                    use_pmh_proxy=p["use_pmh_proxy"]),
    },

    "F": {
        "desc": "RSI Trend Crossover",
        "params": {
            "rsi_thresh_long":  [45, 50, 55, 60],
            "rsi_thresh_short": [35, 40, 45, 50],
        },
        "sl_mult": [1.0],
        "tp_mult": [1.5],
        "entry_fn": lambda df, i, p: model_f_entry(df, i,
                                                    rsi_thresh_long=p["rsi_thresh_long"],
                                                    rsi_thresh_short=p["rsi_thresh_short"]),
    },

    "G": {
        "desc": "ORB 5-bar + Vol",
        "params": {
            "vol_mult": [1.0, 1.2, 1.5, 2.0],
        },
        "sl_mult": [1.0],
        "tp_mult": [1.5],
        "entry_fn": lambda df, i, p: model_g_entry(df, i, vol_mult=p["vol_mult"]),
    },

    "H": {
        "desc": "Gold EMA/BB/VWAP",
        "params": {},
        "sl_mult": [0.75, 1.0, 1.25],
        "tp_mult": [1.0, 1.5, 2.0],
        "entry_fn": lambda df, i, p: model_h_entry(df, i),
    },

    "I": {
        "desc": "63-WMA Swing",
        "params": {
            "near_pct": [0.020, 0.030, 0.040, 0.050],
        },
        "sl_mult": [1.5],
        "tp_mult": [3.0],
        "entry_fn": lambda df, i, p: model_i_entry(df, i, near_pct=p["near_pct"]),
    },

    "J": {
        "desc": "Follow Money SMA150/200",
        "params": {
            "near_pct": [0.010, 0.015, 0.020, 0.030],
            "vol_mult": [1.0, 1.5, 2.0],
        },
        "sl_mult": [1.0],
        "tp_mult": [1.5],
        "entry_fn": lambda df, i, p: model_j_entry(df, i, near_pct=p["near_pct"],
                                                     vol_mult=p["vol_mult"]),
    },

    "K": {
        "desc": "EMA/VWAP/BB Session Filter",
        "params": {},
        "sl_mult": [0.75, 1.0, 1.25],
        "tp_mult": [1.0, 1.5, 2.0],
        "entry_fn": lambda df, i, p: model_k_entry(df, i),
    },
}


# ════════════════════════════════════════════════════════════════════════════
# SCORING — balance WR and signal count
# ════════════════════════════════════════════════════════════════════════════

def score(wr, n, min_n=3):
    """Combined score: win rate weighted by log(trade count)."""
    if n < min_n:
        return -999
    return wr * np.log(n + 1)


# ════════════════════════════════════════════════════════════════════════════
# RUN TUNING
# ════════════════════════════════════════════════════════════════════════════

def evaluate_config(model_id, param_dict, sl_mult, tp_mult, ticker_data, min_signals=3):
    """Evaluate one parameter config across all tickers."""
    grid = GRIDS[model_id]

    def entry_fn(df, i):
        return grid["entry_fn"](df, i, param_dict)

    all_trades = []
    for ticker_name, df in ticker_data:
        if df is None:
            continue
        result = run_backtest(df, entry_fn, sl_mult, tp_mult, min_signals=0)
        if result is not None:
            all_trades.extend(result["trades"])

    n = len(all_trades)
    if n < min_signals:
        return None

    wins   = sum(1 for t in all_trades if t["Result"] == "WIN")
    losses = sum(1 for t in all_trades if t["Result"] == "LOSS")
    wr     = wins / n * 100 if n > 0 else 0
    avg    = np.mean([t["PnL%"] for t in all_trades]) if all_trades else 0

    return {
        "params":  {**param_dict, "sl": sl_mult, "tp": tp_mult},
        "n":       n,
        "wins":    wins,
        "losses":  losses,
        "wr":      round(wr, 2),
        "avg":     round(avg, 4),
        "score":   round(score(wr, n, min_signals), 2),
    }


def tune_model(model_id, ticker_data, min_signals=3):
    """Grid search one model across all param combos."""
    grid = GRIDS[model_id]
    param_names = list(grid["params"].keys())
    param_vals  = list(grid["params"].values())

    combos = list(product(*param_vals))
    sl_vals = grid["sl_mult"]
    tp_vals = grid["tp_mult"]
    all_combos = list(product(combos, sl_vals, tp_vals))

    results = []
    for combo, sl, tp in all_combos:
        param_dict = dict(zip(param_names, combo))
        result = evaluate_config(model_id, param_dict, sl, tp, ticker_data, min_signals)
        if result is not None:
            results.append(result)

    if not results:
        return None

    # Sort by score desc
    results.sort(key=lambda x: -x["score"])
    return results


def run_tuning(models=None, days=252, min_signals=3, top_k=5):
    print(f"\n{'='*80}")
    print(f"  TJL HK Model Tuner — {datetime.now(HKT).strftime('%Y-%m-%d %H:%M')} HKT")
    print(f"  Models: {models or 'ALL A–K'} | Backtest period: ~{days} days | Min signals: {min_signals}")
    print(f"{'='*80}\n")

    # ── Step 1: Fetch data for all tickers ──────────────────────────────────
    ticker_data = []
    for ticker_raw, code in TICKERS:
        print(f"  [{ticker_raw}] Fetching {days} days from Futu...", end=" ", flush=True)
        df = fetch_daily(code, count=days + 80)
        if df is None or len(df) < WARMUP + 20:
            print(f"FAIL (got {len(df) if df is not None else 0} bars)")
            ticker_data.append((ticker_raw, None))
        else:
            df = calc_indicators(df)
            print(f"OK ({len(df)} bars)")
            ticker_data.append((ticker_raw, df))

    valid = [(n, d) for n, d in ticker_data if d is not None]
    print(f"\n  → {len(valid)}/{len(TICKERS)} tickers loaded\n")

    # ── Step 2: Grid search per model ──────────────────────────────────────
    model_ids = models or list(GRIDS.keys())
    all_results = {}

    for mid in model_ids:
        if mid not in GRIDS:
            print(f"  [{mid}] — unknown model, skipping")
            continue

        grid = GRIDS[mid]
        n_combos = (len(list(product(*grid["params"].values())))
                    if grid["params"] else 1) * len(grid["sl_mult"]) * len(grid["tp_mult"])

        print(f"\n  Tuning Model {mid} — {grid['desc']}")
        print(f"  {n_combos} configs | ", end="", flush=True)

        t0 = time.time()
        results = tune_model(mid, valid, min_signals)
        elapsed = time.time() - t0

        if results is None:
            print(f"no configs passed min_signals={min_signals}")
            continue

        best = results[0]
        all_results[mid] = {
            "desc":    grid["desc"],
            "best":    best,
            "top_k":   results[:top_k],
            "total_cfgs": n_combos,
            "elapsed": round(elapsed, 1),
        }

        print(f"{elapsed:.0f}s | {len(results)} configs | best: n={best['n']}, WR={best['wr']}%, score={best['score']}")

    # ── Step 3: Print results ───────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  TUNING RESULTS — TOP CONFIG PER MODEL (sorted by score)")
    print(f"{'='*80}")

    if not all_results:
        print("  No results. Try lowering --min-signals")
        return

    sorted_models = sorted(all_results.keys(),
                          key=lambda m: -all_results[m]["best"]["score"])

    rows = []
    for mid in sorted_models:
        r    = all_results[mid]
        best = r["best"]
        rows.append({
            "Model":   f"**{mid}**",
            "Desc":    r["desc"][:35],
            "Trades":  best["n"],
            "W":       best["wins"],
            "L":       best["losses"],
            "WR%":     f"**{best['wr']}**",
            "Avg%":    f"{best['avg']:+.3f}",
            "Score":   best["score"],
            "Best params": str(best["params"]),
        })

    # Pretty print
    hdr = f"{'Model':<7} {'Trades':>6} {'W':>4} {'L':>4} {'WR%':>7} {'Avg%':>8} {'Score':>7}  Params"
    print(hdr)
    print("-" * 90)
    for row in rows:
        wr_str = f"{row['WR%']}"
        avg_str = f"{row['Avg%']:>8}"
        print(f"{row['Model']:<7} {row['Trades']:>6} {row['W']:>4} {row['L']:>4} "
              f"{wr_str:>7} {avg_str} {row['Score']:>7.1f}  {row['Best params']}")

    # ── Step 4: Top-K per model ─────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  TOP-{top_k} CONFIGS PER MODEL")
    print(f"{'='*80}")

    for mid in sorted_models:
        r      = all_results[mid]
        top_k2 = r["top_k"]
        print(f"\n  Model {mid} — {r['desc']}")
        print(f"  {'#':<3} {'Trades':>6} {'W':>4} {'L':>4} {'WR%':>7} {'Avg%':>8} {'Score':>7}  Params")
        print("  " + "-" * 65)
        for i, cfg in enumerate(top_k2):
            print(f"  {i+1:<3} {cfg['n']:>6} {cfg['wins']:>4} {cfg['losses']:>4} "
                  f"{cfg['wr']:>7.1f} {cfg['avg']:>+8.3f} {cfg['score']:>7.1f}  {cfg['params']}")

    # ── Step 5: Save results ────────────────────────────────────────────────
    out_file = f"/Users/jaydensmac/tjl_tuning_results_{datetime.now(HKT).strftime('%Y%m%d_%H%M')}.json"
    with open(out_file, "w") as f:
        json.dump({mid: {
            "desc":  r["desc"],
            "best":  r["best"],
            "top_k": r["top_k"],
        } for mid, r in all_results.items()}, f, indent=2, default=str)

    print(f"\n  💾 Results saved to: {out_file}")
    return all_results


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TJL HK Model Parameter Tuner")
    parser.add_argument("--models", nargs="+",
                        help="Models to tune (default: all A–K)")
    parser.add_argument("--days", type=int, default=252,
                        help="Days of history (default: 252)")
    parser.add_argument("--min-signals", type=int, default=3,
                        help="Min trades per config to count (default: 3)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Top-K configs shown per model (default: 5)")
    args = parser.parse_args()

    run_tuning(models=args.models, days=args.days,
               min_signals=args.min_signals, top_k=args.top_k)
