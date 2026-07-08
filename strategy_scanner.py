#!/usr/bin/env python3
"""
strategy_scanner.py — TJL intraday scanner + chart output
──────────────────────────────────────────────────────────
Combines the intraday scanner (Phase 2) and TJL strategy (Phase 3) into one script.

  1. Loads today's gappers from premarket_gappers_YYYY-MM-DD.json
  2. Checks SPY/QQQ regime filter (latched at 10:00 ET)
  3. For each gapper: fetches 5-min data, checks TJL conditions
     (bullish EMA stack 9>20>50, pullback touch, crossover re-entry, PMH gate)
  4. On hit: saves a dark-theme chart (candles, EMAs, entry/SL/TP levels)
             fires macOS notification and opens the chart in Preview

Smart notification rules:
  • First run of the day  → always ping (with or without hits)
  • New hit(s) appeared   → ping for each new one + open chart
  • Nothing new           → silent

Fires every 30 min via launchd (StartInterval: 1800).
Active window: 10:00 AM – 2:00 PM US/Eastern.

Charts saved to: ~/Documents/tjl_charts/
State file    : ~/Documents/strategy_scanner_state.json
Scan log      : ~/Documents/strategy_scanner_YYYY-MM-DD.json

Deps: pip3 install yfinance pandas matplotlib --break-system-packages
"""

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone


# ── .env loader ──────────────────────────────────────────────────────────────
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip("'\""))

_load_dotenv()


