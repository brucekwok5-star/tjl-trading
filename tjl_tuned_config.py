"""
Tuned TJL HK Model Parameters — post grid-search 2026-08-07
============================================================
Results from tjl_tuning.py on 8 HSI mega-caps, 246 bars (~86 trading days).
Score = WR * log(n+1) — balances win rate and signal count.

BEST CONFIG PER MODEL (updated 2026-08-07):
=========================================

Model H — Gold EMA/BB/VWAP          ★ WINNER
  n=19, W=16, L=3, WR=84.2%, avg=+1.79%, score=252.3
  SL = 1.25 × ATR   TP = 1.0 × ATR
  Note: tight TP (1.0× ATR = ~15 HKD on Tencent). 
        Very high conviction — only 19 trades but 84% WR.
  Live params: ATR(14), SL_mult=1.25, TP_mult=1.0

Model K — EMA/VWAP/BB Session Filter (same as H, independent tracking)
  n=19, W=16, L=3, WR=84.2%, avg=+1.79%, score=252.3
  SL = 1.25 × ATR   TP = 1.0 × ATR  ← IDENTICAL to H

Model F — RSI Trend Crossover        ★ RUNNER-UP (volume)
  n=37, W=15, L=22, WR=40.5%, avg=-0.01%, score=147.5
  LONG: RSI crosses UP through 60 + EMA9 > EMA20
  SHORT: RSI crosses DOWN through 45 + EMA9 < EMA20
  SL = 1.0 × ATR   TP = 1.5 × ATR
  Live params: RSI_long=60, RSI_short=45, ATR(14), SL_mult=1.0, TP_mult=1.5

Model A — Pullback (EMA9>EMA20>EMA50)
  n=4, W=2, L=2, WR=50.0%, avg=+1.04%, score=80.5
  near_pct=3.0% (wider than spec's 1.5%)
  SL = 1.5 × ATR   TP = 3.0 × ATR
  Note: very few signals in 86-day window. Use with low confidence.
  Live params: NEAR_EMA_PCT=0.030, ATR(14), SL_mult=1.5, TP_mult=3.0

Model I — 63-WMA Swing              ✗ AVOID
  n=25, W=7, L=18, WR=28.0%, avg=-1.19%, score=91.2
  near_pct=5.0% (wider = more signals but worse WR)
  SL = 1.5 × ATR   TP = 3.0 × ATR
  Do NOT use for live trading. Only use if WR can be improved.
  Live params: NEAR_PCT=0.05, ATR(14), SL_mult=1.5, TP_mult=3.0

Model B — Momentum (above SMA200)
  n=3, W=1, L=2, WR=33.3%, avg=+0.20%, score=46.2
  Too few signals in 86-day window.
  Live params: ATR(14), SL_mult=1.5, TP_mult=3.0

Model J — Follow Money SMA150/200
  n=4, W=1, L=3, WR=25.0%, avg=-0.82%, score=40.2
  Requires 150-bar warmup — very limited in short windows.
  Live params: NEAR_PCT=0.03, VOL_MULT=1.0, ATR(14), SL_mult=1.0, TP_mult=1.5

Models D, E, G — no configs passed min_signals=2 in 86-day window.
  These models need longer history or wider parameters.
  Recommended overrides for live use:
    D (RSI Bounce):    RSI_thresh=35 (was 30), near_vwap=3% (was 1.5%)
    E (20D Breakout):  VOL_MULT=1.0 (was 1.5), RSI_thresh=40 (was 50)
    G (ORB):           VOL_MULT=1.0 (was 1.2)

=========================================
RECOMMENDED LIVE CONFIG (models to activate):
=========================================
  PRIMARY:   Model H (SL=1.25× ATR, TP=1.0× ATR) — 84% WR, high conviction
  SECONDARY: Model F (RSI60_up/45_down, SL=1.0× ATR, TP=1.5× ATR) — 40% WR but 37 trades
  AVOID:     Model I (28% WR, -1.19% avg) — remove from OR logic
  LOW CONF:  Models A, B, J — too few signals in sample

WHAT TO TUNE NEXT:
  - Model D: try RSI_thresh=35, near_vwap=3%
  - Model E: try VOL_MULT=1.0, RSI_thresh=40
  - Model G: try VOL_MULT=1.0
  - Model I: try tight near_pct=1% to reduce false signals
  - All models: run on 1+ year of data when Futu history allows
"""
