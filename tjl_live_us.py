#!/usr/bin/env python3
"""
TJL Live Scanner — US Market via Yahoo Finance
==============================================
Scans US stocks every N seconds using yfinance real-time data,
calculates EMA stack on daily bars, and checks live TJL entry conditions.

TJL LONG Entry Conditions:
  1. EMA9  > EMA20 > EMA50   (bullish stack)
  2. Price within 0.2% of EMA9 (pullback zone)
  3. Price > PMH + buffer    (prior day high or premarket high)

TJS SHORT Entry Conditions:
  1. EMA9  < EMA20 < EMA50   (bearish stack)
  2. Price within 0.2% of EMA9 (bearish rebound zone)
  3. Price < PML - buffer    (below prior day low or premarket low)

Exit LONG:  SL = price - 1.5*ATR | TP = price + 3.0*ATR
Exit SHORT: SL = price + 1.5*ATR | TP = price - 3.0*ATR

Usage:
  python3 tjl_live_us.py                   # scan once
  python3 tjl_live_us.py --continuous       # loop every 30s
  python3 tjl_live_us.py --continuous --interval 60

Environment:
  DISCORD_WEBHOOK_HK_TJL — Discord webhook URL. If set, posts results.
  US_TICKERS             — Optional comma-separated tickers (overrides default watchlist)
"""
import yfinance as yf
import pandas as pd
import numpy as np
import time
import os
import json
import subprocess
import argparse
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HKT = ZoneInfo("Asia/Hong_Kong")

PMH_BUF      = 0.70    # $ buffer for PMH/PML entry
ATR_SL       = 1.5
ATR_TP       = 3.0
ATR_PERIOD   = 14
NEAR_EMA_PCT = 0.002   # 0.2% — pullback zone
SCAN_INTERVAL = 30     # seconds between scans in continuous mode

# ── Default US Watchlist ───────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    ("NVDA",  "NVIDIA"),
    ("TSLA",  "Tesla"),
    ("AAPL",  "Apple"),
    ("MSFT",  "Microsoft"),
    ("META",  "Meta"),
    ("AMZN",  "Amazon"),
    ("GOOGL", "Google"),
    ("AMD",   "AMD"),
    ("INTC",  "Intel"),
    ("NFLX",  "Netflix"),
    ("SPXL",  "S&P 500 3x"),
    ("TQQQ",  "Nasdaq 100 3x"),
    ("SOXL",  "Semiconductor 3x"),
    ("QLD",   "QQQ 2x"),
    ("UPRO",  "S&P 500 3x"),
    ("TSM",   "TSMC"),
    ("SMCI",  "Super Micro"),
    ("PLTR",  "Palantir"),
    ("COIN",  "Coinbase"),
    ("MSTR",  "MicroStrategy"),
    ("RIVN",  "Rivian"),
    ("LCID",  "Lucid"),
    ("NIO",   "NIO"),
    ("XPEV",  "XPeng"),
    ("LI",    "Li Auto"),
    ("BIDU",  "Baidu"),
    ("BABA",  "Alibaba"),
    ("JD",    "JD.com"),
    ("PDD",   "Pinduoduo"),
    ("NTES",  "NetEase"),
    ("TME",   "Tencent Music"),
    ("VNET",  "VNet"),
    ("BEKE",  "KE Holdings"),
    ("TAL",   "TAL Edu"),
    ("EDU",   "New Oriental"),
    ("BILI",  "Bilibili"),
    ("DDD",   "3D Systems"),
    ("SMAR",  "SmartSheet"),
    ("DOCU",  "DocuSign"),
    ("SNOW",  "Snowflake"),
    ("CRWD",  "CrowdStrike"),
    ("ZS",    "Zscaler"),
    ("OKTA",  "Okta"),
    ("PANW",  "Palo Alto"),
    ("NET",   "Cloudflare"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)


def get_us_market_open():
    """Check if US market is currently open (9:30–16:00 ET weekdays)."""
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    hour, minute = now.hour, now.minute
    total_mins = hour * 60 + minute
    # 9:30 AM = 570 mins, 4:00 PM = 960 mins
    return 570 <= total_mins <= 960


