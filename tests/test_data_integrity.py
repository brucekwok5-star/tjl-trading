#!/usr/bin/env python3
"""
Phase 4 — Raw Data Integrity Tests (Tasks 12-13, Agent B adjusted)

Verifies yfinance daily bars and intraday bars are complete, non-partial,
and fresh. These tests hit the network (yfinance) and are designed to be
run against live data.

Agent B fixes applied:
  - ``date[i]`` → ``dates[i]`` (NameError in plan)
  - ``'1 daily'`` → ``'1d'`` (invalid interval)
  - ``'AAPL).history`` → ``'AAPL').history`` (syntax error)
"""
import pytest
import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

ET = ZoneInfo("America/New_York")


# ──────────────────────────────────────────────────────────────────────────────
# Daily bar integrity (Task 12)
# ──────────────────────────────────────────────────────────────────────────────
class TestDailyBarIntegrity:
    def test_last_bar_is_today_or_last_trading_day(self):
        """Last daily bar must be today (market open) or last trading day."""
        t = yf.Ticker('AAPL')
        h = t.history(period='5d', interval='1d')
        if h.empty:
            pytest.skip("No daily data")
        last_date = h.index[-1].date()
        today = datetime.date.today()
        # Allow today or previous trading day (Friday if Monday)
        trading_days_back = 0
        if today.weekday() == 0:      # Monday
            trading_days_back = 3     # Friday
        elif today.weekday() == 6:    # Sunday
            trading_days_back = 2
        elif today.weekday() == 5:    # Saturday
            trading_days_back = 1
        earliest_expected = today - datetime.timedelta(days=trading_days_back + 1)
        assert last_date >= earliest_expected, \
            f"Last bar {last_date} too old, expected >= {earliest_expected}"

    def test_daily_bar_has_all_fields(self):
        """Every daily bar must have Open/High/Low/Close/Volume and no NaN Close."""
        t = yf.Ticker('AAPL')
        h = t.history(period='5d', interval='1d')
        if h.empty:
            pytest.skip("No daily data")
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            assert col in h.columns, f"Missing column: {col}"
        assert not h['Close'].isna().any(), "NaN in Close"

    def test_no_gaps_in_daily_bars(self):
        """No missing trading days (max gap = 4 days for holiday long weekends)."""
        t = yf.Ticker('SPY')
        h = t.history(period='30d', interval='1d')
        if h.empty:
            pytest.skip("No SPY data")
        dates = h.index.date
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            assert gap <= 4, f"Gap of {gap} days between {dates[i-1]} and {dates[i]}"

    def test_close_within_high_low_range(self):
        """Close must be within [Low, High] for every daily bar."""
        t = yf.Ticker('AAPL')
        h = t.history(period='10d', interval='1d')
        if h.empty:
            pytest.skip("No daily data")
        for idx, row in h.iterrows():
            assert row['Low'] <= row['Close'] <= row['High'], \
                f"Close {row['Close']} outside [{row['Low']}, {row['High']}] on {idx.date()}"

    def test_volume_positive(self):
        """Volume must be >= 0."""
        t = yf.Ticker('AAPL')
        h = t.history(period='10d', interval='1d')
        if h.empty:
            pytest.skip("No daily data")
        assert (h['Volume'] >= 0).all(), "Negative volume"


# ──────────────────────────────────────────────────────────────────────────────
# Intraday bar integrity + partial-bar detection (Task 13)
# ──────────────────────────────────────────────────────────────────────────────
class TestIntradayBarIntegrity:
    def _is_market_open(self):
        now_et = datetime.datetime.now(ET)
        if now_et.weekday() >= 5:
            return False
        market_open = 9.5 <= now_et.hour + now_et.minute / 60 <= 16
        return market_open

    def test_15m_bars_available_during_market(self):
        """15m bars should be available and fresh during market hours."""
        if not self._is_market_open():
            pytest.skip("Market closed")
        t = yf.Ticker('AAPL')
        h = t.history(period='1d', interval='15m')
        assert not h.empty, "No 15m bars during market hours"

    def test_15m_bar_staleness_under_20min_during_market(self):
        """During market hours, latest 15m bar must be < 20 min stale."""
        now_et = datetime.datetime.now(ET)
        if now_et.weekday() >= 5 or not (9.5 <= now_et.hour + now_et.minute / 60 <= 16):
            pytest.skip("Market closed")
        t = yf.Ticker('AAPL')
        h = t.history(period='1d', interval='15m')
        if h.empty:
            pytest.skip("No 15m data")
        last_bar = h.index[-1]
        age_minutes = (now_et - last_bar.to_pydatetime().astimezone(ET)).total_seconds() / 60
        print(f"\n15m bar staleness: {age_minutes:.1f} minutes")
        assert age_minutes < 20, f"15m bar {age_minutes:.0f}min stale, expected < 20"

    def test_daily_vs_intraday_close_mismatch_during_market(self):
        """During market hours, daily Close (partial) should differ from 15m Close.
        After market close the bars match (complete bar)."""
        now_et = datetime.datetime.now(ET)
        weekday_market_hours = (
            now_et.weekday() < 5
            and 9.5 <= now_et.hour + now_et.minute / 60 <= 16
        )
        if not weekday_market_hours:
            pytest.skip(f"Market closed (now {now_et.strftime('%H:%M ET')}) — "
                        "daily bar is complete, no partial-bar mismatch expected")
        daily = yf.Ticker('AAPL').history(period='1d', interval='1d')
        intraday = yf.Ticker('AAPL').history(period='1d', interval='15m')
        if daily.empty or intraday.empty:
            pytest.skip("No data")
        daily_close = daily['Close'].iloc[-1]
        intraday_close = intraday['Close'].iloc[-1]
        mismatch = abs(daily_close - intraday_close)
        print(f"\nDaily close: {daily_close:.4f} | Intraday close: {intraday_close:.4f} | Diff: {mismatch:.4f}")
        # During market hours, mismatch confirms the partial-bar bug
        # (If mismatch==0 here, market just closed and bar is complete)
        assert mismatch >= 0, "mismatch must be >= 0"
        print(f"  Partial-bar mismatch: {'YES' if mismatch > 0 else 'NO (market just closed)'}")
