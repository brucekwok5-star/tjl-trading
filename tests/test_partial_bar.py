#!/usr/bin/env python3
"""
Phase 4 — Partial-Bar Fix Tests

Unit tests for is_market_hours() and get_safe_price() in tjl_ndx11_hkstyle.py.

These tests monkeypatch datetime.now() to inject fixed times so they are
deterministic and independent of when they are run.
"""
import pytest
import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

import tjl_ndx11_hkstyle as tj

ET = ZoneInfo("America/New_York")


# ──────────────────────────────────────────────────────────────────────────────
# is_market_hours()
# ──────────────────────────────────────────────────────────────────────────────
class TestIsMarketHours:
    @patch('tjl_ndx11_hkstyle.datetime')
    def test_true_at_10am_weekday(self, mock_dt):
        """10:00 ET Monday → market open → True."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 10, 0, 0, tzinfo=ET)
        # datetime.now() is mocked, so datetime.now(ET) returns the value above
        assert tj.is_market_hours() is True

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_true_at_930am(self, mock_dt):
        """9:30 ET exactly → market open → True."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 9, 30, 0, tzinfo=ET)
        assert tj.is_market_hours() is True

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_true_at_359pm(self, mock_dt):
        """15:59 ET → still within RTH → True."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 15, 59, 0, tzinfo=ET)
        assert tj.is_market_hours() is True

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_false_at_400pm(self, mock_dt):
        """16:00 ET → market closed → False."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 16, 0, 0, tzinfo=ET)
        assert tj.is_market_hours() is False

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_false_at_pre_market(self, mock_dt):
        """9:29 ET → before open → False."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 9, 29, 0, tzinfo=ET)
        assert tj.is_market_hours() is False

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_false_at_midnight(self, mock_dt):
        """00:00 ET → False."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 0, 0, 0, tzinfo=ET)
        assert tj.is_market_hours() is False

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_false_on_saturday(self, mock_dt):
        """Saturday at noon → False."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 8, 12, 0, 0, tzinfo=ET)
        assert tj.is_market_hours() is False

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_false_on_sunday(self, mock_dt):
        """Sunday at noon → False."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 9, 12, 0, 0, tzinfo=ET)
        assert tj.is_market_hours() is False

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_false_at_120pm(self, mock_dt):
        """12:00 ET → market open → True (midday test)."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 12, 0, 0, tzinfo=ET)
        assert tj.is_market_hours() is True

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_false_after_hours_evening(self, mock_dt):
        """18:00 ET → after hours → False."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 18, 0, 0, tzinfo=ET)
        assert tj.is_market_hours() is False


# ──────────────────────────────────────────────────────────────────────────────
# get_safe_price()
# ──────────────────────────────────────────────────────────────────────────────
class TestGetSafePrice:
    @pytest.fixture
    def ticker_data(self):
        """Synthetic ticker_data dict with prev_close and current price."""
        return {
            'prev_close': 100.00,
            'price':      102.50,
        }

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_returns_prev_close_during_market_hours(self, mock_dt, ticker_data):
        """During RTH → should return prev_close, NOT partial-bar price."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 11, 30, 0, tzinfo=ET)
        result = tj.get_safe_price(ticker_data)
        assert result == 100.00, f"Expected prev_close 100.00 during RTH, got {result}"
        assert result != ticker_data['price'], "Should NOT return partial-bar price during RTH"

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_returns_current_price_after_close(self, mock_dt, ticker_data):
        """After market close → should return current (complete) price."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 16, 30, 0, tzinfo=ET)
        result = tj.get_safe_price(ticker_data)
        assert result == 102.50, f"Expected current price 102.50 after close, got {result}"

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_returns_current_price_on_weekend(self, mock_dt, ticker_data):
        """Weekend → should return current price (market closed)."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 9, 12, 0, 0, tzinfo=ET)  # Sunday
        result = tj.get_safe_price(ticker_data)
        assert result == 102.50, f"Expected current price 102.50 on weekend, got {result}"

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_returns_current_price_pre_market(self, mock_dt, ticker_data):
        """Pre-market → should return current price."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 8, 0, 0, tzinfo=ET)
        result = tj.get_safe_price(ticker_data)
        assert result == 102.50, f"Expected current price 102.50 pre-market, got {result}"

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_safe_price_differs_from_raw_when_partial(self, mock_dt, ticker_data):
        """During RTH, safe price ≠ raw partial-bar price (the bug being fixed)."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 11, 0, 0, tzinfo=ET)
        safe = tj.get_safe_price(ticker_data)
        raw  = ticker_data['price']
        assert safe != raw, f"Safe price {safe} should differ from partial raw {raw} during RTH"

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_safe_price_equals_raw_after_close(self, mock_dt, ticker_data):
        """After close, safe price == raw price (bar is complete)."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 17, 0, 0, tzinfo=ET)
        safe = tj.get_safe_price(ticker_data)
        raw  = ticker_data['price']
        assert safe == raw, f"Safe price {safe} should equal raw {raw} after close"


# ──────────────────────────────────────────────────────────────────────────────
# Integration: fetch_batch uses get_safe_price logic
# ──────────────────────────────────────────────────────────────────────────────
class TestFetchBatchPartialBarIntegration:
    @patch('tjl_ndx11_hkstyle.datetime')
    def test_fetch_batch_sets_raw_price_field(self, mock_dt):
        """fetch_batch results should have a 'raw_price' field for reference."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 11, 0, 0, tzinfo=ET)
        batch = tj.fetch_batch(['AAPL'], period='60d')
        if 'AAPL' not in batch:
            pytest.skip("No AAPL data (network?)")
        assert 'raw_price' in batch['AAPL'], "fetch_batch must set 'raw_price' field"
        assert isinstance(batch['AAPL']['raw_price'], float)

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_fetch_batch_price_uses_safe_during_market(self, mock_dt):
        """During RTH, fetch_batch 'price' should equal prev_close, not raw_price."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 11, 30, 0, tzinfo=ET)
        batch = tj.fetch_batch(['AAPL'], period='60d')
        if 'AAPL' not in batch:
            pytest.skip("No AAPL data (network?)")
        d = batch['AAPL']
        assert d['price'] == d['prev_close'], \
            f"During RTH price ({d['price']}) should == prev_close ({d['prev_close']})"

    @patch('tjl_ndx11_hkstyle.datetime')
    def test_fetch_batch_price_equals_raw_after_close(self, mock_dt):
        """After close, fetch_batch 'price' should equal 'raw_price'."""
        mock_dt.now.return_value = datetime.datetime(2026, 8, 10, 17, 0, 0, tzinfo=ET)
        batch = tj.fetch_batch(['AAPL'], period='60d')
        if 'AAPL' not in batch:
            pytest.skip("No AAPL data (network?)")
        d = batch['AAPL']
        assert d['price'] == d['raw_price'], \
            f"After close price ({d['price']}) should == raw_price ({d['raw_price']})"
