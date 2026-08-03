#!/usr/bin/env python3
"""
TJL Live Scanner — US Market via Yahoo Finance
==============================================
Scans US stocks every N seconds using yfinance real-time data,
calculates EMA stack on daily bars, and checks live TJL entry conditions.

TJL Entry Conditions:
  1. EMA9  > EMA20 > EMA50   (bullish stack)
  2. Price within 0.2% of EMA9 (pullback zone)
  3. Price > PMH + buffer    (prior day high or premarket high)

Exit: SL = price - 1.5*ATR | TP = price + 3.0*ATR

Usage:
  python3 tjl_live_us.py                   # scan once
  python3 tjl_live_us.py --continuous       # loop every 30s
  python3 tjl_live_us.py --continuous --interval 60

Environment:
  DISCORD_WEBHOOK_HK_TJL — Discord webhook URL. If set, posts results.
  US_TICKERS          — Optional comma-separated tickers (overrides default watchlist)
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

PMH_BUF      = 0.70    # $ buffer above PMH
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
    """Get daily OHLC bars from yfinance."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=f"{count}d", interval="1d")
        if hist.empty or len(hist) < 30:
            return None, None, None
        hist = hist.sort_index()
        return hist['High'].values, hist['Low'].values, hist['Close'].values
    except:
        return None, None, None


def get_live_price(ticker):
    """Get current price from yfinance (15min delay for non-premium)."""
    try:
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        price = info.get('regularMarketPrice') or info.get('previousClose')
        prev_close = info.get('previousClose')
        day_high = info.get('dayHigh')
        day_low = info.get('dayLow')
        if price is None:
            # fallback to history
            hist = tk.history(period="2d")
            if len(hist) >= 2:
                price = float(hist['Close'].iloc[-1])
                prev_close = float(hist['Close'].iloc[-2])
                day_high = float(hist['High'].iloc[-1])
                day_low = float(hist['Low'].iloc[-1])
            else:
                return None
        return {
            'price': float(price),
            'prev_close': float(prev_close) if prev_close else None,
            'day_high': float(day_high) if day_high else None,
            'day_low': float(day_low) if day_low else None,
        }
    except Exception as e:
        return None


def get_premarket_high(ticker):
    """Get premarket high (4AM–9:30AM ET today) via yfinance."""
    try:
        tk = yf.Ticker(ticker)
        # premarket data available in "Pre-Market" history
        # Use today's 1min data to calc premarket high
        today = date.today().strftime("%Y-%m-%d")
        # 1min bars for today - try last 100 1-min bars
        premarket = tk.history(start=today, interval="1m", auto_adjust=True, keepna=True)
        if premarket.empty:
            return None
        # premarket hours: 4:00 AM - 9:30 AM ET
        # Filter bars in that window
        et_idx = premarket.index.tz_convert(ET) if premarket.index.tz else premarket.index.tz_localize(ET)
        mask = (et_idx.hour >= 4) & ((et_idx.hour < 9) | ((et_idx.hour == 9) & (et_idx.minute <= 30)))
        if mask.sum() == 0:
            return None
        return float(premarket[mask]['High'].max())
    except:
        return None


def check_tjl(ticker, name, price, day_high, prev_day_high, highs, lows, closes):
    """Check all 3 TJL conditions. Returns signal dict or None."""
    if len(closes) < 60:
        return None, f"{ticker}: insufficient bars ({len(closes)})"

    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None, f"{ticker}: NaN in EMA"

    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None, f"{ticker}: ATR error"

    # PMH: use max of prior day high and today's premarket high
    pmh = prev_day_high or 0
    pmh = max(pmh, day_high) if day_high else pmh

    stack_ok     = (e9 > e20 > e50)
    near_ema_ok  = (abs(price - e9) / e9 <= NEAR_EMA_PCT)
    above_pmh_ok = (pmh > 0) and (price > pmh + PMH_BUF)

    sl = price - ATR_SL * atr
    tp = price + ATR_TP * atr
    rr = (ATR_TP * atr) / (ATR_SL * atr)

    result = {
        'ticker':    ticker,
        'name':      name,
        'price':     round(price, 2),
        'prev_close': round(float(closes[-1]), 2),
        'e9':        round(e9, 2),
        'e20':       round(e20, 2),
        'e50':       round(e50, 2),
        'atr':       round(atr, 3),
        'pmh':       round(pmh, 2),
        'sl':        round(sl, 2),
        'tp':        round(tp, 2),
        'rr_ratio':  round(rr, 2),
        'stack_ok':    stack_ok,
        'near_ema_ok': near_ema_ok,
        'above_pmh_ok': above_pmh_ok,
    }

    if not all([stack_ok, near_ema_ok, above_pmh_ok]):
        reasons = []
        if not stack_ok:     reasons.append("!stack")
        if not near_ema_ok:  reasons.append("!nearEMA")
        if not above_pmh_ok: reasons.append("!abovePMH")
        return None, f"{ticker}: {' '.join(reasons)}"

    return result, None


