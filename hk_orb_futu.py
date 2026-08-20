#!/usr/bin/env python3
"""
ORB 1:2 — HK Custom List via Futu OpenD (realtime-quote ORB)
Uses Futu real-time quotes for ORB calculation — no 15m history needed.
Run at 9:30 AM HKT, re-run with --verify at 4 PM for close results.
Usage:
  python3 hk_orb_futu.py                  # live scan (9:30 AM)
  python3 hk_orb_futu.py --verify         # verify today's close (4 PM+)
  python3 hk_orb_futu.py --date 2026-08-18 --verify  # verify past date
"""
import sys
import time
import argparse
from datetime import datetime, date

try:
    import futu as ft
    from futu.quote.open_quote_context import OpenQuoteContext, KLType, SubType
    ft.OpenQuoteContext = OpenQuoteContext
    ft.KLType = KLType
    ft.SubType = SubType
except ImportError:
    print("[ERROR] futu not installed: pip install futu")
    sys.exit(1)

HOST = '127.0.0.1'
PORT = 11111

TN = {
    'HK.00001': '长和',              'HK.00012': '恒基地产',        'HK.00016': '新鸿基地产',
    'HK.00027': '银河娱乐',          'HK.00038': '第一拖拉机',      'HK.00100': 'MINIMAX-W',
    'HK.00101': '恒隆地产',          'HK.00135': '昆仑能源',        'HK.00148': '建滔集团',
    'HK.00175': '吉利汽车',          'HK.00270': '粤海投资',        'HK.00288': '万洲国际',
    'HK.00291': '华润啤酒',          'HK.00305': '五菱汽车',        'HK.00338': '上海石油化工',
    'HK.00340': '潼关黄金',          'HK.00386': '中国石化',        'HK.00388': '香港交易所',
    'HK.00425': '敏实集团',          'HK.00641': '恒富控股',        'HK.00669': '创科实业',
    'HK.00688': '中国海外发展',       'HK.00700': '腾讯控股',         'HK.00762': '中国联通',
    'HK.00780': '同程旅行',          'HK.00815': '中国白银集团',     'HK.00857': '中国石油股份',
    'HK.00883': '中国海洋石油',       'HK.00939': '建设银行',         'HK.00981': '中芯国际',
    'HK.00992': '联想集团',          'HK.01024': '快手-W',           'HK.01070': 'TCL电子',
    'HK.01109': '华润置地',          'HK.01113': '长实集团',         'HK.01171': '兖矿能源',
    'HK.01211': '比亚迪股份',         'HK.01288': '农业银行',         'HK.01347': '华虹宏力',
    'HK.01378': '中国宏桥',          'HK.01398': '工商银行',         'HK.01497': '燕之屋',
    'HK.01548': '金斯瑞生物科技',     'HK.01698': '腾讯音乐',         'HK.01768': '鸣鸣很忙',
    'HK.01787': '山东黄金',          'HK.01801': '信达生物',         'HK.01810': '小米集团-W',
    'HK.01815': '珠峰黄金',          'HK.01818': '招金矿业',         'HK.01876': '百威亚太',
    'HK.01888': '建滔积层板',        'HK.01972': '太古地产',         'HK.02013': '微盟集团',
    'HK.02020': '安踏体育',          'HK.02057': '中通快递-W',       'HK.02096': '先声药业',
    'HK.02099': '中国黄金国际',       'HK.02149': '贝克微',           'HK.02208': '金风科技',
    'HK.02259': '紫金黄金国际',       'HK.02269': '药明生物',         'HK.02276': '康耐特光学',
    'HK.02313': '申洲国际',          'HK.02318': '中国平安',         'HK.02319': '蒙牛乳业',
    'HK.02338': '潍柴动力',          'HK.02359': '药明康德',         'HK.02388': '中银香港',
    'HK.02476': '胜宏科技',          'HK.02507': '西锐',             'HK.02513': '智谱',
    'HK.02525': '禾赛-W',           'HK.02556': '迈富时',           'HK.02571': '赛目科技',
    'HK.02601': '中国太保',          'HK.02628': '中国人寿',         'HK.02688': '新奥能源',
    'HK.02823': '安硕A50',          'HK.02883': '中海油田服务',     'HK.02899': '紫金矿业',
    'HK.03323': '中国建材',          'HK.03330': '灵宝黄金',         'HK.03360': '远东宏信',
    'HK.03606': '福耀玻璃',          'HK.03618': '重庆农村商业银行', 'HK.03661': '圣邦股份',
    'HK.03690': '美团-W',            'HK.03750': '宁德时代',         'HK.03759': '康龙化成',
    'HK.03888': '金山软件',          'HK.03908': '中金公司',         'HK.03939': '万国黄金',
    'HK.03968': '招商银行',          'HK.03986': '兆易创新',         'HK.03988': '中国银行',
    'HK.03993': '洛阳钼业',          'HK.06030': '中信证券',         'HK.06110': '滔搏',
    'HK.06160': '百济神州',          'HK.06166': '剑桥科技',         'HK.06181': '老铺黄金',
    'HK.06715': '鲟龙科技',          'HK.06809': '澜起科技',         'HK.06862': '海底捞',
    'HK.06869': '长飞光纤光缆',       'HK.06880': 'Momenta',          'HK.06979': '珍酒李渡',
    'HK.06990': '科伦博泰生物',       'HK.07709': '东英SK海力士2x',  'HK.07747': '南方两倍三星',
    'HK.09618': '京东集团-SW',       'HK.09633': '农夫山泉',         'HK.09680': '如祺出行',
    'HK.09866': '蔚来-SW',           'HK.09878': '汇通达网络',       'HK.09888': '百度集团-SW',
    'HK.09903': '天数智芯',          'HK.09926': '康方生物',         'HK.09961': '携程集团-S',
    'HK.09973': '奇瑞汽车',          'HK.09987': '百胜中国',         'HK.09988': '阿里巴巴-W',
    'HK.09992': '泡泡玛特',          'HK.09999': '网易',
}

