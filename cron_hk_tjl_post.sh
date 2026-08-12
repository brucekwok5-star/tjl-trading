#!/bin/bash
# Build and post Discord embed for TJL HK scan
set -e
export PATH="/usr/bin:/bin:$PATH"
export DISCORD_WEBHOOK_HK_TJL='https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj'

# Build the payload
PAYLOAD=$(env python3 - <<'PYEOF'
import json
with open("/Users/jaydensmac/tjl_live_signals_2026-08-10.json") as f:
    data = json.load(f)
signals = data.get("signals", [])
longs = [s for s in signals if s.get("direction") == "LONG"]
shorts = [s for s in signals if s.get("direction") == "SHORT"]
regime = data.get("regime", "?").upper()
bull_pct = data.get("bull_pct", 0)
bear_pct = data.get("bear_pct", 0)
scanned_at = data.get("scanned_at", "?")

def fmt(s):
    return f"**{s.get('name','?')}** (M:{s.get('signal_model','?')}) @ {s.get('price',0):.2f}  SL {s.get('sl',0):.2f}  TP {s.get('tp',0):.2f}  R:R 1:{s.get('rr_ratio',0)}"

long_lines = "\n".join([fmt(s) for s in longs[:10]]) or "_(none)_"
short_lines = "\n".join([fmt(s) for s in shorts[:10]]) or "_(none)_"

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
    "color": 0x1F77B4,
    "footer": {"text": "Source: Futu OpenD · Hermes TJL HK scanner"},
}
payload = {
    "thread_name": "HK TJL Live 2026-08-10",
    "content": f"📊 TJL HK scan — {len(longs)} LONG / {len(shorts)} SHORT — regime {regime}",
    "embeds": [embed],
}
print(json.dumps(payload))
PYEOF
)

# POST to Discord
curl -s -w "\nHTTP_CODE:%{http_code}\n" -X POST "$DISCORD_WEBHOOK_HK_TJL" \
  -H "Content-Type: application/json" \
  --data "$PAYLOAD"
echo "Done"