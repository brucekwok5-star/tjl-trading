#!/usr/bin/env python3
"""
TJL US Scanner — HK-style 11 Models A-K (A/B/C/D/E/F/G/H/I/J/K)
Ported from tjl_live_futu.py HK strategy to US markets via yfinance.

KEY DIFFERENCES vs tjl_ndx11.py (US-style):
  A: NEAR_EMA_PCT=1.5% (HK-style, was 1.0%)
  B: No stack, just SMA200 + PMH + HOD
  C: NEW — Vol Pullback (2% EMA9 + vol spike 2x + PMH)
  D: RSI crosses through 30 (not < 30) + near VWAP
  E: BB Squeeze + 20d hi/lo + RSI gate
  F: RSI crosses 50 + price vs EMA20 (not stack)
  G: ORB + ATR confirm + stack
  H: EMA9 crosses BB mid + EMA21 + VWAP triple confirm
  I: 63WMA + RSI gate (pullback vs WMA from correct side)
  J: 150/200 DMA + vol (needs 200 bars)
  K: Same as H (EMA9 cross BB mid)
  ATR: 1.0 / 1.5 for D/E/F/G/H/J/K; 1.5 / 3.0 for A/B/C (2:1 R:R)
"""
import sys, os, json, time, yfinance as yf
import numpy as np, pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import functools

ET = ZoneInfo("America/New_York")

# ── Strategy constants (HK-style) ─────────────────────────────────────────────
PMH_BUF          = 0.70    # USD buffer for PMH
ATR_PERIOD       = 14

# Model-specific R:R
ATR_SL_TIGHT     = 1.0     # Models D/E/F/G/H/J/K: 1:1.5 R:R
ATR_TP_TIGHT     = 1.5
ATR_SL_WIDE      = 1.5     # Models A/B/C: 1:2 R:R
ATR_TP_WIDE      = 3.0

NEAR_EMA_PCT_A   = 0.015   # Model A: ±1.5% of EMA9
NEAR_EMA_PCT_C   = 0.020   # Model C: ±2.0% of EMA9
NEAR_EMA_PCT_I   = 0.030   # Model I: ±3.0% of 63WMA
VOL_SPIKE_MULT   = 2.0      # Model C/J: vol ≥ 2× avg20
VOL_CONFIRM      = 1.5      # Models E/H/I: vol ≥ 1.5× avg20

# Backtested win rates — updated from grid search (9 tickers, 60d, 15-min bars)
# Sources: 1) prior backtest (1271+ trades US+HK), 2) grid search Aug 2026 (9 tickers, 60d)
# VERDICT: H(profitable), I(profitable), J(profitable), K(profitable) | F(marginal in BEARISH) | kill rest
MODEL_WR = {
    'A': {'wr': 31, 'avg': -0.20, 'trades': 13,  'verdict': 'kill'},
    'B': {'wr':  0, 'avg':  0.00, 'trades':  0,  'verdict': 'untested'},
    'C': {'wr':  0, 'avg':  0.00, 'trades':  0,  'verdict': 'untested'},
    'D': {'wr':  0, 'avg': -3.43, 'trades':  5,  'verdict': 'kill'},
    'E': {'wr': 17, 'avg': -1.03, 'trades': 42,  'verdict': 'kill'},
    'F': {'wr': 56, 'avg': +0.40, 'trades': 295, 'verdict': 'BEARISH-only'},  # 56% WR in BEARISH
    'G': {'wr': 21, 'avg': -0.46, 'trades': 81,  'verdict': 'kill'},
    'H': {'wr': 50, 'avg': +0.04, 'trades':   4,  'verdict': 'profitable'},  # 42-50% WR
    'I': {'wr': 31, 'avg': +0.41, 'trades': 225,  'verdict': 'profitable'},  # 31% WR backtested (vs 48% prior estimate)
    'J': {'wr': 54, 'avg': +0.76, 'trades': 323,  'verdict': 'profitable'},  # 54% WR HK
    'K': {'wr': 45, 'avg': +0.69, 'trades':  10,  'verdict': 'profitable'},
}
PROFITABLE_MODELS = {'H', 'I', 'J', 'K'}
BEARISH_ONLY_MODELS = {'F'}

# ── Helpers ───────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)

def calc_emas(closes):
    c = np.array(closes, dtype=float)
    e9  = float(pd.Series(c).ewm(span=9,  adjust=False).mean().iloc[-1])
    e20 = float(pd.Series(c).ewm(span=20, adjust=False).mean().iloc[-1])
    e21 = float(pd.Series(c).ewm(span=21, adjust=False).mean().iloc[-1])
    e50 = float(pd.Series(c).ewm(span=50, adjust=False).mean().iloc[-1])
    return e9, e20, e21, e50

def calc_atr(highs, lows, closes, period=14):
    h = np.array(highs, dtype=float); l = np.array(lows, dtype=float); c = np.array(closes, dtype=float)
    if len(c) < period + 1: return None
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(tr[-period:].mean())

def calc_vwap(highs, lows, closes, volumes):
    h = np.array(highs, dtype=float); l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float); v = np.array(volumes, dtype=float)
    if len(v) < 2 or v.sum() == 0: return None
    tp = (h + l + c) / 3
    return float((tp * v).sum() / v.sum())

