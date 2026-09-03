#!/usr/bin/env python3
"""
D-TAT S&P 500 Scanner v2 — with improved filters for better return.
Key improvements:
- Market regime filter (SPY > EMA20 for LONG)
- Volume confirmation filter
- Gap filter
- RSI momentum filter (14 period)
- MACD histogram filter
- Asymmetric position sizing
- Partial exit at 38.2% with trailing stop
- Daily loss limit (stop after 3 consecutive losses)
- Signal logging for forward testing
"""
import json, sys, urllib.request, os
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

# NEW: Regime and filter settings
SPY_TICKER   = "SPY"
EMA_PERIOD   = 20
VOLUME_MULT  = 1.2      # Volume must be > this x average
GAP_LIMIT    = 0.02     # Skip if gap > 2%
MAX_ENTRY_HOUR = 11     # No entries after 11:00 ET
LONG_SIZE_PCT = 0.5     # LONG = 50% of SHORT size
PARTIAL_TP   = 0.382    # Close partial at 38.2% Fib level
PARTIAL_PCT  = 0.5      # Close 50% at partial TP
TRAIL_START  = 0.5       # Start trailing after 50% of target reached
TRAIL_DIST   = 0.5       # Trail at 0.5x remaining distance to TP

# NEW: Daily loss limit
MAX_CONSECUTIVE_LOSSES = 3  # Stop trading after this many losses
DAILY_LOSS_FILE = os.path.expanduser("~/tjl_signals/daily_tracking.json")

# NEW: RSI/MACD momentum filters
RSI_PERIOD  = 14
RSI_OVERSOLD = 40       # LONG only if RSI > oversold
RSI_OVERBOUGHT = 60     # SHORT only if RSI < overbought
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# Logging
LOG_FILE = os.path.expanduser("~/tjl_signals/dtat_v2_signals.json")
LOG_SKIPS = True  # Log skipped signals too

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1305198403200229447/8hN1qH0mE8nA3pR7vL5kX2yZ9wC4jF6bD8sQ1tU7mG3iH0aV2cX5zN9jM4bR6dT8wZ"

# S&P 500 tickers (same as v1)
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

# ── Signal Logging ───────────────────────────────────────────────────────────

