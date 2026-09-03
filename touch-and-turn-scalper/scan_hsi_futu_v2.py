#!/usr/bin/env python3
"""D-TAT HK Scan via Futu OpenD v2 — using updated API."""
from futu import *
import pandas as pd
from datetime import date as dt_date, datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

HKT = ZoneInfo('Asia/Hong_Kong')
ET = ZoneInfo("America/New_York")

# Settings
TP_LEVEL = 0.382
RR_RATIO = 2.0
OR_PCT = 0.25  # Opening range % of ATR

# HK Stock list (top 50 by market cap)
HK_STOCKS = [
    ("HK.00700", "騰訊控股"),
    ("HK.00939", "建設銀行"),
    ("HK.00981", "中芯國際"),
    ("HK.00005", "滙豐控股"),
    ("HK.00388", "香港交易所"),
    ("HK.02628", "中國人壽"),
    ("HK.00992", "聯想集團"),
    ("HK.00386", "中國石化"),
    ("HK.00857", "中國石油"),
    ("HK.00883", "中海油"),
    ("HK.00175", "吉利汽車"),
    ("HK.00762", "中國聯通"),
    ("HK.00688", "中國海外"),
    ("HK.01810", "小米集團"),
    ("HK.09988", "阿里巴巴"),
    ("HK.03690", "美團點評"),
    ("HK.02269", "商湯科技"),
    ("HK.01024", "快手"),
    ("HK.02318", "中國平安"),
    ("HK.02333", "雅居樂"),
    ("HK.01171", "華能水電"),
    ("HK.00267", "中國鐵建"),
    ("HK.06808", "融創中國"),
    ("HK.03968", "招商銀行"),
    ("HK.00101", "恒隆地產"),
    ("HK.00016", "新鴻基地產"),
    ("HK.00012", "恒基地產"),
    ("HK.06677", "農夫山泉"),
    ("HK.02238", "中國太保"),
    ("HK.02690", "石藥集團"),
    ("HK.06618", "京東健康"),
    ("HK.01888", "中國燃氣"),
    ("HK.01928", "周大福"),
    ("HK.01787", "山東黃金"),
    ("HK.00960", "龍湖集團"),
    ("HK.00178", "大唐新能源"),
    ("HK.06098", "海底撈"),
    ("HK.06186", "中國羽毛球"),
    ("HK.01919", "中遠海運"),
    ("HK.01368", "綠城服務"),
    ("HK.02196", "滔搏體育"),
    ("HK.03883", "中國鐵塔"),
    ("HK.06110", "聯通A股"),
    ("HK.06886", "金斯瑞"),
    ("HK.00011", "恒生銀行"),
    ("HK.03328", "交通銀行"),
    ("HK.02314", "蘇黎世保險"),
    ("HK.01359", "廣汽集團"),
    ("HK.00753", "中國國航"),
    ("HK.01088", "中國神華"),
]


