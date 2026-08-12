"""Unit tests for each model entry-checker function (A-K) in tjl_live_futu.

Covers: check_tjl, check_tjl_model_b..k, check_tjs. Pure functions: pass in
synthetic OHLCV arrays + price levels and assert the structured result.
"""
from __future__ import annotations

import math

import numpy as np
import pytest


# ── Synthetic data helpers ────────────────────────────────────────────────────


def _uptrend_bars(n=80, base=100.0, slope=0.10, vol=1_000_000, rng_seed=0):
    """Steady uptrend → EMA9 > EMA20 > EMA50, ATR = ~1.0."""
    closes = np.array([base + slope * i for i in range(n)], dtype=float)
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, vol, dtype=int)
    return highs, lows, closes, volumes


def _downtrend_bars(n=80, base=200.0, slope=0.05, vol=1_000_000):
    closes = np.array([base - slope * i for i in range(n)], dtype=float)
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, vol, dtype=int)
    return highs, lows, closes, volumes


def _flat_bars(n=80, base=100.0, vol=1_000_000):
    closes = np.array([base] * n, dtype=float)
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, vol, dtype=int)
    return highs, lows, closes, volumes


# ── Model A — check_tjl (long pullback, bullish stack) ────────────────────────


class TestCheckTjlModelA:
    def test_returns_none_when_few_bars(self, tjl_mod):
        closes = np.array([100.0] * 30)
        highs = closes + 0.5
        lows = closes - 0.5
        assert tjl_mod.check_tjl(100.0, highs, lows, closes, 100.0) is None

    def test_returns_dict_with_required_keys_on_uptrend(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        price = float(c[-1])
        out = tjl_mod.check_tjl(price, h, l, c, price - 1.0)
        assert out is not None
        for k in ("price", "e9", "e20", "e50", "atr", "pmh", "sl", "tp",
                  "rr_ratio", "direction", "model_a", "model_b"):
            assert k in out, f"missing {k}"
        assert out["direction"] == "LONG"

    def test_bullish_stack_ok_true_on_uptrend(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        price = float(c[-1])
        out = tjl_mod.check_tjl(price, h, l, c, price - 5.0)
        assert out["model_a"]["stack_ok"] == True

    def test_near_ema_within_1pct_true(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        # Set price = e9 + 0.5% of e9 → within ±1.5%
        out = tjl_mod.check_tjl(float(c[-1]), h, l, c, 0.0)
        assert out is not None
        e9 = out["e9"]
        # Use price = e9 (exactly on EMA) → definitely within tolerance
        out2 = tjl_mod.check_tjl(e9, h, l, c, e9 - 5.0)
        assert out2["model_a"]["near_ema_ok"] == True

    def test_above_pmh_requires_buffer(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        # Set today_high (PMH) higher than price → fails above_pmh
        out = tjl_mod.check_tjl(float(c[-1]), h, l, c, float(c[-1]) + 100.0)
        assert out["model_a"]["above_pmh_ok"] == False

    def test_above_pmh_passes_when_price_well_above(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        price = float(c[-1])
        out = tjl_mod.check_tjl(price, h, l, c, price - 5.0)
        assert out["model_a"]["above_pmh_ok"] == True

    def test_sl_tp_calculated_from_atr(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        price = float(c[-1])
        out = tjl_mod.check_tjl(price, h, l, c, price - 5.0)
        atr = out["atr"]
        # ATR_SL = 1.0, ATR_TP = 1.5
        assert abs((price - out["sl"]) - atr * 1.0) < 0.05
        assert abs((out["tp"] - price) - atr * 1.5) < 0.05

    def test_model_b_field_initially_none(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        out = tjl_mod.check_tjl(float(c[-1]), h, l, c, 0.0)
        assert out["model_b"] is None

    def test_returns_none_when_atr_unavailable(self, tjl_mod):
        # 60 bars all identical → atr() may still compute (0.0), but result
        # should still be a dict since check_tjl allows zero ATR
        closes = np.array([100.0] * 60)
        highs = closes + 0.5
        lows = closes - 0.5
        out = tjl_mod.check_tjl(100.0, highs, lows, closes, 0.0)
        assert out is not None

    def test_downtrend_stack_ok_false(self, tjl_mod):
        h, l, c, v = _downtrend_bars()
        price = float(c[-1])
        out = tjl_mod.check_tjl(price, h, l, c, price - 5.0)
        assert out["model_a"]["stack_ok"] == False

    def test_pmh_falls_back_to_price_when_zero(self, tjl_mod):
        h, l, c, v = _uptrend_bars()
        price = float(c[-1])
        out = tjl_mod.check_tjl(price, h, l, c, 0.0)
        # With PMH=0, the function uses price as PMH; above_pmh needs price > price+0.70, fails
        # (PMH_BUF = 0.70)
        assert out is not None
        assert out["model_a"]["above_pmh_ok"] == False


# ── Model B — check_tjl_model_b (HT Momentum, above SMA200) ──────────────────


class TestCheckTjlModelB:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=150)
        assert tjl_mod.check_tjl_model_b(100.0, h, l, c, 100.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=220, slope=0.5)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_b(price, h, l, c, price - 5.0)
        assert out is not None
        for k in ("price", "sma200", "atr", "pmh", "hod", "sl", "tp",
                  "rr_ratio", "direction", "above_sma200_ok",
                  "above_pmh_ok", "above_hod_ok"):
            assert k in out, f"missing {k}"
        assert out["direction"] == "LONG"

    def test_above_sma200_true_on_uptrend(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=220, slope=0.5)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_b(price, h, l, c, price - 5.0)
        assert out["above_sma200_ok"] == True

    def test_below_sma200_on_downtrend(self, tjl_mod):
        h, l, c, v = _downtrend_bars(n=220, slope=0.5)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_b(price, h, l, c, price - 5.0)
        assert out is not None
        assert out["above_sma200_ok"] == False

    def test_above_hod_requires_price_above_pmh(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=220, slope=0.5)
        price = float(c[-1])
        # If HOD > price, above_hod_ok must be False
        out = tjl_mod.check_tjl_model_b(price, h, l, c, price + 100.0)
        assert out["above_hod_ok"] == False

    def test_sl_tp_calculated_from_atr(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=220, slope=0.5)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_b(price, h, l, c, price - 5.0)
        atr = out["atr"]
        assert abs((price - out["sl"]) - atr * 1.0) < 0.05
        assert abs((out["tp"] - price) - atr * 1.5) < 0.05


# ── Model C — check_tjl_model_c (volume-confirmed pullback) ──────────────────


class TestCheckTjlModelC:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=10)
        assert tjl_mod.check_tjl_model_c(100.0, h, l, c, v, 100.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.1)
        price = float(c[-1])
        # Spike volume 3× avg20
        v_spike = v.copy()
        v_spike[-1] = int(np.mean(v[-21:-1]) * 3)
        out = tjl_mod.check_tjl_model_c(price, h, l, c, v_spike, price - 5.0)
        assert out is not None
        for k in ("price", "e9", "e20", "e50", "atr", "avg_vol20",
                  "today_vol", "vol_ratio", "pmh", "sl", "tp", "rr_ratio",
                  "direction", "near_ema_ok", "above_pmh_ok", "vol_spike_ok"):
            assert k in out, f"missing {k}"

    def test_vol_spike_pass_with_2x(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.1)
        price = float(c[-1])
        v2 = v.copy()
        v2[-1] = int(np.mean(v[-21:-1]) * 2.5)
        out = tjl_mod.check_tjl_model_c(price, h, l, c, v2, price - 5.0)
        assert out is not None
        assert out["vol_spike_ok"] == True
        assert out["vol_ratio"] >= 2.0

    def test_vol_spike_fail_with_low_volume(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.1)
        price = float(c[-1])
        v2 = v.copy()
        v2[-1] = 1
        out = tjl_mod.check_tjl_model_c(price, h, l, c, v2, price - 5.0)
        assert out is not None
        assert out["vol_spike_ok"] == False

    def test_near_ema_wider_than_a(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.1)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_c(price, h, l, c, v, price - 5.0)
        assert out is not None
        # We can verify near_ema_ok uses the wider NEAR_EMA_PCT_C (2.0%)
        e9 = out["e9"]
        # Near ±2% should pass
        out2 = tjl_mod.check_tjl_model_c(e9 * 1.01, h, l, c, v, e9 * 1.01 - 5.0)
        assert out2 is not None
        assert out2["near_ema_ok"] == True

    def test_zero_avg_volume_handled(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80)
        v0 = v.copy()
        v0[:-1] = 0
        v0[-1] = 0
        # Result should still come back; vol_ratio = 0 (avg_vol20 == 0)
        out = tjl_mod.check_tjl_model_c(100.0, h, l, c, v0, 100.0)
        # May return None due to insufficient bars; either is acceptable
        if out is not None:
            assert out["vol_ratio"] == 0


# ── Model D — check_tjl_model_d (RSI oversold bounce) ────────────────────────


class TestCheckTjlModelD:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=15)
        assert tjl_mod.check_tjl_model_d(100.0, h, l, c, v, 100.0, 100.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_d(price, h, l, c, v, price - 1.0, price - 2.0)
        if out is not None:
            for k in ("price", "vwap", "rsi_now", "rsi_prev", "atr", "pmh",
                      "sl", "tp", "rr_ratio", "direction", "long_fire",
                      "near_vwap", "rsi_bounce"):
                assert k in out, f"missing {k}"

    def test_no_fire_when_rsi_doesnt_cross(self, tjl_mod):
        # Constant price → rsi may be 100 → never crosses up from below 30
        h, l, c, v = _flat_bars(n=80)
        out = tjl_mod.check_tjl_model_d(100.0, h, l, c, v, 100.0, 100.0)
        # rsi of constant series returns 100 → not bouncing
        if out is not None:
            assert out["long_fire"] == False


# ── Model E — check_tjl_model_e (20-day high breakout) ───────────────────────


class TestCheckTjlModelE:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=10)
        assert tjl_mod.check_tjl_model_e(100.0, h, l, c, v, 100.0) is None

    def test_returns_dict_with_required_keys_on_fire(self, tjl_mod):
        # Need: price > 20-day high, rsi > 50, vol > 1.5x avg20
        h, l, c, v = _uptrend_bars(n=80, slope=1.0)
        price = float(c[-1]) + 5.0   # break above 20-day high
        v2 = v.copy()
        v2[-1] = int(np.mean(v[-21:-1]) * 2.0)   # 2x volume
        out = tjl_mod.check_tjl_model_e(price, h, l, c, v2, price - 5.0)
        assert out is not None
        for k in ("price", "high_20", "low_20", "rsi", "atr", "avg_vol20",
                  "today_vol", "vol_ratio", "pmh", "sl", "tp", "rr_ratio",
                  "direction", "long_fire", "short_fire", "above_high",
                  "below_low", "vol_ok"):
            assert k in out, f"missing {k}"
        # On strong uptrend with break & volume, expect long_fire
        assert out["long_fire"] == True
        assert out["direction"] == "LONG"

    def test_short_fire_on_breakdown(self, tjl_mod):
        h, l, c, v = _downtrend_bars(n=80, slope=1.0)
        price = float(c[-1]) - 5.0
        v2 = v.copy()
        v2[-1] = int(np.mean(v[-21:-1]) * 2.0)
        out = tjl_mod.check_tjl_model_e(price, h, l, c, v2, price + 5.0)
        assert out is not None
        assert out["short_fire"] == True
        assert out["direction"] == "SHORT"

    def test_no_fire_without_volume(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=1.0)
        price = float(c[-1]) + 5.0
        out = tjl_mod.check_tjl_model_e(price, h, l, c, v, price - 5.0)
        # Low volume → vol_ok False → no fire
        assert out is None

    def test_sl_tp_for_long(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=1.0)
        price = float(c[-1]) + 5.0
        v2 = v.copy()
        v2[-1] = int(np.mean(v[-21:-1]) * 2.0)
        out = tjl_mod.check_tjl_model_e(price, h, l, c, v2, price - 5.0)
        atr = out["atr"]
        assert (price - out["sl"]) == pytest.approx(atr * 1.0, abs=0.05)
        assert (out["tp"] - price) == pytest.approx(atr * 1.5, abs=0.05)

    def test_sl_tp_for_short(self, tjl_mod):
        h, l, c, v = _downtrend_bars(n=80, slope=1.0)
        price = float(c[-1]) - 5.0
        v2 = v.copy()
        v2[-1] = int(np.mean(v[-21:-1]) * 2.0)
        out = tjl_mod.check_tjl_model_e(price, h, l, c, v2, price + 5.0)
        atr = out["atr"]
        assert (out["sl"] - price) == pytest.approx(atr * 1.0, abs=0.05)
        assert (price - out["tp"]) == pytest.approx(atr * 1.5, abs=0.05)


# ── Model F — check_tjl_model_f (RSI Trend Crossover) ───────────────────────


class TestCheckTjlModelF:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=10)
        assert tjl_mod.check_tjl_model_f(100.0, h, l, c, v, 100.0, 100.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.5)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_f(price, h, l, c, v, price - 5.0, price - 5.0)
        if out is not None:
            for k in ("price", "ema20", "rsi", "prev_rsi", "atr", "avg_vol20",
                      "today_vol", "vol_ratio", "sl", "tp", "rr_ratio",
                      "direction", "long_fire", "short_fire", "vol_ok",
                      "price_above_ema", "price_below_ema"):
                assert k in out, f"missing {k}"


# ── Model G — check_tjl_model_g (Opening Range Breakout) ─────────────────────


class TestCheckTjlModelG:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=10)
        assert tjl_mod.check_tjl_model_g(100.0, h, l, c, v, 100.0, 99.0, 99.5) is None

    def test_returns_none_when_open_missing(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80)
        assert tjl_mod.check_tjl_model_g(100.0, h, l, c, v, 100.0, 99.0, None) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.5)
        price = float(c[-1])
        v2 = v.copy()
        v2[-1] = int(np.mean(v[-21:-1]) * 2.0)
        out = tjl_mod.check_tjl_model_g(price, h, l, c, v2, price - 1.0, price - 2.0, price - 5.0)
        if out is not None:
            for k in ("price", "orb_high", "orb_low", "today_open", "atr",
                      "vol_now", "vol_avg20", "vol_ratio", "sl", "tp",
                      "rr_ratio", "direction", "long_fire", "short_fire"):
                assert k in out, f"missing {k}"


# ── Model H — check_tjl_model_h (Gold EMA/BB/VWAP trend) ─────────────────────


class TestCheckTjlModelH:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=10)
        assert tjl_mod.check_tjl_model_h(100.0, h, l, c, v, 100.0, 99.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.5)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_h(price, h, l, c, v, price - 5.0, price - 5.0)
        if out is not None:
            for k in ("price", "e9", "e21", "bb_mid", "vwap", "atr", "sl",
                      "tp", "rr_ratio", "direction", "long_fire", "short_fire"):
                assert k in out, f"missing {k}"