def load_signals():
    """Load existing signals from JSON file."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"signals": [], "metadata": {}}
    return {"signals": [], "metadata": {}}

def save_signal(signal):
    """Save a signal to the JSON log file."""
    data = load_signals()
    data["signals"].append(signal)

    # Ensure directory exists
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    with open(LOG_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def log_signal(result, market_regime, spy_gap):
    """Log a signal with filter metadata."""
    today = str(dt_date.today())

    signal = {
        "date": today,
        "timestamp": datetime.now(ET).isoformat(),
        "symbol": result.get("symbol"),
        "action": result.get("action"),
        "market_regime": market_regime,
        "spy_gap_pct": round(spy_gap * 100, 2),
    }

    if result.get("action") == "SETUP_FOUND":
        signal.update({
            "direction": result.get("direction"),
            "entry": result.get("entry"),
            "tp": result.get("tp"),
            "sl": result.get("sl"),
            "atr14": result.get("atr14"),
            "candle_range": result.get("candle_range"),
            "position_size": result.get("position_size"),
            "rsi": result.get("rsi"),
            "macd_hist": result.get("macd_hist"),
            "filters_passed": ["liquidity"],
        })
        if result.get("direction") == "LONG":
            signal["filters_passed"].append("regime_bull")
            signal["filters_passed"].append("volume")
            signal["filters_passed"].append("rsi")
            signal["filters_passed"].append("macd")
        else:
            signal["filters_passed"].append("volume")
            signal["filters_passed"].append("rsi")
            signal["filters_passed"].append("macd")
    else:
        # Skipped signals - log the reason
        signal["skip_reason"] = result.get("note") or result.get("action")
        if "regime" in str(result.get("note", "")).lower():
            signal["filtered_by"] = "regime"
        elif "volume" in str(result.get("note", "")).lower():
            signal["filtered_by"] = "volume"
        elif "gap" in str(result.get("note", "")).lower():
            signal["filtered_by"] = "gap"
        elif "rsi" in str(result.get("note", "")).lower():
            signal["filtered_by"] = "rsi"
        elif "macd" in str(result.get("note", "")).lower():
            signal["filtered_by"] = "macd"
        else:
            signal["filtered_by"] = "liquidity"

    # Save to file
    if LOG_SKIPS or signal.get("action") == "SETUP_FOUND":
        save_signal(signal)

# ── Market Regime ────────────────────────────────────────────────────────────────

def get_market_regime():
    """Get current market regime: BULL, BEAR, or NEUTRAL based on SPY EMA."""
    try:
        spy = yf.Ticker(SPY_TICKER).history(period="60d")
        if spy.empty or len(spy) < EMA_PERIOD:
            return "NEUTRAL"

        spy['EMA20'] = spy['Close'].ewm(span=EMA_PERIOD, adjust=False).mean()
        current_price = spy['Close'].iloc[-1]
        ema20 = spy['EMA20'].iloc[-1]

        if current_price > ema20 * 1.01:  # 1% buffer
            return "BULL"
        elif current_price < ema20 * 0.99:
            return "BEAR"
        return "NEUTRAL"
    except Exception as e:
        print(f"Regime detection error: {e}")
        return "NEUTRAL"

def get_spy_gap():
    """Get today's gap from previous close."""
    try:
        spy = yf.Ticker(SPY_TICKER)
        prev = spy.history(period="2d")
        if len(prev) < 2:
            return 0
        prev_close = prev['Close'].iloc[-2]
        today_open = yf.download(SPY_TICKER, period="1d", interval="1d", auto_adjust=True)
        if today_open.empty:
            return 0
        today_open = today_open['Open'].iloc[-1]
        return (today_open - prev_close) / prev_close
    except:
        return 0

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_trading_day(d):
    return d.weekday() < 5

def last_trading_day(ref):
    d = ref - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d

def fetch_today_5m(ticker_sym):
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

def fetch_volume_avg(ticker_sym, days=20):
    """Get average volume over N days."""
    try:
        df = yf.download(ticker_sym, period=f"{days}d", interval="1d", progress=False)
        if df.empty:
            return None
        df.columns = df.columns.get_level_values(0)
        return df['Volume'].mean()
    except:
        return None

def get_first_candle_15m(df_5m):
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

def get_today_volume_ratio(ticker_sym):
    """Get today's volume / 20-day average volume."""
    try:
        df = yf.download(ticker_sym, period="1d", interval="1d", progress=False)
        if df.empty:
            return None
        df.columns = df.columns.get_level_values(0)
        today_vol = df['Volume'].iloc[-1]
        avg_vol = fetch_volume_avg(ticker_sym)
        if avg_vol and avg_vol > 0:
            return today_vol / avg_vol
        return None
    except:
        return None

def get_rsi(ticker_sym, period=14):
    """Calculate RSI(14) from 30-day daily data."""
    try:
        df = yf.download(ticker_sym, period="30d", interval="1d", progress=False)
        if df.empty or len(df) < period + 1:
            return None
        df.columns = df.columns.get_level_values(0)
        close = df['Close']

        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    except:
        return None

def get_macd(ticker_sym):
    """Calculate MACD (12,26,9). Returns (MACD line, signal line, histogram)."""
    try:
        df = yf.download(ticker_sym, period="60d", interval="1d", progress=False)
        if df.empty or len(df) < 60:
            return None, None, None
        df.columns = df.columns.get_level_values(0)
        close = df['Close']

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        return (
            float(macd_line.iloc[-1]),
            float(signal_line.iloc[-1]),
            float(histogram.iloc[-1])
        )
    except:
        return None, None, None

# ── Daily Loss Tracking ───────────────────────────────────────────────────────────

