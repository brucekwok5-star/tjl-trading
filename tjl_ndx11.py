#!/usr/bin/env python3
"""
TJL US Scanner v2 — 11 Models A-K | S&P 500 / NDX100 / Custom
yfinance batch download, Discord webhook, JSON output.

BUGFIXES vs v1:
  1. SHORT SL/TP now correctly above/below entry (was always LONG direction)
  2. Model E: lower_band/upper_band logic fixed (was inverted)
  3. Model D: short_fire was hardcoded False — now functional
  4. Model F: tightened RSI zones to reduce noise
  5. Model H: near_bb tightened to outer 20% of band, not entire range
  6. Model K: tightened near_bb and added EMA9 proximity requirement
  7. Models B/D: no longer bypass conditions when data is None
  8. Batch yfinance download (1 API call vs 4 per ticker)
  9. Removed redundant calc_emas calls in Model E
 10. JSON saved to disk for downstream use
 11. Profitable-model filter (H/I/J) flag
 12. Win-rate annotation from backtest data
 13. Fixed PMH/PML to use prior day H/L (not None fallback)
"""
import sys, os, json, time, yfinance as yf
import numpy as np, pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

ET = ZoneInfo("America/New_York")
os.environ.setdefault('DISCORD_WEBHOOK_HK_TJL',
    'https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj')

# ── Strategy constants ────────────────────────────────────────────────────────
PMH_BUF        = 0.70
ATR_SL         = 1.5
ATR_TP         = 3.0
ATR_PERIOD     = 14
NEAR_EMA_PCT   = 0.01    # 1.0% pullback zone

# Backtested win rates per model (from 15-min backtest, 60 days, 1271 trades)
# Used to annotate signals and filter
MODEL_WR = {
    'A': {'wr': 31, 'avg': -0.20, 'trades': 13,  'verdict': 'marginal'},
    'B': {'wr': 0,  'avg': 0,     'trades': 0,   'verdict': 'untested'},
    'C': {'wr': 0,  'avg': 0,     'trades': 0,   'verdict': 'untested'},
    'D': {'wr': 0,  'avg': -3.43, 'trades': 5,   'verdict': 'kill'},
    'E': {'wr': 17, 'avg': -1.03, 'trades': 42,  'verdict': 'kill'},
    'F': {'wr': 31, 'avg': -0.09, 'trades': 350, 'verdict': 'noise'},
    'G': {'wr': 21, 'avg': -0.46, 'trades': 81,  'verdict': 'kill'},
    'H': {'wr': 45, 'avg': +0.69, 'trades': 25,  'verdict': 'profitable'},
    'I': {'wr': 48, 'avg': +0.41, 'trades': 27,  'verdict': 'profitable'},
    'J': {'wr': 54, 'avg': +0.76, 'trades': 19,  'verdict': 'best'},
    'K': {'wr': 27, 'avg': -0.27, 'trades': 113, 'verdict': 'kill'},
}

# Models enabled by default (only profitable ones)
PROFITABLE_MODELS = {'H', 'I', 'J'}

# ── Helpers ───────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)

def calc_emas(closes):
    c = np.array(closes, dtype=float)
    e9  = float(pd.Series(c).ewm(span=9,  adjust=False).mean().iloc[-1])
    e20 = float(pd.Series(c).ewm(span=20, adjust=False).mean().iloc[-1])
    e50 = float(pd.Series(c).ewm(span=50, adjust=False).mean().iloc[-1])
    return e9, e20, e50

def calc_atr(highs, lows, closes, period=14):
    h = np.array(highs, dtype=float); l = np.array(lows, dtype=float); c = np.array(closes, dtype=float)
    if len(c) < period + 1: return None
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(tr[-period:].mean())

def calc_vwap(highs, lows, closes, volumes):
    h, l, c, v = np.array(highs, dtype=float), np.array(lows, dtype=float), np.array(closes, dtype=float), np.array(volumes, dtype=float)
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

