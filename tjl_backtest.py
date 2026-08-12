#!/usr/bin/env python3
"""
TJL Backtest — Models D through K (8 models).
Intraday and daily support via ft.KLType.

Usage:
  python3 tjl_backtest.py                  # default: daily, 20 days, max 5-bar hold
  python3 tjl_backtest.py --15min          # 15-min bars, 20 days
  python3 tjl_backtest.py --daily 60      # daily bars, 60 days, 10-bar hold
  python3 tjl_backtest.py --5min 20       # 5-min bars, 20 days
"""
import sys, argparse, futu as ft
from futu.quote.open_quote_context import OpenQuoteContext, KLType, SubType
ft.OpenQuoteContext = OpenQuoteContext
ft.KLType = KLType
ft.SubType = SubType
import pandas as pd
import numpy as np
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")

# ── CLI args ─────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='TJL backtest')
parser.add_argument('--daily',   dest='ktype', action='store_const',
                    const=ft.KLType.K_DAY,   help='Daily bars (default)')
parser.add_argument('--15min',   dest='ktype', action='store_const',
                    const=ft.KLType.K_15M,   help='15-minute bars')
parser.add_argument('--5min',    dest='ktype', action='store_const',
                    const=ft.KLType.K_5M,    help='5-minute bars')
parser.add_argument('--1min',    dest='ktype', action='store_const',
                    const=ft.KLType.K_1M,    help='1-minute bars')
parser.add_argument('--30min',   dest='ktype', action='store_const',
                    const=ft.KLType.K_30M,   help='30-minute bars')
parser.add_argument('--60min',   dest='ktype', action='store_const',
                    const=ft.KLType.K_60M,   help='60-minute bars')
parser.add_argument('--model',   dest='model', type=str, default=None,
                    help='Restrict backtest to ONE model letter (D-Q). '
                         'Use to backtest exactly the model that fired a live signal '
                         'on a specific ticker — no cross-stock cherry-picking.')
parser.add_argument('--ticker',  dest='ticker', type=str, default=None,
                    help='Restrict backtest to ONE ticker code (5-digit, e.g. 01109). '
                         'Pairs with --model for one-stock-one-model backtest.')
parser.add_argument('days',      nargs='?', type=int, default=20,
                    help='Number of trading days to backtest (default: 20)')
parser.add_argument('--hold',    dest='max_hold', type=int, default=5,
                    help='Max bars to hold before forced exit (default: 5)')
parser.add_argument('--lookback', type=int, default=None,
                    help='Override lookback bar count (auto-calculated from days if unset)')
args = parser.parse_args()  # always parse — argparse handles no-arg correctly

# ── Config ────────────────────────────────────────────────────────────────────
PMH_BUF      = 0.70
ATR_SL       = 1.0
ATR_TP       = 1.5
ATR_PERIOD   = 14
NEAR_EMA_PCT = 0.015
NEAR_EMA_PCT_C = 0.020
VOL_SPIKE_MULT = 2.0

KL_TYPE   = args.ktype  if args and args.ktype  else ft.KLType.K_DAY
TRADE_DAYS = args.days   if args else 20
MAX_HOLD  = args.max_hold if args and args.max_hold else 5
# Rough lookback: 1.5× the bar count needed to cover TRADE_DAYS plus warm-up
if args and args.lookback:
    LOOKBACK = args.lookback
elif KL_TYPE == ft.KLType.K_DAY:
    LOOKBACK = int(TRADE_DAYS * 1.5) + 60  # ~1.5× coverage + warm-up
elif KL_TYPE == ft.KLType.K_60M:
    LOOKBACK = TRADE_DAYS * 7 * 4   # 4 × 60-min bars per trading day
elif KL_TYPE == ft.KLType.K_30M:
    LOOKBACK = TRADE_DAYS * 7 * 8
elif KL_TYPE == ft.KLType.K_15M:
    LOOKBACK = TRADE_DAYS * 7 * 16
elif KL_TYPE == ft.KLType.K_5M:
    LOOKBACK = TRADE_DAYS * 7 * 48
elif KL_TYPE == ft.KLType.K_1M:
    LOOKBACK = TRADE_DAYS * 7 * 240
else:
    LOOKBACK = int(TRADE_DAYS * 1.5) + 60

KL_LABEL = {
    ft.KLType.K_DAY:  'Daily',
    ft.KLType.K_60M:  '60-min',
    ft.KLType.K_30M:  '30-min',
    ft.KLType.K_15M:  '15-min',
    ft.KLType.K_5M:   '5-min',
    ft.KLType.K_1M:   '1-min',
}.get(KL_TYPE, str(KL_TYPE))

