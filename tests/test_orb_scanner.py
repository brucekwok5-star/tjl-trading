"""ORB live scanner tests — pure-function logic + Discord payload.

Network-dependent functions (fetch_15m, htf_bias, get_pct_risk, orb_signal)
require live yfinance and are marked with @pytest.mark.network.
"""
import sys
from datetime import date
import json
import urllib.error

sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import pandas as pd
import pytest

from orb_live_scanner import (
    is_trading_day,
    orb_levels,
    confirm_direction,
    post_discord,
    DISCORD_WH,
)


# ── is_trading_day ────────────────────────────────────────────────────────────

class TestIsTradingDay:
    def test_weekday_returns_true(self):
        # 2026-08-18 is a Tuesday
        assert is_trading_day(date(2026, 8, 18)) is True

    def test_saturday_returns_false(self):
        assert is_trading_day(date(2026, 8, 22)) is False

    def test_sunday_returns_false(self):
        assert is_trading_day(date(2026, 8, 23)) is False

    def test_new_years_day_returns_false(self):
        assert is_trading_day(date(2026, 1, 1)) is False

    def test_independence_day_returns_false(self):
        assert is_trading_day(date(2026, 7, 3)) is False

    def test_christmas_returns_false(self):
        assert is_trading_day(date(2026, 12, 25)) is False

    def test_normal_monday_returns_true(self):
        assert is_trading_day(date(2026, 8, 17)) is True


# ── orb_levels ────────────────────────────────────────────────────────────────

class TestOrbLevels:
    """40% of high-open above open, 40% of open-low below open."""

    def test_basic_calculation(self):
        # Open=100, High=105, Low=95  →  ORH = 100 + 0.4*5 = 102,  ORL = 100 - 0.4*5 = 98
        day = pd.DataFrame(
            {"Open": [100.0], "High": [105.0], "Low": [95.0], "Close": [100.0]},
            index=pd.DatetimeIndex(["2026-08-19 09:30"]),
        )
        orh, orl, rng = orb_levels(day)
        assert orh == pytest.approx(102.0)
        assert orl == pytest.approx(98.0)
        assert rng == pytest.approx(10.0)

    def test_asymmetric_range(self):
        # Open=200, High=210, Low=190  →  ORH = 200 + 0.4*10 = 204,  ORL = 200 - 0.4*10 = 196
        day = pd.DataFrame(
            {"Open": [200.0], "High": [210.0], "Low": [190.0], "Close": [200.0]},
            index=pd.DatetimeIndex(["2026-08-19 09:30"]),
        )
        orh, orl, rng = orb_levels(day)
        assert orh == pytest.approx(204.0)
        assert orl == pytest.approx(196.0)
        assert rng == pytest.approx(20.0)

    def test_skewed_bar(self):
        # Open=100, High=108, Low=99  →  high-open=8 → ORH=103.2 ; open-low=1 → ORL=99.6
        day = pd.DataFrame(
            {"Open": [100.0], "High": [108.0], "Low": [99.0], "Close": [101.0]},
            index=pd.DatetimeIndex(["2026-08-19 09:30"]),
        )
        orh, orl, rng = orb_levels(day)
        assert orh == pytest.approx(103.2)
        assert orl == pytest.approx(99.6)
        assert rng == pytest.approx(9.0)

    def test_uses_first_bar_only(self):
        """Only the first 15-min bar drives ORH/ORL; later bars must be ignored."""
        day = pd.DataFrame(
            {
                "Open": [100.0, 200.0],
                "High": [105.0, 999.0],
                "Low": [95.0, 1.0],
                "Close": [100.0, 500.0],
            },
            index=pd.DatetimeIndex([
                "2026-08-19 09:30",
                "2026-08-19 09:45",
            ]),
        )
        orh, orl, rng = orb_levels(day)
        assert orh == pytest.approx(102.0)
        assert orl == pytest.approx(98.0)
        assert rng == pytest.approx(10.0)


# ── confirm_direction ─────────────────────────────────────────────────────────

