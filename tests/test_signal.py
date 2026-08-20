"""Signal construction tests: SL/TP/R:R correctness (Task 7)."""
import sys
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import pytest
from tjl_ndx11_hkstyle import (
    make_signal,
    ATR_SL_TIGHT, ATR_TP_TIGHT, ATR_SL_WIDE, ATR_TP_WIDE,
)


class TestSignalLONG:
    def test_long_tight_sl_below_tp_above(self):
        """Tight models (D/E/F/G/H/J/K): SL = price - 1.0×ATR, TP = price + 1.5×ATR."""
        sig = make_signal('TEST', 100.0, 'LONG', 'F', 2.0)
        assert sig['sl'] == pytest.approx(100 - ATR_SL_TIGHT * 2.0)
        assert sig['tp'] == pytest.approx(100 + ATR_TP_TIGHT * 2.0)
        assert sig['rr_ratio'] == 1.5

    def test_long_wide_sl_below_tp_above(self):
        """Wide models (A/B/C/I): SL = price - 1.5×ATR, TP = price + 3.0×ATR."""
        sig = make_signal('TEST', 100.0, 'LONG', 'A', 2.0)
        assert sig['sl'] == pytest.approx(100 - ATR_SL_WIDE * 2.0)
        assert sig['tp'] == pytest.approx(100 + ATR_TP_WIDE * 2.0)
        assert sig['rr_ratio'] == 2.0

    def test_long_i_is_wide(self):
        """Model I uses wide ATR multipliers."""
        sig = make_signal('TEST', 100.0, 'LONG', 'I', 2.0)
        assert sig['atr_type'] == 'wide'
        assert sig['rr_ratio'] == 2.0


class TestSignalSHORT:
    def test_short_tight_sl_above_tp_below(self):
        """SHORT: SL above entry, TP below entry."""
        sig = make_signal('TEST', 100.0, 'SHORT', 'F', 2.0)
        assert sig['sl'] > 100.0, "SHORT SL must be above entry"
        assert sig['tp'] < 100.0, "SHORT TP must be below entry"
        assert sig['rr_ratio'] == 1.5

    def test_short_wide_sl_above_tp_below(self):
        sig = make_signal('TEST', 100.0, 'SHORT', 'I', 2.0)
        assert sig['sl'] > 100.0
        assert sig['tp'] < 100.0
        assert sig['rr_ratio'] == 2.0

    def test_short_sl_tp_symmetry(self):
        """SHORT: SL = price + SL_mult×ATR, TP = price - TP_mult×ATR."""
        sig = make_signal('TEST', 100.0, 'SHORT', 'H', 3.0)
        assert sig['sl'] == pytest.approx(100 + ATR_SL_TIGHT * 3.0)
        assert sig['tp'] == pytest.approx(100 - ATR_TP_TIGHT * 3.0)


class TestSignalFields:
    def test_signal_has_required_fields(self):
        """Every signal must have these fields."""
        sig = make_signal('TEST', 100.0, 'LONG', 'A', 2.0)
        for field in ('ticker', 'price', 'direction', 'model',
                      'sl', 'tp', 'rr_ratio', 'atr', 'wr', 'wr_verdict', 'atr_type'):
            assert field in sig, f"Missing field: {field}"

    def test_signal_ema_fields_when_provided(self):
        """When e9 is passed, near_pct and e9 are included."""
        sig = make_signal('TEST', 100.0, 'LONG', 'A', 2.0, e9=99.0)
        assert 'e9' in sig
        assert 'near_pct' in sig
        assert sig['e9'] == 99.0

    def test_signal_extra_fields(self):
        """Extra dict fields are merged into signal."""
        sig = make_signal('TEST', 100.0, 'LONG', 'E', 2.0,
                          extra={'squeeze': True, 'rsi': 55.3})
        assert sig['squeeze'] is True
        assert sig['rsi'] == 55.3

    def test_wr_lookup(self):
        """Win rate is looked up from MODEL_WR."""
        sig = make_signal('TEST', 100.0, 'LONG', 'J', 2.0)
        assert sig['wr'] == 54  # Model J has wr=54 in MODEL_WR
        assert sig['wr_verdict'] == 'profitable'

    def test_atr_type_classification(self):
        """Wide models: A/B/C/I; tight models: D/E/F/G/H/J/K."""
        for model in ('A', 'B', 'C', 'I'):
            sig = make_signal('T', 100.0, 'LONG', model, 2.0)
            assert sig['atr_type'] == 'wide', f"Model {model} should be wide"
        for model in ('D', 'E', 'F', 'G', 'H', 'J', 'K'):
            sig = make_signal('T', 100.0, 'LONG', model, 2.0)
            assert sig['atr_type'] == 'tight', f"Model {model} should be tight"
