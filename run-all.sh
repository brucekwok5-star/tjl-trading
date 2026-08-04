#!/bin/bash
# run-all.sh — Run all 3 TJL scanners and produce a side-by-side comparison report.
#
# Usage:
#   ./run-all.sh                          # 3 default tickers, no notify
#   ./run-all.sh "AAPL,NVDA,TSLA,AMD,MU"  # custom watchlist
#   ./run-all.sh AAPL,TSLA --notify       # with Telegram delivery
#
# Output: prints unified comparison to stdout. Each scanner still writes its
# own JSON to ~/, prefixed by source.

set -e

# Args
TICKERS="${1:-AAPL,NVDA,TSLA}"
NOTIFY_FLAG=""
for arg in "$@"; do
  if [ "$arg" = "--notify" ]; then
    NOTIFY_FLAG="--notify"
  fi
done

PY="/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python"
SCRIPTS_DIR="/Users/jaydensmac/.openclaw/workspace"

# Load ITICK_TOKEN from .env
export ITICK_TOKEN=$(grep '^ITICK_TOKEN=' ~/.hermes/.env 2>/dev/null | cut -d= -f2- | tr -d '"' || echo "")
if [ -z "$ITICK_TOKEN" ]; then
  echo "⚠ ITICK_TOKEN not set — iTick + TV PMH fallback will fail"
fi

export US_TICKERS="$TICKERS"

echo "================================================================"
echo " TJL SCANNER COMPARISON — $TICKERS"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"
echo ""

run_one() {
  local label="$1"; local script="$2"; local extra="${3:-}"
  echo "─── $label ───"
  if [ -n "$extra" ] && [ "$extra" != " " ]; then
    "$PY" "$SCRIPTS_DIR/$script" $extra $NOTIFY_FLAG 2>&1 | tail -20
  else
    "$PY" "$SCRIPTS_DIR/$script" $NOTIFY_FLAG 2>&1 | tail -20
  fi
  echo ""
}

# yfinance (fast)
run_one "yfinance (EMA stack, 15-min delay)" "tjl_live_us.py"

# iTick (free tier — may take ~1 min due to rate limits)
echo "─── iTick (EMA stack, real-time REST) ───"
echo "(may take ~1 min due to free-tier rate limit of 5 calls/min)"
"$PY" "$SCRIPTS_DIR/tjl_live_us_itick.py" $NOTIFY_FLAG 2>&1 | tail -20
echo ""

# TV-MCP (slowest — ~25s per ticker)
echo "─── TradingView MCP (Trend Join Long — HumbledTrader) ───"
echo "(~25s per ticker due to chart-switching)"
"$PY" "$SCRIPTS_DIR/tjl_live_us_tv.py" --tickers "$TICKERS" $NOTIFY_FLAG 2>&1 | tail -25
echo ""

echo "================================================================"
echo " All outputs:"
echo "================================================================"
ls -lt ~/tjl_live_us_$(date +%Y-%m-%d).json ~/tjl_live_us_itick_$(date +%Y-%m-%d).json ~/tjl_watchlist_$(date +%Y-%m-%d)_*.json 2>/dev/null | head -10

echo ""
echo "================================================================"
echo " Side-by-side comparison:"
echo "================================================================"
"$PY" /Users/jaydensmac/.openclaw/workspace/compare_results.py 2>&1 || echo "(compare_results.py failed — check JSON files manually)"