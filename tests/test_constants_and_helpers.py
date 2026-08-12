"""Unit tests for constants, watchlist, and module-level helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestConstants:
    def test_pmh_buf_is_70_hkd(self, tjl_mod):
        assert tjl_mod.PMH_BUF == 0.70

    def test_atr_sl_value(self, tjl_mod):
        assert tjl_mod.ATR_SL == 1.0  # Updated to tighter stop in current code

    def test_atr_tp_value(self, tjl_mod):
        assert tjl_mod.ATR_TP == 1.5  # 1.5x ATR take profit

    def test_atr_period_is_14(self, tjl_mod):
        assert tjl_mod.ATR_PERIOD == 14

    def test_near_ema_pct_a(self, tjl_mod):
        assert tjl_mod.NEAR_EMA_PCT == 0.015

    def test_near_ema_pct_c_is_wider(self, tjl_mod):
        assert tjl_mod.NEAR_EMA_PCT_C == 0.020
        assert tjl_mod.NEAR_EMA_PCT_C > tjl_mod.NEAR_EMA_PCT

    def test_vol_spike_mult_is_2x(self, tjl_mod):
        assert tjl_mod.VOL_SPIKE_MULT == 2.0

    def test_scan_interval_default_30(self, tjl_mod):
        assert tjl_mod.SCAN_INTERVAL == 30

    def test_timezone_is_hkt(self, tjl_mod):
        assert str(tjl_mod.HKT) == "Asia/Hong_Kong"


class TestWatchlist:
    def test_watchlist_non_empty(self, tjl_mod):
        assert len(tjl_mod.WATCHLIST) >= 30

    def test_all_codes_start_with_hk(self, tjl_mod):
        bad = [(name, code) for name, code in tjl_mod.WATCHLIST if not code.startswith("HK.")]
        assert bad == [], f"non-HK codes: {bad}"

    def test_all_codes_are_5_digit(self, tjl_mod):
        bad = [(n, c) for n, c in tjl_mod.WATCHLIST
               if not c.split(".", 1)[-1].isdigit() or len(c.split(".", 1)[-1]) != 5]
        assert bad == [], f"non-5-digit codes: {bad}"

    def test_all_names_match_code_tail(self, tjl_mod):
        for name, code in tjl_mod.WATCHLIST:
            assert name == code.split(".", 1)[-1], f"{name} != tail of {code}"

    def test_all_codes_derivable_from_watchlist(self, tjl_mod):
        assert tjl_mod.ALL_CODES == [c for _, c in tjl_mod.WATCHLIST]

    def test_no_duplicate_codes(self, tjl_mod):
        codes = [c for _, c in tjl_mod.WATCHLIST]
        assert len(codes) == len(set(codes)), "duplicate codes in WATCHLIST"

    def test_contains_mega_caps(self, tjl_mod):
        codes = {c for _, c in tjl_mod.WATCHLIST}
        for must in ("HK.00700", "HK.09988", "HK.00388", "HK.00939"):
            assert must in codes, f"{must} missing from watchlist"


class TestLogHelper:
    def test_log_writes_to_stdout(self, tjl_mod, capsys):
        tjl_mod.log("hello world")
        out = capsys.readouterr().out
        assert "hello world" in out
        # Should contain HKT timestamp
        assert "[" in out and "]" in out


class TestGetDailyBars:
    def test_returns_none_on_failure(self, tjl_mod, fake_ctx):
        fake_ctx.request_history_kline.return_value = (-1, None, None)
        result = tjl_mod.get_daily_bars(fake_ctx, "HK.00700", count=80)
        assert result == (None, None, None, None)

    def test_returns_none_when_empty(self, tjl_mod, fake_ctx):
        empty = pd.DataFrame(columns=["time_key", "high", "low", "close", "volume"])
        fake_ctx.request_history_kline.return_value = (0, empty, None)
        result = tjl_mod.get_daily_bars(fake_ctx, "HK.00700", count=80)
        assert result == (None, None, None, None)

    def test_returns_arrays_on_success(self, tjl_mod, fake_ctx):
        df = pd.DataFrame({
            "time_key": pd.date_range("2025-01-01", periods=80, freq="D"),
            "high": np.linspace(101, 105, 80),
            "low": np.linspace(99, 95, 80),
            "close": np.linspace(100, 104, 80),
            "volume": np.full(80, 1000),
        })
        fake_ctx.request_history_kline.return_value = (0, df, None)
        highs, lows, closes, volumes = tjl_mod.get_daily_bars(fake_ctx, "HK.00700", count=80)
        assert highs is not None and len(highs) == 80
        assert lows is not None and len(lows) == 80
        assert closes is not None and len(closes) == 80
        assert volumes is not None and len(volumes) == 80

    def test_sorts_by_time_key(self, tjl_mod, fake_ctx):
        # Provide bars in reverse chronological order, but with closes that
        # ascend with their (descending) date — so after sort, closes descend.
        dates = pd.date_range("2025-03-21", periods=80, freq="D")[::-1]
        closes_aligned = np.linspace(104, 100, 80)  # newest=104, oldest=100
        df = pd.DataFrame({
            "time_key": dates,
            "high": np.linspace(105, 101, 80),
            "low": np.linspace(104, 99, 80),
            "close": closes_aligned,
            "volume": np.full(80, 1000),
        })
        fake_ctx.request_history_kline.return_value = (0, df, None)
        highs, lows, closes, volumes = tjl_mod.get_daily_bars(fake_ctx, "HK.00700")
        # After ascending sort by time_key, oldest row (close=100) comes first
        assert closes[0] == pytest.approx(100.0)
        assert closes[-1] == pytest.approx(104.0)
        assert list(closes) == sorted(closes)
        # And the indexes are reset (0..N-1, not the original 79..0)
        assert len(closes) == 80


class TestGetIntradayBars30min:
    def test_returns_none_on_failure(self, tjl_mod, fake_ctx):
        fake_ctx.request_history_kline.return_value = (-1, None, None)
        assert tjl_mod.get_intraday_bars_30min(fake_ctx, "HK.00700") == (None, None)

    def test_returns_first_bar_high_low(self, tjl_mod, fake_ctx):
        df = pd.DataFrame({
            "time_key": pd.date_range("2025-01-01 09:30", periods=20, freq="30min"),
            "high": [101.0] + [102.0] * 19,
            "low": [99.0] + [98.0] * 19,
            "close": [100.0] * 20,
            "volume": [1000] * 20,
        })
        fake_ctx.request_history_kline.return_value = (0, df, None)
        orb_high, orb_low = tjl_mod.get_intraday_bars_30min(fake_ctx, "HK.00700")
        assert orb_high == 101.0
        assert orb_low == 99.0


class TestDetectRegime:
    def test_bullish_when_most_stacks_bullish(self, tjl_mod, fake_ctx):
        # 60+1 tickers with bullish uptrend bars → regime should be bullish
        watchlist = [(f"{i:05d}", f"HK.{i:05d}") for i in range(10001, 10065)]

        def fake_history(code, ktype=None, max_count=80, **kw):
            closes = np.array([100.0 + j * 0.05 for j in range(80)])
            highs = closes + 0.3
            lows = closes - 0.3
            df = pd.DataFrame({
                "time_key": pd.date_range("2025-01-01", periods=80, freq="D"),
                "high": highs, "low": lows,
                "close": closes, "volume": np.full(80, 1000),
            })
            return (0, df, None)

        fake_ctx.request_history_kline.side_effect = fake_history
        regime, bear_pct, bull_pct, evaluated = tjl_mod.detect_regime(fake_ctx, watchlist)
        assert regime == "bullish"
        assert bull_pct >= 0.60
        assert evaluated == 64

    def test_bearish_when_most_stacks_bearish(self, tjl_mod, fake_ctx):
        watchlist = [(f"{i:05d}", f"HK.{i:05d}") for i in range(10001, 10065)]

        def fake_history(code, ktype=None, max_count=80, **kw):
            closes = np.array([200.0 - j * 0.05 for j in range(80)])
            highs = closes + 0.3
            lows = closes - 0.3
            df = pd.DataFrame({
                "time_key": pd.date_range("2025-01-01", periods=80, freq="D"),
                "high": highs, "low": lows,
                "close": closes, "volume": np.full(80, 1000),
            })
            return (0, df, None)

        fake_ctx.request_history_kline.side_effect = fake_history
        regime, _, _, _ = tjl_mod.detect_regime(fake_ctx, watchlist)
        assert regime == "bearish"

    def test_neutral_with_empty_watchlist(self, tjl_mod, fake_ctx):
        fake_ctx.request_history_kline.return_value = (-1, None, None)
        regime, bear, bull, evaluated = tjl_mod.detect_regime(fake_ctx, [])
        assert regime == "neutral"
        assert evaluated == 0

    def test_handles_short_bars(self, tjl_mod, fake_ctx):
        # Return fewer than 60 bars → should skip (not crash)
        df = pd.DataFrame({
            "time_key": pd.date_range("2025-01-01", periods=10, freq="D"),
            "high": [101.0] * 10, "low": [99.0] * 10,
            "close": [100.0] * 10, "volume": [1000] * 10,
        })
        fake_ctx.request_history_kline.return_value = (0, df, None)
        watchlist = [("12345", "HK.12345")]
        regime, _, _, evaluated = tjl_mod.detect_regime(fake_ctx, watchlist)
        assert evaluated == 0
        assert regime == "neutral"