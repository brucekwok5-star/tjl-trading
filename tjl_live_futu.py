#!/usr/bin/env python3
"""
TJL Live Scanner — Futu OpenD Real-Time Data
==============================================
Subscribes to HK stocks via Futu OpenD, calculates EMA stack on daily bars,
and checks live TJL entry conditions every N seconds.

TJL Entry Conditions (3 models — any fire = signal):
  Model A — Pullback:     EMA9 > EMA20 > EMA50  + price within ±1.5% of EMA9  + above PMH + 0.70
  Model B — HT Momentum:  price > SMA200        + price > PMH + 0.70          + price > today's HOD
  Model C — Vol Pullback: Any EMA config         + price within ±2.0% of EMA9 + vol ≥ 2× avg20 + above PMH + 0.70

Exit: SL = price - 1.5*ATR | TP = price + 3.0*ATR

Usage:
  python3 tjl_live_futu.py                   # scan once
  python3 tjl_live_futu.py --continuous     # loop every 30s
  python3 tjl_live_futu.py --continuous --interval 60

Environment:
  DISCORD_WEBHOOK_HK_TJL — Discord webhook URL. If set, posts results.
"""
from tjl_model_tracker import ModelTracker
import sys
import futu as ft
from futu.quote.open_quote_context import OpenQuoteContext, KLType, SubType
ft.OpenQuoteContext = OpenQuoteContext
ft.KLType = KLType
ft.SubType = SubType
import pandas as pd
import numpy as np
import time
import os
import json
import subprocess
import argparse
from datetime import datetime, date
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")

PMH_BUF      = 0.70    # HKD buffer above PMH
ATR_SL       = 1.0     # tighter: 1× ATR stop loss
ATR_TP       = 1.5     # tighter: 1.5× ATR take profit (3:2 R:R)
ATR_PERIOD   = 14
NEAR_EMA_PCT = 0.015   # 1.5% — Model A pullback zone
NEAR_EMA_PCT_C = 0.020  # 2.0% — Model C pullback zone (wider)
VOL_SPIKE_MULT = 2.0    # volume ≥ 2× 20-day avg for Model C
SCAN_INTERVAL = 30     # seconds between scans in continuous mode

WATCHLIST = [
    # ── Financials ───────────────────────────────────────────
    ("00005", "HK.00005"),  # HSBC Holdings
    ("00388", "HK.00388"),  # HKEx
    ("00939", "HK.00939"),  # CCB
    ("01299", "HK.01299"),  # AIA Group
    ("01398", "HK.01398"),  # ICBC
    ("02318", "HK.02318"),  # Ping An
    ("02388", "HK.02388"),  # BOC Hong Kong
    ("02628", "HK.02628"),  # China Life
    ("03968", "HK.03968"),  # China Merchants Bank
    ("03988", "HK.03988"),  # Bank of China
    ("06030", "HK.06030"),  # CITIC Securities
    # ── Utilities ────────────────────────────────────────────
    ("00002", "HK.00002"),  # CLP Holdings
    ("00003", "HK.00003"),  # Hong Kong & China Gas
    ("00006", "HK.00006"),  # Power Assets
    ("00836", "HK.00836"),  # China Resources Power
    ("01038", "HK.01038"),  # Cheung Kong Infrastructure
    ("02688", "HK.02688"),  # ENN Energy
    # ── Properties ──────────────────────────────────────────
    ("00012", "HK.00012"),  # Henderson Land
    ("00016", "HK.00016"),  # Sun Hung Kai Properties
    ("00101", "HK.00101"),  # Hang Lung Properties
    ("00688", "HK.00688"),  # China Overseas Land & Investment
    ("00823", "HK.00823"),  # Link REIT
    ("00960", "HK.00960"),  # Longfor Properties
    ("01109", "HK.01109"),  # China Resources Land
    ("01113", "HK.01113"),  # CK Asset Holdings
    ("01209", "HK.01209"),  # China Resources Mixc Lifestyle
    ("01997", "HK.01997"),  # Wharf Real Estate
    # ── Commerce & Industry ────────────────────────────────────
    ("00001", "HK.00001"),  # CK Hutchison
    ("00027", "HK.00027"),  # Galaxy Entertainment
    ("00066", "HK.00066"),  # MTR Corporation
    ("00175", "HK.00175"),  # Geely Auto
    ("00241", "HK.00241"),  # Alibaba Health
    ("00257", "HK.00257"),  # China Everbright
    ("00267", "HK.00267"),  # CITIC Limited
    ("00285", "HK.00285"),  # BYD Electronics
    ("00288", "HK.00288"),  # WH Group
    ("00291", "HK.00291"),  # China Resources Beer
    ("00300", "HK.00300"),  # Midea Group
    ("00316", "HK.00316"),  # Orient Overseas
    ("00322", "HK.00322"),  # Tingyi
    ("00358", "HK.00358"),  # Shanghai Electric
    ("00386", "HK.00386"),  # Sinopec
    ("00669", "HK.00669"),  # Techtronic Industries
    ("00700", "HK.00700"),  # Tencent
    ("00728", "HK.00728"),  # China Telecom
    ("00762", "HK.00762"),  # China Unicom
    ("00857", "HK.00857"),  # PetroChina
    ("00868", "HK.00868"),  # Xinyi Glass
    ("00881", "HK.00881"),  # Zhongsheng Group
    ("00883", "HK.00883"),  # CNOOC
    ("00941", "HK.00941"),  # China Mobile
    ("00968", "HK.00968"),  # Xinyi Solar
    ("00981", "HK.00981"),  # SMIC
    ("00992", "HK.00992"),  # Lenovo
    ("01024", "HK.01024"),  # Kuaishou
    ("01044", "HK.01044"),  # Hengan International
    ("01088", "HK.01088"),  # China Shenhua Energy
    ("01093", "HK.01093"),  # CSPC Pharmaceutical
    ("01099", "HK.01099"),  # Sinopharm
    ("01177", "HK.01177"),  # Sino Biopharm
    ("01211", "HK.01211"),  # BYD
    ("01378", "HK.01378"),  # China Hongqiao Group
    ("01810", "HK.01810"),  # Xiaomi
    ("01818", "HK.01818"),  # Zoomlion
    ("01876", "HK.01876"),  # Budweiser Brewing
    ("01888", "HK.01888"),  # Kingboard Laminates
    ("01928", "HK.01928"),  # Sands China
    ("01929", "HK.01929"),  # Chow Tai Fook
    ("01972", "HK.01972"),  # Swire Properties
    ("02015", "HK.02015"),  # Li Auto
    ("02020", "HK.02020"),  # Anta Sports
    ("02057", "HK.02057"),  # ZTO Express
    ("02096", "HK.02096"),  # China Resources Healthcare
    ("02099", "HK.02099"),  # China Resources Pharma
    ("02269", "HK.02269"),  # WuXi Biologics
    ("02282", "HK.02282"),  # Kangda Biotech
    ("02313", "HK.02313"),  # Shenzhou International
    ("02319", "HK.02319"),  # Mengniu Dairy
    ("02331", "HK.02331"),  # Li-Ning
    ("02338", "HK.02338"),  # AVIC
    ("02359", "HK.02359"),  # WuXi AppTec
    ("02382", "HK.02382"),  # Sunny Optical
    ("02588", "HK.02588"),  # Bank of Communications
    ("02600", "HK.02600"),  # Chalco
    ("02618", "HK.02618"),  # JD Logistics
    ("02865", "HK.02865"),  # Drinda
    ("02883", "HK.02883"),  # China Resources Gas
    ("02899", "HK.02899"),  # Zijin Mining
    ("03309", "HK.03309"),  # C-MER Medical
    ("03606", "HK.03606"),  # MDV Holdings
    ("03690", "HK.03690"),  # Meituan
    ("03692", "HK.03692"),  # Hansoh Pharmaceutical
    ("03750", "HK.03750"),  # Shanghai Hanbao
    ("03939", "HK.03939"),  # Wanguo Gold
    ("03986", "HK.03986"),  # GigaDevice
    ("03993", "HK.03993"),  # CMOC
    ("03998", "HK.03998"),  # CSPC Innovation
    ("06031", "HK.06031"),  # Tsingtao Brewery
    ("06082", "HK.06082"),  # Biren Technology
    ("06098", "HK.06098"),  # China Vanke
    ("06199", "HK.06199"),  # Longfor Group
    ("06618", "HK.06618"),  # JD Health
    ("06690", "HK.06690"),  # Haier Smart Home
    ("06808", "HK.06808"),  # Hengan
    ("06809", "HK.06809"),  # Montage Technology
    ("06862", "HK.06862"),  # Haidilao
    ("06869", "HK.06869"),  # FiberHome
    ("07618", "HK.07618"),  # AIA Health
    ("07688", "HK.07688"),  # Topu CNC
    ("09618", "HK.09618"),  # JD.com
    ("09633", "HK.09633"),  # Nongfu Spring
    ("09888", "HK.09888"),  # Baidu
    ("09889", "HK.09889"),  # China Ruyi
    ("09898", "HK.09898"),  # XPeng
    ("09901", "HK.09901"),  # Garrison Metals
    ("09961", "HK.09961"),  # Trip.com
    ("09988", "HK.09988"),  # Alibaba
    ("09992", "HK.09992"),  # Pop Mart
    ("09999", "HK.09999"),  # NetEase
]

ALL_CODES = [code for _, code in WATCHLIST]

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(HKT).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


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


def get_daily_bars(ctx, code, count=80):
    ret, kl, _ = ctx.request_history_kline(code, ktype=ft.KLType.K_DAY, max_count=count)
    if ret != 0 or kl is None or kl.empty:
        return None, None, None, None
    kl = kl.sort_values('time_key').reset_index(drop=True)
    return kl['high'].values, kl['low'].values, kl['close'].values, kl['volume'].values


