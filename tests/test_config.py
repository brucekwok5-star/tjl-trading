"""Configuration / security tests (Task 4).

Verifies no hardcoded Discord webhook, _prev_closes is reset.
"""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import os
import inspect


SCANNER_PATH = '/Users/jaydensmac/.openclaw/workspace/tjl_ndx11_hkstyle.py'


def test_webhook_not_hardcoded():
    """Discord webhook URL must not be hardcoded in source."""
    source = open(SCANNER_PATH).read()
    assert 'discord.com/api/webhooks' not in source, \
        "Discord webhook URL must not be hardcoded in source"


def test_no_setdefault_webhook():
    """os.environ.setdefault must not be used for Discord webhook."""
    source = open(SCANNER_PATH).read()
    assert 'os.environ.setdefault' not in source or 'DISCORD_WEBHOOK' not in source, \
        "os.environ.setdefault should not reference DISCORD_WEBHOOK"


def test_webhook_from_env_only():
    """Webhook is read via os.environ.get at runtime."""
    # Import the module
    import tjl_ndx11_hkstyle as t
    src = inspect.getsource(t.run_scan)
    assert "os.environ.get('DISCORD_WEBHOOK_HK_TJL')" in src, \
        "run_scan should read webhook from os.environ.get"


def test_prev_closes_reset_in_run_scan():
    """_prev_closes must be reset at the start of run_scan."""
    import tjl_ndx11_hkstyle as t
    src = inspect.getsource(t.run_scan)
    assert '_prev_closes = {}' in src, \
        "run_scan should reset _prev_closes = {}"


def test_prev_closes_is_module_level():
    """_prev_closes exists as a module-level global."""
    import tjl_ndx11_hkstyle as t
    assert hasattr(t, '_prev_closes'), "Module should have _prev_closes global"
    assert isinstance(t._prev_closes, dict)
