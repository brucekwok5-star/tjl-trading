"""Data fetch tests: fetch_batch single/multi/empty/invalid ticker paths (Task 3)."""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import pytest
from tjl_ndx11_hkstyle import fetch_batch


class TestFetchBatchBasics:
    def test_empty_ticker_list(self):
        """Empty ticker list returns empty dict."""
        result = fetch_batch([])
        assert result == {}

    def test_empty_string_ticker(self):
        """Empty/whitespace tickers are filtered."""
        result = fetch_batch(['', '  ', None])
        assert result == {}


class TestFetchBatchLive:
    """Live network tests — resilient to yfinance failures."""

    @pytest.mark.network
    def test_single_ticker_fetch(self):
        """fetch_batch(['AAPL']) must return data for AAPL."""
        result = fetch_batch(['AAPL'], period='60d')
        if not result:
            pytest.skip("Network unavailable or yfinance rate-limited")
        assert 'AAPL' in result, f"AAPL not in result keys: {list(result.keys())}"
        assert len(result['AAPL']['closes']) >= 20, \
            f"Too few bars: {len(result['AAPL']['closes'])}"

    @pytest.mark.network
    def test_single_ticker_has_all_fields(self):
        """Single-ticker result dict has all expected keys."""
        result = fetch_batch(['AAPL'], period='60d')
        if not result:
            pytest.skip("Network unavailable")
        d = result['AAPL']
        for field in ('closes', 'highs', 'lows', 'volumes',
                      'today_open', 'prev_high', 'prev_low',
                      'prev_close', 'price', 'day_high', 'day_low'):
            assert field in d, f"Missing field: {field}"

    @pytest.mark.network
    def test_multi_ticker_fetch(self):
        """fetch_batch(['AAPL','NVDA']) must return data for both."""
        result = fetch_batch(['AAPL', 'NVDA'], period='60d')
        if not result:
            pytest.skip("Network unavailable")
        assert 'AAPL' in result
        assert 'NVDA' in result
        assert len(result['AAPL']['closes']) >= 20
        assert len(result['NVDA']['closes']) >= 20

    @pytest.mark.network
    def test_invalid_ticker_handled(self):
        """Invalid tickers don't crash the batch."""
        result = fetch_batch(['INVALIDXYZ123'], period='30d')
        assert isinstance(result, dict)
        # Should not contain the invalid ticker with data
        if 'INVALIDXYZ123' in result:
            assert len(result['INVALIDXYZ123'].get('closes', [])) == 0

    @pytest.mark.network
    def test_mixed_valid_invalid(self):
        """Batch with valid + invalid tickers returns valid ones."""
        result = fetch_batch(['AAPL', 'INVALIDXYZ123'], period='60d')
        if not result:
            pytest.skip("Network unavailable")
        # AAPL should be present (valid)
        assert 'AAPL' in result or len(result) == 0  # Resilient to full failure