def get_live_quotes(ctx, codes):
    # Subscribe in small batches to avoid bulk-call failures from unknown codes
    result = {}
    for code in codes:
        ctx.subscribe([code], [ft.SubType.QUOTE])
    time.sleep(2.0)  # allow all subscriptions to settle
    # Fetch one at a time so unknown stocks don't poison the batch
    for code in codes:
        ret, df = ctx.get_stock_quote([code])
        if ret != 0 or df is None:
            continue
        if isinstance(df, str):  # error string
            continue
        for _, row in df.iterrows():
            result[code] = {
                'price':      float(row['last_price']),
                'prev_close': float(row['prev_close_price']),
                'high_today': float(row['high_price']),
                'low_today':  float(row['low_price']),
                'open_today': float(row.get('open_price', row['prev_close_price'])),
                'volume':     int(row['volume']),
            }
    return result


def detect_regime(ctx, watchlist):
    """Return 'bullish', 'bearish', or 'neutral' based on EMA stack distribution."""
    bearish = 0
    bullish = 0
    evaluated = 0
    for name, code in watchlist:
        _, _, closes, _ = get_daily_bars(ctx, code, count=80)
        if closes is None or len(closes) < 60:
            continue
        e9, e20, e50 = calc_emas(closes)
        if any(np.isnan(x) for x in [e9, e20, e50]):
            continue
        evaluated += 1
        if e9 < e20 < e50:
            bearish += 1
        elif e9 > e20 > e50:
            bullish += 1
    if evaluated == 0:
        return 'neutral', 0, 0, evaluated
    bear_pct = bearish / evaluated
    bull_pct = bullish / evaluated
    if bear_pct >= 0.60:
        return 'bearish', bear_pct, bull_pct, evaluated
    elif bull_pct >= 0.60:
        return 'bullish', bear_pct, bull_pct, evaluated
    return 'neutral', bear_pct, bull_pct, evaluated


def check_tjl(price, highs, lows, closes, today_high):
    """Long entry: bullish stack + pullback to EMA9 + above PMH."""
    if len(closes) < 60:
        return None
    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None
    pmh = today_high if today_high else price
    stack_ok     = (e9 > e20 > e50)
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT)
    above_pmh_ok = (price > pmh + PMH_BUF)
    sl = price - ATR_SL * atr
    tp = price + ATR_TP * atr
    return {
        'price':        round(price, 2),
        'e9':           round(e9, 2),
        'e20':          round(e20, 2),
        'e50':          round(e50, 2),
        'atr':          round(atr, 3),
        'pmh':          round(pmh, 2),
        'sl':           round(sl, 2),
        'tp':           round(tp, 2),
        'rr_ratio':     round((ATR_TP * atr) / (ATR_SL * atr), 2),
        'direction':    'LONG',
        'model_a': {
            'stack_ok':     stack_ok,
            'near_ema_ok':  near_ema_ok,
            'above_pmh_ok': above_pmh_ok,
        },
        'model_b': None,   # filled by check_tjl_model_b
    }


def check_tjl_model_b(price, highs, lows, closes, today_high):
    """Model B (HT Momentum): above SMA200 + above PMH + above today's HOD."""
    if len(closes) < 200:
        return None
    sma200 = np.mean(closes[-200:])
    if np.isnan(sma200):
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None
    pmh = today_high if today_high else price
    hod = today_high if today_high else price
    above_sma200_ok = (price > sma200)
    above_pmh_ok    = (price > pmh + PMH_BUF)
    above_hod_ok    = (price > hod)
    sl = price - ATR_SL * atr
    tp = price + ATR_TP * atr
    return {
        'price':          round(price, 2),
        'sma200':         round(sma200, 2),
        'atr':            round(atr, 3),
        'pmh':            round(pmh, 2),
        'hod':            round(hod, 2),
        'sl':             round(sl, 2),
        'tp':             round(tp, 2),
        'rr_ratio':       round((ATR_TP * atr) / (ATR_SL * atr), 2),
        'direction':      'LONG',
        'above_sma200_ok': above_sma200_ok,
        'above_pmh_ok':    above_pmh_ok,
        'above_hod_ok':    above_hod_ok,
    }


def check_tjl_model_c(price, highs, lows, closes, volumes, today_high):
    """
    Model C — Volume-Confirmed Pullback:
      1. Any EMA configuration (flexible — not strict 9>20>50)
      2. Price within ±2% of EMA9 (wider than Model A's ±1.5%)
      3. Volume ≥ 2× 20-day average volume on the pullback day
      4. Above today's PMH + buffer
    """
    if len(closes) < 21 or len(volumes) < 21:
        return None
    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None
    # 20-day average volume (skip today as it's partial)
    avg_vol20 = np.mean(volumes[-21:-1])  # last 20 complete days
    today_vol = volumes[-1] if len(volumes) >= 1 else 0
    vol_spike_ok = (today_vol >= VOL_SPIKE_MULT * avg_vol20)
    pmh = today_high if today_high else price
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT_C)
    above_pmh_ok = (price > pmh + PMH_BUF)
    sl = price - ATR_SL * atr
    tp = price + ATR_TP * atr
    return {
        'price':         round(price, 2),
        'e9':            round(e9, 2),
        'e20':           round(e20, 2),
        'e50':           round(e50, 2),
        'atr':           round(atr, 3),
        'avg_vol20':     round(avg_vol20, 0),
        'today_vol':     int(today_vol),
        'vol_ratio':     round(today_vol / avg_vol20, 1) if avg_vol20 > 0 else 0,
        'pmh':           round(pmh, 2),
        'sl':            round(sl, 2),
        'tp':            round(tp, 2),
        'rr_ratio':      round((ATR_TP * atr) / (ATR_SL * atr), 2),
        'direction':     'LONG',
        'near_ema_ok':   near_ema_ok,
        'above_pmh_ok':  above_pmh_ok,
        'vol_spike_ok':  vol_spike_ok,
    }


# ── Model D: VWAP Mean Reversion ─────────────────────────────────────────────
# Logic:
#   LONG:  price > VWAP AND RSI(14) < 60  (overbought RSI = reversion to VWAP)
#   SHORT: price < VWAP AND RSI(14) > 40  (oversold RSI = reversion upward)
# Entry: ATR-based SL/TP
# Regime: LONG in bullish/neutral only; SHORT in bearish/neutral only

def calc_vwap(highs, lows, closes, volumes):
    """Compute VWAP from daily bars (high/low/close typical, weighted by volume)."""
    if len(highs) < 2 or len(volumes) < 2:
        return None
    typical = (np.array(highs) + np.array(lows) + np.array(closes)) / 3.0
    vol = np.array(volumes, dtype=float)
    cum_pv = np.cumsum(typical * vol)
    cum_vol = np.cumsum(vol)
    # VWAP = cumulative price*vol / cumulative vol; align to last bar
    vwap = cum_pv / cum_vol
    return float(vwap[-1])


def calc_rsi(closes, period=14):
    """Compute RSI(14) from close prices."""
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)


def check_tjl_model_d(price, highs, lows, closes, volumes, today_high, today_low):
    """
    Model D — RSI Oversold Bounce (TRUE mean reversion):
      Entry: RSI(14) crosses UP through 30 from BELOW 30 (oversold bounce)
             AND price within 1% of VWAP
             AND price above PMH (confirm momentum shift)
      Exit: price crosses back below VWAP = take profit
      SL: 1× ATR, TP: 1.5× ATR (3:2 R:R)
    """
    if len(closes) < 22 or len(volumes) < 21:
        return None
    vwap = calc_vwap(highs, lows, closes, volumes)
    atr  = calc_atr(highs, lows, closes)
    if vwap is None or atr is None or np.isnan(atr):
        return None

    # RSI — need previous bar's RSI too to detect crossing
    rsi_now = calc_rsi(closes)
    rsi_prev = calc_rsi(closes[:-1]) if len(closes) >= 15 else None
    if rsi_now is None or rsi_prev is None:
        return None

    # RSI crosses UP through 30 from below (true oversold bounce)
    rsi_bounce = (rsi_prev < 30) and (rsi_now >= 30)
    near_vwap  = abs(price - vwap) / vwap < 0.015   # within 1.5% of VWAP
    above_pmh  = price >= today_high - 0.70          # above premarket high

    long_fire = rsi_bounce and near_vwap and above_pmh
    if not long_fire:
        return None

    sl = price - ATR_SL * atr
    tp = price + ATR_TP * atr

    return {
        'price':       round(price, 2),
        'vwap':       round(vwap, 3),
        'rsi_now':    round(rsi_now, 1),
        'rsi_prev':   round(rsi_prev, 1),
        'atr':        round(atr, 3),
        'pmh':        round(today_high, 2),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   round(ATR_TP / ATR_SL, 2),
        'direction':  'LONG',
        'long_fire':  long_fire,
        'near_vwap':  near_vwap,
        'rsi_bounce': rsi_bounce,
    }


# ── Model E: Bollinger Band Squeeze Breakout ──────────────────────────────────
# Logic:
#   Squeeze: current BB bandwidth < 20% of 20-bar average bandwidth
#   Expansion: bandwidth expands > 1.5× on the breakout bar
#   Volume surge: volume > 1.5× 20-bar avg on expansion day
#   LONG only: squeeze resolves upward with volume confirmation

def calc_bb_bands(closes, period=20, num_std=2):
    """Return (upper, middle, lower, bandwidth) as numpy arrays."""
    if len(closes) < period:
        return None, None, None, None
    s = pd.Series(closes)
    mid = s.rolling(period).mean().values
    std = s.rolling(period).std().values
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid * 100  # as % of midpoint
    return upper, mid, lower, bandwidth


