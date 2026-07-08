#!/usr/bin/env python3
"""
tjl_backtest.py — Python backtest of Trend Join Long (TJL) v4
──────────────────────────────────────────────────────────────
Replicates the PineScript v6 logic using yfinance 5-min data.

Strategy params (mirrors PineScript defaults):
  EMA fast / slow / bias : 9 / 20 / 50
  ATR length             : 14
  Stop loss              : 1.5 × ATR below entry
  Take profit            : 3.0 × ATR above entry
  PMH buffer             : $0.10
  Max entries / day      : 3
  No-entry cutoff        : 14:00 ET
  EOD flat               : 15:55 ET
  Session                : 09:30–16:00 ET
  Initial capital        : $25,000
  Position size          : 5% of equity per trade
  Commission             : 0.05% per side
  Slippage               : $0.02 per share (≈ 2 ticks)
"""

import json
import math
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ET = ZoneInfo("America/New_York")

# ── Params ────────────────────────────────────────────────────────────────────
EMA_FAST     = 9
EMA_SLOW     = 20
EMA_BIAS     = 50
ATR_LEN      = 14
SL_MULT      = 1.5
TP_MULT      = 3.0
PMH_BUF      = 0.10
USE_PMH      = True
MAX_DAY      = 3
CUTOFF_HHMM  = 1400
EOD_HHMM     = 1555
INIT_CAP     = 25_000.0
PCT_SIZE     = 0.05
COMMISSION   = 0.0005   # 0.05% per side
SLIPPAGE     = 0.02     # $ per share