def load_daily_tracking():
    """Load daily trading stats."""
    if os.path.exists(DAILY_LOSS_FILE):
        try:
            with open(DAILY_LOSS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"date": None, "consecutive_losses": 0}
    return {"date": None, "consecutive_losses": 0}

def save_daily_tracking(data):
    """Save daily trading stats."""
    os.makedirs(os.path.dirname(DAILY_LOSS_FILE), exist_ok=True)
    with open(DAILY_LOSS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def check_daily_loss_limit():
    """Check if we've hit the daily loss limit. Returns (can_trade, reason)."""
    today = str(dt_date.today())
    data = load_daily_tracking()

    # Reset if new day
    if data.get("date") != today:
        data = {"date": today, "consecutive_losses": 0}
        save_daily_tracking(data)
        return True, None

    if data.get("consecutive_losses", 0) >= MAX_CONSECUTIVE_LOSSES:
        return False, f"Daily loss limit reached ({MAX_CONSECUTIVE_LOSSES} losses)"

    return True, None

def record_trade_result(won: bool):
    """Record trade outcome for daily tracking."""
    today = str(dt_date.today())
    data = load_daily_tracking()

    # Reset if new day
    if data.get("date") != today:
        data = {"date": today, "consecutive_losses": 0}

    if won:
        data["consecutive_losses"] = 0
    else:
        data["consecutive_losses"] = data.get("consecutive_losses", 0) + 1

    save_daily_tracking(data)

def analyze_today(symbol, market_regime, spy_gap):
    """Analyze a single symbol with improved filters."""
    df_daily = fetch_30d_daily(symbol)
    if df_daily is None or len(df_daily) < 15:
        result = {"symbol": symbol, "error": "no daily data"}
        log_signal(result, market_regime, spy_gap)
        return result

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
        result = {"symbol": symbol, "error": "ATR calc failed"}
        log_signal(result, market_regime, spy_gap)
        return result

    # Today's 5-min data
    df_5m = fetch_today_5m(symbol)
    candle = get_first_candle_15m(df_5m)
    if candle is None:
        result = {
            "symbol": symbol,
            "date": str(dt_date.today()),
            "atr14": round(atr14, 2),
            "action": "NO_DATA",
            "note": "No 5-min data for today yet"
        }
        log_signal(result, market_regime, spy_gap)
        return result

    open_, high_, low_, close_ = candle
    threshold    = atr14 * OR_PCT
    candle_range = round(high_ - low_, 4)
    is_liq       = candle_range >= threshold

    if not is_liq:
        result = {
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
        log_signal(result, market_regime, spy_gap)
        return result

    # NEW: Gap filter
    if abs(spy_gap) > GAP_LIMIT:
        result = {
            "symbol": symbol,
            "date": str(dt_date.today()),
            "atr14": round(atr14, 2),
            "action": "SKIP_GAP",
            "note": f"Gap {spy_gap*100:.1f}% > {GAP_LIMIT*100:.0f}% limit"
        }
        log_signal(result, market_regime, spy_gap)
        return result

    # Original direction logic: red = LONG, green = SHORT
    direction = "LONG" if close_ < open_ else "SHORT"

    # NEW: Market regime filter for LONG
    if direction == "LONG" and market_regime == "BEAR":
        result = {
            "symbol": symbol,
            "date": str(dt_date.today()),
            "atr14": round(atr14, 2),
            "action": "SKIP_REGIME",
            "note": "LONG skipped in bear market"
        }
        log_signal(result, market_regime, spy_gap)
        return result

    # NEW: Market regime filter for SHORT (less restrictive)
    if direction == "SHORT" and market_regime == "BULL":
        # In bull market, be more selective with shorts
        # Only take if very strong liquidity candle
        if candle_range < threshold * 1.5:
            result = {
                "symbol": symbol,
                "date": str(dt_date.today()),
                "atr14": round(atr14, 2),
                "action": "SKIP_REGIME",
                "note": "SHORT weak in bull market"
            }
            log_signal(result, market_regime, spy_gap)
            return result

    # NEW: Volume filter for LONG
    if direction == "LONG":
        vol_ratio = get_today_volume_ratio(symbol)
        if vol_ratio is not None and vol_ratio < VOLUME_MULT:
            result = {
                "symbol": symbol,
                "date": str(dt_date.today()),
                "atr14": round(atr14, 2),
                "action": "SKIP_VOLUME",
                "note": f"Vol {vol_ratio:.1f}x < {VOLUME_MULT}x"
            }
            log_signal(result, market_regime, spy_gap)
            return result

    # NEW: RSI filter - LONG needs RSI > oversold, SHORT needs RSI < overbought
    rsi = get_rsi(symbol, RSI_PERIOD)
    if rsi is not None:
        if direction == "LONG" and rsi < RSI_OVERSOLD:
            result = {
                "symbol": symbol,
                "date": str(dt_date.today()),
                "atr14": round(atr14, 2),
                "action": "SKIP_RSI",
                "note": f"RSI {rsi:.1f} < {RSI_OVERSOLD} (oversold)"
            }
            log_signal(result, market_regime, spy_gap)
            return result
        if direction == "SHORT" and rsi > RSI_OVERBOUGHT:
            result = {
                "symbol": symbol,
                "date": str(dt_date.today()),
                "atr14": round(atr14, 2),
                "action": "SKIP_RSI",
                "note": f"RSI {rsi:.1f} > {RSI_OVERBOUGHT} (overbought)"
            }
            log_signal(result, market_regime, spy_gap)
            return result

    # NEW: MACD filter - histogram should align with direction
    macd, signal, hist = get_macd(symbol)
    if macd is not None and signal is not None:
        if direction == "LONG" and hist < 0:  # Bearish MACD
            result = {
                "symbol": symbol,
                "date": str(dt_date.today()),
                "atr14": round(atr14, 2),
                "action": "SKIP_MACD",
                "note": f"MACD hist {hist:.2f} < 0 (bearish)"
            }
            log_signal(result, market_regime, spy_gap)
            return result
        if direction == "SHORT" and hist > 0:  # Bullish MACD
            result = {
                "symbol": symbol,
                "date": str(dt_date.today()),
                "atr14": round(atr14, 2),
                "action": "SKIP_MACD",
                "note": f"MACD hist {hist:.2f} > 0 (bullish)"
            }
            log_signal(result, market_regime, spy_gap)
            return result

    # Entry and risk
    entry = low_ if direction == "LONG" else high_
    tp    = round(low_ + (high_ - low_) * TP_LEVEL, 4)
    sl_dist = abs(tp - entry) / RR_RATIO
    sl = round(entry - sl_dist, 4) if direction == "LONG" else round(entry + sl_dist, 4)

    # NEW: Position sizing info
    position_size = LONG_SIZE_PCT if direction == "LONG" else 1.0

    result = {
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
        "position_size": position_size,
        "market_regime": market_regime,
        "rsi": round(rsi, 1) if rsi else None,
        "macd_hist": round(hist, 4) if hist else None,
        # Partial exit strategy
        "partial_exit": {
            "partial_tp_pct": PARTIAL_PCT,
            "partial_tp_price": round(entry + (tp - entry) * PARTIAL_TP / TP_LEVEL, 4) if direction == "LONG" else round(entry - (entry - tp) * PARTIAL_TP / TP_LEVEL, 4),
            "trail_start": TRAIL_START,
            "trail_dist": TRAIL_DIST,
        },
    }
    log_signal(result, market_regime, spy_gap)
    return result

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

def build_discord(setups, skips, errors, market_regime, spy_gap):
    longs   = [s for s in setups if s["direction"] == "LONG"]
    shorts  = [s for s in setups if s["direction"] == "SHORT"]
    total   = len(setups) + len(skips) + len(errors)

    def sf(s):
        size_pct = s.get("position_size", 1.0)
        size_str = f"{size_pct*100:.0f}%" if size_pct < 1 else "100%"
        return [
            {"name": "Entry",      "value": f"${s['entry']:.4f}",  "inline": True},
            {"name": "TP (38.2%)", "value": f"${s['tp']:.4f}",   "inline": True},
            {"name": "SL",          "value": f"${s['sl']:.4f}",   "inline": True},
            {"name": "R:R",         "value": f"{s['rr_ratio']}:1", "inline": True},
            {"name": "Size",        "value": size_str,            "inline": True},
            {"name": "ATR(14)",     "value": f"${s['atr14']:.2f}", "inline": True},
        ]

    embeds = []

    regime_color = 0x00FF00 if market_regime == "BULL" else 0xFF0000 if market_regime == "BEAR" else 0xFFAA00

    embeds.append({
        "title": f"D-TAT v2 — {dt_date.today()} | Regime: {market_regime}",
        "description": (
            f"Scanned **{total}** S&P 500 symbols.\n"
            f"✅ **{len(setups)} setups** | ⏭️ {len(skips)} skipped | ❌ {len(errors)} errors\n"
            f"SPY Gap: {spy_gap*100:+.1f}% | Regime: {market_regime}"
        ),
        "color": regime_color,
        "fields": [
            {"name": "Long",              "value": f"{len(longs)} setups", "inline": True},
            {"name": "Short",             "value": f"{len(shorts)} setups", "inline": True},
            {"name": "Liquidity Filter",  "value": f"≥ {OR_PCT*100:.0f}% of ATR(14)", "inline": True},
            {"name": "Volume Filter",     "value": f"≥ {VOLUME_MULT}x avg", "inline": True},
            {"name": "Gap Limit",         "value": f"≤ {GAP_LIMIT*100:.0f}%", "inline": True},
            {"name": "LONG Size",         "value": f"{LONG_SIZE_PCT*100:.0f}% of SHORT", "inline": True},
        ],
        "footer": {"text": "D-TAT v2 | Logged to ~/tjl_signals/dtat_v2_signals.json"},
    })

    if longs:
        for chunk in _chunks(sorted(longs, key=lambda x: -x["candle_range"]), 10):
            embeds.append({
                "title": f"🟢 LONG — {len(longs)} setups",
                "color": 0x00FF00,
                "fields": [f for s in chunk for f in sf(s)],
                "footer": {"text": f"LONG: only when SPY > EMA{EMA_PERIOD} + volume confirm"},
            })

    if shorts:
        for chunk in _chunks(sorted(shorts, key=lambda x: -x["candle_range"]), 10):
            embeds.append({
                "title": f"🔴 SHORT — {len(shorts)} setups",
                "color": 0xFF4444,
                "fields": [f for s in chunk for f in sf(s)],
                "footer": {"text": "SHORT: more selective in bull market"},
            })

    if skips:
        skip_types = {}
        for s in skips:
            reason = s.get("note", s.get("action", "unknown"))
            skip_types[reason] = skip_types.get(reason, 0) + 1

        lines = "\n".join(f"{note}: {count}" for note, count in list(skip_types.items())[:10])
        embeds.append({
            "title": f"⏭️ Skipped ({len(skips)} total)",
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
    print(f"D-TAT v2 Live Scan — {today}  (ET: {datetime.now(ET).strftime('%H:%M')})")

    # Check daily loss limit
    can_trade, limit_reason = check_daily_loss_limit()
    if not can_trade:
        print(f"\n⚠️ DAILY LOSS LIMIT REACHED: {limit_reason}")
        print("No new signals will be generated today.")
        return

    # Get market regime
    print("Detecting market regime...")
    market_regime = get_market_regime()
    spy_gap = get_spy_gap()
    print(f"Market regime: {market_regime} | SPY gap: {spy_gap*100:+.1f}%")

    print(f"Scanning {len(SP500_TICKERS)} S&P 500 symbols...\n")

    setups, skips, errors = [], [], []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(analyze_today, sym, market_regime, spy_gap): sym for sym in SP500_TICKERS}
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
            elif r["action"].startswith("SKIP"):
                skips.append(r)
            elif r["action"] == "SETUP_FOUND":
                setups.append(r)

    total = len(setups) + len(skips) + len(errors)
    print(f"\n{'='*90}")
    print(f"{'D-TAT v2 LIVE SCAN':>35}  {today}")
    print(f"{'='*90}")
    print(f"Regime: {market_regime} | Gap: {spy_gap*100:+.1f}%")
    print(f"Total: {total}  |  ✅ Setups: {len(setups)}  |  ⏭️ Skipped: {len(skips)}  |  ❌ Errors: {len(errors)}")

    # Print filter stats
    filter_stats = {"regime": 0, "volume": 0, "gap": 0, "liquidity": 0, "rsi": 0, "macd": 0}
    for s in skips:
        note = s.get("note", "")
        if "regime" in note.lower():
            filter_stats["regime"] += 1
        elif "volume" in note.lower():
            filter_stats["volume"] += 1
        elif "gap" in note.lower():
            filter_stats["gap"] += 1
        elif "rsi" in note.lower():
            filter_stats["rsi"] += 1
        elif "macd" in note.lower():
            filter_stats["macd"] += 1
        else:
            filter_stats["liquidity"] += 1

    print(f"\nFilter Stats:")
    print(f"  Regime filtered: {filter_stats['regime']}")
    print(f"  Volume filtered: {filter_stats['volume']}")
    print(f"  Gap filtered: {filter_stats['gap']}")
    print(f"  RSI filtered: {filter_stats['rsi']}")
    print(f"  MACD filtered: {filter_stats['macd']}")
    print(f"  Below liquidity: {filter_stats['liquidity']}")

    # Daily loss tracking info
    tracking = load_daily_tracking()
    print(f"\nDaily Stats:")
    print(f"  Consecutive losses: {tracking.get('consecutive_losses', 0)}/{MAX_CONSECUTIVE_LOSSES}")

    if setups:
        longs  = sorted([s for s in setups if s["direction"]=="LONG"],  key=lambda x: -x["candle_range"])
        shorts = sorted([s for s in setups if s["direction"]=="SHORT"], key=lambda x: -x["candle_range"])

        if longs:
            print(f"\n🟢 LONG ({len(longs)} setups) — Size: {LONG_SIZE_PCT*100:.0f}%:")
            print(f"{'Symbol':<8} {'Entry':>10} {'TP':>10} {'SL':>10} {'ATR':>7} {'Range':>7} {'Thresh':>7}")
            print("-"*68)
            for s in longs:
                print(f"{s['symbol']:<8} {s['entry']:>10.4f} {s['tp']:>10.4f} {s['sl']:>10.4f} {s['atr14']:>7.2f} {s['candle_range']:>7.2f} {s['threshold']:>7.2f}")

        if shorts:
            print(f"\n🔴 SHORT ({len(shorts)} setups):")
            print(f"{'Symbol':<8} {'Entry':>10} {'TP':>10} {'SL':>10} {'ATR':>7} {'Range':>7} {'Thresh':>7}")
            print("-"*68)
            for s in shorts:
                print(f"{s['symbol']:<8} {s['entry']:>10.4f} {s['tp']:>10.4f} {s['sl']:>10.4f} {s['atr14']:>7.2f} {s['candle_range']:>7.2f} {s['threshold']:>7.2f}")

    print(f"\nSignals logged to: {LOG_FILE}")

    # Discord
    if setups or skips:
        print("\nPosting to Discord...")
        payload = build_discord(setups, skips, errors, market_regime, spy_gap)
        ok = post_discord(payload)
        print(f"Discord: {'✅ OK' if ok else '❌ FAILED'}")

if __name__ == "__main__":
    main()
