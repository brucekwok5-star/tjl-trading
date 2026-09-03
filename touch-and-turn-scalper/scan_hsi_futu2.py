#!/usr/bin/env python3
"""D-TAT HK Full Scan via Futu OpenD — 169 stocks."""
import futu as ft
import pandas as pd
from datetime import date as dt_date
from zoneinfo import ZoneInfo

HKT = ZoneInfo('Asia/Hong_Kong')

STOCKS_RAW = """00001	長和
00005	滙豐控股
00012	恒基地產
00016	新鴻基地產
00020	商湯-W
00027	銀河娛樂
00038	第一拖拉機股份
00100	MINIMAX-W
00101	恒隆地產
00123	越秀地產
00135	昆侖能源
00148	建滔集團
00168	青島啤酒股份
00175	吉利汽車
00270	粵海投資
00288	萬洲國際
00291	華潤啤酒
00293	國泰航空
00305	五菱汽車
00338	上海石油化工股份
00340	潼關黃金
00386	中國石油化工股份
00388	香港交易所
00425	敏實集團
00641	恒富控股
00669	創科實業
00688	中國海外發展
00700	騰訊控股
00762	中國聯通
00780	同程旅行
00815	中國白銀集團
00817	中國金茂
00857	中國石油股份
00883	中國海洋石油
00939	建設銀行
00960	龍湖集團
00981	中芯國際
00992	聯想集團
01024	快手-W
01070	TCL電子
01093	石藥集團
01109	華潤置地
01113	長實集團
01171	兗礦能源
01177	中國生物製藥
01211	比亞迪股份
01288	農業銀行
01299	友邦保險
01347	華虹宏力
01368	特步國際
01378	中國宏橋
01398	工商銀行
01458	周黑鴨
01497	燕之屋
01519	極兔速遞-W
01548	金斯瑞生物科技
01698	騰訊音樂-SW
01768	鳴鳴很忙
01787	山東黃金
01801	信達生物
01810	小米集團-W
01815	珠峰黃金
01876	百威亞太
01879	曦智科技-P
01888	建滔積層板
01908	建發國際集團
01910	新秀麗
01918	融創中國
01929	周大福
01952	雲頂新耀
01972	太古地產
01997	九龍倉置業
02005	石四藥集團
02013	微盟集團
02015	理想汽車-W
02018	瑞聲科技
02020	安踏體育
02057	中通快遞-W
02096	先聲藥業
02099	中國黃金國際
02149	貝克微
02162	康諾亞-B
02196	復星醫藥
02208	金風科技
02228	晶泰控股
02256	和譽-B
02259	紫金黃金國際
02269	藥明生物
02313	申洲國際
02318	中國平安
02319	蒙牛乳業
02328	中國財險
02331	李寧
02338	濰柴動力
02359	藥明康德
02388	中銀香港
02423	貝殼-W
02476	勝宏科技
02507	西銳
02513	智譜
02525	禾賽-W
02556	邁富時
02558	中銀航空租賃
02571	賽目科技
02601	中國太保
02628	中國人壽
02669	中海物業
02688	新奧能源
02823	安碩A50
02883	中海油田服務
02899	紫金礦業
03033	南方恒生科技
03288	海天味業
03296	華勤技術
03323	中國建材
03328	交通銀行
03330	靈寶黃金
03360	遠東宏信
03606	福耀玻璃
03618	重慶農村商業銀行
03661	聖邦股份
03690	美團-W
03750	寧德時代
03759	康龍化成
03858	佳鑫國際資源
03888	金山軟件
03899	中集安瑞科
03900	綠城中國
03908	中金公司
03968	招商銀行
03978	卓越教育集團
03986	兆易創新
03988	中國銀行
03993	洛陽鉬業
06030	中信証券
06110	滔搏
06158	正榮地產
06160	百濟神州
06166	劍橋科技
06181	老鋪黃金
06185	康希諾生物
06683	巨星傳奇
06715	鱘龍科技
06809	瀾起科技
06862	海底撈
06869	長飛光纖光纜
06979	珍酒李渡
06990	科倫博泰生物
07226	南方兩倍做多恆科
07552	南方兩倍做空恒科
07709	南方東英SK海力士每日槓桿最多(2x)產品
07747	南方兩倍做多三星電子
09618	京東集團-SW
09626	嗶哩嗶哩-W
09633	農夫山泉
09680	如祺出行
09698	萬國數據-SW
09866	蔚來-SW
09868	小鵬集團-W
09878	匯通達網絡
09888	百度集團-SW
09899	網易雲音樂
09926	康方生物
09961	攜程集團-S
09973	奇瑞汽車
09987	百勝中國
09988	阿里巴巴-W
09992	泡泡瑪特
09999	網易"""

STOCKS = []
for line in STOCKS_RAW.strip().split('\n'):
    parts = line.split('\t')
    raw = parts[0].lstrip('0') or '0'
    code = f'HK.{raw.zfill(5)}'
    name = parts[1]
    STOCKS.append((code, name))

TP = 0.382; RR = 2.0; OR = 0.25