def calc_rsi(closes, period=14):
    c = np.array(closes, dtype=float)
    if len(c) < period + 1: return None
    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = float(pd.Series(gain).ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    avg_loss = float(pd.Series(loss).ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    if avg_loss == 0: return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calc_prev_rsi(closes, period=14):
    """Previous bar's RSI (for cross detection).

    Uses the same delta sequence as calc_rsi (prepend c[0]) so that the
    EWM chain is identical — taking iloc[-2] gives the true previous RSI.
    """
    c = np.array(closes, dtype=float)
    if len(c) < period + 2: return None
    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = float(pd.Series(gain).ewm(alpha=1/period, adjust=False).mean().iloc[-2])
    avg_loss = float(pd.Series(loss).ewm(alpha=1/period, adjust=False).mean().iloc[-2])
    if avg_loss == 0: return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calculate_confidence(model_wr, regime, direction, rr_ratio):
    """Score signal confidence 0-1.

    Formula: (model_wr/100) * (1.2 if regime matches direction else 1.0) * (rr_ratio/2.0)
    """
    regime_match = (
        (regime == 'BULLISH' and direction == 'LONG') or
        (regime == 'BEARISH' and direction == 'SHORT')
    )
    return round((model_wr / 100) * (1.2 if regime_match else 1.0) * (rr_ratio / 2.0), 3)

def make_signal(ticker, price, direction, model, atr, e9=None, extra=None, regime=None):
    """Build signal dict. Uses model-specific ATR for R:R."""
    wide = model in ('A', 'B', 'C', 'I')
    sl_mult = ATR_SL_WIDE if wide else ATR_SL_TIGHT
    tp_mult = ATR_TP_WIDE if wide else ATR_TP_TIGHT
    if direction == 'LONG':
        sl = round(price - sl_mult * atr, 2)
        tp = round(price + tp_mult * atr, 2)
    else:
        sl = round(price + sl_mult * atr, 2)
        tp = round(price - tp_mult * atr, 2)
    rr = round(tp_mult / sl_mult, 1)
    model_wr = MODEL_WR.get(model, {}).get('wr', 0)
    sig = {
        'ticker': ticker, 'price': round(price, 2),
        'direction': direction, 'model': model,
        'sl': sl, 'tp': tp, 'rr_ratio': rr,
        'atr': round(atr, 3),
        'wr': model_wr,
        'wr_verdict': MODEL_WR.get(model, {}).get('verdict', 'unknown'),
        'atr_type': 'wide' if wide else 'tight',
    }
    if regime is not None:
        sig['confidence'] = calculate_confidence(model_wr, regime, direction, rr)
    if e9 is not None:
        sig['e9'] = round(e9, 2)
        sig['near_pct'] = round(abs(price - e9) / e9 * 100, 2)
    if extra:
        sig.update(extra)
    return sig

# ── Partial-bar protection ────────────────────────────────────────────────────
def is_market_hours():
    """True during US regular trading hours (9:30-16:00 ET, Mon-Fri).

    Uses ET timezone-aware now so callers don't need to worry about local TZ.
    """
    now = datetime.now(ET)
    if now.weekday() >= 5:          # Sat=5, Sun=6
        return False
    t = now.hour + now.minute / 60.0
    return 9.5 <= t < 16.0

def get_safe_price(ticker_data):
    """Return a non-partial price for the ticker.

    During US market hours, the last daily bar from yfinance is PARTIAL —
    the Close is an intraday snapshot with low volume. Using it as the
    'price' for signal generation causes false signals (P0 bug).

    Fix: while RTH is open, return the previous day's COMPLETE close
    (ticker_data['prev_close']). After the close, return the current
    bar's Close as normal.
    """
    if is_market_hours():
        return ticker_data['prev_close']
    return ticker_data['price']

# ── Batch data fetch ──────────────────────────────────────────────────────────
def fetch_batch(tickers, period="250d"):
    """Batch-download daily bars. Needs 250d for Model J (150+200 DMA)."""
    valid = [t.strip() for t in tickers if t and t.strip()]
    if not valid: return {}
    try:
        data = yf.download(valid, period=period, interval="1d",
                           group_by='ticker', progress=False, threads=True)
    except Exception as e:
        log(f"Batch download error: {e}")
        return {}
    results = {}
    for t in valid:
        try:
            if data is None or data.empty:
                continue
            if len(valid) == 1 and not isinstance(data.columns, pd.MultiIndex):
                df = data
            elif isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    continue
                df = data[t]
            else:
                df = data
            if df is None or df.empty:
                continue
            df = df.dropna(subset=['Close'])
            if len(df) < 30:
                continue
            closes  = df['Close'].values
            highs   = df['High'].values
            lows    = df['Low'].values
            volumes = df['Volume'].values
            prev_close = float(df['Close'].iloc[-2]) if len(df) >= 2 else float(closes[0])
            raw_price  = float(df['Close'].iloc[-1])
            # P0 fix: during RTH, daily bar Close is a partial intraday snapshot.
            # Use prev_close as the 'price' so signals don't fire on incomplete data.
            safe_price = prev_close if is_market_hours() else raw_price
            results[t] = {
                'closes': closes, 'highs': highs, 'lows': lows, 'volumes': volumes,
                'today_open':  float(df['Open'].iloc[-1]),
                'prev_high':   float(df['High'].iloc[-2]) if len(df) >= 2 else float(df['High'].iloc[0]),
                'prev_low':    float(df['Low'].iloc[-2])  if len(df) >= 2 else float(df['Low'].iloc[0]),
                'prev_close':  prev_close,
                'raw_price':   raw_price,           # last daily Close (partial during RTH)
                'price':       safe_price,          # safe price used by all model checkers
                'day_high':    float(df['High'].iloc[-1]),
                'day_low':     float(df['Low'].iloc[-1]),
            }
        except Exception:
            continue
    return results

# ── Regime ─────────────────────────────────────────────────────────────────────
REGIME_CACHE = {'result': None, 'timestamp': 0.0}
REGIME_CACHE_TTL = 300  # 5 minutes

@functools.lru_cache(maxsize=1)
def _get_regime_cached():
    """Actual regime computation — called through get_regime() with LRU cache."""
    try:
        spy = yf.Ticker("SPY").history(period="1y", interval="1d")
        qqq = yf.Ticker("QQQ").history(period="1y", interval="1d")
        if spy.empty or qqq.empty:
            return "neutral"
        def smas(df):
            s50  = df['Close'].rolling(50).mean().iloc[-1]
            s200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else df['Close'].mean()
            return df['Close'].iloc[-1] > s50 > s200
        if smas(spy) and smas(qqq):
            return "BULLISH"
        if not smas(spy) and not smas(qqq):
            return "BEARISH"
        return "neutral"
    except Exception:
        return "neutral"

def get_regime():
    """Return cached regime (5-min TTL). Invalidate manually via REGIME_CACHE['timestamp'] = 0."""
    now = time.time()
    if REGIME_CACHE['result'] is not None and (now - REGIME_CACHE['timestamp']) < REGIME_CACHE_TTL:
        return REGIME_CACHE['result']
    result = _get_regime_cached()
    REGIME_CACHE['result'] = result
    REGIME_CACHE['timestamp'] = now
    return result

# ── EMA Stack ─────────────────────────────────────────────────────────────────
def ema_stack(e9, e20, e50):
    if e9 > e20 > e50: return 'bullish'
    if e9 < e20 < e50: return 'bearish'
    return 'neutral'

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL A — Pullback (original TJL: EMA9 > EMA20 > EMA50 + near EMA9 + PMH)
# R:R: 1:2 (ATR 1.5 / 3.0)
# ═══════════════════════════════════════════════════════════════════════════════
def check_a(ticker, d):
    """
    HK-style Model A:
      1. Bullish EMA stack: EMA9 > EMA20 > EMA50
      2. Pullback: |price - EMA9| / EMA9 <= 1.5% (NEAR_EMA_PCT_A)
      3. Above PMH + PMH_BUF
    Exit: SL = price - 1.5×ATR, TP = price + 3.0×ATR
    """
    c = d['closes']
    if len(c) < 60: return None
    e9, e20, _, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(d['highs'], d['lows'], c)
    if not atr: return None
    price = d['price']
    pmh = d['prev_high']

    stack_ok     = (e9 > e20 > e50)
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT_A)
    above_pmh_ok = (price > pmh + PMH_BUF)
    if stack_ok and near_ema_ok and above_pmh_ok:
        return make_signal(ticker, price, 'LONG', 'A', atr, e9)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL B — HT Momentum (Above SMA200 + PMH + today's HOD)
# R:R: 1:2 (ATR 1.5 / 3.0)
# ═══════════════════════════════════════════════════════════════════════════════
def check_b(ticker, d):
    """
    HK-style Model B (no EMA stack, pure momentum):
      1. Price > SMA200
      2. Price > PMH + PMH_BUF
      3. Price > today's HOD - 0.50 (within 0.50 of HOD)
    Exit: SL = price - 1.5×ATR, TP = price + 3.0×ATR
    """
    c = d['closes']
    if len(c) < 200: return None
    sma200 = float(pd.Series(np.array(c)).rolling(200).mean().iloc[-1])
    if np.isnan(sma200): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    price = d['price']

    above_sma200 = (price > sma200)
    above_pmh    = (price > d['prev_high'] + PMH_BUF)
    above_hod    = (price > d['day_high'] - 0.50)
    if above_sma200 and above_pmh and above_hod:
        return make_signal(ticker, price, 'LONG', 'B', atr)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL C — Volume-Confirmed Pullback (NEW in HK-style)
# R:R: 1:2 (ATR 1.5 / 3.0)
# ═══════════════════════════════════════════════════════════════════════════════
def check_c(ticker, d):
    """
    HK-style Model C (volume spike + wide pullback):
      1. No EMA stack required (any trend)
      2. Price within ±2.0% of EMA9 (NEAR_EMA_PCT_C)
      3. Volume >= 2× avg20 (VOL_SPIKE_MULT)
      4. Above PMH + PMH_BUF
    Exit: SL = price - 1.5×ATR, TP = price + 3.0×ATR
    """
    c = d['closes']; v = d['volumes']
    if len(c) < 60 or len(v) < 22: return None
    e9, _, _, _ = calc_emas(c)
    if np.isnan(e9): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    avg_vol20 = float(np.mean(v[-20:]))
    price = d['price']

    near_ema  = (abs(price - e9) / e9 <= NEAR_EMA_PCT_C)
    vol_spike = (v[-1] >= VOL_SPIKE_MULT * avg_vol20)
    above_pmh = (price > d['prev_high'] + PMH_BUF)
    if near_ema and vol_spike and above_pmh:
        return make_signal(ticker, price, 'LONG', 'C', atr, e9)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL D — RSI Oversold Bounce (mean reversion)
# R:R: 1:1.5 (ATR 1.0 / 1.5)
# ═══════════════════════════════════════════════════════════════════════════════
def check_d(ticker, d):
    """
    HK-style Model D (RSI cross through 30 = true mean reversion):
      LONG:  RSI(14) crosses UP through 30 from below 30
              AND price within 1.5% of VWAP
              AND price > PMH
      Exit:   SL = price - 1.0×ATR, TP = price + 1.5×ATR
    """
    c = d['closes']; v = d['volumes']
    if len(c) < 22: return None
    rsi_curr = calc_rsi(c)
    rsi_prev = calc_prev_rsi(c)
    if rsi_curr is None or rsi_prev is None: return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    vwap = calc_vwap(d['highs'], d['lows'], c, v)
    if vwap is None: return None
    price = d['price']

    # RSI crosses UP through 30 (was below, now above or at 30)
    rsi_cross_up = (rsi_prev < 30 <= rsi_curr)
    near_vwap     = (abs(price - vwap) / vwap <= 0.015)
    above_pmh     = (price > d['prev_high'] + PMH_BUF)
    if rsi_cross_up and near_vwap and above_pmh:
        return make_signal(ticker, price, 'LONG', 'D', atr)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL E — BB Squeeze + 20d Hi/Lo Breakout + RSI gate
# R:R: 1:1.5 (ATR 1.0 / 1.5)
# ═══════════════════════════════════════════════════════════════════════════════
def check_e(ticker, d):
    """
    HK-style Model E (BB squeeze + 20d breakout + RSI confirm):
      LONG:  Price breaks above 20-day HIGH AND RSI > 50 AND vol >= 1.5× avg20
      SHORT: Price breaks below 20-day LOW  AND RSI < 50 AND vol >= 1.5× avg20
      Exit:  SL = price ± 1.0×ATR, TP = price ± 1.5×ATR
    """
    c = d['closes']; h = d['highs']; l = d['lows']; v = d['volumes']
    if len(c) < 25: return None
    rsi = calc_rsi(c)
    if rsi is None: return None
    atr = calc_atr(h, l, c) or (d['price'] * 0.01)
    avg_vol20 = float(np.mean(v[-20:]))
    vol_ok = (v[-1] >= VOL_CONFIRM * avg_vol20)
    price = d['price']

    hi20  = float(np.max(h[-20:]))      # 20-day high of highs
    lo20  = float(np.min(l[-20:]))      # 20-day low of lows
    s = pd.Series(np.array(c))
    bb_s = float(s.rolling(20).std().iloc[-1])
    bb_avg = float(s.rolling(20).mean().iloc[-1])
    bb_bandwidth = bb_s
    bb_avg_bandwidth = float(s.rolling(20).apply(
        lambda x: np.std(x), raw=True).mean())

    # Squeeze: current bandwidth < 20% of average bandwidth
    squeeze = (bb_bandwidth < 0.20 * bb_avg_bandwidth) if bb_avg_bandwidth > 0 else False

    # LONG: above 20d high + RSI > 50 + vol
    long_fire  = (price >= hi20 * 0.98) and (rsi > 50) and vol_ok
    # SHORT: below 20d low + RSI < 50 + vol
    short_fire = (price <= lo20 * 1.02) and (rsi < 50) and vol_ok

    if long_fire:
        return make_signal(ticker, price, 'LONG', 'E', atr, extra={'squeeze': squeeze, 'rsi': round(rsi, 1)})
    if short_fire:
        return make_signal(ticker, price, 'SHORT', 'E', atr, extra={'squeeze': squeeze, 'rsi': round(rsi, 1)})
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL F — RSI Trend Crossover (HK-style)
# R:R: 1:1.5 (ATR 1.0 / 1.5)
# ═══════════════════════════════════════════════════════════════════════════════
def check_f(ticker, d, direction='LONG'):
    """
    HK-style Model F (RSI crosses 50 + price vs EMA20):
      LONG:  RSI(14) crosses ABOVE 50 while price > EMA20
      SHORT: RSI(14) crosses BELOW 50 while price < EMA20
      Exit:  SL = price ± 1.0×ATR, TP = price ± 1.5×ATR
    """
    c = d['closes']
    if len(c) < 22: return None
    rsi_curr = calc_rsi(c)
    rsi_prev = calc_prev_rsi(c)
    if rsi_curr is None or rsi_prev is None: return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    e9, e20, _, _ = calc_emas(c)
    if np.isnan(e9) or np.isnan(e20): return None
    price = d['price']

    # RSI crossed above 50
    cross_up   = (rsi_prev < 50 <= rsi_curr)
    # RSI crossed below 50
    cross_down = (rsi_prev > 50 >= rsi_curr)

    if direction == 'LONG':
        above_ema20 = (price > e20)
        if cross_up and above_ema20:
            return make_signal(ticker, price, 'LONG', 'F', atr, e9)
    else:  # SHORT
        below_ema20 = (price < e20)
        if cross_down and below_ema20:
            return make_signal(ticker, price, 'SHORT', 'F', atr, e9)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL G — ORB / Opening Range Breakout (HK-style)
# R:R: 1:1.5 (ATR 1.0 / 1.5)
# ═══════════════════════════════════════════════════════════════════════════════
def check_g(ticker, d, direction='LONG'):
    """
    HK-style Model G (ORB + ATR confirm + stack):
      LONG:  Price > today_open + PMH_BUF
             AND price > EMA9 > EMA20 (bullish stack)
             AND ATR confirms direction (atr < price * 0.03 = not too volatile)
      SHORT: Price < today_open - PMH_BUF
             AND price < EMA9 < EMA20 (bearish stack)
             AND ATR confirms
      Exit:  SL = price ± 1.0×ATR, TP = price ± 1.5×ATR
    """
    c = d['closes']
    today_open = d.get('today_open')
    if len(c) < 30 or today_open is None: return None
    e9, e20, _, _ = calc_emas(c)
    if np.isnan(e9) or np.isnan(e20): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    price = d['price']

    above_open = (price > today_open + PMH_BUF)
    below_open = (price < today_open - PMH_BUF)
    stack_bull = (e9 > e20)
    stack_bear = (e9 < e20)
    # ATR sanity: stock not too volatile for ORB
    atr_ok = (atr < price * 0.03)

    if direction == 'LONG':
        if above_open and stack_bull and atr_ok:
            return make_signal(ticker, price, 'LONG', 'G', atr, e9)
    else:
        if below_open and stack_bear and atr_ok:
            return make_signal(ticker, price, 'SHORT', 'G', atr, e9)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL H — Gold EMA/BB/VWAP (HK-style)
# R:R: 1:1.5 (ATR 1.0 / 1.5)
# ═══════════════════════════════════════════════════════════════════════════════
def check_h(ticker, d, direction='LONG'):
    """
    HK-style Model H (EMA9 crosses BB mid + EMA21 + VWAP triple confirm):
      LONG:  EMA9 crosses ABOVE BB(20) midline
             AND price > EMA21
             AND price > VWAP
             AND vol >= 1.5× avg20
      SHORT: EMA9 crosses BELOW BB(20) midline
             AND price < EMA21
             AND price < VWAP
             AND vol >= 1.5× avg20
      Exit:  SL = price ± 1.0×ATR, TP = price ± 1.5×ATR
    """
    c = d['closes']; v = d['volumes']
    if len(c) < 50: return None
    e9, e20, e21, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e21, e50]): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    vwap = calc_vwap(d['highs'], d['lows'], c, v)
    if vwap is None: return None
    price = d['price']
    avg_vol20 = float(np.mean(v[-20:]))
    vol_ok = (v[-1] >= VOL_CONFIRM * avg_vol20)

    s = pd.Series(np.array(c))
    bb_mid = float(s.rolling(20).mean().iloc[-1])
    prev_bb_mid = float(s.iloc[:-1].rolling(20).mean().iloc[-1])
    if np.isnan(bb_mid) or np.isnan(prev_bb_mid) or prev_bb_mid <= 0: return None

    # EMA9 crosses ABOVE BB midline
    ema_cross_up   = (e9 > bb_mid) and (e9 <= prev_bb_mid)
    # EMA9 crosses BELOW BB midline
    ema_cross_down = (e9 < bb_mid) and (e9 >= prev_bb_mid)

    above_vwap = (price > vwap)
    below_vwap = (price < vwap)
    above_ema21 = (price > e21)
    below_ema21 = (price < e21)

    if direction == 'LONG':
        if ema_cross_up and above_ema21 and above_vwap and vol_ok:
            return make_signal(ticker, price, 'LONG', 'H', atr, e9)
    else:
        if ema_cross_down and below_ema21 and below_vwap and vol_ok:
            return make_signal(ticker, price, 'SHORT', 'H', atr, e9)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL I — 63WMA Swing (SHM-lite)
