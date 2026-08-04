#!/usr/bin/env python3
"""
TJL (Trend Join Long) Live Scanner — TradingView MCP variant
==============================================================
Implements HumbledTrader's "Trend Join Long" setup, sourced from:
  https://www.humbledtrader.com/blog/connect-claude-to-tradingview-mcp/

Data source: TradingView Desktop via the `tv` CLI (which wraps the tradingview-mcp
server, which drives TradingView via Chrome DevTools Protocol on port 9222).

ENTRY CRITERIA (per article):
  daily_breakout   = (curr_px > prev_daily_high) AND (prev_daily_close > sma200)
  intraday_breakout = (curr_px > pmh)             AND (curr_px > today_hod)
  Result = "PASS" if both true, else "fail_daily" or "fail_intraday"

PREREQ:
  - TradingView Desktop running with --remote-debugging-port=9222
  - An active chart tab open (not the "New Tab" welcome screen)
  - `tv` CLI on PATH (install with: cd ~/.local/share/tradingview-mcp && npm link)

Usage:
  python3 tjl_live_us_tv.py                    # default 3-ticker demo
  US_TICKERS=AMD,NVDA,TSLA python3 tjl_live_us_tv.py
  python3 tjl_live_us_tv.py --continuous       # loop every 30 min during market hours

Time gate: 10:00–15:30 ET on weekdays. Outside that window: writes error JSON
and exits cleanly.
"""
import json
import os
import subprocess
import sys
import time
import argparse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

TV_CLI       = os.environ.get("TV_CLI", "/Users/jaydensmac/.local/bin/tv")
ITICK_TOKEN  = os.environ.get("ITICK_TOKEN")  # Optional; if set, used for PMH fallback
ITICK_BASE   = "https://api.itick.io"         # NB: .io, not .org as docs say
SMA_PERIOD   = 200
TIME_GATE_START = (10, 0)   # 10:00 ET
TIME_GATE_END   = (15, 30)  # 15:30 ET
SCAN_INTERVAL   = 30 * 60   # 30 min default for --continuous
PER_TICKER_BUDGET = 60      # seconds; hard cap per ticker
QUOTE_AFTER_SYMBOL = 5      # seconds; chart needs time to load after symbol switch
OHLCV_AFTER_TF     = 3      # seconds; chart needs time to load after timeframe switch

# Default demo universe (matches article's prompt for the small test)
DEFAULT_WATCHLIST = ["AMD", "NVDA", "MU"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)


def run_tv(args, timeout=PER_TICKER_BUDGET):
    """Run `tv <args>` and return parsed JSON or raise."""
    cmd = [TV_CLI] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"tv {args!r} failed (exit {r.returncode}): {r.stderr[:200] or r.stdout[:200]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"tv {args!r} returned non-JSON: {r.stdout[:300]}")


def in_market_hours(now=None):
    """True between 10:00 and 15:30 ET on weekdays."""
    now = now or datetime.now(ET)
    if now.weekday() >= 5:
        return False
    total = now.hour * 60 + now.minute
    return (TIME_GATE_START[0]*60 + TIME_GATE_START[1]) <= total <= (TIME_GATE_END[0]*60 + TIME_GATE_END[1])


def health_check():
    """Verify TV is alive and the CDP target is a real chart."""
    try:
        st = run_tv(["status"], timeout=10)
    except Exception as e:
        return False, f"tv status failed: {e}", {}
    cdp = st.get("cdp_connected")
    api = st.get("api_available")
    if not cdp:
        return False, "cdp_connected=false (TV not running with --remote-debugging-port=9222)", st
    if not api:
        return False, "api_available=false (no active chart tab in TV; open a chart first)", st
    return True, "", st


