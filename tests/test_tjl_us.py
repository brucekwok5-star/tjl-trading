"""Comprehensive tests for tjl_live_us.py (US market TJL scanner via yfinance).

Tests the v2 API: simple 3-condition model with both TJL LONG and TJS SHORT.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── Stub yfinance so the module imports without network ───────────────────────
@pytest.fixture(scope="session", autouse=True)
def stub_yfinance():
    yf_pkg = types.ModuleType("yfinance")
    yf_pkg.Ticker = type("T", (), {})
    sys.modules["yfinance"] = yf_pkg
    yield yf_pkg


@pytest.fixture(scope="session")
def tjl_us(stub_yfinance):
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tjl_live_us.py",
    )
    spec = importlib.util.spec_from_file_location("tjl_live_us", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tjl_live_us"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Synthetic data helpers ────────────────────────────────────────────────────
def _uptrend(n=80, base=100.0, slope=0.10, vol=1_000_000):
    closes = np.array([base + slope * i for i in range(n)])
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, vol, dtype=int)
    return highs, lows, closes, volumes


def _downtrend(n=80, base=200.0, slope=0.05, vol=1_000_000):
    closes = np.array([base - slope * i for i in range(n)])
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, vol, dtype=int)
    return highs, lows, closes, volumes


def _oscillating(n=80, base=100.0, step=1.0, vol=1_000_000):
    closes = np.array([base + (step if i % 2 == 0 else -step) for i in range(n)])
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, vol, dtype=int)
    return highs, lows, closes, volumes


def _bars_df(n=80, base=100.0, slope=0.1):
    closes = np.array([base + slope * i for i in range(n)])
    return pd.DataFrame({
        "Open": closes - 0.1,
        "High": closes + 0.5,
        "Low":  closes - 0.5,
        "Close": closes,
        "Volume": np.full(n, 1_000_000),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def _downtrend_df(n=250, base=300.0, slope=0.5):
    closes = np.array([base - slope * i for i in range(n)])
    return pd.DataFrame({
        "Open": closes - 0.1,
        "High": closes + 0.5,
        "Low":  closes - 0.5,
        "Close": closes,
        "Volume": np.full(n, 1_000_000),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


# ── Constants ─────────────────────────────────────────────────────────────────

class TestUsConstants:
    def test_pmh_buf(self, tjl_us):
        assert tjl_us.PMH_BUF == 0.70

    def test_atr_constants(self, tjl_us):
        assert tjl_us.ATR_SL == 1.5
        assert tjl_us.ATR_TP == 3.0
        assert tjl_us.ATR_PERIOD == 14

    def test_near_ema_pct(self, tjl_us):
        assert tjl_us.NEAR_EMA_PCT == 0.002

    def test_scan_interval(self, tjl_us):
        assert tjl_us.SCAN_INTERVAL > 0

    def test_timezones(self, tjl_us):
        assert str(tjl_us.ET) == "America/New_York"
        assert str(tjl_us.HKT) == "Asia/Hong_Kong"


class TestUsWatchlist:
    def test_watchlist_non_empty(self, tjl_us):
        assert len(tjl_us.DEFAULT_WATCHLIST) >= 20

    def test_watchlist_items_are_pairs(self, tjl_us):
        for item in tjl_us.DEFAULT_WATCHLIST:
            assert len(item) == 2
            ticker, name = item
            assert isinstance(ticker, str) and ticker
            assert isinstance(name, str) and name

    def test_no_duplicate_tickers(self, tjl_us):
        tickers = [t for t, _ in tjl_us.DEFAULT_WATCHLIST]
        assert len(tickers) == len(set(tickers))

    def test_contains_mega_caps(self, tjl_us):
        tickers = {t for t, _ in tjl_us.DEFAULT_WATCHLIST}
        for must in ("NVDA", "TSLA", "AAPL", "MSFT", "META"):
            assert must in tickers


# ── Math helpers ──────────────────────────────────────────────────────────────

class TestUsCalcEmas:
    def test_returns_three_floats(self, tjl_us):
        closes = [100.0 + 0.1 * i for i in range(60)]
        result = tjl_us.calc_emas(closes)
        assert len(result) == 3
        for v in result:
            assert isinstance(v, float)

    def test_bullish_stack_on_uptrend(self, tjl_us):
        closes = [100.0 + 0.1 * i for i in range(60)]
        e9, e20, e50 = tjl_us.calc_emas(closes)
        assert e9 > e20 > e50

    def test_bearish_stack_on_downtrend(self, tjl_us):
        closes = [200.0 - 0.05 * i for i in range(60)]
        e9, e20, e50 = tjl_us.calc_emas(closes)
        assert e9 < e20 < e50

    def test_flat_series_converges(self, tjl_us):
        e9, e20, e50 = tjl_us.calc_emas([100.0] * 80)
        assert abs(e9 - 100.0) < 1e-9
        assert abs(e20 - 100.0) < 1e-9
        assert abs(e50 - 100.0) < 1e-9


class TestUsCalcAtr:
    def test_symmetric_range_yields_range(self, tjl_us):
        closes = [100.0] * 60
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        atr = tjl_us.calc_atr(highs, lows, closes)
        assert atr is not None and 0.95 < atr < 1.05

    def test_returns_none_when_too_few_trs(self, tjl_us):
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        assert tjl_us.calc_atr(highs, lows, closes, period=14) is None

    def test_handles_gap_up(self, tjl_us):
        closes = [100.0] * 15
        highs = [101.0] * 14 + [120.0]
        lows = [99.0] * 14 + [118.0]
        atr = tjl_us.calc_atr(highs, lows, closes)
        assert atr is not None and atr > 1.0


# ── Market hours & regime ──────────────────────────────────────────────────────

class TestUsMarketHours:
    def test_weekend_returns_false(self, tjl_us):
        original = tjl_us.datetime
        try:
            class FakeDT:
                @staticmethod
                def now(tz=None):
                    return original(2026, 8, 8, 12, 0, tzinfo=tjl_us.ET)
            tjl_us.datetime = FakeDT
            assert tjl_us.get_us_market_open() is False
        finally:
            tjl_us.datetime = original

    def test_weekday_before_open_returns_false(self, tjl_us):
        original = tjl_us.datetime
        try:
            class FakeDT:
                @staticmethod
                def now(tz=None):
                    return original(2026, 8, 4, 9, 0, tzinfo=tjl_us.ET)
            tjl_us.datetime = FakeDT
            assert tjl_us.get_us_market_open() is False
        finally:
            tjl_us.datetime = original

    def test_weekday_mid_session_returns_true(self, tjl_us):
        original = tjl_us.datetime
        try:
            class FakeDT:
                @staticmethod
                def now(tz=None):
                    return original(2026, 8, 4, 10, 0, tzinfo=tjl_us.ET)
            tjl_us.datetime = FakeDT
            assert tjl_us.get_us_market_open() is True
        finally:
            tjl_us.datetime = original

    def test_weekday_after_close_returns_false(self, tjl_us):
        original = tjl_us.datetime
        try:
            class FakeDT:
                @staticmethod
                def now(tz=None):
                    return original(2026, 8, 4, 16, 30, tzinfo=tjl_us.ET)
            tjl_us.datetime = FakeDT
            assert tjl_us.get_us_market_open() is False
        finally:
            tjl_us.datetime = original


class TestUsGetRegime:
    def test_bullish_when_both_up(self, tjl_us):
        spy = pd.DataFrame({"Close": [100.0, 101.0]})
        qqq = pd.DataFrame({"Close": [200.0, 201.0]})
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.side_effect = [spy, qqq]
            assert tjl_us.get_regime() == "BULLISH"

    def test_bearish_when_spy_down(self, tjl_us):
        spy = pd.DataFrame({"Close": [100.0, 99.0]})
        qqq = pd.DataFrame({"Close": [200.0, 201.0]})
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.side_effect = [spy, qqq]
            assert tjl_us.get_regime() == "BEARISH"

    def test_unknown_when_insufficient_history(self, tjl_us):
        spy = pd.DataFrame({"Close": [100.0]})
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = spy
            assert tjl_us.get_regime() == "UNKNOWN"

    def test_unknown_on_exception(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.side_effect = RuntimeError
            assert tjl_us.get_regime() == "UNKNOWN"


# ── Data fetchers ─────────────────────────────────────────────────────────────

class TestUsGetDailyBars:
    def test_returns_3_tuple_on_success(self, tjl_us):
        df = _bars_df()
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = df
            result = tjl_us.get_daily_bars("NVDA")
        assert result is not None
        # Returns (highs, lows, closes) — 3-tuple in v2
        assert len(result) == 3
        highs, lows, closes = result
        assert len(highs) == 80
        assert len(lows) == 80
        assert len(closes) == 80

    def test_returns_none_tuple_when_empty(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = pd.DataFrame()
            result = tjl_us.get_daily_bars("NVDA")
        assert result == (None, None, None)

    def test_returns_none_on_exception(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.side_effect = RuntimeError("network")
            result = tjl_us.get_daily_bars("NVDA")
        assert result == (None, None, None)

    def test_drops_nan_close_rows(self, tjl_us):
        dates = pd.date_range("2025-01-01", periods=80, freq="D")
        df = _bars_df().copy()
        df.index = dates
        df.loc[dates[5], "Close"] = np.nan
        df.loc[dates[6], "Close"] = np.nan
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = df
            result = tjl_us.get_daily_bars("NVDA")
        assert result is not None
        highs, lows, closes = result
        assert not np.isnan(closes).any()

    def test_returns_none_when_too_few_bars(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = _bars_df(n=20)
            result = tjl_us.get_daily_bars("NVDA")
        assert result == (None, None, None)


class TestUsGetLivePrice:
    def test_returns_dict_with_fast_info(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.fast_info = {
                "regularMarketPrice": 150.0,
                "previousClose": 148.0,
                "dayHigh": 151.0,
                "dayLow": 147.0,
            }
            q = tjl_us.get_live_price("NVDA")
        assert q["price"] == 150.0
        assert q["prev_close"] == 148.0
        assert q["day_high"] == 151.0
        assert q["day_low"] == 147.0

    def test_falls_back_to_history(self, tjl_us):
        # Use a real class (not MagicMock) because v2's get_live_price returns
        # None for prev_close when fast_info is the empty {} that MagicMock
        # returns from auto-attribute access on tk.fast_info.
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        hist = pd.DataFrame({
            "Close": [145.0, 147.0, 149.0],
            "High":  [146.0, 148.0, 150.0],
            "Low":   [144.0, 146.0, 148.0],
        }, index=dates)

        class _RealTicker:
            fast_info = {}
            def history(self, period):
                return hist

        with patch.object(tjl_us.yf, "Ticker", return_value=_RealTicker()):
            q = tjl_us.get_live_price("NVDA")
        assert q["price"] == 149.0
        assert q["prev_close"] == 147.0

    def test_returns_none_when_no_data(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.fast_info = {}
            mock_tk.return_value.history.return_value = pd.DataFrame()
            q = tjl_us.get_live_price("NVDA")
        assert q is None

    def test_returns_none_on_exception(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.fast_info = {}
            mock_tk.return_value.history.side_effect = RuntimeError
            q = tjl_us.get_live_price("NVDA")
        assert q is None


class TestUsGetPremarket:
    def _setup_bars(self, n=10, tz="US/Eastern"):
        idx = pd.date_range("2025-01-01 04:30", periods=n, freq="1min", tz=tz)
        return idx

    def test_premarket_high_returns_value(self, tjl_us):
        idx = self._setup_bars()
        df = pd.DataFrame({"High": np.linspace(100, 110, 10)}, index=idx)
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = df
            h = tjl_us.get_premarket_high("NVDA")
        assert h == 110.0

    def test_premarket_low_returns_value(self, tjl_us):
        idx = self._setup_bars()
        df = pd.DataFrame({"Low": np.linspace(100, 90, 10)}, index=idx)
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = df
            low = tjl_us.get_premarket_low("NVDA")
        assert low == 90.0

    def test_premarket_high_none_on_empty(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.return_value = pd.DataFrame()
            assert tjl_us.get_premarket_high("NVDA") is None

    def test_premarket_high_none_on_exception(self, tjl_us):
        with patch.object(tjl_us.yf, "Ticker") as mock_tk:
            mock_tk.return_value.history.side_effect = RuntimeError
            assert tjl_us.get_premarket_high("NVDA") is None


# ── check_tjl (Model A LONG) ──────────────────────────────────────────────────

class TestUsCheckTjl:
    def test_passes_when_all_conditions_true(self, tjl_us):
        h, l, c, _ = _uptrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        prev_day_high = price - 10.0
        res, reason = tjl_us.check_tjl(
            "NVDA", "NVIDIA", price, day_high=price - 5.0,
            prev_day_high=prev_day_high, highs=h, lows=l, closes=c,
        )
        assert res is not None, f"got None with reason: {reason}"
        assert reason is None
        assert res["direction"] == "LONG"
        assert res["sl"] < res["price"] < res["tp"]

    def test_returns_none_with_reason_when_few_bars(self, tjl_us):
        h, l, c, _ = _uptrend(n=30)
        res, reason = tjl_us.check_tjl(
            "NVDA", "NVIDIA", 100.0, 100.0, 100.0, h, l, c,
        )
        assert res is None
        assert reason is not None and "insufficient bars" in reason

    def test_returns_none_with_reason_when_far_from_ema(self, tjl_us):
        h, l, c, _ = _uptrend(n=80)
        res, reason = tjl_us.check_tjl(
            "NVDA", "NVIDIA", 1000.0, 1000.0, 1000.0, h, l, c,
        )
        assert res is None
        assert reason is not None and "nearEMA" in reason

    def test_no_pmh_means_no_above_pmh(self, tjl_us):
        h, l, c, _ = _uptrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        res, reason = tjl_us.check_tjl(
            "NVDA", "NVIDIA", price, day_high=price,
            prev_day_high=0, highs=h, lows=l, closes=c, premarket_high=0,
        )
        assert res is None
        assert reason is not None and "abovePMH" in reason

    def test_downtrend_rejected(self, tjl_us):
        h, l, c, _ = _downtrend(n=80)
        price = float(c[-1])
        res, reason = tjl_us.check_tjl(
            "NVDA", "NVIDIA", price, day_high=price,
            prev_day_high=price - 5.0, highs=h, lows=l, closes=c,
        )
        assert res is None
        assert reason is not None and "stack" in reason

    def test_uses_premarket_high_when_higher(self, tjl_us):
        h, l, c, _ = _uptrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        # prev_day_high=0 (disabled), premarket_high slightly below price
        res, reason = tjl_us.check_tjl(
            "NVDA", "NVIDIA", price, day_high=price,
            prev_day_high=0, highs=h, lows=l, closes=c,
            premarket_high=price - 0.3,
        )
        assert res is None
        assert reason is not None and "abovePMH" in reason

    def test_returns_dict_with_required_keys(self, tjl_us):
        h, l, c, _ = _uptrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        res, _ = tjl_us.check_tjl(
            "NVDA", "NVIDIA", price, day_high=price - 5.0,
            prev_day_high=price - 10.0, highs=h, lows=l, closes=c,
        )
        assert res is not None
        for k in ("ticker", "name", "price", "direction", "e9", "e20", "e50",
                  "atr", "pmh", "sl", "tp", "rr_ratio"):
            assert k in res

    def test_rr_ratio_is_2_for_v2(self, tjl_us):
        h, l, c, _ = _uptrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        res, _ = tjl_us.check_tjl(
            "NVDA", "NVIDIA", price, day_high=price - 5.0,
            prev_day_high=price - 10.0, highs=h, lows=l, closes=c,
        )
        # v2 uses ATR_SL=1.5, ATR_TP=3.0 → R:R = 2.0
        assert abs(res["rr_ratio"] - 2.0) < 0.01


# ── check_tjs (TJS SHORT) ─────────────────────────────────────────────────────

class TestUsCheckTjs:
    def test_short_signal_on_bearish_stack(self, tjl_us):
        h, l, c, _ = _downtrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        res, reason = tjl_us.check_tjs(
            "NVDA", "NVIDIA", price, day_low=price + 5.0,
            prev_day_low=price + 5.0, highs=h, lows=l, closes=c,
        )
        assert res is not None, f"got None with reason: {reason}"
        assert res["direction"] == "SHORT"
        assert res["sl"] > res["price"] > res["tp"]

    def test_no_signal_on_uptrend(self, tjl_us):
        h, l, c, _ = _uptrend(n=80)
        price = float(c[-1])
        res, reason = tjl_us.check_tjs(
            "NVDA", "NVIDIA", price, day_low=price,
            prev_day_low=price - 5.0, highs=h, lows=l, closes=c,
        )
        assert res is None
        assert reason is not None and "stack" in reason

    def test_returns_dict_with_required_keys(self, tjl_us):
        h, l, c, _ = _downtrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        res, _ = tjl_us.check_tjs(
            "NVDA", "NVIDIA", price, day_low=price + 5.0,
            prev_day_low=price + 5.0, highs=h, lows=l, closes=c,
        )
        for k in ("ticker", "name", "price", "direction", "e9", "e20", "e50",
                  "atr", "pml", "sl", "tp", "rr_ratio"):
            assert k in res

    def test_rr_ratio_for_short(self, tjl_us):
        h, l, c, _ = _downtrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        res, _ = tjl_us.check_tjs(
            "NVDA", "NVIDIA", price, day_low=price + 5.0,
            prev_day_low=price + 5.0, highs=h, lows=l, closes=c,
        )
        assert abs(res["rr_ratio"] - 2.0) < 0.01

    def test_uses_premarket_low_when_lower(self, tjl_us):
        h, l, c, _ = _downtrend(n=80, slope=0.1)
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        # prev_day_low=0 (disabled), premarket_low slightly above price
        res, reason = tjl_us.check_tjs(
            "NVDA", "NVIDIA", price, day_low=price + 5.0,
            prev_day_low=0, highs=h, lows=l, closes=c,
            premarket_low=price + 0.3,
        )
        assert res is None
        assert reason is not None and "belowPML" in reason


# ── _build_discord_payload ───────────────────────────────────────────────────

class TestUsBuildDiscordPayload:
    def test_returns_none_when_no_webhook(self, tjl_us, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_HK_TJL", raising=False)
        url, payload = tjl_us._build_discord_payload([], "now", "BULLISH", [], [])
        assert url is None
        assert payload is None

    def test_payload_with_long_signals(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        signals = [{
            "ticker": "NVDA", "name": "NVIDIA", "price": 150.0,
            "direction": "LONG",
            "e9": 148.0, "e20": 145.0, "e50": 140.0,
            "sl": 145.0, "tp": 160.0, "rr_ratio": 2.0,
        }]
        longs = [s for s in signals if s.get("direction") == "LONG"]
        shorts = []
        url, payload = tjl_us._build_discord_payload(
            signals, "now", "BULLISH", longs, shorts
        )
        assert url is not None
        assert payload is not None
        # Embed structure
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1
        assert payload["embeds"][0]["fields"]  # non-empty

    def test_payload_no_signals(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        url, payload = tjl_us._build_discord_payload([], "now", "BULLISH", [], [])
        assert url is not None
        assert payload is not None
        # Description should mention no signals
        embed = payload["embeds"][0]
        assert "No signals" in embed.get("description", "") or not embed.get("fields")

    def test_regime_color_bullish(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        url, payload = tjl_us._build_discord_payload([], "now", "BULLISH", [], [])
        # 0x228B22 = green
        assert payload["embeds"][0]["color"] == 0x228B22

    def test_regime_color_bearish(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        url, payload = tjl_us._build_discord_payload([], "now", "BEARISH", [], [])
        # 0xDC143C = red
        assert payload["embeds"][0]["color"] == 0xDC143C

    def test_thread_name_present(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        url, payload = tjl_us._build_discord_payload([], "now", "BULLISH", [], [])
        assert "thread_name" in payload
        assert payload["thread_name"].startswith("US TJL Live")


# ── post_discord ──────────────────────────────────────────────────────────────

class TestUsPostDiscord:
    def test_skips_when_no_webhook(self, tjl_us, monkeypatch, capsys):
        monkeypatch.delenv("DISCORD_WEBHOOK_HK_TJL", raising=False)
        tjl_us.post_discord([], "now", "BULLISH")
        out = capsys.readouterr().out
        assert "not set" in out.lower()

    def test_posts_with_signals(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        fake_run = MagicMock(return_value=MagicMock(stdout="ok\n204"))
        with patch.object(tjl_us.subprocess, "run", fake_run):
            signals = [{"ticker": "NVDA", "name": "NVIDIA", "price": 150.0,
                        "e9": 148.0, "e20": 145.0, "e50": 140.0,
                        "sl": 145.0, "tp": 160.0, "rr_ratio": 2.0,
                        "direction": "LONG"}]
            tjl_us.post_discord(signals, "now", "BULLISH")
        assert fake_run.called

    def test_uses_curl_with_thread_name(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        fake_run = MagicMock(return_value=MagicMock(stdout="ok\n204"))
        with patch.object(tjl_us.subprocess, "run", fake_run):
            tjl_us.post_discord(
                [{"ticker": "NVDA", "name": "NVIDIA", "price": 100.0,
                  "e9": 99.0, "e20": 98.0, "e50": 97.0,
                  "sl": 95.0, "tp": 110.0, "rr_ratio": 2.0,
                  "direction": "LONG"}],
                "now", "BULLISH"
            )
        # Verify the curl command has the webhook URL
        args = fake_run.call_args[0][0]
        assert any("https://discord.example/webhook" in str(a) for a in args)


# ── notify_telegram ───────────────────────────────────────────────────────────

class TestUsNotifyTelegram:
    def test_sends_text(self, tjl_us, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        # notify_telegram uses subprocess.run internally for hermes
        fake_run = MagicMock(return_value=MagicMock(stdout="ok", stderr=""))
        with patch.object(tjl_us.subprocess, "run", fake_run) as fr:
            tjl_us.notify_telegram({
                "scanned_at": "2026-01-01 09:30 ET",
                "signals": [{"ticker": "NVDA", "name": "NVIDIA", "price": 150.0, "rr_ratio": 2.0}],
                "regime": "BULLISH",
            })
        assert fr.called

    def test_swallows_subprocess_exception(self, tjl_us):
        with patch.object(tjl_us.subprocess, "run",
                          side_effect=FileNotFoundError):
            tjl_us.notify_telegram({"scanned_at": "now", "signals": [], "regime": "BULLISH"})


# ── run_scan orchestrator ─────────────────────────────────────────────────────

class TestUsRunScan:
    def test_no_signals_on_empty_watchlist(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        with patch.object(tjl_us, "get_regime", return_value="BULLISH"):
            signals = tjl_us.run_scan(notify=False)
        assert signals == []

    def test_no_daily_bars_skips_ticker(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [("NVDA", "NVIDIA")])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        with patch.object(tjl_us, "get_regime", return_value="BULLISH"):
            with patch.object(tjl_us, "get_daily_bars", return_value=(None, None, None)):
                signals = tjl_us.run_scan(notify=False)
        assert signals == []

    def test_no_live_price_skips_ticker(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [("NVDA", "NVIDIA")])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        h = np.array([101.0] * 80); l = np.array([99.0] * 80); c = np.array([100.0] * 80)
        with patch.object(tjl_us, "get_regime", return_value="BULLISH"):
            with patch.object(tjl_us, "get_daily_bars", return_value=(h, l, c)):
                with patch.object(tjl_us, "get_live_price", return_value=None):
                    signals = tjl_us.run_scan(notify=False)
        assert signals == []

    def test_bullish_full_scan_with_signal(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [("NVDA", "NVIDIA")])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        bars = _bars_df(n=250, base=100.0, slope=0.1)
        h = bars["High"].values; l = bars["Low"].values; c = bars["Close"].values
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        # Make prev_day_high very low so above_pmh passes
        h = h.copy()
        h[-2] = c[-1] - 50.0
        quote = {
            "price": price,
            "prev_close": price,
            "day_high": price - 5.0,
            "day_low": price - 10.0,
        }
        with patch.object(tjl_us, "get_regime", return_value="BULLISH"):
            with patch.object(tjl_us, "get_daily_bars", return_value=(h, l, c)):
                with patch.object(tjl_us, "get_live_price", return_value=quote):
                    with patch.object(tjl_us, "get_premarket_high", return_value=0):
                        with patch.object(tjl_us, "get_premarket_low", return_value=0):
                            signals = tjl_us.run_scan(notify=False)
        assert isinstance(signals, list)
        names = {s.get("ticker") for s in signals}
        assert "NVDA" in names

    def test_bearish_regime_suppresses_longs(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [("NVDA", "NVIDIA")])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        bars = _bars_df(n=250, base=100.0, slope=0.1)
        h = bars["High"].values; l = bars["Low"].values; c = bars["Close"].values
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        h = h.copy(); h[-2] = c[-1] - 50.0
        quote = {
            "price": price, "prev_close": price,
            "day_high": price - 5.0, "day_low": price - 10.0,
        }
        with patch.object(tjl_us, "get_regime", return_value="BEARISH"):
            with patch.object(tjl_us, "get_daily_bars", return_value=(h, l, c)):
                with patch.object(tjl_us, "get_live_price", return_value=quote):
                    with patch.object(tjl_us, "get_premarket_high", return_value=0):
                        with patch.object(tjl_us, "get_premarket_low", return_value=0):
                            signals = tjl_us.run_scan(notify=False)
        # In BEARISH regime, no LONG signals should fire
        for s in signals:
            assert s.get("direction") != "LONG"

    def test_bearish_regime_allows_shorts(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [("NVDA", "NVIDIA")])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        bars = _downtrend_df(n=250, base=300.0, slope=0.1)
        h = bars["High"].values.copy()
        l = bars["Low"].values.copy()
        c = bars["Close"].values
        # Make prev_day_low very high so pml > price + 0.7
        l[-2] = c[-1] + 50.0
        e9, _, _ = tjl_us.calc_emas(c)
        price = float(e9)
        quote = {
            "price": price, "prev_close": price + 1.0,
            "day_high": price + 5.0, "day_low": price + 5.0,
        }
        with patch.object(tjl_us, "get_regime", return_value="BEARISH"):
            with patch.object(tjl_us, "get_daily_bars", return_value=(h, l, c)):
                with patch.object(tjl_us, "get_live_price", return_value=quote):
                    with patch.object(tjl_us, "get_premarket_high", return_value=0):
                        with patch.object(tjl_us, "get_premarket_low", return_value=0):
                            signals = tjl_us.run_scan(notify=False)
        shorts = [s for s in signals if s.get("direction") == "SHORT"]
        assert len(shorts) >= 1, f"Expected SHORT signal, got: {signals}"

    def test_custom_us_tickers_env(self, tjl_us, monkeypatch):
        monkeypatch.setenv("US_TICKERS", "AAPL,MSFT,GOOGL")
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        with patch.object(tjl_us, "get_regime", return_value="BULLISH"):
            with patch.object(tjl_us, "get_daily_bars", return_value=(None, None, None)):
                signals = tjl_us.run_scan(notify=False)
        assert isinstance(signals, list)

    def test_runs_post_discord(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        with patch.object(tjl_us, "get_regime", return_value="BULLISH"):
            with patch.object(tjl_us, "post_discord") as pd_mock:
                tjl_us.run_scan(notify=False)
        assert pd_mock.called

    def test_runs_notify_telegram(self, tjl_us, monkeypatch):
        monkeypatch.setattr(tjl_us, "DEFAULT_WATCHLIST", [])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        with patch.object(tjl_us, "get_regime", return_value="BULLISH"):
            with patch.object(tjl_us, "notify_telegram") as nt_mock:
                tjl_us.run_scan(notify=True)
        assert nt_mock.called


# ── CLI smoke test ────────────────────────────────────────────────────────────

class TestUsCli:
    def test_help_runs(self):
        import subprocess
        result = subprocess.run(
            ["python3",
             os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tjl_live_us.py"),
             "--help"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert "--continuous" in result.stdout
        assert "--interval" in result.stdout


# ── Log helper ────────────────────────────────────────────────────────────────

class TestUsLog:
    def test_log_writes_to_stdout(self, tjl_us, capsys):
        tjl_us.log("hello")
        out = capsys.readouterr().out
        assert "hello" in out
        assert "ET" in out