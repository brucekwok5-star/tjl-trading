#!/usr/bin/env python3
"""D-TAT HSI (香港恒生指數成分股) 實時掃描器."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as dt_date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

HKT        = ZoneInfo("Asia/Hong_Kong")
ET         = ZoneInfo("America/New_York")
TP_LEVEL   = 0.382
RR_RATIO   = 2.0
OR_PCT     = 0.25
MAX_WORKERS = 20

# HSI 成分股（截至 2024-2025 主要名單）
HSI_TICKERS = [
    "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK",
    "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0027.HK",
    "0066.HK", "0101.HK", "0175.HK", "0269.HK", "0289.HK",
    "0291.HK", "0318.HK", "0386.HK", "0388.HK", "0449.HK",
    "0669.HK", "0688.HK", "0738.HK", "0823.HK", "0859.HK",
    "0861.HK", "0881.HK", "0902.HK", "0941.HK", "0988.HK",
    "1000.HK", "1024.HK", "1038.HK", "1093.HK", "1109.HK",
    "1177.HK", "1186.HK", "1211.HK", "1249.HK", "1299.HK",
    "1347.HK", "1378.HK", "1686.HK", "1699.HK", "1755.HK",
    "1766.HK", "1772.HK", "1797.HK", "1810.HK", "1876.HK",
    "1900.HK", "1928.HK", "1972.HK", "2018.HK", "2068.HK",
    "2096.HK", "2111.HK", "2138.HK", "2202.HK", "2238.HK",
    "2269.HK", "2313.HK", "2314.HK", "2319.HK", "2338.HK",
    "2359.HK", "2382.HK", "2388.HK", "2600.HK", "2611.HK",
    "2622.HK", "2689.HK", "2899.HK", "3690.HK", "3692.HK",
    "3968.HK", "3988.HK", "6030.HK", "6060.HK", "6618.HK",
    "6628.HK", "6699.HK", "6808.HK", "6823.HK", "6837.HK",
    "6979.HK", "6998.HK", "7000.HK", "7008.HK", "7070.HK",
    "7261.HK", "7536.HK", "7738.HK", "7799.HK", "8028.HK",
    "8088.HK", "8233.HK", "8257.HK", "8285.HK", "8303.HK",
    "8354.HK", "8558.HK", "8798.HK", "8808.HK", "8839.HK",
    "8869.HK", "9002.HK", "9036.HK", "9048.HK", "9068.HK",
    "9081.HK", "9098.HK", "9112.HK", "9122.HK", "9188.HK",
    "9206.HK", "9220.HK", "9259.HK", "9287.HK", "9300.HK",
    "9347.HK", "9375.HK", "9399.HK", "9446.HK", "9466.HK",
    "9509.HK", "9557.HK", "9597.HK", "9602.HK", "9618.HK",
    "9633.HK", "9666.HK", "9688.HK", "9696.HK", "9709.HK",
    "9727.HK", "9740.HK", "9761.HK", "9779.HK", "9796.HK",
    "9808.HK", "9820.HK", "9848.HK", "9878.HK", "9886.HK",
    "9898.HK", "9906.HK", "9918.HK", "9928.HK", "9933.HK",
    "9956.HK", "9960.HK", "9971.HK", "9983.HK", "9988.HK",
    "9992.HK", "9997.HK",
]

# 主要藍籌股（常用，流動性最好）
MAJOR_TICKERS = [
    "0700.HK", "0941.HK", "1299.HK", "0998.HK",
    "2318.HK", "3328.HK", "3988.HK", "3968.HK",
    "0005.HK", "0006.HK", "0011.HK", "0016.HK",
    "0168.HK", "0175.HK", "0181.HK", "0269.HK",
    "0288.HK", "0291.HK", "0386.HK", "0669.HK",
    "0688.HK", "0762.HK", "0780.HK", "0823.HK",
    "0857.HK", "0861.HK", "0881.HK", "0902.HK",
    "0988.HK", "1093.HK", "1109.HK", "1177.HK",
    "1186.HK", "1211.HK", "1249.HK", "1347.HK",
    "1686.HK", "1755.HK", "1766.HK", "1772.HK",
    "1810.HK", "1876.HK", "1928.HK", "1972.HK",
    "2018.HK", "2068.HK", "2096.HK", "2111.HK",
    "2202.HK", "2313.HK", "2319.HK", "2338.HK",
    "2382.HK", "2600.HK", "2689.HK", "2899.HK",
    "3690.HK", "3692.HK", "6618.HK", "6628.HK",
    "6699.HK", "6837.HK", "6979.HK", "7000.HK",
    "7065.HK", "7070.HK", "7261.HK", "8028.HK",
    "8088.HK", "8233.HK", "8285.HK", "8558.HK",
    "8839.HK", "9036.HK", "9081.HK", "9220.HK",
    "9300.HK", "9399.HK", "9618.HK", "9633.HK",
    "9688.HK", "9808.HK", "9868.HK", "9906.HK",
    "9933.HK", "9956.HK", "9960.HK", "9988.HK",
    "9992.HK",
]


def fetch_today_5m(ticker_sym):
    """Fetch today's 5-min bars for HK ticker."""
    try:
        df = yf.download(
            ticker_sym, period="1d", interval="5m",
            auto_adjust=True, keepna=False, progress=False
        )
        if df.empty:
            return None
        df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_convert(HKT) if df.index.tz else df.tz_localize(HKT)
        return df
    except Exception:
        return None


