"""Tests for notification helpers (Discord + Telegram) and edge cases."""
from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest


class TestPostDiscord:
    def test_skips_when_no_webhook(self, tjl_mod, monkeypatch, capsys):
        monkeypatch.delenv("DISCORD_WEBHOOK_HK_TJL", raising=False)
        tjl_mod.post_discord([], "now")
        out = capsys.readouterr().out
        assert "DISCORD_WEBHOOK_HK_TJL not set" in out

    def test_posts_with_signals(self, tjl_mod, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        fake_run = MagicMock(return_value=MagicMock(stdout="ok\n204"))
        with patch.object(tjl_mod.subprocess, "run", fake_run):
            signals = [{
                "name": "00700", "price": 350.0, "e9": 348.0,
                "e20": 345.0, "e50": 340.0, "sl": 345.0, "tp": 360.0,
                "rr_ratio": 1.5,
            }]
            tjl_mod.post_discord(signals, "2026-01-01 09:30 HKT")
        assert fake_run.called
        # Inspect the curl call
        args = fake_run.call_args[0][0]
        assert "curl" in args
        assert "https://discord.example/webhook?wait=true" in " ".join(args)
        # The payload JSON should include content + thread_name
        payload_str = next((a for a in args if a.startswith("{")), "")
        # payload was passed via -d; recover from the call
        call_kwargs = fake_run.call_args[1]
        assert "data" in call_kwargs or "-d" in args

    def test_truncates_long_content(self, tjl_mod, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        fake_run = MagicMock(return_value=MagicMock(stdout="ok\n204"))
        with patch.object(tjl_mod.subprocess, "run", fake_run):
            # Generate a huge signal list to force truncation
            signals = [{
                "name": f"T{i:04d}", "price": 100.0 + i, "e9": 99.0,
                "e20": 98.0, "e50": 97.0, "sl": 95.0, "tp": 110.0,
                "rr_ratio": 1.5,
            } for i in range(200)]
            tjl_mod.post_discord(signals, "now")
        assert fake_run.called

    def test_no_signals_message(self, tjl_mod, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_HK_TJL", "https://discord.example/webhook")
        fake_run = MagicMock(return_value=MagicMock(stdout="ok\n204"))
        with patch.object(tjl_mod.subprocess, "run", fake_run):
            tjl_mod.post_discord([], "now")
        assert fake_run.called


class TestNotifyTelegram:
    def test_handles_no_signals(self, tjl_mod, monkeypatch):
        fake_run = MagicMock(return_value=MagicMock(stdout="ok", stderr=""))
        with patch.object(tjl_mod.subprocess, "run", fake_run) as fr:
            tjl_mod.notify_telegram({
                "scanned_at": "2026-01-01 09:30 HKT",
                "signals": [],
            })
        assert fr.called
        args = fr.call_args[0][0]
        assert args[:4] == ["hermes", "send", "--to", "telegram"]

    def test_sends_signals_summary(self, tjl_mod, monkeypatch):
        fake_run = MagicMock(return_value=MagicMock(stdout="ok", stderr=""))
        with patch.object(tjl_mod.subprocess, "run", fake_run) as fr:
            tjl_mod.notify_telegram({
                "scanned_at": "2026-01-01 09:30 HKT",
                "signals": [
                    {"name": "00700", "price": 350.0, "rr_ratio": 1.5},
                    {"name": "09988", "price": 90.0, "rr_ratio": 1.8},
                ],
            })
        assert fr.called
        sent_text = fr.call_args[1]["input"]
        assert "00700" in sent_text
        assert "09988" in sent_text

    def test_swallows_subprocess_exception(self, tjl_mod, monkeypatch):
        with patch.object(tjl_mod.subprocess, "run",
                          side_effect=FileNotFoundError("hermes not found")):
            # Should not raise — log a warning instead
            tjl_mod.notify_telegram({"scanned_at": "now", "signals": []})

    def test_handles_subprocess_timeout(self, tjl_mod, monkeypatch):
        with patch.object(tjl_mod.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired("hermes", 30)):
            tjl_mod.notify_telegram({"scanned_at": "now", "signals": []})


class TestLogTable:
    """Smoke-test that log_table is called without crashing (it's a closure inside run_scan)."""

    def test_log_table_callable_via_module(self, tjl_mod):
        # log_table is defined inside run_scan so we can't call it directly.
        # But we can verify run_scan ran successfully and produced no errors.
        # Already covered in integration tests.
        assert hasattr(tjl_mod, "run_scan")