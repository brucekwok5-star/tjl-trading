#!/usr/bin/env python3
"""
premarket_gappers_scanner.py
────────────────────────────
Fetches Yahoo Finance pre-market gainers, applies filters, enriches each
ticker with a Google News RSS catalyst, then writes:

    ./premarket_gappers_YYYY-MM-DD.json

Filters:  gap_pct > 5 %  |  price > $3  |  premarket_volume > 50 000
Cap:      top 10 by gap_pct descending
Runtime:  ~60-90 s (Benzinga calls are sequential with a polite 1.2 s delay)

Usage:    python3 premarket_gappers_scanner.py
          ./premarket_gappers_scanner.py   (after chmod +x)
"""

import html as html_module
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone


# ── .env loader ──────────────────────────────────────────────────────────────
def _load_dotenv():
    """Load KEY=VALUE pairs from .env (same dir as this script) into os.environ."""
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

# ── Configuration ────────────────────────────────────────────────────────────
YAHOO_GAINERS_URL = "https://finance.yahoo.com/markets/stocks/gainers/"
MIN_GAP_PCT       = 5.0
MIN_PRICE         = 3.0
MIN_VOLUME        = 50_000
TOP_N             = 10
FETCH_TIMEOUT     = 20   # seconds per request
CATALYST_TIMEOUT  = 15
INTER_REQUEST_S   = 1.2  # politeness delay between Benzinga calls

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}


# ── HTTP helper ───────────────────────────────────────────────────────────────
def fetch(url: str, timeout: int = FETCH_TIMEOUT) -> str:
    import gzip, zlib
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw)
        elif enc == "br":
            try:
                import brotli
                raw = brotli.decompress(raw)
            except ImportError:
                pass  # best-effort; brotli may not be installed
        return raw.decode("utf-8", errors="replace")


# ── Yahoo Finance parser ──────────────────────────────────────────────────────
def _raw(v):
    """Unwrap Yahoo's {raw: x, fmt: '...'} wrapper or return scalar."""
    if isinstance(v, dict):
        return v.get("raw", 0)
    return v if v is not None else 0


def _extract_stock(item: dict):
    """Pull symbol / price / gap_pct / volume from one JSON object."""
    if not isinstance(item, dict):
        return None

    sym = item.get("symbol") or item.get("ticker") or ""
    # Only plain equity tickers (no exchange prefix, no spaces)
    if not re.match(r'^[A-Z]{1,5}$', sym):
        return None

    price = _raw(
        item.get("regularMarketPrice")
        or item.get("preMarketPrice")
        or item.get("price")
        or item.get("lastPrice")
    )
    pct = _raw(
        item.get("regularMarketChangePercent")
        or item.get("preMarketChangePercent")
        or item.get("changePercent")
    )
    vol = _raw(
        item.get("regularMarketVolume")
        or item.get("preMarketVolume")
        or item.get("volume")
    )

    if not price or pct == 0:
        return None

    return {
        "symbol":           sym,
        "price":            float(price),
        "gap_pct":          float(pct),
        "premarket_volume": int(vol),
    }


def _search_json(obj, depth=0, seen=None):
    """
    Recursively walk a JSON blob looking for lists whose items all have a
    'symbol' key — that's a stock table.
    """
    if seen is None:
        seen = set()
    oid = id(obj)
    if oid in seen or depth > 25:
        return []
    seen.add(oid)

    if isinstance(obj, list) and len(obj) >= 2:
        sample = obj[:4]
        if all(isinstance(x, dict) and "symbol" in x for x in sample):
            return [obj]   # found a candidate; don't recurse into it
        results = []
        for item in obj:
            results.extend(_search_json(item, depth + 1, seen))
        return results

    if isinstance(obj, dict):
        results = []
        for v in obj.values():
            results.extend(_search_json(v, depth + 1, seen))
        return results

    return []


