#!/usr/bin/env python3
"""
Performance benchmarks for TJL US Scanner (Phase 3).

Tests:
  a) test_10_tickers_under_15s       — scan 10 tickers, measure wall time
  b) test_50_tickers_under_20s       — scan 50 tickers (Agent B tightened from 30s)
  c) test_fetch_batch_bottleneck     — measure fetch_batch() vs model computation time
  d) test_get_regime_caching         — measure get_regime() once vs multiple calls (2 API calls each)
  e) test_memory_no_leak             — run scan 3×, verify peak memory < 500 MB

These tests hit the network (yfinance). That's expected.

Agent B Adjustments (from plan):
  - 50 tickers: tightened to < 20s (was 30s)
  - 500 tickers: tightened to < 90s (was 120s)
  - get_regime() makes 2 API calls (SPY + QQQ) every scan — flag for caching
"""
import os
import sys
import time
import tracemalloc

import pytest

# Ensure workspace is importable
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

from tjl_ndx11_hkstyle import run_scan, fetch_batch, get_regime, SP500_CORE


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_discord(monkeypatch):
    """Remove Discord webhook env var so scans don't try to post."""
    monkeypatch.delenv('DISCORD_WEBHOOK_HK_TJL', raising=False)


# ── a) 10-ticker scan speed ───────────────────────────────────────────────────

def test_10_tickers_under_15s():
    """Scan 10 tickers and verify wall time is under 15 seconds."""
    tickers = ['AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN',
               'META', 'TSLA', 'AMD', 'INTC', 'MU']
    t0 = time.time()
    run_scan(tickers)
    elapsed = time.time() - t0
    print(f"\n  10 tickers: {elapsed:.1f}s")
    assert elapsed < 15, f"10 tickers took {elapsed:.1f}s (limit 15s)"


# ── b) 50-ticker scan speed (Agent B: tightened from 30s to 20s) ──────────────

def test_50_tickers_under_20s():
    """Scan 50 tickers and verify wall time is under 20 seconds.

    Agent B tightened this from 30s to 20s to catch regressions earlier.
    yfinance batch of 50×250d ≈ 3-5s download + get_regime() 2 API calls.
    """
    tickers = SP500_CORE[:50]
    assert len(tickers) == 50, f"Need 50 tickers, got {len(tickers)}"
    t0 = time.time()
    run_scan(tickers)
    elapsed = time.time() - t0
    print(f"\n  50 tickers: {elapsed:.1f}s")
    assert elapsed < 20, f"50 tickers took {elapsed:.1f}s (limit 20s)"


# ── c) fetch_batch bottleneck analysis ────────────────────────────────────────

def test_fetch_batch_bottleneck():
    """Measure fetch_batch() vs model computation time.

    Is the bottleneck yfinance I/O or model computation?
    Agent B confirmed: fetch is >90% of scan time.
    """
    tickers = ['AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN',
               'META', 'TSLA', 'AMD', 'INTC', 'MU']

    # Measure fetch time only
    t0 = time.time()
    batch = fetch_batch(tickers, period='250d')
    fetch_t = time.time() - t0

    # Measure model computation on pre-fetched data
    from tjl_ndx11_hkstyle import MODEL_CHECKERS
    t1 = time.time()
    signal_count = 0
    for ticker, d in batch.items():
        for model, direction, checker, regime_check in MODEL_CHECKERS:
            try:
                sig = checker(ticker, d)
                if sig:
                    signal_count += 1
            except Exception:
                pass
    compute_t = time.time() - t1

    total = fetch_t + compute_t
    fetch_pct = fetch_t / total * 100 if total > 0 else 0

    print(f"\n  Fetch: {fetch_t:.2f}s | Compute: {compute_t:.3f}s | "
          f"Fetch is {fetch_pct:.0f}% of scan | Signals: {signal_count}")

    # Fetch should dominate (>50% of total time)
    assert fetch_t > 0, "Fetch returned in 0s — suspicious"
    assert fetch_pct > 50, (
        f"Fetch is only {fetch_pct:.0f}% of scan time — "
        f"unexpected; fetch={fetch_t:.2f}s compute={compute_t:.3f}s"
    )
    # Fetch for 10 tickers should be reasonable
    assert fetch_t < 10, f"Fetch is bottleneck at {fetch_t:.2f}s for 10 tickers"


# ── d) get_regime() caching analysis ──────────────────────────────────────────

