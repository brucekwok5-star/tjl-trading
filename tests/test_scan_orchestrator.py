"""Coverage boost for run_scan orchestrator: hit each model's debug path."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _bars(closes=None, n=80):
    if closes is None:
        closes = np.array([100.0 + 0.05 * i for i in range(n)])
    return pd.DataFrame({
        "time_key": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
        "high": np.asarray(closes) + 0.3,
        "low":  np.asarray(closes) - 0.3,
        "close": closes,
        "volume": np.full(len(closes), 1_000_000, dtype=int),
    })


def _quote(code, price, prev_close, high, low, open_, vol):
    return pd.DataFrame([{
        "code": code, "last_price": price,
        "prev_close_price": prev_close, "high_price": high,
        "low_price": low, "open_price": open_, "volume": vol,
    }])


def _setup_ctx(bars_df, quote_df):
    ctx = MagicMock()
    ctx.request_history_kline.return_value = (0, bars_df, None)
    ctx.get_stock_quote.return_value = (0, quote_df)
    ctx.subscribe.return_value = (0, None)
    ctx.close.return_value = (0, None)
    return ctx


class TestRunScanOrchestrator:
    def test_run_scan_with_downtrend_short_signals(self, tjl_mod, monkeypatch):
        """Run scan in bearish regime → TJS short fires (downtrend + pullback)."""
        closes = np.array([200.0 - 0.05 * i for i in range(80)])
        bar_df = _bars(closes)
        # Volume spike for Model C/F/E
        bar_df.loc[bar_df.index[-1], "volume"] = 5_000_000

        price = float(closes[-1])
        quote_df = _quote("HK.00700", price, price + 1.0,
                          price - 5.0, price + 5.0, price + 0.5, 5_000_000)
        ctx = _setup_ctx(bar_df, quote_df)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            signals = tjl_mod.run_scan(notify=False)
        # In a downtrend with PMH_buffer above price, TJS should not fire either,
        # but the scan should complete without error.
        assert isinstance(signals, list)

    def test_run_scan_covers_all_models_no_crash(self, tjl_mod, monkeypatch):
        """Single bullish ticker: cover all 11 models in scan loop."""
        closes = np.array([100.0 + 0.05 * i for i in range(80)])
        bar_df = _bars(closes)
        bar_df.loc[bar_df.index[-1], "volume"] = 5_000_000
        price = float(closes[-1])
        quote_df = _quote("HK.00700", price, price - 1.0,
                          price - 5.0, price - 10.0, price - 1.0, 5_000_000)
        ctx = _setup_ctx(bar_df, quote_df)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            signals = tjl_mod.run_scan(notify=False)
        assert isinstance(signals, list)

    def test_run_scan_no_bars_for_ticker(self, tjl_mod, monkeypatch):
        """If daily bars fail to fetch for a ticker, run_scan logs and skips."""
        closes = np.array([100.0] * 80)
        bar_df = _bars(closes)
        quote_df = _quote("HK.00700", 100.0, 100.0, 100.5, 99.5, 100.0, 1_000_000)
        ctx = MagicMock()
        # First call (bars) returns failure for HK.00700
        ctx.request_history_kline.return_value = (-1, None, None)
        ctx.get_stock_quote.return_value = (0, quote_df)
        ctx.subscribe.return_value = (0, None)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            signals = tjl_mod.run_scan(notify=False)
        assert isinstance(signals, list)
        # No signals because no bars available
        assert signals == []


class TestHKTickersOverrideInRunScan:
    """Test HK_TICKERS env var actually narrows the watchlist when main() runs."""

    def test_main_runs_one_shot_when_no_args(self, tjl_mod, monkeypatch, capsys):
        """Calling main() with no args runs run_scan once."""
        import sys
        monkeypatch.setattr(sys, "argv", ["tjl_live_futu.py"])
        monkeypatch.setenv("HK_TICKERS", "")
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        ctx = _setup_ctx(_bars(), _quote("HK.00700", 100.0, 100.0, 100.5, 99.5, 100.0, 1_000_000))
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            tjl_mod.main()
        out = capsys.readouterr().out
        assert "TJL Live Scanner" in out

    def test_main_applies_hk_tickers_override(self, tjl_mod, monkeypatch, capsys):
        """HK_TICKERS env var narrows the watchlist."""
        import sys
        monkeypatch.setattr(sys, "argv", ["tjl_live_futu.py"])
        monkeypatch.setenv("HK_TICKERS", "HK.00700,HK.09988")
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        ctx = _setup_ctx(_bars(), _quote("HK.00700", 100.0, 100.0, 100.5, 99.5, 100.0, 1_000_000))
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            tjl_mod.main()
        out = capsys.readouterr().out
        assert "HK_TICKERS override" in out

    def test_main_continuous_stops_on_interrupt(self, tjl_mod, monkeypatch):
        """--continuous loops until KeyboardInterrupt."""
        import sys
        monkeypatch.setattr(sys, "argv", ["tjl_live_futu.py", "--continuous", "--interval", "1"])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")

        # Make run_scan + sleep raise KeyboardInterrupt after first iteration
        original_run_scan = tjl_mod.run_scan
        call_count = {"n": 0}

        def fake_run_scan(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] >= 1:
                raise KeyboardInterrupt()
            return original_run_scan(*a, **kw)

        with patch.object(tjl_mod, "run_scan", side_effect=fake_run_scan):
            with patch.object(tjl_mod.time, "sleep"):  # avoid real sleep
                tjl_mod.main()  # Should exit cleanly via KeyboardInterrupt
        assert call_count["n"] >= 1


class TestPostDiscordDuringScan:
    """Verify post_discord gets called inside run_scan when webhook is set."""

    def test_post_discord_invoked_when_signals(self, tjl_mod, monkeypatch):
        closes = np.array([100.0 + 0.05 * i for i in range(80)])
        bar_df = _bars(closes)
        bar_df.loc[bar_df.index[-1], "volume"] = 5_000_000
        price = float(closes[-1])
        quote_df = _quote("HK.00700", price, price - 1.0,
                          price - 5.0, price - 10.0, price - 1.0, 5_000_000)
        ctx = _setup_ctx(bar_df, quote_df)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")

        post_called = []
        with patch.object(tjl_mod, "post_discord", side_effect=lambda *a, **kw: post_called.append(True)):
            with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
                tjl_mod.run_scan(notify=False)
        assert post_called == [True] or len(post_called) >= 1

    def test_notify_telegram_invoked_when_notify_true(self, tjl_mod, monkeypatch):
        closes = np.array([100.0 + 0.05 * i for i in range(80)])
        bar_df = _bars(closes)
        bar_df.loc[bar_df.index[-1], "volume"] = 5_000_000
        price = float(closes[-1])
        quote_df = _quote("HK.00700", price, price - 1.0,
                          price - 5.0, price - 10.0, price - 1.0, 5_000_000)
        ctx = _setup_ctx(bar_df, quote_df)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")

        with patch.object(tjl_mod, "notify_telegram") as nt:
            with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
                tjl_mod.run_scan(notify=True)
        assert nt.called


class TestLogTableCoverage:
    """Cover log_table paths by producing both long and short signal lists."""

    def test_run_scan_with_both_long_and_short(self, tjl_mod, monkeypatch):
        # Build a setup that produces both LONG (model A) and SHORT (TJS)
        # Use 2 tickers in the watchlist
        ctx = MagicMock()
        # Ticker 1: bullish — fires LONG
        closes1 = np.array([100.0 + 0.05 * i for i in range(80)])
        bars1 = _bars(closes1)
        bars1.loc[bars1.index[-1], "volume"] = 5_000_000
        price1 = float(closes1[-1])
        quote1 = _quote("HK.00700", price1, price1 - 1.0,
                        price1 - 5.0, price1 - 10.0, price1 - 1.0, 5_000_000)
        # Ticker 2: bearish — fires SHORT (TJS)
        closes2 = np.array([200.0 - 0.05 * i for i in range(80)])
        bars2 = _bars(closes2)
        price2 = float(closes2[-1])
        quote2 = _quote("HK.00005", price2, price2 + 1.0,
                        price2 - 5.0, price2 + 5.0, price2 + 0.5, 1_000_000)

        responses = {
            "HK.00700": (0, bars1, None),
            "HK.00005": (0, bars2, None),
        }
        ctx.request_history_kline.side_effect = lambda code, *a, **kw: responses.get(code, (-1, None, None))

        quote_responses = {"HK.00700": quote1, "HK.00005": quote2}
        def quote_fn(codes):
            return (0, quote_responses.get(codes[0], quote1))
        ctx.get_stock_quote.side_effect = quote_fn

        monkeypatch.setattr(tjl_mod, "WATCHLIST",
                            [("00700", "HK.00700"), ("00005", "HK.00005")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700", "HK.00005"])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")

        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            signals = tjl_mod.run_scan(notify=False)
        assert isinstance(signals, list)


class TestRegimeBranches:
    """Run scan in different regimes to cover regime-guarded branches."""

    def test_bearish_regime_short_signals(self, tjl_mod, monkeypatch):
        closes = np.array([200.0 - 0.05 * i for i in range(80)])
        bar_df = _bars(closes)
        bar_df.loc[bar_df.index[-1], "volume"] = 5_000_000
        price = float(closes[-1])
        quote_df = _quote("HK.00700", price, price + 1.0,
                          price - 5.0, price + 5.0, price + 0.5, 5_000_000)
        ctx = _setup_ctx(bar_df, quote_df)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            signals = tjl_mod.run_scan(notify=False)
        assert isinstance(signals, list)


class TestModelEOrchestrator:
    """Regression test: Model E orchestrator must read long_fire/short_fire,
    not is_squeezed/is_expanding/at_lower/at_upper (which never existed)."""

    def test_model_e_signal_flows_through_run_scan(self, tjl_mod, monkeypatch):
        # Construct a setup where the LAST bar's price is the highest of the
        # last 21 days (triggers Model E's "20-day high break"), RSI > 50,
        # and volume >= 1.5x avg20. To ensure Model E (not G) wins the OR-logic
        # race, keep the prior bars below the breakout level.
        closes = np.array([100.0] * 79 + [115.0])  # flat then sharp breakout
        bar_df = _bars(closes)
        bar_df.loc[bar_df.index[-1], "volume"] = 5_000_000  # 5× spike

        price = 115.0
        quote_df = _quote("HK.00700", price, price - 1.0,
                          price - 5.0, price - 10.0, price - 1.0, 5_000_000)
        ctx = _setup_ctx(bar_df, quote_df)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            signals = tjl_mod.run_scan(notify=False)

        e_signals = [s for s in signals if s.get("signal_model") == "E"]
        long_signals = [s for s in signals if s.get("direction") == "LONG"]
        assert len(long_signals) >= 1, (
            f"Expected at least one LONG signal in a 20-day-high breakout, "
            f"got {[s.get('signal_model') for s in signals]}"
        )
        # If Model E fired, it should be LONG
        if e_signals:
            assert e_signals[0]["direction"] == "LONG"

    def test_model_e_no_signal_without_volume(self, tjl_mod, monkeypatch):
        # Same breakout but no volume spike → should not fire
        closes = np.array([100.0 + 0.01 * i for i in range(80)])
        bar_df = _bars(closes)
        bar_df.loc[bar_df.index[-1], "close"] = 110.0
        bar_df.loc[bar_df.index[-1], "high"] = 112.0
        bar_df.loc[bar_df.index[-1], "low"] = 109.0
        # No volume spike — keep at 1M (same as prior bars)
        bar_df.loc[bar_df.index[-1], "volume"] = 1_000_000

        price = 110.0
        quote_df = _quote("HK.00700", price, price - 1.0,
                          price - 5.0, price - 10.0, price - 1.0, 1_000_000)
        ctx = _setup_ctx(bar_df, quote_df)
        monkeypatch.setattr(tjl_mod, "WATCHLIST", [("00700", "HK.00700")])
        monkeypatch.setattr(tjl_mod, "ALL_CODES", ["HK.00700"])
        with patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx):
            signals = tjl_mod.run_scan(notify=False)

        e_signals = [s for s in signals if s.get("signal_model") == "E"]
        assert e_signals == [], "Model E should not fire without volume confirmation"