def parse_yahoo_gainers(page_html: str):
    """Return list of stock dicts from Yahoo Finance gainers page."""

    # ── Strategy 1: __NEXT_DATA__ JSON blob ──────────────────────────────
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page_html, re.DOTALL
    )
    if m:
        try:
            data = json.loads(m.group(1))
            candidates = _search_json(data)
            if candidates:
                best = max(candidates, key=len)
                stocks = [_extract_stock(s) for s in best]
                stocks = [s for s in stocks if s]
                if stocks:
                    return stocks
        except Exception:
            pass

    # ── Strategy 2: any embedded JSON array with "symbol" keys ───────────
    for blob in re.findall(r'\[(\{"symbol"\s*:.*?\})\]', page_html, re.DOTALL):
        try:
            items = json.loads("[" + blob + "]")
            stocks = [_extract_stock(s) for s in items]
            stocks = [s for s in stocks if s]
            if stocks:
                return stocks
        except Exception:
            pass

    # ── Strategy 3: scan ALL script tags for JSON arrays ─────────────────
    for script_body in re.findall(r'<script[^>]*>(.*?)</script>', page_html, re.DOTALL):
        for array_match in re.finditer(r'(\[[\s\S]{50,}\])', script_body):
            try:
                items = json.loads(array_match.group(1))
                if not isinstance(items, list):
                    continue
                stocks = [_extract_stock(s) for s in items]
                stocks = [s for s in stocks if s]
                if len(stocks) >= 5:  # needs to look like a real table
                    return stocks
            except Exception:
                pass

    return []


# ── Yahoo Finance quote API — volume enrichment ───────────────────────────────
YAHOO_QUOTE_HOSTS = [
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]