def check_tjl_model_e(price, highs, lows, closes, volumes, today_high):
    """
    Model E -- 20-Day High Breakout (MOMENTUM):
      LONG:  price breaks above 20-day high AND RSI > 50 AND vol > 1.5x avg20
      SHORT: price breaks below 20-day low  AND RSI < 50 AND vol > 1.5x avg20
      Rationale: break of 20-day high in uptrend with volume confirmation.
      SL: 1x ATR, TP: 1.5x ATR (3:2 R:R)
    """
    if len(closes) < 22 or len(volumes) < 21:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None

    rsi = calc_rsi(closes)
    if rsi is None:
        return None

    # 20-day high/low (excluding today — need yesterday's close as "today" proxy)
    high_20  = float(np.max(highs[-21:-1]))   # yesterday's 20-day high
    low_20   = float(np.min(lows[-21:-1]))     # yesterday's 20-day low

    avg_vol20 = np.mean(volumes[-21:-1])
    vol_ratio = volumes[-1] / avg_vol20 if avg_vol20 > 0 else 0
    vol_ok    = vol_ratio >= 1.5

    above_high = price > high_20
    below_low  = price < low_20

    long_fire  = above_high and vol_ok and (rsi > 50)
    short_fire = below_low  and vol_ok and (rsi < 50)

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    sl = price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr
    tp = price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr

    return {
        'price':        round(price, 2),
        'high_20':     round(high_20, 3),
        'low_20':      round(low_20, 3),
        'rsi':         round(rsi, 1),
        'atr':         round(atr, 3),
        'avg_vol20':  round(avg_vol20, 0),
        'today_vol':  int(volumes[-1]),
        'vol_ratio':  round(vol_ratio, 1),
        'pmh':        round(today_high, 2),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   round(ATR_TP / ATR_SL, 2),
        'direction':   direction,
        'long_fire':  long_fire,
        'short_fire': short_fire,
        'above_high': above_high,
        'below_low':  below_low,
        'vol_ok':     vol_ok,
    }


def check_tjl_model_f(price, highs, lows, closes, volumes, today_high, today_low):
    """
    Model F — RSI Trend Crossover:
      Long:  RSI(14) crosses ABOVE 50 while price is above EMA20
      Short: RSI(14) crosses BELOW 50 while price is below EMA20
      Confirmed by: volume > avg20 * 1.2 AND ATR confirming the move.
      SL: 1x ATR, TP: 1.5x ATR (3:2 R:R)
    """
    if len(closes) < 22 or len(volumes) < 21:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None

    rsi = calc_rsi(closes)
    if rsi is None:
        return None

    ema20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else price

    # Previous RSI (yesterday's close-based)
    prev_rsi = calc_rsi(closes[:-1]) if len(closes) >= 15 else None

    avg_vol20 = np.mean(volumes[-21:-1])
    vol_ratio = volumes[-1] / avg_vol20 if avg_vol20 > 0 else 0
    vol_ok    = vol_ratio >= 1.2

    price_above_ema = price > ema20
    price_below_ema = price < ema20

    # RSI crossed above 50
    rsi_cross_up   = (prev_rsi is not None) and (prev_rsi < 50) and (rsi > 50)
    # RSI crossed below 50
    rsi_cross_down = (prev_rsi is not None) and (prev_rsi > 50) and (rsi < 50)

    long_fire  = price_above_ema and rsi_cross_up  and vol_ok
    short_fire = price_below_ema and rsi_cross_down and vol_ok

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    sl = price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr
    tp = price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr

    return {
        'price':        round(price, 2),
        'ema20':        round(ema20, 3),
        'rsi':          round(rsi, 1),
        'prev_rsi':     round(prev_rsi, 1) if prev_rsi else None,
        'atr':          round(atr, 3),
        'avg_vol20':   round(avg_vol20, 0),
        'today_vol':   int(volumes[-1]),
        'vol_ratio':   round(vol_ratio, 1),
        'sl':           round(sl, 2),
        'tp':           round(tp, 2),
        'rr_ratio':    round(ATR_TP / ATR_SL, 2),
        'direction':    direction,
        'long_fire':   long_fire,
        'short_fire':  short_fire,
        'vol_ok':      vol_ok,
        'price_above_ema': price_above_ema,
        'price_below_ema': price_below_ema,
    }


# ── Model F: Opening Range Breakout (ORB) ─────────────────────────────────────
# Logic:
#   30-min OR: high/low of first 30 minutes of trading
#   Break of OR high with volume confirmation → LONG
#   Break of OR low with volume confirmation → SHORT
#   Volume confirmation: today's volume at time of break > 1.5× avg volume at same time-of-day
#   Note: With daily bars only, we approximate OR as today's HOD/LOD vs previous day's close
#         and use the HOD/LOD of the current day as proxy. We also use intraday bar data
#         from Futu to get 30-min range when available, else fall back to heuristic.

def get_intraday_bars_30min(ctx, code):
    """
    Fetch 30-minute bars for today (up to 20 bars = 10 hours of trading).
    Returns (orb_high, orb_low) or (None, None) if unavailable.
    """
    ret, kl, _ = ctx.request_history_kline(
        code, ktype=ft.KLType.K_30M, max_count=20,
        start_date=date.today().strftime("%Y-%m-%d"),
        end_date=date.today().strftime("%Y-%m-%d")
    )
    if ret != 0 or kl is None or kl.empty:
        return None, None
    kl = kl.sort_values('time_key').reset_index(drop=True)
    # First 30-min bar is bar index 0
    if len(kl) < 1:
        return None, None
    orb_high = float(kl['high'].iloc[0])
    orb_low  = float(kl['low'].iloc[0])
    return orb_high, orb_low


def calc_vwap_bars(highs, lows, closes, volumes):
    """VWAP over a sliding window (typical = full day or N bars)."""
    typical = (np.array(highs) + np.array(lows) + np.array(closes)) / 3.0
    cumvol = np.cumsum(np.array(volumes))
    cumtp = np.cumsum(typical * np.array(volumes))
    return cumtp / cumvol


def check_tjl_model_g(price, highs, lows, closes, volumes, today_high, today_low, today_open):
    """
    Model G — Opening Range Breakout (ORB).
    Long: price breaks ABOVE today's opening range high (first 15–30 min).
    Short: price breaks BELOW today's opening range low.
    Confirmed by: volume > avg20 * 1.2 AND ATR confirming the move.
    Exit: ATR-based SL/TP (1x / 1.5x). Always flat by EOD.
    SL: 1x ATR, TP: 1.5x ATR (3:2 R:R)
    """
    if len(closes) < 30 or today_open is None:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None

    # Opening range: high/low of first 3 x 15-min bars (9:30–10:00)
    # In live: use today's high/low since open
    orb_high = today_high
    orb_low  = today_low

    vol_avg20 = np.mean(volumes[-21:-1]) if len(volumes) >= 21 else np.mean(volumes[:-1])
    vol_now   = volumes[-1] if len(volumes) >= 1 else 0
    vol_ok    = vol_now >= vol_avg20 * 1.2

    long_fire  = (price > orb_high) and vol_ok
    short_fire = (price < orb_low)  and vol_ok

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    sl = price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr
    tp = price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr

    return {
        'price':       round(price, 2),
        'orb_high':    round(orb_high, 2),
        'orb_low':     round(orb_low, 2),
        'today_open':  round(today_open, 2),
        'atr':         round(atr, 3),
        'vol_now':     round(vol_now, 0),
        'vol_avg20':   round(vol_avg20, 0),
        'vol_ratio':   round(vol_now / vol_avg20, 2) if vol_avg20 > 0 else 0,
        'sl':          round(sl, 2),
        'tp':          round(tp, 2),
        'rr_ratio':    round(ATR_TP / ATR_SL, 2),
        'direction':   direction,
        'long_fire':   long_fire,
        'short_fire':  short_fire,
    }


def check_tjl_model_h(price, highs, lows, closes, volumes, today_high, today_low):
    """
    Model H — Gold EMA/BB/VWAP (trend-following intraday).
    Entry: Fast EMA crosses BB midline AND price above slow EMA AND price above VWAP.
    LONG: EMA9 crosses above BB mid(20) + price > EMA21 + price > VWAP.
    SHORT: EMA9 crosses below BB mid(20) + price < EMA21 + price < VWAP.
    SL: 1x ATR, TP: 1.5x ATR (3:2 R:R)
    """
    if len(closes) < 25 or len(volumes) < 21:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None

    s = pd.Series(closes)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e21 = float(s.ewm(span=21, adjust=False).mean().iloc[-1])
    e9_prev  = float(s.ewm(span=9,  adjust=False).mean().iloc[-2])
    if any(np.isnan(x) for x in [e9, e21, e9_prev]):
        return None

    # Bollinger Bands midline = 20-SMA
    bb_mid = float(s.rolling(20).mean().iloc[-1])
    bb_prev = float(s.rolling(20).mean().iloc[-2])
    if np.isnan(bb_mid) or np.isnan(bb_prev):
        return None

    # VWAP
    vwap = calc_vwap(highs, lows, closes, volumes)

    # Crossover: EMA9 crosses BB midline
    cross_up   = (e9_prev < bb_prev) and (e9 >= bb_mid)
    cross_down = (e9_prev > bb_prev) and (e9 <= bb_mid)

    # Trend filter: price above both EMA21 and VWAP for longs
    price_above_all = (price > e21) and (price > vwap)
    price_below_all = (price < e21) and (price < vwap)

    long_fire  = cross_up  and price_above_all
    short_fire = cross_down and price_below_all

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    sl = price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr
    tp = price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr

    return {
        'price':      round(price, 2),
        'e9':         round(e9, 3),
        'e21':        round(e21, 3),
        'bb_mid':     round(bb_mid, 3),
        'vwap':       round(vwap, 3),
        'atr':        round(atr, 3),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   round(ATR_TP / ATR_SL, 2),
        'direction':  direction,
        'long_fire':  long_fire,
        'short_fire': short_fire,
    }