def check_regime():
    """Optional regime filter using SPY/QQQ via TV MCP.

    Returns "BULLISH" if both SPY and QQQ are above their prior daily close,
    "BEARISH" if either is below, "UNKNOWN" if data unavailable.

    Note: This is NOT in HumbledTrader's original recipe. It's added here as
    an optional quality improvement. Pass --no-regime to skip.
    """
    regime = "UNKNOWN"
    details = []
    for sym in ("SPY", "QQQ"):
        try:
            # switch chart, get intraday quote, get yesterday's close from daily bar
            run_tv(["symbol", sym], timeout=15)
            time.sleep(QUOTE_AFTER_SYMBOL)
            q = run_tv(["quote"], timeout=15)
            curr = float(q.get("last") or q.get("close") or 0)
            run_tv(["timeframe", "D"], timeout=15)
            time.sleep(OHLCV_AFTER_TF)
            daily = run_tv(["ohlcv", "--count", "5"], timeout=30)
            bars = daily.get("bars") or []
            if len(bars) >= 2:
                prev_close = float(bars[-2]["close"])  # yesterday's close
                if prev_close > 0:
                    details.append((sym, curr, prev_close, curr > prev_close))
        except Exception as e:
            details.append((sym, 0, 0, False))
    if details and all(d[3] for d in details):
        regime = "BULLISH"
    elif details and any(not d[3] for d in details):
        regime = "BEARISH"
    return regime, details


# ── Per-ticker check (mirrors article recipe) ─────────────────────────────────

