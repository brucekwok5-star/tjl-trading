#!/usr/bin/env python3
"""
TJL US Scanner — tjl_models unified library
=============================================
Scans US stocks using unified model functions from tjl_models.py.

Models A-K via tjl_models: check_model_a through check_model_k
Data: yfinance batch download
Discord webhook on completion
"""
import sys, os, json, time
import numpy as np
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

ET = ZoneInfo("America/New_York")
os.environ.setdefault('DISCORD_WEBHOOK_HK_TJL',
    'https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj')

# ── Backtest win-rate annotations (from 15-min backtest, 60 days, 1271 trades) ──
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
PROFITABLE_MODELS = {'H', 'I', 'J'}

# ── Unified model library ────────────────────────────────────────────────────────
from tjl_models import (
    check_model_a, check_model_b, check_model_c, check_model_d,
    check_model_e, check_model_f, check_model_g, check_model_h,
    check_model_i, check_model_j, check_model_k,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)


def _annotate(sig):
    """Add win-rate annotation from MODEL_WR."""
    m = sig.get('model', '?')
    w = MODEL_WR.get(m, {})
    sig['wr'] = w.get('wr', 0)
    sig['wr_verdict'] = w.get('verdict', 'unknown')
    return sig


# ── Batch data fetch ────────────────────────────────────────────────────────────

