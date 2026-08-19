# TJL Scanner Test Plan — 2026-08-19

## System Under Test

`tjl_ndx11_hkstyle.py` — HK-style TJL scanner, 11 Models A-K
`tjl_ndx11.py` — US-style TJL scanner v2, 11 Models A-K

## Test Scope

### 1. Unit Tests — Indicators
- `tests/test_indicators.py`
- RSI calc: golden cross (RSI crosses 50 from below) = long
- RSI calc: death cross (RSI crosses 50 from above) = short
- ATR calculation is positive
- EMA / SMA positive slope vs flat vs negative
- VWAP = typical price mean

### 2. Unit Tests — Models A-K
- `tests/test_models.py`
- Each model returns a dict with required keys: model, direction, sl, tp, rr
- Models A-K: no KeyError, no crash on valid data
- Models A/B/C/D/E/G/H/I/J/K: returns valid signal or None
- Models F: returns LONG when RSI crosses up, SHORT when crosses down
- Models G: KILL — returns None always (ORB broken)
- Models H/I: trend confirmation logic fires correctly
- Models J: DMA cross fires on golden/death cross
- Models K: SHORT only, BEARISH regime required

### 3. Data Fetch
- `tests/test_data_fetch.py`
- `batch_fetch()` returns data for all tickers
- `batch_fetch()` with bad ticker: skips gracefully, no crash
- Single-ticker fetch: returns DataFrame

### 4. Signal Construction
- `tests/test_signal.py`
- `make_signal()` adds sl/tp/rr correctly
- `make_signal()` with R:R 1.5 = SL at -40%, TP at +60%
- `make_signal()` with R:R 2.0 = SL at -33%, TP at +67%
- Signal sorted by WR descending

### 5. Regime Detection
- `tests/test_regime.py`
- SPY + QQQ both above SMA50 + SMA200 = BULLISH
- SPY + QQQ both below SMA50 + SMA200 = BEARISH
- One above/one below = NEUTRAL
- `can_long()` returns True in BULLISH
- `can_short()` returns True in BEARISH

### 6. End-to-End
- `tests/test_e2e.py`
- `run_scan()` on 5 real tickers returns signals
- `run_scan()` on empty list: no crash
- Regime correctly identified

### 7. Config / Security
- `tests/test_config.py`
- Webhook URL not logged
- Webhook URL not in error messages

### 8. Performance
- `tests/test_perf.py`
- `batch_fetch()` 10 tickers < 5s
- `batch_fetch()` 50 tickers < 20s
- Memory no leak across runs
- No regime API call duplication

### 9. Data Integrity
- `tests/test_data_integrity.py`
- Daily bars close != intraday price during market hours
- After market close: close matches

### 10. Partial Bar
- `tests/test_partial_bar.py`
- `get_safe_price()` returns prev_close during market hours
- `get_safe_price()` returns raw close after market close
- `is_market_hours()` correct

### 11. Enhancements (Phase 6)
- `tests/test_enhancements.py`
- `calculate_confidence()` returns 0-1 float
- `calculate_confidence()` penalizes regime mismatch
- `post_telegram()` graceful when no token

## Acceptance Criteria

- All 151 tests pass
- No test takes > 10s
- No regime cache pollution between tests
- No hardcoded API keys or webhooks in source

## Known Issues

- Model G (ORB): 21% WR, marked kill
- Model F: BEARISH-only, fires in BULLISH but is noise
- Yahoo Finance sandbox: only 5 HK tickers accessible (0700, 0388, 9618, 9988, 9961)