def check_ticker(symbol):
    """
    Implements the article's Trend Join Long entry test for one ticker.
    Returns dict with keys: symbol, curr_price, prev_daily_high, prev_daily_close,
    sma200, pmh, today_hod, daily_breakout, intraday_breakout, result, error.
    """
    out = {"symbol": symbol}

    # 1. Switch chart to this ticker (article step 1)
    sym_resp = run_tv(["symbol", symbol], timeout=15)
    if not sym_resp.get("success"):
        out["error"] = f"chart_set_symbol failed: {sym_resp}"
        out["result"] = "fail_symbol"
        return out
    time.sleep(QUOTE_AFTER_SYMBOL)

    # 2. Get current intraday quote (article step 3, do this BEFORE switching TF
    #    to avoid the chart rebinding to daily and losing the intraday view)
    q = run_tv(["quote"], timeout=15)
    if not q.get("success"):
        out["error"] = f"quote_get failed: {q}"
        out["result"] = "fail_quote"
        return out
    curr_px = float(q.get("last") or q.get("close") or 0)
    out["curr_price"] = curr_px

    # 3. Switch to daily timeframe, fetch 210 daily bars (article step 2)
    run_tv(["timeframe", "D"], timeout=15)
    time.sleep(OHLCV_AFTER_TF)
    daily = run_tv(["ohlcv", "--count", str(SMA_PERIOD + 10)], timeout=30)
    if not daily.get("success"):
        out["error"] = f"daily ohlcv failed: {daily}"
        out["result"] = "fail_data"
        return out
    bars = daily.get("bars") or daily.get("data") or []
    if len(bars) < SMA_PERIOD:
        out["error"] = f"insufficient daily bars ({len(bars)})"
        out["result"] = "fail_data"
        return out
    # TV returns bars in CHRONOLOGICAL order (oldest first); latest bar is [-1]
    prev_daily_high  = float(bars[-1]["high"])
    prev_daily_close = float(bars[-1]["close"])
    sma200 = sum(float(b["close"]) for b in bars[-SMA_PERIOD:]) / SMA_PERIOD
    out["prev_daily_high"]  = round(prev_daily_high, 4)
    out["prev_daily_close"] = round(prev_daily_close, 4)
    out["sma200"]           = round(sma200, 4)

    # 4. Switch to 1-minute, fetch today's bars for PMH + HOD (article step 4)
    run_tv(["timeframe", "1"], timeout=15)
    time.sleep(OHLCV_AFTER_TF)
    intraday = run_tv(["ohlcv", "--count", "400"], timeout=30)
    if not intraday.get("success"):
        out["error"] = f"intraday ohlcv failed: {intraday}"
        out["result"] = "fail_data"
        return out
    i_bars = intraday.get("bars") or intraday.get("data") or []
    if not i_bars:
        out["error"] = "no intraday bars"
        out["result"] = "fail_data"
        return out

    # Filter into premarket (04:00–09:30 ET) and regular (≥09:30 ET) for TODAY
    # NOTE: TV's `tv ohlcv` endpoint only returns regular-session bars even when
    # the chart visually shows pre-market data. So we fall back to iTick's REST
    # API (1-min bars) for PMH when available — ITICK_TOKEN env var required.
    pmh_bars, today_hod_bars = [], []
    now_et = datetime.now(ET)
    for b in i_bars:
        # TV bar time is unix seconds (UTC)
        ts = int(b.get("time", 0))
        bar_et = datetime.fromtimestamp(ts, ET)
        if bar_et.date() != now_et.date():
            continue
        minutes = bar_et.hour * 60 + bar_et.minute
        if (4*60) <= minutes < (9*60 + 30):
            pmh_bars.append(b)
        elif minutes >= (9*60 + 30):
            today_hod_bars.append(b)
    pmh = max((float(b["high"]) for b in pmh_bars), default=0.0)

    # PMH fallback via iTick — needed because TV's ohlcv omits pre-market bars
    if pmh <= 0 and ITICK_TOKEN:
        try:
            url = (f"{ITICK_BASE}/stock/kline?"
                   f"region=US&code={symbol}&kType=2&limit=200")
            req = urllib.request.Request(url, headers={
                "accept": "application/json", "token": ITICK_TOKEN})
            resp = urllib.request.urlopen(req, timeout=10)
            d = json.loads(resp.read().decode())
            if d.get("code") == 0 and d.get("data"):
                # iTick returns newest-first; reverse for chronological order
                for bar in reversed(d["data"]):
                    ts = int(bar["t"]) // 1000   # ms → s
                    bar_et = datetime.fromtimestamp(ts, ET)
                    if bar_et.date() != now_et.date():
                        continue
                    minutes = bar_et.hour * 60 + bar_et.minute
                    if (4*60) <= minutes < (9*60 + 30):
                        pmh = max(pmh, float(bar["h"]))
            if pmh > 0:
                log(f"    ✓ PMH from iTick fallback: {pmh:.2f}")
        except Exception as e:
            log(f"    ⚠ iTick PMH fallback failed: {e}")

    today_hod = max((float(b["high"]) for b in today_hod_bars), default=curr_px)
    if pmh <= 0:
        log("    ⚠ PMH=0 — TV lacks pre-market in ohlcv AND iTick fallback unavailable. "
            "Set ITICK_TOKEN to enable.")
    out["pmh"]        = round(pmh, 4)
    out["today_hod"]  = round(today_hod, 4)

    # 5. Evaluate (article step 5)
    # If pmh=0 (Extended Hours off), the intraday_breakout check is meaningless —
    # require a valid PMH value, otherwise mark as fail_intraday with a note.
    daily_breakout = (curr_px > prev_daily_high) and (prev_daily_close > sma200)
    if pmh <= 0:
        intraday_breakout = False
        out["note"] = "PMH unavailable (Extended Hours off); intraday breakout check skipped"
    else:
        intraday_breakout = (curr_px > pmh) and (curr_px > today_hod)
    out["daily_breakout"]    = bool(daily_breakout)
    out["intraday_breakout"] = bool(intraday_breakout)
    if daily_breakout and intraday_breakout:
        out["result"] = "PASS"
    elif not daily_breakout:
        out["result"] = "fail_daily"
    else:
        out["result"] = "fail_intraday"
    return out