def fetch_30d_daily(ticker_sym):
    """Fetch 30 days daily for ATR."""
    try:
        df = yf.download(
            ticker_sym, period="1mo", interval="1d",
            auto_adjust=True, keepna=False, progress=False
        )
        if df.empty:
            return None
        df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None


def get_first_candle_15m(df_5m):
    """Aggregate 09:30, 09:35, 09:40 bars into 15-min candle."""
    if df_5m is None or df_5m.empty:
        return None
    try:
        bars = df_5m[
            (df_5m.index.hour == 9) & (df_5m.index.minute < 45)
        ].head(3)
        if bars.empty:
            return None
        return (
            float(bars.iloc[0]["Open"]),
            float(bars["High"].max()),
            float(bars["Low"].min()),
            float(bars.iloc[-1]["Close"]),
        )
    except Exception:
        return None


def analyze_today_hk(symbol):
    """Analyze one HSI/HK ticker for today's D-TAT setup."""
    df_daily = fetch_30d_daily(symbol)
    if df_daily is None or len(df_daily) < 15:
        return {"symbol": symbol, "error": "no daily data"}

    # ATR(14)
    try:
        high = df_daily["High"]
        low  = df_daily["Low"]
        close = df_daily["Close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs()
        ], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])
    except Exception:
        return {"symbol": symbol, "error": "ATR calc failed"}

    df_5m = fetch_today_5m(symbol)
    candle = get_first_candle_15m(df_5m)
    if candle is None:
        return {
            "symbol": symbol,
            "date": str(dt_date.today()),
            "atr14": round(atr14, 2),
            "action": "NO_DATA",
            "note": "No 5-min data yet or not traded today"
        }

    open_, high_, low_, close_ = candle
    threshold    = atr14 * OR_PCT
    candle_range = round(high_ - low_, 4)
    is_liq       = candle_range >= threshold

    if not is_liq:
        return {
            "symbol": symbol,
            "date": str(dt_date.today()),
            "atr14": round(atr14, 2),
            "threshold": round(threshold, 2),
            "candle_range": round(candle_range, 2),
            "is_liquidity": False,
            "action": "SKIP",
            "candle_open": round(open_, 2),
            "candle_close": round(close_, 2),
            "direction": None,
            "entry": None, "tp": None, "sl": None,
        }

    direction = "LONG" if close_ < open_ else "SHORT"
    entry = low_ if direction == "LONG" else high_
    tp    = round(low_ + (high_ - low_) * TP_LEVEL, 4)
    sl_dist = abs(tp - entry) / RR_RATIO
    sl = round(entry - sl_dist, 4) if direction == "LONG" else round(entry + sl_dist, 4)

    return {
        "symbol": symbol,
        "date": str(dt_date.today()),
        "atr14": round(atr14, 2),
        "threshold": round(threshold, 2),
        "candle_range": round(candle_range, 2),
        "is_liquidity": True,
        "action": "SETUP_FOUND",
        "candle_open": round(open_, 2),
        "candle_close": round(close_, 2),
        "direction": direction,
        "entry": round(entry, 4),
        "tp": round(tp, 4),
        "sl": round(sl, 4),
        "rr_ratio": RR_RATIO,
    }


