"""Tests for futu_alpha_scoring.py — verify_old_predictions, parse_signals, score math, _re_rank.

These cover the production path: yfinance→Futu swap, start/end date fix, rate-limit backoff,
main() integration of verify_old_predictions(), parse_signals extraction, _re_rank ordering.
"""
import sys, os, json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import pandas as pd
import futu_alpha_scoring as fas


# --- parse_signals: dict-of-code->info structure -----------------------------

def test_parse_signals_extracts_bullish_from_hk_post():
    """Real Futu posts have a short author line then a content line. Function needs both:
    author (2-10 chars, no bull/bear kw) + content (≥10 chars, contains BULL/BEAR kw)."""
    raw = {
        "00700": {
            "name": "騰訊控股",
            "posts": [{
                "text": "tester\n看好 $騰訊控股 (00700.HK)$ 今天會升",
                "time": "2026-08-15",
            }]
        }
    }
    sigs = fas.parse_signals(raw)
    assert len(sigs) >= 1, f"expected ≥1 signal, got {len(sigs)}"
    s = sigs[0]
    assert s["code"] == "00700", f"expected code 00700, got {s['code']}"
    assert s["direction"] == "bullish"
    assert s["user"] == "tester"


def test_parse_signals_handles_empty_input():
    """Empty data structures should return empty list, not crash."""
    assert fas.parse_signals({}) == []
    assert fas.parse_signals({"00700": {"name": "x", "posts": []}}) == []


# --- _re_rank (production ordering) -----------------------------------------

def _make_pred(user, stock, direction, accuracy, created="2026-08-14T10:00:00"):
    return {
        "user": user, "stock": stock, "direction": direction,
        "accuracy": accuracy, "verified": True, "created": created,
        "specificity": 0.5, "confidence": 0.5,
    }


def test_re_rank_filters_below_min_preds():
    """Users with fewer than min_preds verified predictions should be excluded."""
    lb = {
        "predictions": [
            _make_pred("u1", "00700", "bullish", 0.7),
            # u2 has only 1 verified prediction — should be filtered at min_preds=2
            _make_pred("u2", "00992", "bearish", 0.7),
            _make_pred("u1", "00992", "bullish", 0.7),
        ],
        "ranked": [],
    }
    fas._re_rank(lb, min_preds=2)
    users = [r["user"] for r in lb["ranked"]]
    assert "u1" in users, "u1 has 2 verified, should be in"
    assert "u2" not in users, "u2 has 1 verified, should be filtered out"


def test_re_rank_orders_consistent_bullish_above_mixed():
    """Higher accuracy + same-direction bonus → higher final_score → first in ranked list."""
    lb = {
        "predictions": [
            _make_pred("consistent_bull", "00700", "bullish", 0.7),
            _make_pred("consistent_bull", "00992", "bullish", 0.7),
            _make_pred("mixed", "00700", "bullish", 0.7),
            _make_pred("mixed", "00992", "bearish", 0.7),
        ],
        "ranked": [],
    }
    fas._re_rank(lb, min_preds=2)
    assert lb["ranked"][0]["user"] == "consistent_bull", \
        f"consistent_bull should rank first (same-direction bonus), got {lb['ranked'][0]['user']}"


def test_re_rank_skips_unverified_predictions():
    """Predictions with accuracy=None (unverified) should not contribute to ranking."""
    lb = {
        "predictions": [
            _make_pred("u1", "00700", "bullish", 0.7),
            _make_pred("u1", "00992", "bullish", 0.7),
            # u2's preds have accuracy=None — should be filtered
            {"user": "u2", "stock": "00700", "direction": "bullish",
             "accuracy": None, "verified": False, "created": "2026-08-14T10:00:00",
             "specificity": 0.5, "confidence": 0.5},
            {"user": "u2", "stock": "00992", "direction": "bullish",
             "accuracy": None, "verified": False, "created": "2026-08-14T10:00:00",
             "specificity": 0.5, "confidence": 0.5},
        ],
        "ranked": [],
    }
    fas._re_rank(lb, min_preds=2)
    users = [r["user"] for r in lb["ranked"]]
    assert "u1" in users
    assert "u2" not in users, "u2's preds are accuracy=None, should be filtered"


