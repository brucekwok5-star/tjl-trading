# TJL HK Backtest Report — Empirical Results

**Date:** 2026-08-15
**Universe:** 8 HSI mega-caps (00005, 00288, 00700, 00823, 00941, 01109, 02899, 09618)
**Bars:** Daily, 252 trading days (252d hold-10) + 60 days (60d hold-5 for sanity)
**Data source:** Futu OpenD historical K-lines
**Total trades (closed):** 3,641 (252d) + 849 (60d) = 4,490

## Verdict

**Only 3 of 18 models are profitable.** The rest lose money.

## Models that PASS (PF > 1.0, positive expectancy)

| Model | N   | WR%   | PF   | Expect%/trade | Decision       |
|-------|-----|-------|------|---------------|----------------|
| **X** | 149 | 43.6% | 1.42 | +0.570%       | ✅ KEEP — best PF |
| **R** | 634 | 36.6% | 1.17 | +0.195%       | ✅ KEEP — most trades, robust |
| **I** |  86 | 37.2% | 1.03 | +0.064%       | ⚠️ KEEP w/ 10-bar hold only; loses on 5-bar |

## Models that FAIL (negative expectancy, kill list)

| Model | N   | WR%   | PF   | Expect%/trade | Notes              |
|-------|-----|-------|------|---------------|--------------------|
| V     | 890 | 12.6% | 0.29 | -2.53%        | **WORST** — high N, kill immediately |
| L     | 324 | 26.2% | 0.61 | -1.04%        | Kill |
| S     | 583 | 28.0% | 0.73 | -0.82%        | Kill |
| Q     | 135 | 27.4% | 0.51 | -1.61%        | Kill |
| P     |  16 |  6.2% | 0.19 | -2.37%        | Kill (also rare)   |
| G     | 166 | 36.7% | 0.79 | -0.39%        | Kill (WR ok but loses) |
| E     |  70 | 34.3% | 0.71 | -0.56%        | Kill |
| N     | 161 | 27.3% | 0.90 | -0.21%        | Kill (marginal)    |
| O     |  33 | 84.8% | 0.16 | -0.57%        | Kill (high WR but tiny wins, big losses) |
| U     | 236 | 31.8% | 0.86 | -0.27%        | Kill |
| F     |  87 | 39.1% | 0.97 | -0.049%       | Borderline — disable for now |
| H     |  33 | 39.4% | 0.97 | -0.043%       | Borderline (small N) |
| K     |  33 | 39.4% | 0.97 | -0.043%       | Borderline (small N, mirror of H) |

## Caveats

1. **Universe is mega-cap only** (HSI top 8). Mid-caps and small-caps may behave very differently.
2. **60d hold-5 results differ from 252d hold-10**: model I wins on 10-bar hold but loses on 5-bar; R remains profitable in both.
3. **Survivorship in OPEN trades**: 1,174 trades are still OPEN (couldn't close within 252d window). Including these would change WR for some models.
4. **No slippage / commission** in numbers. Realistic fill is 0.05–0.15% worse than backtest.
5. **No regime filter**: scanner ran in all market conditions. Adding HSI 200DMA filter may help.

## Recommended Action

1. **Update `tjl_live_futu.py` to fire only Models X, R, I** — drop the rest from dispatch list.
2. **Add Model I to conditional dispatch**: only fire when recent ATR suggests ≥10-bar swing room (currently scanner uses default 5-bar hold, which loses for I).
3. **Add slippage model** in backtest: subtract 0.10% from each TP, add 0.05% to each SL, see if X/R/I still pass.
4. **Track live results in `tjl_model_tracker.py`** with same DROP criteria (WR<30% OR PF≤1.0 in rolling last 20 trades).

## Methodology Notes

- TP/SL hit detection uses intra-bar hi/lo (not just close), so the 563% "wins" I initially saw were a parsing bug (column offset) — real pct range is -12.20% to +17.66% as expected for 1.5–3× ATR setups.
- 252-day × 18-model × 8-stock backtest takes ~15+ minutes to complete. 60-day × 18-model × 8-stock takes ~5+ minutes. Consider running as overnight cron.
- PYTHONPATH must be unset before invoking `/usr/bin/python3 tjl_backtest.py` (otherwise 3.11 venv shadows system Python).
