#!/usr/bin/env python3
"""
D-TAT HK Scanner via Futu OpenD
Futu OpenD must be running (./FutuOpenD).
Connects, fetches daily ATR + 5-min live klines, runs D-TAT.
"""
import futu as ft
import pandas as pd
from datetime import datetime, date as dt_date, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

HKT = ZoneInfo('Asia/Hong_Kong')
TP_LEVEL = 0.382
RR = 2.0
OR_PCT = 0.25
OPEND_HOST = '127.0.0.1'
OPEND_PORT = 11111

STOCKS = [
    ('00001','长和'),('00012','恒基地产'),('00016','新鸿基地产'),('00027','银河娱乐'),
    ('00100','MINIMAX-W'),('00101','恒隆地产'),('00135','昆仑能源'),('00148','建滔集团'),
    ('00175','吉利汽车'),('00270','粤海投资'),('00288','万洲国际'),('00291','华润啤酒'),
    ('00305','五菱汽车'),('00338','上海石油化工'),('00340','潼关黄金'),
    ('00386','中国石化'),('00388','香港交易所'),('00425','敏实集团'),
    ('00641','恒富控股'),('00669','创科实业'),('00688','中国海外发展'),
    ('00700','腾讯控股'),('00762','中国联通'),('00780','同程旅行'),
    ('00815','中国白银集团'),('00857','中国石油'),('00883','中国海洋石油'),
    ('00939','建设银行'),('00981','中芯国际'),('00992','联想集团'),
    ('01024','快手-W'),('01070','TCL电子'),('01109','华润置地'),('01113','长实集团'),
    ('01171','兖矿能源'),('01211','比亚迪股份'),('01288','农业银行'),
    ('01347','华虹宏力'),('01378','中国宏桥'),('01398','工商银行'),
    ('01497','燕之屋'),('01548','金斯瑞生物科技'),('01698','腾讯音乐'),
    ('01768','鸣鸣很忙'),('01787','山东黄金'),('01801','信达生物'),
    ('01810','小米集团-W'),('01815','珠峰黄金'),('01818','招金矿业'),
    ('01876','百威亚太'),('01888','建滔积层板'),('01972','太古地产'),
    ('02013','微盟集团'),('02020','安踏体育'),('02057','中通快递-W'),
    ('02096','先声药业'),('02099','中国黄金国际'),('02149','贝克微'),
    ('02208','金风科技'),('02259','紫金黄金国际'),('02269','药明生物'),
    ('02313','申洲国际'),('02318','中国平安'),('02319','蒙牛乳业'),
    ('02338','潍柴动力'),('02359','药明康德'),('02388','中银香港'),
    ('02476','胜宏科技'),('02507','西锐'),('02513','智谱'),
    ('02525','禾赛-W'),('02556','迈富时'),('02571','赛目科技'),
    ('02601','中国太保'),('02628','中国人寿'),('02688','新奥能源'),
    ('02823','安硕A50'),('02883','中海油田服务'),('02899','紫金矿业'),
    ('03323','中国建材'),('03330','灵宝黄金'),('03360','远东宏信'),
    ('03606','福耀玻璃'),('03618','重庆农村商业银行'),('03661','圣邦股份'),
    ('03690','美团-W'),('03750','宁德时代'),('03759','康龙化成'),
    ('03888','金山软件'),('03908','中金公司'),('03939','万国黄金'),
    ('03968','招商银行'),('03986','兆易创新'),('03988','中国银行'),
    ('03993','洛阳钼业'),('06030','中信证券'),('06110','滔搏'),
    ('06160','百济神州'),('06166','剑桥科技'),('06181','老铺黄金'),
    ('06715','鲟龙科技'),('06809','澜起科技'),('06862','海底捞'),
    ('06869','长飞光纤光缆'),('06880','Momenta'),('06979','珍酒李渡'),
    ('06990','科伦博泰生物'),('07709','南方东英SK海力士'),('07747','南方两倍做多三星电子'),
    ('09618','京东集团-SW'),('09633','农夫山泉'),('09680','如祺出行'),
    ('09866','蔚来-SW'),('09878','汇通达网络'),('09888','百度集团-SW'),
    ('09903','天数智芯'),('09926','康方生物'),('09961','携程集团-S'),
    ('09973','奇瑞汽车'),('09987','百胜中国'),('09988','阿里巴巴-W'),
    ('09992','泡泡玛特'),('09999','网易'),
]


def calc_atr14(daily_df: pd.DataFrame) -> float | None:
    """Calculate ATR(14) from daily DataFrame."""
    h = daily_df['high'].values.astype(float)
    l = daily_df['low'].values.astype(float)
    c = daily_df['close'].values.astype(float)
    tr = pd.concat([
        pd.Series(h - l),
        pd.Series(abs(h[1:] - c[:-1])),
        pd.Series(abs(l[1:] - c[:-1])),
    ], axis=1).max(axis=1).values
    if len(tr) < 15:
        return None
    return float(pd.Series(tr).iloc[-14:].mean())