# --- verify_old_predictions (the bug-fix surface) ----------------------------

def _make_kline_df(start_date: date, n_days: int) -> pd.DataFrame:
    """Build a synthetic daily K-line DataFrame matching Futu's schema."""
    dates = [start_date + timedelta(days=i) for i in range(n_days)]
    prices = [100.0 + i for i in range(n_days)]  # monotonic up
    return pd.DataFrame({
        "time_key": [d.strftime("%Y-%m-%d") for d in dates],
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": [1000] * n_days, "turnover": [100000] * n_days,
    })


def test_verify_old_predictions_marks_unverified_with_fake_futu(tmp_path):
    """When Futu returns a valid DataFrame, unverified predictions should be marked verified
    with correct accuracy scores."""
    test_lb = tmp_path / "leaderboard.json"
    test_lb.write_text(json.dumps({
        "predictions": [
            {"user": "u1", "stock": "00700", "direction": "bullish",
             "text": "x", "created": "2026-08-13T10:00:00",  # 2 days old
             "accuracy": None, "verified": False},
        ],
        "ranked": [],
    }))
    fake_df = _make_kline_df(date(2026, 8, 13), 5)
    fake_futu = MagicMock()
    fake_futu.AuType = MagicMock()
    fake_futu.AuType.QFQ = "QFQ"
    fake_ctx = MagicMock()
    fake_ctx.request_history_kline.return_value = (0, fake_df, None)
    fake_futu.quote.open_quote_context.OpenQuoteContext = MagicMock(return_value=fake_ctx)

    with patch.object(fas, "LB_PATH", test_lb), \
         patch.dict(sys.modules, {"futu": fake_futu,
                                  "futu.quote.open_quote_context": fake_futu.quote.open_quote_context}):
        n = fas.verify_old_predictions(min_age_days=1, max_age_days=10)
    assert n == 1, f"expected 1 verified, got {n}"
    saved = json.loads(test_lb.read_text())
    p = saved["predictions"][0]
    assert p["verified"] is True
    assert p["accuracy"] == 1.0, f"bullish + price went up 4 days → expected 1.0, got {p['accuracy']}"
    assert "entry_price" in p and "exit_price" in p


def test_verify_old_predictions_skips_too_young(tmp_path):
    """Predictions created today (age 0) should be skipped — too young to verify."""
    test_lb = tmp_path / "leaderboard.json"
    today_str = date.today().isoformat()
    test_lb.write_text(json.dumps({
        "predictions": [
            {"user": "u1", "stock": "00700", "direction": "bullish",
             "text": "x", "created": f"{today_str}T10:00:00",
             "accuracy": None, "verified": False},
        ],
        "ranked": [],
    }))
    fake_ctx = MagicMock()
    fake_futu = MagicMock()
    fake_futu.AuType = MagicMock()
    fake_futu.AuType.QFQ = "QFQ"
    fake_futu.quote.open_quote_context.OpenQuoteContext = MagicMock(return_value=fake_ctx)

    with patch.object(fas, "LB_PATH", test_lb), \
         patch.dict(sys.modules, {"futu": fake_futu,
                                  "futu.quote.open_quote_context": fake_futu.quote.open_quote_context}):
        n = fas.verify_old_predictions(min_age_days=1, max_age_days=10)
    assert n == 0, f"age-0 prediction should be skipped, got {n} verified"
    fake_ctx.request_history_kline.assert_not_called()