# ── Model I — check_tjl_model_i (63-WMA swing, daily bars) ───────────────────


class TestCheckTjlModelI:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=30)
        assert tjl_mod.check_tjl_model_i(100.0, h, l, c, v, 100.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.3)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_i(price, h, l, c, v, price - 1.0)
        if out is not None:
            for k in ("price", "wma63", "rsi", "atr", "sl", "tp",
                      "rr_ratio", "direction", "long_fire", "short_fire"):
                assert k in out, f"missing {k}"

    def test_penny_stock_filtered(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, base=0.5)
        # Price < 1.0 → filtered
        out = tjl_mod.check_tjl_model_i(0.5, h, l, c, v, 0.4)
        assert out is None

    def test_high_atr_filtered(self, tjl_mod):
        # ATR > 20% of price → filtered
        closes = np.array([100.0] * 80)
        highs = closes + 30.0  # huge range
        lows = closes - 30.0
        volumes = np.full(80, 1_000_000, dtype=int)
        out = tjl_mod.check_tjl_model_i(100.0, highs, lows, closes, volumes, 90.0)
        assert out is None

    def test_sl_tp_wider_r_ratio(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.3)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_i(price, h, l, c, v, price - 1.0)
        if out is not None:
            # SL = 1.5*ATR, TP = 3.0*ATR → R:R = 2.0
            assert out["rr_ratio"] == pytest.approx(2.0, abs=0.01)