# ── Test stocks (HSI constituents used in today's live scan) ─────────────────
BACKTEST_STOCKS = [
    ("01109", "HK.01109"),  # 华润置地
    ("02899", "HK.02899"),  # 紫金矿业
    ("00005", "HK.00005"),  # HSBC
    ("09618", "HK.09618"),  # JD.com
    ("00823", "HK.00823"),  # 领展房产
    ("00288", "HK.00288"),  # 万洲
    ("00941", "HK.00941"),  # China Mobile (baseline)
    ("00700", "HK.00700"),  # Tencent (baseline)
]

# ── One-stock-one-model filter ────────────────────────────────────────────────
# Build the runtime set of models to actually run. If --model is given, restrict
# to that single letter — prevents cross-stock cherry-picking.
VALID_MODELS = list("DEFGHIJKLMNOPQ")
if hasattr(args, 'model') and args.model:
    if args.model.upper() not in VALID_MODELS:
        sys.stderr.write(f"ERROR: --model must be one of {VALID_MODELS}, got '{args.model}'\n")
        sys.exit(1)
    ACTIVE_MODELS = [args.model.upper()]
else:
    ACTIVE_MODELS = VALID_MODELS[:]

# Build the runtime list of stocks. If --ticker is given, restrict to that one.
ACTIVE_STOCKS = BACKTEST_STOCKS[:]
if hasattr(args, 'ticker') and args.ticker:
    ticker_code = args.ticker.zfill(5)
    matching = [(n, c) for n, c in BACKTEST_STOCKS if n == ticker_code]
    if not matching:
        sys.stderr.write(
            f"ERROR: --ticker {ticker_code} not in BACKTEST_STOCKS. "
            f"Known: {[n for n, _ in BACKTEST_STOCKS]}\n"
        )
        sys.exit(1)
    ACTIVE_STOCKS = matching

# ── Indicator helpers ─────────────────────────────────────────────────────────

def calc_emas(closes):
    s = pd.Series(closes)
    e9  = s.ewm(span=9,  adjust=False).mean().iloc[-1]
    e20 = s.ewm(span=20, adjust=False).mean().iloc[-1]
    e50 = s.ewm(span=50, adjust=False).mean().iloc[-1]
    return e9, e20, e50

def calc_atr(highs, lows, closes, period=ATR_PERIOD):
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return None
    return np.mean(trs[-period:])

def calc_vwap(highs, lows, closes, volumes):
    if len(highs) < 2 or len(volumes) < 2:
        return None
    typical = (np.array(highs) + np.array(lows) + np.array(closes)) / 3.0
    vol = np.array(volumes, dtype=float)
    cum_pv = np.cumsum(typical * vol)
    cum_vol = np.cumsum(vol)
    return float(cum_pv[-1] / cum_vol[-1])

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    return float(100 - (100 / (1 + avg_gain / avg_loss)))

def calc_bb_bands(closes, period=20, num_std=2):
    """Return (upper, middle, lower, bandwidth) as numpy arrays."""
    if len(closes) < period:
        return None, None, None, None
    s = pd.Series(closes)
    mid = s.rolling(period).mean().values
    std = s.rolling(period).std().values
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid * 100
    return upper, mid, lower, bandwidth

def get_bars(ctx, code, ktype=ft.KLType.K_DAY, count=100):
    """Fetch historical K-lines. Returns (highs, lows, closes, volumes, opens)."""
    ret, kl, _ = ctx.request_history_kline(code, ktype=ktype, max_count=count)
    if ret != 0 or kl is None or kl.empty:
        return None, None, None, None, None
    kl = kl.sort_values('time_key').reset_index(drop=True)
    return (kl['high'].values, kl['low'].values, kl['close'].values,
            kl['volume'].values, kl['open'].values)

# ── Model signals (bar-by-bar, exclude last bar = today) ─────────────────────

def model_d_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model D: RSI Oversold Bounce.
    RSI crosses UP through 30 from below + near VWAP + above PMH.
    """
    if bar_idx < 22:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    vwap = calc_vwap(h, l, c, v)
    atr  = calc_atr(h, l, c)
    if vwap is None or atr is None:
        return None
    rsi_now  = calc_rsi(c)
    rsi_prev = calc_rsi(c[:-1]) if len(c) >= 15 else None
    if rsi_now is None or rsi_prev is None:
        return None
    rsi_bounce = (rsi_prev < 30) and (rsi_now >= 30)
    near_vwap  = abs(price - vwap) / vwap < 0.015
    above_pmh  = price >= (max(h) - 0.70)
    long_fire  = rsi_bounce and near_vwap and above_pmh
    if not long_fire:
        return None
    return {'direction': 'LONG', 'price': price,
            'sl': price - ATR_SL * atr, 'tp': price + ATR_TP * atr,
            'atr': atr, 'vwap': round(vwap, 3), 'rsi': round(rsi_now, 1)}


def model_e_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model E: 20-Day High Breakout.
    Price breaks above 20-day high + vol surge + RSI > 50.
    """
    if bar_idx < 22:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    high_20 = float(np.max(h[-21:-1]))
    low_20  = float(np.min(l[-21:-1]))
    avg_vol20 = np.mean(v[-21:-1])
    vol_ratio = v[-1] / avg_vol20 if avg_vol20 > 0 else 0
    vol_ok = vol_ratio >= 1.5
    above_high = price > high_20
    below_low  = price < low_20
    long_fire  = above_high and vol_ok and (rsi > 50)
    short_fire = below_low  and vol_ok and (rsi < 50)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr,
            'tp': price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr,
            'atr': atr, 'high_20': round(high_20, 3), 'rsi': round(rsi, 1)}


