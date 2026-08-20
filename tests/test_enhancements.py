"""Phase 6 Enhancement tests: regime caching, confidence scoring, Telegram."""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import pytest
from unittest.mock import patch, MagicMock
import time


class TestRegimeCaching:
    """Verify get_regime() caching works (5-min TTL)."""

    def test_regime_returns_from_cache_on_second_call(self, monkeypatch):
        """Second call within TTL should NOT recompute (cache hit)."""
        import tjl_ndx11_hkstyle as m

        call_count = 0

        def mock_cached():
            nonlocal call_count
            call_count += 1
            return "BULLISH"

        # Clear module-level cache
        m.REGIME_CACHE['result'] = None
        m.REGIME_CACHE['timestamp'] = 0.0
        m._get_regime_cached.cache_clear()

        monkeypatch.setattr(m, '_get_regime_cached', mock_cached)

        # First call
        r1 = m.get_regime()
        # Second call (should be cached)
        r2 = m.get_regime()

        assert r1 == r2 == "BULLISH"
        assert call_count == 1, "Inner cached fn should only be called once"

    def test_regime_cache_respects_ttl(self, monkeypatch):
        """Cache should expire after REGIME_CACHE_TTL seconds."""
        import tjl_ndx11_hkstyle as m

        call_count = 0

        def mock_cached():
            nonlocal call_count
            call_count += 1
            return "BEARISH"

        m.REGIME_CACHE['result'] = None
        m.REGIME_CACHE['timestamp'] = 0.0
        m._get_regime_cached.cache_clear()
        monkeypatch.setattr(m, '_get_regime_cached', mock_cached)

        # First call
        m.get_regime()
        assert call_count == 1

        # Simulate cache expiry: set timestamp to 10 minutes ago
        m.REGIME_CACHE['timestamp'] = time.time() - 600

        # Should recompute
        m.get_regime()
        assert call_count == 2

    def test_regime_manual_invalidation_works(self, monkeypatch):
        """Setting REGIME_CACHE['timestamp'] = 0 forces recompute."""
        import tjl_ndx11_hkstyle as m

        call_count = 0

        def mock_cached():
            nonlocal call_count
            call_count += 1
            return "neutral"

        m.REGIME_CACHE['result'] = None
        m.REGIME_CACHE['timestamp'] = 0.0
        m._get_regime_cached.cache_clear()
        monkeypatch.setattr(m, '_get_regime_cached', mock_cached)

        m.get_regime()
        assert call_count == 1

        # Manually invalidate
        m.REGIME_CACHE['timestamp'] = 0.0

        m.get_regime()
        assert call_count == 2

    def test_regime_cache_miss_triggers_computation(self, monkeypatch):
        """When cache is empty, should call the cached inner function."""
        import tjl_ndx11_hkstyle as m

        call_count = 0

        def mock_cached():
            nonlocal call_count
            call_count += 1
            return "BULLISH"

        m.REGIME_CACHE['result'] = None
        m.REGIME_CACHE['timestamp'] = 0.0
        m._get_regime_cached.cache_clear()
        monkeypatch.setattr(m, '_get_regime_cached', mock_cached)

        assert call_count == 0
        m.get_regime()
        assert call_count == 1


class TestCalculateConfidence:
    """Verify calculate_confidence() formula correctness."""

    def test_confidence_bullish_regime_long_direction(self):
        from tjl_ndx11_hkstyle import calculate_confidence
        # Model J: wr=54, rr_ratio=1.5, BULLISH + LONG → regime matches
        conf = calculate_confidence(54, 'BULLISH', 'LONG', 1.5)
        expected = round((54 / 100) * 1.2 * (1.5 / 2.0), 3)
        assert conf == expected, f"Expected {expected}, got {conf}"

    def test_confidence_bearish_regime_short_direction(self):
        from tjl_ndx11_hkstyle import calculate_confidence
        # Regime matches direction → 1.2 multiplier
        conf = calculate_confidence(45, 'BEARISH', 'SHORT', 1.5)
        expected = round((45 / 100) * 1.2 * (1.5 / 2.0), 3)
        assert conf == expected

    def test_confidence_regime_mismatch_no_multiplier(self):
        from tjl_ndx11_hkstyle import calculate_confidence
        # BULLISH regime but SHORT direction → no regime match bonus
        conf = calculate_confidence(45, 'BULLISH', 'SHORT', 1.5)
        expected = round((45 / 100) * 1.0 * (1.5 / 2.0), 3)
        assert conf == expected

    def test_confidence_neutral_regime(self):
        from tjl_ndx11_hkstyle import calculate_confidence
        # neutral regime → no match bonus
        conf = calculate_confidence(48, 'neutral', 'LONG', 2.0)
        expected = round((48 / 100) * 1.0 * (2.0 / 2.0), 3)
        assert conf == expected

    def test_confidence_zero_wr(self):
        from tjl_ndx11_hkstyle import calculate_confidence
        conf = calculate_confidence(0, 'BULLISH', 'LONG', 1.5)
        assert conf == 0.0

    def test_confidence_max_wr_and_rr(self):
        from tjl_ndx11_hkstyle import calculate_confidence
        # Max possible: wr=100, rr_ratio=2.0, regime matches
        conf = calculate_confidence(100, 'BULLISH', 'LONG', 2.0)
        expected = round((100 / 100) * 1.2 * (2.0 / 2.0), 3)
        assert conf == expected

    def test_confidence_in_signal_output(self):
        """make_signal with regime= should include confidence field."""
        from tjl_ndx11_hkstyle import make_signal
        sig = make_signal('TEST', 100.0, 'LONG', 'J', 2.0, regime='BULLISH')
        assert 'confidence' in sig
        # Model J wr=54, BULLISH+LONG match, rr=1.5 (tight ATR)
        expected = round((54 / 100) * 1.2 * (1.5 / 2.0), 3)
        assert sig['confidence'] == expected

    def test_confidence_not_in_signal_without_regime(self):
        """make_signal without regime= should NOT include confidence."""
        from tjl_ndx11_hkstyle import make_signal
        sig = make_signal('TEST', 100.0, 'LONG', 'J', 2.0)
        assert 'confidence' not in sig


