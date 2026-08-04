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
        highs, lows, closes = get_daily_bars(ticker, count=80)
        if highs is None:
            debug_info.append(f"{ticker}: no daily bars")
            continue

        # Get live price
        quote = get_live_price(ticker)
        if quote is None:
            debug_info.append(f"{ticker}: no live price")
            continue

        price      = quote['price']
        day_high   = float(quote.get('day_high')) if quote.get('day_high') else None
        day_low    = float(quote.get('day_low'))  if quote.get('day_low')  else None

        # Prior day high/low = yesterday's OHLC bar (index -2, since -1 is today so far)
        prev_day_high = float(highs[-2]) if len(highs) >= 2 and not np.isnan(highs[-2]) else None
        prev_day_low  = float(lows[-2])  if len(lows)  >= 2 and not np.isnan(lows[-2])  else None

        # Premarket high and low (04:00–09:30 ET)
        premarket_high = get_premarket_high(ticker) or 0
        premarket_low  = get_premarket_low(ticker)  or 0

        # ── LONG check (suppressed in BEARISH regime) ────────────────────────
        if regime != "BEARISH":
            result, err = check_tjl(
                ticker, name, price, day_high, prev_day_high,
                highs, lows, closes, premarket_high=premarket_high
            )
            if err:
                debug_info.append(err)
            else:
                long_signals.append(result)
        else:
            debug_info.append(f"{ticker}: LONG suppressed (BEARISH regime)")

        # ── SHORT check (suppressed in BULLISH regime) ───────────────────────
        if regime != "BULLISH":
            result, err = check_tjs(
                ticker, name, price, day_low, prev_day_low,
                highs, lows, closes, premarket_low=premarket_low
            )
            if err:
                debug_info.append(err)
            else:
                short_signals.append(result)
        else:
            debug_info.append(f"{ticker}: SHORT suppressed (BULLISH regime)")

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