def get_regime():
    """Check SPY vs QQQ regime: BULLISH if both above previous close."""
    try:
        spy = yf.Ticker("SPY").history(period="2d")
        qqq = yf.Ticker("QQQ").history(period="2d")
        if len(spy) < 2 or len(qqq) < 2:
            return "UNKNOWN"
        spy_up = spy['Close'].iloc[-1] > spy['Close'].iloc[-2]
        qqq_up = qqq['Close'].iloc[-1] > qqq['Close'].iloc[-2]
        return "BULLISH" if (spy_up and qqq_up) else "BEARISH"
    except:
        return "UNKNOWN"


def calc_emas(closes):
    s = pd.Series(closes)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    e50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
    return e9, e20, e50



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


def calc_vwap_bars(highs, lows, closes, volumes):
    """VWAP over a sliding window (typical = full day or N bars)."""
    typical = (np.array(highs) + np.array(lows) + np.array(closes)) / 3.0
    cumvol = np.cumsum(np.array(volumes))
    cumtp = np.cumsum(typical * np.array(volumes))
    return cumtp / cumvol





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


def get_daily_bars(ticker, count=80):
    """Get daily OHLC bars from yfinance. Drops rows with NaN close."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=f"{count}d", interval="1d")
        if hist.empty or len(hist) < 30:
            return None, None, None
        hist = hist.sort_index()
        # Drop rows where Close is NaN (data gaps corrupt EMA and ATR)
        hist = hist[hist['Close'].notna()]
        if hist.empty or len(hist) < 30:
            return None, None, None
        return hist['High'].values, hist['Low'].values, hist['Close'].values, hist['Volume'].values
    except:
        return None, None, None


def get_live_price(ticker):
    """Get current price from yfinance (15min delay for non-premium).

    Priority: fast_info.lastPrice → 1m bar override (post-market/weekend stale cache)
    → daily history fallback.
    """
    try:
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        price      = info.get('lastPrice')              or info.get('regularMarketPrice')
        prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
        day_high   = info.get('dayHigh')   or info.get('regularMarketDayHigh')
        day_low    = info.get('dayLow')    or info.get('regularMarketDayLow')

        # ── 1m bar override ───────────────────────────────────────────────────
        # If lastPrice ≈ prev_close the market is closed (no new trades).
        # Use the last 1m bar to get the true last-trade price.
        try:
            m1 = tk.history(period="1d", interval="1m")
            if m1 is not None and not m1.empty and len(m1) >= 2:
                m1_close = float(m1.iloc[-1]['Close'])
                m1_high  = float(m1['High'].max())
                m1_low   = float(m1['Low'].min())
                p  = float(price)       if price      is not None else None
                pc = float(prev_close) if prev_close is not None else None
                if p is not None and pc is not None and abs(p - pc) < 0.01:
                    price = m1_close
                elif price is None:
                    price = m1_close
                day_high = max(float(day_high or 0), m1_high)
                day_low  = min(float(day_low  or 999999), m1_low)
        except Exception:
            pass  # 1m bars are best-effort

        # ── Final history fallback ───────────────────────────────────────────
        if price is None:
            hist = tk.history(period="2d")
            if len(hist) >= 2:
                price      = float(hist['Close'].iloc[-1])
                prev_close = float(hist['Close'].iloc[-2])
                day_high   = float(hist['High'].iloc[-1])
                day_low    = float(hist['Low'].iloc[-1])
            else:
                return None

        return {
            'price':      float(price),
            'prev_close': float(prev_close) if prev_close else None,
            'day_high':   float(day_high)   if day_high   else None,
            'day_low':    float(day_low)    if day_low    else None,
        }
    except Exception as e:
        return None


def get_premarket_high(ticker):
    """Get premarket high (4AM–9:30AM ET today) via yfinance 1-min bars."""
    try:
        today_str = date.today().strftime("%Y-%m-%d")
        bars = yf.Ticker(ticker).history(start=today_str, interval="1m", auto_adjust=True, keepna=True)
        if bars.empty:
            return None
        et_idx = bars.index.tz_convert(ET) if bars.index.tz else bars.index.tz_localize(ET)
        mask = (et_idx.hour >= 4) & ((et_idx.hour < 9) | ((et_idx.hour == 9) & (et_idx.minute <= 30)))
        if mask.sum() == 0:
            return None
        return float(bars[mask]['High'].max())
    except:
        return None


def get_premarket_low(ticker):
    """Get premarket low (4AM–9:30AM ET today) via yfinance 1-min bars."""
    try:
        today_str = date.today().strftime("%Y-%m-%d")
        bars = yf.Ticker(ticker).history(start=today_str, interval="1m", auto_adjust=True, keepna=True)
        if bars.empty:
            return None
        et_idx = bars.index.tz_convert(ET) if bars.index.tz else bars.index.tz_localize(ET)
        mask = (et_idx.hour >= 4) & ((et_idx.hour < 9) | ((et_idx.hour == 9) & (et_idx.minute <= 30)))
        if mask.sum() == 0:
            return None
        return float(bars[mask]['Low'].min())
    except:
        return None




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


def check_tjl(ticker, name, price, day_high, prev_day_high, highs, lows, closes,
                 premarket_high=0):
    """
    Check all 3 TJL LONG conditions. Returns signal dict or None.

    Conditions:
      1. EMA9 > EMA20 > EMA50  (bullish stack)
      2. |price - EMA9| / EMA9 <= 0.2%  (near EMA9 pullback)
      3. price > PMH + $0.70  (above prior-day or premarket high)
    """
    if len(closes) < 60:
        return None, f"{ticker}: insufficient bars ({len(closes)})"

    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None, f"{ticker}: NaN in EMA"

    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None, f"{ticker}: ATR error"

    # PMH = max of yesterday's actual high and today's premarket high.
    # The regular-session intraday high is NOT included — price can never
    # exceed today's intraday high, so using it would make above_pmh_ok
    # permanently False. We intentionally use only the OVERNIGHT high
    # (prior day close→high and premarket) as the breakout reference.
    pmh = prev_day_high or 0
    if premarket_high and premarket_high > pmh:
        pmh = premarket_high

    stack_ok     = (e9 > e20 > e50)
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT)
    above_pmh_ok = (pmh > 0) and (price > pmh + PMH_BUF)

    sl = price - ATR_SL * atr
    tp = price + ATR_TP * atr
    rr = (ATR_TP * atr) / (ATR_SL * atr)

    result = {
        'ticker':     ticker,
        'name':       name,
        'price':      round(price, 2),
        'direction':  'LONG',
        'prev_close': round(float(closes[-1]), 2),
        'e9':         round(e9, 2),
        'e20':        round(e20, 2),
        'e50':        round(e50, 2),
        'atr':        round(atr, 3),
        'pmh':        round(pmh, 2),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   round(rr, 2),
        'stack_ok':     stack_ok,
        'near_ema_ok':  near_ema_ok,
        'above_pmh_ok': above_pmh_ok,
    }

    if not all([stack_ok, near_ema_ok, above_pmh_ok]):
        reasons = []
        if not stack_ok:     reasons.append("!stack")
        if not near_ema_ok:  reasons.append("!nearEMA")
        if not above_pmh_ok: reasons.append("!abovePMH")
        return None, f"{ticker}: {' '.join(reasons)}"

    return result, None


def check_tjs(ticker, name, price, day_low, prev_day_low, highs, lows, closes,
                 premarket_low=0):
    """
    Check SHORT entry conditions (TJS = Trend-Join-Short).
    Mirror of check_tjl() with inverted conditions:

      1. EMA9 < EMA20 < EMA50  (bearish stack)
      2. |price - EMA9| / EMA9 <= 0.2%  (near EMA9 rebound)
      3. price < PML - $0.70  (below prior-day or premarket low)

    Exit:  SL = price + 1.5×ATR  (stop ABOVE entry for short)
           TP = price - 3.0×ATR  (profit BELOW entry)
    """
    if len(closes) < 60:
        return None, f"{ticker}: insufficient bars ({len(closes)})"

    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None, f"{ticker}: NaN in EMA"

    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None, f"{ticker}: ATR error"

    # PML: min of prior day low and today's premarket low
    pml = prev_day_low or 0
    if premarket_low and premarket_low < pml:
        pml = premarket_low

    stack_ok     = (e9 < e20 < e50)
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT)
    below_pml_ok = (pml > 0) and (price < pml - PMH_BUF)

    # SHORT: SL above entry, TP below entry
    sl = price + ATR_SL * atr
    tp = price - ATR_TP * atr
    rr = (ATR_TP * atr) / (ATR_SL * atr)

    result = {
        'ticker':     ticker,
        'name':       name,
        'price':      round(price, 2),
        'direction':  'SHORT',
        'prev_close': round(float(closes[-1]), 2),
        'e9':         round(e9, 2),
        'e20':        round(e20, 2),
        'e50':        round(e50, 2),
        'atr':        round(atr, 3),
        'pml':        round(pml, 2),
        'sl':         round(sl, 2),
        'tp':         round(tp, 2),
        'rr_ratio':   round(rr, 2),
        'stack_ok':      stack_ok,
        'near_ema_ok':   near_ema_ok,
        'below_pml_ok':  below_pml_ok,
    }

    if not all([stack_ok, near_ema_ok, below_pml_ok]):
        reasons = []
        if not stack_ok:      reasons.append("!stack")
        if not near_ema_ok:   reasons.append("!nearEMA")
        if not below_pml_ok:  reasons.append("!belowPML")
        return None, f"{ticker}: {' '.join(reasons)}"

    return result, None


def _build_discord_payload(signals, now_str, regime, longs, shorts):
    """Build rich Discord embed payload for TJL results."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_HK_TJL", "").strip()
    if not webhook_url:
        return None, None

    regime_color = 0x228B22 if regime == "BULLISH" else (0xDC143C if regime == "BEARISH" else 0x888888)
    regime_emoji = "🟢" if regime == "BULLISH" else ("🔴" if regime == "BEARISH" else "⚪")

    # Build embed fields
    fields = []
    if longs:
        field_value = (
            "```\n"
            + "\n".join(
                f"{s['ticker']:<8}  price={s['price']:>7.2f}  EMA9={s['e9']:>7.2f}  "
                f"SL={s['sl']:>7.2f}  TP={s['tp']:>7.2f}  R:R={s['rr_ratio']:.1f}"
                for s in sorted(longs, key=lambda x: -x['rr_ratio'])
            )
            + "```"
        )
        fields.append({"name": f"🟢 LONG ({len(longs)})", "value": field_value, "inline": False})

    if shorts:
        field_value = (
            "```\n"
            + "\n".join(
                f"{s['ticker']:<8}  price={s['price']:>7.2f}  EMA9={s['e9']:>7.2f}  "
                f"SL={s['sl']:>7.2f}  TP={s['tp']:>7.2f}  R:R={s['rr_ratio']:.1f}"
                for s in sorted(shorts, key=lambda x: -x['rr_ratio'])
            )
            + "```"
        )
        fields.append({"name": f"🔴 SHORT ({len(shorts)})", "value": field_value, "inline": False})

    description = (
        f"**Regime:** {regime_emoji} **{regime}**\n"
        f"**Signals:** {len(signals)} ({len(longs)} LONG, {len(shorts)} SHORT)\n"
        + ("*No signals — all conditions fail.*" if not signals else "")
    )

    embed = {
        "title": f"US TJL Live Scan — {now_str}",
        "color": regime_color,
        "description": description,
        "fields": fields,
        "footer": {
            "text": (
                "LONG: SL=price−1.5×ATR  TP=price+3×ATR | SHORT: SL=price+1.5×ATR  TP=price−3×ATR\n"
                "PMH=prior/premarket high | PML=prior/premarket low | 15min delay (yfinance free)"
            )
        },
    }

    content = f"**US TJL Live Scan** — {regime_emoji} **{regime}**"
    payload = {
        "content": content,
        "embeds": [embed],
        "thread_name": f"US TJL Live {datetime.now(ET).strftime('%Y-%m-%d')}",
    }
    return webhook_url, payload