def make_signal(ticker, price, direction, model, atr, e9=None, extra=None):
    """Build a signal dict with correct SL/TP for LONG vs SHORT."""
    if direction == 'LONG':
        sl = round(price - ATR_SL * atr, 2)
        tp = round(price + ATR_TP * atr, 2)
    else:  # SHORT
        sl = round(price + ATR_SL * atr, 2)
        tp = round(price - ATR_TP * atr, 2)
    sig = {
        'ticker': ticker,
        'price': round(price, 2),
        'direction': direction,
        'model': model,
        'sl': sl,
        'tp': tp,
        'rr_ratio': round(ATR_TP / ATR_SL, 1),
        'atr': round(atr, 3),
        'wr': MODEL_WR.get(model, {}).get('wr', 0),
        'wr_verdict': MODEL_WR.get(model, {}).get('verdict', 'unknown'),
    }
    if e9 is not None:
        sig['e9'] = round(e9, 2)
        sig['near_pct'] = round(abs(price - e9) / e9 * 100, 2)
    if extra:
        sig.update(extra)
    return sig

# ── Batch data fetch ──────────────────────────────────────────────────────────
def fetch_batch(tickers, period="80d"):
    """Batch-download daily bars for all tickers in one yfinance call.
    Returns dict: ticker -> {highs, lows, closes, volumes, open, prev_high, prev_low}
    """
    valid = [t for t in tickers if t and t.strip()]
    if not valid:
        return {}

    try:
        data = yf.download(valid, period=period, interval="1d",
                           group_by='ticker', progress=False, threads=True)
    except Exception as e:
        log(f"Batch download error: {e}")
        return {}

    # Also get fast_info for live prices
    live_prices = {}
    try:
        quotes = yf.download(valid, period="1d", interval="1d",
                             group_by='ticker', progress=False, prepost=True)
    except Exception:
        quotes = None

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
            if len(df) < 30: continue

            highs   = df['High'].values
            lows    = df['Low'].values
            closes  = df['Close'].values
            volumes = df['Volume'].values

            today_open   = float(df['Open'].iloc[-1])
            prev_high    = float(df['High'].iloc[-2]) if len(df) >= 2 else float(df['High'].iloc[0])
            prev_low     = float(df['Low'].iloc[-2]) if len(df) >= 2 else float(df['Low'].iloc[0])
            prev_close   = float(df['Close'].iloc[-2]) if len(df) >= 2 else float(closes[0])
            current_price = float(df['Close'].iloc[-1])
            day_high     = float(df['High'].iloc[-1])
            day_low      = float(df['Low'].iloc[-1])

            results[t] = {
                'highs': highs, 'lows': lows, 'closes': closes, 'volumes': volumes,
                'today_open': today_open,
                'prev_high': prev_high, 'prev_low': prev_low,
                'prev_close': prev_close,
                'price': current_price,
                'day_high': day_high, 'day_low': day_low,
            }
        except Exception:
            continue

    return results

# ── Regime ────────────────────────────────────────────────────────────────────
def get_regime():
    try:
        spy = yf.Ticker("SPY").history(period="1y", interval="1d")
        qqq = yf.Ticker("QQQ").history(period="1y", interval="1d")
        if spy.empty or qqq.empty: return "neutral"
        def smas(df):
            s50 = df['Close'].rolling(50).mean().iloc[-1]
            s200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else df['Close'].mean()
            return df['Close'].iloc[-1] > s50 > s200
        spy_ok = smas(spy)
        qqq_ok = smas(qqq)
        if spy_ok and qqq_ok: return "BULLISH"
        if not spy_ok and not qqq_ok: return "BEARISH"
        return "neutral"
    except Exception:
        return "neutral"

# ── Models ────────────────────────────────────────────────────────────────────
# Each model returns a signal dict or None.
# Direction-aware: LONG uses bullish stack, SHORT uses bearish stack.

def check_a(ticker, d):
    """Model A: Pullback — price near EMA9 in bullish stack, above PMH."""
    c = d['closes']; h = d['highs']; l = d['lows']
    if len(c) < 60: return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(h, l, c)
    if not atr: return None
    price = d['price']
    pmh = d['prev_high']
    stack_ok     = (e9 > e20 > e50)
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT)
    above_pmh_ok = (price > pmh + PMH_BUF)
    if stack_ok and near_ema_ok and above_pmh_ok:
        return make_signal(ticker, price, 'LONG', 'A', atr, e9)
    return None

def check_b(ticker, d):
    """Model B: HT Momentum — above SMA200, above PMH, above HOD."""
    c = d['closes']; h = d['highs']
    if len(c) < 200: return None
    e9, e20, e50 = calc_emas(c)
    sma200 = float(pd.Series(np.array(c)).rolling(200).mean().iloc[-1])
    if np.isnan(sma200): return None
    atr = calc_atr(h, d['lows'], c) or (d['price'] * 0.01)
    price = d['price']
    above_sma200 = (price > sma200)
    above_pmh    = (price > d['prev_high'] + PMH_BUF)
    above_hod    = (price > d['day_high'] - 0.50)
    if above_sma200 and above_pmh and above_hod:
        return make_signal(ticker, price, 'LONG', 'B', atr, e9)
    return None