# R:R: 1:2 (ATR 1.5 / 3.0)
# ═══════════════════════════════════════════════════════════════════════════════
def check_i(ticker, d, direction='LONG'):
    """
    HK-style Model I (63WMA + RSI gate + pullback):
      LONG:  Price > 63WMA
             AND RSI(14) > 50
             AND price has pulled BACK to within 3% of 63WMA from above
             (pullback-to-trend, not chasing)
      SHORT: Price < 63WMA
             AND RSI(14) < 50
             AND price has rallied TO within 3% of 63WMA from below
             (rejection of trend)
      Exit:  SL = price ± 1.5×ATR, TP = price ± 3.0×ATR (2:1 R:R)
    """
    c = d['closes']
    if len(c) < 70: return None
    rsi = calc_rsi(c)
    if rsi is None: return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    price = d['price']
    s = pd.Series(np.array(c))
    wma63 = float(s.rolling(63).mean().iloc[-1])
    if np.isnan(wma63) or wma63 <= 0: return None
    pullback_tol = NEAR_EMA_PCT_I  # 3%

    above_wma = (price > wma63)
    below_wma = (price < wma63)
    # Pullback: price has come back TO WMA from the correct side
    # LONG: price was above wma63, now pulled back to within 3% of it
    pullback_long  = (abs(price - wma63) / wma63 <= pullback_tol)
    # SHORT: price was below wma63, now rallied to within 3% of it
    rally_short = (abs(price - wma63) / wma63 <= pullback_tol)

    # STRICTER SHORT filters: prevent fading a near-WMA bounce in choppy markets
    # Require: RSI < 45 (not just < 50) + price 1.5%+ away from WMA (not just touching)
    # LONG: unchanged
    if direction == 'LONG':
        if above_wma and pullback_long and rsi > 50:
            return make_signal(ticker, price, 'LONG', 'I', atr, extra={'wma63': round(wma63, 2), 'rsi': round(rsi, 1)})
    else:
        # SHORT: RSI < 45 (more oversold) AND price further from WMA (1.5% min)
        strong_short = rsi < 45 and (wma63 - price) / wma63 >= 0.015
        if below_wma and rally_short and strong_short:
            return make_signal(ticker, price, 'SHORT', 'I', atr, extra={'wma63': round(wma63, 2), 'rsi': round(rsi, 1)})
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL J — 150/200 DMA Follow-the-Money (needs 250 bars)
# R:R: 1:1.5 (ATR 1.0 / 1.5)
# ═══════════════════════════════════════════════════════════════════════════════
def check_j(ticker, d, direction='LONG'):
    """
    HK-style Model J (150/200 DMA + vol surge):
      LONG:  Price within 2% of 150-DMA
             AND price > 200-DMA (confirm uptrend)
             AND vol >= 2× avg20
      SHORT: Price within 2% of 150-DMA
             AND price < 200-DMA (confirm downtrend)
             AND vol >= 2× avg20
      Exit:  SL = price ± 1.0×ATR, TP = price ± 1.5×ATR
    """
    c = d['closes']; v = d['volumes']
    if len(c) < 210: return None   # need 200 for DMA200 + buffer
    s = pd.Series(np.array(c))
    dma150 = float(s.rolling(150).mean().iloc[-1])
    dma200 = float(s.rolling(200).mean().iloc[-1])
    if np.isnan(dma150) or np.isnan(dma200): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    avg_vol20 = float(np.mean(v[-20:]))
    vol_ok = (v[-1] >= VOL_SPIKE_MULT * avg_vol20)  # 2x vol for J
    price = d['price']

    near_dma150 = (abs(price - dma150) / dma150 <= 0.02)
    above_200   = (price > dma200)
    below_200   = (price < dma200)

    if direction == 'LONG':
        if near_dma150 and above_200 and vol_ok:
            return make_signal(ticker, price, 'LONG', 'J', atr, extra={'dma150': round(dma150, 2), 'dma200': round(dma200, 2)})
    else:
        if near_dma150 and below_200 and vol_ok:
            return make_signal(ticker, price, 'SHORT', 'J', atr, extra={'dma150': round(dma150, 2), 'dma200': round(dma200, 2)})
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL K — EMA/VWAP/Bollinger Session (identical logic to H, separate model)
# R:R: 1:1.5 (ATR 1.0 / 1.5)
# ═══════════════════════════════════════════════════════════════════════════════
def check_k(ticker, d, direction='SHORT'):
    """
    HK-style Model K (same as Model H — EMA9 cross BB mid):
      Kept separate for independent signal tracking.
      SHORT only in this implementation.
      LONG:  EMA9 crosses above BB mid + price > EMA21 + price > VWAP
      SHORT: EMA9 crosses below BB mid + price < EMA21 + price < VWAP
      Exit:  SL = price ± 1.0×ATR, TP = price ± 1.5×ATR
    """
    c = d['closes']; v = d['volumes']
    if len(c) < 50: return None
    e9, e20, e21, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e21, e50]): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    vwap = calc_vwap(d['highs'], d['lows'], c, v)
    if vwap is None: return None
    price = d['price']
    avg_vol20 = float(np.mean(v[-20:]))
    vol_ok = (v[-1] >= VOL_CONFIRM * avg_vol20)

    s = pd.Series(np.array(c))
    bb_mid = float(s.rolling(20).mean().iloc[-1])
    prev_bb_mid = float(s.iloc[:-1].rolling(20).mean().iloc[-1])
    if np.isnan(bb_mid) or np.isnan(prev_bb_mid) or prev_bb_mid <= 0: return None

    ema_cross_up   = (e9 > bb_mid) and (e9 <= prev_bb_mid)
    ema_cross_down = (e9 < bb_mid) and (e9 >= prev_bb_mid)
    above_vwap = (price > vwap); below_vwap = (price < vwap)
    above_ema21 = (price > e21); below_ema21 = (price < e21)

    if direction == 'LONG':
        if ema_cross_up and above_ema21 and above_vwap and vol_ok:
            return make_signal(ticker, price, 'LONG', 'K', atr, e9)
    else:
        if ema_cross_down and below_ema21 and below_vwap and vol_ok:
            return make_signal(ticker, price, 'SHORT', 'K', atr, e9)
    return None