def check_tjl_model_i(price, highs, lows, closes, volumes, today_high):
    """
    Model I — SHM-lite (Daily swing: 63-WMA trend + RSI momentum gate).
    Adapted from Sovereign Horizon Matrix for HK daily bars.
    LONG: price > 63-WMA AND RSI(14) > 50 AND price within 3% of 63-WMA (pullback to trend).
    SHORT: price < 63-WMA AND RSI(14) < 50 AND price within 3% of 63-WMA (rally to trend).
    SL: 1.5x ATR, TP: 3x ATR (2:1 R:R) — swings need room.
    Guards: skip if ATR > 20% of price (penny stocks with unreliable ATR).
    """
    if len(closes) < 65 or len(volumes) < 21:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None
    # Reject penny stocks where ATR is unreliable (ATR > 20% of price)
    if price < 1.0 or atr / price > 0.20:
        return None

    s = pd.Series(closes)
    wma63 = float(s.rolling(63).mean().iloc[-1])
    if np.isnan(wma63) or wma63 <= 0:
        return None

    rsi = calc_rsi(closes)
    if rsi is None or np.isnan(rsi):
        return None

    # Pullback zone: price within 3% of WMA63
    # LONG fires when price has pulled BACK to WMA63 from above (price < wma63 but near it)
    # SHORT fires when price has rallied TO WMA63 from below (price > wma63 but near it)
    pullback_tolerance = 0.03
    near_wma_from_below = price < wma63 and abs(price - wma63) / wma63 <= pullback_tolerance
    near_wma_from_above = price > wma63 and abs(price - wma63) / wma63 <= pullback_tolerance

    # LONG: price has pulled BACK to WMA63 from above + RSI > 50 confirms bounce
    long_fire  = near_wma_from_below and (rsi > 50)
    # SHORT: price has rallied TO WMA63 from below + RSI < 50 confirms rejection
    short_fire = near_wma_from_above and (rsi < 50)

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    # Swing models need wider R:R (2:1): SL=1.5ATR, TP=3.0ATR
    sl = price - 1.5 * atr if direction == 'LONG' else price + 1.5 * atr
    tp = price + 3.0 * atr if direction == 'LONG' else price - 3.0 * atr

    return {
        'price':     round(price, 2),
        'wma63':     round(wma63, 3),
        'rsi':       round(rsi, 1),
        'atr':       round(atr, 3),
        'sl':        round(sl, 2),
        'tp':        round(tp, 2),
        'rr_ratio':  round(3.0 / 1.5, 2),
        'direction': direction,
        'long_fire': long_fire,
        'short_fire': short_fire,
    }


def check_tjl_model_j(price, highs, lows, closes, volumes, today_high):
    """
    Model J — Follow the Money (institutional mean reversion).
    150/200 DMA baseline + volume surge confirm.
    LONG: price pulls back TO or NEAR 150-DMA AND above 200-DMA AND vol > 1.5x avg20.
    SHORT: price pulls up TO or NEAR 150-DMA AND below 200-DMA AND vol > 1.5x avg20.
    SL: 1x ATR, TP: 1.5x ATR (3:2 R:R)
    """
    if len(closes) < 155 or len(volumes) < 21:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None

    s = pd.Series(closes)
    dma150 = float(s.rolling(150).mean().iloc[-1])
    dma200 = float(s.rolling(200).mean().iloc[-1])
    if np.isnan(dma150) or np.isnan(dma200):
        return None

    vol_avg20 = float(pd.Series(volumes).rolling(20).mean().iloc[-1])
    vol_now   = volumes[-1]
    if np.isnan(vol_avg20) or vol_avg20 == 0:
        return None

    # Pullback: price within 2% of 150-DMA
    near_dma150 = abs(price - dma150) / dma150 <= 0.02
    above_200   = price > dma200
    below_200   = price < dma200
    vol_ok      = vol_now >= vol_avg20 * 1.5

    long_fire  = near_dma150 and above_200 and vol_ok
    short_fire = near_dma150 and below_200 and vol_ok

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    sl = price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr
    tp = price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr

    return {
        'price':      round(price, 2),
        'dma150':     round(dma150, 3),
        'dma200':     round(dma200, 3),
        'atr':        round(atr, 3),
        'vol_now':    round(vol_now, 0),
        'vol_avg20':  round(vol_avg20, 0),
        'vol_ratio':  round(vol_now / vol_avg20, 2),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   round(ATR_TP / ATR_SL, 2),
        'direction':  direction,
        'long_fire':  long_fire,
        'short_fire': short_fire,
    }


def check_tjl_model_k(price, highs, lows, closes, volumes, today_high, today_low):
    """
    Model K — EMA/VWAP/Bollinger Session (clean intraday).
    From: Gold Intraday EMA/BB/VWAP + Reliable Alerts.
    LONG: Fast EMA (9) crosses above BB mid(20) AND price > EMA21 AND price > VWAP.
    SHORT: Fast EMA (9) crosses below BB mid(20) AND price < EMA21 AND price < VWAP.
    Asia session active (9:30–12:00 HKT implied).
    SL: 1x ATR, TP: 1.5x ATR (3:2 R:R)
    """
    if len(closes) < 25 or len(volumes) < 21:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None

    s = pd.Series(closes)
    e9   = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e21  = float(s.ewm(span=21, adjust=False).mean().iloc[-1])
    e9_p = float(s.ewm(span=9,  adjust=False).mean().iloc[-2])
    if any(np.isnan(x) for x in [e9, e21, e9_p]):
        return None

    bb_mid  = float(s.rolling(20).mean().iloc[-1])
    bb_mid_p = float(s.rolling(20).mean().iloc[-2])
    if np.isnan(bb_mid):
        return None

    vwap = calc_vwap(highs, lows, closes, volumes)

    cross_up   = (e9_p < bb_mid_p) and (e9 >= bb_mid)
    cross_down = (e9_p > bb_mid_p) and (e9 <= bb_mid)

    above_all = (price > e21) and (price > vwap)
    below_all = (price < e21) and (price < vwap)

    long_fire  = cross_up  and above_all
    short_fire = cross_down and below_all

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    sl = price - ATR_SL * atr if direction == 'LONG' else price + ATR_SL * atr
    tp = price + ATR_TP * atr if direction == 'LONG' else price - ATR_TP * atr

    return {
        'price':      round(price, 2),
        'e9':         round(e9, 3),
        'e21':        round(e21, 3),
        'bb_mid':     round(bb_mid, 3),
        'vwap':       round(vwap, 3),
        'atr':        round(atr, 3),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   round(ATR_TP / ATR_SL, 2),
        'direction':  direction,
        'long_fire':  long_fire,
        'short_fire': short_fire,
    }


def check_tjl_model_m(price, highs, lows, closes, volumes, today_high, today_low):
    """
    Model M — EMA Ribbon Compression (Swing).
    Backtest: 33% WR, PF 1.73, +0.87% expectancy. Rare but clean signals.
    LONG: EMA9 > EMA21 > EMA50 AND spread(EMA9, EMA50) < 1% AND price breaks above EMA9.
    SHORT: EMA9 < EMA21 < EMA50 AND spread < 1% AND price breaks below EMA9.
    Exit: SL = EMA50, TP = 3 ATR.
    """
    if len(closes) < 55 or len(volumes) < 21:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None

    s = pd.Series(closes)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e21 = float(s.ewm(span=21, adjust=False).mean().iloc[-1])
    e50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
    prev_close = float(closes[-2])

    if any(np.isnan(x) or x <= 0 for x in [e9, e21, e50]):
        return None

    spread_pct = abs(e9 - e50) / e50 * 100
    compressed = spread_pct < 1.0
    bull_stack = e9 > e21 > e50
    bear_stack = e9 < e21 < e50

    # Breakout from compression
    long_breakout  = (prev_close <= e9) and (price > e9)
    short_breakout = (prev_close >= e9) and (price < e9)

    long_fire  = compressed and bull_stack and long_breakout
    short_fire = compressed and bear_stack and short_breakout

    if not (long_fire or short_fire):
        return None

    direction = 'LONG' if long_fire else 'SHORT'
    sl = e50
    tp = price + 3.0 * atr if direction == 'LONG' else price - 3.0 * atr

    return {
        'price':      round(price, 2),
        'e9':         round(e9, 3),
        'e21':        round(e21, 3),
        'e50':        round(e50, 3),
        'atr':        round(atr, 3),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   3.0,
        'direction':  direction,
        'long_fire':  long_fire,
        'short_fire': short_fire,
    }


