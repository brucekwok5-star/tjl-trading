#!/usr/bin/env python3
"""
tjl_models — Unified TJL Model Library (A-K, R, S, T, U, V, W, X)
===============================================================
Single source of truth for all TJL entry logic.
Works for both HK (Futu) and US (yfinance) markets.

Key design:
  - Models A-E: take `pmh_src` param — 'intraday' (HK live high) or 'prev_day' (US yesterday H/L)
  - Models F-X: market-agnostic, no pmh_src needed
  - All signals return the same dict shape regardless of market

Signal dict:
  {
    'price': float, 'direction': 'LONG'|'SHORT', 'model': letter,
    'sl': float, 'tp': float, 'rr_ratio': float, 'atr': float,
    <model-specific fields...>
  }

Usage:
  from tjl_models import check_model_a, check_model_b, ..., check_model_x
  sig = check_model_a(price, highs, lows, closes, volumes, pmh_src='intraday',
                       today_high=today_high, today_low=today_low,
                       today_open=today_open, prev_high=prev_high,
                       prev_low=prev_low, sma200=sma200)
  # sig = None if no signal
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# ── Constants ────────────────────────────────────────────────────────────────────
PMH_BUF       = 0.70    # buffer above/below PMH/PML
ATR_SL        = 1.5     # stop loss: 1.5 × ATR
ATR_TP        = 3.0     # take profit: 3.0 × ATR
ATR_PERIOD    = 14
NEAR_EMA_PCT  = 0.015   # ±1.5% — Model A pullback zone
NEAR_EMA_PCT_C = 0.020  # ±2.0% — Model C pullback zone (wider)


# ── Core helpers ────────────────────────────────────────────────────────────────

def calc_emas(closes):
    """EMA9, EMA20, EMA50 from close series. Returns (e9, e20, e50) as floats."""
    c = np.array(closes, dtype=float)
    s = pd.Series(c)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    e50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
    return e9, e20, e50


def calc_atr(highs, lows, closes, period=ATR_PERIOD):
    """ATR from highs/lows/closes arrays. Returns float or None."""
    h = np.array(highs, dtype=float)
    l = np.array(lows,  dtype=float)
    c = np.array(closes, dtype=float)
    if len(c) < period + 1:
        return None
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(np.abs(h[1:] - c[:-1]),
                               np.abs(l[1:] - c[:-1])))
    return float(tr[-period:].mean())


def calc_vwap(highs, lows, closes, volumes):
    """VWAP from OHLV arrays. Returns float or None."""
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    c = np.array(closes,  dtype=float)
    v = np.array(volumes, dtype=float)
    if len(v) < 2 or v.sum() == 0:
        return None
    tp = (h + l + c) / 3
    return float((tp * v).sum() / v.sum())


def calc_rsi(closes, period=14):
    """RSI from closes. Returns float 0-100 or None."""
    c = np.array(closes, dtype=float)
    if len(c) < period + 1:
        return None
    delta = np.diff(c, prepend=c[0])
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_g = float(pd.Series(gain).ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    avg_l = float(pd.Series(loss).ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    if avg_l == 0:
        return 100.0
    return 100 - (100 / (1 + avg_g / avg_l))


def _pmh(price, today_high, today_low, prev_high, prev_low, pmh_src):
    """
    Resolve PMH (previous/prior market high) based on market type.
    pmh_src: 'intraday' (HK live) or 'prev_day' (US yfinance).
    Returns (pmh, pml) as floats.
    """
    if pmh_src == 'intraday':
        pmh = float(today_high) if today_high else float(price)
        pml = float(today_low)  if today_low  else float(price)
    else:  # prev_day
        pmh = float(prev_high) if prev_high else float(price)
        pml = float(prev_low)  if prev_low  else float(price)
    return pmh, pml


def _signal(ticker, price, direction, model, atr, e9=None, extra=None):
    """Build unified signal dict. All fields present regardless of market."""
    if direction == 'LONG':
        sl = round(price - ATR_SL * atr, 2)
        tp = round(price + ATR_TP * atr, 2)
    else:
        sl = round(price + ATR_SL * atr, 2)
        tp = round(price - ATR_TP * atr, 2)
    sig = {
        'ticker':    ticker,
        'price':     round(float(price), 2),
        'direction': direction,
        'model':     model,
        'sl':        sl,
        'tp':        tp,
        'rr_ratio':  round(ATR_TP / ATR_SL, 1),
        'atr':       round(float(atr), 3),
    }
    if e9 is not None:
        sig['e9']       = round(float(e9), 2)
        sig['near_pct'] = round(abs(float(price) - float(e9)) / float(e9) * 100, 2)
    if extra:
        sig.update(extra)
    return sig


# ════════════════════════════════════════════════════════════════════════════════
# MODEL FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════════

def check_model_a(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  pmh_src: str = 'intraday',
                  today_high=None, today_low=None,
                  prev_high=None,  prev_low=None,
                  sma200=None, day_high=None):
    """
    Model A — Pullback (EMA stack + near EMA9 + above PMH).
    Logic: EMA9 > EMA20 > EMA50  AND  |price - EMA9| / EMA9 ≤ 1.5%
            AND  price > PMH + buffer.
    pmh_src: 'intraday' uses today_high (HK live); 'prev_day' uses prev_high (US).
    """
    c = np.array(closes, dtype=float)
    if len(c) < 60:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, c)
    if not atr:
        return None
    pmh, _ = _pmh(price, today_high, today_low, prev_high, prev_low, pmh_src)
    stack_ok    = bool(e9 > e20 > e50)
    near_ema_ok = bool(abs(price - e9) / e9 <= NEAR_EMA_PCT)
    above_pmh   = bool(price > pmh + PMH_BUF)
    if stack_ok and near_ema_ok and above_pmh:
        return _signal(ticker, price, 'LONG', 'A', atr, e9, {
            'pmh': round(pmh, 2),
            'e20': round(e20, 2),
            'e50': round(e50, 2),
            'stack_ok':    True,
            'near_ema_ok': near_ema_ok,
            'above_pmh':   above_pmh,
        })
    return None


def check_model_b(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  pmh_src: str = 'intraday',
                  today_high=None, today_low=None,
                  prev_high=None,  prev_low=None,
                  sma200=None, day_high=None):
    """
    Model B — HT Momentum (above SMA200 + above PMH + above HOD).
    Long only. Requires 200-bar SMA200 in dataset.
    pmh_src: 'intraday' uses today_high (HK live); 'prev_day' uses prev_high (US).
    day_high: today's intraday high (only used when pmh_src='intraday' for HOD check).
    """
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    if len(c) < 200:
        return None
    e9, e20, e50 = calc_emas(c)
    sma200_val = float(pd.Series(c).rolling(200).mean().iloc[-1])
    if np.isnan(sma200_val):
        return None
    atr = calc_atr(h, lows, c) or (float(price) * 0.01)
    pmh, _ = _pmh(price, today_high, today_low, prev_high, prev_low, pmh_src)
    hod = float(today_high) if today_high else float(price)
    above_sma200 = bool(price > sma200_val)
    above_pmh    = bool(price > pmh + PMH_BUF)
    above_hod    = bool(price > hod - 0.50)
    if above_sma200 and above_pmh and above_hod:
        return _signal(ticker, price, 'LONG', 'B', atr, e9, {
            'pmh': round(pmh, 2),
            'sma200': round(sma200_val, 2),
            'above_sma200': above_sma200,
            'above_pmh':    above_pmh,
            'above_hod':    above_hod,
        })
    return None


def check_model_c(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  pmh_src: str = 'intraday',
                  today_high=None, today_low=None,
                  prev_high=None,  prev_low=None):
    """
    Model C — Volume Pullback (near EMA9 + vol spike ≥1.5× avg20 + above PMH).
    pmh_src: 'intraday' uses today_high (HK live); 'prev_day' uses prev_high (US).
    """
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 60 or len(v) < 22:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(h, lows, c) or (float(price) * 0.01)
    pmh, _ = _pmh(price, today_high, today_low, prev_high, prev_low, pmh_src)
    avg_vol   = float(np.mean(v[-20:]))
    near_ema  = bool(abs(price - e9) / e9 <= NEAR_EMA_PCT_C)
    above_pmh = bool(price > pmh + PMH_BUF)
    vol_spike = bool(v[-1] > avg_vol * 1.5)
    if near_ema and above_pmh and vol_spike:
        return _signal(ticker, price, 'LONG', 'C', atr, e9, {
            'pmh': round(pmh, 2),
            'near_ema':  near_ema,
            'above_pmh': above_pmh,
            'vol_spike': vol_spike,
            'vol_ratio': round(float(v[-1]) / avg_vol, 2) if avg_vol > 0 else 0,
        })
    return None


def check_model_d(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  pmh_src: str = 'intraday',
                  today_high=None, today_low=None,
                  prev_high=None,  prev_low=None):
    """
    Model D — RSI Bounce (RSI < 40 + near VWAP + above PMH).
    Fires LONG only. VWAP acts as dynamic support.
    pmh_src: 'intraday' uses today_high (HK live); 'prev_day' uses prev_high (US).
    """
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 22:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    atr = calc_atr(highs, lows, c) or (float(price) * 0.01)
    vwap = calc_vwap(highs, lows, c, v)
    if vwap is None:
        return None
    pmh, _ = _pmh(price, today_high, today_low, prev_high, prev_low, pmh_src)
    rsi_ok   = bool(rsi < 40)
    vwap_ok  = bool(abs(price - vwap) / vwap <= 0.02)
    above_pmh = bool(price > pmh + PMH_BUF)
    if rsi_ok and vwap_ok and above_pmh:
        return _signal(ticker, price, 'LONG', 'D', atr, extra={
            'pmh': round(pmh, 2),
            'rsi': round(rsi, 1),
            'vwap': round(vwap, 2),
            'rsi_ok':  rsi_ok,
            'vwap_ok': vwap_ok,
            'above_pmh': above_pmh,
        })
    return None


def check_model_e(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  pmh_src: str = 'intraday',
                  today_high=None, today_low=None,
                  prev_high=None,  prev_low=None):
    """
    Model E — 20d Hi/Lo Breakout (at 20-day high with vol confirm).
    LONG: price ≥ 98% of 20-day high  AND  vol ≥ 1.2× avg20.
    SHORT: price ≤ 102% of 20-day low  AND  vol ≥ 1.2× avg20.
    pmh_src: 'intraday' uses today_high (HK live); 'prev_day' uses prev_high (US).
    """
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 25:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr     = calc_atr(h, l, c) or (float(price) * 0.01)
    hi20    = float(np.max(h[-20:]))
    lo20    = float(np.min(l[-20:]))
    avg_vol = float(np.mean(v[-20:]))
    vol_ok  = bool(v[-1] > avg_vol * 1.2)
    at_hi   = bool(price >= hi20 * 0.98)
    at_lo   = bool(price <= lo20 * 1.02)
    if at_hi and vol_ok:
        return _signal(ticker, price, 'LONG', 'E', atr, e9, {
            'hi20': round(hi20, 2), 'lo20': round(lo20, 2),
            'vol_ok': vol_ok,
        })
    if at_lo and vol_ok:
        return _signal(ticker, price, 'SHORT', 'E', atr, e9, {
            'hi20': round(hi20, 2), 'lo20': round(lo20, 2),
            'vol_ok': vol_ok,
        })
    return None


def check_model_f(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  direction: str = 'LONG'):
    """
    Model F — RSI Trend Crossover (bullish/bearish EMA stack + RSI zone).
    LONG:  EMA9>EMA20>EMA50  AND  45 ≤ RSI ≤ 65.
    SHORT: EMA9<EMA20<EMA50  AND  35 ≤ RSI ≤ 55.
    No pmh_src needed — market-agnostic.
    """
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    if len(c) < 30:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(h, lows, c) or (float(price) * 0.01)
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    stack_bull = bool(e9 > e20 > e50)
    stack_bear = bool(e9 < e20 < e50)
    if direction == 'LONG':
        if stack_bull and 45 <= rsi <= 65:
            return _signal(ticker, price, 'LONG', 'F', atr, e9, {
                'rsi': round(rsi, 1),
                'e9': round(e9, 2), 'e20': round(e20, 2), 'e50': round(e50, 2),
            })
    else:  # SHORT
        if stack_bear and 35 <= rsi <= 55:
            return _signal(ticker, price, 'SHORT', 'F', atr, e9, {
                'rsi': round(rsi, 1),
                'e9': round(e9, 2), 'e20': round(e20, 2), 'e50': round(e50, 2),
            })
    return None


def check_model_g(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  direction: str = 'LONG',
                  today_open: float = None):
    """
    Model G — ORB Opening Range Breakout (price breaks today open ±$0.10 + stack).
    LONG:  price > today_open + 0.10  AND  EMA9>EMA20>EMA50.
    SHORT: price < today_open - 0.10  AND  EMA9<EMA20<EMA50.
    No pmh_src needed — uses today's open price directly.
    """
    c = np.array(closes, dtype=float)
    if len(c) < 60 or today_open is None:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, c) or (float(price) * 0.01)
    stack_bull = bool(e9 > e20 > e50)
    stack_bear = bool(e9 < e20 < e50)
    if direction == 'LONG':
        if (price > float(today_open) + 0.10) and stack_bull:
            return _signal(ticker, price, 'LONG', 'G', atr, e9, {
                'today_open': round(float(today_open), 2),
            })
    else:  # SHORT
        if (price < float(today_open) - 0.10) and stack_bear:
            return _signal(ticker, price, 'SHORT', 'G', atr, e9, {
                'today_open': round(float(today_open), 2),
            })
    return None


def check_model_h(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  direction: str = 'LONG'):
    """
    Model H — Gold EMA/BB (near outer Bollinger Band + vol confirm).
    LONG:  EMA9>EMA20>EMA50  AND  price in top 30% of BB  AND  vol ≥ avg20.
    SHORT: EMA9<EMA20<EMA50  AND  price in bottom 30% of BB  AND  vol ≥ avg20.
    """
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 50:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, c) or (float(price) * 0.01)
    bb_mid   = float(pd.Series(c).rolling(20).mean().iloc[-1])
    bb_std   = float(pd.Series(c).rolling(20).std().iloc[-1])
    bb_upper = bb_mid + bb_std * 2
    bb_lower = bb_mid - bb_std * 2
    stack_bull = bool(e9 > e20 > e50)
    stack_bear = bool(e9 < e20 < e50)
    avg_vol    = float(np.mean(v[-20:]))
    vol_ok     = bool(v[-1] > avg_vol)
    band_w     = bb_upper - bb_lower
    if band_w <= 0:
        return None
    near_upper = bool(price >= bb_upper - band_w * 0.3)
    near_lower = bool(price <= bb_lower + band_w * 0.3)
    if direction == 'LONG':
        if stack_bull and near_upper and vol_ok:
            return _signal(ticker, price, 'LONG', 'H', atr, e9, {
                'bb_upper': round(bb_upper, 2),
                'bb_lower': round(bb_lower, 2),
                'vol_ok':   vol_ok,
            })
    else:  # SHORT
        if stack_bear and near_lower and vol_ok:
            return _signal(ticker, price, 'SHORT', 'H', atr, e9, {
                'bb_upper': round(bb_upper, 2),
                'bb_lower': round(bb_lower, 2),
                'vol_ok':   vol_ok,
            })
    return None


def check_model_i(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  direction: str = 'LONG'):
    """
    Model I — 63WMA Swing (near EMA9 + price vs 63-day WMA + vol confirm).
    LONG:  price > 63-WMA  AND  |price-EMA9|/EMA9 ≤ 1.5%  AND  vol ≥ avg20.
    SHORT: price < 63-WMA  AND  |price-EMA9|/EMA9 ≤ 1.5%  AND  vol ≥ avg20.
    """
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 70:
        return None
    wma63 = float(pd.Series(c).rolling(63).mean().iloc[-1])
    e9, _, _ = calc_emas(c)
    atr = calc_atr(highs, lows, c) or (float(price) * 0.01)
    above_wma = bool(price > wma63)
    near_ema  = bool(abs(price - e9) / e9 <= 0.015)
    avg_vol   = float(np.mean(v[-20:]))
    vol_ok    = bool(v[-1] > avg_vol)
    if direction == 'LONG' and above_wma and near_ema and vol_ok:
        return _signal(ticker, price, 'LONG', 'I', atr, e9, {
            'wma63': round(wma63, 2),
            'vol_ok': vol_ok,
        })
    if direction == 'SHORT' and (not above_wma) and near_ema and vol_ok:
        return _signal(ticker, price, 'SHORT', 'I', atr, e9, {
            'wma63': round(wma63, 2),
            'vol_ok': vol_ok,
        })
    return None


def check_model_j(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  direction: str = 'LONG'):
    """
    Model J — DMA Cross (5/20 DMA crossover + vol confirm).
    LONG:  DMA5 crosses above DMA20 today  AND  vol ≥ avg20.
    SHORT: DMA5 crosses below DMA20 today  AND  vol ≥ avg20.
    """
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 40:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr  = calc_atr(highs, lows, c) or (float(price) * 0.01)
    s    = pd.Series(c)
    dma5  = float(s.rolling(5).mean().iloc[-1])
    dma20 = float(s.rolling(20).mean().iloc[-1])
    prev_d5  = float(s.iloc[:-1].rolling(5).mean().iloc[-1])
    prev_d20 = float(s.iloc[:-1].rolling(20).mean().iloc[-1])
    cross_up   = bool((dma5 > dma20) and (prev_d5 <= prev_d20))
    cross_down = bool((dma5 < dma20) and (prev_d5 >= prev_d20))
    avg_vol    = float(np.mean(v[-20:]))
    vol_ok     = bool(v[-1] > avg_vol)
    if direction == 'LONG' and cross_up and vol_ok:
        return _signal(ticker, price, 'LONG', 'J', atr, e9, {
            'dma5': round(dma5, 2), 'dma20': round(dma20, 2),
        })
    if direction == 'SHORT' and cross_down and vol_ok:
        return _signal(ticker, price, 'SHORT', 'J', atr, e9, {
            'dma5': round(dma5, 2), 'dma20': round(dma20, 2),
        })
    return None


def check_model_k(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  direction: str = 'SHORT'):
    """
    Model K — Session Short (below VWAP + near lower BB + below EMA9).
    SHORT only. Requires ALL three: below VWAP, in lower BB zone, below EMA9.
    """
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 30:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, c) or (float(price) * 0.01)
    vwap = calc_vwap(highs, lows, c, v)
    if vwap is None:
        return None
    bb_mid   = float(pd.Series(c).rolling(20).mean().iloc[-1])
    bb_std   = float(pd.Series(c).rolling(20).std().iloc[-1])
    bb_lower = bb_mid - bb_std * 2
    below_vwap = bool(price < vwap)
    near_lower = bool(price <= bb_lower + bb_std * 0.5)
    below_e9   = bool(price < e9)
    if direction == 'SHORT' and below_vwap and near_lower and below_e9:
        return _signal(ticker, price, 'SHORT', 'K', atr, e9, {
            'vwap': round(vwap, 2),
            'bb_lower': round(bb_lower, 2),
        })
    return None


def check_model_m(ticker: str, price: float,
                  highs, lows, closes, volumes,
                  direction: str = 'LONG'):
    """
    Model M — EMA Ribbon Compression (9/20/50 EMAs converge, then expand).
    LONG:  EMAs in bullish stack AND ribbon width < 20% of price AND expanding.
    SHORT: EMAs in bearish stack AND ribbon width < 20% of price AND expanding.
    """
    c = np.array(closes, dtype=float)
    if len(c) < 60:
        return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    # Check compression: spread < 20% of price
    spread = abs(e9 - e50)
    if spread / float(price) > 0.20:
        return None
    atr = calc_atr(highs, lows, c) or (float(price) * 0.01)
    stack_bull = bool(e9 > e20 > e50)
    stack_bear = bool(e9 < e20 < e50)
    if direction == 'LONG' and stack_bull:
        return _signal(ticker, price, 'LONG', 'M', atr, e9, {
            'e9': round(e9, 2), 'e20': round(e20, 2), 'e50': round(e50, 2),
        })
    if direction == 'SHORT' and stack_bear:
        return _signal(ticker, price, 'SHORT', 'M', atr, e9, {
            'e9': round(e9, 2), 'e20': round(e20, 2), 'e50': round(e50, 2),
        })
    return None


# ── K/R/S/T/U — From GitHub research (je-sais-tm, ali-azary, soham-srivastava) ──

def check_model_keltner(ticker: str, price: float,
                        highs, lows, closes, volumes,
                        direction: str = 'LONG'):
    """
    Model R — Keltner Channel + RSI Breakout.
    LONG:  price > EMA30 + ATR  AND  RSI > 30.
    SHORT: price < EMA30 - ATR  AND  RSI < 70.
    """
    if len(closes) < 35 or len(volumes) < 14:
        return None
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    ema30 = float(pd.Series(c).ewm(span=30, adjust=False).mean().iloc[-1])
    if np.isnan(ema30) or ema30 <= 0:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    upper = ema30 + atr
    lower = ema30 - atr
    if direction == 'LONG':
        if (price > upper) and (rsi > 30):
            return _signal(ticker, price, 'LONG', 'R', atr, extra={
                'ema30': round(ema30, 2), 'rsi': round(rsi, 1),
                'upper': round(upper, 2), 'lower': round(lower, 2),
            })
    else:
        if (price < lower) and (rsi < 70):
            return _signal(ticker, price, 'SHORT', 'R', atr, extra={
                'ema30': round(ema30, 2), 'rsi': round(rsi, 1),
                'upper': round(upper, 2), 'lower': round(lower, 2),
            })
    return None


def check_model_ichimoku(ticker: str, price: float,
                         highs, lows, closes, volumes,
                         direction: str = 'LONG'):
    """
    Model S — Ichimoku Cloud Breakout (ali-azary/OUMeanReversionStrategy.py).
    LONG:  price > cloud_top  AND  Tenkan > Kijun  AND  Chikou > price 14 bars ago.
    SHORT: price < cloud_bot  AND  Tenkan < Kijun  AND  Chikou < price 14 bars ago.
    """
    if len(closes) < 55:
        return None
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    c = np.array(closes, dtype=float)
    if len(c) < 16:
        return None
    tenkan    = (np.max(h[-9:])  + np.min(l[-9:]))  / 2
    kijun     = (np.max(h[-26:]) + np.min(l[-26:])) / 2
    senkou_a  = (tenkan + kijun) / 2
    senkou_b  = (np.max(h[-52:]) + np.min(l[-52:])) / 2
    chikou    = float(c[-1] - c[-15]) if len(c) >= 15 else 0
    if np.isnan(tenkan) or np.isnan(kijun) or np.isnan(senkou_a):
        return None
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    cloud_top = max(senkou_a, senkou_b)
    cloud_bot = min(senkou_a, senkou_b)
    if direction == 'LONG':
        if (price > cloud_top) and (tenkan > kijun) and (chikou > 0):
            return _signal(ticker, price, 'LONG', 'S', atr, extra={
                'tenkan': round(tenkan, 2), 'kijun': round(kijun, 2),
                'cloud_top': round(cloud_top, 2), 'cloud_bot': round(cloud_bot, 2),
                'chikou': round(chikou, 2),
            })
    else:
        if (price < cloud_bot) and (tenkan < kijun) and (chikou < 0):
            return _signal(ticker, price, 'SHORT', 'S', atr, extra={
                'tenkan': round(tenkan, 2), 'kijun': round(kijun, 2),
                'cloud_top': round(cloud_top, 2), 'cloud_bot': round(cloud_bot, 2),
                'chikou': round(chikou, 2),
            })
    return None


def check_model_zscore(ticker: str, price: float,
                       highs, lows, closes, volumes,
                       direction: str = 'LONG'):
    """
    Model T — Mean Reversion z-score (ali-azary/OUMeanReversionStrategy.py).
    LONG:  z-score < -1.0  AND  price > SMA20  AND  RSI > 30.
    SHORT: z-score > +1.0  AND  price < SMA20  AND  RSI < 70.
    """
    if len(closes) < 25:
        return None
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    if len(c) < 20:
        return None
    s = pd.Series(c)
    sma20 = float(s.rolling(20).mean().iloc[-1])
    std20 = float(s.rolling(20).std().iloc[-1])
    if np.isnan(sma20) or np.isnan(std20) or std20 <= 0:
        return None
    z_score = (float(price) - sma20) / std20
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    if direction == 'LONG':
        if (z_score < -1.0) and (price > sma20) and (rsi > 30):
            return _signal(ticker, price, 'LONG', 'T', atr, extra={
                'z_score': round(z_score, 2),
                'sma20':  round(sma20, 2),
                'rsi':    round(rsi, 1),
            })
    else:
        if (z_score > +1.0) and (price < sma20) and (rsi < 70):
            return _signal(ticker, price, 'SHORT', 'T', atr, extra={
                'z_score': round(z_score, 2),
                'sma20':  round(sma20, 2),
                'rsi':    round(rsi, 1),
            })
    return None


def check_model_dual_thrust(ticker: str, price: float,
                            highs, lows, closes, volumes,
                            today_high, today_low, today_open):
    """
    Model U — Dual Thrust Opening Range (je-sais-tm/quant-trading/DualThrust.py).
    Range = max(N_high - N_low, |N_close - N_open|)  [N=2 lookback]
    Upper = today_open + 0.5 * range   LONG fires above
    Lower = today_open - 0.5 * range   SHORT fires below
    SL: 1× ATR | TP: 2× ATR | R:R = 2:1
    """
    N = 2; K = 0.5
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    if len(c) < 10 or len(h) < N + 1:
        return None
    o = np.array([float(today_open)] * len(c)) if not hasattr(today_open, '__iter__') \
        else np.array(today_open, dtype=float)
    n_h = h[-(N):]; n_l = l[-(N):]
    n_c = c[-(N):]; n_o = o[-(N):]
    range_val = float(max(
        np.max(n_h) - np.min(n_l),
        abs(n_c[-1] - n_o[0]) if len(n_o) else abs(c[-1] - o[-1])
    ))
    upper = float(today_open) + K * range_val
    lower = float(today_open) - K * range_val
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    # Custom SL/TP for DT (1:2 instead of 1.5:3)
    sl_long = round(price - atr, 2)
    tp_long = round(price + 2.0 * atr, 2)
    sl_short = round(price + atr, 2)
    tp_short = round(price - 2.0 * atr, 2)
    if price > upper:
        sig = _signal(ticker, price, 'LONG', 'U', atr, extra={
            'upper': round(upper, 2), 'lower': round(lower, 2),
            'range': round(range_val, 2),
            'sl': sl_long, 'tp': tp_long,
        })
        sig['sl'] = sl_long; sig['tp'] = tp_long
        sig['rr_ratio'] = 2.0
        return sig
    if price < lower:
        sig = _signal(ticker, price, 'SHORT', 'U', atr, extra={
            'upper': round(upper, 2), 'lower': round(lower, 2),
            'range': round(range_val, 2),
            'sl': sl_short, 'tp': tp_short,
        })
        sig['sl'] = sl_short; sig['tp'] = tp_short
        sig['rr_ratio'] = 2.0
        return sig
    return None


def check_model_regime_dt(ticker: str, price: float,
                          highs, lows, closes, volumes,
                          today_open):
    """
    Model V — Dual Thrust Regime Adaptive (soham-srivastava/Dual_Thrust_Strategy).
    Same as U but k1/k2 are dynamic based on EMA10 vs EMA30 bias.
    Bullish (E10>E30): k1=0.4, k2=0.7  → tighter long entry, wider short
    Bearish (E10<E30): k1=0.7, k2=0.4  → wider long, tighter short
    Flat: k1=k2=0.5
    EMA240 macro gate.
    """
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    if len(c) < 35:
        return None
    e10 = float(pd.Series(c).ewm(span=10, adjust=False).mean().iloc[-1])
    e30 = float(pd.Series(c).ewm(span=30, adjust=False).mean().iloc[-1])
    e240 = float(pd.Series(c).ewm(span=240, adjust=False).mean().iloc[-1]) if len(c) >= 240 else None
    if np.isnan(e10) or np.isnan(e30):
        return None
    # Macro gate: trade with the trend
    if e240 is not None and not np.isnan(e240):
        if price < e240:  # bearish macro
            return None
    if e10 > e30 * 1.01:
        k1, k2 = 0.4, 0.7
    elif e10 < e30 * 0.99:
        k1, k2 = 0.7, 0.4
    else:
        k1, k2 = 0.5, 0.5
    N = 2
    o = np.array([float(today_open)] * len(c)) if not hasattr(today_open, '__iter__') \
        else np.array(today_open, dtype=float)
    if len(h) < N + 1:
        return None
    n_h = h[-(N):]; n_l = l[-(N):]
    n_c = c[-(N):]; n_o = o[-(N):]
    range_val = float(max(
        np.max(n_h) - np.min(n_l),
        abs(n_c[-1] - n_o[0]) if len(n_o) else abs(c[-1] - o[-1])
    ))
    upper = float(today_open) + k1 * range_val
    lower = float(today_open) - k2 * range_val
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    if price > upper:
        return _signal(ticker, price, 'LONG', 'V', atr, extra={
            'upper': round(upper, 2), 'lower': round(lower, 2),
            'range': round(range_val, 2),
            'k1': k1, 'k2': k2,
            'e10': round(e10, 2), 'e30': round(e30, 2),
        })
    if price < lower:
        return _signal(ticker, price, 'SHORT', 'V', atr, extra={
            'upper': round(upper, 2), 'lower': round(lower, 2),
            'range': round(range_val, 2),
            'k1': k1, 'k2': k2,
            'e10': round(e10, 2), 'e30': round(e30, 2),
        })
    return None


def check_model_ob(ticker: str, price: float,
                   highs, lows, closes, volumes):
    """
    Model W — SMC Order Block + FVG (joshyattridge/smart-money-concepts 1.9k★).
    Detect 5-day bearish candle sequences → highest high of body zone = Order Block.
    Price retests OB zone + RSI < 40 = bullish entry signal.
    FVG (3-candle gap) = institutional order flow confirmation.
    """
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    if len(c) < 20:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    # Scan last 5 candles for bearish sequence (body < 30% of range)
    ob_high = None
    for i in range(max(0, len(c) - 5), len(c) - 1):
        body  = abs(c[i] - (h[i] + l[i]) / 2)  # distance from midpoint = body proxy
        range_c = h[i] - l[i]
        if range_c > 0 and body / range_c < 0.30:  # small body = consolidation
            ob_high = float(h[i])
            break
    if ob_high is None:
        # Fallback: use highest high of last 5
        ob_high = float(np.max(h[-5:]))
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    # Retest: price within 1 ATR of order block high
    near_ob   = bool(abs(price - ob_high) <= atr * 1.5)
    rsi_oversold = bool(rsi < 40)
    if near_ob and rsi_oversold:
        return _signal(ticker, price, 'LONG', 'W', atr, extra={
            'ob_high': round(ob_high, 2),
            'rsi': round(rsi, 1),
        })
    return None


def check_model_rsi_div(ticker: str, price: float,
                        highs, lows, closes, volumes):
    """
    Model X — RSI Divergence (multiple strategy repos).
    Bullish divergence: price makes lower low, RSI makes higher/equal low.
    Confirmed by: EMA20 slope up.
    Entry: next bar open. SL: recent swing low. TP: recent swing high.
    """
    c = np.array(closes, dtype=float)
    if len(c) < 30:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    # Price and RSI last 3 bars
    if len(c) < 3:
        return None
    price_ll  = (c[-1] < c[-2] < c[-3])          # lower lows
    rsi_hl    = (rsi >= float(calc_rsi(c[:-1]) or 0))  # RSI not making lower low
    # EMA20 slope
    e20_cur  = float(pd.Series(c).ewm(span=20, adjust=False).mean().iloc[-1])
    e20_prev = float(pd.Series(c).ewm(span=20, adjust=False).mean().iloc[-2])
    ema_up   = bool(e20_cur >= e20_prev)
    if price_ll and rsi_hl and ema_up:
        atr = calc_atr(highs, lows, c)
        if atr is None:
            atr = float(price) * 0.01
        return _signal(ticker, price, 'LONG', 'X', atr, extra={
            'rsi': round(rsi, 1),
            'ema20': round(e20_cur, 2),
        })
    return None
