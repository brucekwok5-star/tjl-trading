"""Shared pytest config for TJL scanner tests."""
import sys, os

sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')
os.environ.pop('DISCORD_WEBHOOK_HK_TJL', None)

import pytest

@pytest.fixture(autouse=True)
def clear_regime_cache():
    """Clear REGIME_CACHE before each test to prevent cross-test pollution."""
    import tjl_ndx11_hkstyle as s
    s.REGIME_CACHE = {'result': None, 'timestamp': 0.0}
    yield
    s.REGIME_CACHE = {'result': None, 'timestamp': 0.0}