# ── Model R: Keltner Channel + RSI Breakout ─────────────────────────────────
# From: KeltnerChannelRSIBreakoutStrategy.py (ali-azary repo)
# Idea: Price breaks Keltner band (EMA±ATR) + RSI confirms direction.
# LONG: price > upper_band AND RSI > 30. SHORT: price < lower_band AND RSI < 70.
# SL: 1.5 ATR, TP: 3 ATR.
def check_tjl_model_r(price, highs, lows, closes, volumes, today_high, today_low):
    if len(closes) < 35 or len(volumes) < 14:
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None

    s = pd.Series(closes)
    ema30 = float(s.ewm(span=30, adjust=False).mean().iloc[-1])
    if np.isnan(ema30) or ema30 <= 0:
        return None

    upper_band = ema30 + atr
    lower_band = ema30 - atr

    # RSI
    deltas = pd.Series(closes).diff()
    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)
    avg_gain = gains.ewm(com=13, adjust=False).mean().iloc[-1]
    avg_loss = losses.ewm(com=13, adjust=False).mean().iloc[-1]
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs)) if avg_loss > 0 else 100

    prev_close = float(closes[-2]) if len(closes) >= 2 else price

    long_fire  = (price > upper_band) and (rsi > 30)
    short_fire = (price < lower_band) and (rsi < 70)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {
        'price': round(price, 2),
        'ema30': round(ema30, 2),
        'atr': round(atr, 3),
        'rsi': round(rsi, 1),
        'sl': round(price - 1.5 * atr if direction == 'LONG' else price + 1.5 * atr, 2),
        'tp': round(price + 3.0 * atr if direction == 'LONG' else price - 3.0 * atr, 2),
        'rr_ratio': 2.0,
        'direction': direction,
        'long_fire': long_fire,
        'short_fire': short_fire,
    }


# ── Model S: Ichimoku Cloud Breakout ────────────────────────────────────────
# From: IchimokuCloudStrategy.py (ali-azary repo) — adapted to pure numpy/pandas
# Idea: Price breaks cloud (Kumo) + Tenkan/Kijun cross + Chikou confirms.
# LONG: above cloud AND TK > KJ AND Chikou > price 14 bars ago.
# SHORT: below cloud AND TK < KJ AND Chikou < price 14 bars ago.
# SL: 1.5 ATR, TP: 3 ATR.
def check_tjl_model_s(price, highs, lows, closes, volumes, today_high, today_low):
    if len(closes) < 55:
        return None
    h = np.array(highs)
    l = np.array(lows)
    c = np.array(closes)

    if len(c) < 16:
        return None

    tenkan = (np.max(h[-9:]) + np.min(l[-9:])) / 2
    kijun  = (np.max(h[-26:]) + np.min(l[-26:])) / 2
    senkou_a = (tenkan + kijun) / 2
    senkou_b = (np.max(h[-52:]) + np.min(l[-52:])) / 2
    chikou = c[-1] - c[-15] if len(c) >= 15 else 0

    if np.isnan(tenkan) or np.isnan(kijun) or np.isnan(senkou_a):
        return None

    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None

    cloud_top = max(senkou_a, senkou_b)
    cloud_bot = min(senkou_a, senkou_b)

    long_fire  = (price > cloud_top) and (tenkan > kijun) and (chikou > 0)
    short_fire = (price < cloud_bot) and (tenkan < kijun) and (chikou < 0)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {
        'price': round(price, 2),
        'atr': round(atr, 3),
        'tenkan': round(tenkan, 2),
        'kijun': round(kijun, 2),
        'cloud_top': round(cloud_top, 2),
        'cloud_bot': round(cloud_bot, 2),
        'sl': round(price - 1.5 * atr if direction == 'LONG' else price + 1.5 * atr, 2),
        'tp': round(price + 3.0 * atr if direction == 'LONG' else price - 3.0 * atr, 2),
        'rr_ratio': 2.0,
        'direction': direction,
        'long_fire': long_fire,
        'short_fire': short_fire,
    }


# ── Model T: Mean Reversion z-score ─────────────────────────────────────────
# From: OUMeanReversionStrategy.py (ali-azary repo) — adapted to daily bars
# Idea: Price deviates >1 std from SMA20 → mean revert. Trend filter via SMA20.
# LONG: z-score < -1.0 AND price > SMA20 (trend intact, reversion bounces).
# SHORT: z-score > +1.0 AND price < SMA20 (trend broken, reversion falls).
# SL: 2 ATR, TP: SMA20 (mean).
def check_tjl_model_t(price, highs, lows, closes, volumes, today_high, today_low):
    if len(closes) < 25:
        return None
    c = np.array(closes)
    h = np.array(highs)
    l = np.array(lows)

    if len(c) < 20:
        return None
    c_series = pd.Series(c)
    sma20 = float(c_series.rolling(20).mean().iloc[-1])
    std20 = float(c_series.rolling(20).std().iloc[-1])
    if np.isnan(sma20) or np.isnan(std20) or std20 <= 0:
        return None
    z_score = (price - sma20) / std20

    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None

    deltas = pd.Series(c).diff()
    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)
    avg_gain = gains.ewm(com=13, adjust=False).mean().iloc[-1]
    avg_loss = losses.ewm(com=13, adjust=False).mean().iloc[-1]
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs)) if avg_loss > 0 else 100

    long_fire  = (z_score < -1.0) and (price > sma20) and (rsi > 30)
    short_fire = (z_score > +1.0) and (price < sma20) and (rsi < 70)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {
        'price': round(price, 2),
        'atr': round(atr, 3),
        'z_score': round(z_score, 2),
        'sma20': round(sma20, 2),
        'rsi': round(rsi, 1),
        'sl': round(price - 2.0 * atr if direction == 'LONG' else price + 2.0 * atr, 2),
        'tp': round(sma20, 2),
        'rr_ratio': round(abs(price - sma20) / (2.0 * atr), 1),
        'direction': direction,
        'long_fire': long_fire,
        'short_fire': short_fire,
    }


def check_tjl_model_u(price, highs, lows, closes, volumes, today_high, today_low, today_open):
    """
    Model U: Dual Thrust Opening Range Breakout.
    From: je-suis-tm/quant-trading — Dual Thrust.
    Range = max(N_high - N_low, |N_close - N_open|)  [N=2 lookback]
    Upper = today_open + 0.5 * range
    Lower = today_open - 0.5 * range
    LONG: price breaks above upper.  SHORT: price breaks below lower.
    SL: 1 ATR.  TP: 2 ATR.  R:R = 2:1.
    Warmup: 10 bars.
    """
    N = 2; K = 0.5
    if len(closes) < 10:
        return None
    h = np.array(highs)
    l = np.array(lows)
    c = np.array(closes)
    o = np.array(today_open) if hasattr(today_open, '__iter__') else np.array([today_open] * len(closes))

    if len(h) < N + 1:
        return None

    n_highs  = h[-(N):]
    n_lows   = l[-(N):]
    n_closes = c[-(N):]
    n_opens  = o[-(N):]

    range1 = float(np.max(n_highs) - np.min(n_lows))
    range2 = abs(float(n_closes[0]) - float(n_opens[-1]))   # |oldest_close - newest_open|
    dt_range = max(range1, range2)
    if dt_range <= 0:
        return None

    open_price = float(o[-1])
    upper = open_price + K * dt_range
    lower = open_price - K * dt_range

    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None

    if price > upper:
        direction = 'LONG'
        return {
            'price': round(price, 2),
            'atr': round(atr, 3),
            'sl': round(price - 1.0 * atr, 2),
            'tp': round(price + 2.0 * atr, 2),
            'rr_ratio': 2.0,
            'direction': direction,
            'range': round(dt_range, 3),
            'upper': round(upper, 2),
            'lower': round(lower, 2),
            'long_fire': True,
            'short_fire': False,
        }
    elif price < lower:
        direction = 'SHORT'
        return {
            'price': round(price, 2),
            'atr': round(atr, 3),
            'sl': round(price + 1.0 * atr, 2),
            'tp': round(price - 2.0 * atr, 2),
            'rr_ratio': 2.0,
            'direction': direction,
            'range': round(dt_range, 3),
            'upper': round(upper, 2),
            'lower': round(lower, 2),
            'long_fire': False,
            'short_fire': True,
        }
    return None


def check_tjl_model_v(price, highs, lows, closes, volumes, today_open):
    """
    Model V: Dual Thrust — Regime Adaptive (enhanced Model U).
    From: soham-srivastava/Dual_Thrust_Strategy (GC 2026).
    Same as Model U but k1/k2 shift by EMA-10 vs EMA-30 bias.
    Bullish (EMA10 > EMA30) → k1=0.4, k2=0.7 (easy long, hard short).
    Bearish  (EMA10 < EMA30) → k1=0.7, k2=0.4 (hard long, easy short).
    SL: 1.5 ATR.  TP: 3.0 ATR.  R:R = 2:1.
    Warmup: 35 bars.
    """
    if len(closes) < 35:
        return None
    h = np.array(highs[-35:])
    l = np.array(lows[-35:])
    c = np.array(closes[-35:])
    N = 2
    if len(h) < N + 1:
        return None
    n_highs  = h[-(N):]
    n_lows   = l[-(N):]
    n_closes = c[-(N):]
    range1 = float(np.max(n_highs) - np.min(n_lows))
    range2 = abs(float(n_closes[0]) - float(closes[-(N+1)]))
    dt_range = max(range1, range2)
    if dt_range <= 0:
        return None
    open_price = float(today_open) if hasattr(today_open, '__iter__') is False else float(closes[-1])
    s = pd.Series(c)
    ema10 = float(s.ewm(span=10, adjust=False).mean().iloc[-1])
    ema30 = float(s.ewm(span=30, adjust=False).mean().iloc[-1])
    if np.isnan(ema10) or np.isnan(ema30):
        return None
    bullish = ema10 > ema30
    k1 = 0.4 if bullish else 0.7
    k2 = 0.7 if bullish else 0.4
    upper = open_price + k1 * dt_range
    lower = open_price - k2 * dt_range
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    if price > upper:
        return {
            'price': round(price, 2), 'atr': round(atr, 3),
            'sl': round(price - 1.5 * atr, 2),
            'tp': round(price + 3.0 * atr, 2),
            'rr_ratio': 2.0, 'direction': 'LONG',
            'k1': k1, 'k2': k2,
            'ema10': round(ema10, 2), 'ema30': round(ema30, 2),
            'regime': 'BULL' if bullish else 'BEAR',
            'range': round(dt_range, 3),
        }
    elif price < lower:
        return {
            'price': round(price, 2), 'atr': round(atr, 3),
            'sl': round(price + 1.5 * atr, 2),
            'tp': round(price - 3.0 * atr, 2),
            'rr_ratio': 2.0, 'direction': 'SHORT',
            'k1': k1, 'k2': k2,
            'ema10': round(ema10, 2), 'ema30': round(ema30, 2),
            'regime': 'BULL' if bullish else 'BEAR',
            'range': round(dt_range, 3),
        }
    return None


