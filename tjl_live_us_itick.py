#!/usr/bin/env python3
"""
TJL Live Scanner — US Market via iTick (real-time)
====================================================
Same TJL strategy as tjl_live_us.py (yfinance), but uses iTick REST API
for real-time prices and daily klines.

TJL Entry Conditions:
  1. EMA9  > EMA20 > EMA50   (bullish stack)
  2. Price within 0.2% of EMA9 (pullback zone)
  3. Price > PMH + buffer    (prior day high)

Exit: SL = price - 1.5*ATR | TP = price + 3.0*ATR

Usage:
  python3 tjl_live_us_itick.py                   # scan once
  python3 tjl_live_us_itick.py --continuous       # loop every 30s

Environment:
  ITICK_TOKEN         — required. iTick API token (from itick.org dashboard).
  US_TICKERS          — Optional comma-separated tickers (overrides default watchlist)

Rate limits (free plan):
  5 calls/min. The script uses 1 quote + 1 kline per ticker = 2 calls/ticker.
  With the default 45-ticker watchlist, one scan = 90 calls → ~18 min on free tier.
  For sub-minute scans, upgrade to Base tier (120 calls/min).
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import subprocess
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PMH_BUF      = 0.70
ATR_SL       = 1.5
ATR_TP       = 3.0
ATR_PERIOD   = 14
NEAR_EMA_PCT = 0.002
SCAN_INTERVAL = 30
ITICK_BASE   = "https://api.itick.io"   # NOTE: .io, not .org (docs are wrong)

# ── Default US Watchlist (same 45 as tjl_live_us.py) ───────────────────────────
DEFAULT_WATCHLIST = [
    ("NVDA",  "NVIDIA"),      ("TSLA",  "Tesla"),       ("AAPL",  "Apple"),
    ("MSFT",  "Microsoft"),   ("META",  "Meta"),        ("AMZN",  "Amazon"),
    ("GOOGL", "Google"),      ("AMD",   "AMD"),         ("INTC",  "Intel"),
    ("NFLX",  "Netflix"),     ("SPXL",  "S&P 500 3x"),  ("TQQQ",  "Nasdaq 100 3x"),
    ("SOXL",  "Semi 3x"),     ("QLD",   "QQQ 2x"),      ("UPRO",  "S&P 500 3x"),
    ("TSM",   "TSMC"),        ("SMCI",  "Super Micro"), ("PLTR",  "Palantir"),
    ("COIN",  "Coinbase"),    ("MSTR",  "MicroStrategy"),("RIVN",  "Rivian"),
    ("LCID",  "Lucid"),       ("NIO",   "NIO"),         ("XPEV",  "XPeng"),
    ("LI",    "Li Auto"),     ("BIDU",  "Baidu"),       ("BABA",  "Alibaba"),
    ("JD",    "JD.com"),      ("PDD",   "Pinduoduo"),   ("NTES",  "NetEase"),
    ("TME",   "Tencent Music"),("VNET", "VNet"),        ("BEKE",  "KE Holdings"),
    ("TAL",   "TAL Edu"),     ("EDU",   "New Oriental"),("BILI",  "Bilibili"),
    ("DDD",   "3D Systems"),  ("SMAR",  "SmartSheet"),  ("DOCU",  "DocuSign"),
    ("SNOW",  "Snowflake"),   ("CRWD",  "CrowdStrike"), ("ZS",    "Zscaler"),
    ("OKTA",  "Okta"),        ("PANW",  "Palo Alto"),   ("NET",   "Cloudflare"),
]


def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)


def itick_get(path, params, token, retries=3):
    """GET an iTick endpoint with retry + backoff on 429."""
    url = f"{ITICK_BASE}{path}"
    headers = {"accept": "application/json", "token": token}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code == 429:
                # Rate limited — back off with jitter
                wait = 15 + (attempt * 10) + (hash(path) % 5)
                log(f"  ⏸ rate-limited, sleeping {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            d = r.json()
            if d.get("code") not in (0, None):
                return None  # API-level error (e.g., bad symbol)
            return d.get("data")
        except requests.RequestException as e:
            if attempt == retries - 1:
                log(f"  ⚠ {path} failed: {e}")
                return None
            time.sleep(2 ** attempt)
    return None


def calc_emas(closes):
    s = pd.Series(closes)
    e9  = float(s.ewm(span=9,  adjust=False).mean().iloc[-1])
    e20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    e50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
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


def get_daily_klines(ticker, token, count=80):
    """Fetch daily OHLC bars from iTick. Returns (highs, lows, closes) or None."""
    data = itick_get("/stock/kline",
                     {"region": "US", "code": ticker, "kType": 8, "limit": count},
                     token)
    if not data:
        return None, None, None
    # iTick returns newest first; reverse for chronological order
    data = list(reversed(data))
    highs  = [float(b["h"]) for b in data]
    lows   = [float(b["l"]) for b in data]
    closes = [float(b["c"]) for b in data]
    return highs, lows, closes


def get_quote(ticker, token):
    """Fetch real-time quote. Returns dict with price, prev_close, day_high or None."""
    data = itick_get("/stock/quote",
                     {"region": "US", "code": ticker},
                     token)
    if not data:
        return None
    return {
        "price":      float(data.get("ld")) if data.get("ld") else None,
        "prev_close": float(data.get("p"))  if data.get("p")  else None,
        "day_high":   float(data.get("h"))  if data.get("h")  else None,
        "day_low":    float(data.get("l"))  if data.get("l")  else None,
        "change_pct": float(data.get("chp")) if data.get("chp") else None,
    }



def get_premarket_high_itick(ticker, token):
    """Get premarket high (04:00–09:30 ET today) via iTick 5-min klines."""
    # Use the existing itick_get helper which handles retries/backoff on 429.
    data = itick_get("/stock/kline",
                     {"region": "US", "code": ticker, "kType": 2, "limit": 200},
                     token)
    if not data:
        return 0
    now_et = datetime.now(ET)
    pmh = 0.0
    for bar in data:
        ts = int(bar["t"]) // 1000
        bar_et = datetime.fromtimestamp(ts, ET)
        if bar_et.date() != now_et.date():
            continue
        minutes = bar_et.hour * 60 + bar_et.minute
        if 4*60 <= minutes < 9*60 + 30:
            pmh = max(pmh, float(bar["h"]))
    return pmh


def check_tjl(ticker, name, price, day_high, prev_day_high, highs, lows, closes,
                 premarket_high=0):
    """Check all 3 TJL conditions. Returns (result_dict, error_str|None)."""
    if len(closes) < 60:
        return None, f"{ticker}: insufficient bars ({len(closes)})"

    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None, f"{ticker}: NaN in EMA"

    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None, f"{ticker}: ATR error"

    # PMH: max of prior day high and today's PREMARKET high (4am-9:30am ET).
    # Excluding regular-session high so above_pmh_ok can actually fire.
    # See SKILL.md "Known Issues / Strategy Logic".
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
        "ticker":    ticker,
        "name":      name,
        "price":     round(price, 2),
        "prev_close": round(float(closes[-1]), 2),
        "e9":        round(e9, 2),
        "e20":       round(e20, 2),
        "e50":       round(e50, 2),
        "atr":       round(atr, 3),
        "pmh":       round(pmh, 2),
        "sl":        round(sl, 2),
        "tp":        round(tp, 2),
        "rr_ratio":  round(rr, 2),
        "stack_ok":    stack_ok,
        "near_ema_ok": near_ema_ok,
        "above_pmh_ok": above_pmh_ok,
    }

    if not all([stack_ok, near_ema_ok, above_pmh_ok]):
        reasons = []
        if not stack_ok:     reasons.append("!stack")
        if not near_ema_ok:  reasons.append("!nearEMA")
        if not above_pmh_ok: reasons.append("!abovePMH")
        return None, f"{ticker}: {' '.join(reasons)}"

    return result, None



def notify_telegram(payload):
    """Send scan summary to Telegram via `hermes send`."""
    import subprocess
    regime_emoji = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(payload.get("regime", ""), "⚪")
    lines = [
        f"📊 *TJL Scan (iTick)* — {payload['scanned_at']}",
        f"Regime: {regime_emoji} *{payload.get('regime', 'UNKNOWN')}*",
        f"Signals: *{len(payload.get('signals', []))}*",
    ]
    if payload.get("signals"):
        lines += ["", "```", f"{'Ticker':<8} {'Price':>8} {'R:R':>5}", "-" * 30]
        for s in sorted(payload["signals"], key=lambda x: -x["rr_ratio"]):
            lines.append(f"{s['ticker']:<8} {s['price']:>8.2f} {s['rr_ratio']:>5.1f}")
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




def run_scan(token, notify=False):
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%Y-%m-%d %H:%M:%S ET")
    today_str = now_et.strftime("%Y-%m-%d")

    log("=" * 70)
    log("TJL Live Scanner — US Market (iTick real-time)")
    log(f"Time : {now_str}")
    log("=" * 70)

    # Build watchlist
    custom = os.environ.get("US_TICKERS", "").strip()
    if custom:
        watchlist = [(t, t) for t in custom.split(",")]
        log(f"Custom watchlist (US_TICKERS): {len(watchlist)} tickers")
    else:
        watchlist = DEFAULT_WATCHLIST
        log(f"Default watchlist: {len(watchlist)} tickers")

    # Regime check — iTick stocks API doesn't reliably return data for ETFs
    # (SPY/QQQ) or indices (SPX/NDX) on the free tier. So we use yfinance as
    # a fallback for the regime probe (cheap, fast, no rate limit).
    regime = "UNKNOWN"
    regime_source = "none"
    try:
        import yfinance as yf
        spy_df = yf.Ticker("SPY").history(period="2d")
        qqq_df = yf.Ticker("QQQ").history(period="2d")
        if len(spy_df) >= 2 and len(qqq_df) >= 2:
            spy_up = spy_df["Close"].iloc[-1] > spy_df["Close"].iloc[-2]
            qqq_up = qqq_df["Close"].iloc[-1] > qqq_df["Close"].iloc[-2]
            regime = "BULLISH" if (spy_up and qqq_up) else "BEARISH"
            regime_source = "yfinance (fallback — iTick ETFs/index unreliable)"
    except Exception as e:
        log(f"  ⚠ regime check via yfinance failed: {e}")
    log(f"Regime (SPY/QQQ): {regime}  (source: {regime_source})")
    log("")

    # Scan each ticker (sequential — iTick rate limits make parallelism fragile)
    signals = []
    debug_info = []
    for ticker, name in watchlist:
        highs, lows, closes = get_daily_klines(ticker, token, count=80)
        if highs is None:
            debug_info.append(f"{ticker}: no daily klines")
            continue

        quote = get_quote(ticker, token)
        if not quote or not quote.get("price"):
            debug_info.append(f"{ticker}: no live quote")
            continue

        price = quote["price"]
        day_high = quote.get("day_high") or (float(closes[-1]) if closes and len(closes) > 0 else None)
        prev_day_high = float(highs[-2]) if highs and len(highs) >= 2 else quote.get("prev_close")

        # Fetch premarket high (4-9:30 ET) for the PMH breakout check.
        # Without this, the strategy's third condition can never fire on live scans.
        premarket_high = get_premarket_high_itick(ticker, token)
        result, err = check_tjl(ticker, name, price, day_high, prev_day_high, highs, lows, closes,
                                 premarket_high=premarket_high)
        if err:
            debug_info.append(err)
        else:
            signals.append(result)

    # Print results
    log("")
    if signals:
        log("=" * 70)
        log("  🚨 US TJL SIGNALS (iTick real-time)")
        log("=" * 70)
        log(f"{'Ticker':<12} {'Name':<16} {'Price':>8} {'EMA9':>8} {'EMA20':>8} "
            f"{'EMA50':>8} {'ATR':>7} {'PMH':>8} {'SL':>8} {'TP':>8} {'R:R':>5}")
        log("-" * 105)
        for s in sorted(signals, key=lambda x: -x["rr_ratio"]):
            log(f"{s['ticker']:<12} {s['name']:<16} {s['price']:>8.2f} {s['e9']:>8.2f} "
                f"{s['e20']:>8.2f} {s['e50']:>8.2f} {s['atr']:>7.3f} {s['pmh']:>8.2f} "
                f"{s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}")
        log("")
        log(f"  ✅ {len(signals)} signal(s)")
    else:
        log("=" * 70)
        log("  ⏳ NO TJL SIGNALS — all conditions fail")
        log("=" * 70)

    if debug_info:
        log("")
        log("── Debug (condition fails) ──")
        for d in debug_info[:20]:
            log(f"  {d}")

    # Save JSON
    out_file = os.path.expanduser(f"~/tjl_live_us_itick_{today_str}.json")
    with open(out_file, "w") as f:
        json.dump({
            "scanned_at": now_str,
            "source":     "iTick (api.itick.io)",
            "regime":     regime,
            "signals":    signals,
            "debug":      debug_info[:20],
        }, f, indent=2)
    log(f"📁 Saved to {out_file}")

    if notify:
        try:
            with open(out_file) as f:
                payload = json.load(f)
            notify_telegram(payload)
        except Exception as e:
            log(f"⚠ notify failed: {e}")

    return signals


def main():
    parser = argparse.ArgumentParser(description="TJL Live Scanner — US Market (iTick)")
    parser.add_argument("--continuous", action="store_true", help="Loop every 30s")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL, help=f"Seconds between scans (default {SCAN_INTERVAL})")
    parser.add_argument("--notify", action="store_true", help="Send results to Telegram")
    args = parser.parse_args()

    token = os.environ.get("ITICK_TOKEN", "").strip()
    if not token:
        print("ERROR: ITICK_TOKEN not set. Add it to ~/.hermes/.env", file=sys.stderr)
        sys.exit(1)

    log(f"TJL Live US Scanner | iTick | Press Ctrl+C to stop")
    log(f"Watchlist: {len(DEFAULT_WATCHLIST)} tickers (override with US_TICKERS env)")
    log(f"Free plan: 5 calls/min — one scan = {len(DEFAULT_WATCHLIST)*2} calls (~18 min)")
    log("")

    if args.continuous:
        log(f"CONTINUOUS mode — interval {args.interval}s")
        try:
            while True:
                run_scan(token, notify=args.notify)
                log(f"Sleeping {args.interval}s...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log("Stopped.")
    else:
        run_scan(token, notify=args.notify)


if __name__ == "__main__":
    main()