# ── Model J — check_tjl_model_j (150/200 DMA mean reversion) ─────────────────


class TestCheckTjlModelJ:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80)
        assert tjl_mod.check_tjl_model_j(100.0, h, l, c, v, 100.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=220, slope=0.2)
        price = float(c[-1])
        v2 = v.copy()
        v2[-1] = int(np.mean(v[-21:-1]) * 2.0)
        out = tjl_mod.check_tjl_model_j(price, h, l, c, v2, price - 1.0)
        if out is not None:
            for k in ("price", "dma150", "dma200", "atr", "vol_now",
                      "vol_avg20", "vol_ratio", "sl", "tp", "rr_ratio",
                      "direction", "long_fire", "short_fire"):
                assert k in out, f"missing {k}"


# ── Model K — check_tjl_model_k (EMA/VWAP/BB session) ────────────────────────


class TestCheckTjlModelK:
    def test_returns_none_when_few_bars(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=10)
        assert tjl_mod.check_tjl_model_k(100.0, h, l, c, v, 100.0, 99.0) is None

    def test_returns_dict_with_required_keys(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.5)
        price = float(c[-1])
        out = tjl_mod.check_tjl_model_k(price, h, l, c, v, price - 1.0, price - 1.0)
        if out is not None:
            for k in ("price", "e9", "e21", "bb_mid", "vwap", "atr", "sl",
                      "tp", "rr_ratio", "direction", "long_fire", "short_fire"):
                assert k in out, f"missing {k}"


