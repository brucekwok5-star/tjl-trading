#!/usr/bin/env python3
"""Build Discord embed JSON for TJL HK scan results."""
import json
import sys

DATA_PATH = "/Users/jaydensmac/tjl_live_signals_2026-08-10.json"
with open(DATA_PATH) as f:
    data = json.load(f)

signals = data.get("signals", [])
longs = [s for s in signals if s.get("direction") == "LONG"]
shorts = [s for s in signals if s.get("direction") == "SHORT"]

regime = data.get("regime", "?").upper()
bull_pct = data.get("bull_pct", 0)
bear_pct = data.get("bear_pct", 0)
scanned_at = data.get("scanned_at", "?")

def fmt_signal(s):
    name = s.get("name", "?")
    model = s.get("signal_model", "?")
    price = s.get("price", 0)
    sl = s.get("sl", 0)
    tp = s.get("tp", 0)
    rr = s.get("rr_ratio", 0)
    return f"**{name}** (M:{model}) @ {price:.2f}  SL {sl:.2f}  TP {tp:.2f}  R:R 1:{rr}"

long_lines = "\n".join([fmt_signal(s) for s in longs[:10]]) or "_(none)_"
short_lines = "\n".join([fmt_signal(s) for s in shorts[:10]]) or "_(none)_"

# Note: 00002 fires both H and K — they share the same trade, so we de-dupe by
# (ticker, direction) and pick the first model in each pair. The user asked
# for ticker/price/SL/TP/R:R/model so we'll keep duplicates visible.

description = (
    f"**LONG:** {len(longs)}  |  **SHORT:** {len(shorts)}\n"
    f"**Regime:** {regime} (bull={bull_pct}% bear={bear_pct}%)\n"
    f"**Scanned:** {scanned_at}\n"
    f"\n**LONG signals:**\n{long_lines}\n"
    f"\n**SHORT signals:**\n{short_lines}"
)

embed = {
    "title": "TJL HK Live — 2026-08-10",
    "description": description,
    "color": 0x1F77B4,  # muted blue
    "footer": {"text": "Source: Futu OpenD · Hermes TJL HK scanner"},
}

payload = {
    "thread_name": "HK TJL Live 2026-08-10",
    "content": f"📊 *TJL HK scan* — {len(longs)} LONG / {len(shorts)} SHORT — regime {regime}",
    "embeds": [embed],
}

print(json.dumps(payload, indent=2))