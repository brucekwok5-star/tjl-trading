#!/usr/bin/env python3
"""
compare_results.py — Side-by-side comparison of the 3 TJL scanners.

Reads the most recent JSON output from each scanner and produces a unified
report showing what each scanner found for each ticker.

Usage:
  python3 compare_results.py [YYYY-MM-DD]

If no date given, uses today (ET). Compares the most recent JSON per scanner.
"""
import glob, json, os, sys
from datetime import datetime, date

if len(sys.argv) > 1:
    arg = sys.argv[1]
    if arg.startswith("--home="):
        os.environ["HOME"] = arg[len("--home="):]
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    else:
        today = arg
else:
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

print("=" * 90)
print(f"TJL SCANNER COMPARISON — {today}")
print("=" * 90)

def latest(pattern):
    files = sorted(glob.glob(os.path.expanduser(pattern)), key=os.path.getmtime)
    return files[-1] if files else None

# Find each scanner's most recent output
yf_file = latest(f"~/tjl_live_us_{today}.json")
it_file = latest(f"~/tjl_live_us_itick_{today}.json")
tv_file = latest(f"~/tjl_watchlist_{today}_*.json")

sources = []
if yf_file: sources.append(("yfinance", yf_file))
if it_file: sources.append(("iTick", it_file))
if tv_file: sources.append(("TV-MCP", tv_file))

if not sources:
    print(f"No scan outputs found for {today}. Run the scanners first.")
    sys.exit(1)

print()
for name, path in sources:
    print(f"  [{name}] {os.path.basename(path)} ({os.path.getsize(path)} bytes)")
print()

# Load each
results = {}
for name, path in sources:
    with open(path) as f:
        results[name] = json.load(f)

# Build per-ticker dict from each
def extract_yf(d):
    out = {}
    for entry in d.get("debug", []):
        sym, _, reasons = entry.partition(":")
        out[sym.strip()] = {"result": "fail", "reasons": reasons.strip()}
    for s in d.get("signals", []):
        out[s["ticker"]] = {"result": "PASS", "price": s["price"], "rr": s["rr_ratio"]}
    return out

def extract_it(d):
    out = {}
    for entry in d.get("debug", []):
        sym, _, reasons = entry.partition(":")
        out[sym.strip()] = {"result": "fail", "reasons": reasons.strip()}
    for s in d.get("signals", []):
        out[s["ticker"]] = {"result": "PASS", "price": s["price"], "rr": s["rr_ratio"]}
    return out

def extract_tv(d):
    out = {}
    for r in d.get("all_results", []):
        out[r["symbol"]] = {
            "result": r.get("result", "?"),
            "price": r.get("curr_price"),
            "pdh": r.get("prev_daily_high"),
            "sma200": r.get("sma200"),
            "pmh": r.get("pmh"),
        }
    for h in d.get("hits", []):
        out[h["symbol"]]["result"] = "PASS"
    return out

extractors = {"yfinance": extract_yf, "iTick": extract_it, "TV-MCP": extract_tv}
by_ticker = {}
for name, d in results.items():
    by_ticker[name] = extractors[name](d)

# Union of all tickers
all_tickers = sorted(set().union(*[set(d.keys()) for d in by_ticker.values()]))
if not all_tickers:
    print("No tickers found across scans.")
    sys.exit(1)

# Per-ticker comparison table
print("=" * 90)
print("PER-TICKER COMPARISON")
print("=" * 90)

# Header
header = f"{'Ticker':<8}"
for name in by_ticker:
    header += f" {name:<25}"
print(header)
print("-" * len(header))

# Each ticker
for sym in all_tickers:
    line = f"{sym:<8}"
    for name, data in by_ticker.items():
        if sym in data:
            r = data[sym]
            if r["result"] == "PASS":
                cell = "✅ PASS"
                if "price" in r and r["price"]:
                    cell += f" @ {r['price']:.2f}"
            else:
                cell = f"❌ {r['result']}"
                if "reasons" in r and r["reasons"]:
                    cell += f" ({r['reasons'][:20]})"
                elif "pdh" in r:
                    cell = f"❌ px={r['price']:.2f} PDH={r['pdh']:.2f}"
                    if r.get('sma200'):
                        cell += f" SMA200={r['sma200']:.2f}"
            line += f" {cell[:24]:<25}"
        else:
            line += f" {'—':<25}"
    print(line)

# Regime row
print()
print("=" * 90)
print("REGIME / METADATA")
print("=" * 90)
for name, d in results.items():
    regime = d.get("regime", "n/a")
    src = d.get("source", "n/a")
    print(f"  {name:<10} regime={regime:<10} source={src}")

print()
print("=" * 90)
print("INTERPRETATION")
print("=" * 90)
print("""
✓ PASS = ticker meets all strategy entry conditions.
✗ fail = at least one condition failed.

Different scanners use different strategies:
  - yfinance/iTick: EMA-stack + pullback + PMH breakout (legacy)
  - TV-MCP: SMA200 + PDH breakout + PMH breakout (HumbledTrader)

A ticker can PASS in one scanner and FAIL in another — that's expected.
The most useful question: do all 3 agree the trade is bad? → skip it.
""")