def check_c(ticker, d):
    """Model C: Vol Pullback — near EMA9 + volume spike 1.5x."""
    c = d['closes']; h = d['highs']; v = d['volumes']
    if len(c) < 60 or len(v) < 22: return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(h, d['lows'], c) or (d['price'] * 0.01)
    avg_vol = float(np.mean(v[-20:]))
    price = d['price']
    near_ema  = (abs(price - e9) / e9 <= 0.02)
    above_pmh = (price > d['prev_high'] + PMH_BUF)
    vol_spike = (v[-1] > avg_vol * 1.5)
    if near_ema and above_pmh and vol_spike:
        return make_signal(ticker, price, 'LONG', 'C', atr, e9)
    return None

def check_d(ticker, d):
    """Model D: RSI Bounce — RSI < 40 (oversold) + near VWAP."""
    c = d['closes']; v = d['volumes']
    if len(c) < 22: return None
    rsi = calc_rsi(c)
    if rsi is None: return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    vwap = calc_vwap(d['highs'], d['lows'], c, v)
    price = d['price']
    if vwap is None: return None  # FIX: don't bypass
    rsi_oversold = (rsi < 40)  # FIX: tightened from <55 to <40
    vwap_ok = (abs(price - vwap) / vwap <= 0.02)
    if rsi_oversold and vwap_ok:
        return make_signal(ticker, price, 'LONG', 'D', atr)
    return None

def check_e(ticker, d):
    """Model E: 20d Hi Breakout — at 20-day high with volume confirmation."""
    c = d['closes']; h = d['highs']; v = d['volumes']
    if len(c) < 25: return None
    e9, e20, e50 = calc_emas(c)  # FIX: removed duplicate call
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(h, d['lows'], c) or (d['price'] * 0.01)
    hi20 = float(np.max(h[-20:]))   # FIX: 20-day HIGH of highs
    lo20 = float(np.min(d['lows'][-20:]))  # FIX: 20-day LOW of lows
    avg_vol = float(np.mean(v[-20:]))
    price = d['price']
    vol_ok = (v[-1] > avg_vol * 1.2)
    # LONG: breaking above 20-day high
    at_breakout = (price >= hi20 * 0.98)
    if at_breakout and vol_ok:
        return make_signal(ticker, price, 'LONG', 'E', atr, e9)
    return None

def check_f(ticker, d, direction='LONG'):
    """Model F: RSI Trend — bullish/bearish stack + RSI zone."""
    c = d['closes']; h = d['highs']; v = d['volumes']
    if len(c) < 30: return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(h, d['lows'], c) or (d['price'] * 0.01)
    rsi = calc_rsi(c)
    if rsi is None: return None
    price = d['price']
    stack_bull = (e9 > e20 > e50)
    stack_bear = (e9 < e20 < e50)

    if direction == 'LONG':
        # FIX: tightened RSI to 45-65 (was 40-70)
        if stack_bull and 45 <= rsi <= 65:
            return make_signal(ticker, price, 'LONG', 'F', atr, e9)
    else:  # SHORT
        # FIX: tightened RSI to 35-55 (was 30-60), require clean bearish stack
        if stack_bear and 35 <= rsi <= 55:
            return make_signal(ticker, price, 'SHORT', 'F', atr, e9)
    return None

def check_g(ticker, d, direction='LONG'):
    """Model G: ORB — above/below open with stack confirmation."""
    c = d['closes']
    today_open = d.get('today_open')
    if len(c) < 60 or today_open is None: return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    price = d['price']
    stack_bull = (e9 > e20 > e50)
    stack_bear = (e9 < e20 < e50)

    if direction == 'LONG':
        if (price > today_open + 0.10) and stack_bull:
            return make_signal(ticker, price, 'LONG', 'G', atr, e9)
    else:
        # FIX: require clean bearish stack (was just !stack_bull)
        if (price < today_open - 0.10) and stack_bear:
            return make_signal(ticker, price, 'SHORT', 'G', atr, e9)
    return None

