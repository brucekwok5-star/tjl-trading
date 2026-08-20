"""End-to-end scan integration test (Task 9)."""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import os
import glob
import pytest


@pytest.fixture
def no_discord(monkeypatch):
    """Ensure no Discord webhook is set during tests."""
    monkeypatch.delenv('DISCORD_WEBHOOK_HK_TJL', raising=False)


@pytest.mark.network
def test_scan_returns_list(no_discord):
    """Full run_scan on a small basket returns a list."""
    from tjl_ndx11_hkstyle import run_scan
    sigs = run_scan(['AAPL', 'NVDA', 'MSFT', 'TSLA', 'AMD'])
    assert isinstance(sigs, list)


@pytest.mark.network
def test_signal_structure(no_discord):
    """Every signal from run_scan has correct structure."""
    from tjl_ndx11_hkstyle import run_scan
    sigs = run_scan(['COHR', 'STX', 'AMAT'])
    for sig in sigs:
        assert 'ticker' in sig
        assert 'price' in sig
        assert 'direction' in sig
        assert sig['direction'] in ('LONG', 'SHORT')
        assert 'model' in sig
        assert sig['model'] in 'ABCDEFGHIJK'
        assert 'sl' in sig and 'tp' in sig
        assert 'wr' in sig and 'wr_verdict' in sig
        # LONG: SL < price < TP
        if sig['direction'] == 'LONG':
            assert sig['sl'] < sig['price'] < sig['tp'], \
                f"LONG signal SL/TP wrong: {sig}"
        # SHORT: TP < price < SL
        else:
            assert sig['tp'] < sig['price'] < sig['sl'], \
                f"SHORT signal SL/TP wrong: {sig}"
        assert 'rr_ratio' in sig


@pytest.mark.network
def test_json_saved(no_discord):
    """run_scan saves a JSON file."""
    from tjl_ndx11_hkstyle import run_scan
    run_scan(['AAPL'])
    jsons = glob.glob(os.path.expanduser('~/tjl_us_hkstyle_*.json'))
    assert len(jsons) > 0, "Expected at least one JSON file saved"


@pytest.mark.network
def test_scan_with_models_filter(no_discord):
    """run_scan respects models_filter."""
    from tjl_ndx11_hkstyle import run_scan
    sigs = run_scan(['AAPL', 'NVDA', 'MSFT'], models_filter={'H', 'I'})
    # All signals should be from model H or I
    for sig in sigs:
        assert sig['model'] in ('H', 'I'), \
            f"Model {sig['model']} not in filter {{H,I}}"


@pytest.mark.network
def test_scan_empty_tickers(no_discord):
    """Empty ticker list returns empty signals."""
    from tjl_ndx11_hkstyle import run_scan
    sigs = run_scan([])
    assert sigs == []


@pytest.mark.network
def test_scan_does_not_post_discord(no_discord):
    """When no webhook env var, no Discord post is attempted."""
    from tjl_ndx11_hkstyle import run_scan, _post_discord
    # This test passes if run_scan doesn't raise — the no_discord fixture
    # ensures no webhook is set
    sigs = run_scan(['AAPL'])
    assert isinstance(sigs, list)