def test_verify_old_predictions_handles_futu_string_error(tmp_path):
    """When Futu returns ret!=0 with a string error message, should not crash."""
    test_lb = tmp_path / "leaderboard.json"
    test_lb.write_text(json.dumps({
        "predictions": [
            {"user": "u1", "stock": "00700", "direction": "bullish",
             "text": "x", "created": "2026-08-10T10:00:00",
             "accuracy": None, "verified": False},
        ],
        "ranked": [],
    }))
    fake_ctx = MagicMock()
    fake_ctx.request_history_kline.return_value = (-1, "too frequent request", None)
    fake_futu = MagicMock()
    fake_futu.AuType = MagicMock()
    fake_futu.AuType.QFQ = "QFQ"
    fake_futu.quote.open_quote_context.OpenQuoteContext = MagicMock(return_value=fake_ctx)

    with patch.object(fas, "LB_PATH", test_lb), \
         patch.dict(sys.modules, {"futu": fake_futu,
                                  "futu.quote.open_quote_context": fake_futu.quote.open_quote_context}):
        n = fas.verify_old_predictions(min_age_days=1, max_age_days=10)
    assert n == 0, f"Futu error should not verify anything, got {n}"


def test_verify_old_predictions_passes_start_end_to_futu(tmp_path):
    """Regression test: must pass explicit start/end dates to Futu so it returns recent data,
    not the oldest max_count days."""
    test_lb = tmp_path / "leaderboard.json"
    test_lb.write_text(json.dumps({
        "predictions": [
            {"user": "u1", "stock": "00700", "direction": "bullish",
             "text": "x", "created": "2026-08-13T10:00:00",
             "accuracy": None, "verified": False},
        ],
        "ranked": [],
    }))
    fake_df = _make_kline_df(date(2026, 8, 13), 5)
    fake_ctx = MagicMock()
    fake_ctx.request_history_kline.return_value = (0, fake_df, None)
    fake_futu = MagicMock()
    fake_futu.AuType = MagicMock()
    fake_futu.AuType.QFQ = "QFQ"
    fake_futu.quote.open_quote_context.OpenQuoteContext = MagicMock(return_value=fake_ctx)

    with patch.object(fas, "LB_PATH", test_lb), \
         patch.dict(sys.modules, {"futu": fake_futu,
                                  "futu.quote.open_quote_context": fake_futu.quote.open_quote_context}):
        fas.verify_old_predictions(min_age_days=1, max_age_days=10)

    # Verify start/end were passed (this is the bug fix)
    call_args = fake_ctx.request_history_kline.call_args
    assert "start" in call_args.kwargs, "regression: must pass start= kwarg to Futu"
    assert "end" in call_args.kwargs, "regression: must pass end= kwarg to Futu"
    assert call_args.kwargs["end"] == date.today().strftime("%Y-%m-%d")


# --- main() integration ------------------------------------------------------

def test_main_with_existing_leaderboard_posts_to_discord(tmp_path):
    """When leaderboard has ranked users and no new signals, main() should still post
    the existing leaderboard to Discord."""
    test_lb = tmp_path / "leaderboard.json"
    test_lb.write_text(json.dumps({
        "predictions": [
            {"user": "u1", "stock": "00700", "direction": "bullish",
             "accuracy": 0.7, "verified": True, "created": "2026-08-14T10:00:00",
             "specificity": 0.5, "confidence": 0.5},
            {"user": "u1", "stock": "00992", "direction": "bullish",
             "accuracy": 0.7, "verified": True, "created": "2026-08-14T10:00:00",
             "specificity": 0.5, "confidence": 0.5},
        ],
        "ranked": [{"user": "u1", "avg_accuracy": 0.7, "n_predictions": 2,
                     "final_score": 0.6, "stocks": ["00700", "00992"], "n_days": 1,
                     "all_same_direction": True}],
    }))
    fake_ctx = MagicMock()
    fake_futu = MagicMock()
    fake_futu.AuType = MagicMock()
    fake_futu.AuType.QFQ = "QFQ"
    fake_futu.quote.open_quote_context.OpenQuoteContext = MagicMock(return_value=fake_ctx)

    with patch.object(fas, "LB_PATH", test_lb), \
         patch.dict(sys.modules, {"futu": fake_futu,
                                  "futu.quote.open_quote_context": fake_futu.quote.open_quote_context}), \
         patch.object(fas, "post_to_discord", return_value="204") as mock_post, \
         patch.object(fas, "verify_old_predictions", return_value=0):
        ranked = fas.main(scraped_data={}, verify=True)
    assert ranked is not None and len(ranked) == 1, f"expected 1 ranked, got {ranked}"
    mock_post.assert_called_once()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