def fetch_dailyATR(ctx, code):
    """Get 3mo daily kline for ATR(14)."""
    ret, data, page_key = ctx.request_history_kline(code, start='2026-05-01', end='2026-08-21',
                                           ktype=ft.KLType.K_DAY, max_count=500)
    if ret != 0 or data is None or len(data) < 15:
        return None
    h = data['high'].astype(float).values
    l = data['low'].astype(float).values
    c = data['close'].astype(float).values
    tr = pd.concat([pd.Series(h-l), pd.Series(abs(h[1:]-c[:-1])), pd.Series(abs(l[1:]-c[:-1]))], axis=1).max(axis=1).values
    return float(pd.Series(tr).iloc[-14:].mean())

def fetch_cur_price(ctx, code):
    """Get today's close (or last close if not yet closed)."""
    ret, data = ctx.get_cur_kline(code, num=1, ktype=ft.KLType.K_1M)
    if ret == 0 and data is not None and len(data) > 0:
        return float(data.iloc[-1]['close'])
    return None

def fetch_5m_today(ctx, code):
    """Get today's 5-min bars (all today, reconstruct the 09:30/35/40 bars)."""
    today_str = '2026-08-21'
    ret, data, page_key = ctx.request_history_kline(code, start=today_str, end='2026-08-22',
                                           ktype=ft.KLType.K_5M)
    if ret != 0 or data is None or len(data) < 3:
        return None
    data = data.copy()
    data['time_key'] = pd.to_datetime(data['time_key']).dt.tz_localize(HKT)
    data = data.sort_values('time_key').reset_index(drop=True)
    today_start = pd.Timestamp('2026-08-21', tz=HKT).normalize() + pd.Timedelta(hours=9, minutes=30)
    bars = data[data['time_key'] >= today_start]
    if len(bars) < 3:
        return None
    return bars.head(3)

def analyze_stock(ctx, code, name):
    a14 = fetch_dailyATR(ctx, code)
    if a14 is None: return None, 'no_atr'

    bars = fetch_5m_today(ctx, code)
    if bars is None: return None, 'no_5m'

    o = float(bars.iloc[0]['open'])
    h = float(bars['high'].max())
    l = float(bars['low'].min())
    c = float(bars.iloc[-1]['close'])
    rng = h - l

    if rng < a14 * OR: return None, 'low_liq'

    cur = fetch_cur_price(ctx, code)

    dir_ = 'LONG' if c < o else 'SHORT'
    entry = l if dir_ == 'LONG' else h
    tp = round(l + rng * TP, 2) if dir_ == 'LONG' else round(h - rng * TP, 2)
    sl = round(entry - (tp - entry) / RR, 2) if dir_ == 'LONG' else round(entry + (entry - tp) / RR, 2)
    win_pct = round(abs(tp - entry) / entry * 100, 2)

    return {
        'name': name, 'entry': entry, 'tp': tp, 'sl': sl,
        'win_pct': win_pct, 'rng': rng, 'cur': cur, 'a14': a14
    }, dir_

def main():
    print(f'Connecting to Futu OpenD...')
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)

    longs, shorts, errs = [], [], []

    for i, (code, name) in enumerate(STOCKS):
        print(f'[{i+1}/{len(STOCKS)}] {code} ({name})...', flush=True)
        res, s = analyze_stock(ctx, code, name)
        if res:
            (longs if s == 'LONG' else shorts).append((code, res))
        else:
            errs.append((code, name, s))

    ctx.close = lambda: None  # prevent blocking stop()

    longs.sort(key=lambda x: -x[1]['rng'])
    shorts.sort(key=lambda x: -x[1]['rng'])

    print(f'\n=== D-TAT HK Scan — Aug 21 ===')
    print(f'Total: {len(STOCKS)} | LONG: {len(longs)} | SHORT: {len(shorts)} | Errors: {len(errs)}')
    print(f'\nLONG ({len(longs)}):')
    for code, d in longs:
        print(f"  {code} {d['name']:<14} E={d['entry']:>8.2f} TP={d['tp']:>8.2f} SL={d['sl']:>8.2f} Win%={d['win_pct']:>5.1f}% R={d['rng']:>7.2f} Cur={d['cur'] or '?':>8}")
    print(f'\nSHORT ({len(shorts)}):')
    for code, d in shorts:
        print(f"  {code} {d['name']:<14} E={d['entry']:>8.2f} TP={d['tp']:>8.2f} SL={d['sl']:>8.2f} Win%={d['win_pct']:>5.1f}% R={d['rng']:>7.2f} Cur={d['cur'] or '?':>8}")
    if errs:
        print(f'\nErrors: {[(c,n,s) for c,n,s in errs[:10]]}')

    import json, os
    os.makedirs('/tmp', exist_ok=True)
    with open('/tmp/hk_scan_results.json', 'w') as f:
        json.dump({'longs': longs, 'shorts': shorts, 'errs': [(c,n,s) for c,n,s in errs]}, f)

if __name__ == '__main__':
    main()
