#!/bin/bash
# ── Strategy Scanner — one-click installer ───────────────────────────────────

set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/Documents"
LA="$HOME/Library/LaunchAgents"
LABEL="com.bruce.strategy-scanner"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Strategy Scanner — Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "[1/3] Copying strategy_scanner.py → $DEST"
cp "$DIR/strategy_scanner.py" "$DEST/strategy_scanner.py"
chmod +x "$DEST/strategy_scanner.py"
echo "      ✓"

echo ""
echo "[2/3] Installing plist → $LA/$LABEL.plist"
mkdir -p "$LA"
cp "$DIR/$LABEL.plist" "$LA/$LABEL.plist"
echo "      ✓"

echo ""
echo "[3/3] Loading launchd job …"
launchctl unload "$LA/$LABEL.plist" 2>/dev/null || true
launchctl load   "$LA/$LABEL.plist"
echo "      ✓"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  Done!"
echo ""
echo "  Fires every 30 min. Active 10:00 AM – 2:00 PM ET."
echo "  Notifications: first run of day + new hits only."
echo "  Log: ~/Documents/strategy_scanner.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
sleep 8