def check_tjl_model_w(price, highs, lows, closes, volumes):
    """
    Model W: RSI Divergence + EMA Trend.
    Bullish Divergence: price makes lower low, RSI makes higher low → LONG.
    Bearish Divergence: price makes higher high, RSI makes lower high → SHORT.
    Confirm: EMA9 > EMA20 for LONG, EMA9 < EMA20 for SHORT.
    SL: 1.5 ATR.  TP: 3.0 ATR.  R:R = 2:1.
    Warmup: 60 bars.
    """
    if len(closes) < 60:
        return None
    h = np.array(highs); l = np.array(lows); c = np.array(closes)
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    s = pd.Series(c)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    if np.isnan(e9) or np.isnan(e20):
        return None
    rsi_now = calc_rsi(c)
    if rsi_now is None:
        return None
    lookback = 20
    if len(c) < lookback + 14:
        return None
    pw = c[-lookback:]
    ph = np.max(pw[:-1])
    pl = np.min(pw[:-1])
    rsi_vals = []
    for i in range(-lookback, 0):
        rs = calc_rsi(c[:i+14]) if i+14 > 0 else None
        if rs is not None:
            rsi_vals.append(rs)
    if len(rsi_vals) < 3:
        return None
    rsi_at_sh = float(np.max(rsi_vals[:-1])) if len(rsi_vals) > 1 else float(rsi_vals[-1])
    rsi_at_sl = float(np.min(rsi_vals[:-1])) if len(rsi_vals) > 1 else float(rsi_vals[-1])
    bullish_div = (price < pl * 1.02) and (rsi_now > rsi_at_sl)
    bearish_div = (price > ph * 0.98) and (rsi_now < rsi_at_sh)
    long_fire  = bullish_div and (e9 > e20)
    short_fire = bearish_div and (e9 < e20)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {
        'price': round(price, 2), 'atr': round(atr, 3),
        'sl': round(price - 1.5 * atr, 2) if direction == 'LONG' else round(price + 1.5 * atr, 2),
        'tp': round(price + 3.0 * atr, 2) if direction == 'LONG' else round(price - 3.0 * atr, 2),
        'rr_ratio': 2.0, 'direction': direction,
        'rsi': round(rsi_now, 1), 'e9': round(e9, 2), 'e20': round(e20, 2),
    }


def check_tjl_model_x(price, highs, lows, closes, volumes):
    """
    Model X: ICT SMC — Order Block + Fair Value Gap.
    Based on: joshyattridge/smart-money-concepts.
    Bullish OB: 3 bearish bars followed by bullish bar piercing above.
    FVG: middle candle bullish, gap above to next candle.
    LONG: price retesting OB high or filling bullish FVG.
    SHORT: mirror.  SL: 1.0 ATR.  TP: 2.0 ATR.  R:R = 2:1.
    Warmup: 30 bars.
    """
    if len(closes) < 30:
        return None
    c = np.array(closes); h = np.array(highs); l = np.array(lows)
    atr = calc_atr(h, l, c)
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    n = len(c)
    if n < 5:
        return None
    fvg_bull = (c[-3] > c[-4]) and (h[-3] < l[-1])
    fvg_bear = (c[-3] < c[-4]) and (l[-3] > h[-1])
    bull_ob = (c[-5] < c[-5+1] if n >= 6 else False) and (c[-4] < closes[-4+1] if n >= 5 else False) and (c[-3] < closes[-3+1] if n >= 4 else False) and (c[-2] > c[-3])
    bear_ob = (c[-5] > c[-5+1] if n >= 6 else False) and (c[-4] > closes[-4+1] if n >= 5 else False) and (c[-3] > closes[-3+1] if n >= 4 else False) and (c[-2] < c[-3])
    ob_bull_high = h[-3] if bull_ob else None
    ob_bear_low  = l[-3] if bear_ob else None
    rsi_now = calc_rsi(c)
    if rsi_now is None:
        return None
    long_fire = short_fire = False
    if ob_bull_high:
        long_fire = abs(price - ob_bull_high) / ob_bull_high < 0.01 and 40 < rsi_now < 70
    if fvg_bull:
        gap_mid = (l[-1] + h[-3]) / 2
        long_fire = long_fire or (abs(price - gap_mid) / gap_mid < 0.005 and rsi_now > 45)
    if ob_bear_low:
        short_fire = abs(price - ob_bear_low) / ob_bear_low < 0.01 and 30 < rsi_now < 60
    if fvg_bear:
        gap_mid = (h[-1] + l[-3]) / 2
        short_fire = short_fire or (abs(price - gap_mid) / gap_mid < 0.005 and rsi_now < 55)
    if not (long_fire or short_fire):
        return None
    direction = 'LONG' if long_fire else 'SHORT'
    return {
        'price': round(price, 2), 'atr': round(atr, 3),
        'sl': round(price - 1.0 * atr, 2) if direction == 'LONG' else round(price + 1.0 * atr, 2),
        'tp': round(price + 2.0 * atr, 2) if direction == 'LONG' else round(price - 2.0 * atr, 2),
        'rr_ratio': 2.0, 'direction': direction,
        'fvg': 'BULL' if fvg_bull else ('BEAR' if fvg_bear else None),
        'ob': 'BULL' if ob_bull_high else ('BEAR' if ob_bear_low else None),
        'rsi': round(rsi_now, 1),
    }


def check_tjs(price, highs, lows, closes, today_low):
    """Short entry: bearish stack + pullback to EMA9 + below PML."""
    if len(closes) < 60:
        return None
    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None
    pml = today_low if today_low else price
    stack_ok     = (e9 < e20 < e50)
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT)
    below_pml_ok = (price < pml - PMH_BUF)   # same buffer, inverted
    sl = price + ATR_SL * atr                 # SL above entry for short
    tp = price - ATR_TP * atr                 # TP below entry for short
    rr = (ATR_TP * atr) / (ATR_SL * atr)
    return {
        'price':        round(price, 2),
        'e9':           round(e9, 2),
        'e20':          round(e20, 2),
        'e50':          round(e50, 2),
        'atr':          round(atr, 3),
        'pml':          round(pml, 2),
        'sl':           round(sl, 2),
        'tp':           round(tp, 2),
        'rr_ratio':     round(rr, 2),
        'direction':     'SHORT',
        'stack_ok':     stack_ok,
        'near_ema_ok':  near_ema_ok,
        'below_pml_ok': below_pml_ok,
    }


