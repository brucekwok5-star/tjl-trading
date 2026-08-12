#!/usr/bin/env python3
"""HK 15-min backtest for the 6 HK signals"""
import sys; sys.path.insert(0,"/Users/jaydensmac/.openclaw/workspace")
import os
os.environ["DISCORD_WEBHOOK_HK_TJL"] = "https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj"

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import time as dtime
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")

ATR_SL = 1.5
ATR_TP = 3.0
ATR_PERIOD = 14
NEAR_EMA_PCT = 0.01
PMH_BUF = 0.70
WARMUP = 50

TICKERS = ["1024.HK","2382.HK","2313.HK","6030.HK","1044.HK","2020.HK"]

def log(msg):
    print(f"[{pd.Timestamp.now(ET).strftime('%H:%M:%S ET')}] {msg}", flush=True)

def get_hk_15m_bars(ticker, days=60):
    tk = yf.Ticker(ticker)
    df = tk.history(period=f"{days}d", interval="15m")
    if df.empty:
        return None
    df.index = df.index.tz_convert(HK)
    df = df.between_time(dtime(9, 30), dtime(15, 55))
    df = df.dropna(subset=["Close"])
    return df

def ema_at(arr, idx, span):
    if idx < span: return np.nan
    c = np.array(arr[:idx+1], dtype=float)
    return float(pd.Series(c).ewm(span=span, adjust=False).mean().iloc[-1])

def rolling_atr(highs, lows, closes, idx, period=14):
    if idx < period + 1: return np.nan
    h = np.array(highs[:idx+1]); l = np.array(lows[:idx+1]); c = np.array(closes[:idx+1])
    tr = np.maximum(h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))
    return float(tr[-period:].mean())

