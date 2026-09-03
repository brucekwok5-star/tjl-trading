#!/usr/bin/env python3
"""D-TAT US Scanner — Yahoo Finance, 5-min bars (or last trading day if weekend)."""
import yfinance as yf
import pandas as pd
from datetime import date as dt_date, timedelta
from zoneinfo import ZoneInfo
import json

ET = ZoneInfo('America/New_York')
TP = 0.382; RR = 2.0; OR = 0.25

STOCKS = [
    ("AAPL","苹果"),("AMAT","应用材料"),("AMD","美国超微"),("AMGN","安进"),
    ("AMZN","亚马逊"),("APO","阿波罗"),("ASTS","AST SpaceMobile"),
    ("AVGO","博通"),("BA","波音"),("BABA","阿里巴巴"),("BAC","美国银行"),
    ("BEKE","贝壳"),("BRK-B","伯克希尔-B"),("CBRS","Cerebras"),
    ("CCTL","城堡证券"),("COIN","Coinbase"),("CRCL","Circle"),
    ("EL","雅诗兰黛"),("FCX","麦克莫兰铜金"),("FDX","联邦快递"),
    ("GDX","黄金矿业ETF"),("GLD","黄金ETF"),("GOOG","谷歌-C"),
    ("GOOGL","谷歌-A"),("HOOD","Robinhood"),("HYG","高收益债ETF"),
    ("IBIT","比特币ETF"),("ICE","洲际交易所"),("INTC","英特尔"),
    ("IREN","IREN Ltd"),("IWM","罗素2000ETF"),("JPM","摩根大通"),
    ("LITE","Lumentum"),("LLY","礼来"),("LQD","投资级债ETF"),
    ("META","Meta"),("MKTX","MarketAxess"),("MRK","默沙东"),
    ("MRNA","Moderna"),("MRVL","迈威尔"),("MSFT","微软"),
    ("MSTR","Strategy"),("MU","美光"),("NBIS","NEBIUS"),
    ("NTES","网易"),("NVDA","英伟达"),("ORCL","甲骨文"),
    ("PLTR","Palantir"),("QQQ","纳指ETF"),("ROST","罗斯百货"),
    ("SKHY","SK海力士"),("SMH","半导体ETF"),("SNDK","闪迪"),
    ("SOXL","3X多半导"),("SOXS","3X空半导"),("SOXX","半导体ETF"),
    ("SPCX","SpaceX"),("SPY","标普ETF"),("STX","希捷"),
    ("TQQQ","3X多纳指"),("TSM","台积电"),("TSLA","特斯拉"),
    ("UAL","联合航空"),("VOO","标普500ETF"),("WMT","沃尔玛"),
    ("XOM","埃克森美孚"),
]

def _last_trading_day():
    today = dt_date.today()
    wd = today.weekday()
    if wd < 5:
        return today
    # Sat=5, Sun=6
    return today - timedelta(days=1 if wd == 5 else 2)

def get_5m_bars(symbol):
    """Get first 3 x 5-min bars of last trading day."""
    df = yf.download(symbol, period='5d', interval='5m', auto_adjust=True, keepna=False, progress=False)
    if df is None or len(df) == 0:
        return None, 'no_data'
    # Unwrap MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Index to ET-aware datetime
    df.index = pd.to_datetime(df.index).tz_convert(ET)
    # Target: first 3 bars of last trading day
    last_day = _last_trading_day()
    day_start = pd.Timestamp(last_day, tz=ET) + pd.Timedelta(hours=9, minutes=30)
    # Remove tz for comparison with tz-naive df index
    day_start_naive = day_start.tz_localize(None)
    df_naive = df.copy()
    df_naive.index = df_naive.index.tz_localize(None)
    bars = df_naive[df_naive.index >= day_start_naive]
    if len(bars) < 3:
        return None, 'insufficient_bars'
    return bars.head(3), None

def get_daily_atr(symbol):
    df = yf.download(symbol, period='3mo', interval='1d', auto_adjust=True, keepna=False, progress=False)
    if df is None or len(df) < 15:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    h = df['High'].astype(float).values
    l = df['Low'].astype(float).values
    c = df['Close'].astype(float).values
    tr = pd.concat([
        pd.Series(h - l),
        pd.Series(abs(h[1:] - c[:-1])),
        pd.Series(abs(l[1:] - c[:-1]))
    ], axis=1).max(axis=1).values
    return float(pd.Series(tr).iloc[-14:].mean())

def dtat(c, o, h, l, a14):
    rng = h - l
    if rng < a14 * OR:
        return None
    dir_ = 'LONG' if c < o else 'SHORT'
    entry = l if dir_ == 'LONG' else h
    tp = round(l + rng * TP, 2) if dir_ == 'LONG' else round(h - rng * TP, 2)
    sl = round(entry - (tp - entry) / RR, 2) if dir_ == 'LONG' else round(entry + (entry - tp) / RR, 2)
    win_pct = round(abs(tp - entry) / entry * 100, 2)
    return {'dir': dir_, 'entry': entry, 'tp': tp, 'sl': sl, 'win_pct': win_pct, 'rng': rng}

def main():
    scan_date = _last_trading_day()
    longs, shorts, errs = [], [], []
    for symbol, name in STOCKS:
        try:
            a14 = get_daily_atr(symbol)
            if a14 is None:
                errs.append((symbol, name, 'no_atr'))
                continue
            bars, err = get_5m_bars(symbol)
            if err:
                errs.append((symbol, name, err))
                continue
            o = float(bars.iloc[0]['Open'])
            h = float(bars['High'].max())
            l = float(bars['Low'].min())
            c = float(bars.iloc[-1]['Close'])
            res = dtat(c, o, h, l, a14)
            if res is None:
                errs.append((symbol, name, 'low_liq'))
                continue
            res['symbol'] = symbol
            res['name'] = name
            res['cur'] = c
            res['a14'] = a14
            if res['dir'] == 'LONG':
                longs.append((symbol, res))
            else:
                shorts.append((symbol, res))
        except Exception as e:
            errs.append((symbol, name, str(e)[:40]))

    longs.sort(key=lambda x: -x[1]['rng'])
    shorts.sort(key=lambda x: -x[1]['rng'])

    print(f'\n=== D-TAT US Scan — {scan_date} ===')
    print(f'Total: {len(STOCKS)} | LONG: {len(longs)} | SHORT: {len(shorts)} | Errors: {len(errs)}')
    print(f'\nLONG ({len(longs)}):')
    for sym, d in longs:
        print(f"  {sym:<8} {d['name']:<12} E={d['entry']:>9.2f} TP={d['tp']:>9.2f} SL={d['sl']:>9.2f} Win%={d['win_pct']:>5.1f}% R={d['rng']:>8.2f} Cur={d['cur']:>9.2f}")
    print(f'\nSHORT ({len(shorts)}):')
    for sym, d in shorts:
        print(f"  {sym:<8} {d['name']:<12} E={d['entry']:>9.2f} TP={d['tp']:>9.2f} SL={d['sl']:>9.2f} Win%={d['win_pct']:>5.1f}% R={d['rng']:>8.2f} Cur={d['cur']:>9.2f}")
    if errs:
        print(f'\nErrors ({len(errs)}): {[(s,n,e) for s,n,e in errs[:15]]}')

    with open('/tmp/us_scan_results.json', 'w') as f:
        json.dump({'longs': longs, 'shorts': shorts, 'errs': errs, 'scan_date': str(scan_date)}, f)
    print('\nSaved to /tmp/us_scan_results.json')

if __name__ == '__main__':
    main()