class TestPostTelegram:
    """Verify post_telegram graceful behavior."""

    def test_telegram_noop_when_no_token(self, monkeypatch):
        """post_telegram should return silently when TELEGRAM_BOT_TOKEN not set."""
        import os
        import tjl_ndx11_hkstyle as m

        # Ensure no token
        monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)

        # Track that requests.post is NOT called
        called = False
        original_post = getattr(m.requests, 'post', None)

        def track_post(*args, **kwargs):
            nonlocal called
            called = True
            if original_post:
                return original_post(*args, **kwargs)
            raise RuntimeError("Should not be called")

        monkeypatch.setattr(m.requests, 'post', track_post)

        m.post_telegram([], 'BULLISH', '2026-08-13 10:00 ET')

        assert not called, "requests.post should NOT be called when no token"

    def test_telegram_noop_with_empty_signals(self, monkeypatch):
        """post_telegram should return silently even if token is set but no signals."""
        import tjl_ndx11_hkstyle as m

        monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_token_123')
        called = False

        def track_post(*args, **kwargs):
            nonlocal called
            called = True
            raise RuntimeError("Should not be called when signals empty")

        monkeypatch.setattr(m.requests, 'post', track_post)

        m.post_telegram([], 'BULLISH', '2026-08-13 10:00 ET')

        assert not called

    def test_telegram_called_when_token_set_and_signals_present(self, monkeypatch):
        """post_telegram should call API when token is set and signals exist."""
        import tjl_ndx11_hkstyle as m

        monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_token_abc')

        mock_response = MagicMock()
        mock_response.status_code = 200
        called_args = []

        def track_post(url, json=None, **kwargs):
            called_args.append((url, json))
            return mock_response

        monkeypatch.setattr(m.requests, 'post', track_post)

        sigs = [{
            'ticker': 'AAPL',
            'model': 'H',
            'price': 175.0,
            'direction': 'LONG',
            'sl': 173.0,
            'tp': 178.0,
            'rr_ratio': 1.5,
            'wr': 45,
            'confidence': 0.405,
        }]

        m.post_telegram(sigs, 'BULLISH', '2026-08-13 10:00 ET')

        assert len(called_args) == 1
        url, payload = called_args[0]
        assert 'api.telegram.org' in url
        assert 'test_token_abc' in url
        assert payload['chat_id'] == '8370185160'
        assert 'AAPL' in payload['text']
        assert 'conf=0.405' in payload['text']

    def test_telegram_message_contains_confidence(self, monkeypatch):
        """Telegram message should include confidence score when present."""
        import tjl_ndx11_hkstyle as m

        monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_token_xyz')

        mock_response = MagicMock()
        mock_response.status_code = 200
        captured = []

        def track_post(url, json=None, **kwargs):
            captured.append(json)
            return mock_response

        monkeypatch.setattr(m.requests, 'post', track_post)

        sigs = [{
            'ticker': 'NVDA',
            'model': 'J',
            'price': 500.0,
            'direction': 'LONG',
            'sl': 495.0,
            'tp': 510.0,
            'rr_ratio': 2.0,
            'wr': 54,
            'confidence': 0.324,
        }]

        m.post_telegram(sigs, 'neutral', '2026-08-13 12:00 ET')

        assert len(captured) == 1
        assert 'conf=' in captured[0]['text']
        assert '0.324' in captured[0]['text']
