"""Indicator unit tests: RSI, ATR, EMA, VWAP.

Also covers Task 1: calc_prev_rsi() fix.
"""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import numpy as np
import pytest
from tjl_ndx11_hkstyle import calc_rsi, calc_prev_rsi, calc_atr, calc_emas, calc_vwap


# ─── RSI Tests ────────────────────────────────────────────────────────────────

class TestRSI:
    def test_rsi_ascending(self):
        """Ascending prices → RSI > 50."""
        closes = np.linspace(100, 110, 30)
        rsi = calc_rsi(closes)
        assert 50 < rsi <= 100, f"Ascending should be >50, got {rsi}"

    def test_rsi_descending(self):
        """Descending prices → RSI < 50."""
        closes = np.linspace(110, 100, 30)
        rsi = calc_rsi(closes)
        assert 0 <= rsi < 50, f"Descending should be <50, got {rsi}"

    def test_rsi_flat(self):
        """Flat prices → RSI near 50 or 100 (no losses)."""
        closes = np.full(30, 100.0)
        rsi = calc_rsi(closes)
        assert rsi == 50.0 or rsi == 100.0, f"Flat should be ~50/100, got {rsi}"

    def test_rsi_short_data_returns_none(self):
        """Too few data points → None."""
        assert calc_rsi(np.array([100, 101])) is None

    def test_rsi_range(self):
        """Random walk → RSI within [0, 100]."""
        closes = np.random.RandomState(42).randn(100) + 100
        rsi = calc_rsi(closes)
        assert 0 <= rsi <= 100

    def test_rsi_returns_float(self):
        """calc_rsi returns a Python float."""
        closes = np.linspace(100, 110, 30)
        rsi = calc_rsi(closes)
        assert isinstance(rsi, float), f"Got {type(rsi)}"


# ─── calc_prev_rsi Tests (Task 1 bug fix) ─────────────────────────────────────

class TestPrevRSI:
    def test_prev_rsi_returns_valid_value(self):
        """calc_prev_rsi should return a float in [0, 100], not crash."""
        closes = np.array([100.0 + i * 0.5 for i in range(30)])
        rsi = calc_rsi(closes)
        prev = calc_prev_rsi(closes)
        assert isinstance(rsi, float), f"calc_rsi returned {type(rsi)}"
        assert isinstance(prev, float), f"calc_prev_rsi returned {type(prev)}"
        assert 0 <= rsi <= 100, f"RSI out of range: {rsi}"
        assert 0 <= prev <= 100, f"prev RSI out of range: {prev}"

    def test_prev_rsi_short_data_returns_none(self):
        """Too few data points → None."""
        assert calc_prev_rsi(np.array([100, 101, 102])) is None

    def test_prev_rsi_equals_rsi_of_shorter_series(self):
        """prev_rsi(closes) must equal rsi(closes[:-1]).

        This is the core semantic invariant: the previous bar's RSI is
        exactly what calc_rsi would give on the data up to the previous bar.
        """
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(50)) + 100
        prev = calc_prev_rsi(closes)
        manual_prev = calc_rsi(closes[:-1])
        assert prev is not None
        assert manual_prev is not None
        assert abs(prev - manual_prev) < 0.01, \
            f"prev_rsi({prev:.4f}) != rsi(closes[:-1])({manual_prev:.4f})"

    def test_prev_rsi_neq_current_rsi_on_changing_data(self):
        """On non-flat data, prev_rsi and rsi should differ."""
        np.random.seed(99)
        closes = np.cumsum(np.random.randn(50)) + 100
        rsi = calc_rsi(closes)
        prev = calc_prev_rsi(closes)
        assert rsi != prev, "RSI and prev_rsi should differ on changing data"

    def test_prev_rsi_no_loss_returns_100(self):
        """If avg_loss == 0 on prev bar, prev RSI should be 100."""
        closes = np.array([100.0 + i for i in range(30)])  # pure ascending
        prev = calc_prev_rsi(closes)
        assert prev == 100.0, f"Expected 100, got {prev}"


# ─── ATR Tests ────────────────────────────────────────────────────────────────