# ── Helpers ───────────────────────────────────────────────────────────────────
def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _atr(high, low, close, period=14):
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ── Core backtest ─────────────────────────────────────────────────────────────
def run_backtest(ticker: str, days: int = 30) -> dict:
    # ── Fetch ─────────────────────────────────────────────────────────────
    today = date.today()
    # Yahoo Finance hard-caps 5-min data at 60 days.
    # Fetch up to 59 days total; use first 5 as EMA warm-up, rest as sim window.
    fetch_days = min(days + 5, 59)
    start = today - timedelta(days=fetch_days)

    df = yf.download(
        ticker,
        start=str(start),
        end=str(today + timedelta(days=1)),
        interval="5m",
        prepost=True,        # include pre/after-hours for PMH
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        return {"ticker": ticker, "error": "no data"}

    # Flatten MultiIndex columns (yfinance quirk)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Convert to ET
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(ET)

    # ── Indicators (all bars for EMA warm-up accuracy) ────────────────────
    df["ema_f"] = _ema(df["Close"], EMA_FAST)
    df["ema_s"] = _ema(df["Close"], EMA_SLOW)
    df["ema_b"] = _ema(df["Close"], EMA_BIAS)
    df["atr"]   = _atr(df["High"], df["Low"], df["Close"], ATR_LEN)

    # ── Time columns ──────────────────────────────────────────────────────
    df["hhmm"]    = df.index.hour * 100 + df.index.minute
    df["et_date"] = df.index.date
    df["is_pre"]  = (df["hhmm"] >= 400)  & (df["hhmm"] < 930)
    df["is_reg"]  = (df["hhmm"] >= 930)  & (df["hhmm"] < 1600)
    df["past_cut"]= df["hhmm"] >= CUTOFF_HHMM

    # ── PMH: max premarket high per calendar day ───────────────────────────
    pre = df[df["is_pre"]][["et_date", "High"]]
    pmh_map = pre.groupby("et_date")["High"].max() if not pre.empty else pd.Series(dtype=float)
    df["PMH"]       = df["et_date"].map(pmh_map)
    df["pmh_level"] = df["PMH"] + PMH_BUF

    # ── Entry signals ─────────────────────────────────────────────────────
    df["trend_up"]  = (
        (df["Close"] > df["ema_s"]) &
        (df["ema_f"] > df["ema_s"]) &
        (df["ema_s"] > df["ema_b"])
    )
    # Crossover: close crosses above EMA9
    df["crossover"] = (
        (df["Close"].shift(1) <= df["ema_f"].shift(1)) &
        (df["Close"] > df["ema_f"])
    )
    # Pullback: any of last 4 bars' low touched EMA9 zone
    df["pb_low"]     = df["Low"].rolling(4).min()
    df["pb_touched"] = df["pb_low"] <= df["ema_f"] * 1.002
    df["join"]       = df["crossover"] & df["pb_touched"]
    df["pmh_ok"]     = (
        (not USE_PMH) |
        df["PMH"].isna() |
        (df["Close"] > df["pmh_level"])
    )

    # ── Simulation (only on the last `days` of calendar data) ─────────────
    cutoff = today - timedelta(days=days)
    sim    = df[df["et_date"] >= cutoff].copy()

    equity     = INIT_CAP
    position   = None
    trades     = []
    day_cnt    = {}   # date → entries taken

    for row in sim.itertuples():
        d    = row.et_date
        hhmm = row.hhmm

        # ── EOD: close any open position ──────────────────────────────────
        if position is not None and hhmm >= EOD_HHMM and row.is_reg:
            px  = row.Close - SLIPPAGE
            pnl = (px - position["entry_px"]) * position["shares"]
            pnl -= (position["entry_px"] + px) * position["shares"] * COMMISSION
            equity += pnl
            trades.append({**position, "exit_px": round(px, 4),
                           "exit_time": str(row.Index), "exit_reason": "EOD",
                           "pnl": round(pnl, 2), "equity": round(equity, 2)})
            position = None
            continue

        # ── SL / TP check ─────────────────────────────────────────────────
        if position is not None and row.is_reg:
            hit_sl = row.Low  <= position["sl"]
            hit_tp = row.High >= position["tp"]
            if hit_sl or hit_tp:
                if hit_tp and not hit_sl:
                    px, reason = position["tp"], "TP"
                else:
                    px, reason = position["sl"], "SL"   # SL wins if both hit
                px  = max(px - SLIPPAGE, 0.01)
                pnl = (px - position["entry_px"]) * position["shares"]
                pnl -= (position["entry_px"] + px) * position["shares"] * COMMISSION
                equity += pnl
                trades.append({**position, "exit_px": round(px, 4),
                               "exit_time": str(row.Index), "exit_reason": reason,
                               "pnl": round(pnl, 2), "equity": round(equity, 2)})
                position = None
                continue

        # ── Entry check ───────────────────────────────────────────────────
        if (position is None
                and row.is_reg
                and not row.past_cut
                and row.trend_up
                and row.join
                and row.pmh_ok
                and not pd.isna(row.ema_f)
                and not pd.isna(row.atr)
                and row.atr > 0):

            if day_cnt.get(d, 0) < MAX_DAY:
                px     = row.Close + SLIPPAGE
                sl     = px - SL_MULT * row.atr
                tp     = px + TP_MULT * row.atr
                shares = math.floor((equity * PCT_SIZE) / px)
                if shares < 1:
                    continue
                equity -= px * shares * COMMISSION   # entry commission
                position = {
                    "ticker":     ticker,
                    "entry_time": str(row.Index),
                    "entry_px":   round(px, 4),
                    "sl":         round(sl, 4),
                    "tp":         round(tp, 4),
                    "shares":     shares,
                    "atr":        round(float(row.atr), 4),
                    "pmh":        round(float(row.PMH), 4) if not pd.isna(row.PMH) else None,
                }
                day_cnt[d] = day_cnt.get(d, 0) + 1

    # Close any position still open at end of data
    if position is not None and not sim.empty:
        px  = float(sim["Close"].iloc[-1]) - SLIPPAGE
        pnl = (px - position["entry_px"]) * position["shares"]
        pnl -= (position["entry_px"] + px) * position["shares"] * COMMISSION
        equity += pnl
        trades.append({**position, "exit_px": round(px, 4),
                       "exit_time": str(sim.index[-1]), "exit_reason": "END",
                       "pnl": round(pnl, 2), "equity": round(equity, 2)})

    # ── Metrics ───────────────────────────────────────────────────────────
    n = len(trades)
    if n == 0:
        return {"ticker": ticker, "trades": 0, "wins": 0, "losses": 0,
                "win_rate_pct": 0.0, "total_pnl": 0.0, "pnl_pct": 0.0,
                "profit_factor": 0.0, "max_dd": 0.0, "max_dd_pct": 0.0,
                "final_equity": round(equity, 2)}

    wins_list  = [t for t in trades if t["pnl"] > 0]
    loss_list  = [t for t in trades if t["pnl"] <= 0]
    gross_win  = sum(t["pnl"] for t in wins_list)
    gross_loss = abs(sum(t["pnl"] for t in loss_list))
    pf         = round(gross_win / gross_loss, 3) if gross_loss > 0 else float("inf")

    # Max drawdown over equity curve
    eq_curve = [INIT_CAP] + [t["equity"] for t in trades]
    peak, max_dd = INIT_CAP, 0.0
    for e in eq_curve:
        peak   = max(peak, e)
        max_dd = max(max_dd, peak - e)

    total_pnl = equity - INIT_CAP
    return {
        "ticker":        ticker,
        "trades":        n,
        "wins":          len(wins_list),
        "losses":        len(loss_list),
        "win_rate_pct":  round(len(wins_list) / n * 100, 1),
        "total_pnl":     round(total_pnl, 2),
        "pnl_pct":       round(total_pnl / INIT_CAP * 100, 2),
        "profit_factor": pf,
        "max_dd":        round(max_dd, 2),
        "max_dd_pct":    round(max_dd / INIT_CAP * 100, 2),
        "final_equity":  round(equity, 2),
        "trades_detail": trades,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
TICKERS = [
    "NVDA",   # watchlist
    "AMD",    # TradingView test stock
    "TSLA",
    "META",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
]

if __name__ == "__main__":
    days = 30
    print(f"\nTJL v4 — Python Backtest — Last {days} calendar days")
    print(f"Capital: ${INIT_CAP:,.0f}  |  Size: {PCT_SIZE*100:.0f}%/trade  |"
          f"  SL {SL_MULT}×ATR  TP {TP_MULT}×ATR  |  Comm {COMMISSION*100:.2f}%  Slip ${SLIPPAGE}")
    print("=" * 80)
    hdr = f"{'Ticker':<7} {'Trades':>6} {'Wins':>5} {'Losses':>7} "
    hdr += f"{'WinRate':>8} {'P&L $':>10} {'P&L %':>7} {'PF':>7} {'MaxDD $':>9} {'MaxDD%':>7}"
    print(hdr)
    print("-" * 80)

    all_results = []
    for tkr in TICKERS:
        try:
            r = run_backtest(tkr, days)
            all_results.append(r)
            if "error" in r:
                print(f"{tkr:<7}  ERROR: {r['error']}")
            else:
                print(
                    f"{r['ticker']:<7} {r['trades']:>6} {r['wins']:>5} {r['losses']:>7} "
                    f"{r['win_rate_pct']:>7.1f}% {r['total_pnl']:>+10.2f} "
                    f"{r['pnl_pct']:>+6.2f}% {r['profit_factor']:>7.3f} "
                    f"{r['max_dd']:>9.2f} {r['max_dd_pct']:>6.2f}%"
                )
        except Exception as ex:
            print(f"{tkr:<7}  EXCEPTION: {ex}")
            all_results.append({"ticker": tkr, "error": str(ex)})

    print("=" * 80)

    # Aggregate across all valid results
    valid = [r for r in all_results if "error" not in r and r["trades"] > 0]
    if valid:
        tot_trades = sum(r["trades"]  for r in valid)
        tot_wins   = sum(r["wins"]    for r in valid)
        tot_pnl    = sum(r["total_pnl"] for r in valid)
        avg_pf     = sum(r["profit_factor"] for r in valid if r["profit_factor"] != float("inf")) / max(len(valid), 1)
        print(
            f"{'TOTAL':<7} {tot_trades:>6} {tot_wins:>5} {tot_trades-tot_wins:>7} "
            f"{tot_wins/tot_trades*100:>7.1f}% {tot_pnl:>+10.2f}            "
            f"{avg_pf:>7.3f}"
        )

    # Save results (strip trade detail for cleaner JSON summary)
    summary = []
    for r in all_results:
        s = {k: v for k, v in r.items() if k != "trades_detail"}
        summary.append(s)

    out = {
        "run_date":   str(date.today()),
        "days":       days,
        "tickers":    TICKERS,
        "strategy":   {"ema_fast": EMA_FAST, "ema_slow": EMA_SLOW, "ema_bias": EMA_BIAS,
                       "sl_mult": SL_MULT, "tp_mult": TP_MULT, "pmh_buf": PMH_BUF,
                       "max_day": MAX_DAY, "commission": COMMISSION, "slippage": SLIPPAGE},
        "results":    summary,
    }
    with open("tjl_backtest_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nSaved → tjl_backtest_results.json")