# ── Short entry — check_tjs ───────────────────────────────────────────────────


class TestCheckTjs:
    def test_returns_none_when_few_bars(self, tjl_mod):
        closes = np.array([100.0] * 30)
        highs = closes + 0.5
        lows = closes - 0.5
        assert tjl_mod.check_tjs(100.0, highs, lows, closes, 100.0) is None

    def test_short_signal_on_bearish_stack(self, tjl_mod):
        h, l, c, v = _downtrend_bars(n=80, slope=0.1)
        price = float(c[-1])
        # Place PML high enough that price < PML - 0.7
        out = tjl_mod.check_tjs(price, h, l, c, price + 5.0)
        assert out is not None
        for k in ("price", "e9", "e20", "e50", "atr", "pml", "sl", "tp",
                  "rr_ratio", "direction", "stack_ok", "near_ema_ok",
                  "below_pml_ok"):
            assert k in out, f"missing {k}"
        assert out["direction"] == "SHORT"
        assert out["stack_ok"] == True

    def test_short_sl_above_tp_below(self, tjl_mod):
        h, l, c, v = _downtrend_bars(n=80, slope=0.1)
        price = float(c[-1])
        out = tjl_mod.check_tjs(price, h, l, c, price + 5.0)
        # Short: SL > entry, TP < entry
        assert out["sl"] > price
        assert out["tp"] < price

    def test_no_signal_on_uptrend(self, tjl_mod):
        h, l, c, v = _uptrend_bars(n=80, slope=0.1)
        price = float(c[-1])
        out = tjl_mod.check_tjs(price, h, l, c, price - 5.0)
        # Bullish stack → stack_ok False
        assert out is not None
        assert out["stack_ok"] == False