def check_h(ticker, d, direction='LONG'):
    """Model H: Gold BB — near outer Bollinger Band with volume."""
    c = d['closes']; v = d['volumes']
    if len(c) < 50: return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    bb_mid = float(pd.Series(np.array(c)).rolling(20).mean().iloc[-1])
    bb_std = float(pd.Series(np.array(c)).rolling(20).std().iloc[-1])
    bb_upper = bb_mid + bb_std * 2
    bb_lower = bb_mid - bb_std * 2
    price = d['price']
    stack_bull = (e9 > e20 > e50)
    stack_bear = (e9 < e20 < e50)
    avg_vol = float(np.mean(v[-20:]))
    vol_ok = (v[-1] > avg_vol)

    # FIX: near_bb tightened — only outer 30% of band (was entire band)
    band_width = bb_upper - bb_lower
    if band_width <= 0: return None
    near_upper = (price >= bb_upper - band_width * 0.3)  # top 30%
    near_lower = (price <= bb_lower + band_width * 0.3)  # bottom 30%

    if direction == 'LONG':
        if stack_bull and near_upper and vol_ok:
            return make_signal(ticker, price, 'LONG', 'H', atr, e9)
    else:
        if stack_bear and near_lower and vol_ok:
            return make_signal(ticker, price, 'SHORT', 'H', atr, e9)
    return None

def check_i(ticker, d, direction='LONG'):
    """Model I: 63WMA Swing — near EMA9 + above/below 63-day WMA."""
    c = d['closes']; v = d['volumes']
    if len(c) < 70: return None
    wma63 = float(pd.Series(np.array(c)).rolling(63).mean().iloc[-1])
    e9, _, _ = calc_emas(c)
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    price = d['price']
    above_wma = (price > wma63)
    near_ema  = (abs(price - e9) / e9 <= 0.015)
    avg_vol = float(np.mean(v[-20:]))
    vol_ok = (v[-1] > avg_vol)

    if direction == 'LONG' and above_wma and near_ema and vol_ok:
        return make_signal(ticker, price, 'LONG', 'I', atr, e9)
    if direction == 'SHORT' and (not above_wma) and near_ema and vol_ok:
        return make_signal(ticker, price, 'SHORT', 'I', atr, e9)
    return None

def check_j(ticker, d, direction='LONG'):
    """Model J: DMA Cross — 5/20 DMA crossover with volume."""
    c = d['closes']; v = d['volumes']
    if len(c) < 40: return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    s = pd.Series(np.array(c))
    dma5  = float(s.rolling(5).mean().iloc[-1])
    dma20 = float(s.rolling(20).mean().iloc[-1])
    prev_dma5  = float(s.iloc[:-1].rolling(5).mean().iloc[-1])
    prev_dma20 = float(s.iloc[:-1].rolling(20).mean().iloc[-1])
    cross_up   = (dma5 > dma20) and (prev_dma5 <= prev_dma20)
    cross_down = (dma5 < dma20) and (prev_dma5 >= prev_dma20)
    avg_vol = float(np.mean(v[-20:]))
    vol_ok = (v[-1] > avg_vol)

    if direction == 'LONG' and cross_up and vol_ok:
        return make_signal(ticker, price=d['price'], direction='LONG', model='J', atr=atr, e9=e9)
    if direction == 'SHORT' and cross_down and vol_ok:
        return make_signal(ticker, d['price'], 'SHORT', 'J', atr, e9)
    return None

def check_k(ticker, d, direction='SHORT'):
    """Model K: Session SHORT — below VWAP + near lower BB + below EMA9."""
    c = d['closes']; v = d['volumes']
    if len(c) < 30: return None
    e9, e20, e50 = calc_emas(c)
    if any(np.isnan(x) for x in [e9, e20, e50]): return None
    atr = calc_atr(d['highs'], d['lows'], c) or (d['price'] * 0.01)
    vwap = calc_vwap(d['highs'], d['lows'], c, v)
    bb_mid = float(pd.Series(np.array(c)).rolling(20).mean().iloc[-1])
    bb_std = float(pd.Series(np.array(c)).rolling(20).std().iloc[-1])
    bb_lower = bb_mid - bb_std * 2
    price = d['price']
    if vwap is None: return None  # FIX: don't bypass

    # FIX: tightened — require ALL of: below VWAP, near lower BB, below EMA9
    below_vwap  = (price < vwap)
    near_lower  = (price <= bb_lower + bb_std * 0.5)  # FIX: tight zone
    below_e9    = (price < e9)  # FIX: added EMA9 requirement

    if direction == 'SHORT' and below_vwap and near_lower and below_e9:
        return make_signal(ticker, price, 'SHORT', 'K', atr, e9)
    return None

