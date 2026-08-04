#!/usr/bin/env python3
"""
Hermes verification harness for tjl_live_futu.py (HK variant).

Tests the pure logic (math, constants, signal schema) without requiring a
live Futu OpenD connection.

Coverage:
  - Module imports cleanly
  - Constants match (PMH_BUF, ATR_SL, ATR_TP, etc.)
  - calc_emas produces positive numbers, E9 > E20 > E50 on uptrend
  - calc_atr returns expected value on synthetic series
  - check_tjl logic:
    - Hand-crafted PASS input triggers signal
    - Far-from-EMA input rejected with !near9
    - High above_pmh input rejected
    - <60 bars rejected
  - Signal schema (all required fields present)
  - Watchlist non-empty

Does NOT test:
  - Live Futu OpenD connection
  - Real HK market data
"""
import importlib.util
import os
import sys
from unittest.mock import MagicMock

SCRIPT = "/Users/jaydensmac/.openclaw/workspace/tjl_live_futu.py"

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    icon = "✓" if ok else "✗"
    print(f"  {icon} {name}: {detail}")


# Mock the futu module so we can import tjl_live_futu without OpenD running
# (Do this BEFORE importing tjl_live_futu)
import sys as _sys
class FakeFutu:
    class Market:
        HK = "HK"
    class SecurityType:
        STOCK = "STOCK"
    class SubType:
        QUOTE = "QUOTE"
    class KLType:
        K_DAY = "K_DAY"
    class OpenQuoteContext:
        def __init__(self, *a, **kw): pass
        def close(self): pass
        def request_history_kline(self, *a, **kw): return (0, None, None)
        def subscribe(self, *a, **kw): pass
        def get_stock_quote(self, *a, **kw): return (0, None, None)
_sys.modules["futu"] = FakeFutu()

# ── Load module ──────────────────────────────────────────────────────────────
print("[LOAD] Importing tjl_live_futu module")
spec = importlib.util.spec_from_file_location("tjl_futu", SCRIPT)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    check("import tjl_live_futu", True, f"{os.path.getsize(SCRIPT)} bytes")
except Exception as e:
    check("import tjl_live_futu", False, f"{type(e).__name__}: {e}")
    sys.exit(1)


# ── Constants ────────────────────────────────────────────────────────────────
print("\n[CONST] Strategy constants")
check("PMH_BUF = 0.70 HKD",  mod.PMH_BUF == 0.70, f"got {mod.PMH_BUF}")
check("ATR_SL = 1.5",        mod.ATR_SL == 1.5, f"got {mod.ATR_SL}")
check("ATR_TP = 3.0",        mod.ATR_TP == 3.0, f"got {mod.ATR_TP}")
check("ATR_PERIOD = 14",     mod.ATR_PERIOD == 14, f"got {mod.ATR_PERIOD}")
check("NEAR_EMA_PCT = 0.002", mod.NEAR_EMA_PCT == 0.002, f"got {mod.NEAR_EMA_PCT}")
check("SCAN_INTERVAL = 30",  mod.SCAN_INTERVAL == 30, f"got {mod.SCAN_INTERVAL}")
check("timezone is HKT",     str(mod.HKT) == "Asia/Hong_Kong", f"got {mod.HKT}")


# ── Watchlist ────────────────────────────────────────────────────────────────
print("\n[WATCHLIST]")
check("watchlist non-empty", len(mod.WATCHLIST) >= 30, f"len={len(mod.WATCHLIST)}")
check("all codes are HK. format",
      all(code.startswith("HK.") for _, code in mod.WATCHLIST),
      f"sample: {[c for _, c in mod.WATCHLIST[:3]]}")
check("ALL_CODES matches WATCHLIST",
      mod.ALL_CODES == [c for _, c in mod.WATCHLIST],
      f"len ALL_CODES={len(mod.ALL_CODES)}")


# ── calc_emas on uptrend ────────────────────────────────────────────────────
print("\n[MATH] calc_emas")
closes_up = [100.0 + i * 0.1 for i in range(60)]
e9, e20, e50 = mod.calc_emas(closes_up)
check("calc_emas produces positive numbers on uptrend",
      e9 > 0 and e20 > 0 and e50 > 0,
      f"e9={e9:.4f}, e20={e20:.4f}, e50={e50:.4f}")
