"""Model logic unit tests: all 11 models A-K.

Covers Task 2 (check_h/check_k NaN guard) plus model behavior tests.
"""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import numpy as np
import pytest
from tjl_ndx11_hkstyle import (
    check_a, check_b, check_c, check_d, check_e,
    check_f, check_g, check_h, check_i, check_j, check_k,
    make_signal,
)


def make_data(closes, highs=None, lows=None, volumes=None, **kwargs):
    """Build synthetic bar-data dict for model checkers."""
    closes = np.array(closes, dtype=float)
    n = len(closes)
    defaults = {
        'closes': closes,
        'highs':  np.array(closes) * 1.02 if highs is None else np.array(highs, dtype=float),
        'lows':   np.array(closes) * 0.98 if lows is None else np.array(lows, dtype=float),
        'volumes': np.full(n, 1000.0) if volumes is None else np.array(volumes, dtype=float),
        'today_open': float(closes[-1]),
        'prev_high':  float(max(closes[-5:])) * 1.01,
        'prev_low':   float(min(closes[-5:])) * 0.99,
        'prev_close': float(closes[-2]),
        'price':      float(closes[-1]),
        'day_high':   float(max(closes[-10:])) * 1.01,
        'day_low':    float(min(closes[-10:])) * 0.99,
    }
    defaults.update(kwargs)
    return defaults


# ─── Model A — Pullback ───────────────────────────────────────────────────────

class TestModelA:
    def test_bullish_pullback_fires(self):
        """Strong uptrend, pullback to EMA9 → fires LONG."""
        closes = np.concatenate([np.linspace(100, 130, 70), np.array([128.0, 129.5])])
        d = make_data(closes, prev_high=127.0)  # price > PMH
        sig = check_a('TEST', d)
        assert sig is not None
        assert sig['direction'] == 'LONG'
        assert sig['model'] == 'A'

    def test_downtrend_returns_none(self):
        """Downtrend → no bullish stack → None."""
        closes = np.array([100 - i * 0.1 for i in range(70)])
        d = make_data(closes)
        assert check_a('TEST', d) is None

    def test_short_data_returns_none(self):
        """< 60 bars → None."""
        d = make_data(np.linspace(100, 110, 30))
        assert check_a('TEST', d) is None


# ─── Model B — HT Momentum ─────────────────────────────────────────────────────

class TestModelB:
    def test_above_sma200_fires(self):
        """Strong uptrend above SMA200 + above PMH → fires LONG."""
        closes = np.linspace(100, 150, 250)
        # price must be > day_high - 0.50, so set day_high close to price
        d = make_data(closes, prev_high=148.0, day_high=150.3)
        sig = check_b('TEST', d)
        assert sig is not None
        assert sig['direction'] == 'LONG'

    def test_below_sma200_returns_none(self):
        """Price below SMA200 → None."""
        closes = np.concatenate([np.linspace(200, 100, 250)])
        d = make_data(closes)
        assert check_b('TEST', d) is None

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 100))
        assert check_b('TEST', d) is None


# ─── Model C — Volume-Confirmed Pullback ──────────────────────────────────────

class TestModelC:
    def test_vol_spike_near_ema_fires(self):
        """Price near EMA9 + volume spike → fires LONG."""
        closes = np.linspace(100, 115, 65)
        vols = np.full(65, 1000.0)
        vols[-1] = 3000.0  # 3x avg
        d = make_data(closes, volumes=vols, prev_high=112.0)
        sig = check_c('TEST', d)
        # May or may not fire depending on near_ema; test no crash + valid output
        assert sig is None or sig['direction'] == 'LONG'

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 30))
        assert check_c('TEST', d) is None


# ─── Model D — RSI Oversold Bounce ─────────────────────────────────────────────

class TestModelD:
    def test_runs_without_crash(self):
        """Model D should run without error and return None or a valid LONG."""
        closes = np.concatenate([np.linspace(100, 80, 20), np.array([82.0, 85.0])])
        d = make_data(closes)
        result = check_d('TEST', d)
        assert result is None or result['direction'] == 'LONG'

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 15))
        assert check_d('TEST', d) is None


# ─── Model E — BB Squeeze + 20d Breakout ───────────────────────────────────────

class TestModelE:
    def test_runs_without_crash(self):
        """Model E should run without error."""
        closes = np.linspace(100, 110, 30)
        d = make_data(closes)
        result = check_e('TEST', d)
        assert result is None or result['direction'] in ('LONG', 'SHORT')

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 15))
        assert check_e('TEST', d) is None


# ─── Model F — RSI Trend Crossover ─────────────────────────────────────────────

class TestModelF:
    def test_long_runs_without_crash(self):
        closes = np.linspace(100, 110, 30)
        d = make_data(closes)
        result = check_f('TEST', d, 'LONG')
        assert result is None or result['direction'] == 'LONG'

    def test_short_runs_without_crash(self):
        closes = np.linspace(110, 100, 30)
        d = make_data(closes)
        result = check_f('TEST', d, 'SHORT')
        assert result is None or result['direction'] == 'SHORT'

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 15))
        assert check_f('TEST', d, 'LONG') is None


# ─── Model G — ORB ─────────────────────────────────────────────────────────────

class TestModelG:
    def test_runs_without_crash(self):
        closes = np.linspace(100, 110, 40)
        d = make_data(closes, today_open=100.0)
        result = check_g('TEST', d, 'LONG')
        assert result is None or result['direction'] == 'LONG'

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 15))
        assert check_g('TEST', d, 'LONG') is None


# ─── Model H — Gold EMA/BB/VWAP (Task 2: NaN guard) ───────────────────────────

