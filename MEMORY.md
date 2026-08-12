# MEMORY.md - Long-Term Memory

## Accounts
- **Futu**: acct `90130881`, password in Mac Keychain (futunn.com)

## Infrastructure
- Mac mini (Darwin 25.3.0, arm64)
- OpenClaw workspace: `/Users/jaydensmac/.openclaw/workspace`
- Skills: `skills/bkskills/` (custom) + `plugin-skills/` (built-in)
- GitHub backup: `https://github.com/brucekwok5-star/openclaw-config`

## Skills (Custom)
- `futu-discussion-hunter` — scrape Futu stock discussion boards for predictive users
- `stock-trading-v3-hk-final` / `stock-trading-v3-us-final` — advanced stock analysis
- `stock-market-movers`, `stock-pnl-calculator`, `stock-quick-check`
- `calendar-check`, `calendar-checker`, `gmail-check`, `eclass-check`
- `school-timetable`, `homework-reminder`, `check-bus`, `whatsapp-reminder`

## Preferences
- Keep secrets out of GitHub (redacted before push)
- Prefer keychain for credentials storage

## Stock Scan Preferences
- **TJL scan codes**: When user provides 5-digit Futu-format HK codes (e.g. 07709, 02513), always convert to standard format by stripping leading zeros and appending `.HK` (e.g. 7709.HK, 2513.HK) before running scans. Do this automatically — user confirmed "always do that".
- **TJL scan posts**: Always include backtest info (Trades, WR%, NetPnL per ticker) when posting TJL signals to Discord or any other channel — user requested this on 2026-07-31.

## Current Projects
- Backtest program (in progress - details TBD)