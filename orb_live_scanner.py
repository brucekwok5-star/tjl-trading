#!/usr/bin/env python3
"""
ORB Live Scanner — Discord alerts for US market
Fires at 9:30 AM EST Mon-Fri, reads 15-min yfinance data, posts to Discord.
"""
import yfinance as yf
import pandas as pd
import numpy as np
import json
import sys
import re
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, date

DISCORD_WH  = "https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj"
TICKERS     = ["QQQ", "SPY", "TSLA", "NVDA"]
TZ          = "America/New_York"

# ── helpers ───────────────────────────────────────────────────────────────────

def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in {
        date(2026,1,1), date(2026,1,19), date(2026,2,16), date(2026,4,3),
        date(2026,5,25), date(2026,7,3),  date(2026,9,7),  date(2026,11,26),
        date(2026,12,25),
    }

def fetch_15m(ticker: str, trade_date: pd.Timestamp) -> pd.DataFrame | None:
    """Fetch 15-min bars for the session day. Yahoo caps at ~60 days."""
    start = (trade_date - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    end   = (trade_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.Ticker(ticker).history(start=start, end=end, interval="15m", auto_adjust=True)
    if df.empty:
        return None
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(TZ)
    else:
        df.index = df.index.tz_convert(TZ)
    ds = trade_date.replace(hour=9, minute=30, second=0)
    de = trade_date.replace(hour=16, minute=0, second=0)
    return df[(df.index >= ds) & (df.index <= de)]

def orb_levels(day: pd.DataFrame):
    """Compute ORH, ORL, range from first 15-min bar."""
    first = day.iloc[0]
    o = float(first["Open"])
    h = float(first["High"])
    l = float(first["Low"])
    orh = o + 0.40 * (h - o)
    orl = o - 0.40 * (o - l)
    return orh, orl, h - l

def confirm_direction(day: pd.DataFrame, orh: float, orl: float, cutoff: pd.Timestamp):
    """Confirm direction: close above ORH = LONG, below ORL = SHORT, else None."""
    window = day[(day.index >= cutoff) & (day.index <= cutoff + pd.Timedelta(minutes=5))]
    if window.empty:
        return None
    close = float(window.iloc[0]["Close"])
    return 1 if close > orh else (-1 if close < orl else None)

def htf_bias(ticker: str, before: pd.Timestamp) -> int:
    """1 = above 20sma (bull), -1 = below (bear), 0 = neutral."""
    df = yf.Ticker(ticker).history(
        start=(before - pd.Timedelta(days=60)).strftime("%Y-%m-%d"),
        end  =(before - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1d", auto_adjust=True)
    if len(df) < 20:
        return 0
    sma = df["Close"].tail(20).mean()
    last = df["Close"].iloc[-1]
    return 1 if last > sma else (-1 if last < sma else 0)

def get_pct_risk(ticker: str) -> float:
    """ATR-based pct risk (clamped 0.3%–1.0% of price)."""
    df = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=True)
    if len(df) < 15:
        return 0.005
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    last = df["Close"].iloc[-1]
    return float(min(max(atr / last, 0.003), 0.010))

def orb_signal(ticker: str, trade_date: pd.Timestamp) -> dict | None:
    """Full ORB signal for one ticker on trade_date. Returns None if no signal."""
    if not is_trading_day(trade_date.date()):
        return None
    day = fetch_15m(ticker, trade_date)
    if day is None or len(day) < 2:
        return None

    orh, orl, rng = orb_levels(day)
    open_px = float(day.iloc[0]["Open"])
    if rng < 0.010 * open_px:
        return None   # thin range filter

    session_start = trade_date.replace(hour=9, minute=30, second=0)
    direction = confirm_direction(day, orh, orl, session_start)
    if direction is None:
        return None

    bias = htf_bias(ticker, trade_date)
    p_r  = get_pct_risk(ticker)

    # Skip against trend
    if direction == 1 and bias == -1:
        return None
    if direction == -1 and bias == 1:
        return None

    if direction == 1:
        entry = orh + 0.01
        stop   = entry * (1 - p_r)
        risk   = entry * p_r
        tp1    = entry + risk
        tp2    = entry + risk * 2
    else:
        entry = orl - 0.01
        stop   = entry * (1 + p_r)
        risk   = entry * p_r
        tp1    = entry - risk
        tp2    = entry - risk * 2

    bias_label = {1: "HTF BULL", -1: "HTF BEAR", 0: "HTF NEUTRAL"}[bias]

    return {
        "ticker":    ticker,
        "dir":       "LONG" if direction == 1 else "SHORT",
        "dir_num":   direction,
        "entry":     round(entry, 2),
        "stop":      round(stop, 2),
        "tp1":       round(tp1, 2),
        "tp2":       round(tp2, 2),
        "orh":       round(orh, 2),
        "orl":       round(orl, 2),
        "range_pct": round(rng / open_px * 100, 2),
        "bias":      bias_label,
        "atr_pct":   round(p_r * 100, 2),
    }

# ── Discord ───────────────────────────────────────────────────────────────────

def post_discord(signals: list[dict]):
    """Post ORB signals to Discord webhook."""
    if not signals:
        return
    now_str = datetime.now().strftime("%b %d %Y %H:%M ET")
    lines = [f"**ORB Scan — {now_str}**"]
    for s in signals:
        emoji = "LONG" if s["dir"] == "LONG" else "SHORT"
        lines.append("")
        lines.append(f"**{s['ticker']}**  {emoji}  `[HTF {s['bias']}]`")
        lines.append(f"   Entry: `{s['entry']}`  Stop: `{s['stop']}`  TP1: `{s['tp1']}`  TP2: `{s['tp2']}`")
        lines.append(f"   ORH: `{s['orh']}`  ORL: `{s['orl']}`  Range: `{s['range_pct']}%`  Risk: `{s['atr_pct']}%`")

    body = {"content": "\n".join(lines), "thread_name": "ORB US Live"}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WH, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "orb-live-scanner/1.0 (+https://hermes.local)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[Discord] Posted {len(signals)} signal(s) — {resp.status}")
    except Exception as e:
        print(f"[Discord] ERROR: {e}")

# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # --dry-run: scan today without posting
    dry = "--dry-run" in sys.argv

    trade_date = pd.Timestamp.now(TZ).normalize()

    print(f"[ORB Scanner] {trade_date.date()} — scanning {TICKERS} ...")

    signals = []
    for ticker in TICKERS:
        sig = orb_signal(ticker, trade_date)
        if sig:
            print(f"  {ticker}: {sig['dir']}  entry={sig['entry']}  stop={sig['stop']}  "
                  f"tp1={sig['tp1']}  tp2={sig['tp2']}  [{sig['bias']}]")
            signals.append(sig)
        else:
            print(f"  {ticker}: no signal")

    if signals:
        if dry:
            print(f"[Dry run] Would post {len(signals)} signal(s) to Discord")
        else:
            post_discord(signals)
    else:
        print("[ORB Scanner] No signals today.")
