#!/usr/bin/env python3
"""
D-TAT Backtest v2 — 1 month historical test.
Tests the improved D-TAT strategy with all filters.
"""
import json
import os
from datetime import date as dt_date, datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

ET = ZoneInfo("America/New_York")

# Settings (same as scanner v2)
TP_LEVEL = 0.382
RR_RATIO = 2.0
OR_PCT = 0.25
VOLUME_MULT = 1.2
RSI_PERIOD = 14
RSI_OVERSOLD = 40
RSI_OVERBOUGHT = 60
STRICTER_LONG = True
LONG_RSI_STRICT = 50
LONG_SIZE_PCT = 0.25
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

# Test period: last 30 days
END_DATE = dt_date.today()
START_DATE = END_DATE - timedelta(days=35)  # Extra days for lookback

# Sample S&P 500 stocks for backtest
TEST_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "UNH",
    "HD", "MA", "PG", "JNJ", "XOM", "BAC", "COST", "ABBV", "KO", "PEP",
    "AVGO", "TMO", "CSCO", "MCD", "ACN", "ABT", "DHR", "WMT", "NEE", "LIN"
]


def calc_rsi_series(prices, period=14):
    """Calculate RSI for entire series."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd_series(prices, fast=12, slow=26, signal=9):
    """Calculate MACD histogram for entire series."""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line - signal_line


def calc_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def fetch_data(ticker, days=35):
    """Fetch historical data."""
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE + timedelta(days=1), progress=False)
        if df.empty or len(df) < 20:
            print(f"  {ticker}: No data ({len(df)} rows)")
            return None

        # Handle multi-level columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Rename to standard names
        df = df.rename(columns={
            'Close': 'Close', 'High': 'High', 'Low': 'Low', 'Open': 'Open', 'Volume': 'Volume'
        })
        print(f"  {ticker}: {len(df)} rows, range {df.index[0].date()} to {df.index[-1].date()}")
        return df
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None


def backtest_stock(ticker, df):
    """Backtest a single stock."""
    if df is None or len(df) < 25:
        print(f"  {ticker}: Not enough data ({len(df) if df is not None else 0} rows)")
        return []

    df = df.copy()

    # Calculate indicators
    df['ATR'] = calc_atr(df, 14)
    df['RSI'] = calc_rsi_series(df['Close'], RSI_PERIOD)
    df['MACD'] = calc_macd_series(df['Close'], MACD_FAST, MACD_SLOW, MACD_SIGNAL)

    # Check how many valid ATR values we have
    valid_atr = df['ATR'].notna().sum()
    print(f"  {ticker}: {len(df)} rows, {valid_atr} valid ATR")

    results = []
    debug_count = 0

    for i in range(15, len(df) - 1):
        row = df.iloc[i]
        next_row = df.iloc[i + 1]

        # Skip if no ATR
        if pd.isna(row['ATR']) or row['ATR'] == 0:
            continue

        atr = float(row['ATR'])
        threshold = atr * OR_PCT

        # Use intraday range - the high-low range of the day represents potential liquidity
        day_range = float(row['High'] - row['Low'])

        # Debug: print first few
        if debug_count < 1:
            print(f"    -> {ticker}: ATR={atr:.2f} threshold={threshold:.4f} range={day_range:.2f} pass={day_range >= threshold}")
            debug_count += 1

        # Use 25% of ATR as threshold (OR_PCT = 0.25 means 25% of ATR)
        if day_range < threshold:
            continue  # No liquidity - skip this day

        # Direction based on candle (red = close < open = LONG, green = SHORT)
        is_red = row['Close'] < row['Open']
        direction = "LONG" if is_red else "SHORT"

        # Entry / TP / SL
        if direction == "LONG":
            entry = row['Low']
            tp = row['Low'] + day_range * TP_LEVEL
            sl = entry - abs(tp - entry) / RR_RATIO
        else:
            entry = row['High']
            tp = row['High'] - day_range * TP_LEVEL
            sl = entry + abs(tp - entry) / RR_RATIO

        # Apply filters
        rsi = row['RSI'] if not pd.isna(row['RSI']) else None
        macd = row['MACD'] if not pd.isna(row['MACD']) else None

        # RSI filter
        if direction == "LONG":
            rsi_thresh = LONG_RSI_STRICT if STRICTER_LONG else RSI_OVERSOLD
            if rsi is not None and rsi < rsi_thresh:
                continue
        else:
            if rsi is not None and rsi > RSI_OVERBOUGHT:
                continue

        # MACD filter
        if macd is not None:
            if direction == "LONG" and macd < 0:
                continue
            if direction == "SHORT" and macd > 0:
                continue

        # Simulate trade outcome
        entry_price = float(entry)
        tp_price = float(tp)
        sl_price = float(sl)

        # Check if TP or SL hit next day
        next_high = float(next_row['High'])
        next_low = float(next_row['Low'])

        if direction == "LONG":
            if next_high >= tp_price:
                result = "WIN"
                pnl_pct = (tp_price - entry_price) / entry_price * 100
            elif next_low <= sl_price:
                result = "LOSS"
                pnl_pct = -(abs(sl_price - entry_price) / entry_price * 100)
            else:
                result = "HOLD"
                pnl_pct = 0
        else:  # SHORT
            if next_low <= tp_price:
                result = "WIN"
                pnl_pct = (entry_price - tp_price) / entry_price * 100
            elif next_high >= sl_price:
                result = "LOSS"
                pnl_pct = -(abs(entry_price - sl_price) / entry_price * 100)
            else:
                result = "HOLD"
                pnl_pct = 0

        results.append({
            "date": str(df.index[i].date()),
            "ticker": ticker,
            "direction": direction,
            "entry": round(entry_price, 2),
            "tp": round(tp_price, 2),
            "sl": round(sl_price, 2),
            "result": result,
            "pnl_pct": round(pnl_pct, 2),
            "rsi": round(rsi, 1) if rsi else None,
            "macd": round(macd, 4) if macd else None,
        })

    return results


def main():
    print(f"D-TAT Backtest v2 — {START_DATE} to {END_DATE}")
    print(f"Testing {len(TEST_STOCKS)} stocks\n")

    all_trades = []

    for ticker in TEST_STOCKS:
        print(f"Backtesting {ticker}...", end=" ")
        df = fetch_data(ticker)
        trades = backtest_stock(ticker, df)
        all_trades.extend(trades)
        print(f"{len(trades)} signals")

    # Summary
    if not all_trades:
        print("No trades generated!")
        return

    wins = [t for t in all_trades if t['result'] == 'WIN']
    losses = [t for t in all_trades if t['result'] == 'LOSS']
    holds = [t for t in all_trades if t['result'] == 'HOLD']

    total = len(all_trades)
    win_rate = len(wins) / total * 100 if total > 0 else 0
    avg_win = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0

    longs = [t for t in all_trades if t['direction'] == 'LONG']
    shorts = [t for t in all_trades if t['direction'] == 'SHORT']

    long_wins = len([t for t in longs if t['result'] == 'WIN'])
    short_wins = len([t for t in shorts if t['result'] == 'WIN'])
    long_wr = long_wins / len(longs) * 100 if longs else 0
    short_wr = short_wins / len(shorts) * 100 if shorts else 0

    print(f"\n{'='*60}")
    print(f"D-TAT BACKTEST RESULTS — 1 Month")
    print(f"{'='*60}")
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"Total signals: {total}")
    print(f"  Wins: {len(wins)} | Losses: {len(losses)} | Holds: {len(holds)}")
    print(f"Overall WR: {win_rate:.1f}%")
    print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:.2f}%")
    print(f"\nBy Direction:")
    print(f"  LONG: {len(longs)} signals, WR: {long_wr:.1f}%")
    print(f"  SHORT: {len(shorts)} signals, WR: {short_wr:.1f}%")

    # Save results
    os.makedirs(os.path.expanduser("~/tjl_signals"), exist_ok=True)
    with open(os.path.expanduser("~/tjl_signals/backtest_results.json"), 'w') as f:
        json.dump({
            "period": {"start": str(START_DATE), "end": str(END_DATE)},
            "total_signals": total,
            "wins": len(wins),
            "losses": len(losses),
            "holds": len(holds),
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "long_signals": len(longs),
            "long_wr": round(long_wr, 1),
            "short_signals": len(shorts),
            "short_wr": round(short_wr, 1),
            "trades": all_trades,
        }, f, indent=2)

    print(f"\nResults saved to ~/tjl_signals/backtest_results.json")


if __name__ == "__main__":
    main()