def rolling_rsi(arr, idx, period=14):
    if idx < period + 1: return np.nan
    c = np.array(arr[:idx+1], dtype=float)
    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    ag = float(pd.Series(gain).ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    al = float(pd.Series(loss).ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    if al == 0: return 100.0
    return 100 - (100 / (1 + ag / al))

def rolling_vwap(highs, lows, closes, vols, idx):
    if idx < 2: return np.nan
    h = np.array(highs[:idx+1]); l = np.array(lows[:idx+1])
    c = np.array(closes[:idx+1]); v = np.array(vols[:idx+1])
    if v.sum() == 0: return np.nan
    tp = (h + l + c) / 3
    return float((tp * v).sum() / v.sum())

def backtest_ticker(ticker, regime_override="BEARISH"):
    df = get_hk_15m_bars(ticker, days=60)
    if df is None or len(df) < WARMUP + 20:
        log(f"{ticker}: {len(df) if df is not None else 0} bars — skipping"); return []

    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    vols   = df["Volume"].values
    times  = df.index

    tk = yf.Ticker(ticker)
    dly = tk.history(period="30d", interval="1d")
    day_open = float(dly["Open"].iloc[-1]) if not dly.empty else closes[0]
    prev_day_high = float(dly["High"].iloc[-2]) if len(dly) >= 2 else None

    trades = []
    in_pos = False
    e_px = e_atr = e_dir = e_mdl = None

    for i in range(WARMUP, len(closes)):
        price = closes[i]
        hi, lo = highs[i], lows[i]
        dt = times[i]

        if in_pos:
            if e_dir == "LONG":
                hit_sl = (lo <= e_px - ATR_SL * e_atr)
                hit_tp = (hi >= e_px + ATR_TP * e_atr)
                if hit_sl or hit_tp:
                    ep = (e_px - ATR_SL * e_atr) if hit_sl else (e_px + ATR_TP * e_atr)
                    pnl = (ep - e_px) / e_px * 100
                    res = "WIN" if pnl > 0.05 else ("LOSS" if pnl < -0.05 else "BE")
                    trades.append({"Ticker":ticker,"Time":str(dt)[:16],"Entry":round(e_px,2),"Exit":round(ep,2),"PnL%":round(pnl,2),"Result":res,"ATR":round(e_atr,3),"Dir":e_dir,"Model":e_mdl})
                    in_pos = False
            elif e_dir == "SHORT":
                hit_sl = (hi >= e_px + ATR_SL * e_atr)
                hit_tp = (lo <= e_px - ATR_TP * e_atr)
                if hit_sl or hit_tp:
                    ep = (e_px + ATR_SL * e_atr) if hit_sl else (e_px - ATR_TP * e_atr)
                    pnl = (e_px - ep) / e_px * 100
                    res = "WIN" if pnl > 0.05 else ("LOSS" if pnl < -0.05 else "BE")
                    trades.append({"Ticker":ticker,"Time":str(dt)[:16],"Entry":round(e_px,2),"Exit":round(ep,2),"PnL%":round(pnl,2),"Result":res,"ATR":round(e_atr,3),"Dir":e_dir,"Model":e_mdl})
                    in_pos = False
            continue

        e9  = ema_at(closes, i, 9)
        e20 = ema_at(closes, i, 20)
        e50 = ema_at(closes, i, 50)
        atr = rolling_atr(highs, lows, closes, i, ATR_PERIOD)
        if np.isnan(e9) or np.isnan(atr): continue

        rsi   = rolling_rsi(closes, i)
        vwap  = rolling_vwap(highs, lows, closes, vols, i)
        vol_now = vols[i]
        vol_avg = float(np.mean(vols[max(0,i-20):i]))

        sma200 = float(pd.Series(closes[:i+1]).rolling(200).mean().iloc[-1]) if i >= 200 else np.nan
        wma63  = float(pd.Series(closes[:i+1]).rolling(63).mean().iloc[-1]) if i >= 63 else np.nan
        dma5   = float(pd.Series(closes[:i+1]).rolling(5).mean().iloc[-1])
        dma20  = float(pd.Series(closes[:i+1]).rolling(20).mean().iloc[-1])
        pdma5  = float(pd.Series(closes[:i]).rolling(5).mean().iloc[-1]) if i > 0 else dma5
        pdma20 = float(pd.Series(closes[:i]).rolling(20).mean().iloc[-1]) if i > 0 else dma20
        bb_mid = float(pd.Series(closes[max(0,i-20):i+1]).mean())
        bb_std = float(pd.Series(closes[max(0,i-20):i+1]).std())
        hi20   = float(np.max(highs[max(0,i-20):i+1]))

        stack_ok = (not np.isnan(e9) and not np.isnan(e20) and not np.isnan(e50) and e9 > e20 > e50)
        regime = regime_override
        fired = []

        # A
        if regime in ("BULLISH","neutral") and stack_ok and abs(price-e9)/e9 <= NEAR_EMA_PCT and (prev_day_high is not None and price > prev_day_high + PMH_BUF):
            fired.append(("A","LONG"))
        # B
        if regime in ("BULLISH","neutral") and not np.isnan(sma200) and price > sma200:
            fired.append(("B","LONG"))
        # C
        if regime in ("BULLISH","neutral") and stack_ok and abs(price-e9)/e9 <= 0.02 and vol_now > vol_avg * 1.5:
            fired.append(("C","LONG"))
        # D
        if regime in ("BULLISH","neutral") and rsi < 55:
            fired.append(("D","LONG"))
        # E
        if regime in ("BULLISH","neutral") and price >= hi20 * 0.98 and vol_now > vol_avg * 1.2:
            fired.append(("E","LONG"))
        # F
        if rsi >= 40 and rsi <= 70 and stack_ok and regime in ("BULLISH","neutral"):
            fired.append(("F","LONG"))
        if rsi >= 30 and rsi <= 60 and not stack_ok and regime in ("BEARISH","neutral"):
            fired.append(("F","SHORT"))
        # G
        above_open = price > day_open + 0.10
        below_open = price < day_open - 0.10
        if above_open and stack_ok and regime in ("BULLISH","neutral"):
            fired.append(("G","LONG"))
        if below_open and not stack_ok and regime in ("BEARISH","neutral"):
            fired.append(("G","SHORT"))
        # H
        bb_upper = bb_mid + bb_std * 2
        bb_lower = bb_mid - bb_std * 2
        near_bb = bb_lower <= price <= bb_upper
        if near_bb and vol_now > vol_avg:
            if stack_ok and regime in ("BULLISH","neutral"): fired.append(("H","LONG"))
            if not stack_ok and regime in ("BEARISH","neutral"): fired.append(("H","SHORT"))
        # I
        above_wma = (not np.isnan(wma63) and price > wma63)
        near_e9_ok = abs(price-e9)/e9 <= 0.015
        if near_e9_ok and vol_now > vol_avg:
            if above_wma and regime in ("BULLISH","neutral"): fired.append(("I","LONG"))
            if not above_wma and regime in ("BEARISH","neutral"): fired.append(("I","SHORT"))
        # J
        cross_up   = (dma5 > dma20) and (pdma5 <= pdma20)
        cross_down = (dma5 < dma20) and (pdma5 >= pdma20)
        if cross_up and vol_now > vol_avg and regime in ("BULLISH","neutral"): fired.append(("J","LONG"))
        if cross_down and vol_now > vol_avg and regime in ("BEARISH","neutral"): fired.append(("J","SHORT"))
        # K
        above_vwap = (vwap is not None and not np.isnan(vwap) and price > vwap) or (vwap is None or np.isnan(vwap))
        if above_vwap and near_bb and regime in ("BULLISH","neutral"): fired.append(("K","LONG"))
        if not above_vwap and near_bb and regime in ("BEARISH","neutral"): fired.append(("K","SHORT"))

        if fired:
            mdl, direction = fired[0]
            in_pos = True
            e_px = price; e_atr = atr; e_dir = direction; e_mdl = mdl

    return trades

if __name__ == "__main__":
    log(f"HK 15-min Backtest | 6 HK stocks | 11 Models | BEARISH")
    log(f"Tickers: {', '.join(TICKERS)}")
    log("="*60)

    all_trades = []
    for ticker in TICKERS:
        log(f"Backtesting {ticker}...")
        trades = backtest_ticker(ticker, regime_override="BEARISH")
        all_trades.extend(trades)
        if trades:
            w = [t for t in trades if t["Result"]=="WIN"]
            l = [t for t in trades if t["Result"]=="LOSS"]
            be = [t for t in trades if t["Result"]=="BE"]
            log(f"  {len(trades)} trades | {len(w)}W {len(l)}L {len(be)}BE | WR={len(w)/len(trades)*100:.0f}%")
        else:
            log(f"  0 trades")

    log(f"\n{'='*60}")
    log(f"TOTAL: {len(all_trades)} trades")
    if all_trades:
        w = [t for t in all_trades if t["Result"]=="WIN"]
        l = [t for t in all_trades if t["Result"]=="LOSS"]
        be = [t for t in all_trades if t["Result"]=="BE"]
        wr = len(w)/len(all_trades)*100
        avg = float(np.mean([t["PnL%"] for t in all_trades]))
        log(f"  WIN={len(w)} | LOSS={len(l)} | BE={len(be)}")
        log(f"  Win Rate: {wr:.1f}%")
        log(f"  Avg P&L: {avg:+.2f}%")
        log(f"\nPer ticker:")
        for tkr in sorted(set(t["Ticker"] for t in all_trades)):
            ts = [t for t in all_trades if t["Ticker"]==tkr]
            ws = [t for t in ts if t["Result"]=="WIN"]
            wr_t = len(ws)/len(ts)*100
            avg_t = float(np.mean([t["PnL%"] for t in ts]))
            log(f"  {tkr}: {len(ts)} trades | WR={wr_t:.0f}% | Avg={avg_t:+.2f}%")
        log(f"\nPer model:")
        for mdl in sorted(set(t["Model"] for t in all_trades)):
            ts = [t for t in all_trades if t["Model"]==mdl]
            ws = [t for t in ts if t["Result"]=="WIN"]
            wr_m = len(ws)/len(ts)*100
            avg_m = float(np.mean([t["PnL%"] for t in ts]))
            log(f"  {mdl}: {len(ts)} trades | WR={wr_m:.0f}% | Avg={avg_m:+.2f}%")
        log(f"\nAll trades ({len(all_trades)}):")
        print(f"  {'Ticker':<12} {'Time':<18} {'Dir':<6} {'Model':<6} {'Entry':>8} {'Exit':>8} {'PnL%':>8} {'Result':<6}")
        print(f"  {'-'*80}")
        for t in sorted(all_trades, key=lambda x: x["Time"]):
            print(f"  {t['Ticker']:<12} {t['Time']:<18} {t['Dir']:<6} {t['Model']:<6} {t['Entry']:>8.2f} {t['Exit']:>8.2f} {t['PnL%']:>+7.2f}% {t['Result']:<6}")
    else:
        log("  No trades generated — check HK market hours filter")