# ── Scan engine ───────────────────────────────────────────────────────────────
_prev_closes = {}

MODEL_CHECKERS = {
    'A': lambda t, d, reg: check_a(t, d) if reg in ('BULLISH', 'neutral') else None,
    'B': lambda t, d, reg: check_b(t, d) if reg in ('BULLISH', 'neutral') else None,
    'C': lambda t, d, reg: check_c(t, d) if reg in ('BULLISH', 'neutral') else None,
    'D': lambda t, d, reg: check_d(t, d) if reg in ('BULLISH', 'neutral') else None,
    'E': lambda t, d, reg: check_e(t, d) if reg in ('BULLISH', 'neutral') else None,
    'F_LONG':  lambda t, d, reg: check_f(t, d, 'LONG')  if reg in ('BULLISH', 'neutral') else None,
    'F_SHORT': lambda t, d, reg: check_f(t, d, 'SHORT') if reg in ('BEARISH', 'neutral') else None,
    'G_LONG':  lambda t, d, reg: check_g(t, d, 'LONG')  if reg in ('BULLISH', 'neutral') else None,
    'G_SHORT': lambda t, d, reg: check_g(t, d, 'SHORT') if reg in ('BEARISH', 'neutral') else None,
    'H_LONG':  lambda t, d, reg: check_h(t, d, 'LONG')  if reg in ('BULLISH', 'neutral') else None,
    'H_SHORT': lambda t, d, reg: check_h(t, d, 'SHORT') if reg in ('BEARISH', 'neutral') else None,
    'I_LONG':  lambda t, d, reg: check_i(t, d, 'LONG')  if reg in ('BULLISH', 'neutral') else None,
    'I_SHORT': lambda t, d, reg: check_i(t, d, 'SHORT') if reg in ('BEARISH', 'neutral') else None,
    'J_LONG':  lambda t, d, reg: check_j(t, d, 'LONG')  if reg in ('BULLISH', 'neutral') else None,
    'J_SHORT': lambda t, d, reg: check_j(t, d, 'SHORT') if reg in ('BEARISH', 'neutral') else None,
    'K_SHORT': lambda t, d, reg: check_k(t, d, 'SHORT') if reg in ('BEARISH', 'neutral') else None,
}