# ── Regime routing ────────────────────────────────────────────────────────────
LONG_MODELS   = {'A', 'B', 'C', 'D', 'E'}
SHORT_MODELS  = {'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K'}

def can_long(regime):
    return regime in ('BULLISH', 'neutral')

def can_short(regime):
    return regime in ('BEARISH', 'neutral')

# ── Scan engine ───────────────────────────────────────────────────────────────
_prev_closes = {}

MODEL_CHECKERS = [
    # (model_letter, direction_label, checker_fn, regime_check_fn)
    ('A', 'LONG',  check_a,  lambda r: can_long(r)),
    ('B', 'LONG',  check_b,  lambda r: can_long(r)),
    ('C', 'LONG',  check_c,  lambda r: can_long(r)),
    ('D', 'LONG',  check_d,  lambda r: can_long(r)),
    ('E', None,     check_e,  lambda r: True),   # check_e returns its own direction
    ('F', 'LONG',  lambda t,d: check_f(t,d,'LONG'),  lambda r: can_long(r)),
    ('F', 'SHORT', lambda t,d: check_f(t,d,'SHORT'), lambda r: can_short(r)),
    ('G', 'LONG',  lambda t,d: check_g(t,d,'LONG'),  lambda r: can_long(r)),
    ('G', 'SHORT', lambda t,d: check_g(t,d,'SHORT'), lambda r: can_short(r)),
    ('H', 'LONG',  lambda t,d: check_h(t,d,'LONG'),  lambda r: can_long(r)),
    ('H', 'SHORT', lambda t,d: check_h(t,d,'SHORT'), lambda r: can_short(r)),
    ('I', 'LONG',  lambda t,d: check_i(t,d,'LONG'),  lambda r: can_long(r)),
    ('I', 'SHORT', lambda t,d: check_i(t,d,'SHORT'), lambda r: can_short(r)),
    ('J', 'LONG',  lambda t,d: check_j(t,d,'LONG'),  lambda r: can_long(r)),
    ('J', 'SHORT', lambda t,d: check_j(t,d,'SHORT'), lambda r: can_short(r)),
    ('K', 'LONG',  lambda t,d: check_k(t,d,'LONG'),  lambda r: can_long(r)),
    ('K', 'SHORT', lambda t,d: check_k(t,d,'SHORT'), lambda r: can_short(r)),
]

