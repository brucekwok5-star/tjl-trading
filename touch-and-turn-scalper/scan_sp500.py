#!/usr/bin/env python3
"""D-TAT S&P 500 Scanner — live scan for today's open."""
import json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as dt_date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ET           = ZoneInfo("America/New_York")
TP_LEVEL     = 0.382
RR_RATIO     = 2.0
OR_PCT       = 0.25
MAX_WORKERS  = 25
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1305198403200229447/8hN1qH0mE8nA3pR7vL5kX2yZ9wC4jF6bD8sQ1tU7mG3iH0aV2cX5zN9jM4bR6dT8wZ"

SP500_TICKERS = [
    "A","AAPL","ABBV","ABC","ABNB","ABT","ACGL","ACN","ADBE","ADI",
    "ADM","ADP","ADSK","AEP","AEIS","AFL","AG","AIG","AIZ","AJG",
    "AKAM","ALB","ALGN","ALL","AMAT","AMCR","AMD","AME","AMGN","AMP",
    "AMT","AMZN","ANSS","AON","APA","APD","APH","APTV","ARE","ATO",
    "AVB","AVGO","AVY","AWK","AXON","AZO","BA","BAC","BALL","BAND",
    "BDX","BEN","BF-B","BIIB","BK","BKNG","BKR","BLDR","BLK","BMRN",
    "BMY","BR","BRO","BSX","BURL","BWA","BX","BYD","BZ","C","CAG",
    "CAH","CARR","CAT","CB","CBOE","CBRE","CCL","CHD","CHRW","CHTR",
    "CI","CINF","CL","CLX","CMA","CMCSA","CME","CMG","CMI","CMS",
    "CNC","CNH","COF","COO","COP","COR","COST","CPT","CRL","CRM",
    "CSCO","CSGP","CSL","CTAS","CTRA","CTSH","CTVA","CVS","CVX","CZR",
    "D","DASH","DAY","DD","DE","DECK","DEL","DELL","DG","DGX","DHI",
    "DHR","DIS","DLR","DLTR","DOV","DOW","DPZ","DRI","DTE","DUK",
    "DXC","DXCM","EA","EBAY","ECL","ED","EG","EIX","EL","ELV","EMN",
    "EMR","ENPH","EOG","EPAM","EQIX","EQR","EQT","ERIE","ES","ESS",
    "EXC","EXCH","EXPD","EXPE","EXR","F","FANG","FAST","FCX","FDS",
    "FDX","FE","FF","FI","FICO","FIS","FITB","FLT","FMC","FN","FOXA",
    "FRC","FRT","FSLR","FTNT","FTV","G","GAT","GDDY","GE","GEHC","GEN",
    "GILD","GIS","GL","GLW","GM","GNRC","GOOG","GOOGL","GPC","GPN",
    "GRMN","GRUB","GS","GWW","HAL","HAS","HBAN","HCA","HD","HES","HII",
    "HLT","HMC","HOG","HOLX","HON","HPE","HPQ","HRL","HSIC","HST","HSY",
    "HUBB","HUM","HWM","IBM","ICE","IDXX","IEX","IFF","INCY","INGR",
    "INTC","INTU","INVH","IONQ","IQV","IR","IRM","ISRG","IT","ITW","IVZ",
    "J","JBHT","JBL","JCI","JKHY","JNJ","JNPR","JPM","JUN","K","KDP",
    "KEY","KEYS","KHC","KIM","KLAC","KMB","KMI","KMX","KO","KR","KSS",
    "KT","L","LAUR","LDOS","LEN","LHX","LH","LII","LLY","LMT","LNC",
    "LNG","LNT","LOW","LRCX","LUV","LVS","LW","LYB","LYV","M","MA",
    "MAA","MAR","MAS","MCD","MCHP","MCK","MCO","MDGL","MDLZ","MDT","MED",
    "MELI","META","MGM","MHK","MKC","MKTX","MLM","MMC","MMM","MNST","MO",
    "MOH","MOS","MPC","MPWR","MRK","MRNA","MRO","MS","MSCI","MSFT","MTCH",
    "MTD","MU","NDAQ","NDSN","NEE","NEM","NET","NFLX","NI","NKE","NOC",
    "NOT","NOV","NOW","NRG","NSC","NTAP","NTRS","NUE","NVDA","NVR","NXPI",
    "O","ODFL","OG","OKE","ON","ORCL","ORLY","OSK","OXY","PANW","PAR",
    "PAYC","PAYX","PCAR","PCG","PCI","PD","PEG","PEN","PEP","PFE","PFG",
    "PG","PGR","PH","PHM","PKG","PLD","PLTR","PM","PNC","PNR","PNW",
    "POOL","PPG","PPL","PRU","PSA","PSX","PTC","PVH","PWR","PXD","PYPL",
    "QCOM","QD","RCL","REG","REGN","RF","RHI","RJF","RL","RMD","ROK",
    "ROL","ROP","ROST","RSG","RTX","RVTY","S","SALT","SAM","SAP","SCHW",
    "SEDG","SEE","SEG","SF","SHW","SJM","SKX","SLB","SLG","SMAR","SMCI",
    "SNA","SNPS","SNX","SO","SOLV","SPG","SPGI","SPOT","SRE","STE","STLD",
    "STM","STT","STX","STZ","SWK","SWKS","SYF","SYK","SYY","T","TAP",
    "TDG","TDY","TECH","TEAM","TER","TFC","TFX","TGT","TJX","TK","TMO",
    "TMUS","TNG","TPR","TPL","TRGP","TRMB","TROW","TRV","TSCO","TSLA",
    "TSN","TT","TTWO","TXN","TXT","TYL","UDR","UHS","ULTA","UNH","UNP",
    "UNVR","UPS","UPST","URI","USB","V","VEEV","VFC","VIAC","VICI","VLO",
    "VLTO","VMC","VMI","VMW","VNO","VOD","VRSK","VRSN","VRTX","VST","VTRS",
    "VZ","W","WAB","WAT","WBA","WBD","WCN","WDC","WEC","WELL","WFC","WHR",
    "WKB","WM","WMB","WMT","WNR","WPP","WSO","WTW","WY","WYNN","XEL",
    "XOM","XPO","XRAY","XYL","YUM","ZBH","ZBRA","ZION","ZTS",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_trading_day(d):
    return d.weekday() < 5

def last_trading_day(ref):
    d = ref - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d

def fetch_today_5m(ticker_sym):
    """Fetch today's 5-min bars using yf.download (works during live market)."""
    try:
        df = yf.download(
            ticker_sym, period="1d", interval="5m",
            auto_adjust=True, keepna=False, progress=False
        )
        if df.empty:
            return None
        df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_convert(ET) if df.index.tz else df.tz_localize(ET)
        return df
    except Exception:
        return None

def fetch_30d_daily(ticker_sym):
    """Fetch last 30 days daily bars for ATR computation."""
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
    """Aggregate first 3 x 5-min bars (09:30–09:42 ET) into a 15-min candle."""
    if df_5m is None or df_5m.empty:
        return None
    try:
        bars = df_5m[(df_5m.index.hour == 9) & (df_5m.index.minute < 45)].head(3)
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

def analyze_today(symbol):
    """Analyze a single symbol for today's D-TAT setup."""
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

    # Today's 5-min data
    df_5m = fetch_today_5m(symbol)
    candle = get_first_candle_15m(df_5m)
    if candle is None:
        return {
            "symbol": symbol,
            "date": str(dt_date.today()),
            "atr14": round(atr14, 2),
            "action": "NO_DATA",
            "note": "No 5-min data for today yet (before 09:30 or no trading)"
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

# ── Discord ───────────────────────────────────────────────────────────────────

def post_discord(payload: str) -> bool:
    req = urllib.request.Request(
        DISCORD_WEBHOOK,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Discord error: {e}")
        return False

def build_discord(setups, skips, errors):
    longs   = [s for s in setups if s["direction"] == "LONG"]
    shorts  = [s for s in setups if s["direction"] == "SHORT"]
    total   = len(setups) + len(skips) + len(errors)

    def sf(s):
        return [
            {"name": "Entry",      "value": f"${s['entry']:.4f}",  "inline": True},
            {"name": "TP (38.2%)", "value": f"${s['tp']:.4f}",   "inline": True},
            {"name": "SL",          "value": f"${s['sl']:.4f}",   "inline": True},
            {"name": "R:R",         "value": f"{s['rr_ratio']}:1", "inline": True},
            {"name": "ATR(14)",     "value": f"${s['atr14']:.2f}", "inline": True},
            {"name": "Candle",      "value": f"${s['candle_range']:.2f} / thr ${s['threshold']:.2f}", "inline": False},
        ]

    embeds = []

    embeds.append({
        "title": f"D-TAT Live Scan — {dt_date.today()}",
        "description": (
            f"Scanned **{total}** S&P 500 symbols.\n"
            f"✅ **{len(setups)} setups** | ⏭️ {len(skips)} skipped | ❌ {len(errors)} errors"
        ),
        "color": 0x00FF88 if setups else 0xFF6600,
        "fields": [
            {"name": "Long",              "value": f"{len(longs)} setups", "inline": True},
            {"name": "Short",             "value": f"{len(shorts)} setups", "inline": True},
            {"name": "Liquidity Filter",  "value": f"≥ {OR_PCT*100:.0f}% of ATR(14)", "inline": True},
        ],
        "footer": {"text": "D-TAT | Delta Touch & Turn Scalper | yfinance live data — verify before trading"},
    })

    if longs:
        for chunk in _chunks(sorted(longs, key=lambda x: -x["candle_range"]), 10):
            embeds.append({
                "title": f"🟢 LONG — {len(longs)} setups",
                "color": 0x00FF00,
                "fields": [f for s in chunk for f in sf(s)],
                "footer": {"text": "Red opening candle → liquidity run down → fade long at range low"},
            })

    if shorts:
        for chunk in _chunks(sorted(shorts, key=lambda x: -x["candle_range"]), 10):
            embeds.append({
                "title": f"🔴 SHORT — {len(shorts)} setups",
                "color": 0xFF4444,
                "fields": [f for s in chunk for f in sf(s)],
                "footer": {"text": "Green opening candle → liquidity run up → fade short at range high"},
            })

    if skips:
        lines = "\n".join(
            f"`{s['symbol']}` ${s['candle_range']:.2f} < ${s['threshold']:.2f}"
            for s in skips[:10]
        )
        embeds.append({
            "title": f"⏭️ Skipped ({len(skips)} total) — below liquidity threshold",
            "description": lines,
            "color": 0x888888,
        })

    return json.dumps({"embeds": embeds})

def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = dt_date.today()
    print(f"D-TAT Live Scan — {today}  (ET: {datetime.now(ET).strftime('%H:%M')})")
    print(f"Scanning {len(SP500_TICKERS)} S&P 500 symbols...\n")

    setups, skips, errors = [], [], []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(analyze_today, sym): sym for sym in SP500_TICKERS}
        done = 0
        for fut in as_completed(futures):
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(SP500_TICKERS)} done...", flush=True)
            r = fut.result()
            if r is None or r.get("error"):
                errors.append(r or {"symbol": futures[fut], "error": "none"})
            elif r["action"] == "SKIP":
                skips.append(r)
            elif r["action"] == "SETUP_FOUND":
                setups.append(r)

    total = len(setups) + len(skips) + len(errors)
    print(f"\n{'='*90}")
    print(f"{'D-TAT LIVE SCAN':>35}  {today}")
    print(f"{'='*90}")
    print(f"Total: {total}  |  ✅ Setups: {len(setups)}  |  ⏭️ Skipped: {len(skips)}  |  ❌ Errors: {len(errors)}")

    if setups:
        longs  = sorted([s for s in setups if s["direction"]=="LONG"],  key=lambda x: -x["candle_range"])
        shorts = sorted([s for s in setups if s["direction"]=="SHORT"], key=lambda x: -x["candle_range"])
        print(f"\n🟢 LONG ({len(longs)} setups):")
        print(f"{'Symbol':<8} {'Entry':>10} {'TP':>10} {'SL':>10} {'ATR':>7} {'Range':>7} {'Thresh':>7}")
        print("-"*68)
        for s in longs:
            print(f"{s['symbol']:<8} {s['entry']:>10.4f} {s['tp']:>10.4f} {s['sl']:>10.4f} {s['atr14']:>7.2f} {s['candle_range']:>7.2f} {s['threshold']:>7.2f}")
        print(f"\n🔴 SHORT ({len(shorts)} setups):")
        print(f"{'Symbol':<8} {'Entry':>10} {'TP':>10} {'SL':>10} {'ATR':>7} {'Range':>7} {'Thresh':>7}")
        print("-"*68)
        for s in shorts:
            print(f"{s['symbol']:<8} {s['entry']:>10.4f} {s['tp']:>10.4f} {s['sl']:>10.4f} {s['atr14']:>7.2f} {s['candle_range']:>7.2f} {s['threshold']:>7.2f}")

    # Discord
    if setups or skips:
        print("\nPosting to Discord...")
        payload = build_discord(setups, skips, errors)
        ok = post_discord(payload)
        print(f"Discord: {'✅ OK' if ok else '❌ FAILED'}")

if __name__ == "__main__":
    main()
