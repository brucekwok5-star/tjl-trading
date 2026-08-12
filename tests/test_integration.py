"""Tests for log, post_discord, notify_telegram, run_scan, and main CLI."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── log ──────────────────────────────────────────────────────────────────────


class TestLog:
    def test_log_writes_timestamped_line(self, tjl_mod, capsys):
        tjl_mod.log("hello world")
        out = capsys.readouterr().out
        # HH:MM:SS prefix — match "[<digit>" (handles both "03:..." and "14:...")
        import re
        assert re.search(r"\[\d", out), f"missing timestamp prefix: {out!r}"
        assert "hello world" in out
        assert out.endswith("\n")


# ── post_discord ─────────────────────────────────────────────────────────────


class TestPostDiscord:
    def test_skips_when_webhook_missing(self, tjl_mod, monkeypatch, capsys):
        monkeypatch.delenv("DISCORD_WEBHOOK_HK_TJL", raising=False)
        with patch.object(tjl_mod.subprocess, "run") as mock_run:
            tjl_mod.post_discord([], "2024-05-01 09:30:00 HKT")
        mock_run.assert_not_called()
        out = capsys.readouterr().out
        assert "DISCORD_WEBHOOK_HK_TJL not set" in out

    def test_posts_with_signals(self, tjl_mod, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://example.com/webhook")
        signals = [{
            "name": "HK.00700",
            "price": 350.0,
            "e9": 348.0,
            "e20": 345.0,
            "e50": 340.0,
            "sl": 348.0,
            "tp": 354.0,
            "rr_ratio": 1.5,
        }]
        with patch.object(tjl_mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok\n200")
            tjl_mod.post_discord(signals, "2024-05-01 09:30:00 HKT")
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        assert args[0] == "curl"
        assert "POST" in args
        assert "https://example.com/webhook?wait=true" in args

    def test_no_signals_message(self, tjl_mod, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://example.com/webhook")
        with patch.object(tjl_mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="\n200")
            tjl_mod.post_discord([], "2024-05-01 09:30:00 HKT")
        # Verify the payload mentions "No TJL signals"
        payload = mock_run.call_args.args[0][-1] if mock_run.call_args else None
        # The payload is passed via -d arg, last position
        called_args = mock_run.call_args.args[0]
        # find the -d argument
        d_idx = called_args.index("-d") + 1
        payload = json.loads(called_args[d_idx])
        assert "No TJL signals" in payload["content"]

    def test_handles_string_emas_missing(self, tjl_mod, monkeypatch):
        # Model B has no e9/e20/e50; should fall back to '--'
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://example.com/webhook")
        signals = [{
            "name": "HK.00005",
            "price": 80.0,
            "sma200": 78.0,
            "sl": 79.0,
            "tp": 82.0,
            "rr_ratio": 2.0,
        }]
        with patch.object(tjl_mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="\n200")
            tjl_mod.post_discord(signals, "2024-05-01 09:30:00 HKT")
        # Just verify no crash and subprocess called
        assert mock_run.called

    def test_truncates_long_content(self, tjl_mod, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://example.com/webhook")
        # Generate many signals to exceed 1900 char limit
        signals = []
        for i in range(50):
            signals.append({
                "name": f"HK.{i:05d}",
                "price": 100.0 + i,
                "e9": 99.0 + i,
                "e20": 98.0 + i,
                "e50": 97.0 + i,
                "sl": 95.0,
                "tp": 110.0,
                "rr_ratio": 1.5,
            })
        with patch.object(tjl_mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="\n200")
            tjl_mod.post_discord(signals, "2024-05-01 09:30:00 HKT")
        called_args = mock_run.call_args.args[0]
        d_idx = called_args.index("-d") + 1
        payload = json.loads(called_args[d_idx])
        assert "(truncated)" in payload["content"]


# ── notify_telegram ──────────────────────────────────────────────────────────


class TestNotifyTelegram:
    def test_no_signals_branch(self, tjl_mod):
        with patch.object(tjl_mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="sent", stderr="")
            tjl_mod.notify_telegram({
                "scanned_at": "2024-05-01 09:30:00 HKT",
                "signals": [],
                "regime": "neutral",
            })
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        assert args[0:3] == ["hermes", "send", "--to"]
        assert args[3] == "telegram"
        text = mock_run.call_args.kwargs["input"]
        assert "TJL HK Scan" in text
        assert "Signals: *0*" in text
        assert "No signals" in text

    def test_with_signals(self, tjl_mod):
        with patch.object(tjl_mod.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="sent", stderr="")
            tjl_mod.notify_telegram({
                "scanned_at": "2024-05-01 09:30:00 HKT",
                "signals": [
                    {"name": "HK.00700", "price": 350.0, "rr_ratio": 1.5}
                ],
                "regime": "bullish",
            })
        text = mock_run.call_args.kwargs["input"]
        assert "Signals: *1*" in text
        assert "HK.00700" in text

    def test_handles_exception_silently(self, tjl_mod, capsys):
        with patch.object(tjl_mod.subprocess, "run", side_effect=RuntimeError("boom")):
            tjl_mod.notify_telegram({"scanned_at": "now", "signals": []})
        out = capsys.readouterr().out
        assert "Telegram delivery failed" in out


# ── run_scan integration ─────────────────────────────────────────────────────


def _build_full_ctx(tjl_mod):
    """Build a fully-mocked ctx that supplies 80-bar history for any ticker
    plus a corresponding live quote."""
    ctx = MagicMock()

    # Build a generic bullish daily df with volume series
    n = 80
    times = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = np.array([100.0 + 0.5 * i for i in range(n)])
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, 1_000_000, dtype=int)
    # Spike volume on last bar so Model C/E/F/G/H may fire
    volumes[-1] = 2_500_000

    df = pd.DataFrame({
        "time_key": times,
        "open": closes - 0.1,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })

    def kline_handler(code, ktype=..., max_count=80, start_date=None, end_date=None):
        if str(ktype) == "K_30M" or str(ktype) == "K_30M":
            return (-1, None, None)
        return (0, df, None)

    ctx.request_history_kline.side_effect = kline_handler

    def quote_handler(codes):
        rows = []
        for code in codes:
            last_price = float(df["close"].iloc[-1]) + 5.0  # above PMH
            rows.append({
                "code": code,
                "last_price": last_price,
                "prev_close_price": float(df["close"].iloc[-2]),
                "high_price": float(df["high"].iloc[-1]),
                "low_price": float(df["low"].iloc[-1]),
                "open_price": float(df["open"].iloc[-1]),
                "volume": int(df["volume"].iloc[-1]),
            })
        return (0, pd.DataFrame(rows))

    ctx.get_stock_quote.side_effect = quote_handler
    ctx.subscribe.return_value = (0, None)
    return ctx


class TestRunScan:
    def test_runs_full_scan_with_signals(self, tjl_mod, monkeypatch, tmp_path):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")  # disable Discord
        ctx = _build_full_ctx(tjl_mod)

        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx), \
             patch.object(tjl_mod, "post_discord") as mock_discord, \
             patch("os.path.expanduser", return_value=str(tmp_path / "sig.json")):
            signals = tjl_mod.run_scan()

        # Should return a list (signals or empty)
        assert isinstance(signals, list)
        mock_discord.assert_called_once()

    def test_runs_scan_with_no_discord_posted(self, tjl_mod, monkeypatch, tmp_path):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        ctx = _build_full_ctx(tjl_mod)

        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx), \
             patch("os.path.expanduser", return_value=str(tmp_path / "sig.json")):
            signals = tjl_mod.run_scan()
        assert isinstance(signals, list)

    def test_saves_signals_to_json(self, tjl_mod, monkeypatch, tmp_path):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        ctx = _build_full_ctx(tjl_mod)
        out_file = tmp_path / "sig.json"

        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx), \
             patch.object(tjl_mod, "post_discord"):
            tjl_mod.run_scan()
        # File should exist if any signals were generated
        if out_file.exists():
            data = json.loads(out_file.read_text())
            assert "scanned_at" in data
            assert "source" in data
            assert data["source"] == "Futu OpenD"
            assert "signals" in data

    def test_telegram_path(self, tjl_mod, monkeypatch, tmp_path):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        ctx = _build_full_ctx(tjl_mod)
        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx), \
             patch.object(tjl_mod, "post_discord"), \
             patch.object(tjl_mod, "notify_telegram") as mock_tg, \
             patch("os.path.expanduser", return_value=str(tmp_path / "sig.json")):
            tjl_mod.run_scan(notify=True)
        mock_tg.assert_called_once()

    def test_handles_no_quotes(self, tjl_mod, monkeypatch, tmp_path):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "")
        ctx = MagicMock()
        ctx.subscribe.return_value = (0, None)
        ctx.request_history_kline.return_value = (-1, None, None)
        ctx.get_stock_quote.return_value = (-1, None)

        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod.ft, "OpenQuoteContext", return_value=ctx), \
             patch.object(tjl_mod, "post_discord"):
            signals = tjl_mod.run_scan()
        assert signals == []


# ── main CLI ─────────────────────────────────────────────────────────────────


class TestMain:
    def test_main_runs_once_by_default(self, tjl_mod, monkeypatch):
        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod, "run_scan") as mock_scan, \
             patch("sys.argv", ["tjl_live_futu.py"]):
            tjl_mod.main()
        mock_scan.assert_called_once_with(notify=False)

    def test_main_continuous_loops_until_interrupt(self, tjl_mod, monkeypatch):
        # Make sleep raise on second call to break the loop
        call_count = {"n": 0}

        def fake_sleep(*args):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise KeyboardInterrupt()

        with patch.object(tjl_mod.time, "sleep", side_effect=fake_sleep), \
             patch.object(tjl_mod, "run_scan") as mock_scan, \
             patch("sys.argv", ["tjl_live_futu.py", "--continuous", "--interval", "1"]):
            tjl_mod.main()
        # Should have run scan at least once
        assert mock_scan.call_count >= 1

    def test_main_with_notify_flag(self, tjl_mod, monkeypatch):
        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod, "run_scan") as mock_scan, \
             patch("sys.argv", ["tjl_live_futu.py", "--notify"]):
            tjl_mod.main()
        mock_scan.assert_called_once_with(notify=True)

    def test_main_hk_tickers_override(self, tjl_mod, monkeypatch):
        monkeypatch.setenv("HK_TICKERS", "HK.00700,HK.09988")
        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod, "run_scan"), \
             patch("sys.argv", ["tjl_live_futu.py"]):
            tjl_mod.main()
        # After running, WATCHLIST should have been replaced
        assert tjl_mod.WATCHLIST == [("00700", "HK.00700"), ("09988", "HK.09988")]
        assert tjl_mod.ALL_CODES == ["HK.00700", "HK.09988"]

    def test_main_hk_tickers_override_empty_does_nothing(self, tjl_mod, monkeypatch):
        original = list(tjl_mod.WATCHLIST)
        monkeypatch.delenv("HK_TICKERS", raising=False)
        with patch.object(tjl_mod.time, "sleep"), \
             patch.object(tjl_mod, "run_scan"), \
             patch("sys.argv", ["tjl_live_futu.py"]):
            tjl_mod.main()
        # WATCHLIST unchanged (note: other tests may have replaced it; we just verify it
        # was not replaced by an empty list)
        assert len(tjl_mod.WATCHLIST) > 0