def fetch_batch(tickers, period="80d"):
    """Batch-download daily bars for all tickers in one yfinance call."""
    valid = [t for t in tickers if t and t.strip()]
    if not valid:
        return {}
    try:
        data = __import__('yfinance').download(
            valid, period=period, interval="1d",
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

            highs   = df['High'].values
            lows    = df['Low'].values
            closes  = df['Close'].values
            volumes = df['Volume'].values

            results[t] = {
                'highs':      highs,
                'lows':       lows,
                'closes':     closes,
                'volumes':    volumes,
                'today_open': float(df['Open'].iloc[-1]),
                'prev_high':  float(df['High'].iloc[-2]) if len(df) >= 2 else float(highs[0]),
                'prev_low':   float(df['Low'].iloc[-2])  if len(df) >= 2 else float(lows[0]),
                'prev_close': float(df['Close'].iloc[-2]) if len(df) >= 2 else float(closes[0]),
                'price':      float(df['Close'].iloc[-1]),
                'day_high':   float(df['High'].iloc[-1]),
                'day_low':    float(df['Low'].iloc[-1]),
            }
        except Exception:
            continue
    return results


# ── Regime ─────────────────────────────────────────────────────────────────────

def get_regime():
    try:
        yf = __import__('yfinance')
        spy = yf.Ticker("SPY").history(period="1y", interval="1d")
        qqq = yf.Ticker("QQQ").history(period="1y", interval="1d")
        if spy.empty or qqq.empty:
            return "neutral"
        def smas(df):
            s50 = df['Close'].rolling(50).mean().iloc[-1]
            s200 = (df['Close'].rolling(200).mean().iloc[-1]
                    if len(df) >= 200 else df['Close'].mean())
            return df['Close'].iloc[-1] > s50 > s200
        spy_ok = smas(spy)
        qqq_ok = smas(qqq)
        if spy_ok and qqq_ok: return "BULLISH"
        if not spy_ok and not qqq_ok: return "BEARISH"
        return "neutral"
    except Exception:
        return "neutral"


# ── Model dispatch (calls unified tjl_models functions) ─────────────────────────

def _run_model(model_key, ticker, d, regime):
    """Call the appropriate tjl_models function. Returns annotated signal or None."""
    price  = d['price']
    highs  = d['highs']
    lows   = d['lows']
    closes = d['closes']
    vols   = d['volumes']
    regime_filter = {
        'A':  ('BULLISH', 'neutral'), 'B':  ('BULLISH', 'neutral'),
        'C':  ('BULLISH', 'neutral'), 'D':  ('BULLISH', 'neutral'),
        'E':  ('BULLISH', 'neutral'), 'F_LONG':  ('BULLISH', 'neutral'),
        'F_SHORT': ('BEARISH', 'neutral'),
        'G_LONG':  ('BULLISH', 'neutral'),
        'G_SHORT': ('BEARISH', 'neutral'),
        'H_LONG':  ('BULLISH', 'neutral'),
        'H_SHORT': ('BEARISH', 'neutral'),
        'I_LONG':  ('BULLISH', 'neutral'),
        'I_SHORT': ('BEARISH', 'neutral'),
        'J_LONG':  ('BULLISH', 'neutral'),
        'J_SHORT': ('BEARISH', 'neutral'),
        'K_SHORT': ('BEARISH', 'neutral'),
    }
    if regime not in regime_filter.get(model_key, ()):
        return None

    try:
        sig = None
        if model_key == 'A':
            sig = check_model_a(ticker, price, highs, lows, closes, vols,
                                pmh_src='prev_day', prev_high=d['prev_high'],
                                prev_low=d['prev_low'])
        elif model_key == 'B':
            sig = check_model_b(ticker, price, highs, lows, closes, vols,
                                pmh_src='prev_day', prev_high=d['prev_high'],
                                prev_low=d['prev_low'], sma200=None,
                                day_high=d['day_high'])
        elif model_key == 'C':
            sig = check_model_c(ticker, price, highs, lows, closes, vols,
                                pmh_src='prev_day', prev_high=d['prev_high'],
                                prev_low=d['prev_low'])
        elif model_key == 'D':
            sig = check_model_d(ticker, price, highs, lows, closes, vols,
                                pmh_src='prev_day', prev_high=d['prev_high'],
                                prev_low=d['prev_low'])
        elif model_key == 'E':
            sig = check_model_e(ticker, price, highs, lows, closes, vols,
                                pmh_src='prev_day', prev_high=d['prev_high'],
                                prev_low=d['prev_low'])
        elif model_key == 'F_LONG':
            sig = check_model_f(ticker, price, highs, lows, closes, vols, 'LONG')
        elif model_key == 'F_SHORT':
            sig = check_model_f(ticker, price, highs, lows, closes, vols, 'SHORT')
        elif model_key == 'G_LONG':
            sig = check_model_g(ticker, price, highs, lows, closes, vols,
                                'LONG', today_open=d['today_open'])
        elif model_key == 'G_SHORT':
            sig = check_model_g(ticker, price, highs, lows, closes, vols,
                                'SHORT', today_open=d['today_open'])
        elif model_key == 'H_LONG':
            sig = check_model_h(ticker, price, highs, lows, closes, vols, 'LONG')
        elif model_key == 'H_SHORT':
            sig = check_model_h(ticker, price, highs, lows, closes, vols, 'SHORT')
        elif model_key == 'I_LONG':
            sig = check_model_i(ticker, price, highs, lows, closes, vols, 'LONG')
        elif model_key == 'I_SHORT':
            sig = check_model_i(ticker, price, highs, lows, closes, vols, 'SHORT')
        elif model_key == 'J_LONG':
            sig = check_model_j(ticker, price, highs, lows, closes, vols, 'LONG')
        elif model_key == 'J_SHORT':
            sig = check_model_j(ticker, price, highs, lows, closes, vols, 'SHORT')
        elif model_key == 'K_SHORT':
            sig = check_model_k(ticker, price, highs, lows, closes, vols, 'SHORT')
        if sig:
            return _annotate(sig)
    except Exception:
        pass
    return None


# ── Model keys enabled per model letter ────────────────────────────────────────

ALL_MODEL_KEYS = [
    'A', 'B', 'C', 'D', 'E',
    'F_LONG', 'F_SHORT',
    'G_LONG', 'G_SHORT',
    'H_LONG', 'H_SHORT',
    'I_LONG', 'I_SHORT',
    'J_LONG', 'J_SHORT',
    'K_SHORT',
]


# ── Scan engine ────────────────────────────────────────────────────────────────

_prev_closes = {}


def run_scan(tickers, models_filter=None):
    """
    Scan tickers with all 11 models (A-K) from the unified tjl_models library.
    models_filter: set of model LETTERS to enable (e.g. {'H','I','J'}).
    """
    global _prev_closes
    _prev_closes = {}
    tickers = [t.strip() for t in tickers if t and t.strip()]
    tickers = list(dict.fromkeys(tickers))

    now_et  = datetime.now(ET)
    now_str = now_et.strftime("%Y-%m-%d %H:%M:%S ET")

    log("=" * 72)
    log(f"TJL US (tjl_models) | {now_str}")
    log(f"Scanning {len(tickers)} tickers...")
    log("=" * 72)

    t0 = time.time()
    batch = fetch_batch(tickers)
    log(f"Data fetched: {len(batch)}/{len(tickers)} in {time.time()-t0:.1f}s")

    errors = [t for t in tickers if t not in batch]
    if errors:
        log(f"Skipped: {', '.join(errors[:10])}{'...' if len(errors) > 10 else ''}")

    regime = get_regime()
    log(f"Regime: {regime}")

    all_signals = []
    for ticker, d in batch.items():
        _prev_closes[ticker] = d['prev_close']
        for mk in ALL_MODEL_KEYS:
            model_letter = mk.split('_')[0]
            if models_filter and model_letter not in models_filter:
                continue
            sig = _run_model(mk, ticker, d, regime)
            if sig:
                all_signals.append(sig)

    # Dedupe: same ticker + model + direction
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

    json_path = os.path.expanduser(f"~/tjl_us_v3_{now_et.strftime('%Y%m%d_%H%M%S')}.json")
    output = {
        'scanned_at': now_str, 'regime': regime,
        'tickers_scanned': len(tickers), 'tickers_with_data': len(batch),
        'signals': all_signals, 'longs': len(longs), 'shorts': len(shorts),
        'errors': errors,
    }
    try:
        with open(json_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        log(f"JSON saved: {json_path}")
    except Exception as e:
        log(f"JSON save error: {e}")

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

    body = (f"**TJL US (v3 unified) | {now_str}**\n"
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


# ── Default watchlist (top S&P 500 by market cap) ──────────────────────────────

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
    parser = argparse.ArgumentParser(description="TJL US Scanner (tjl_models unified)")
    parser.add_argument('--tickers', type=str, default=None,
                        help='Comma-separated tickers (default: S&P 500 core)')
    parser.add_argument('--models', type=str, default='all',
                        help="'all', 'profitable' (H/I/J), or 'A,F,H'")
    parser.add_argument('--no-discord', action='store_true')
    args = parser.parse_args()

    if args.no_discord:
        os.environ.pop('DISCORD_WEBHOOK_HK_TJL', None)

    tickers = ([t.strip() for t in args.tickers.split(',')]
               if args.tickers else SP500_CORE)

    if args.models == 'all':
        models_filter = None
    elif args.models == 'profitable':
        models_filter = PROFITABLE_MODELS
    else:
        models_filter = set(args.models.split(','))

    print(f"Scanning {len(tickers)} tickers with models: {args.models}")
    run_scan(tickers, models_filter=models_filter)
