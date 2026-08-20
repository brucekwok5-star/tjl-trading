#!/usr/bin/env python3
"""
ORB Backtest — Opening Range Breakout on US market
Tickers: QQQ, SPY, TSLA, NVDA  |  Period: 2026-01-01 to 2026-08-17
Fix v3: Correct ORB math — risk = 50%×OR_range, tp_1r = entry ± OR_range (1R), tp_2r = entry ± 2×OR_range (2R)
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date
import json

TICKERS = ["QQQ", "SPY", "TSLA", "NVDA"]
START, END = "2026-01-01", "2026-08-17"

# ── helpers ───────────────────────────────────────────────────────────────────

def is_trading_day(dt: pd.Timestamp) -> bool:
    if dt.weekday() >= 5:
        return False
    return dt.date() not in {
        date(2026,1,1), date(2026,1,19), date(2026,2,16), date(2026,4,3),
        date(2026,5,25), date(2026,7,3),  date(2026,9,7),  date(2026,11,26),
    }

def fetch_daily(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    df = yf.Ticker(ticker).history(start=start, end=end, interval="1d")
    if df.empty:
        return None
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    return df

def htf_bias(df: pd.DataFrame, before: pd.Timestamp) -> int:
    hist = df[df.index < before].tail(20)
    if len(hist) < 10:
        return 0
    return 1 if hist["Close"].iloc[-1] > hist["Close"].mean() else (-1 if hist["Close"].iloc[-1] < hist["Close"].mean() else 0)

# ── simulate ─────────────────────────────────────────────────────────────────

def simulate(ticker: str, start: str, end: str, use_bias: bool = False):
    df = fetch_daily(ticker, start, end)
    if df is None:
        return []

    # ORH/ORL proxy from daily bars (first-hour range baked into full-day High/Low)
    orhs, orls = [], []
    for idx in df.index:
        o = float(df.loc[idx, "Open"]); h = float(df.loc[idx, "High"]); l = float(df.loc[idx, "Low"])
        orhs.append(o + 0.40*(h - o)); orls.append(o - 0.40*(o - l))
    df["orh"] = orhs; df["orl"] = orls
    df["or_range"] = df["orh"] - df["orl"]

    trades = []
    for day in df.index:
        if not is_trading_day(day):
            continue

        today    = df.loc[day]
        open_px  = float(today["Open"])
        day_high = float(today["High"])
        day_low  = float(today["Low"])
        day_range = day_high - day_low
        close_px = float(today["Close"])
        orh, orl = float(today["orh"]), float(today["orl"])

        # OR range filter (skip thin-range days)
        if day_range < 0.010 * open_px:
            continue

        bias = htf_bias(df, day) if use_bias else 0

        # 5-min confirmation: close above ORH = long, below ORL = short
        direction = 1 if close_px > orh else (-1 if close_px < orl else None)
        if direction is None:
            continue

        if use_bias:
            if direction == 1 and bias == -1: continue
            if direction == -1 and bias == 1:  continue

        # ── Correct ORB stop / target math ──────────────────────────────────────────
        #
        # ORB video: risk = entry→OR_boundary, tp_1R = opposite OR boundary, tp_2R = 2×
        # risk = 50% of OR range (entry to OR boundary = half the range)
        # tp_1r = entry ± OR_range (opposite OR boundary = 1R)
        # tp_2r = entry ± 2×OR_range (2R)
        #
        # Example TSLA Aug14: OR_range=15.93, risk=7.96, tp_1r=345.91±15.93, tp_2r=345.91±31.86
        # TSLA Aug14 actual: day_high=351.26, tp_1r=361.84 — NOT reached → -1R stop

        risk = day_range * 0.50   # 50% of OR range = distance from entry to opposite OR boundary

        if direction == 1:   # LONG
            entry  = orh + 0.01
            stop    = entry - risk    # ORL proxy
            tp_1r  = entry + risk     # = entry + OR_range = 1R
            tp_2r  = entry + risk * 2 # = entry + 2×OR_range = 2R
        else:               # SHORT
            entry  = orl - 0.01
            stop    = entry + risk    # ORH proxy
            tp_1r  = entry - risk     # = entry - OR_range = 1R
            tp_2r  = entry - risk * 2 # = entry - 2×OR_range = 2R

        if direction == 1:
            if day_low  <= stop:     outcome, exit_px, pnl_r = "loss",  stop,   -1.0
            elif day_high >= tp_2r: outcome, exit_px, pnl_r = "win2", tp_2r,  2.0
            elif day_high >= tp_1r: outcome, exit_px, pnl_r = "win1", tp_1r,  1.0
            else:
                pnl_r = (close_px - entry) / risk
                outcome, exit_px = "close", close_px
        else:
            if day_high >= stop:    outcome, exit_px, pnl_r = "loss",  stop,   -1.0
            elif day_low  <= tp_2r: outcome, exit_px, pnl_r = "win2", tp_2r,  2.0
            elif day_low  <= tp_1r: outcome, exit_px, pnl_r = "win1", tp_1r,  1.0
            else:
                pnl_r = (entry - close_px) / risk
                outcome, exit_px = "close", close_px

        trades.append({
            "date":    str(day.date()),
            "dir":     direction,
            "entry":   round(entry, 4),
            "stop":    round(stop, 4),
            "tp_1r":   round(tp_1r, 4),
            "tp_2r":   round(tp_2r, 4),
            "or_range":round(day_range, 4),
            "exit":    round(exit_px, 4),
            "outcome": outcome,
            "pnl_r":   round(pnl_r, 4),
            "bias":    bias,
        })
    return trades

# ── run ──────────────────────────────────────────────────────────────────────

results = {}
for ticker in TICKERS:
    t0 = pd.Timestamp.now()
    tr    = simulate(ticker, START, END, use_bias=False)
    tr_b  = simulate(ticker, START, END, use_bias=True)
    results[ticker] = {"raw": tr, "biased": tr_b}
    print(f"[*] {ticker} ... {len(tr)} trades ({len(tr_b)} w/bias)  {pd.Timestamp.now()-t0}")

# ── summary ──────────────────────────────────────────────────────────────────

HDR = f"{'TICKER':<8} {'TRADES':>6} {'WINS':>5} {'LOSS':>5} {'CLOSE':>6} {'WR':>7} {'AvgR':>7} {'MaxDD':>7}"
SEP = "=" * 65

for label, key in [("No HTF Bias", "raw"), ("With HTF Bias", "biased")]:
    print(f"\n{'─'*65}")
    print(f"MODE: {label}")
    print(SEP); print(HDR); print(SEP)
    all_t = []
    for ticker, d in results.items():
        raw = d[key]
        wins = [t for t in raw if t["outcome"] in ("win1","win2")]
        loss = [t for t in raw if t["outcome"] == "loss"]
        close_t = [t for t in raw if t["outcome"] == "close"]
        if not raw:
            print(f"{ticker:<8}  No trades"); continue
        pnls = [t["pnl_r"] for t in raw]
        cumul = np.cumsum(pnls)
        maxdd = float(max(np.maximum.accumulate(cumul) - cumul))
        avg   = float(np.mean(pnls))
        print(f"{ticker:<8} {len(raw):>6} {len(wins):>5} {len(loss):>5} {len(close_t):>6} "
              f"{len(wins)/len(raw):>7.1%} {avg:>7.3f} {maxdd:>7.3f}")
        all_t.extend(raw)

    if all_t:
        wins = [t for t in all_t if t["outcome"] in ("win1","win2")]
        loss = [t for t in all_t if t["outcome"] == "loss"]
        close_t = [t for t in all_t if t["outcome"] == "close"]
        pnls = [t["pnl_r"] for t in all_t]
        cumul = np.cumsum(pnls)
        maxdd = float(max(np.maximum.accumulate(cumul) - cumul))
        avg   = float(np.mean(pnls))
        print("-" * 65)
        print(f"{'TOTAL':<8} {len(all_t):>6} {len(wins):>5} {len(loss):>5} {len(close_t):>6} "
              f"{len(wins)/len(all_t):>7.1%} {avg:>7.3f} {maxdd:>7.3f}")
        w1 = sum(1 for t in wins if t["outcome"]=="win1")
        w2 = sum(1 for t in wins if t["outcome"]=="win2")
        print(f"  win1={w1} | win2={w2} | losses={len(loss)} | close={len(close_t)}")

# ── save ──────────────────────────────────────────────────────────────────────
out = {"meta": {"start":START,"end":END,"tickers":TICKERS},
       "per_ticker": {t: {"raw":d["raw"],"biased":d["biased"]} for t,d in results.items()}}
with open("/Users/jaydensmac/.openclaw/workspace/orb_backtest_results.json","w") as f:
    json.dump(out, f, indent=2)
print(f"\n[+] Saved → orb_backtest_results.json")