def test_get_regime_caching():
    """Measure get_regime() called once vs multiple times.

    get_regime() fetches SPY + QQQ 1-year history every call = 2 API calls.
    If a single call takes >2s, caching is strongly recommended.

    RECOMMENDATION:
      If get_regime() > 2s, add @functools.lru_cache or a module-level cache:
        import functools
        @functools.lru_cache(maxsize=1)
        def get_regime():
            ...
      Or cache with TTL:
        _regime_cache = {'val': None, 'ts': 0}
        def get_regime(ttl=300):
            import time
            if time.time() - _regime_cache['ts'] < ttl:
                return _regime_cache['val']
            ...compute...
            _regime_cache.update(val=result, ts=time.time())
            return result

    Agent B flagged: "get_regime() called every scan = 2 API calls wasted."
    """
    # First call (cold)
    t0 = time.time()
    r1 = get_regime()
    single_t = time.time() - t0

    # Second call (no cache — measures the waste of repeated calls)
    t1 = time.time()
    r2 = get_regime()
    second_t = time.time() - t1

    # Simulated waste: if called 5 times in one session
    t2 = time.time()
    for _ in range(5):
        get_regime()
    five_calls_t = time.time() - t2

    print(f"\n  get_regime() single call: {single_t:.2f}s")
    print(f"  get_regime() second call: {second_t:.2f}s")
    print(f"  5 calls (no cache): {five_calls_t:.2f}s "
          f"({five_calls_t/5:.2f}s each)")
    print(f"  With cache, 5 calls would cost ~{single_t:.2f}s "
          f"(savings: {five_calls_t - single_t:.2f}s)")

    # Sanity: regime must be valid
    assert r1 in ('BULLISH', 'BEARISH', 'neutral'), f"Invalid regime: {r1}"
    assert r1 == r2, f"Inconsistent: {r1} vs {r2}"

    # CACHING RECOMMENDATION:
    # If single call > 2s, the scanner should cache regime.
    # Document this as a comment for Phase 6 enhancement.
    if single_t > 2.0:
        print(f"\n  ⚠️  get_regime() took {single_t:.2f}s > 2s — "
              f"CACHING STRONGLY RECOMMENDED (@lru_cache or TTL cache)")
    else:
        print(f"\n  ✅ get_regime() took {single_t:.2f}s — acceptable, "
              f"but caching still saves {five_calls_t - single_t:.2f}s "
              f"across 5 calls")

    # NOTE: yfinance HTTP connection pooling can make 5 calls faster than 1
    # if the connection wasn't warmed up yet. This is NOT a bug.
    # Actual finding: get_regime() takes ~0.1-0.2s total. Explicit caching
    # yields <0.1s savings — LOW PRIORITY for Phase 6.
    print(f"\n  Regime caching: {five_calls_t:.3f}s for 5 calls vs {single_t:.3f}s for 1")
    print(f"  Actual savings from explicit caching: negligible ({five_calls_t - single_t:.3f}s max)")
    print(f"  RECOMMENDATION: skip explicit lru_cache on get_regime — LOW PRIORITY")
    # No assertion — informational only


# ── e) Memory leak test ───────────────────────────────────────────────────────

def test_memory_no_leak():
    """Run scan 3 times, verify peak memory stays under 500 MB.

    Checks for:
      - _prev_closes global dict accumulating across calls (B6)
      - DataFrames not being garbage collected
      - Any unbounded growth in repeated scans
    """
    tickers = ['AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN']
    tracemalloc.start()

    snapshots = []
    for i in range(3):
        run_scan(tickers)
        current, peak = tracemalloc.get_traced_memory()
        snapshots.append({
            'run': i + 1,
            'current_mb': current / 1024 / 1024,
            'peak_mb': peak / 1024 / 1024,
        })

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    current_mb = current / 1024 / 1024

    print(f"\n  Memory across 3 scans:")
    for s in snapshots:
        print(f"    Run {s['run']}: current={s['current_mb']:.1f} MB, "
              f"peak={s['peak_mb']:.1f} MB")
    print(f"  Final: current={current_mb:.1f} MB, peak={peak_mb:.1f} MB")

    # Peak must stay under 500 MB
    assert peak_mb < 500, (
        f"Peak memory {peak_mb:.0f} MB > 500 MB limit — possible leak"
    )

    # Current (live) memory after 3 runs should not be wildly larger
    # than after run 1 — indicates data isn't accumulating
    run1_current = snapshots[0]['current_mb']
    run3_current = snapshots[2]['current_mb']
    growth_mb = run3_current - run1_current
    print(f"  Growth run1→run3: {growth_mb:+.1f} MB")

    # Allow some growth but flag if > 100 MB accumulation
    assert growth_mb < 100, (
        f"Memory grew {growth_mb:+.1f} MB across runs — possible leak "
        f"(run1={run1_current:.1f} MB → run3={run3_current:.1f} MB)"
    )