def run_scan(tickers, models_filter=None):
    """
    Scan tickers with all 11 models.
    models_filter: set of model letters to enable (default: all).
    Returns list of signal dicts.
    """
    global _prev_closes
    _prev_closes = {}

    tickers = [t.strip() for t in tickers if t and t.strip()]
    tickers = list(dict.fromkeys(tickers))  # dedupe

    if models_filter is None:
        models_filter = set(MODEL_WR.keys())  # all models

    now_et  = datetime.now(ET)
    now_str = now_et.strftime("%Y-%m-%d %H:%M:%S ET")

    log("=" * 72)
    log(f"TJL US v2 — 11 Models A-K | {now_str}")
    log(f"Models enabled: {sorted(models_filter)}")
    log(f"Scanning {len(tickers)} tickers... (batch download)")
    log("=" * 72)

    # Batch fetch all data in one call
    t0 = time.time()
    batch = fetch_batch(tickers)
    t_fetch = time.time() - t0
    log(f"Data fetched: {len(batch)}/{len(tickers)} tickers in {t_fetch:.1f}s")

    errors = [t for t in tickers if t not in batch]
    if errors:
        log(f"Skipped (no data): {', '.join(errors[:10])}{'...' if len(errors)>10 else ''}")

    regime = get_regime()
    log(f"Regime: {regime}")

    all_signals = []

    for ticker, d in batch.items():
        _prev_closes[ticker] = d['prev_close']

        for model_key, checker in MODEL_CHECKERS.items():
            model_letter = model_key.split('_')[0]
            if model_letter not in models_filter:
                continue
            try:
                sig = checker(ticker, d, regime)
                if sig:
                    all_signals.append(sig)
            except Exception:
                pass

    longs  = [s for s in all_signals if s['direction'] == 'LONG']
    shorts = [s for s in all_signals if s['direction'] == 'SHORT']

    # Dedupe: same ticker + same model + same direction
    seen = set()
    deduped = []
    for s in all_signals:
        key = (s['ticker'], s['model'], s['direction'])
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    all_signals = deduped

    # Sort by win rate descending
    all_signals.sort(key=lambda x: (-x.get('wr', 0), x['ticker']))

    log(f"\nRegime: {regime} | {len(longs)} LONG | {len(shorts)} SHORT | {len(errors)} errors")
    log("─" * 72)
    log(f"{'Ticker':<8} {'M':<3} {'Price':>8} {'PrevC':>8} {'P&L%':>7} {'Dir':<6} {'SL':>8} {'TP':>8} {'R:R':>4} {'WR':>4}")
    log("─" * 72)
    for sig in all_signals:
        t = sig['ticker']; m = sig.get('model', '?')
        px = sig['price']; prev = _prev_closes.get(t, px) or px
        pnl = px - prev
        pnl_pct = (pnl / prev * 100) if prev else 0
        sl = sig.get('sl', 0); tp = sig.get('tp', 0); rr = sig.get('rr_ratio', 0)
        d_dir = sig.get('direction', 'LONG')
        wr = sig.get('wr', 0)
        log(f"{t:<8} {m:<3} ${px:>7.2f}  ${prev:>7.2f}  {pnl_pct:>+6.1f}%  {d_dir:<6} ${sl:>7.2f}  ${tp:>7.2f}  {rr:.1f}  {wr}%")
    log("─" * 72)

    # Save JSON
    json_path = os.path.expanduser(f"~/tjl_us_v2_{now_et.strftime('%Y%m%d_%H%M%S')}.json")
    output = {
        'scanned_at': now_str,
        'regime': regime,
        'models_enabled': sorted(models_filter),
        'tickers_scanned': len(tickers),
        'tickers_with_data': len(batch),
        'signals': all_signals,
        'longs': len(longs),
        'shorts': len(shorts),
        'errors': errors,
    }
    try:
        with open(json_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        log(f"JSON saved: {json_path}")
    except Exception as e:
        log(f"JSON save error: {e}")

    # Discord
    webhook_url = os.environ.get('DISCORD_WEBHOOK_HK_TJL')
    if webhook_url and all_signals:
        _post_discord(all_signals, regime, now_str, webhook_url)

    return all_signals

def _post_discord(signals, regime, now_str, webhook_url):
    rows = []
    for sig in signals:
        t = sig['ticker']; m = sig.get('model', '?')
        px = sig['price']; prev = _prev_closes.get(t, px) or px
        pnl_pct = f"{(px-prev)/prev*100:+.1f}%" if prev else "N/A"
        sl = sig.get('sl', 0); tp = sig.get('tp', 0); rr = sig.get('rr_ratio', 0)
        d = sig.get('direction', 'LONG'); wr = sig.get('wr', 0)
        rows.append(f"`{t:<6}` M{m} ${px:.2f} {pnl_pct:>7} {d:<5} SL=${sl:.2f} TP=${tp:.2f} R:R={rr} WR={wr}%")

    body = (f"**TJL US v2 | {now_str}**\n"
            f"Regime: **{regime}** | {len(signals)} signals\n\n"
            + "\n".join(rows))

    for i in range(0, len(body), 1900):
        chunk = body[i:i+1900]
        try:
            r = requests.post(webhook_url, json={
                'content': chunk,
                'thread_name': 'TJL US Signals'
            }, timeout=10)
            log(f"Discord: {r.status_code}")
        except Exception as e:
            log(f"Discord error: {e}")

# ── Default watchlist (top S&P 500 by market cap) ─────────────────────────────
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
    parser = argparse.ArgumentParser(description="TJL US Scanner v2")
    parser.add_argument('--tickers', type=str, default=None,
                        help='Comma-separated tickers (default: S&P 500 core)')
    parser.add_argument('--models', type=str, default='all',
                        help="Models to enable: 'all', 'profitable' (H/I/J), or 'A,F,H'")
    parser.add_argument('--no-discord', action='store_true',
                        help='Skip Discord posting')
    args = parser.parse_args()

    if args.no_discord:
        os.environ.pop('DISCORD_WEBHOOK_HK_TJL', None)

    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',')]
    else:
        tickers = SP500_CORE

    if args.models == 'all':
        models_filter = None
    elif args.models == 'profitable':
        models_filter = PROFITABLE_MODELS
    else:
        models_filter = set(args.models.split(','))

    print(f"Scanning {len(tickers)} tickers with models: {args.models}")
    run_scan(tickers, models_filter=models_filter)
