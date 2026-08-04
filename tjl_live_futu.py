#!/usr/bin/env python3
"""
TJL Live Scanner — Futu OpenD Real-Time Data
============================================
Subscribes to HK stocks via Futu OpenD, calculates EMA stack on daily bars,
and checks live TJL entry conditions every N seconds.

TJL Entry Conditions:
  1. EMA9  > EMA20 > EMA50   (bullish stack)
  2. Price within 0.2% of EMA9 (pullback zone)
  3. Price > PMH + buffer    (above premarket/high of day)

Exit: SL = price - 1.5*ATR | TP = price + 3.0*ATR

Usage:
  python3 tjl_live_futu.py                   # scan once
  python3 tjl_live_futu.py --continuous     # loop every 30s
  python3 tjl_live_futu.py --continuous --interval 60

Environment:
  DISCORD_WEBHOOK_HK_TJL — Discord webhook URL. If set, posts results.
"""
import futu as ft
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
ATR_SL       = 1.5
ATR_TP       = 3.0
ATR_PERIOD   = 14
NEAR_EMA_PCT = 0.002   # 0.2% — original strict spec
SCAN_INTERVAL = 30     # seconds between scans in continuous mode

WATCHLIST = [
    ("00700 Tencent",  "HK.00700"),
    ("09618 JD.com",   "HK.09618"),
    ("09988 Alipay",   "HK.09988"),
    ("03690 Meituan",  "HK.03690"),
    ("09926 KE",       "HK.09926"),
    ("09961 Kuaishou", "HK.09961"),
    ("02513",          "HK.02513"),
    ("07709",          "HK.07709"),
    ("07747",          "HK.07747"),
    ("03896",          "HK.03896"),
    ("06082",          "HK.06082"),
    ("06166",          "HK.06166"),
    ("03317",          "HK.03317"),
    ("02476",          "HK.02476"),
    ("09903",          "HK.09903"),
    ("01787",          "HK.01787"),
    ("01877",          "HK.01877"),
    ("01810",          "HK.01810"),
    ("01211 BYD",      "HK.01211"),
    ("02318 PingAn",   "HK.02318"),
    ("09939",          "HK.09939"),
    ("00939",          "HK.00939"),
    ("00941",          "HK.00941"),
    ("00981",          "HK.00981"),
    ("01024",          "HK.01024"),
    ("01299 AIA",      "HK.01299"),
    ("01347",          "HK.01347"),
    ("01378",          "HK.01378"),
    ("02259 PopMart",  "HK.02259"),
    ("02269",          "HK.02269"),
    ("02899",          "HK.02899"),
    ("03308",          "HK.03308"),
    ("02800 HangSeng", "HK.02800"),
    ("02828",          "HK.02828"),
    ("03033",          "HK.03033"),
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
        return None, None, None
    kl = kl.sort_values('time_key').reset_index(drop=True)
    return kl['high'].values, kl['low'].values, kl['close'].values


def get_live_quotes(ctx, codes):
    for code in codes:
        ctx.subscribe([code], [ft.SubType.QUOTE])
    time.sleep(1.5)
    ret, df = ctx.get_stock_quote(codes)
    if ret != 0 or df is None or df.empty:
        return {}
    result = {}
    for _, row in df.iterrows():
        code = row['code']
        result[code] = {
            'price':      float(row['last_price']),
            'prev_close': float(row['prev_close_price']),
            'high_today': float(row['high_price']),
            'low_today':  float(row['low_price']),
            'volume':     int(row['volume']),
        }
    return result


def check_tjl(price, highs, lows, closes, today_high):
    if len(closes) < 60:
        return None
    e9, e20, e50 = calc_emas(closes)
    if any(np.isnan(x) for x in [e9, e20, e50]):
        return None
    atr = calc_atr(highs, lows, closes)
    if atr is None or np.isnan(atr):
        return None
    pmh = today_high if today_high else price
    stack_ok    = (e9 > e20 > e50)
    near_ema_ok = (abs(price - e9) / e9 <= NEAR_EMA_PCT)
    above_pmh_ok = (price > pmh + PMH_BUF)
    sl = price - ATR_SL * atr
    tp = price + ATR_TP * atr
    return {
        'price':       round(price, 2),
        'e9':          round(e9, 2),
        'e20':         round(e20, 2),
        'e50':         round(e50, 2),
        'atr':         round(atr, 3),
        'pmh':         round(pmh, 2),
        'sl':          round(sl, 2),
        'tp':          round(tp, 2),
        'rr_ratio':    round((ATR_TP * atr) / (ATR_SL * atr), 2),
        'stack_ok':    stack_ok,
        'near_ema_ok': near_ema_ok,
        'above_pmh_ok': above_pmh_ok,
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
            lines.append(
                f"{s['name']:<18} {s['price']:>8.2f} {s['e9']:>8.2f} {s['e20']:>8.2f} "
                f"{s['e50']:>8.2f} {s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}"
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

    # Step 1: Live quotes
    log(f"Fetching live quotes ({len(ALL_CODES)} tickers)...")
    quotes = get_live_quotes(ctx, ALL_CODES)
    log(f"Got live data for {len(quotes)} tickers")

    # Step 2: Check TJL for each ticker
    signals = []
    debug_info = []

    for name, code in WATCHLIST:
        if code not in quotes:
            debug_info.append(f"{code}: no live quote")
            continue

        q = quotes[code]
        price = q['price']
        today_high = q['high_today']

        highs, lows, closes = get_daily_bars(ctx, code, count=80)
        if highs is None:
            debug_info.append(f"{code}: no daily bars")
            continue

        result = check_tjl(price, highs, lows, closes, today_high)
        if not result:
            debug_info.append(f"{code}: calc error")
            continue

        result['name'] = name
        all_ok = result['stack_ok'] and result['near_ema_ok'] and result['above_pmh_ok']
        if all_ok:
            signals.append(result)
        else:
            reasons = []
            if not result['stack_ok']:     reasons.append("!stack")
            if not result['near_ema_ok']:  reasons.append("!near9")
            if not result['above_pmh_ok']: reasons.append("!abovePMH")
            debug_info.append(f"{code}: {' '.join(reasons)}")

    ctx.close()

    # Step 3: Print results
    if signals:
        log("")
        log("=" * 65)
        log("  🚨 TJL SIGNALS — LIVE")
        log("=" * 65)
        log(f"{'Ticker':<18} {'Price':>8} {'EMA9':>8} {'EMA20':>8} {'EMA50':>8} "
            f"{'ATR':>7} {'PMH':>8} {'SL':>8} {'TP':>8} {'R:R':>5}")
        log("-" * 100)
        for s in sorted(signals, key=lambda x: -x['rr_ratio']):
            log(f"{s['name']:<18} {s['price']:>8.2f} {s['e9']:>8.2f} {s['e20']:>8.2f} "
                f"{s['e50']:>8.2f} {s['atr']:>7.3f} {s['pmh']:>8.2f} "
                f"{s['sl']:>8.2f} {s['tp']:>8.2f} {s['rr_ratio']:>5.1f}")

        out_file = os.path.expanduser(f"~/tjl_live_signals_{today_str}.json")
        with open(out_file, "w") as f:
            json.dump({"scanned_at": now_str, "source": "Futu OpenD", "signals": signals}, f, indent=2)
        log(f"📁 Saved to {out_file}")
    else:
        log("")
        log("=" * 65)
        log("  ⏳ NO TJL SIGNALS — ALL CONDITIONS FAIL")
        log("=" * 65)

    log("")
    log("── Debug: Condition breakdown ──")
    for d in debug_info[:15]:
        log(f"  {d}")

    # Step 4: Post to Discord
    post_discord(signals, now_str)

    # Step 5: Optional Telegram notification
    if notify:
        notify_telegram({"scanned_at": now_str, "signals": signals})

    return signals


def main():
    parser = argparse.ArgumentParser(description="TJL Live Scanner — Futu OpenD")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL, help="Seconds between scans")
    parser.add_argument("--notify", action="store_true", help="Send results to Telegram")
    args = parser.parse_args()

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