def post_discord(signals, now_str, regime):
    """Post TJL results to Discord webhook (handles both LONG and SHORT)."""
    longs  = [s for s in signals if s.get('direction') == 'LONG']
    shorts = [s for s in signals if s.get('direction') == 'SHORT']

    webhook_url, payload = _build_discord_payload(signals, now_str, regime, longs, shorts)
    if not webhook_url:
        log("[WARN] DISCORD_WEBHOOK_HK_TJL not set — skipping Discord")
        return

    body = json.dumps(payload, ensure_ascii=False)
    result = subprocess.run(
        ["curl", "-s", "-w", "\n%{http_code}",
         "-X", "POST", f"{webhook_url}?wait=true",
         "-H", "Content-Type: application/json",
         "-d", body],
        capture_output=True, text=True, timeout=15
    )
    out = result.stdout.strip().split("\n")
    status = out[-1] if out else "unknown"
    log(f"Discord: HTTP {status}")


def notify_telegram(payload):
    """Send scan summary to Telegram via `hermes send`."""
    import subprocess
    longs  = [s for s in payload.get('signals', []) if s.get('direction') == 'LONG']
    shorts = [s for s in payload.get('signals', []) if s.get('direction') == 'SHORT']
    regime_emoji = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(payload.get('regime', ''), "⚪")
    lines = [
        f"📊 *TJL Scan (yfinance)* — {payload['scanned_at']}",
        f"Regime: {regime_emoji} *{payload.get('regime', 'UNKNOWN')}*",
        f"Signals: *{len(payload.get('signals', []))}* ({len(longs)} LONG, {len(shorts)} SHORT)",
    ]
    if longs:
        lines += ["", "🟢 *LONG*", "```",
                  f"{'Ticker':<8} {'Price':>8} {'EMA9':>8} {'R:R':>5}",
                  "-" * 35]
        for s in sorted(longs, key=lambda x: -x['rr_ratio']):
            lines.append(f"{s['ticker']:<8} {s['price']:>8.2f} {s['e9']:>8.2f} {s['rr_ratio']:>5.1f}")
        lines.append("```")
    if shorts:
        lines += ["", "🔴 *SHORT*", "```",
                  f"{'Ticker':<8} {'Price':>8} {'EMA9':>8} {'R:R':>5}",
                  "-" * 35]
        for s in sorted(shorts, key=lambda x: -x['rr_ratio']):
            lines.append(f"{s['ticker']:<8} {s['price']:>8.2f} {s['e9']:>8.2f} {s['rr_ratio']:>5.1f}")
        lines.append("```")
    if not longs and not shorts:
        lines.append("⏳ No signals.")
    text = "\n".join(lines)
    try:
        r = subprocess.run(["hermes", "send", "--to", "telegram"],
                           input=text, text=True, capture_output=True, timeout=30)
        log(f"📨 Telegram: {r.stdout.strip() or r.stderr.strip()}")
    except Exception as e:
        log(f"⚠ Telegram delivery failed: {e}")