class TestConfirmDirection:
    def _bar(self, ts, close):
        return pd.DataFrame(
            {"Open": [close], "High": [close + 1], "Low": [close - 1], "Close": [close]},
            index=pd.DatetimeIndex([ts]),
        )

    def test_long_when_close_above_orh(self):
        day = self._bar("2026-08-19 09:35", 105.0)
        assert confirm_direction(day, orh=102.0, orl=98.0, cutoff=pd.Timestamp("2026-08-19 09:35")) == 1

    def test_short_when_close_below_orl(self):
        day = self._bar("2026-08-19 09:35", 95.0)
        assert confirm_direction(day, orh=102.0, orl=98.0, cutoff=pd.Timestamp("2026-08-19 09:35")) == -1

    def test_no_signal_inside_range(self):
        day = self._bar("2026-08-19 09:35", 100.0)
        assert confirm_direction(day, orh=102.0, orl=98.0, cutoff=pd.Timestamp("2026-08-19 09:35")) is None

    def test_no_signal_when_bar_outside_window(self):
        # Bar at 09:50 but cutoff is 09:35 → window [09:35, 09:40] excludes it
        day = self._bar("2026-08-19 09:50", 200.0)
        assert confirm_direction(day, orh=102.0, orl=98.0, cutoff=pd.Timestamp("2026-08-19 09:35")) is None


# ── post_discord payload shape ────────────────────────────────────────────────

class TestPostDiscordPayload:
    """Verify the JSON body has the right shape without hitting Discord."""

    def test_payload_includes_thread_name(self, monkeypatch):
        captured = {}

        class FakeResp:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=10):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.headers)
            captured["url"] = req.full_url
            return FakeResp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        post_discord([{
            "ticker": "TSLA", "dir": "LONG", "bias": "BULL",
            "entry": 339.87, "stop": 336.47, "tp1": 343.27, "tp2": 346.67,
            "orh": 339.80, "orl": 339.50, "range_pct": 1.2, "atr_pct": 1.0,
        }])
        body = captured["body"]
        assert "thread_name" in body
        assert body["thread_name"] == "ORB US Live"
        assert "content" in body
        assert "TSLA" in body["content"]
        assert "LONG" in body["content"]
        assert "339.87" in body["content"]

    def test_payload_user_agent_present(self, monkeypatch):
        captured = {}

        class FakeResp:
            status = 204
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=10):
            captured["headers"] = dict(req.headers)
            return FakeResp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        post_discord([])
        # No signals → returns early, never posts. Use one signal instead.
        post_discord([{
            "ticker": "QQQ", "dir": "LONG", "bias": "BULL",
            "entry": 100, "stop": 99, "tp1": 101, "tp2": 102,
            "orh": 99.5, "orl": 99.0, "range_pct": 1.0, "atr_pct": 1.0,
        }])
        ua = captured["headers"].get("User-agent", "")
        assert ua, "User-Agent header missing — Cloudflare will 403"
        assert "orb-live-scanner" in ua

    def test_no_post_when_signals_empty(self, monkeypatch):
        called = {"n": 0}

        def fake_urlopen(*a, **k):
            called["n"] += 1
            raise AssertionError("urlopen must not be called for empty signals")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        post_discord([])
        assert called["n"] == 0

    def test_webhook_url_is_configured(self):
        """Guard against the placeholder being reintroduced."""
        assert "YOUR_WEBHOOK_HERE" not in DISCORD_WH, (
            "DISCORD_WH is the placeholder; scanner will 403"
        )
        assert DISCORD_WH.startswith("https://discord.com/api/webhooks/")


# ── Network-marked end-to-end (skipped if yfinance unavailable) ───────────────

@pytest.mark.network
class TestOrbSignalLive:
    """End-to-end live scan. Requires network + yfinance."""

    def test_today_produces_valid_signal_or_none(self):
        from orb_live_scanner import orb_signal
        today = pd.Timestamp.now("America/New_York").normalize()
        sig = orb_signal("QQQ", today)
        if sig is not None:
            assert sig["ticker"] == "QQQ"
            assert sig["dir"] in ("LONG", "SHORT")
            assert sig["entry"] > 0
            assert sig["stop"] > 0
            assert sig["tp1"] > 0
            assert sig["tp2"] > 0
            if sig["dir"] == "LONG":
                assert sig["stop"] < sig["entry"]
                assert sig["tp1"] > sig["entry"]
                assert sig["tp2"] > sig["tp1"]
            else:
                assert sig["stop"] > sig["entry"]
                assert sig["tp1"] < sig["entry"]
                assert sig["tp2"] < sig["tp1"]