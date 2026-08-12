#!/usr/bin/env python3
"""TJL US cash session open scan — TV MCP with yfinance fallback.

Writes a single JSON document to TJL_LIVE_OUT describing regime, signals,
and source. The cron job consumes that JSON, posts to Discord, and forwards
to Telegram via `hermes send --to telegram -`.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone

OUT_PATH = os.environ.get("TJL_LIVE_OUT", "/tmp/tjl_us_open.json")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _empty_payload(error: str | None = None) -> dict:
    return {
        "scanned_at": _now(),
        "source": "tjl_live_us_tv",
        "regime": "UNKNOWN",
        "regime_emoji": "⚪",
        "signals": [],
        "error": error,
    }


def try_tv_mcp() -> dict | None:
    """Best-effort TV MCP quote fetch. Returns a regime dict or None on failure."""
    try:
        # Lazy imports — MCP tools are loaded via tool_call in normal Hermes sessions.
        # In cron we have no MCP bridge, so this returns None immediately.
        return None
    except Exception:
        return None


def yfinance_scan() -> dict:
    """Fallback scanner using yfinance on the NDX pre-market universe."""
    import yfinance as yf  # type: ignore

    tickers_env = os.environ.get(
        "TJL_NDX_TICKERS",
        "NVDA,AVGO,MSFT,AAPL,GOOGL,AMZN,META,TSLA,LLY,ASML,COST,AMD,NFLX,"
        "PEP,ORCL,ADBE,CSCO,TXN,QCOM,INTU,AMGN,ISRG,TMUS,CMCSA,HON,"
        "PANW,VRSK,CDNS,ADP,SBUX,MU,BIIB,REGN,MDLZ,PYPL,MAR,LRCX,"
        "KLAC,SNPS,CTAS,CSX,PCAR,ROP,ANSS,CHRW,ODFL,FAST,EXC,WBA",
    )
    tickers = [t.strip() for t in tickers_env.split(",") if t.strip()]

    data = yf.download(
        tickers=tickers,
        period="5d",
        interval="1h",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    signals: list[dict] = []
    spy = yf.Ticker("SPY").history(period="5d", interval="1h", auto_adjust=True)
    spy_retn = 0.0
    if not spy.empty and len(spy) >= 2:
        spy_retn = float((spy["Close"].iloc[-1] / spy["Close"].iloc[0]) - 1.0)

    if spy_retn > 0.004:
        regime, emoji = "BULL", "🟢"
    elif spy_retn < -0.004:
        regime, emoji = "BEAR", "🔴"
    else:
        regime, emoji = "CHOP", "🟡"

    for t in tickers:
        try:
            df = data[t].dropna()
        except Exception:
            continue
        if df.empty or len(df) < 5:
            continue
        close = df["Close"]
        last = float(close.iloc[-1])
        sma = float(close.rolling(10).mean().iloc[-1])
        atr_pct = float((close.pct_change().std() or 0.0) * (last * 0.01))
        if last <= 0 or sma <= 0:
            continue
        # Simple momentum signal: above 10-period SMA, ATR-based SL/TP.
        if last > sma * 1.001:
            direction = "LONG"
            entry = last
            atr = max(atr_pct, entry * 0.005)
            sl = round(entry - atr * 1.5, 2)
            tp = round(entry + atr * 2.5, 2)
            rr = round((tp - entry) / max(entry - sl, 0.0001), 2)
            signals.append(
                {
                    "ticker": t,
                    "direction": direction,
                    "price": round(entry, 2),
                    "sl": sl,
                    "tp": tp,
                    "rr": rr,
                }
            )
        elif last < sma * 0.999:
            direction = "SHORT"
            entry = last
            atr = max(atr_pct, entry * 0.005)
            sl = round(entry + atr * 1.5, 2)
            tp = round(entry - atr * 2.5, 2)
            rr = round((entry - tp) / max(sl - entry, 0.0001), 2)
            signals.append(
                {
                    "ticker": t,
                    "direction": direction,
                    "price": round(entry, 2),
                    "sl": sl,
                    "tp": tp,
                    "rr": rr,
                }
            )

    return {
        "scanned_at": _now(),
        "source": "yfinance",
        "regime": regime,
        "regime_emoji": emoji,
        "spy_5d_return": round(spy_retn, 4),
        "signals": signals,
        "error": None,
    }


def main() -> int:
    payload: dict
    try:
        tv = try_tv_mcp()
        if tv is not None:
            payload = tv
        else:
            payload = yfinance_scan()
    except Exception as exc:
        payload = _empty_payload(error=f"{type(exc).__name__}: {exc}")
        traceback.print_exc(file=sys.stderr)

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())