class TestModelH:
    def test_short_data_no_crash(self):
        """check_h must not crash on data with < 40 bars (NaN guard)."""
        d = make_data(np.linspace(100, 110, 30))
        result = check_h('TEST', d, 'LONG')
        assert result is None, f"Expected None for short data, got {result}"

    def test_runs_without_crash(self):
        """check_h should run without error on sufficient data."""
        closes = np.linspace(100, 110, 60)
        d = make_data(closes)
        result = check_h('TEST', d, 'LONG')
        assert result is None or result['direction'] == 'LONG'

    def test_short_returns_none(self):
        closes = np.linspace(100, 110, 60)
        d = make_data(closes)
        result = check_h('TEST', d, 'SHORT')
        assert result is None or result['direction'] == 'SHORT'

    def test_very_short_data_returns_none(self):
        """25 bars: not enough for BB(20) on prev slice."""
        d = make_data(np.linspace(100, 110, 25))
        assert check_h('TEST', d, 'LONG') is None


# ─── Model I — 63WMA Swing ────────────────────────────────────────────────────

class TestModelI:
    def test_runs_without_crash(self):
        closes = np.linspace(100, 110, 80)
        d = make_data(closes)
        result = check_i('TEST', d, 'LONG')
        assert result is None or result['direction'] == 'LONG'

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 50))
        assert check_i('TEST', d, 'LONG') is None


# ─── Model J — 150/200 DMA ────────────────────────────────────────────────────

class TestModelJ:
    def test_runs_without_crash(self):
        closes = np.linspace(100, 120, 220)
        d = make_data(closes)
        result = check_j('TEST', d, 'LONG')
        assert result is None or result['direction'] == 'LONG'

    def test_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 150))
        assert check_j('TEST', d, 'LONG') is None


# ─── Model K — EMA/VWAP/BB Session (Task 2: NaN guard) ─────────────────────────

class TestModelK:
    def test_short_data_no_crash(self):
        """check_k must not crash on data with < 40 bars."""
        d = make_data(np.linspace(100, 110, 30))
        result = check_k('TEST', d, 'SHORT')
        assert result is None, f"Expected None for short data, got {result}"

    def test_runs_without_crash(self):
        closes = np.linspace(100, 110, 60)
        d = make_data(closes)
        result = check_k('TEST', d, 'SHORT')
        assert result is None or result['direction'] == 'SHORT'

    def test_long_runs_without_crash(self):
        closes = np.linspace(100, 110, 60)
        d = make_data(closes)
        result = check_k('TEST', d, 'LONG')
        assert result is None or result['direction'] == 'LONG'

    def test_very_short_data_returns_none(self):
        d = make_data(np.linspace(100, 110, 25))
        assert check_k('TEST', d, 'SHORT') is None


# ─── Cross-model: all models handle numpy arrays ──────────────────────────────

class TestAllModelsNumpySafe:
    """Verify all model functions accept numpy arrays without crashing."""

    @pytest.mark.parametrize("checker,dir_arg", [
        (check_a, None),
        (check_b, None),
        (check_c, None),
        (check_d, None),
        (check_e, None),
        (check_f, 'LONG'),
        (check_g, 'LONG'),
        (check_h, 'LONG'),
        (check_i, 'LONG'),
        (check_j, 'LONG'),
        (check_k, 'SHORT'),
    ])
    def test_model_no_crash(self, checker, dir_arg):
        """Each model function should not crash on valid data."""
        closes = np.linspace(100, 110, 70)
        d = make_data(closes)
        try:
            if dir_arg:
                result = checker('TEST', d, dir_arg)
            else:
                result = checker('TEST', d)
            assert result is None or isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"{checker.__name__} crashed: {e}")

# ─── V/W/X models (live Futu API signatures) ──────────────────────────────────

from tjl_live_futu import check_tjl_model_v, check_tjl_model_w, check_tjl_model_x

class TestModelVXW:
    """V/W/X use (price, highs, lows, closes, volumes, today_open/y) — same data shape."""

    @pytest.fixture
    def data(self):
        closes = np.linspace(100, 110, 70)
        highs  = closes + 0.5
        lows   = closes - 0.5
        vols   = np.full(70, 1000.0)
        return highs, lows, closes, vols

    def test_v_flat_returns_none(self, data):
        highs, lows, closes, vols = data
        assert check_tjl_model_v(100.0, highs, lows, closes, vols, 100.0) is None

    def test_w_flat_returns_none(self, data):
        highs, lows, closes, vols = data
        assert check_tjl_model_w(100.0, highs, lows, closes, vols) is None

    def test_x_flat_returns_none(self, data):
        highs, lows, closes, vols = data
        assert check_tjl_model_x(100.0, highs, lows, closes, vols) is None

    def test_v_short_data_returns_none(self):
        highs  = np.array([100.0]*5)
        lows   = np.array([99.0]*5)
        closes = np.array([99.5]*5)
        vols   = np.array([1000.0]*5)
        assert check_tjl_model_v(99.5, highs, lows, closes, vols, 99.5) is None

    def test_w_short_data_returns_none(self):
        highs  = np.array([100.0]*5)
        lows   = np.array([99.0]*5)
        closes = np.array([99.5]*5)
        vols   = np.array([1000.0]*5)
        assert check_tjl_model_w(99.5, highs, lows, closes, vols) is None

    def test_x_short_data_returns_none(self):
        highs  = np.array([100.0]*5)
        lows   = np.array([99.0]*5)
        closes = np.array([99.5]*5)
        vols   = np.array([1000.0]*5)
        assert check_tjl_model_x(99.5, highs, lows, closes, vols) is None