def fetch_ohlcv(symbol, days=30):
    """Fetch OHLCV data for a symbol using Futu OpenD."""
    ctx = None
    try:
        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        end_date = dt_date.today()
        start_date = end_date - timedelta(days=days + 10)

        ret, data, page_key = ctx.request_history_kline(
            symbol,
            start=str(start_date),
            end=str(end_date),
            ktype=KLType.K_DAY,
            max_count=100
        )

        if ret != 0 or data is None or data.empty:
            return None

        # Rename columns to standard names
        data = data.rename(columns={
            'time_key': 'date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        })
        return data

    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None
    finally:
        if ctx:
            ctx.close()


def fetch_today_5m(symbol):
    """Fetch today's 5-min data."""
    ctx = None
    try:
        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

        ret, data, page_key = ctx.request_history_kline(
            symbol,
            start=str(dt_date.today()),
            end=str(dt_date.today()),
            ktype=KLType.K_5M,
            max_count=100
        )

        if ret != 0 or data is None or data.empty:
            return None

        data = data.rename(columns={
            'time_key': 'time',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        })
        return data

    except Exception as e:
        print(f"Error fetching 5m {symbol}: {e}")
        return None
    finally:
        if ctx:
            ctx.close()


def get_first_candle_15m(df_5m):
    """Get first 15-min candle (09:30-09:45 HK time)."""
    if df_5m is None or df_5m.empty:
        return None
    try:
        # Filter for first 15 minutes (09:30-09:45)
        df_5m['hour'] = pd.to_datetime(df_5m['time']).dt.hour
        df_5m['minute'] = pd.to_datetime(df_5m['time']).dt.minute
        bars = df_5m[(df_5m['hour'] == 9) & (df_5m['minute'] < 45)].head(3)

        if bars.empty:
            return None

        return (
            float(bars.iloc[0]["Open"]),
            float(bars["High"].max()),
            float(bars["Low"].min()),
            float(bars.iloc[-1]["Close"]),
        )
    except Exception as e:
        print(f"Error getting first candle: {e}")
        return None


def analyze_hk_stock(symbol, name):
    """Analyze a single HK stock."""
    # Get 30 days daily data for ATR
    df_daily = fetch_ohlcv(symbol, days=30)
    if df_daily is None or len(df_daily) < 15:
        return {"symbol": symbol, "name": name, "error": "no daily data"}

    # Calculate ATR(14)
    try:
        df_daily['High'] = pd.to_numeric(df_daily['High'], errors='coerce')
        df_daily['Low'] = pd.to_numeric(df_daily['Low'], errors='coerce')
        df_daily['Close'] = pd.to_numeric(df_daily['Close'], errors='coerce')

        high = df_daily['High']
        low = df_daily['Low']
        close = df_daily['Close']
        prev_close = close.shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)

        atr14 = float(tr.rolling(14).mean().iloc[-1])
    except Exception as e:
        return {"symbol": symbol, "name": name, "error": f"ATR calc failed: {e}"}

    # Get today's 5-min data
    df_5m = fetch_today_5m(symbol)
    candle = get_first_candle_15m(df_5m)

    if candle is None:
        return {
            "symbol": symbol,
            "name": name,
            "date": str(dt_date.today()),
            "atr14": round(atr14, 2),
            "action": "NO_DATA",
            "note": "No 5-min data yet"
        }

    open_, high_, low_, close_ = candle
    threshold = atr14 * OR_PCT
    candle_range = round(high_ - low_, 4)
    is_liq = candle_range >= threshold

    if not is_liq:
        return {
            "symbol": symbol,
            "name": name,
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

    # Direction: red (close < open) = LONG, green = SHORT
    direction = "LONG" if close_ < open_ else "SHORT"
    entry = low_ if direction == "LONG" else high_
    tp = round(low_ + (high_ - low_) * TP_LEVEL, 4)
    sl_dist = abs(tp - entry) / RR_RATIO
    sl = round(entry - sl_dist, 4) if direction == "LONG" else round(entry + sl_dist, 4)

    return {
        "symbol": symbol,
        "name": name,
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
    now_hk = datetime.now(HKT).strftime('%H:%M')
    print(f"D-TAT HK Scan v2 — {today} (HK: {now_hk})")
    print(f"Scanning {len(HK_STOCKS)} HK stocks...\n")

    setups, skips, errors = [], [], []

    # Process each stock
    for symbol, name in HK_STOCKS:
        result = analyze_hk_stock(symbol, name)
        print(f"{symbol} {name}: {result.get('action', 'ERROR')}")

        if result.get("error"):
            errors.append(result)
        elif result["action"] == "SKIP":
            skips.append(result)
        elif result["action"] == "SETUP_FOUND":
            setups.append(result)

    total = len(setups) + len(skips) + len(errors)
    print(f"\n{'='*70}")
    print(f"{'D-TAT HK SCAN v2':>35}  {today}")
    print(f"{'='*70}")
    print(f"Total: {total}  |  ✅ Setups: {len(setups)}  |  ⏭️ Skipped: {len(skips)}  |  ❌ Errors: {len(errors)}")

    if setups:
        longs = sorted([s for s in setups if s["direction"] == "LONG"], key=lambda x: -x["candle_range"])
        shorts = sorted([s for s in setups if s["direction"] == "SHORT"], key=lambda x: -x["candle_range"])

        if longs:
            print(f"\n🟢 LONG ({len(longs)} setups):")
            for s in longs:
                print(f"  {s['symbol']} {s['name']}: Entry ${s['entry']:.2f} TP ${s['tp']:.2f} SL ${s['sl']:.2f}")

        if shorts:
            print(f"\n🔴 SHORT ({len(shorts)} setups):")
            for s in shorts:
                print(f"  {s['symbol']} {s['name']}: Entry ${s['entry']:.2f} TP ${s['tp']:.2f} SL ${s['sl']:.2f}")


if __name__ == "__main__":
    main()