def model_f_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model F: RSI Trend Crossover.
    LONG: RSI(14) crosses above 55 + EMA9 > EMA20.
    SHORT: RSI(14) crosses below 45 + EMA9 < EMA20.
    """
    if bar_idx < 22:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    rsi_now  = calc_rsi(c)
    rsi_prev = calc_rsi(c[:-1]) if len(c) >= 15 else None
    if rsi_now is None or rsi_prev is None:
        return None
    s = pd.Series(c)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    if np.isnan(e9) or np.isnan(e20):
        return None
    rsi_cross_up   = (rsi_prev < 55) and (rsi_now >= 55)
    rsi_cross_down = (rsi_prev > 45) and (rsi_now <= 45)
    long_fire  = rsi_cross_up  and (e9 > e20)
    short_fire = rsi_cross_down and (e9 < e20)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr,
            'tp': price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr,
            'atr': atr, 'rsi': round(rsi_now, 1)}


def model_g_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model G: ORB — 5-bar breakout with vol confirm.
    LONG: close > max(high[-5:-1]) AND vol > 1.2 * avg20.
    SHORT: close < min(low[-5:-1])  AND vol > 1.2 * avg20.
    """
    if bar_idx < 30:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    # ORB range: 5-bar high/low before entry
    if len(c) < 6:
        return None
    orb_high = max(h[-6:-1])
    orb_low  = min(l[-6:-1])
    vol_avg20 = float(pd.Series(v).rolling(20).mean().iloc[-1])
    vol_now   = v[-1]
    if np.isnan(vol_avg20) or vol_avg20 == 0:
        return None
    vol_ok = vol_now >= vol_avg20 * 1.2
    long_fire  = (price > orb_high) and vol_ok
    short_fire = (price < orb_low)  and vol_ok
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr,
            'tp': price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr,
            'atr': atr, 'orb_high': round(orb_high, 2), 'orb_low': round(orb_low, 2),
            'vol_ratio': round(vol_now / vol_avg20, 2)}


def model_h_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model H: Gold EMA/BB/VWAP.
    LONG: EMA9 crosses above BB(20) midline AND price > EMA21 AND price > VWAP.
    SHORT: EMA9 crosses below BB(20) midline AND price < EMA21 AND price < VWAP.
    """
    if bar_idx < 25:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    s = pd.Series(c)
    e9   = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e9p  = float(s.ewm(span=9,  adjust=False).mean().iloc[-2])
    e21  = float(s.ewm(span=21, adjust=False).mean().iloc[-1])
    if any(np.isnan(x) for x in [e9, e9p, e21]):
        return None
    bb_mid  = float(s.rolling(20).mean().iloc[-1])
    bb_midp = float(s.rolling(20).mean().iloc[-2])
    if np.isnan(bb_mid) or np.isnan(bb_midp):
        return None
    vwap = calc_vwap(h, l, c, v)
    cross_up   = (e9p < bb_midp) and (e9 >= bb_mid)
    cross_down = (e9p > bb_midp) and (e9 <= bb_mid)
    above = (price > e21) and (price > vwap)
    below = (price < e21) and (price < vwap)
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    long_fire  = cross_up  and above
    short_fire = cross_down and below
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr,
            'tp': price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr,
            'atr': atr, 'e9': round(e9, 3), 'bb_mid': round(bb_mid, 3),
            'vwap': round(vwap, 3), 'rsi': round(rsi, 1)}


def model_i_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model I: SHM-lite — 63-WMA pullback swing.
    LONG: price has pulled back TO 63-WMA from above + RSI > 50.
    SHORT: price has rallied TO 63-WMA from below + RSI < 50.
    Penny stocks (ATR > 20% of price) are rejected.
    Swing R:R: SL=1.5ATR, TP=3.0ATR.
    """
    if bar_idx < 65:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    # Reject penny stocks where ATR is unreliable
    if price < 1.0 or atr / price > 0.20:
        return None
    s = pd.Series(c)
    wma63 = float(s.rolling(63).mean().iloc[-1])
    if np.isnan(wma63) or wma63 <= 0:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    pullback_tolerance = 0.03
    near_wma_from_below = price < wma63 and abs(price - wma63) / wma63 <= pullback_tolerance
    near_wma_from_above = price > wma63 and abs(price - wma63) / wma63 <= pullback_tolerance
    long_fire  = near_wma_from_below and (rsi > 50)
    short_fire = near_wma_from_above and (rsi < 50)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - 1.5 * atr if direction == 'LONG' else price + 1.5 * atr,
            'tp': price + 3.0 * atr if direction == 'LONG' else price - 3.0 * atr,
            'atr': atr, 'wma63': round(wma63, 3), 'rsi': round(rsi, 1)}