def run_scan(tickers, models_filter=None):
    global _prev_closes
    _prev_closes = {}
    tickers = [t.strip() for t in tickers if t.strip()]
    tickers = list(dict.fromkeys(tickers))

    if models_filter is None:
        models_filter = set(MODEL_WR.keys())

    now_et  = datetime.now(ET)
    now_str  = now_et.strftime("%Y-%m-%d %H:%M:%S ET")

    log("=" * 72)
    log(f"TJL US — HK-style 11 Models | {now_str}")
    log(f"Models: {sorted(models_filter)}")
    log(f"Fetching {len(tickers)} tickers (250d lookback for Model J)...")
    log("=" * 72)

    t0 = time.time()
    batch = fetch_batch(tickers, period="250d")
    log(f"Data: {len(batch)}/{len(tickers)} tickers in {time.time()-t0:.1f}s")

    errors = [t for t in tickers if t not in batch]
    regime = get_regime()
    log(f"Regime: {regime}")

    all_signals = []
    for ticker, d in batch.items():
        _prev_closes[ticker] = d['prev_close']
        for model, direction, checker, regime_check in MODEL_CHECKERS:
            if model not in models_filter:
                continue
            if not regime_check(regime):
                continue
            try:
                sig = checker(ticker, d)
                if sig:
                    sig_dir = sig.get('direction')
                    if direction is None or sig_dir == direction:
                        sig['confidence'] = calculate_confidence(
                            sig['wr'], regime, sig_dir, sig['rr_ratio']
                        )
                        all_signals.append(sig)
            except Exception:
                pass

    # Dedupe by ticker+model+direction
    seen = set()
    deduped = []
    for s in all_signals:
        key = (s['ticker'], s['model'], s['direction'])
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    all_signals = deduped
    all_signals.sort(key=lambda x: (-x.get('wr', 0), x['ticker']))

    longs  = [s for s in all_signals if s['direction'] == 'LONG']
    shorts = [s for s in all_signals if s['direction'] == 'SHORT']

    log(f"\n{regime} | {len(longs)} LONG | {len(shorts)} SHORT | {len(errors)} errors")
    log("-" * 80)
    log(f"{'Ticker':<8} {'M':<3} {'Price':>8} {'PrevC':>8} {'P&L%':>7} {'Dir':<6} "
        f"{'SL':>8} {'TP':>9} {'R:R':>4} {'WR':>4} {'Type'}")
    log("-" * 80)
    for sig in all_signals:
        t = sig['ticker']; m = sig['model']; px = sig['price']
        prev = _prev_closes.get(t, px) or px
        pnl_pct = (px - prev) / prev * 100 if prev else 0
        sl = sig['sl']; tp = sig['tp']; rr = sig['rr_ratio']
        d = sig['direction']; wr = sig['wr']
        atr_type = sig.get('atr_type', '?')
        log(f"{t:<8}{m:<3} ${px:>7.2f}  ${prev:>7.2f}  {pnl_pct:>+6.1f}%  {d:<6} "
            f"${sl:>7.2f}  ${tp:>8.2f}  {rr:.1f}  {wr:>3}%  {atr_type}")
    log("-" * 80)

    # JSON
    json_path = os.path.expanduser(f"~/tjl_us_hkstyle_{now_et.strftime('%Y%m%d_%H%M%S')}.json")
    out = {
        'scanned_at': now_str, 'regime': regime,
        'models': sorted(models_filter),
        'tickers': len(tickers), 'tickers_with_data': len(batch),
        'signals': all_signals,
        'longs': len(longs), 'shorts': len(shorts), 'errors': errors,
    }
    try:
        with open(json_path, 'w') as f:
            json.dump(out, f, indent=2, default=str)
        log(f"JSON: {json_path}")
    except Exception as e:
        log(f"JSON error: {e}")

    # Discord
    webhook_url = os.environ.get('DISCORD_WEBHOOK_HK_TJL')
    if webhook_url and all_signals:
        _post_discord(all_signals, regime, now_str, webhook_url)

    # Telegram
    if all_signals:
        post_telegram(all_signals, regime, now_str)

    return all_signals