def run_scan(notify=False):
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%Y-%m-%d %H:%M:%S ET")
    today_str = now_et.strftime("%Y-%m-%d")

    log("=" * 70)
    log("TJL Live Scanner — US Market (Yahoo Finance)")
    log(f"Time : {now_str}")
    log("=" * 70)

    # Step 1: Regime check (SPY + QQQ)
    regime = get_regime()
    log(f"Regime (SPY/QQQ): {regime}")
    if regime == "BEARISH":
        log("⚠️  BEARISH regime — TJL LONG suppressed; TJS SHORT allowed")
    log("")

    # Step 2: Build watchlist
    custom_tickers = os.environ.get("US_TICKERS", "").strip()
    if custom_tickers:
        watchlist = [(t, t) for t in custom_tickers.split(",")]
        log(f"Using custom tickers from US_TICKERS env: {len(watchlist)} tickers")
    else:
        watchlist = DEFAULT_WATCHLIST
        log(f"Using default watchlist: {len(watchlist)} tickers")

    # Step 3: Scan each ticker
    long_signals  = []
    short_signals = []
    debug_info    = []

        for ticker, name in watchlist:
        # Get daily bars first (needed for EMA + ATR)
        bars = get_daily_bars(ticker, count=80)
        if bars[0] is None:
            debug_info.append(f"{ticker}: no daily bars")
            continue
        highs, lows, closes, volumes = bars

        # Get live price
        quote = get_live_price(ticker)
        if quote is None:
            debug_info.append(f"{ticker}: no live price")
            continue

        price      = quote['price']
        day_high   = float(quote.get('day_high')) if quote.get('day_high') else None
        day_low    = float(quote.get('day_low'))  if quote.get('day_low')  else None

        # Today's open
        tk_yf = yf.Ticker(ticker)
        today_hist = tk_yf.history(period="5d", interval="1d")
        today_open = float(today_hist['Open'].iloc[-1]) if not today_hist.empty else price

        # Prior day high/low (index -2 = yesterday)
        prev_day_high = float(highs[-2]) if len(highs) >= 2 and not np.isnan(highs[-2]) else None
        prev_day_low  = float(lows[-2])  if len(lows)  >= 2 and not np.isnan(lows[-2])  else None

        # Premarket high and low (04:00-09:30 ET)
        premarket_high = get_premarket_high(ticker) or 0
        premarket_low  = get_premarket_low(ticker)  or 0

        # ── Model A: Pullback (EMA stack + near EMA9 + above PMH) ────────────
        if regime in ("BULLISH", "neutral"):
            sig, err = check_tjl(ticker, name, price, day_high, prev_day_high,
                                  highs, lows, closes, premarket_high=premarket_high)
            if sig:
                sig["signal_model"] = "A"
                long_signals.append(sig)
            elif err:
                debug_info.append(f"{ticker}A: {err.split(':')[-1].strip()}")

        # ── Model B: HT Momentum (above SMA200 + above PMH + above HOD) ──────
        if regime in ("BULLISH", "neutral"):
            r = check_tjl_model_b(price, highs, lows, closes, day_high)
            if r:
                r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "B"
                if r.get("above_sma200_ok") and r.get("above_pmh_ok") and r.get("above_hod_ok"):
                    if not any(s["ticker"] == ticker for s in long_signals):
                        long_signals.append(r)
                else:
                    reasons = []
                    if not r.get("above_sma200_ok"): reasons.append("!sma200")
                    if not r.get("above_pmh_ok"):    reasons.append("!abovePMH")
                    if not r.get("above_hod_ok"):    reasons.append("!aboveHOD")
                    debug_info.append(f"{ticker}B: {' '.join(reasons)}")

        # ── Model C: Volume-Confirmed Pullback ────────────────────────────────
        if regime in ("BULLISH", "neutral"):
            r = check_tjl_model_c(price, highs, lows, closes, volumes, day_high)
            if r:
                r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "C"
                if r.get("near_ema_ok") and r.get("above_pmh_ok") and r.get("vol_spike_ok"):
                    if not any(s["ticker"] == ticker for s in long_signals):
                        long_signals.append(r)
                else:
                    reasons = []
                    if not r.get("near_ema_ok"):  reasons.append("!near2pct")
                    if not r.get("above_pmh_ok"): reasons.append("!abovePMH")
                    if not r.get("vol_spike_ok"): reasons.append("!volSpike")
                    debug_info.append(f"{ticker}C: {' '.join(reasons)}")

        # ── Model D: RSI Oversold Bounce ─────────────────────────────────────
        r = check_tjl_model_d(price, highs, lows, closes, volumes, day_high, day_low)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "D"
            d_long  = r.get("long_fire")
            d_short = r.get("short_fire")
            if regime in ("BULLISH", "neutral") and d_long:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "D" for s in long_signals):
                    long_signals.append(r)
            elif regime == "BEARISH" and d_short:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "D" for s in short_signals):
                    short_signals.append(r)
            else:
                debug_info.append(f"{ticker}D: regime={regime} long={d_long} short={d_short}")

        # ── Model E: 20-Day High Breakout ───────────────────────────────────
        r = check_tjl_model_e(price, highs, lows, closes, volumes, day_high)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "E"
            e_long  = r.get("long_fire")
            e_short = r.get("short_fire")
            regime_ok_long  = regime in ("BULLISH", "neutral") and e_long
            regime_ok_short = regime == "BEARISH" and e_short
            if regime_ok_long:
                if not any(s["ticker"] == ticker for s in long_signals):
                    long_signals.append(r)
            elif regime_ok_short:
                if not any(s["ticker"] == ticker for s in short_signals):
                    short_signals.append(r)
            else:
                reasons = []
                if not r.get("at_lower"): reasons.append("!atLower")
                if not r.get("at_upper"): reasons.append("!atUpper")
                if not r.get("vol_ok"):   reasons.append("!volOk")
                debug_info.append(f"{ticker}E: {' '.join(reasons)}")

        # ── Model F: RSI Trend Crossover ────────────────────────────────────
        r = check_tjl_model_f(price, highs, lows, closes, volumes, day_high, day_low)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "F"
            f_long  = r.get("long_fire")
            f_short = r.get("short_fire")
            regime_ok_long  = regime in ("BULLISH", "neutral") and f_long
            regime_ok_short = regime in ("BEARISH", "neutral") and f_short
            if regime_ok_long:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "F" for s in long_signals):
                    long_signals.append(r)
            elif regime_ok_short:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "F" for s in short_signals):
                    short_signals.append(r)
            else:
                debug_info.append(f"{ticker}F: regime={regime} long={f_long} short={f_short}")

        # ── Model G: Opening Range Breakout ───────────────────────────────────
        r = check_tjl_model_g(price, highs, lows, closes, volumes, day_high, day_low, today_open)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "G"
            g_long  = r.get("long_fire")
            g_short = r.get("short_fire")
            regime_ok_long  = regime in ("BULLISH", "neutral") and g_long
            regime_ok_short = regime in ("BEARISH", "neutral") and g_short
            if regime_ok_long:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "G" for s in long_signals):
                    long_signals.append(r)
            elif regime_ok_short:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "G" for s in short_signals):
                    short_signals.append(r)

        # ── Model H: Gold EMA/BB ─────────────────────────────────────────────
        r = check_tjl_model_h(price, highs, lows, closes, volumes, day_high, day_low)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "H"
            h_long  = r.get("long_fire")
            h_short = r.get("short_fire")
            regime_ok_long  = regime in ("BULLISH", "neutral") and h_long
            regime_ok_short = regime in ("BEARISH", "neutral") and h_short
            if regime_ok_long:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "H" for s in long_signals):
                    long_signals.append(r)
            elif regime_ok_short:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "H" for s in short_signals):
                    short_signals.append(r)

        # ── Model I: 63WMA Swing ─────────────────────────────────────────────
        r = check_tjl_model_i(price, highs, lows, closes, volumes, day_high)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "I"
            i_long  = r.get("long_fire")
            i_short = r.get("short_fire")
            regime_ok_long  = regime in ("BULLISH", "neutral") and i_long
            regime_ok_short = regime in ("BEARISH", "neutral") and i_short
            if regime_ok_long:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "I" for s in long_signals):
                    long_signals.append(r)
            elif regime_ok_short:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "I" for s in short_signals):
                    short_signals.append(r)

        # ── Model J: Follow the Money DMA ────────────────────────────────────
        r = check_tjl_model_j(price, highs, lows, closes, volumes, day_high)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "J"
            j_long  = r.get("long_fire")
            j_short = r.get("short_fire")
            regime_ok_long  = regime in ("BULLISH", "neutral") and j_long
            regime_ok_short = regime in ("BEARISH", "neutral") and j_short
            if regime_ok_long:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "J" for s in long_signals):
                    long_signals.append(r)
            elif regime_ok_short:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "J" for s in short_signals):
                    short_signals.append(r)

        # ── Model K: EMA/VWAP/Bollinger Session ───────────────────────────────
        r = check_tjl_model_k(price, highs, lows, closes, volumes, day_high, day_low)
        if r:
            r["ticker"] = ticker; r["name"] = name; r["signal_model"] = "K"
            k_long  = r.get("long_fire")
            k_short = r.get("short_fire")
            regime_ok_long  = regime in ("BULLISH", "neutral") and k_long
            regime_ok_short = regime in ("BEARISH", "neutral") and k_short
            if regime_ok_long:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "K" for s in long_signals):
                    long_signals.append(r)
            elif regime_ok_short:
                if not any(s["ticker"] == ticker and s.get("signal_model") == "K" for s in short_signals):
                    short_signals.append(r)

        # ── TJS SHORT (suppressed in BULLISH) ───────────────────────────────
        if regime == "BEARISH":
            r, err = check_tjs(ticker, name, price, day_low, prev_day_low,
                                highs, lows, closes, premarket_low=premarket_low)
            if err:
                debug_info.append(err)
            else:
                short_signals.append(r)

    all_signals = long_signals + short_signals

    # Step 4: Print results
    log("")
    if all_signals:
        log("=" * 70)
        log("  🚨 US TJL SIGNALS")
        log("=" * 70)

        if long_signals:
            log("")
            log("  🟢 LONG")
            log(f"  {'Ticker':<10} {'Name':<14} {'Price':>8} {'EMA9':>8} {'EMA20':>8} {'EMA50':>8} "
                f"{'PMH':>8} {'SL':>8} {'TP':>8} {'R:R':>5}")
            log("  " + "-" * 97)
            for s in sorted(long_signals, key=lambda x: -x['rr_ratio']):
                log(f"  {s['ticker']:<10} {s['name']:<14} {s['price']:>8.2f} {s['e9']:>8.2f} "
                    f"{s['e20']:>8.2f} {s['e50']:>8.2f} {s['pmh']:>8.2f} "
                    f"{s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}")

        if short_signals:
            log("")
            log("  🔴 SHORT")
            log(f"  {'Ticker':<10} {'Name':<14} {'Price':>8} {'EMA9':>8} {'EMA20':>8} {'EMA50':>8} "
                f"{'PML':>8} {'SL':>8} {'TP':>8} {'R:R':>5}")
            log("  " + "-" * 97)
            for s in sorted(short_signals, key=lambda x: -x['rr_ratio']):
                log(f"  {s['ticker']:<10} {s['name']:<14} {s['price']:>8.2f} {s['e9']:>8.2f} "
                    f"{s['e20']:>8.2f} {s['e50']:>8.2f} {s['pml']:>8.2f} "
                    f"{s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}")

        log("")
        log(f"  ✅ {len(all_signals)} signal(s) ({len(long_signals)} LONG, {len(short_signals)} SHORT)")
    else:
        log("=" * 70)
        log("  ⏳ NO TJL SIGNALS — all conditions fail for all tickers")
        log("=" * 70)

    # Debug info
    if debug_info:
        log("")
        log("── Debug (condition fails) ──")
        for d in debug_info[:20]:
            log(f"  {d}")

    # Step 5: Save to file
    out_file = os.path.expanduser(f"~/tjl_live_us_{today_str}.json")
    with open(out_file, "w") as f:
        json.dump({
            "scanned_at": now_str,
            "source": "Yahoo Finance",
            "regime": regime,
            "signals": all_signals,
            "longs": long_signals,
            "shorts": short_signals,
            "debug": debug_info[:20],
        }, f, indent=2)
    log(f"📁 Saved to {out_file}")

    # Step 6: Discord
    post_discord(all_signals, now_str, regime)

    # Step 7: Optional Telegram notification
    if notify:
        try:
            with open(out_file) as f:
                payload = json.load(f)
            notify_telegram(payload)
        except Exception as e:
            log(f"⚠ notify failed: {e}")

    return all_signals


def main():
    parser = argparse.ArgumentParser(description="TJL Live Scanner — US Market (yfinance)")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL,
                        help=f"Seconds between scans (default {SCAN_INTERVAL})")
    parser.add_argument("--notify", action="store_true",
                        help="Send results to Telegram after each scan")
    args = parser.parse_args()

    log(f"TJL Live US Scanner | yfinance | Press Ctrl+C to stop")
    log(f"Watchlist: {len(DEFAULT_WATCHLIST)} tickers (override with US_TICKERS env)")
    log("")

    if args.continuous:
        log(f"CONTINUOUS mode — interval {args.interval}s")
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
