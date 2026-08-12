"""Unit tests for pure-math helpers in tjl_live_futu."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── calc_emas ─────────────────────────────────────────────────────────────────

class TestCalcEmas:
    def test_returns_three_floats(self, tjl_mod):
        closes = [100.0 + i * 0.1 for i in range(60)]
        result = tjl_mod.calc_emas(closes)
        assert len(result) == 3
        for v in result:
            assert isinstance(v, float)

    def test_uptrend_produces_bullish_stack(self, tjl_mod):
        closes = [100.0 + i * 0.1 for i in range(60)]
        e9, e20, e50 = tjl_mod.calc_emas(closes)
        assert e9 > e20 > e50, f"got e9={e9}, e20={e20}, e50={e50}"

    def test_downtrend_produces_bearish_stack(self, tjl_mod):
        closes = [200.0 - i * 0.05 for i in range(60)]
        e9, e20, e50 = tjl_mod.calc_emas(closes)
        assert e9 < e20 < e50, f"got e9={e9}, e20={e20}, e50={e50}"

    def test_flat_series_converges_to_same_value(self, tjl_mod):
        closes = [100.0] * 80
        e9, e20, e50 = tjl_mod.calc_emas(closes)
        assert abs(e9 - 100.0) < 1e-9
        assert abs(e20 - 100.0) < 1e-9
        assert abs(e50 - 100.0) < 1e-9

    def test_short_series_runs_without_error(self, tjl_mod):
        # pandas ewm on tiny series gives a value (no exception)
        closes = [100.0, 101.0, 102.0]
        e9, e20, e50 = tjl_mod.calc_emas(closes)
        assert e9 > 0 and e20 > 0 and e50 > 0

    def test_accepts_numpy_array(self, tjl_mod):
        closes = np.array([100.0 + i * 0.1 for i in range(60)])
        e9, e20, e50 = tjl_mod.calc_emas(closes)
        assert e9 > e20 > e50


# ── calc_atr ──────────────────────────────────────────────────────────────────

class TestCalcAtr:
    def test_symmetric_range_yields_that_range(self, tjl_mod):
        # 60 bars, H-L = 1.0 each day, with no gap; ATR(14) ≈ 1.0
        closes = [100.0] * 60
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        atr = tjl_mod.calc_atr(highs, lows, closes)
        assert atr is not None
        assert 0.95 < atr < 1.05

    def test_returns_none_when_too_few_trs(self, tjl_mod):
        # Need at least period=14 true ranges; we give 10 bars total → 9 TRs
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        atr = tjl_mod.calc_atr(highs, lows, closes, period=14)
        assert atr is None

    def test_handles_gap_up(self, tjl_mod):
        # Final bar gaps up: high - prev_close is large
        closes = [100.0] * 15
        highs = [101.0] * 14 + [120.0]
        lows = [99.0] * 14 + [118.0]
        atr = tjl_mod.calc_atr(highs, lows, closes)
        assert atr is not None and atr > 1.0

    def test_handles_gap_down(self, tjl_mod):
        closes = [100.0] * 15
        highs = [101.0] * 14 + [82.0]
        lows = [99.0] * 14 + [80.0]
        atr = tjl_mod.calc_atr(highs, lows, closes)
        assert atr is not None and atr > 1.0

    def test_zero_range_yields_zero(self, tjl_mod):
        # All bars identical → all TRs == 0
        closes = [100.0] * 60
        highs = [100.0] * 60
        lows = [100.0] * 60
        atr = tjl_mod.calc_atr(highs, lows, closes)
        assert atr == 0.0


# ── calc_rsi ──────────────────────────────────────────────────────────────────

class TestCalcRsi:
    def test_returns_none_for_short_series(self, tjl_mod):
        assert tjl_mod.calc_rsi([100.0] * 10) is None

    def test_purely_uptrend_approaches_100(self, tjl_mod):
        closes = [100.0 + i for i in range(30)]
        rsi = tjl_mod.calc_rsi(closes)
        assert rsi is not None
        assert rsi > 90, f"expected very high RSI on pure uptrend, got {rsi}"

    def test_purely_downtrend_approaches_0(self, tjl_mod):
        closes = [200.0 - i for i in range(30)]
        rsi = tjl_mod.calc_rsi(closes)
        assert rsi is not None
        assert rsi < 10, f"expected very low RSI on pure downtrend, got {rsi}"

    def test_flat_series_returns_100_when_no_losses(self, tjl_mod):
        # Constant price → no losses, RSI = 100
        closes = [100.0] * 30
        rsi = tjl_mod.calc_rsi(closes)
        assert rsi == 100.0

    def test_result_is_in_valid_range(self, tjl_mod):
        np.random.seed(0)
        closes = list(100 + np.cumsum(np.random.randn(50)))
        rsi = tjl_mod.calc_rsi(closes)
        assert 0 <= rsi <= 100

    def test_custom_period(self, tjl_mod):
        closes = [100.0 + i * 0.5 for i in range(30)]
        rsi = tjl_mod.calc_rsi(closes, period=10)
        assert rsi is not None and rsi > 90


# ── calc_vwap ─────────────────────────────────────────────────────────────────

class TestCalcVwap:
    def test_returns_none_for_short_input(self, tjl_mod):
        assert tjl_mod.calc_vwap([100], [99], [100], [1]) is None

    def test_single_price_yields_that_price(self, tjl_mod):
        # 2 identical bars → typical = 100, VWAP = 100
        vwap = tjl_mod.calc_vwap([101, 101], [99, 99], [100, 100], [50, 50])
        assert vwap is not None
        assert abs(vwap - 100.0) < 1e-6

    def test_higher_volume_anchors_vwap(self, tjl_mod):
        # First bar much higher, but very low volume; second bar lower, heavy vol
        # VWAP should be close to 100 (second bar) due to volume weighting.
        highs = [120.0, 100.0]
        lows = [110.0, 95.0]
        closes = [115.0, 100.0]
        volumes = [1, 1000]
        vwap = tjl_mod.calc_vwap(highs, lows, closes, volumes)
        assert vwap is not None
        assert vwap < 110, f"expected VWAP pulled toward 100 by volume, got {vwap}"


# ── calc_bb_bands ─────────────────────────────────────────────────────────────

class TestCalcBbBands:
    def test_returns_none_when_too_few_bars(self, tjl_mod):
        u, m, l, bw = tjl_mod.calc_bb_bands([100.0] * 10)
        assert (u, m, l, bw) == (None, None, None, None)

    def test_returns_correct_shapes(self, tjl_mod):
        closes = np.array([100.0 + i * 0.1 for i in range(30)])
        u, m, l, bw = tjl_mod.calc_bb_bands(closes)
        assert u.shape == m.shape == l.shape == bw.shape == (30,)

    def test_upper_above_middle_above_lower(self, tjl_mod):
        closes = np.array([100.0 + i * 0.1 for i in range(30)])
        u, m, l, _ = tjl_mod.calc_bb_bands(closes)
        # Drop NaN initial values and check ordering on valid tail
        valid = ~np.isnan(m)
        assert np.all(u[valid] >= m[valid])
        assert np.all(m[valid] >= l[valid])


# ── calc_vwap_bars ────────────────────────────────────────────────────────────

class TestCalcVwapBars:
    def test_returns_array_with_same_length(self, tjl_mod):
        n = 30
        h = [101.0] * n
        l = [99.0] * n
        c = [100.0] * n
        v = [1000] * n
        vwap = tjl_mod.calc_vwap_bars(h, l, c, v)
        assert len(vwap) == n

    def test_constant_bars_yields_constant_vwap(self, tjl_mod):
        n = 20
        h = [101.0] * n
        l = [99.0] * n
        c = [100.0] * n
        v = [1000] * n
        vwap = tjl_mod.calc_vwap_bars(h, l, c, v)
        for v_ in vwap:
            assert abs(v_ - 100.0) < 1e-6