def notify_telegram(payload):
    """Send scan summary to user's Telegram via `hermes send`."""
    import subprocess
    regime_emoji = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(payload.get("regime", ""), "⚪")
    lines = [
        f"📊 *TJL TV Scan* — {payload['scanned_at']}",
        f"Regime: {regime_emoji} *{payload.get('regime', 'UNKNOWN')}*",
        f"Tickers: {payload['candidates_checked']}  Hits: *{len(payload.get('hits', []))}*",
    ]
    if payload.get("skipped"):
        lines.append(f"⏰ Skipped: {payload['skipped']}")
    elif payload.get("error"):
        lines.append(f"❌ Error: {payload['error']}")
    elif payload.get("hits"):
        lines += ["", "```", f"{'Symbol':<8} {'Price':>8} {'PDH':>8} {'SMA200':>8} {'PMH':>8}", "-" * 50]
        for h in payload["hits"]:
            lines.append(f"{h['symbol']:<8} {h['curr_price']:>8.2f} {h['prev_daily_high']:>8.2f} "
                         f"{h['sma200']:>8.2f} {h['pmh']:>8.2f}")
        lines.append("```")
    else:
        lines.append("⏳ No PASS. Top failures:")
        for r in payload.get("all_results", [])[:5]:
            sym = r.get("symbol", "?")
            curr = r.get("curr_price", "?")
            pdh = r.get("prev_daily_high", "?")
            sma = r.get("sma200", "?")
            pmh = r.get("pmh", "?")
            lines.append(f"  `{sym}` px={curr} PDH={pdh} SMA200={sma} PMH={pmh}")
    text = "\n".join(lines)
    try:
        r = subprocess.run(["hermes", "send", "--to", "telegram"],
                           input=text, text=True, capture_output=True, timeout=30)
        log(f"📨 Telegram: {r.stdout.strip() or r.stderr.strip()}")
    except Exception as e:
        log(f"⚠ Telegram delivery failed: {e}")


# ── Scan orchestrator ─────────────────────────────────────────────────────────