def main():
    today = dt_date.today()
    now_hkt = datetime.now(HKT)
    print(f"D-TAT HSI Live Scan  {today}  HKT {now_hkt.strftime('%H:%M')}")
    print(f"Scanning {len(MAJOR_TICKERS)} HK major tickers...\n")

    setups, skips, errors = [], [], []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(analyze_today_hk, sym): sym for sym in MAJOR_TICKERS}
        done = 0
        for fut in as_completed(futures):
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{len(MAJOR_TICKERS)} done...", flush=True)
            r = fut.result()
            if r is None or r.get("error"):
                errors.append(r or {"symbol": futures[fut], "error": "none"})
            elif r["action"] == "SKIP":
                skips.append(r)
            elif r["action"] == "SETUP_FOUND":
                setups.append(r)

    total = len(setups) + len(skips) + len(errors)
    print(f"\n{'='*85}")
    print(f"{'D-TAT HSI LIVE SCAN':>40}  {today}  HKT {now_hkt.strftime('%H:%M')}")
    print(f"{'='*85}")
    print(f"Total: {total}  |  Setups: {len(setups)}  |  Skipped: {len(skips)}  |  Errors: {len(errors)}")

    longs  = sorted([s for s in setups if s["direction"]=="LONG"],  key=lambda x: -x["candle_range"])
    shorts = sorted([s for s in setups if s["direction"]=="SHORT"], key=lambda x: -x["candle_range"])

    if longs:
        print(f"\n🟢 LONG ({len(longs)} setups)  — 红燭 (收低)，低位有撐，等反彈")
        print(f"  {'Code':<10} {'Entry':>9} {'TP':>9} {'SL':>9} {'ATR':>7} {'Range':>8} {'Thresh':>8}")
        print("  " + "-"*70)
        for s in longs:
            print(f"  {s['symbol']:<10} {s['entry']:>9.2f} {s['tp']:>9.2f} {s['sl']:>9.2f} {s['atr14']:>7.2f} {s['candle_range']:>8.2f} {s['threshold']:>8.2f}")

    if shorts:
        print(f"\n🔴 SHORT ({len(shorts)} setups)  — 绿燭 (收高)，高位有壓，等回落")
        print(f"  {'Code':<10} {'Entry':>9} {'TP':>9} {'SL':>9} {'ATR':>7} {'Range':>8} {'Thresh':>8}")
        print("  " + "-"*70)
        for s in shorts:
            print(f"  {s['symbol']:<10} {s['entry']:>9.2f} {s['tp']:>9.2f} {s['sl']:>9.2f} {s['atr14']:>7.2f} {s['candle_range']:>8.2f} {s['threshold']:>8.2f}")

    if setups:
        print(f"\n⚠️  逻辑：等价格回到 range low/high 再进埸，不要追价")
        print(f"⚠️  LONG = 红燭，进埸 = range low | SHORT = 绿燭，进埸 = range high")
        print(f"⚠️  TP = 38.2% 斐波那契回调 | SL = 2:1 R:R | 需 range >= ATR14 × 25%")


if __name__ == "__main__":
    main()