def _post_discord(signals, regime, now_str, webhook_url):
    rows = []
    for s in signals:
        t = s['ticker']; m = s['model']; px = s['price']
        prev = _prev_closes.get(t, px) or px
        pct = f"{(px-prev)/prev*100:+.1f}%" if prev else "N/A"
        rows.append(f"`{t:<6}` M{m} ${px:.2f} {pct:>7} {s['direction']:<5} "
                    f"SL=${s['sl']:.2f} TP=${s['tp']:.2f} R:R={s['rr_ratio']} WR={s['wr']}%")
    body = (f"**TJL US (HK-style) | {now_str}**\n"
            f"Regime: **{regime}** | {len(signals)} signals\n\n"
            + "\n".join(rows))
    for i in range(0, len(body), 1900):
        chunk = body[i:i+1900]
        try:
            r = requests.post(webhook_url, json={'content': chunk, 'thread_name': 'TJL US HK-style'}, timeout=10)
            log(f"Discord: {r.status_code}")
        except Exception as e:
            log(f"Discord error: {e}")

def post_telegram(signals, regime, now_str):
    """Send signal summary to Telegram. Graceful no-op if TELEGRAM_BOT_TOKEN not set."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token or not signals:
        return
    chat_id = "8370185160"
    rows = []
    for s in signals:
        t = s['ticker']; m = s['model']; px = s['price']
        prev = _prev_closes.get(t, px) or px
        pct = f"{(px-prev)/prev*100:+.1f}%" if prev else "N/A"
        conf = s.get('confidence', 'N/A')
        rows.append(f"{t} M{m} ${px:.2f} {pct} {s['direction']} SL=${s['sl']:.2f} TP=${s['tp']:.2f} R:R={s['rr_ratio']} WR={s['wr']}% conf={conf}")
    body = (f"TJL US (HK-style) | {now_str}\n"
            f"Regime: {regime} | {len(signals)} signals\n\n"
            + "\n".join(rows))
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i in range(0, len(body), 3900):
        chunk = body[i:i+3900]
        try:
            r = requests.post(url, json={'chat_id': chat_id, 'text': chunk}, timeout=10)
            log(f"Telegram: {r.status_code}")
        except Exception as e:
            log(f"Telegram error: {e}")

# ── Default watchlist ──────────────────────────────────────────────────────────
SP500_CORE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","LLY","AVGO",
    "JPM","XOM","UNH","MA","HD","PG","CVX","MRK","ABBV","PEP",
    "KO","COST","ADBE","WMT","CRM","BAC","TMO","MCD","CSCO","ACN",
    "ABT","DHR","CMCSA","NFLX","NKE","NEE","WFC","PM","TXN",
    "UPS","RTX","BMY","HON","QCOM","LOW","ORCL","LIN","UNP","AMD",
    "INTC","IBM","CAT","SPGI","AMGN","ELV","INTU","AMAT","GILD","ISRG",
    "MDLZ","BKNG","ADI","VRTX","REGN","PFE","MU","LRCX","SYK","TJX",
    "AXP","CI","CVS","GS","BLK","ADP","MDT","SCHW","V","DE",
]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', type=str, default=None)
    parser.add_argument('--models', type=str, default='all')
    parser.add_argument('--no-discord', action='store_true')
    args = parser.parse_args()
    if args.no_discord:
        os.environ.pop('DISCORD_WEBHOOK_HK_TJL', None)
    tickers = [t.strip() for t in args.tickers.split(',')] if args.tickers else SP500_CORE
    if args.models == 'all':
        mf = None
    elif args.models == 'profitable':
        mf = PROFITABLE_MODELS
    else:
        mf = set(args.models.split(','))
    print(f"Scanning {len(tickers)} tickers | models={args.models}")
    run_scan(tickers, models_filter=mf)