# ── Telegram ─────────────────────────────────────────────────────────────────
def send_telegram(text: str):
    """Send a Markdown message via Telegram bot. Logs on failure, never raises."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [telegram] Not configured — skipping.")
        return
    try:
        result = subprocess.run(
            [
                "curl", "-s",
                f"https://api.telegram.org/bot{token}/sendMessage",
                "-d", f"chat_id={chat_id}",
                "--data-urlencode", f"text={text}",
                "-d", "parse_mode=Markdown",
            ],
            capture_output=True, text=True, timeout=15,
        )
        resp = json.loads(result.stdout) if result.stdout else {}
        if resp.get("ok"):
            print("  [telegram] Sent OK.")
        else:
            print(f"  [telegram] API error: {resp.get('description', result.stdout[:200])}")
    except Exception as e:
        print(f"  [telegram] Failed: {e}")

# ── Timezone ─────────────────────────────────────────────────────────────────
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = None

def ny_now():
    if ET:
        return datetime.now(ET)
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=-4))
    )

# ── Active window: 10:00 AM – 2:00 PM ET ────────────────────────────────────
def in_window() -> bool:
    t = ny_now()
    start = t.replace(hour=10, minute=0,  second=0, microsecond=0)
    end   = t.replace(hour=14, minute=0,  second=0, microsecond=0)
    return start <= t <= end

# ── Paths ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.expanduser("~/Documents")
CHART_DIR  = os.path.join(OUTPUT_DIR, "tjl_charts")
STATE_FILE = os.path.join(OUTPUT_DIR, "strategy_scanner_state.json")

# ── TJL strategy params ──────────────────────────────────────────────────────
EMA_FAST   = 9
EMA_SLOW   = 20
EMA_BIAS   = 50
ATR_LEN    = 14
SL_MULT    = 1.5
TP_MULT    = 3.0
PMH_BUF    = 0.10
USE_PMH    = True
CUTOFF_HHMM = 1400   # no new entries after 2 PM

# ── Check optional deps ──────────────────────────────────────────────────────
try:
    import pandas as pd
    import yfinance as yf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_DEPS = True
except ImportError as _e:
    HAS_DEPS = False
    print(f"[warn] Missing deps ({_e}). "
          "Run: pip3 install yfinance pandas matplotlib --break-system-packages")


# ═══════════════════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════
def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _atr(high, low, close, period=14):
    prev = close.shift(1)
    tr   = pd.concat(
        [(high - low), (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ═══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_intraday(ticker: str, days: int = 7):
    """5-min bars for last `days` days, ET-localised, incl. pre-market for PMH."""
    today = date.today()
    start = today - timedelta(days=days)
    try:
        df = yf.download(
            ticker,
            start=str(start),
            end=str(today + timedelta(days=1)),
            interval="5m",
            prepost=True,
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        print(f"    yfinance error: {e}")
        return None

    if df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(ET)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# REGIME FILTER  (SPY & QQQ both above previous day close, latched at 10:00 ET)
# ═══════════════════════════════════════════════════════════════════════════════
_regime_cache: dict = {}

def check_regime() -> bool:
    today_str = date.today().isoformat()
    if today_str in _regime_cache:
        return _regime_cache[today_str]

    now_et = ny_now()
    if now_et.hour * 100 + now_et.minute < 1000:
        return True   # before latch time → allow through

    results = []
    for sym in ("SPY", "QQQ"):
        try:
            df = fetch_intraday(sym, days=5)
            if df is None or df.empty:
                results.append(True)
                continue

            today = date.today()
            df["et_date"] = df.index.date
            df["hhmm"]    = df.index.hour * 100 + df.index.minute
            is_reg = (df["hhmm"] >= 930) & (df["hhmm"] < 1600)

            prev_close_df = df[df["et_date"] < today]
            if prev_close_df.empty:
                results.append(True)
                continue
            prev_close = float(prev_close_df["Close"].iloc[-1])

            today_reg = df[(df["et_date"] == today) & is_reg]
            if today_reg.empty:
                results.append(True)
                continue
            current = float(today_reg["Close"].iloc[-1])

            results.append(current > prev_close)
        except Exception:
            results.append(True)   # fail-open

    ok = all(results)
    _regime_cache[today_str] = ok
    return ok


# ═══════════════════════════════════════════════════════════════════════════════
# TJL SIGNAL DETECTION
# ═══════════════════════════════════════════════════════════════════════════════
def check_tjl_signal(df, regime_ok: bool) -> dict | None:
    """
    Scan today's bars for the most recent TJL entry signal.
    Returns a signal dict (includes the enriched DataFrame) or None.
    """
    today = date.today()
    df    = df.copy()

    # Indicators
    df["ema_f"] = _ema(df["Close"], EMA_FAST)
    df["ema_s"] = _ema(df["Close"], EMA_SLOW)
    df["ema_b"] = _ema(df["Close"], EMA_BIAS)
    df["atr"]   = _atr(df["High"], df["Low"], df["Close"], ATR_LEN)
    df["hhmm"]  = df.index.hour * 100 + df.index.minute
    df["et_date"] = df.index.date
    df["is_pre"]  = (df["hhmm"] >= 400) & (df["hhmm"] < 930)
    df["is_reg"]  = (df["hhmm"] >= 930) & (df["hhmm"] < 1600)

    # PMH: max pre-market high for today
    pre = df[(df["et_date"] == today) & df["is_pre"]]
    pmh = float(pre["High"].max()) if not pre.empty else None
    pmh_level = (pmh + PMH_BUF) if pmh else None

    # Crossover + pullback flags
    df["crossover"] = (
        (df["Close"].shift(1) <= df["ema_f"].shift(1)) &
        (df["Close"] > df["ema_f"])
    )
    df["pb_low"]     = df["Low"].rolling(4).min()
    df["pb_touched"] = df["pb_low"] <= df["ema_f"] * 1.002
    df["join"]       = df["crossover"] & df["pb_touched"]

    # Regime pass (if regime fails, skip entry)
    if not regime_ok:
        return None

    # Scan today's regular session bars before cutoff (newest first)
    today_reg = df[
        (df["et_date"] == today) &
        df["is_reg"] &
        (df["hhmm"] < CUTOFF_HHMM)
    ]
    if today_reg.empty:
        return None

    for row in today_reg.iloc[::-1].itertuples():
        if pd.isna(row.ema_f) or pd.isna(row.atr) or float(row.atr) <= 0:
            continue

        trend_up = (
            float(row.Close) > float(row.ema_s) and
            float(row.ema_f) > float(row.ema_s) and
            float(row.ema_s) > float(row.ema_b)
        )
        if not trend_up:
            continue
        if not row.join:
            continue
        if USE_PMH and pmh_level is not None and float(row.Close) <= pmh_level:
            continue

        entry = round(float(row.Close) + 0.02, 2)
        atr   = float(row.atr)
        return {
            "signal_time": str(row.Index),
            "entry": entry,
            "sl":    round(entry - SL_MULT * atr, 2),
            "tp":    round(entry + TP_MULT * atr, 2),
            "atr":   round(atr, 4),
            "pmh":   round(pmh, 2) if pmh else None,
            "df":    df,
            "today": today,
        }

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# CHART GENERATION
# ═══════════════════════════════════════════════════════════════════════════════
def generate_chart(ticker: str, signal: dict, regime_ok: bool) -> str | None:
    """Save a dark-theme candlestick chart with EMA overlays and level lines."""
    try:
        os.makedirs(CHART_DIR, exist_ok=True)
        df    = signal["df"]
        today = signal["today"]

        plot_df = df[(df["et_date"] == today) & df["is_reg"]].copy()
        if plot_df.empty:
            return None

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 8),
            gridspec_kw={"height_ratios": [3, 1]},
            facecolor="#0d1117",
        )
        for ax in (ax1, ax2):
            ax.set_facecolor("#0d1117")
            ax.tick_params(colors="#9e9e9e")
            for spine in ax.spines.values():
                spine.set_color("#2d2d2d")

        x     = range(len(plot_df))
        times = [t.strftime("%H:%M") for t in plot_df.index]

        # ── Candlesticks ─────────────────────────────────────────────────────
        for i, (_, row) in enumerate(plot_df.iterrows()):
            o, c, h, l = row["Open"], row["Close"], row["High"], row["Low"]
            col = "#26a69a" if c >= o else "#ef5350"
            ax1.plot([i, i], [l, h], color=col, linewidth=0.8)
            ax1.bar(i, abs(c - o), bottom=min(o, c),
                    color=col, width=0.6, linewidth=0)

        # ── EMAs ─────────────────────────────────────────────────────────────
        ax1.plot(x, plot_df["ema_f"].values, color="#2196F3",
                 linewidth=1.3, label=f"EMA {EMA_FAST}")
        ax1.plot(x, plot_df["ema_s"].values, color="#FF9800",
                 linewidth=1.3, label=f"EMA {EMA_SLOW}")
        ax1.plot(x, plot_df["ema_b"].values, color="#9C27B0",
                 linewidth=1.3, label=f"EMA {EMA_BIAS}")

        # ── PMH ──────────────────────────────────────────────────────────────
        if signal["pmh"]:
            ax1.axhline(signal["pmh"] + PMH_BUF, color="#4CAF50",
                        linewidth=1.0, linestyle="--",
                        label=f"PMH {signal['pmh']:.2f}")

        # ── Entry / SL / TP ──────────────────────────────────────────────────
        ax1.axhline(signal["entry"], color="#00E676", linewidth=1.5,
                    linestyle="-",  label=f"Entry {signal['entry']:.2f}")
        ax1.axhline(signal["sl"],   color="#FF5252", linewidth=1.2,
                    linestyle="--", label=f"SL    {signal['sl']:.2f}")
        ax1.axhline(signal["tp"],   color="#00BCD4", linewidth=1.2,
                    linestyle="--", label=f"TP    {signal['tp']:.2f}")

        # ── Signal arrow ─────────────────────────────────────────────────────
        sig_ts  = pd.Timestamp(signal["signal_time"])
        sig_idx = next((i for i, t in enumerate(plot_df.index) if t >= sig_ts), None)
        if sig_idx is not None:
            ax1.annotate(
                "▲ TJL",
                xy=(sig_idx, signal["entry"]),
                xytext=(sig_idx, signal["entry"] - signal["atr"]),
                color="#00E676", fontsize=9, ha="center",
                arrowprops=dict(arrowstyle="->", color="#00E676"),
            )

        # ── Volume ───────────────────────────────────────────────────────────
        vol_colors = [
            "#26a69a" if plot_df["Close"].iloc[i] >= plot_df["Open"].iloc[i]
            else "#ef5350"
            for i in range(len(plot_df))
        ]
        ax2.bar(x, plot_df["Volume"].values, color=vol_colors, width=0.6)
        ax2.set_ylabel("Volume", color="#9e9e9e", fontsize=8)

        # ── X-axis labels ────────────────────────────────────────────────────
        step = max(1, len(times) // 12)
        ax1.set_xticks([])
        ax2.set_xticks(range(0, len(times), step))
        ax2.set_xticklabels(times[::step], rotation=45, fontsize=7, color="#9e9e9e")

        # ── Legend + title ───────────────────────────────────────────────────
        regime_str = "Regime OK" if regime_ok else "Regime FAIL"
        ax1.legend(loc="upper left", fontsize=8,
                   facecolor="#1a1a2e", labelcolor="white", framealpha=0.8)
        ax1.set_title(
            f"{ticker}  —  TJL Signal  |  {today}  |  {regime_str}",
            color="white", fontsize=12, pad=8,
        )
        ax1.set_ylabel("Price", color="#9e9e9e", fontsize=9)

        plt.tight_layout(pad=1.5)

        ts    = datetime.now().strftime("%H%M")
        fname = os.path.join(CHART_DIR, f"{ticker}_TJL_{today}_{ts}.png")
        plt.savefig(fname, dpi=120, bbox_inches="tight", facecolor="#0d1117")
        plt.close()
        return fname

    except Exception as e:
        print(f"    [warn] Chart failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION
# ═══════════════════════════════════════════════════════════════════════════════
def notify(title: str, subtitle: str, body: str, chart_path: str | None = None):
    def esc(s):
        return str(s).replace("\\", "\\\\").replace('"', '\\"')

    script = (
        f'display notification "{esc(body)}" '
        f'with title "{esc(title)}" '
        f'subtitle "{esc(subtitle)}" '
        f'sound name "Blow"'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception as e:
        print(f"  [warn] Notification failed: {e}")

    # Open the chart in Preview automatically
    if chart_path and os.path.exists(chart_path):
        try:
            subprocess.Popen(["open", chart_path])
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════════════════════
def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# LOAD GAPPERS
# ═══════════════════════════════════════════════════════════════════════════════
def load_gappers_from_file() -> list:
    """Read today's gapper list from premarket_gappers_YYYY-MM-DD.json.
    Tries today then yesterday to handle HKT midnight rollover."""
    for delta in (0, -1):
        d    = (date.today() + timedelta(days=delta)).isoformat()
        path = os.path.join(OUTPUT_DIR, f"premarket_gappers_{d}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                gappers = data.get("gappers", [])
                if gappers:
                    print(f"  Loaded {len(gappers)} gappers from premarket_gappers_{d}.json")
                    return gappers
                print(f"  [warn] {path} has no gappers.")
            except Exception as e:
                print(f"  [warn] Cannot read {path}: {e}")
    print("  [warn] No premarket gappers file found.")
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    now_ny = ny_now()
    today  = date.today().isoformat()
    run_ts = now_ny.strftime("%H:%M ET")

    if not in_window():
        print(f"[{run_ts}] Outside 10 AM–2 PM ET. Exiting.")
        sys.exit(0)

    print(f"[{run_ts}] TJL Scanner firing …")

    # ── State ─────────────────────────────────────────────────────────────────
    state = load_state()
    if state.get("date") != today:
        state = {"date": today, "first_run_done": False, "notified": []}

    # ── Gappers ───────────────────────────────────────────────────────────────
    gappers = load_gappers_from_file()
    if not gappers:
        if not state.get("first_run_done"):
            notify("TJL Scanner", f"First scan · {run_ts}", "No gappers file found.")
            state["first_run_done"] = True
        save_state(state)
        sys.exit(0)

    # ── Regime ────────────────────────────────────────────────────────────────
    regime_ok = True
    if HAS_DEPS:
        print("Checking SPY/QQQ regime …", end=" ", flush=True)
        try:
            regime_ok = check_regime()
            print("OK" if regime_ok else "FAIL")
        except Exception as e:
            print(f"error ({e}) — defaulting to OK")

    # ── Scan each gapper ──────────────────────────────────────────────────────
    hits: list[dict] = []
    if HAS_DEPS:
        for g in gappers:
            ticker = g["symbol"]
            print(f"  {ticker:<6}", end=" ", flush=True)
            try:
                df = fetch_intraday(ticker)
                if df is None:
                    print("no data")
                    continue
                sig = check_tjl_signal(df, regime_ok)
                if sig is None:
                    print("—")
                    continue
                chart = generate_chart(ticker, sig, regime_ok)
                hit = {
                    "symbol":     ticker,
                    "gap_pct":    g.get("gap_pct", 0),
                    "catalyst":   g.get("catalyst"),
                    "entry":      sig["entry"],
                    "sl":         sig["sl"],
                    "tp":         sig["tp"],
                    "atr":        sig["atr"],
                    "pmh":        sig["pmh"],
                    "signal_time": sig["signal_time"],
                    "regime_ok":  regime_ok,
                    "chart_path": chart,
                }
                hits.append(hit)
                print(f"SIGNAL  entry={sig['entry']:.2f}  SL={sig['sl']:.2f}  TP={sig['tp']:.2f}"
                      + (f"  chart→{os.path.basename(chart)}" if chart else ""))
            except Exception as e:
                print(f"error: {e}")

    # ── Save scan log ─────────────────────────────────────────────────────────
    log_path = os.path.join(OUTPUT_DIR, f"strategy_scanner_{today}.json")
    with open(log_path, "w") as f:
        json.dump({
            "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "regime_ok":  regime_ok,
            "gappers":    len(gappers),
            "hits":       [{k: v for k, v in h.items() if k != "df"} for h in hits],
        }, f, indent=2, default=str)

    # ── Smart notifications ───────────────────────────────────────────────────
    notified     = set(state.get("notified", []))
    new_hits     = [h for h in hits if h["symbol"] not in notified]
    regime_label = "Regime OK" if regime_ok else "Regime FAIL"

    def _tg_hits_message(hit_list, header):
        """Build the 🎯 TJL Watchlist Telegram message."""
        lines = [f"🎯 *TJL Watchlist* — {run_ts}"]
        if hit_list:
            for h in hit_list:
                pmh_str = f", PMH ${h['pmh']:.2f}" if h.get("pmh") else ""
                lines.append(
                    f"• {h['symbol']} @ ${h['entry']:.2f}"
                    f" (SL ${h['sl']:.2f}, TP ${h['tp']:.2f}{pmh_str})"
                    f" +{h['gap_pct']:.1f}%"
                )
        else:
            lines.append("No TJL hits this run.")
        lines.append(f"_{regime_label}_")
        return "\n".join(lines)

    if not state.get("first_run_done"):
        # First run of the day — always notify regardless of hits
        if hits:
            h    = hits[0]
            body = (f"{len(hits)} signal(s) | {h['symbol']} +{h['gap_pct']:.1f}% "
                    f"entry {h['entry']:.2f} / SL {h['sl']:.2f} / TP {h['tp']:.2f} | {regime_label}")
            notify("TJL Scanner", f"First scan · {run_ts}", body, h.get("chart_path"))
        else:
            body = f"No TJL setups in {len(gappers)} gappers | {regime_label}"
            notify("TJL Scanner", f"First scan · {run_ts}", body)
        send_telegram(_tg_hits_message(hits, "First scan"))
        state["first_run_done"] = True
        print(f"Notified (first run): {body}")

    elif hits:
        # Subsequent runs — always notify if there are hits (entry prices change each run)
        for h in hits:
            label = "▲ New" if h["symbol"] not in notified else "↻ Update"
            body = (f"{h['symbol']} +{h['gap_pct']:.1f}% | "
                    f"entry {h['entry']:.2f}  SL {h['sl']:.2f}  TP {h['tp']:.2f} | {regime_label}")
            notify(f"TJL Signal {label}", f"{run_ts}", body, h.get("chart_path"))
            print(f"Notified ({label}): {body}")
        notified |= {h["symbol"] for h in hits}
        send_telegram(_tg_hits_message(hits, "Updated hits"))

    else:
        # No hits this run — stay silent
        print(f"Silent — 0 hits, {len(gappers)} gappers scanned.")

    # ── Update state ──────────────────────────────────────────────────────────
    state["notified"]    = sorted(notified | {h["symbol"] for h in hits})
    state["last_run_ny"] = run_ts
    save_state(state)

    top3  = hits[:3]
    parts = [f"{h['symbol']} ({h['gap_pct']:.1f}%)" for h in top3]
    print(f"Done — {len(hits)} TJL hit(s) / {len(gappers)} gappers | {', '.join(parts) or '—'}")


if __name__ == "__main__":
    main()
