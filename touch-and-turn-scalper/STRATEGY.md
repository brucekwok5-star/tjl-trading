# Touch and Turn Scalper — Strategy Document

**YouTube Source:** Carl (20+yr trader) — [video](https://www.youtube.com/watch?v=BifyQ6ppdLU)
**TradingView Indicator:** [1-Min Touch & Turn Scalper (wZ7aK7dY)](https://www.tradingview.com/script/wZ7aK7dY-1-Min-Touch-Turn-Scalper/)
**Date Coded:** 2026-08-17
**Assets:** US equities, NQ/MNQ futures, ES/MES indices

---

## Core Thesis

Institutional traders engineer **liquidity candles** in the first 15 minutes of the New York session
(09:30–09:45 ET) — aggressive directional candles that trap retail traders via stop-loss runs.
The price almost always **touches the edge of the opening range once more** before reversing.
That touch-and-turn is the entry.

The TradingView indicator adds a critical filter: wait for **volume-delta confirmation** that buyers
or sellers are actually absorbing the move at the level before entering — not just touching.

---

## YouTube Strategy vs TradingView Indicator — Key Differences

| Feature | YouTube (Carl) | TradingView Indicator (wZ7aK7dY) | Delta |
|---|---|---|---|
| Opening range | 15-min candle | Same (09:30–09:45 NY) | Same |
| Fib levels | High→low, extended right | Same | Same |
| TP levels | 38.2% / 61.8% | Same | Same |
| Liquidity check | ATR×25% fixed | ATR×25% or 30% (adjustable) | TV has setting |
| **Entry trigger** | **Price touches level** | **Delta-confirmed candle close** | **KEY UPGRADE** |
| Delta confirmation | None | 2/3/5 bars adjustable | TV adds filter |
| Win rate (NQ backtest) | ~70% (theoretical) | **High-50s/low-60s** (54-day real backtest) | More realistic |
| Timeframe | 15-min then 1-min | 1-min only (self-contained) | TV simpler |
| R:R ratio | 2:1 fixed | 2:1 (adjustable) | TV flexible |
| Dashboard | None | On-chart: ATR, setup state, win rate | TV has UI |
| Market tested | Stocks | NQ, MNQ, ES, MES + stocks | TV broader |

### The Critical Improvement: Delta Confirmation

The YouTube strategy enters **on the touch** — price reaches the range edge, you enter.
Problem: price frequently touches and immediately continues through the level (Scenario 4 loss).

The TradingView indicator's key improvement is requiring a **delta-confirmed candle close** before
triggering entry:
- Long setup: wait for a 1-min candle that closes with **positive delta** (buyers winning) at the low
- Short setup: wait for a 1-min candle that closes with **negative delta** (sellers winning) at the high
- This confirms real order-flow absorption, not just a price graze

**54-day NQ backtest result:** delta-confirmation lifted win rate from **high-30s → high-50s/low-60s**
vs the plain instant-touch entry. More realistic than Carl's ~70% claim.

---

## The 3 Steps

### Step 1 — Fibonaccify the Opening Range

1. Open the asset on a **15-minute chart**.
2. Wait for the **first 15-min candle (09:30–09:45 ET) to fully close**.
3. Draw **Fibonacci retracement** from:
   - **High** = top of the opening candle (1.0)
   - **Low** = bottom of the opening candle (0.0)
4. **Extend the Fib levels rightward** into the session.
5. Note **38.2%** and **61.8%** — these are your take-profit targets.

### Step 2 — Confirm the Liquidity Candle

1. Switch to the **daily chart**, add **ATR (14)** — default settings.
2. Read the ATR value.
3. Calculate the **validity threshold**: `ATR × OR_pct`
   - Default `OR_pct = 0.25`; TV indicator also allows `0.30` (stricter).
4. Measure the **opening candle range**: `High − Low`.
5. **If candle range ≥ ATR × OR_pct → valid liquidity candle. Proceed.**
   - If not, skip the day. Quiet choppy mornings are excluded.

### Step 3 — Set the Perfect Trade

1. Switch to **1-minute chart** (TV indicator handles this internally).
2. **Direction**: always opposite to the liquidity candle.
   - Candle is **RED** → place **long limit order at range low**.
   - Candle is **GREEN** → place **short limit order at range high**.
3. **Entry trigger** (with delta confirmation, recommended):
   - Wait for price to **touch** the limit order level.
   - Then wait for the **next 1–3 1-min candles** where delta confirms the turn.
   - Enter when the delta-confirmed candle **closes**.
4. **Take-profit (TP)**: 38.2% Fibonacci level.
5. **Stop-loss (SL)**: `|TP − entry| / 2` → exactly **2:1 reward-to-risk**.
6. **Entry window**: first 90 minutes of NY session only (09:30–11:00 ET).
7. **Max 1 trade per day.**

---

## The 4 Scenarios (Why It Wins ~60–70%)

Every day after the open, price can only do 4 things:

| # | Scenario | What Happens | Outcome |
|---|---|---|---|
| 1 | Push through range | Price usually retraces to TP before breaking through | **WIN** |
| 2 | Stay in range | Price bounces within range → crosses TP | **WIN** |
| 3 | Full reversal | Price crosses TP on the reversal | **WIN** |
| 4 | Break through on first touch | Price never turns — immediate range break | **LOSS** |

Only Scenario 4 is a loss. Delta confirmation significantly reduces Scenario 4 losses by
waiting to confirm the turn before entering.

---

## Settings Reference

| Parameter | YouTube | TV Indicator | Recommended |
|---|---|---|---|
| OR % of Daily ATR | 25% fixed | 25% or 30% | 25% for more trades, 30% for quality |
| Delta Confirmation Window | N/A | 2/3/5 bars | **2–3 bars**; 5+ = chasing |
| Use Delta-Confirmation Entry | OFF | Toggle | **ON (recommended)** |
| TP Level | 38.2% | 38.2% or 61.8% | 38.2% default |
| R:R Ratio | 2:1 fixed | 2:1 (adjustable) | 2:1 |
| ATR Length | 14 default | 14 (adjustable) | 14 |
| Session Window | 90 min | 90 min NY | unchanged |
| Entry trigger | Instant touch | Delta-confirmed close | Delta-confirmed |

---

## Backtest Notes

- Carl's ~70% win rate is theoretical/structural (only 1 of 4 scenarios is a loss).
- TradingView 54-day NQ backtest: **high-50s/low-60s** win rate with delta confirmation.
- The gap between Carl's claim and the backtest reflects real-world slippage, partial fills,
  and the fact that not every Scenario 4 is identifiable before entry.
- **Superior approach:** Use Carl's structural framework + TV's delta filter + your own
  forward-testing on sim.

---

## Limitations

- Historic results ≠ future guarantee. Evaluate regularly.
- Works better on some assets than others — must evaluate per symbol.
- Delta requires tick/volume data; free feeds (yfinance) provide approximations only.
  Full delta confirmation requires the TradingView indicator with real tick data.
- The TradingView indicator is a **PROTECTED SOURCE SCRIPT** (paid, Pine Script source hidden).
- Best performance observed on **NQ futures** (liquid, volatile open).

---

## File Map

```
touch-and-turn-scalper/
├── STRATEGY.md           ← this file (workspace reference)
└── (skill lives in ~/.hermes/skills/trading/touch-and-turn-scalper/)

~/.hermes/skills/trading/touch-and-turn-scalper/
├── SKILL.md              ← Hermes skill (cron + scanner usage)
└── scripts/
    └── scan_touch_and_turn.py  ← scanner
```