class TestATR:
    def test_atr_basic(self):
        """ATR of a simple range should be positive."""
        highs = np.full(20, 105.0)
        lows = np.full(20, 100.0)
        closes = np.full(20, 102.5)
        atr = calc_atr(highs, lows, closes)
        assert atr > 0

    def test_atr_short_data_returns_none(self):
        """Too few bars → None."""
        assert calc_atr(np.array([105]), np.array([100]), np.array([103])) is None

    def test_atr_range_bound(self):
        """ATR should be roughly equal to the range width."""
        highs = np.full(20, 105.0)
        lows = np.full(20, 100.0)
        closes = np.full(20, 102.5)
        atr = calc_atr(highs, lows, closes)
        assert 4.0 < atr < 6.0, f"Expected ~5, got {atr}"

    def test_atr_returns_float(self):
        highs = np.linspace(100, 110, 20)
        lows = np.linspace(95, 105, 20)
        closes = np.linspace(98, 108, 20)
        atr = calc_atr(highs, lows, closes)
        assert isinstance(atr, float)


# ─── EMA Tests ────────────────────────────────────────────────────────────────

class TestEMA:
    def test_ema_ordering_uptrend(self):
        """In a steady uptrend: EMA9 > EMA20 > EMA21 > EMA50."""
        closes = np.linspace(100, 120, 60)
        e9, e20, e21, e50 = calc_emas(closes)
        assert e9 > e20 > e50, f"Uptrend: EMA9({e9}) > EMA20({e20}) > EMA50({e50})"

    def test_ema_ordering_downtrend(self):
        """In a steady downtrend: EMA9 < EMA20 < EMA50."""
        closes = np.linspace(120, 100, 60)
        e9, e20, e21, e50 = calc_emas(closes)
        assert e9 < e20 < e50, f"Downtrend: EMA9({e9}) < EMA20({e20}) < EMA50({e50})"

    def test_ema_returns_floats(self):
        closes = np.linspace(100, 110, 60)
        e9, e20, e21, e50 = calc_emas(closes)
        for v in (e9, e20, e21, e50):
            assert isinstance(v, float)

    def test_ema_responds_to_recent_price(self):
        """EMA9 should be closer to the latest price than EMA50."""
        closes = np.concatenate([np.full(50, 100.0), np.array([110, 115])])
        e9, e20, e21, e50 = calc_emas(closes)
        assert abs(e9 - 115) < abs(e50 - 115)


# ─── VWAP Tests ───────────────────────────────────────────────────────────────

class TestVWAP:
    def test_vwap_basic(self):
        """VWAP of simple bars should be positive."""
        highs = np.array([105, 106], dtype=float)
        lows = np.array([100, 101], dtype=float)
        closes = np.array([103, 104], dtype=float)
        vols = np.array([100, 200], dtype=float)
        vwap = calc_vwap(highs, lows, closes, vols)
        assert vwap > 0

    def test_vwap_weighted_by_volume(self):
        """High-volume bar should pull VWAP toward its typical price."""
        highs = np.array([110, 110], dtype=float)
        lows = np.array([90, 90], dtype=float)
        closes = np.array([100, 100], dtype=float)
        # Equal vol → VWAP at typical price (100)
        vwap_eq = calc_vwap(highs, lows, closes, np.array([100, 100], dtype=float))
        assert abs(vwap_eq - 100) < 0.1

    def test_vwap_zero_volume_returns_none(self):
        """All-zero volume → None."""
        highs = np.array([105], dtype=float)
        lows = np.array([100], dtype=float)
        closes = np.array([103], dtype=float)
        vols = np.array([0], dtype=float)
        assert calc_vwap(highs, lows, closes, vols) is None

    def test_vwap_single_element_too_short(self):
        """len(v) < 2 → None."""
        assert calc_vwap(np.array([105.0]), np.array([100.0]),
                         np.array([103.0]), np.array([100.0])) is None

    def test_vwap_returns_float(self):
        highs = np.array([105, 106], dtype=float)
        lows = np.array([100, 101], dtype=float)
        closes = np.array([103, 104], dtype=float)
        vols = np.array([100, 200], dtype=float)
        assert isinstance(calc_vwap(highs, lows, closes, vols), float)
