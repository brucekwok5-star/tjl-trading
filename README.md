# TJL US Scanner

Trend Join Long (TJL) live scanner for US equities. Three scanner implementations
plus a unified test suite.

## Scanners

| Script | Strategy | Data Source | Latency |
|---|---|---|---|
| `tjl_live_us.py` | EMA stack + pullback (legacy) | yfinance | 15-min delay |
| `tjl_live_us_itick.py` | EMA stack + pullback (legacy) | iTick REST | real-time |
| `tjl_live_us_tv.py` | SMA200 + breakout (HumbledTrader) | TradingView MCP | real-time |

## Tools

- `run-all.sh` — runs all 3 scanners, prints comparison
- `compare_results.py` — side-by-side report from latest JSON outputs

## Skill

The `skill/` directory contains the Hermes skill SKILL.md and references
that teach the agent how to invoke, modify, and interpret the scanners.

## Tests

The `tests/` directory contains a hermes-verify suite (53 checks across all
3 scanners + compare-results). Run with:

```bash
~/.hermes/hermes-agent/venv/bin/python tests/run_all.py
```

## Quick start

```bash
# One-shot scan (3 default tickers)
./run-all.sh

# Custom watchlist + Telegram delivery
./run-all.sh "AAPL,NVDA,TSLA" --notify
```

## Prerequisites

- Python 3.11+ with `yfinance`, `pandas`, `numpy`, `requests`
- (Optional) iTick API token — set `ITICK_TOKEN` in `~/.hermes/.env`
- (Optional) TradingView Desktop + MCP for the TV-MCP variant
- (Optional) Telegram bot for `--notify` delivery
