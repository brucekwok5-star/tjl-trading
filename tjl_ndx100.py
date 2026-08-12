#!/usr/bin/env python3
"""Scan Nasdaq 100 with TJL US models, post P&L table to Discord."""
import sys, os, json, urllib.request
from datetime import date
sys.path.insert(0, '/Users/jaydensmac/.openclaw/workspace')

import yfinance as yf
import importlib
import tjl_live_us as t
importlib.reload(t)

WEBHOOK = os.environ.get(
    'DISCORD_WEBHOOK_HK_TJL',
    'https://discordapp.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj'
)

NDX_100 = [
    "AAPL","ABNB","ADBE","ADI","ADP","ADSK","AEP","AMAT","AMD","AMGN",
    "AMZN","ANSS","APP","ASML","AVGO","AZN","BE","BIIB","BKNG","BOX",
    "CDNS","CEG","CMCSA","COIN","CPRT","CRWD","CSGP","CSX","CTAS","CTSH",
    "DASH","DBX","DDOG","DLTR","DXCM","EA","EXC","EXPE","FAST","FTNT",
    "GE","GFS","GOOGL","GOOG","HPQ","HSIC","IDXX","ILMN","INCY",
    "INTC","INTU","ISRG","JD","KDP","KHC","KLAC","LCID","LRCX","LULU",
    "MAR","MCHP","MDLZ","MELI","META","MNST","MO","MRNA","MRVL","MSFT",
    "MU","NICE","NOW","NTAP","NVDA","ON","ORLY","PANW",
    "PAYX","PCAR","PDD","PNW","PTC","PYPL","QCOM","REGN","RIVN",
    "RKLB","ROST","SBUX","SIRI","SNPS","SPLK","SWKS","TEAM","TMUS",
    "TTD","TTWO","TXN","UAL","UBER","VRSK","VRTX","WBA",
    "WDAY","XEL","XRAY","ZS","ZTS"
]

def get_current_price(tkr):
    """Get current price: 1m bars > fast_info.lastPrice."""
    try:
        tk = yf.Ticker(tkr)
        fi = tk.fast_info
        lp = fi.get('lastPrice')
        rpc = fi.get('regularMarketPreviousClose')
        m1 = tk.history(period="1d", interval="1m")
        if m1 is not None and not m1.empty and len(m1) >= 2:
            curr = float(m1.iloc[-1]['Close'])
        elif lp:
            curr = float(lp)
        else:
            hist = tk.history(period="2d")
            curr = float(hist['Close'].iloc[-1]) if not hist.empty else None
        return curr, float(rpc) if rpc else None
    except:
        return None, None

# Run scan
os.environ['US_TICKERS'] = ','.join(NDX_100)
os.environ['DISCORD_WEBHOOK_HK_TJL'] = WEBHOOK
print(f"Scanning {len(NDX_100)} Nasdaq 100 stocks...")
signals = t.run_scan()

if not signals:
    print("0 signals.")
    payload = json.dumps({
        "username": "TJL US — NDX100",
        "content": f"**TJL US — Nasdaq 100** | {date.today()}\n0 signals"
    }).encode()
    req = urllib.request.Request(WEBHOOK, data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"Discord: {r.status}")
    except Exception as e:
        print(f"Discord error: {e}")
    sys.exit(0)

# Build P&L rows
rows = []
for s in signals:
    tkr = s['ticker']
    entry = s['price']
    curr, _ = get_current_price(tkr)
    if curr is None:
        continue
    pnl = curr - entry
    pct = pnl / entry * 100
    sign = '+' if pnl >= 0 else '-'
    if pct >= 5:     ver = 'Big Gain' if pnl > 0 else 'Big Loss'
    elif pct <= -5:  ver = 'Big Loss'
    elif abs(pct) < 0.3: ver = 'Flat'
    else:            ver = 'Gain' if pnl > 0 else 'Loss'
    rows.append({
        'ticker': tkr, 'name': s.get('name', tkr), 'price': curr,
        'entry': entry, 'pnl': pnl, 'pct': pct, 'chg': f"{sign}{abs(pct):.2f}%",
        'ver': ver, 'model': s.get('model', '?'),
        'sl': s.get('sl'), 'tp': s.get('tp'),
        'rr': s.get('rr_ratio', 2.0),
        'trades': s.get('trades', '-'), 'wr': s.get('wr', '-')
    })

rows.sort(key=lambda x: x['pnl'])

# Console table
print(f"\n{'Ticker':<8} {'Price':>8} {'Chg%':>8} {'Mdl':>4} {'Entry':>8} {'P&L%':>8} {'Verdict'}")
print('─'*75)
for r in rows:
    print(f"{r['ticker']:<8} ${r['price']:>7.2f} {r['chg']:>8} {r['model']:>4} "
          f"${r['entry']:>7.2f} {r['pct']:>+7.2f}%  {r['ver']}")

# Discord table
lines = ["```",
         f"{'Ticker':<8} {'Price':>8} {'Chg%':>8} {'Mdl':>4} {'SL':>8} {'TP':>8} {'R:R':>4} {'Trds':>5} {'WR'}",
         "─"*85]
for r in rows:
    sl = r.get('sl') or 0
    tp = r.get('tp') or 0
    lines.append(f"{r['ticker']:<8} ${r['price']:>7.2f} {r['chg']:>8} {r['model']:>4} "
                 f"${sl:>7.2f} ${tp:>7.2f} {r['rr']:>4.1f}  {r['trades']:<5} {r['wr']}")
lines.append("```")

content = (
    f"**TJL US — Nasdaq 100 Scan** | {date.today()}\n"
    f"{len(signals)} signals "
    f"({sum(1 for r in rows if r['pnl']>=0)}✅ "
    f"{sum(1 for r in rows if r['pnl']<0)}❌)\n"
    + "\n".join(lines)
)

payload = json.dumps({
    "username": "TJL US — NDX100",
    "content": content,
    "thread_name": f"NDX100 {date.today().strftime('%Y-%m-%d')}"
}).encode()
req = urllib.request.Request(WEBHOOK, data=payload,
    headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"\nDiscord: HTTP {resp.status}")
except Exception as e:
    print(f"\nDiscord error: {e}")
