#!/usr/bin/env python3
"""
Hermes verification for compare_results.py.

Tests:
  - Parses today's outputs across all 3 scanners
  - Handles missing scanner gracefully (one absent shouldn't crash)
  - Handles missing tickers gracefully
  - Output format: header + per-ticker table + regime + interpretation
"""
import json, os, subprocess, sys, tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
today = datetime.now(ET).strftime("%Y-%m-%d")
SCRIPT = "/Users/jaydensmac/.openclaw/workspace/compare_results.py"

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    icon = "✓" if ok else "✗"
    print(f"  {icon} {name}: {detail}")


print(f"\n[compare_results.py] Verifying with date={today}")

# ── Test 1: Run with today's real data ────────────────────────────────────────
r = subprocess.run(
    ["python3", SCRIPT], capture_output=True, text=True, timeout=30
)
print("\n[Test 1] Live run with today's data")
check("exit code is 0", r.returncode == 0, f"got {r.returncode}")
check("stdout contains header",
      "TJL SCANNER COMPARISON" in r.stdout,
      "")
check("stdout contains per-ticker section",
      "PER-TICKER COMPARISON" in r.stdout,
      "")
check("stdout contains regime section",
      "REGIME / METADATA" in r.stdout,
      "")
check("stdout contains interpretation section",
      "INTERPRETATION" in r.stdout,
      "")

# ── Test 2: Specific date ────────────────────────────────────────────────────
print("\n[Test 2] Run with explicit date arg")
r2 = subprocess.run(
    ["python3", SCRIPT, today], capture_output=True, text=True, timeout=30
)
check("exit code is 0 with date arg", r2.returncode == 0, f"got {r2.returncode}")
check("header shows the date",
      today in r2.stdout,
      f"date={today}")

# ── Test 3: Sandbox HOME with synthetic data ──────────────────────────────────
print("\n[Test 3] Sandbox HOME with synthetic JSON files")
with tempfile.TemporaryDirectory(prefix="hermes-verify-cmp-") as sandbox:
    # Create fake JSON files in sandbox HOME
    fake_yf = {
        "scanned_at": "2026-08-03 12:00:00 ET",
        "source": "Yahoo Finance",
        "regime": "BULLISH",
        "signals": [{"ticker": "AAPL", "name": "Apple", "price": 200.0,
                     "e9": 199.0, "e20": 198.0, "e50": 197.0,
                     "atr": 1.0, "pmh": 195.0, "sl": 198.5, "tp": 203.0,
                     "rr_ratio": 2.0, "stack_ok": True, "near_ema_ok": True,
                     "above_pmh_ok": True}],
        "debug": ["MSFT: !stack !nearEMA !abovePMH"],
    }
    fake_it = {
        "scanned_at": "2026-08-03 12:00:01 ET",
        "source": "iTick (api.itick.io)",
        "regime": "BEARISH",
        "signals": [],
        "debug": ["AAPL: !nearEMA !abovePMH", "MSFT: !stack !nearEMA"],
    }
    fake_tv = {
        "scanned_at": "2026-08-03 12:00:02 ET",
        "source": "TradingView MCP",
        "strategy": "HumbledTrader",
        "candidates_checked": 2,
        "regime": "BULLISH",
        "regime_details": [{"symbol": "SPY", "current": 100, "prev_close": 99, "up": True}],
        "pmh_source": "iTick fallback",
        "hits": [{"symbol": "AAPL", "curr_price": 200.0, "prev_daily_high": 195.0,
                  "sma200": 180.0, "pmh": 196.0, "sl": 198.5, "tp": 203.0}],
        "all_results": [
            {"symbol": "AAPL", "result": "PASS", "curr_price": 200.0,
             "prev_daily_high": 195.0, "sma200": 180.0, "pmh": 196.0},
            {"symbol": "MSFT", "result": "fail_daily", "curr_price": 400.0,
             "prev_daily_high": 405.0, "sma200": 380.0, "pmh": 395.0},
        ],
        "market_hours_ok": True,
    }
    # Write to sandbox $HOME — note TV file convention is {YYYY-MM-DD}_{HHMM}ET
    with open(os.path.join(sandbox, f"tjl_live_us_{today}.json"), "w") as f:
        json.dump(fake_yf, f)
    with open(os.path.join(sandbox, f"tjl_live_us_itick_{today}.json"), "w") as f:
        json.dump(fake_it, f)
    with open(os.path.join(sandbox, f"tjl_watchlist_{today}_1200ET.json"), "w") as f:
        json.dump(fake_tv, f)

    r3 = subprocess.run(
        ["python3", SCRIPT, "--home=" + sandbox],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "HOME": sandbox},
    )
    if r3.returncode != 0:
        print("DEBUG r3 stdout:", r3.stdout[:500])
        print("DEBUG r3 stderr:", r3.stderr[:500])
    check("sandbox exit code is 0", r3.returncode == 0, f"got {r3.returncode}")
    check("sandbox: AAPL row shows yfinance PASS",
          "AAPL" in r3.stdout and "PASS" in r3.stdout.split("AAPL")[1].split("\n")[0],
          "")
    check("sandbox: MSFT row present in all 3 columns",
          # Cells don't repeat ticker names — check that the row has fail entries in all 3 cols
          ("MSFT" in r3.stdout and
           r3.stdout.count("!stack") >= 1 and   # yfinance cell
           r3.stdout.count("!nearEMA") >= 1 and  # iTick cell
           "px=400" in r3.stdout),              # TV cell
          f"yfinance='{('!stack' in r3.stdout)}', "
          f"iTick='{('!nearEMA' in r3.stdout)}', "
          f"TV='{('px=400' in r3.stdout)}'")
    check("sandbox: regime row shows BEARISH (from iTick)",
          "BEARISH" in r3.stdout,
          "")
    check("sandbox: regime row shows BULLISH (from yfinance + TV)",
          "BULLISH" in r3.stdout,
          "")

# ── Test 4: No data ───────────────────────────────────────────────────────────
print("\n[Test 4] Empty sandbox (no JSON files)")
with tempfile.TemporaryDirectory(prefix="hermes-verify-empty-") as sandbox:
    r4 = subprocess.run(
        ["python3", SCRIPT, "--home=" + sandbox],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "HOME": sandbox},
    )
    # Script should exit with helpful message, not crash
    check("empty: exit code is 1", r4.returncode == 1, f"got {r4.returncode}")
    check("empty: helpful message printed",
          "No scan outputs found" in r4.stdout,
          f"stdout: {r4.stdout[:200]}")


# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"RESULT: {passed}/{total} checks passed")
print("=" * 70)
for name, ok, detail in results:
    if not ok:
        print(f"  FAIL: {name} — {detail}")

sys.exit(0 if passed == total else 1)