def post_discord(signals, now_str, regime):
    """Post TJL results to Discord webhook."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_HK_TJL", "").strip()
    if not webhook_url:
        log("[WARN] DISCORD_WEBHOOK_HK_TJL not set — skipping Discord")
        return

    lines = [
        f"**US TJL Live Scan** — {now_str}",
        f"Regime: **{regime}**",
        "",
    ]
    if signals:
        lines.append(f"🚨 **{len(signals)} US TJL SIGNAL(S)**")
        lines.append("")
        lines.append(f"{'Ticker':<12} {'Name':<16} {'Price':>8} {'EMA9':>8} {'EMA20':>8} {'EMA50':>8} "
                     f"{'SL':>8} {'TP':>8} {'R:R':>5}")
        lines.append("-" * 95)
        for s in sorted(signals, key=lambda x: -x['rr_ratio']):
            lines.append(
                f"{s['ticker']:<12} {s['name']:<16} {s['price']:>8.2f} {s['e9']:>8.2f} "
                f"{s['e20']:>8.2f} {s['e50']:>8.2f} {s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}"
            )
        lines.append("")
        lines.append(f"*PMH = prior day high | SL = price - 1.5×ATR | TP = price + 3.0×ATR*")
    else:
        lines.append("⏳ No TJL signals (all 3 conditions fail for all tickers)")

    content = "\n".join(lines)
    if len(content) > 1900:
        content = content[:1900] + "\n(truncated)"

    thread_name = f"US TJL Live {datetime.now(ET).strftime('%Y-%m-%d')}"
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


def run_scan():
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
        log("⚠️  BEARISH regime — TJL long signals suppressed")
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
    signals = []
    debug_info = []

    for ticker, name in watchlist:
        # Get daily bars first (needed for EMA + ATR)
        highs, lows, closes = get_daily_bars(ticker, count=80)
        if highs is None:
            debug_info.append(f"{ticker}: no daily bars")
            continue

        # Get live price
        quote = get_live_price(ticker)
        if quote is None:
            debug_info.append(f"{ticker}: no live price")
            continue

        price = quote['price']
        day_high = quote.get('day_high') or (float(closes[-1]) if len(closes) > 0 else None)
        prev_day_high = quote.get('prev_close')  # rough proxy for prior day high

        # Use yesterday's daily high as prior day high
        if len(highs) >= 2:
            prev_day_high = float(highs[-2])

        result, err = check_tjl(ticker, name, price, day_high, prev_day_high, highs, lows, closes)
        if err:
            debug_info.append(err)
        else:
            signals.append(result)

    # Step 4: Print results
    log("")
    if signals:
        log("=" * 70)
        log("  🚨 US TJL SIGNALS")
        log("=" * 70)
        log(f"{'Ticker':<12} {'Name':<16} {'Price':>8} {'EMA9':>8} {'EMA20':>8} "
            f"{'EMA50':>8} {'ATR':>7} {'PMH':>8} {'SL':>8} {'TP':>8} {'R:R':>5}")
        log("-" * 105)
        for s in sorted(signals, key=lambda x: -x['rr_ratio']):
            log(f"{s['ticker']:<12} {s['name']:<16} {s['price']:>8.2f} {s['e9']:>8.2f} "
                f"{s['e20']:>8.2f} {s['e50']:>8.2f} {s['atr']:>7.3f} {s['pmh']:>8.2f} "
                f"{s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}")
        log("")
        log(f"  ✅ {len(signals)} signal(s)")
    else:
        log("=" * 70)
        log("  ⏳ NO TJL SIGNALS — all conditions fail")
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
            "signals": signals,
            "debug": debug_info[:20],
        }, f, indent=2)
    log(f"📁 Saved to {out_file}")

    # Step 6: Discord
    post_discord(signals, now_str, regime)

    return signals


def main():
    parser = argparse.ArgumentParser(description="TJL Live Scanner — US Market (yfinance)")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL,
                        help=f"Seconds between scans (default {SCAN_INTERVAL})")
    args = parser.parse_args()

    log(f"TJL Live US Scanner | yfinance | Press Ctrl+C to stop")
    log(f"Watchlist: {len(DEFAULT_WATCHLIST)} tickers (override with US_TICKERS env)")
    log("")

    if args.continuous:
        log(f"CONTINUOUS mode — interval {args.interval}s")
        try:
            while True:
                run_scan()
                log(f"Sleeping {args.interval}s...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log("Stopped.")
    else:
        run_scan()


if __name__ == "__main__":
    main()