WATCHLIST = list(TN.keys())


def connect():
    return ft.OpenQuoteContext(host=HOST, port=PORT)


def get_quotes(ctx, codes):
    """Subscribe and fetch real-time quotes. Returns dict {code: quote_dict}."""
    for code in codes:
        ctx.subscribe([code], [ft.SubType.QUOTE])
    time.sleep(1.5)
    quotes = {}
    for code in codes:
        ret, df = ctx.get_stock_quote([code])
        if ret != 0 or df is None or isinstance(df, str):
            continue
        for _, row in df.iterrows():
            quotes[code] = {
                'price':       float(row['last_price']),
                'prev_close':  float(row['prev_close_price']),
                'high_today':  float(row['high_price']),
                'low_today':   float(row['low_price']),
                'open_today':  float(row.get('open_price', row['prev_close_price'])),
                'volume':      int(row['volume']),
            }
    return quotes


def get_daily_df(ctx, code, count=60):
    """Get daily bars for HTF bias + ATR. Returns None on failure."""
    ret, df, msg = ctx.request_history_kline(
        code=code, ktype=ft.KLType.K_DAY, max_count=count
    )
    if ret != 0 or df is None or df.empty:
        return None
    return df


def scan(tickers, trade_date, verify=False):
    ctx = connect()
    print(f"ORB 1:2 — HK Custom | {trade_date}")
    t0 = time.time()

    # ── Step 1: Real-time quotes ────────────────────────────────────────────
    print(f"Fetching quotes for {len(tickers)} stocks ...")
    quotes = get_quotes(ctx, tickers)
    print(f"  {len(quotes)} quotes in {time.time()-t0:.1f}s")

    # ── Step 2: Daily bars for HTF bias + ATR ───────────────────────────────
    t1 = time.time()
    daily_data = {}
    for code in tickers:
        df = get_daily_df(ctx, code, count=60)
        if df is not None:
            daily_data[code] = df
    print(f"  {len(daily_data)} daily datasets in {time.time()-t1:.1f}s")

    # ── Step 3: ORB scan ───────────────────────────────────────────────────
    t2 = time.time()
    results = []

    for code in tickers:
        if code not in quotes:
            continue

        q = quotes[code]
        o = q['open_today']
        hi = q['high_today']
        lo = q['low_today']
        cp = q['price']

        if o <= 0 or hi <= 0 or lo <= 0:
            continue

        rng = hi - lo
        if rng < 0.005 * o:   # min 0.5% range
            continue

        orh = o + 0.40 * (hi - o)
        orl = o - 0.40 * (o - lo)

        d = 1 if cp > orh else (-1 if cp < orl else None)
        if d is None:
            continue

        # HTF bias from daily 20SMA
        bias = 0
        if code in daily_data:
            df = daily_data[code]
            if len(df) >= 20:
                closes = df['close'].astype(float).tail(20)
                sma = float(closes.mean())
                last = float(df['close'].iloc[-1])
                bias = 1 if last > sma else (-1 if last < sma else 0)

        if d == 1 and bias == -1:
            continue
        if d == -1 and bias == 1:
            continue

        # ATR risk
        p_r = 0.005
        if code in daily_data:
            df = daily_data[code]
            if len(df) >= 15:
                tr = (
                    df['high'].astype(float) - df['low'].astype(float)
                ).clip(
                    lower=(df['high'].astype(float) - df['close'].astype(float).shift(1)).abs()
                ).clip(
                    lower=(df['low'].astype(float) - df['close'].astype(float).shift(1)).abs()
                )
                atr = tr.rolling(14).mean().iloc[-1]
                last_close = float(df['close'].iloc[-1])
                p_r = float(min(max(atr / last_close, 0.003), 0.015))

        if d == 1:
            entry = orh + 0.01
            stop = entry * (1 - p_r)
            risk = entry * p_r
            tp1 = entry + risk
            tp2 = entry + risk * 2
        else:
            entry = orl - 0.01
            stop = entry * (1 + p_r)
            risk = entry * p_r
            tp1 = entry - risk
            tp2 = entry - risk * 2

        score = rng / o * 100 + (8 if bias == 1 else -8 if bias == -1 else 0)

        rec = {
            'code': code,
            'name': TN.get(code, code),
            'dir': 'LONG' if d == 1 else 'SHORT',
            'entry': round(entry, 2),
            'stop': round(stop, 2),
            'tp1': round(tp1, 2),
            'tp2': round(tp2, 2),
            'open': round(o, 2),
            'rng': round(rng, 2),
            'range_pct': round(rng / o * 100, 2),
            'atr_pct': round(p_r * 100, 2),
            'bias': {1: 'HTF_BULL', -1: 'HTF_BEAR', 0: 'HTF_NEUTRAL'}[bias],
            'score': round(score, 1),
            'day_h': round(hi, 2),
            'day_l': round(lo, 2),
            'confirm_close': round(cp, 2),
        }

        if verify:
            day_close = q['price']
            rec['day_close'] = day_close
            if d == 1:
                if lo <= rec['stop']:
                    rec['outcome'] = 'SL'; rec['pnl'] = -1.00
                elif hi >= rec['tp2']:
                    rec['outcome'] = 'TP2'; rec['pnl'] = 2.00
                elif hi >= rec['tp1']:
                    rec['outcome'] = 'TP1'; rec['pnl'] = 1.00
                else:
                    rec['outcome'] = 'CLOSE'
                    rec['pnl'] = round((day_close - entry) / (entry - stop), 2)
            else:
                if hi >= rec['stop']:
                    rec['outcome'] = 'SL'; rec['pnl'] = -1.00
                elif lo <= rec['tp2']:
                    rec['outcome'] = 'TP2'; rec['pnl'] = 2.00
                elif lo <= rec['tp1']:
                    rec['outcome'] = 'TP1'; rec['pnl'] = 1.00
                else:
                    rec['outcome'] = 'CLOSE'
                    rec['pnl'] = round((entry - day_close) / (stop - entry), 2)

        results.append(rec)
        time.sleep(0.05)

    ctx.close()
    print(f"  Scanned in {time.time()-t2:.1f}s  (total {time.time()-t0:.1f}s)")
    return sorted(results, key=lambda x: x['score'], reverse=True)