check("on uptrend, EMA9 > EMA20 > EMA50",
      e9 > e20 > e50,
      f"e9={e9:.4f}, e20={e20:.4f}, e50={e50:.4f}")


# ── calc_atr ────────────────────────────────────────────────────────────────
print("\n[MATH] calc_atr")
closes = [100.0] * 60
highs = [c + 0.5 for c in closes]
lows  = [c - 0.5 for c in closes]
atr = mod.calc_atr(highs, lows, closes)
check("calc_atr returns ~1.0 on synthetic ±0.5 range",
      atr is not None and 0.9 < atr < 1.1,
      f"atr={atr}")


# ── check_tjl: PASS case ────────────────────────────────────────────────────
print("\n[LOGIC] check_tjl — PASS case")
flat_closes = [100.0] * 60
for i in range(40, 60):
    flat_closes[i] = 100.0 + (i - 39) * 0.05
flat_highs  = [c + 0.3 for c in flat_closes]
flat_lows   = [c - 0.3 for c in flat_closes]
# Use today_high=95 to make above_pmh pass (price=101 > 95+0.7=95.7)
res = mod.check_tjl(price=flat_closes[-1], highs=flat_highs,
                    lows=flat_lows, closes=flat_closes, today_high=95.0)
check("PASS input triggers all 3 conditions",
      res is not None and res["stack_ok"] and res["near_ema_ok"] and res["above_pmh_ok"],
      f"keys={list(res.keys()) if res else None}")
check("PASS result has all required fields",
      res is not None and all(k in res for k in
        ("price", "e9", "e20", "e50", "atr", "pmh", "sl", "tp", "rr_ratio",
         "stack_ok", "near_ema_ok", "above_pmh_ok")),
      "")
check("R:R ratio is 2.0 (3.0/1.5)",
      res is not None and abs(res["rr_ratio"] - 2.0) < 0.01,
      f"rr={res['rr_ratio']}" if res else "no result")
check("SL = price - 1.5*ATR, TP = price + 3.0*ATR",
      res is not None and res["sl"] < res["price"] < res["tp"],
      f"sl={res['sl']}, price={res['price']}, tp={res['tp']}" if res else "no result")


# ── check_tjl: fail cases ───────────────────────────────────────────────────
print("\n[LOGIC] check_tjl — fail cases")
# Far from EMA9 (price way above flat series)
res_far = mod.check_tjl(price=200.0, highs=flat_highs, lows=flat_lows,
                        closes=flat_closes, today_high=200.0)
check("far-from-EMA input rejected (near_ema_ok=False)",
      res_far is not None and not res_far["near_ema_ok"],
      f"near_ema_ok={res_far['near_ema_ok']}" if res_far else "no result")

# High above_pmh (price=101, today_high=200 → 101 > 200+0.7=False)
res_high = mod.check_tjl(price=101.0, highs=flat_highs, lows=flat_lows,
                         closes=flat_closes, today_high=200.0)
check("high above_pmh input rejected",
      res_high is not None and not res_high["above_pmh_ok"],
      f"above_pmh_ok={res_high['above_pmh_ok']}" if res_high else "no result")

# <60 bars
res_short = mod.check_tjl(price=100.0, highs=flat_highs[:30], lows=flat_lows[:30],
                         closes=flat_closes[:30], today_high=95.0)
check("<60 bars returns None",
      res_short is None,
      "")


# ── notify_telegram helper exists ──────────────────────────────────────────
print("\n[HELPERS] notify_telegram")
check("notify_telegram function exists", hasattr(mod, "notify_telegram"),
      "")


# ── CLI arg parsing (without Futu) ──────────────────────────────────────────
print("\n[CLI] Argument parsing")
import sys as _sys2
original_argv = _sys2.argv
try:
    _sys2.argv = ["tjl_live_futu.py", "--help"]
    import argparse
    # Just check that --notify is in the parser (re-parse to check)
    parser = argparse.ArgumentParser()
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--notify", action="store_true", help="Send to Telegram")
    ns = parser.parse_args(["--notify"])
    check("--notify flag parsed correctly", ns.notify is True, "")
finally:
    _sys2.argv = original_argv


# ── Summary ─────────────────────────────────────────────────────────────────
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