def fetch_daily_df(ctx, hk_sym: str, days=30) -> pd.DataFrame | None:
    """Get HK daily bars for ATR. Returns DataFrame or None."""
    start = (dt_date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    ret, df, err = ctx.request_history_kline(
        code=hk_sym, start=start, end='', ktype='K_DAY', autype='qfq'
    )
    if ret != 0 or df is None or len(df) < 15:
        return None
    # Parse time_key
    df = df.copy()
    df['time_key'] = pd.to_datetime(df['time_key']).dt.tz_localize(HKT)
    df = df.sort_values('time_key').reset_index(drop=True)
    return df


def fetch_5m_bars(ctx, hk_sym: str) -> pd.DataFrame | None:
    """Subscribe and get 5-min klines. Returns DataFrame or None."""
    ret, err = ctx.subscribe([hk_sym], [ft.SubType.K_5M])
    if ret != 0:
        return None
    ret2, df = ctx.get_cur_kline(code=hk_sym, num=100, ktype='K_5M')
    if ret2 != 0 or df is None or df.empty:
        return None
    df = df.copy()
    df['time_key'] = pd.to_datetime(df['time_key']).dt.tz_localize(HKT)
    df = df.sort_values('time_key').reset_index(drop=True)
    return df


def analyze_stock(code: str, name: str, today: dt_date) -> tuple:
    """Analyze one stock. Returns (code, name, status, data)."""
    ctx = ft.OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    hk_sym = f'HK.{code}'

    # Daily bars for ATR
    daily_df = fetch_daily_df(ctx, hk_sym)
    if daily_df is None:
        ctx.close()
        return (code, name, 'no_daily', None)

    a14 = calc_atr14(daily_df)
    if a14 is None:
        ctx.close()
        return (code, name, 'no_atr', None)

    # 5-min bars for today's OR
    df5 = fetch_5m_bars(ctx, hk_sym)
    ctx.close()

    if df5 is None or df5.empty:
        return (code, name, 'no_5m', None)

    today_ts = pd.Timestamp(today, tz=HKT)
    today_start = today_ts + pd.Timedelta(hours=9, minutes=30)
    today_end   = today_ts + pd.Timedelta(hours=16, minutes=5)

    df_today = df5[(df5['time_key'] >= today_start) & (df5['time_key'] <= today_end)]
    bars = df_today[df_today['time_key'].dt.hour == 9].head(3)

    if len(bars) < 3:
        return (code, name, 'early', {'df_rows': len(df_today), 'bars_09': len(bars)})

    bars3 = bars.head(3)
    o = float(bars3.iloc[0]['open'])
    h = float(bars3['high'].max())
    l = float(bars3['low'].min())
    c = float(bars3.iloc[-1]['close'])
    rng = h - l
    thr = a14 * OR_PCT

    if rng < thr:
        return (code, name, 'low_liq', {'rng': rng, 'thr': thr, 'a14': a14})

    dir_ = 'LONG' if c < o else 'SHORT'
    entry = l if dir_ == 'LONG' else h
    tp = round(l + rng * TP_LEVEL, 2) if dir_ == 'LONG' else round(h - rng * TP_LEVEL, 2)
    sl = round(entry - (tp - entry) / RR, 2) if dir_ == 'LONG' else round(entry + (entry - tp) / RR, 2)
    win_pct = round(abs(tp - entry) / entry * 100, 2)
    day_h = float(df5['high'].max())
    day_l = float(df5['low'].min())
    close_d = float(df5.iloc[-1]['close'])

    return (code, name, dir_, {
        'entry': entry, 'tp': tp, 'sl': sl,
        'rng': rng, 'win_pct': win_pct,
        'day_h': day_h, 'day_l': day_l, 'close_d': close_d,
        'atr14': a14, 'thr': thr,
    })


def run_scan(today: dt_date) -> tuple:
    longs, shorts, errors = [], [], []

    for code, name in STOCKS:
        result = analyze_stock(code, name, today)
        code_n, name_n, status, data = result
        if status in ('LONG', 'SHORT'):
            (longs if status == 'LONG' else shorts).append((code_n, name_n, data))
        else:
            errors.append(result)

    longs.sort(key=lambda x: -x[2]['rng'])
    shorts.sort(key=lambda x: -x[2]['rng'])
    return longs, shorts, errors


def print_results(today: dt_date, longs, shorts, errors):
    now_hkt = datetime.now(HKT).strftime('%H:%M HKT')
    print(f'D-TAT HK Scan (Futu OpenD)  {today}  {now_hkt}')
    print(f'Setups: {len(longs)+len(shorts)}  |  Skipped/Errors: {len(errors)}')
    print()
    if longs:
        print(f'LONG ({len(longs)}):')
        for code, name, d in longs:
            print(f"  {code:<6} {name[:12]:<14} E={d['entry']:>8.2f} TP={d['tp']:>8.2f} SL={d['sl']:>8.2f} Win%={d['win_pct']:>5.1f}% R={d['rng']:>7.2f}  H={d['day_h']:>8.2f}  C={d['close_d']:>8.2f}")
    print()
    if shorts:
        print(f'SHORT ({len(shorts)}):')
        for code, name, d in shorts:
            print(f"  {code:<6} {name[:12]:<14} E={d['entry']:>8.2f} TP={d['tp']:>8.2f} SL={d['sl']:>8.2f} Win%={d['win_pct']:>5.1f}% R={d['rng']:>7.2f}  L={d['day_l']:>8.2f}  C={d['close_d']:>8.2f}")
    print()
    if errors:
        early = [(c, n, s, d) for c, n, s, d in errors if s == 'early']
        low_liq = [(c, n, s, d) for c, n, s, d in errors if s == 'low_liq']
        other = [(c, n, s) for c, n, s, d in errors if s not in ('early', 'low_liq')]
        if early: print(f'  Early (no 3 bars yet): {[c for c,n,s,d in early]}')
        if low_liq: print(f'  Low liq ({len(low_liq)}): {[c for c,n,s,d in low_liq[:5]]}...')
        if other: print(f'  No data: {[c for c,n,s in other]}')


if __name__ == '__main__':
    today = dt_date.today()
    longs, shorts, errors = run_scan(today)
    print_results(today, longs, shorts, errors)