def main():
    parser = argparse.ArgumentParser(description='ORB 1:2 HK via Futu OpenD')
    parser.add_argument('--date', default=None, help='Trade date YYYY-MM-DD (default: today)')
    parser.add_argument('--verify', action='store_true', help='Verify close results')
    parser.add_argument('--watch', default=None, help='Comma-separated HK tickers')
    args = parser.parse_args()

    trade_date = args.date or date.today().strftime('%Y-%m-%d')
    tickers = WATCHLIST
    if args.watch:
        tickers = [t.strip() for t in args.watch.split(',')]

    results = scan(tickers, trade_date, verify=args.verify)

    print(f"\n{'─'*72}")
    print(f"Signals: {len(results)}")
    print()
    hdr = f"{'Code':<10} {'Name':<8} {'DIR':<6} {'ENTRY':>7} {'STOP':>7} {'TP1':>7} {'TP2':>7} {'区间%':>5} {'BIAS':<11} {'SCORE':>5}"
    print(hdr)
    print('─' * len(hdr))
    for r in results:
        print(f"{r['code']:<10} {r['name'][:7]:<8} {r['dir']:<6} "
              f"{r['entry']:>7.2f} {r['stop']:>7.2f} {r['tp1']:>7.2f} {r['tp2']:>7.2f} "
              f"{r['range_pct']:>4.1f}% {r['bias']:<11} {r['score']:>5.1f}")

    longs = [r for r in results if r['dir'] == 'LONG']
    shorts = [r for r in results if r['dir'] == 'SHORT']
    print(f"\nLONG: {len(longs)}  SHORT: {len(shorts)}")

    if args.verify and results and 'outcome' in results[0]:
        wins = [r for r in results if r.get('pnl', 0) > 0]
        loss = [r for r in results if r.get('pnl', 0) < 0]
        net = sum(r.get('pnl', 0) for r in results)
        print(f"\n{'─'*72}")
        print(f"=== VERIFY {trade_date} ===  W={len(wins)} L={len(loss)}  Net={net:+.2f}R\n")
        hdr2 = f"{'Code':<10} {'Name':<8} {'DIR':<6} {'ENTRY':>7} {'STOP':>7} {'DAY_H':>7} {'DAY_L':>7} {'CLOSE':>7} {'OUT':<5} {'PnL':>6}"
        print(hdr2)
        print('─' * len(hdr2))
        for r in results:
            print(f"{r['code']:<10} {r['name'][:7]:<8} {r['dir']:<6} "
                  f"{r['entry']:>7.2f} {r['stop']:>7.2f} {r['day_h']:>7.2f} {r['day_l']:>7.2f} "
                  f"{r['day_close']:>7.2f} {r['outcome']:<5} {r['pnl']:>+6.2f}")


if __name__ == '__main__':
    main()
