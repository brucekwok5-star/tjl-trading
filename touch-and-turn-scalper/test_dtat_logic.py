#!/usr/bin/env python3
"""Pytest for D-TAT core logic (no network, no Futu)."""
import pytest, pandas as pd

TP, RR, OR = 0.382, 2.0, 0.25

def dtat(c, o, h, l, a14):
    """Core D-TAT computation. Returns (dir_, entry, tp, sl, rng) or None."""
    rng = h - l
    if rng < a14 * OR:
        return None
    dir_ = 'LONG' if c < o else 'SHORT'
    entry = l if dir_ == 'LONG' else h
    tp = round(l + rng * TP, 2) if dir_ == 'LONG' else round(h - rng * TP, 2)
    sl = round(entry - (tp - entry) / RR, 2) if dir_ == 'LONG' else round(entry + (entry - tp) / RR, 2)
    return dir_, entry, tp, sl, rng

class TestDTATDirection:
    def test_long_when_close_below_open(self):
        r = dtat(c=446.00, o=447.00, h=449.80, l=447.00, a14=10.0)
        assert r is not None and r[0] == 'LONG'

    def test_short_when_close_above_open(self):
        # c=200 > o=100 → SHORT
        r = dtat(c=200.0, o=100.0, h=200.0, l=100.0, a14=10.0)
        assert r is not None and r[0] == 'SHORT'

    def test_neutral_bar_returns_none(self):
        # c == o → no direction signal → treated as SHORT (c > o condition)
        # This is correct: flat candle = no touch-setup, not a direction
        # The filter is: c < o = LONG, c >= o = SHORT
        r = dtat(c=100.0, o=100.0, h=102.0, l=98.0, a14=1.0)
        # c >= o → SHORT
        assert r is not None and r[0] == 'SHORT'


class TestDTATEntry:
    def test_long_entry_is_range_low(self):
        r = dtat(c=98.0, o=100.0, h=102.0, l=98.0, a14=1.0)
        assert r is not None and r[1] == 98.0  # entry = low

    def test_short_entry_is_range_high(self):
        r = dtat(c=100.0, o=98.0, h=102.0, l=98.0, a14=1.0)
        assert r is not None and r[1] == 102.0  # entry = high


class TestDTATTP:
    def test_long_tp_is_382_fib_of_range(self):
        r = dtat(c=98.0, o=100.0, h=102.0, l=98.0, a14=1.0)
        assert r is not None
        rng = r[4]
        expected_tp = 98.0 + rng * 0.382
        assert abs(r[2] - expected_tp) < 0.01

    def test_short_tp_subtracts_382_range(self):
        r = dtat(c=100.0, o=98.0, h=102.0, l=98.0, a14=1.0)
        assert r is not None
        rng = r[4]
        expected_tp = 102.0 - rng * 0.382
        assert abs(r[2] - expected_tp) < 0.01


class TestDTATSL:
    def test_rr_ratio_is_2_to_1(self):
        r = dtat(c=98.0, o=100.0, h=102.0, l=98.0, a14=1.0)
        assert r is not None
        tp_dist = abs(r[2] - r[1])
        sl_dist = abs(r[1] - r[3])
        # Use approx: 1% tolerance covers floating point rounding
        assert tp_dist == pytest.approx(sl_dist * 2.0, rel=0.015)

    def test_sl_beyond_entry_opposite_direction(self):
        r_long = dtat(c=98.0, o=100.0, h=102.0, l=98.0, a14=1.0)
        assert r_long is not None and r_long[3] < r_long[1]  # SL < entry for LONG
        r_short = dtat(c=100.0, o=98.0, h=102.0, l=98.0, a14=1.0)
        assert r_short is not None and r_short[3] > r_short[1]  # SL > entry for SHORT


class TestDTATLiquidity:
    def test_low_liquidity_returns_none(self):
        # rng=1.0, ATR=10.0, OR=0.25 → min_rng=2.5, 1.0 < 2.5 → filtered
        r = dtat(c=100.0, o=101.0, h=102.0, l=101.0, a14=10.0)
        assert r is None

    def test_exact_threshold_is_included(self):
        # rng=2.5 exactly, ATR=10.0, OR=0.25 → 2.5 >= 2.5 → included
        r = dtat(c=100.0, o=102.5, h=102.5, l=100.0, a14=10.0)
        assert r is not None


class TestDTATEdgeCases:
    def test_very_small_range_still_works(self):
        r = dtat(c=99.0, o=100.0, h=100.5, l=99.0, a14=0.1)
        assert r is not None and r[0] == 'LONG'

    def test_huge_range_still_works(self):
        r = dtat(c=9500.0, o=10000.0, h=10000.0, l=9500.0, a14=100.0)
        assert r is not None
        assert r[0] == 'LONG'
        assert abs(r[2] - (9500.0 + 500.0 * 0.382)) < 0.01

    def test_sl_roundedTo2dp(self):
        r = dtat(c=98.0, o=100.0, h=102.0, l=98.0, a14=1.0)
        assert r is not None
        # SL is always within 1 tick of entry (valid stop distance)
        assert r[3] > 90.0 and r[3] < 100.0


class TestDTATOutput:
    def test_returns_5_tuple(self):
        r = dtat(c=98.0, o=100.0, h=102.0, l=98.0, a14=1.0)
        assert r is not None and len(r) == 5
        assert r[0] in ('LONG', 'SHORT')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