def post_discord(signals, now_str):
    """Post TJL results to Discord webhook."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_HK_TJL", "").strip()
    if not webhook_url:
        log("[WARN] DISCORD_WEBHOOK_HK_TJL not set — skipping Discord post")
        return

    lines = [
        f"**HK TJL Live Scan** — {now_str} (Futu OpenD)",
        "",
    ]
    if signals:
        lines.append(f"🚨 **{len(signals)} TJL SIGNAL(S)**")
        lines.append("")
        lines.append(f"{'Ticker':<18} {'Price':>8} {'EMA9':>8} {'EMA20':>8} {'EMA50':>8} "
                     f"{'SL':>8} {'TP':>8} {'R:R':>5}")
        lines.append("-" * 85)
        for s in sorted(signals, key=lambda x: -x['rr_ratio']):
            e9  = s.get('e9',  s.get('ema9',  '--'))
            e20 = s.get('e20', s.get('ema20', '--'))
            e50 = s.get('e50', s.get('ema50', '--'))
            e9s  = f"{e9:>8.2f}" if isinstance(e9,  (int, float)) else f"{e9:>8}"
            e20s = f"{e20:>8.2f}" if isinstance(e20, (int, float)) else f"{e20:>8}"
            e50s = f"{e50:>8.2f}" if isinstance(e50, (int, float)) else f"{e50:>8}"
            lines.append(
                f"{s['name']:<18} {s['price']:>8.2f} {e9s} {e20s} {e50s} "
                f"{s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}"
            )
    else:
        lines.append("⏳ No TJL signals (all 3 conditions fail for all 35 tickers)")

    content = "\n".join(lines)
    if len(content) > 1900:
        content = content[:1900] + "\n(truncated)"

    # Forum channels require thread_name to create a new thread/post
    thread_name = f"HK TJL Live {datetime.now(HKT).strftime('%Y-%m-%d')}"
    payload = json.dumps({"content": content, "thread_name": thread_name})
    result = subprocess.run(
        ["curl", "-s", "-w", "\n%{http_code}",
         "-X", "POST", f"{webhook_url}?wait=true",
         "-H", "Content-Type: application/json",
         "-d", payload],
        capture_output=True, text=True, timeout=15
    )
    out = result.stdout.strip().split("\n")
    status = out[-1] if out else "unknown"
    log(f"Discord: HTTP {status}")



def notify_telegram(payload):
    """Send HK scan summary to Telegram via `hermes send`."""
    import subprocess
    lines = [
        f"📊 *TJL HK Scan (Futu)* — {payload['scanned_at']}",
        f"Source: Futu OpenD (real-time)",
        f"Signals: *{len(payload.get('signals', []))}*",
    ]
    if payload.get("signals"):
        lines += ["", "```", f"{'Ticker':<18} {'Price':>8} {'R:R':>5}", "-" * 40]
        for s in sorted(payload["signals"], key=lambda x: -x["rr_ratio"]):
            lines.append(f"{s['name']:<18} {s['price']:>8.2f} {s['rr_ratio']:>5.1f}")
        lines.append("```")
    else:
        lines.append("⏳ No signals.")
    text = "\n".join(lines)
    try:
        r = subprocess.run(["hermes", "send", "--to", "telegram"],
                           input=text, text=True, capture_output=True, timeout=30)
        log(f"📨 Telegram: {r.stdout.strip() or r.stderr.strip()}")
    except Exception as e:
        log(f"⚠ Telegram delivery failed: {e}")


def run_scan(notify=False):
    now_str = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S HKT")
    today_str = date.today().strftime("%Y-%m-%d")

    log("=" * 65)
    log("TJL Live Scanner — Futu OpenD Real-Time")
    log(f"Time : {now_str}")
    log("=" * 65)

    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    time.sleep(0.5)

    # ── Model Effectiveness Tracker ────────────────────────────────────────
    # Resolve any open positions that hit TP/SL since last scan
    tracker = ModelTracker()
    tracker.check_resolved(ctx)
    # ───────────────────────────────────────────────────────────────────────

    # Step 1: Live quotes
    log(f"Fetching live quotes ({len(ALL_CODES)} tickers)...")
    quotes = get_live_quotes(ctx, ALL_CODES)
    log(f"Got live data for {len(quotes)} tickers")

    # Step 2: Fetch & cache daily bars for every ticker (one API call each)
    bars_cache = {}
    for name, code in WATCHLIST:
        highs, lows, closes, volumes = get_daily_bars(ctx, code, count=80)
        if highs is not None:
            bars_cache[code] = (highs, lows, closes, volumes)

    # Step 3: Detect market regime
    regime, bear_pct, bull_pct, evaluated = detect_regime(ctx, WATCHLIST)
    log(f"Regime : {regime.upper()}  (bear={bear_pct:.0%}  bull={bull_pct:.0%}  n={evaluated})")

    # Step 4: Scan based on regime
    long_signals  = []
    short_signals = []
    debug_info    = []

    for name, code in WATCHLIST:
        if code not in quotes:
            debug_info.append(f"{code}: no live quote")
            continue
        if code not in bars_cache:
            debug_info.append(f"{code}: no daily bars")
            continue

        q = quotes[code]
        price     = q['price']
        today_high = q['high_today']
        today_low  = q['low_today']
        today_open = q.get('open_today') or q['prev_close']
        highs, lows, closes = bars_cache[code][:3]
        volumes = bars_cache[code][3]

        # ── Model A (Pullback) ───────────────────────────────
        if regime in ('bullish', 'neutral'):
            result = check_tjl(price, highs, lows, closes, today_high)
            if result:
                result['name'] = name
                ma = result['model_a']
                if ma['stack_ok'] and ma['near_ema_ok'] and ma['above_pmh_ok']:
                    result['signal_model'] = 'A'
                    long_signals.append(result)
                else:
                    reasons = []
                    if not ma['stack_ok']:      reasons.append("!stack")
                    if not ma['near_ema_ok']:   reasons.append("!near9")
                    if not ma['above_pmh_ok']:  reasons.append("!abovePMH")
                    debug_info.append(f"{code}: {' '.join(reasons)}")

        # ── Model B (HT Momentum) — separate call ──────────
        if regime in ('bullish', 'neutral'):
            result_b = check_tjl_model_b(price, highs, lows, closes, today_high)
            if result_b:
                result_b['name'] = name
                mb = result_b
                if mb['above_sma200_ok'] and mb['above_pmh_ok'] and mb['above_hod_ok']:
                    result_b['signal_model'] = 'B'
                    already = any(s['name'] == name for s in long_signals)
                    if not already:
                        long_signals.append(result_b)
                else:
                    reasons = []
                    if not mb['above_sma200_ok']: reasons.append("!sma200")
                    if not mb['above_pmh_ok']:     reasons.append("!abovePMH")
                    if not mb['above_hod_ok']:      reasons.append("!aboveHOD")
                    debug_info.append(f"{code}B: {' '.join(reasons)}")

        # ── Model C (Volume-Confirmed Pullback) ─────────────
        if regime in ('bullish', 'neutral'):
            result_c = check_tjl_model_c(price, highs, lows, closes, volumes, today_high)
            if result_c:
                result_c['name'] = name
                mc = result_c
                if mc['near_ema_ok'] and mc['above_pmh_ok'] and mc['vol_spike_ok']:
                    result_c['signal_model'] = 'C'
                    already = any(s['name'] == name for s in long_signals)
                    if not already:
                        long_signals.append(result_c)
                else:
                    reasons = []
                    if not mc['near_ema_ok']:   reasons.append("!near2%")
                    if not mc['above_pmh_ok']: reasons.append("!abovePMH")
                    if not mc['vol_spike_ok']:  reasons.append("!volSpike")
                    debug_info.append(f"{code}C: {' '.join(reasons)}")

        # ── Model D (VWAP Mean Reversion) ─────────────────────
        result_d = check_tjl_model_d(price, highs, lows, closes, volumes, today_high, today_low)
        if result_d:
            result_d['name'] = name
            md = result_d
            d_long_fire  = md.get('long_fire')
            d_short_fire = md.get('short_fire')
            # Regime guard
            regime_ok_long  = regime in ('bullish', 'neutral') and d_long_fire
            regime_ok_short = regime in ('bearish', 'neutral') and d_short_fire
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'D' for s in long_signals):
                result_d['signal_model'] = 'D'
                long_signals.append(result_d)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'D' for s in short_signals):
                result_d['signal_model'] = 'D'
                short_signals.append(result_d)
            else:
                debug_info.append(f"{code}D: regime={regime} long={d_long_fire} short={d_short_fire}")

        # ── Model E (Bollinger Band Squeeze Fade) ─────────────
        if regime in ('bullish', 'neutral') or regime == 'bearish':
            result_e = check_tjl_model_e(price, highs, lows, closes, volumes, today_high)
            if result_e:
                result_e['name'] = name
                me = result_e
                e_long_fire  = me.get('is_squeezed') and me.get('is_expanding') and me.get('at_lower') and me.get('vol_ok')
                e_short_fire = me.get('is_squeezed') and me.get('is_expanding') and me.get('at_upper') and me.get('vol_ok')
                regime_ok_long  = regime in ('bullish', 'neutral') and e_long_fire
                regime_ok_short = regime == 'bearish' and e_short_fire
                if regime_ok_long and not any(s['name'] == name for s in long_signals):
                    result_e['signal_model'] = 'E'
                    long_signals.append(result_e)
                elif regime_ok_short and not any(s['name'] == name for s in short_signals):
                    result_e['signal_model'] = 'E'
                    short_signals.append(result_e)
                else:
                    reasons = []
                    if not me.get('is_squeezed'):  reasons.append("!squeeze")
                    if not me.get('is_expanding'): reasons.append("!expand")
                    if not (me.get('at_lower') or me.get('at_upper')): reasons.append("!atBand")
                    if not me.get('vol_ok'):       reasons.append("!volOk")
                    debug_info.append(f"{code}E: {' '.join(reasons)}")

        # ── Model F (RSI Trend Crossover — reinstated) ───────────
        result_f = check_tjl_model_f(price, highs, lows, closes, volumes, today_high, today_low)
        if result_f:
            result_f['name'] = name
            mf = result_f
            f_long_fire  = mf.get('long_fire')
            f_short_fire = mf.get('short_fire')
            regime_ok_long  = regime in ('bullish', 'neutral') and f_long_fire
            regime_ok_short = regime in ('bearish', 'neutral') and f_short_fire
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'F' for s in long_signals):
                result_f['signal_model'] = 'F'
                long_signals.append(result_f)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'F' for s in short_signals):
                result_f['signal_model'] = 'F'
                short_signals.append(result_f)
            else:
                debug_info.append(f"{code}F: regime={regime} long={f_long_fire} short={f_short_fire}")

        # ── Model G (ORB — Opening Range Breakout) ───────────────
        result_g = check_tjl_model_g(price, highs, lows, closes, volumes, today_high, today_low, today_open)
        if result_g:
            result_g['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'G' for s in long_signals):
                result_g['signal_model'] = 'G'
                long_signals.append(result_g)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'G' for s in short_signals):
                result_g['signal_model'] = 'G'
                short_signals.append(result_g)

        # ── Model H (Gold EMA/BB/VWAP — trend intraday) ─────────
        result_h = check_tjl_model_h(price, highs, lows, closes, volumes, today_high, today_low)
        if result_h:
            result_h['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'H' for s in long_signals):
                result_h['signal_model'] = 'H'
                long_signals.append(result_h)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'H' for s in short_signals):
                result_h['signal_model'] = 'H'
                short_signals.append(result_h)

        # ── Model I (SHM-lite — 63WMA swing, daily bars) ────────
        result_i = check_tjl_model_i(price, highs, lows, closes, volumes, today_high)
        if result_i:
            result_i['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'I' for s in long_signals):
                result_i['signal_model'] = 'I'
                long_signals.append(result_i)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'I' for s in short_signals):
                result_i['signal_model'] = 'I'
                short_signals.append(result_i)

        # ── Model J (Follow the Money — 150/200 DMA) ────────────
        result_j = check_tjl_model_j(price, highs, lows, closes, volumes, today_high)
        if result_j:
            result_j['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'J' for s in long_signals):
                result_j['signal_model'] = 'J'
                long_signals.append(result_j)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'J' for s in short_signals):
                result_j['signal_model'] = 'J'
                short_signals.append(result_j)

        # ── Model K (EMA/VWAP/Bollinger Session) ────────────────
        result_k = check_tjl_model_k(price, highs, lows, closes, volumes, today_high, today_low)
        if result_k:
            result_k['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'K' for s in long_signals):
                result_k['signal_model'] = 'K'
                long_signals.append(result_k)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'K' for s in short_signals):
                result_k['signal_model'] = 'K'
                short_signals.append(result_k)

        # ── Model M (EMA Ribbon Compression) ────────────────────
        result_m = check_tjl_model_m(price, highs, lows, closes, volumes, today_high, today_low)
        if result_m:
            result_m['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'M' for s in long_signals):
                result_m['signal_model'] = 'M'
                long_signals.append(result_m)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'M' for s in short_signals):
                result_m['signal_model'] = 'M'
                short_signals.append(result_m)

        # ── Model R: Keltner Channel + RSI Breakout ──────────────────
        result_r = check_tjl_model_r(price, highs, lows, closes, volumes, today_high, today_low)
        if result_r:
            result_r['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'R' for s in long_signals):
                result_r['signal_model'] = 'R'
                long_signals.append(result_r)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'R' for s in short_signals):
                result_r['signal_model'] = 'R'
                short_signals.append(result_r)

        # ── Model S: Ichimoku Cloud Breakout ──────────────────────────
        result_s = check_tjl_model_s(price, highs, lows, closes, volumes, today_high, today_low)
        if result_s:
            result_s['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'S' for s in long_signals):
                result_s['signal_model'] = 'S'
                long_signals.append(result_s)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'S' for s in short_signals):
                result_s['signal_model'] = 'S'
                short_signals.append(result_s)

        # ── Model T: Mean Reversion z-score ───────────────────────────
        result_t = check_tjl_model_t(price, highs, lows, closes, volumes, today_high, today_low)
        if result_t:
            result_t['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'T' for s in long_signals):
                result_t['signal_model'] = 'T'
                long_signals.append(result_t)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'T' for s in short_signals):
                result_t['signal_model'] = 'T'
                short_signals.append(result_t)

        # ── Model U: Dual Thrust Opening Range Breakout ───────────────
        result_u = check_tjl_model_u(price, highs, lows, closes, volumes, today_high, today_low, today_open)
        if result_u:
            result_u['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'U' for s in long_signals):
                result_u['signal_model'] = 'U'
                long_signals.append(result_u)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'U' for s in short_signals):
                result_u['signal_model'] = 'U'
                short_signals.append(result_u)

        # ── Model V: Dual Thrust — Regime Adaptive ─────────────────────
        result_v = check_tjl_model_v(price, highs, lows, closes, volumes, today_open)
        if result_v:
            result_v['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'V' for s in long_signals):
                result_v['signal_model'] = 'V'
                long_signals.append(result_v)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'V' for s in short_signals):
                result_v['signal_model'] = 'V'
                short_signals.append(result_v)

        # ── Model W: RSI Divergence + EMA Trend ────────────────────────
        result_w = check_tjl_model_w(price, highs, lows, closes, volumes)
        if result_w:
            result_w['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'W' for s in long_signals):
                result_w['signal_model'] = 'W'
                long_signals.append(result_w)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'W' for s in short_signals):
                result_w['signal_model'] = 'W'
                short_signals.append(result_w)

        # ── Model X: ICT SMC — Order Block + FVG ───────────────────────
        result_x = check_tjl_model_x(price, highs, lows, closes, volumes)
        if result_x:
            result_x['name'] = name
            regime_ok_long  = regime in ('bullish', 'neutral')
            regime_ok_short = regime in ('bearish', 'neutral')
            if regime_ok_long and not any(s['name'] == name and s.get('signal_model') == 'X' for s in long_signals):
                result_x['signal_model'] = 'X'
                long_signals.append(result_x)
            elif regime_ok_short and not any(s['name'] == name and s.get('signal_model') == 'X' for s in short_signals):
                result_x['signal_model'] = 'X'
                short_signals.append(result_x)

        # ── Short side (TJS — unchanged) ────────────────────
        if regime in ('bearish', 'neutral'):
            result = check_tjs(price, highs, lows, closes, today_low)
            if result:
                result['name'] = name
                if result['stack_ok'] and result['near_ema_ok'] and result['below_pml_ok']:
                    short_signals.append(result)
                else:
                    reasons = []
                    if not result['stack_ok']:      reasons.append("!stack")
                    if not result['near_ema_ok']:    reasons.append("!near9")
                    if not result['below_pml_ok']:  reasons.append("!belowPML")
                    debug_info.append(f"{code}: {' '.join(reasons)}")

    ctx.close()

    # Step 5: Print results
    def log_table(signals, direction, key_col, sl_col, tp_col):
        if not signals:
            return
        log("")
        log(f"  🚨 {direction} SIGNALS")
        log("=" * 105)
        log(f"{'Ticker':<18} {'M':>2} {'Price':>8} {'EMA9':>8} {'EMA20':>8} {'EMA50':>8} "
            f"{'SMA200':>8} {'ATR':>7} {'SL':>8} {'TP':>8} {'R:R':>5}")
        log("-" * 105)
        for s in sorted(signals, key=lambda x: -x['rr_ratio']):
            model = s.get('signal_model', '?')
            # Model A has e9/e20/e50; Model B does not
            e9_disp  = s.get('e9',    '-')
            e20_disp = s.get('e20',   '-')
            e50_disp = s.get('e50',   '-')
            sma_disp = s.get('sma200', '-')
            def fmt(v): return f"{v:>8.2f}" if isinstance(v, float) else f"{'--':>8}"
            log(f"{s['name']:<18} {model:>2} {fmt(s['price'])} {fmt(e9_disp)} {fmt(e20_disp)} "
                f"{fmt(e50_disp)} {fmt(sma_disp)} {s['atr']:>7.3f} "
                f"{s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}")

    log_table(long_signals,  "LONG",  "PMH",  "pmh",  None)
    log_table(short_signals, "SHORT", "PML",  "pml",  None)

    all_signals = long_signals + short_signals

    # ── Record ALL signals (including DROP) in tracker ─────────────────────
    # This builds the rolling history; filtering to active models happens below
    tracker.record_signals(all_signals)
    active_models = tracker.get_active_models()

    # Filter: only dispatch signals from models that cleared WR/PF thresholds
    effective_signals = [s for s in all_signals if s.get('signal_model') in active_models]
    effective_long  = [s for s in long_signals  if s.get('signal_model') in active_models]
    effective_short = [s for s in short_signals if s.get('signal_model') in active_models]

    # Log which models are DROP this scan
    drop_models = tracker.get_drop_models()
    if drop_models:
        log(f"[Tracker] DROP this scan: {sorted(drop_models)} — {len(effective_signals)} effective signal(s)")

    # ── Print results ──────────────────────────────────────────────────────
    log_table(effective_long,  "LONG",  "PMH",  "pmh",  None)
    log_table(effective_short, "SHORT", "PML",  "pml",  None)

    if not effective_signals:
        log("")
        log("=" * 65)
        log("  ⏳ NO SIGNALS — ALL CONDITIONS FAIL")
        log("=" * 65)

    # Save effective signals to JSON (includes DROP flag for post-scan review)
    if effective_signals:
        out_file = os.path.expanduser(f"~/tjl_live_signals_{today_str}.json")
        with open(out_file, "w") as f:
            # Annotate each signal with whether it was filtered
            all_filtered_models = set(s.get('signal_model') for s in all_signals)
            annotated = []
            for s in effective_signals:
                s2 = dict(s)
                s2['_status'] = 'EFFECTIVE'
                annotated.append(s2)
            # Also record what was dropped this scan
            dropped_this_scan = [dict(s, _status='DROPPED', _drop_reason='WR<30% or PF<=1.0')
                                 for s in all_signals
                                 if s.get('signal_model') not in active_models]
            json.dump({
                "scanned_at": now_str,
                "source": "Futu OpenD",
                "regime": regime,
                "bear_pct": round(bear_pct, 3),
                "bull_pct": round(bull_pct, 3),
                "drop_models": sorted(drop_models),
                "signals": annotated + dropped_this_scan,
            }, f, indent=2, default=str)
        log(f"📁 Saved to {out_file}")

    log("")
    log("── Debug (first 15) ──")
    for d in debug_info[:15]:
        log(f"  {d}")

    # ── Post results ────────────────────────────────────────────────────────
    post_discord(effective_signals, now_str)

    # Step 7: Optional Telegram
    if notify:
        notify_telegram({"scanned_at": now_str, "signals": effective_signals,
                         "regime": regime, "drop_models": sorted(drop_models)})

    # Log tracker stats + close
    tracker.log_status()
    tracker.close()

    return effective_signals


def main():
    parser = argparse.ArgumentParser(description="TJL Live Scanner — Futu OpenD")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL, help="Seconds between scans")
    parser.add_argument("--notify", action="store_true", help="Send results to Telegram")
    args = parser.parse_args()

    # Optional env override: HK_TICKERS=HK.00700,HK.09988,...
    # Restricts the scan to those codes (auto-derived name from code tail).
    override = os.environ.get("HK_TICKERS", "").strip()
    if override:
        global WATCHLIST, ALL_CODES
        codes = [c.strip() for c in override.split(",") if c.strip()]
        WATCHLIST = [(c.split(".", 1)[-1], c) for c in codes]
        ALL_CODES = codes
        log(f"⚙️  HK_TICKERS override active — {len(codes)} tickers: {codes}")

    if args.continuous:
        log(f"CONTINUOUS mode — interval {args.interval}s | Ctrl+C to stop")
        try:
            while True:
                run_scan(notify=args.notify)
                log(f"Sleeping {args.interval}s...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log("Stopped.")
    else:
        run_scan(notify=args.notify)


if __name__ == "__main__":
    main()