def _fetch_quote_api(symbols: str, fields: str) -> dict:
    """Try both Yahoo query hosts with one retry on 429."""
    import gzip, zlib

    api_headers = {
        **HEADERS,
        "Accept": "application/json",
        # slightly different UA to reduce fingerprint overlap with page fetch
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    last_err = None
    for host in YAHOO_QUOTE_HOSTS:
        url = f"{host}/v7/finance/quote?symbols={symbols}&fields={fields}"
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers=api_headers)
                with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                    raw = r.read()
                    enc = r.headers.get("Content-Encoding", "")
                    if enc == "gzip":    raw = gzip.decompress(raw)
                    elif enc == "deflate": raw = zlib.decompress(raw)
                    return json.loads(raw.decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429 and attempt == 0:
                    time.sleep(3)   # back off, then retry once
                    continue
                break  # non-429 error → try next host
            except Exception as e:
                last_err = e
                break

    raise RuntimeError(f"All quote API attempts failed: {last_err}")


def enrich_with_volume(stocks: list) -> list:
    """
    Batch-call Yahoo's v7 quote API to fill in regularMarketVolume /
    preMarketVolume for each stock. The gainers page HTML omits volume,
    so this is a required second step.

    Falls back gracefully: if both hosts are rate-limited the warning is
    printed and volume stays 0. The caller can then relax the volume filter.
    """
    if not stocks:
        return stocks

    symbols = ",".join(s["symbol"] for s in stocks)
    fields  = "regularMarketVolume,preMarketVolume,averageVolume"

    try:
        data    = _fetch_quote_api(symbols, fields)
        results = data.get("quoteResponse", {}).get("result", [])
        vol_map = {}
        for item in results:
            sym = item.get("symbol", "")
            # During premarket hours prefer preMarketVolume; otherwise regularMarketVolume
            vol = (item.get("preMarketVolume")
                   or item.get("regularMarketVolume")
                   or item.get("averageVolume")
                   or 0)
            vol_map[sym] = int(_raw(vol))

        for s in stocks:
            s["premarket_volume"] = vol_map.get(s["symbol"], 0)

    except Exception as e:
        print(f"  [warn] Volume enrichment failed ({e}) — volume filter bypassed")

    return stocks


# ── News catalyst fetcher (Google News RSS) ───────────────────────────────────
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q={ticker}+stock"

def _clean(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html_module.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def get_catalyst(ticker: str):
    """
    Query Google News RSS for '{ticker} stock' and return:
      catalyst  – first headline as a one-sentence string, or None
      headlines – up to 2 verbatim article titles

    Never raises; returns (None, []) on any error.
    Source: news.google.com/rss — public, no auth, no JS rendering needed.
    """
    url = GOOGLE_NEWS_RSS.format(ticker=ticker)
    try:
        req = urllib.request.Request(url, headers={
            **HEADERS,
            "Accept": "application/rss+xml, application/xml, text/xml",
        })
        with urllib.request.urlopen(req, timeout=CATALYST_TIMEOUT) as r:
            import gzip as _gz, zlib as _zl
            raw = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":    raw = _gz.decompress(raw)
            elif enc == "deflate": raw = _zl.decompress(raw)
            rss = raw.decode("utf-8", errors="replace")
    except Exception:
        return None, []

    headlines = []
    for item in re.findall(r'<item>(.*?)</item>', rss, re.DOTALL)[:5]:
        m = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
        if not m:
            continue
        title = _clean(m.group(1))
        # Strip "- Source Name" suffix that Google appends
        title = re.sub(r'\s*-\s*[^-]{1,40}$', '', title).strip()
        if title and len(title) > 15 and title not in headlines:
            headlines.append(title)
        if len(headlines) >= 2:
            break

    catalyst = (headlines[0][:150] + "…" if len(headlines[0]) > 150 else headlines[0]) \
               if headlines else None
    return catalyst, headlines


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today_str = date.today().isoformat()
    outfile   = f"premarket_gappers_{today_str}.json"

    # ── Step 1: Fetch Yahoo Finance ───────────────────────────────────────
    print(f"[1/3] Fetching Yahoo Finance gainers …")
    try:
        page_html = fetch(YAHOO_GAINERS_URL)
    except urllib.error.HTTPError as e:
        sys.exit(f"ERROR: Yahoo Finance returned HTTP {e.code}")
    except Exception as e:
        sys.exit(f"ERROR fetching Yahoo Finance: {e}")

    # ── Step 2: Parse & filter ────────────────────────────────────────────
    print("[2/3] Parsing & filtering …")
    all_stocks = parse_yahoo_gainers(page_html)

    if not all_stocks:
        # Save a debug snippet to help diagnose page structure changes
        debug_path = f"debug_yahoo_{today_str}.html"
        with open(debug_path, "w") as df:
            df.write(page_html[:8000])
        sys.exit(
            f"ERROR: Parsed 0 stocks from Yahoo Finance.\n"
            f"Page structure may have changed. First 8 KB saved to {debug_path}"
        )

    # Enrich with volume via Yahoo's quote API (not present in page HTML)
    print(f"  Enriching {len(all_stocks)} tickers with volume data …")
    all_stocks = enrich_with_volume(all_stocks)

    volume_available = any(s["premarket_volume"] > 0 for s in all_stocks)
    filtered = [
        s for s in all_stocks
        if s["gap_pct"] > MIN_GAP_PCT
        and s["price"]  > MIN_PRICE
        and (not volume_available or s["premarket_volume"] > MIN_VOLUME)
    ]
    if not volume_available:
        print("  [warn] Volume data unavailable — volume filter skipped")
    filtered.sort(key=lambda x: x["gap_pct"], reverse=True)
    top = filtered[:TOP_N]

    print(
        f"  Parsed: {len(all_stocks)} total  |  "
        f"Passing filters: {len(filtered)}  |  "
        f"Taking top: {len(top)}"
    )

    if not top:
        print("No stocks passed the filters today. Writing empty result.")
        gappers = []
    else:
        # ── Step 3: Benzinga catalysts ────────────────────────────────────
        print(f"[3/3] Fetching catalysts ({len(top)} tickers) …")
        gappers = []
        for i, s in enumerate(top, 1):
            ticker = s["symbol"]
            print(f"  [{i:2d}/{len(top)}] {ticker:<6}", end="", flush=True)
            try:
                catalyst, headlines = get_catalyst(ticker)
                status = "ok" if catalyst else "no catalyst found"
            except Exception as exc:
                catalyst, headlines = None, []
                status = f"error: {exc}"
            print(f"  {status}")

            gappers.append({
                "rank":             i,
                "symbol":           ticker,
                "price":            round(s["price"], 2),
                "gap_pct":          round(s["gap_pct"], 2),
                "premarket_volume": s["premarket_volume"],
                "catalyst":         catalyst,
                "headlines":        headlines,
            })

            if i < len(top):
                time.sleep(INTER_REQUEST_S)

    # ── Write JSON output ─────────────────────────────────────────────────
    output = {
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gappers":    gappers,
    }
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved → {outfile}")

    # ── Telegram notification (every run) ─────────────────────────────────
    lines = [f"📊 *Premarket Gappers* — {today_str}"]
    for g in gappers:
        line = f"• {g['symbol']} ${g['price']:.2f} +{g['gap_pct']:.1f}%"
        if g.get("catalyst"):
            line += f" — {g['catalyst'][:120]}"
        lines.append(line)
    if not gappers:
        lines.append("No stocks passed filters today.")
    send_telegram("\n".join(lines))

    # ── One-line summary ──────────────────────────────────────────────────
    top3 = gappers[:3]
    parts = [
        "{} ({:.1f}%) — {}".format(
            g["symbol"],
            g["gap_pct"],
            (g["catalyst"] or "no catalyst")[:60],
        )
        for g in top3
    ]
    n = len(gappers)
    suffix = (", ".join(parts)) if parts else "—"
    print(f"Premarket Gappers: {n} name{'s' if n != 1 else ''}. Top: {suffix}")


if __name__ == "__main__":
    main()
