"""Regime detection tests (Task 8)."""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import pytest
from tjl_ndx11_hkstyle import can_long, can_short, REGIME_CACHE


class TestRegimeRouting:
    def test_can_long_bullish(self):
        assert can_long('BULLISH') is True

    def test_can_long_neutral(self):
        assert can_long('neutral') is True

    def test_can_long_bearish(self):
        assert can_long('BEARISH') is False

    def test_can_short_bearish(self):
        assert can_short('BEARISH') is True

    def test_can_short_neutral(self):
        assert can_short('neutral') is True

    def test_can_short_bullish(self):
        assert can_short('BULLISH') is False


class TestRegimeCache:
    """REGIME_CACHE structure tests — the caching mechanism itself."""

    def test_cache_is_dict(self):
        assert isinstance(REGIME_CACHE, dict)

    def test_cache_keys(self):
        assert 'result' in REGIME_CACHE
        assert 'timestamp' in REGIME_CACHE

    def test_cache_initially_empty(self):
        # Fresh import — cache should be empty
        from tjl_ndx11_hkstyle import REGIME_CACHE as rc
        assert rc['result'] is None
        assert rc['timestamp'] == 0.0

    def test_cache_can_be_set(self):
        import tjl_ndx11_hkstyle as s
        s.REGIME_CACHE = {'result': 'BULLISH', 'timestamp': 1234567890.0}
        assert s.REGIME_CACHE['result'] == 'BULLISH'
        # Clean up
        s.REGIME_CACHE = {'result': None, 'timestamp': 0.0}