def model_j_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model J: Follow the Money — 150/200 DMA.
    LONG: price within 2% of 150-DMA AND above 200-DMA AND vol > 1.5 * avg20.
    SHORT: price within 2% of 150-DMA AND below 200-DMA AND vol > 1.5 * avg20.
    """
    if bar_idx < 155:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    s = pd.Series(c)
    dma150 = float(s.rolling(150).mean().iloc[-1])
    dma200 = float(s.rolling(200).mean().iloc[-1])
    if np.isnan(dma150) or np.isnan(dma200):
        return None
    vol_avg20 = float(pd.Series(v).rolling(20).mean().iloc[-1])
    vol_now   = v[-1]
    if np.isnan(vol_avg20) or vol_avg20 == 0:
        return None
    near = abs(price - dma150) / dma150 <= 0.02
    vol_ok = vol_now >= vol_avg20 * 1.5
    long_fire  = near and (price > dma200) and vol_ok
    short_fire = near and (price < dma200) and vol_ok
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr,
            'tp': price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr,
            'atr': atr, 'dma150': round(dma150, 3), 'dma200': round(dma200, 3),
            'vol_ratio': round(vol_now / vol_avg20, 2)}


def model_k_signal(highs, lows, closes, volumes, bar_idx):
    """Bar-by-bar Model K: EMA/VWAP/Bollinger Session.
    Identical logic to Model H — EMA/BB/VWAP crossover.
    Kept as separate model for independent signal tracking.
    """
    if bar_idx < 25:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    s = pd.Series(c)
    e9   = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e9p  = float(s.ewm(span=9,  adjust=False).mean().iloc[-2])
    e21  = float(s.ewm(span=21, adjust=False).mean().iloc[-1])
    if any(np.isnan(x) for x in [e9, e9p, e21]):
        return None
    bb_mid  = float(s.rolling(20).mean().iloc[-1])
    bb_midp = float(s.rolling(20).mean().iloc[-2])
    if np.isnan(bb_mid) or np.isnan(bb_midp):
        return None
    vwap = calc_vwap(h, l, c, v)
    cross_up   = (e9p < bb_midp) and (e9 >= bb_mid)
    cross_down = (e9p > bb_midp) and (e9 <= bb_mid)
    above = (price > e21) and (price > vwap)
    below = (price < e21) and (price < vwap)
    long_fire  = cross_up  and above
    short_fire = cross_down and below
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr,
            'tp': price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr,
            'atr': atr, 'e9': round(e9, 3), 'bb_mid': round(bb_mid, 3),
            'vwap': round(vwap, 3)}


def model_l_signal(highs, lows, closes, volumes, opens, bar_idx):
    """Model L: VWAP Reversion (Daytrade).
    LONG: price < VWAP*0.985 AND RSI<35 — price dislocated below VWAP, oversold.
    SHORT: price > VWAP*1.015 AND RSI>65 — price dislocated above VWAP, overbought.
    Exit: TP=VWAP, SL=1.5 ATR.
    """
    if bar_idx < 22:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    vwap = calc_vwap(h, l, c, v)
    atr = calc_atr(h, l, c)
    if vwap is None or atr is None or vwap <= 0:
        return None
    rsi = calc_rsi(c)
    if rsi is None:
        return None
    long_fire  = (price < vwap * 0.985) and (rsi < 35)
    short_fire = (price > vwap * 1.015) and (rsi > 65)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - 1.5 * atr if direction == 'LONG' else price + 1.5 * atr,
            'tp': vwap,
            'atr': atr, 'vwap': round(vwap, 3), 'rsi': round(rsi, 1)}


def model_m_signal(highs, lows, closes, volumes, opens, bar_idx):
    """Model M: EMA Ribbon Compression (Swing).
    LONG: EMA9>EMA21>EMA50 AND spread(EMA9,EMA50)<1% AND price breaks above EMA9.
    SHORT: EMA9<EMA21<EMA50 AND spread<1% AND price breaks below EMA9.
    Exit: SL=EMA50, TP=3 ATR.
    """
    if bar_idx < 55:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    prev_close = c[-2]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    s = pd.Series(c)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e21 = float(s.ewm(span=21, adjust=False).mean().iloc[-1])
    e50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
    if any(np.isnan(x) or x <= 0 for x in [e9, e21, e50]):
        return None
    spread_pct = abs(e9 - e50) / e50 * 100
    compressed = spread_pct < 1.0
    # Bull/bear stack
    bull_stack = e9 > e21 > e50
    bear_stack = e9 < e21 < e50
    # Breakout: prev close below EMA9, current close above EMA9
    long_breakout  = (prev_close <= e9) and (price > e9)
    short_breakout = (prev_close >= e9) and (price < e9)
    long_fire  = compressed and bull_stack and long_breakout
    short_fire = compressed and bear_stack and short_breakout
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': e50,
            'tp': price + 3.0 * atr if direction == 'LONG' else price - 3.0 * atr,
            'atr': atr, 'e9': round(e9, 3), 'e21': round(e21, 3),
            'e50': round(e50, 3), 'spread': round(spread_pct, 2)}


def model_n_signal(highs, lows, closes, volumes, opens, bar_idx):
    """Model N: RSI Divergence Reversal (Swing).
    LONG: price[-1]<price[-5] AND RSI[-1]>RSI[-5] AND RSI<45 (bullish divergence).
    SHORT: price[-1]>price[-5] AND RSI[-1]<RSI[-5] AND RSI>55 (bearish divergence).
    Exit: SL=recent swing low/high + 0.5 ATR, TP=2.5 ATR.
    """
    if bar_idx < 22:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    rsi_now  = calc_rsi(c)
    rsi_5ago = calc_rsi(c[:-5]) if len(c) > 20 else None
    if rsi_now is None or rsi_5ago is None:
        return None
    price_now   = c[-1]
    price_5ago  = c[-6]
    # Bullish divergence: price lower low, RSI higher low
    long_fire  = (price_now < price_5ago) and (rsi_now > rsi_5ago) and (rsi_now < 45)
    short_fire = (price_now > price_5ago) and (rsi_now < rsi_5ago) and (rsi_now > 55)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    # SL at recent swing low (for LONG) or high (for SHORT) + 0.5 ATR
    lookback_swing = min(10, len(l))
    if direction == 'LONG':
        swing = float(np.min(l[-lookback_swing:]))
        sl = swing - 0.5 * atr
    else:
        swing = float(np.max(h[-lookback_swing:]))
        sl = swing + 0.5 * atr
    return {'direction': direction, 'price': price,
            'sl': sl,
            'tp': price + 2.5 * atr if direction == 'LONG' else price - 2.5 * atr,
            'atr': atr, 'rsi': round(rsi_now, 1), 'rsi_5ago': round(rsi_5ago, 1)}


def model_o_signal(highs, lows, closes, volumes, opens, bar_idx):
    """Model O: Gap Fill (Daytrade).
    LONG (gap up fill): open > prev_close*1.02 AND close < prev_close*1.01
         -> price gapped up then pulled back, buy expecting fill back up.
    SHORT (gap down fill): open < prev_close*0.98 AND close > prev_close*0.99
         -> price gapped down then bounced, short expecting fill back down.
    Exit: TP=prev_close (full gap fill), SL=1 ATR.
    """
    if bar_idx < 5:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    o = opens[:bar_idx+1]
    price = c[-1]
    open_price = o[-1]
    prev_close = c[-2]
    atr = calc_atr(h, l, c)
    if atr is None or prev_close <= 0:
        return None
    gap_up   = open_price > prev_close * 1.02
    gap_down = open_price < prev_close * 0.98
    # After gap, price has started pulling back toward prev_close
    pulled_back_up   = gap_up   and (price < prev_close * 1.01)
    pulled_back_down = gap_down and (price > prev_close * 0.99)
    long_fire  = pulled_back_up
    short_fire = pulled_back_down
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - 1.0 * atr if direction == 'LONG' else price + 1.0 * atr,
            'tp': prev_close,  # full gap fill target
            'atr': atr, 'open': round(open_price, 3),
            'prev_close': round(prev_close, 3)}


def model_p_signal(highs, lows, closes, volumes, opens, bar_idx):
    """Model P: Donchian Breakout with Trend + Volume Filter.
    LONG: 20d high breakout + EMA50 sloping up + vol > 2x avg.
    SHORT: 20d low breakdown + EMA50 sloping down + vol > 2x avg.
    Exit: TP=3 ATR, SL=1 ATR.
    """
    if bar_idx < 55:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    # Need at least 50 bars for EMA50 slope
    if len(c) < 51:
        return None
    s = pd.Series(c)
    e50_now = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
    e50_5ago = float(s.ewm(span=50, adjust=False).mean().iloc[-6])
    if any(np.isnan(x) for x in [e50_now, e50_5ago]) or e50_5ago <= 0:
        return None
    slope_pct = (e50_now - e50_5ago) / e50_5ago * 100  # 5-bar slope
    # 20-day breakout (exclude today)
    high_20 = float(np.max(h[-21:-1]))
    low_20  = float(np.min(l[-21:-1]))
    avg_vol20 = float(np.mean(v[-21:-1]))
    vol_now = v[-1]
    if avg_vol20 <= 0:
        return None
    vol_ratio = vol_now / avg_vol20
    long_fire  = (price > high_20) and (slope_pct > 0.5) and (vol_ratio >= 2.0)
    short_fire = (price < low_20)  and (slope_pct < -0.5) and (vol_ratio >= 2.0)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - 1.0 * atr if direction == 'LONG' else price + 1.0 * atr,
            'tp': price + 3.0 * atr if direction == 'LONG' else price - 3.0 * atr,
            'atr': atr, 'high_20': round(high_20, 3), 'e50_slope': round(slope_pct, 2),
            'vol_ratio': round(vol_ratio, 2)}


def model_q_signal(highs, lows, closes, volumes, opens, bar_idx):
    """Model Q: ADX Trend Strength Entry (strict).
    LONG: ADX > 30 AND +DI > -DI AND price > EMA200 AND EMA20 > EMA50.
    SHORT: ADX > 30 AND -DI > +DI AND price < EMA200 AND EMA20 < EMA50.
    Exit: SL=1.5 ATR, TP=2.5 ATR.
    """
    if bar_idx < 205:
        return None
    h = highs[:bar_idx+1]; l = lows[:bar_idx+1]
    c = closes[:bar_idx+1]; v = volumes[:bar_idx+1]
    price = c[-1]
    atr = calc_atr(h, l, c)
    if atr is None:
        return None
    s = pd.Series(c)
    e20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    e50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
    e200 = float(s.rolling(200).mean().iloc[-1])
    if any(np.isnan(x) or x <= 0 for x in [e20, e50, e200]):
        return None
    # Compute ADX (14) from highs/lows/closes
    highs_arr = np.array(h, dtype=float)
    lows_arr  = np.array(l, dtype=float)
    closes_arr = np.array(c, dtype=float)
    tr = np.maximum(highs_arr[1:] - lows_arr[1:],
                    np.abs(highs_arr[1:] - closes_arr[:-1]),
                    np.abs(lows_arr[1:] - closes_arr[:-1]))
    up_move = highs_arr[1:] - highs_arr[:-1]
    down_move = lows_arr[:-1] - lows_arr[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    period = 14
    atr_smooth = np.zeros(len(tr))
    plus_dm_smooth = np.zeros(len(tr))
    minus_dm_smooth = np.zeros(len(tr))
    atr_smooth[period-1] = np.mean(tr[:period])
    plus_dm_smooth[period-1] = np.mean(plus_dm[:period])
    minus_dm_smooth[period-1] = np.mean(minus_dm[:period])
    for i in range(period, len(tr)):
        atr_smooth[i] = atr_smooth[i-1] * (period-1)/period + tr[i]
        plus_dm_smooth[i] = plus_dm_smooth[i-1] * (period-1)/period + plus_dm[i]
        minus_dm_smooth[i] = minus_dm_smooth[i-1] * (period-1)/period + minus_dm[i]
    plus_di = 100 * plus_dm_smooth / np.where(atr_smooth > 0, atr_smooth, 1)
    minus_di = 100 * minus_dm_smooth / np.where(atr_smooth > 0, atr_smooth, 1)
    dx = 100 * np.abs(plus_di - minus_di) / np.where(plus_di + minus_di > 0, plus_di + minus_di, 1)
    adx = np.zeros(len(dx))
    adx[period*2-2] = np.mean(dx[period-1:period*2-1])
    for i in range(period*2-1, len(dx)):
        adx[i] = adx[i-1] * (period-1)/period + dx[i]
    adx_now = float(adx[-1])
    plus_di_now = float(plus_di[-1])
    minus_di_now = float(minus_di[-1])
    if np.isnan(adx_now):
        return None
    # Stricter ADX + EMA200 macro filter
    long_fire  = (adx_now > 30) and (plus_di_now > minus_di_now) and (price > e200) and (e20 > e50)
    short_fire = (adx_now > 30) and (minus_di_now > plus_di_now) and (price < e200) and (e20 < e50)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {'direction': direction, 'price': price,
            'sl': price - 1.5 * atr if direction == 'LONG' else price + 1.5 * atr,
            'tp': price + 2.5 * atr if direction == 'LONG' else price - 2.5 * atr,
            'atr': atr, 'adx': round(adx_now, 1),
            'plus_di': round(plus_di_now, 1), 'minus_di': round(minus_di_now, 1)}


# ── Backtest engine ───────────────────────────────────────────────────────────

def backtest_stock(code, name, ktype=None, lookback=None, trade_days=None, max_hold=None):
    """
    Run backtest for models D/E/F for a single stock.
    Uses last `trade_days` completed bars as trade-entry days.
    Holds up to `max_hold` bars before forcing exit at close of bar_idx+max_hold.
    """
    ktype    = ktype     or KL_TYPE
    lookback = lookback  or LOOKBACK
    trade_days = trade_days or TRADE_DAYS
    max_hold   = max_hold   or MAX_HOLD
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    time.sleep(0.3)
    highs, lows, closes, volumes, opens = get_bars(ctx, code, ktype=ktype, count=lookback)
    ctx.close()
    if highs is None or len(closes) < 60:
        return []

    trades = []
    n = len(closes)
    # We trade on bars [start_bar .. n-2] (skip today = n-1)
    start_bar = max(60, n - trade_days - 1)

    # Map model letter → signal function (all 14 always imported)
    ALL_MODEL_FNS = {
        'D': model_d_signal, 'E': model_e_signal,
        'F': model_f_signal, 'G': model_g_signal,
        'H': model_h_signal, 'I': model_i_signal,
        'J': model_j_signal, 'K': model_k_signal,
        'L': model_l_signal, 'M': model_m_signal,
        'N': model_n_signal, 'O': model_o_signal,
        'P': model_p_signal, 'Q': model_q_signal,
    }
    # Restrict to ACTIVE_MODELS (set in module init from --model flag).
    # This is what enforces "one stock, one model" — no cherry-picking.
    MODEL_FNS = [(letter, ALL_MODEL_FNS[letter]) for letter in ACTIVE_MODELS
                 if letter in ALL_MODEL_FNS]

    for bar_idx in range(start_bar, n - 1):
        for model_name, signal_fn in MODEL_FNS:
            # New models L/M/N/O/P/Q need opens too
            if model_name in ('L', 'M', 'N', 'O', 'P', 'Q'):
                sig = signal_fn(highs, lows, closes, volumes, opens, bar_idx)
            else:
                sig = signal_fn(highs, lows, closes, volumes, bar_idx)
            if sig is None:
                continue

            entry     = sig['price']
            sl        = sig['sl']
            tp        = sig['tp']
            direction = sig['direction']
            atr       = sig['atr']

            # ── Exit logic (max_hold bars) ─────────────────────────────────
            # TP/SL hit → exit immediately
            # Model D: also exit if price returns to VWAP (mean reversion closes faster)
            # Model F: also exit if RSI reverses back through 50 (crossover reversal)
            # Otherwise hold up to max_hold bars
            vwap_of_record = calc_vwap(highs[:bar_idx+1], lows[:bar_idx+1],
                                      closes[:bar_idx+1], volumes[:bar_idx+1])
            exit_price = None; outcome = None; exit_bar = bar_idx + 1
            for look in range(1, max_hold + 1):
                if bar_idx + look >= n:
                    break
                next_high  = highs[bar_idx + look]
                next_low   = lows[bar_idx + look]
                next_close = closes[bar_idx + look]

                if direction == 'LONG':
                    if next_low <= sl:
                        exit_price = sl; outcome = 'SL'; exit_bar = bar_idx + look
                        break
                    elif next_high >= tp:
                        exit_price = tp; outcome = 'TP'; exit_bar = bar_idx + look
                        break
                    # Model D: exit at close if price returns to VWAP (mean reversion complete)
                    if model_name == 'D' and vwap_of_record is not None:
                        if next_close <= vwap_of_record:
                            exit_price = next_close; outcome = 'VWAP'; exit_bar = bar_idx + look
                            break
                else:  # SHORT
                    if next_high >= sl:
                        exit_price = sl; outcome = 'SL'; exit_bar = bar_idx + look
                        break
                    elif next_low <= tp:
                        exit_price = tp; outcome = 'TP'; exit_bar = bar_idx + look
                        break
                    # Model D: exit at close if price returns to VWAP
                    if model_name == 'D' and vwap_of_record is not None:
                        if next_close >= vwap_of_record:
                            exit_price = next_close; outcome = 'VWAP'; exit_bar = bar_idx + look
                            break

            # If no SL/TP/VWAP hit, exit at close of last held bar
            if exit_price is None:
                last_close = closes[exit_bar] if exit_bar < n else closes[-1]
                exit_price = last_close
                outcome = 'OPEN'

            if direction == 'LONG':
                gain_pct = (exit_price - entry) / entry * 100
            else:
                gain_pct = (entry - exit_price) / entry * 100

            trades.append({
                'stock': name,
                'model': model_name,
                'direction': direction,
                'entry': round(entry, 2),
                'exit': round(exit_price, 2),
                'sl': round(sl, 2),
                'tp': round(tp, 2),
                'atr': round(atr, 3),
                'outcome': outcome,
                'gain_pct': round(gain_pct, 2),
                'bar_idx': bar_idx,
                'exit_bar': exit_bar,
            })

    return trades


def run_backtest():
    print("=" * 70)
    scope = f"{len(ACTIVE_STOCKS)} ticker(s)"
    if hasattr(args, 'ticker') and args.ticker:
        scope = f"1 ticker: {args.ticker.zfill(5)}"
    model_scope = f"model {ACTIVE_MODELS[0]}" if len(ACTIVE_MODELS) == 1 else f"all {len(ACTIVE_MODELS)} models"
    print(f"TJL BACKTEST — {date.today()}  |  {KL_LABEL} bars")
    print(f"                 {TRADE_DAYS} trading days, max {MAX_HOLD}-bar hold, lookback {LOOKBACK}")
    print(f"                 Scope: {scope} × {model_scope}")
    print("=" * 70)

    all_trades = []
    for name, code in ACTIVE_STOCKS:
        print(f"\n  Fetching {code} ({KL_LABEL})...", end=" ", flush=True)
        trades = backtest_stock(code, name)
        print(f"→ {len(trades)} signal(s)")
        all_trades.extend(trades)

    if not all_trades:
        print("\n⚠️  No trades generated across all stocks and models.")
        return

    # Aggregate by model
    print("\n" + "=" * 70)
    print("OVERALL MODEL SUMMARY")
    print("=" * 70)
    model_labels = {
        'D': 'RSI Oversold Bounce',
        'E': '20d High Breakout',
        'F': 'RSI Trend Crossover',
        'G': 'ORB 5-bar + Vol Confirm',
        'H': 'Gold EMA/BB/VWAP',
        'I': 'SHM 63-WMA Pullback',
        'J': 'Follow Money (SMA150/200)',
        'K': 'EMA+VWAP+BB Session Filter',
        'L': 'VWAP Reversion (Daytrade)',
        'M': 'EMA Ribbon Compression (Swing)',
        'N': 'RSI Divergence Reversal (Swing)',
        'O': 'Gap Fill (Daytrade)',
        'P': 'Donchian Breakout + Trend (Swing)',
        'Q': 'ADX Trend Strength (Swing)',
    }
    for model in ['D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q']:
        model_trades = [t for t in all_trades if t['model'] == model]
        if not model_trades:
            continue
        wins = [t for t in model_trades if t['outcome'] == 'TP']
        losses = [t for t in model_trades if t['outcome'] == 'SL']
        opens = [t for t in model_trades if t['outcome'] == 'OPEN']
        n = len(model_trades)
        win_rate = len(wins) / n * 100 if n > 0 else 0
        avg_gain = np.mean([t['gain_pct'] for t in model_trades])
        avg_win  = np.mean([t['gain_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['gain_pct'] for t in losses]) if losses else 0
        label = model_labels.get(model, model)
        print(f"\n  Model {model} ({label}):")
        print(f"    Trades : {n}  |  W: {len(wins)}  L: {len(losses)}  O: {len(opens)}")
        print(f"    Win Rate: {win_rate:.1f}%")
        print(f"    Avg Gain: {avg_gain:+.2f}%  |  Avg Win: {avg_win:+.2f}%  Avg Loss: {avg_loss:+.2f}%")

    # Per-stock breakdown
    print("\n" + "=" * 70)
    print("PER-STOCK BREAKDOWN (all models)")
    print("=" * 70)
    for name, code in BACKTEST_STOCKS:
        stock_trades = [t for t in all_trades if t['stock'] == name]
        if not stock_trades:
            print(f"\n  {name}: no signals")
            continue
        n = len(stock_trades)
        wins = sum(1 for t in stock_trades if t['outcome'] == 'TP')
        wr = wins / n * 100
        avg = np.mean([t['gain_pct'] for t in stock_trades])
        models_fired = sorted(set(t['model'] for t in stock_trades))
        print(f"  {name:<12} n={n:>2}  WR={wr:>5.1f}%  Avg={avg:+.2f}%  Models={models_fired}")

    # Full trade log
    print("\n" + "=" * 70)
    print("TRADE LOG (all)")
    print("=" * 70)
    print(f"{'Stock':<12} {'M':>2} {'Dir':>5} {'Entry':>8} {'Exit':>8} {'SL':>8} {'TP':>8} {'Gain%':>7} {'Outcome'}")
    print("-" * 80)
    for t in sorted(all_trades, key=lambda x: (x['stock'], x['bar_idx'])):
        print(f"{t['stock']:<12} {t['model']:>2} {t['direction']:>5} "
              f"{t['entry']:>8.2f} {t['exit']:>8.2f} {t['sl']:>8.2f} {t['tp']:>8.2f} "
              f"{t['gain_pct']:>+7.2f}%  {t['outcome']}")

    return all_trades


if __name__ == "__main__":
    run_backtest()
