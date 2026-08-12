"""Tests for futu data fetchers and market regime detection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── get_daily_bars ────────────────────────────────────────────────────────────


def _daily_df(n=80, base=100.0, slope=0.1, vol=1_000_000):
    """Build a futu-shaped daily DataFrame."""
    times = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = np.array([base + slope * i for i in range(n)])
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, vol, dtype=int)
    return pd.DataFrame({
        "time_key": times,
        "open": closes - 0.1,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


class TestGetDailyBars:
    def test_returns_arrays_on_success(self, tjl_mod):
        ctx = MagicMock()
        df = _daily_df()
        ctx.request_history_kline.return_value = (0, df, None)
        highs, lows, closes, volumes = tjl_mod.get_daily_bars(ctx, "HK.00700")
        assert highs is not None
        assert len(highs) == len(closes) == 80

    def test_returns_none_on_failure(self, tjl_mod):
        ctx = MagicMock()
        ctx.request_history_kline.return_value = (-1, None, "error")
        result = tjl_mod.get_daily_bars(ctx, "HK.00700")
        assert result == (None, None, None, None)

    def test_returns_none_on_empty_df(self, tjl_mod):
        ctx = MagicMock()
        ctx.request_history_kline.return_value = (0, pd.DataFrame(), None)
        result = tjl_mod.get_daily_bars(ctx, "HK.00700")
        assert result == (None, None, None, None)

    def test_sorts_by_time(self, tjl_mod):
        ctx = MagicMock()
        df = _daily_df()
        # Shuffle order
        df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
        ctx.request_history_kline.return_value = (0, df, None)
        highs, lows, closes, volumes = tjl_mod.get_daily_bars(ctx, "HK.00700")
        # Verify sorted ascending by time (close[i+1] >= close[i])
        diffs = np.diff(closes)
        assert np.all(diffs >= 0), "expected sorted ascending closes"

    def test_custom_count(self, tjl_mod):
        ctx = MagicMock()
        df = _daily_df(n=120)
        ctx.request_history_kline.return_value = (0, df, None)
        tjl_mod.get_daily_bars(ctx, "HK.00700", count=50)
        # Check the call passed max_count=50
        kwargs = ctx.request_history_kline.call_args.kwargs
        assert kwargs.get("max_count") == 50


# ── get_live_quotes ───────────────────────────────────────────────────────────


class TestGetLiveQuotes:
    def test_subscribes_to_each_code(self, tjl_mod):
        ctx = MagicMock()
        ctx.get_stock_quote.return_value = (0, None)
        codes = ["HK.00700", "HK.09988"]
        tjl_mod.get_live_quotes(ctx, codes)
        # Subscribe called once per code
        assert ctx.subscribe.call_count == len(codes)

    def test_builds_dict_from_quote_rows(self, tjl_mod):
        ctx = MagicMock()
        quote_df = pd.DataFrame([{
            "code": "HK.00700",
            "last_price": 350.0,
            "prev_close_price": 348.0,
            "high_price": 352.0,
            "low_price": 347.0,
            "open_price": 349.0,
            "volume": 1_500_000,
        }])
        ctx.get_stock_quote.return_value = (0, quote_df)
        with patch.object(tjl_mod.time, "sleep"):
            result = tjl_mod.get_live_quotes(ctx, ["HK.00700"])
        assert "HK.00700" in result
        q = result["HK.00700"]
        assert q["price"] == 350.0
        assert q["prev_close"] == 348.0
        assert q["high_today"] == 352.0
        assert q["low_today"] == 347.0
        assert q["open_today"] == 349.0
        assert q["volume"] == 1_500_000

    def test_skips_codes_with_error(self, tjl_mod):
        ctx = MagicMock()
        ctx.get_stock_quote.return_value = (-1, None)
        with patch.object(tjl_mod.time, "sleep"):
            result = tjl_mod.get_live_quotes(ctx, ["HK.00700"])
        assert result == {}

    def test_skips_string_error(self, tjl_mod):
        ctx = MagicMock()
        ctx.get_stock_quote.return_value = (-1, "error string")
        with patch.object(tjl_mod.time, "sleep"):
            result = tjl_mod.get_live_quotes(ctx, ["HK.00700"])
        assert result == {}

    def test_falls_back_to_prev_close_for_missing_open(self, tjl_mod):
        ctx = MagicMock()
        quote_df = pd.DataFrame([{
            "code": "HK.00700",
            "last_price": 350.0,
            "prev_close_price": 348.0,
            "high_price": 352.0,
            "low_price": 347.0,
            "volume": 1_500_000,
            # no 'open_price' key
        }])
        ctx.get_stock_quote.return_value = (0, quote_df)
        with patch.object(tjl_mod.time, "sleep"):
            result = tjl_mod.get_live_quotes(ctx, ["HK.00700"])
        assert result["HK.00700"]["open_today"] == 348.0

    def test_empty_codes_list(self, tjl_mod):
        ctx = MagicMock()
        with patch.object(tjl_mod.time, "sleep"):
            result = tjl_mod.get_live_quotes(ctx, [])
        assert result == {}


# ── detect_regime ─────────────────────────────────────────────────────────────


def _setup_detect_ctx(tjl_mod, df):
    """Build a mock ctx that returns df from request_history_kline."""
    ctx = MagicMock()
    ctx.request_history_kline.return_value = (0, df, None)
    return ctx


class TestDetectRegime:
    def test_bullish_when_most_stacks_bullish(self, tjl_mod):
        df = _daily_df(n=80, base=100.0, slope=0.5)
        ctx = _setup_detect_ctx(tjl_mod, df)
        wl = [("A", "HK.00001"), ("B", "HK.00002"), ("C", "HK.00003"),
              ("D", "HK.00004"), ("E", "HK.00005")]
        regime, bear_pct, bull_pct, n = tjl_mod.detect_regime(ctx, wl)
        assert regime == "bullish"
        assert bull_pct >= 0.6
        assert n == 5

    def test_bearish_when_most_stacks_bearish(self, tjl_mod):
        df = _daily_df(n=80, base=200.0, slope=-0.5)
        ctx = _setup_detect_ctx(tjl_mod, df)
        wl = [("A", "HK.00001"), ("B", "HK.00002"), ("C", "HK.00003"),
              ("D", "HK.00004"), ("E", "HK.00005")]
        regime, bear_pct, bull_pct, n = tjl_mod.detect_regime(ctx, wl)
        assert regime == "bearish"
        assert bear_pct >= 0.6

    def test_neutral_when_no_data(self, tjl_mod):
        ctx = MagicMock()
        ctx.request_history_kline.return_value = (-1, None, None)
        wl = [("A", "HK.00001")]
        regime, bear_pct, bull_pct, n = tjl_mod.detect_regime(ctx, wl)
        assert regime == "neutral"
        assert n == 0

    def test_neutral_when_too_few_bars(self, tjl_mod):
        ctx = _setup_detect_ctx(tjl_mod, _daily_df(n=30))
        wl = [("A", "HK.00001")]
        regime, bear_pct, bull_pct, n = tjl_mod.detect_regime(ctx, wl)
        assert regime == "neutral"
        assert n == 0

    def test_mixed_returns_neutral(self, tjl_mod):
        ctx = MagicMock()
        # Mix of bullish and bearish — needs custom logic
        # 2 bullish + 2 bearish = 50% each → neither reaches 60% threshold → neutral
        bull_df = _daily_df(n=80, base=100.0, slope=0.5)
        bear_df = _daily_df(n=80, base=200.0, slope=-0.5)
        flat_df = _daily_df(n=80, base=100.0, slope=0.0)
        # First 2 are bullish, next 2 bearish, 1 flat → bull 50%, bear 50%, flat 0%
        responses = iter([(0, bull_df, None), (0, bull_df, None),
                          (0, bear_df, None), (0, bear_df, None),
                          (0, flat_df, None)])
        ctx.request_history_kline.side_effect = lambda *a, **kw: next(responses)
        wl = [("A", "HK.00001"), ("B", "HK.00002"), ("C", "HK.00003"),
              ("D", "HK.00004"), ("E", "HK.00005")]
        regime, bear_pct, bull_pct, n = tjl_mod.detect_regime(ctx, wl)
        assert regime == "neutral"


# ── get_intraday_bars_30min ──────────────────────────────────────────────────


class TestGetIntraday30Min:
    def test_returns_high_low_of_first_bar(self, tjl_mod):
        ctx = MagicMock()
        df = pd.DataFrame([
            {"time_key": "2024-05-01 09:30:00", "high": 110.0, "low": 100.0, "close": 105.0},
            {"time_key": "2024-05-01 10:00:00", "high": 112.0, "low": 103.0, "close": 108.0},
            {"time_key": "2024-05-01 10:30:00", "high": 115.0, "low": 105.0, "close": 112.0},
        ])
        ctx.request_history_kline.return_value = (0, df, None)
        high, low = tjl_mod.get_intraday_bars_30min(ctx, "HK.00700")
        assert high == 110.0
        assert low == 100.0

    def test_returns_none_on_failure(self, tjl_mod):
        ctx = MagicMock()
        ctx.request_history_kline.return_value = (-1, None, None)
        high, low = tjl_mod.get_intraday_bars_30min(ctx, "HK.00700")
        assert (high, low) == (None, None)

    def test_returns_none_on_empty_df(self, tjl_mod):
        ctx = MagicMock()
        ctx.request_history_kline.return_value = (0, pd.DataFrame(), None)
        high, low = tjl_mod.get_intraday_bars_30min(ctx, "HK.00700")
        assert (high, low) == (None, None)

    def test_sorts_then_picks_first(self, tjl_mod):
        ctx = MagicMock()
        # Reversed order
        df = pd.DataFrame([
            {"time_key": "2024-05-01 10:30:00", "high": 115.0, "low": 105.0, "close": 112.0},
            {"time_key": "2024-05-01 10:00:00", "high": 112.0, "low": 103.0, "close": 108.0},
            {"time_key": "2024-05-01 09:30:00", "high": 110.0, "low": 100.0, "close": 105.0},
        ])
        ctx.request_history_kline.return_value = (0, df, None)
        high, low = tjl_mod.get_intraday_bars_30min(ctx, "HK.00700")
        assert high == 110.0
        assert low == 100.0