def run_scan(tickers, skip_regime=False, notify=False):
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%Y-%m-%d %H:%M:%S ET")
    stamp   = now_et.strftime("%Y-%m-%d_%H%M") + "ET"
    today   = now_et.strftime("%Y-%m-%d")

    log("=" * 70)
    log("TJL Live Scanner — TradingView MCP (HumbledTrader recipe)")
    log(f"Time : {now_str}")
    log(f"Universe: {len(tickers)} tickers ({', '.join(tickers)})")
    log("=" * 70)

    ok, why, status = health_check()
    if not ok:
        log(f"❌ Health check failed: {why}")
        # Save error JSON and exit cleanly
        out_file = os.path.expanduser(f"~/tjl_watchlist_{stamp}.json")
        with open(out_file, "w") as f:
            json.dump({"scanned_at": now_str, "error": why, "status": status}, f, indent=2)
        log(f"📁 Wrote error report to {out_file}")
        return {"error": why, "hits": [], "all_results": []}

    log(f"✓ TV healthy: chart on {status.get('chart_symbol')} ({status.get('chart_resolution')})")

    # Snapshot starting chart so we can restore it at the end (regime check
    # leaves the chart on SPY/QQQ which is jarring for the user)
    starting_symbol = status.get('chart_symbol')

    # Optional regime check via TV MCP (default ON; skip with --no-regime)
    regime = "UNKNOWN"
    regime_details = []
    if not skip_regime:
        regime, regime_details = check_regime()
        details_str = "  ".join(
            f"{s} curr={c:.2f} prev={p:.2f} {'up' if u else 'down'}"
            for (s, c, p, u) in regime_details
        )
        log(f"📊 Regime (SPY/QQQ): {regime}  [{details_str}]")
    else:
        log("📊 Regime check skipped (--no-regime)")
    log("")

    if not in_market_hours(now_et):
        msg = (f"Outside market hours gate (10:00–15:30 ET). "
               f"Current time: {now_str}. Skipping scan.")
        log(f"⏰ {msg}")
        out_file = os.path.expanduser(f"~/tjl_watchlist_{stamp}.json")
        with open(out_file, "w") as f:
            json.dump({"scanned_at": now_str, "skipped": msg, "hits": [], "all_results": []}, f, indent=2)
        log(f"📁 Wrote skip report to {out_file}")
        return {"skipped": msg, "hits": [], "all_results": []}

    # Per-ticker loop (sequential; chart can't drive two symbols in parallel)
    all_results = []
    hits = []
    for i, sym in enumerate(tickers, 1):
        log(f"[{i}/{len(tickers)}] Checking {sym}…")
        try:
            res = check_ticker(sym)
        except Exception as e:
            log(f"  ⚠ {sym}: {e}")
            all_results.append({"symbol": sym, "result": "error", "error": str(e)[:200]})
            continue
        all_results.append({k: v for k, v in res.items() if k != "error"})
        if res.get("result") == "PASS":
            log(f"  ✅ {sym}: PASS @ ${res['curr_price']}  "
                f"(PDH={res['prev_daily_high']} SMA200={res['sma200']} PMH={res['pmh']})")
            hits.append({k: v for k, v in res.items() if k != "error"})
        else:
            log(f"  — {sym}: {res.get('result', 'error')}  "
                f"(curr={res.get('curr_price')} PDH={res.get('prev_daily_high')} "
                f"SMA200={res.get('sma200')} PMH={res.get('pmh')})")

    # Print article's "one line per ticker" format
    log("")
    log("── Summary ──")
    for r in all_results:
        sym = r.get("symbol", "?")
        result = r.get("result", "error")
        log(f"  {sym}: {result}")

    # Save JSON (article's schema)
    out_file = os.path.expanduser(f"~/tjl_watchlist_{stamp}.json")
    payload = {
        "scanned_at":           now_str,
        "source":               "TradingView MCP (tv CLI)",
        "strategy":             "Trend Join Long (HumbledTrader)",
        "candidates_checked":   len(tickers),
        "hits":                 hits,
        "all_results":          all_results,
        "market_hours_ok":      True,
        "regime":               regime,
        "regime_details":      [
            {"symbol": s, "current": c, "prev_close": p, "up": u}
            for (s, c, p, u) in regime_details
        ],
        "pmh_source":           "iTick fallback" if ITICK_TOKEN else "TV chart (pre-market only when Extended Hours on)",
    }
    with open(out_file, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"📁 Saved to {out_file}")

    # Restore starting chart (best-effort, don't fail the scan if this errors)
    if starting_symbol:
        try:
            first_ticker = starting_symbol.split(":")[-1]  # strip "BATS:" etc
            run_tv(["symbol", first_ticker], timeout=15)
            log(f"🔄 Restored chart to {first_ticker}")
        except Exception as e:
            log(f"⚠ Failed to restore chart: {e}")

    if notify:
        notify_telegram(payload)

    return payload


def main():
    parser = argparse.ArgumentParser(description="TJL Live Scanner — TradingView MCP")
    parser.add_argument("--continuous", action="store_true", help="Loop every 30 min during market hours")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL, help="Seconds between scans (continuous)")
    parser.add_argument("--tickers", help="Comma-separated ticker list (overrides default + US_TICKERS)")
    parser.add_argument("--no-regime", action="store_true",
                        help="Skip the SPY/QQQ regime check (HumbledTrader recipe doesn't include it)")
    parser.add_argument("--notify", action="store_true",
                        help="Send results to Telegram (home channel via hermes send) after scan")
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        env = os.environ.get("US_TICKERS", "").strip()
        if env:
            tickers = [t.strip().upper() for t in env.split(",") if t.strip()]
        else:
            tickers = DEFAULT_WATCHLIST

    log(f"TJL Live TV Scanner | TradingView MCP | Press Ctrl+C to stop")
    log(f"Watchlist: {len(tickers)} tickers  (CLI: {TV_CLI})")

    if args.continuous:
        log(f"CONTINUOUS mode — interval {args.interval}s")
        try:
            while True:
                run_scan(tickers, skip_regime=args.no_regime, notify=args.notify)
                log(f"Sleeping {args.interval}s until next scan...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log("Stopped.")
    else:
        run_scan(tickers, skip_regime=args.no_regime, notify=args.notify)


if __name__ == "__main__":
    main()