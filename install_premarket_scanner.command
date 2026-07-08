#!/bin/bash
# ── Premarket Gappers Scanner — one-click installer ──────────────────────────
# Double-click this file in Finder to install.
# It copies the scanner script, installs the launchd plist, and loads the job.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER_SRC="$SCRIPT_DIR/premarket_gappers_scanner.py"
PLIST_SRC="$SCRIPT_DIR/com.bruce.premarket-gappers.plist"
DEST_DIR="$HOME/Documents"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST_LABEL="com.bruce.premarket-gappers"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Premarket Gappers Scanner — Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Copy scanner script
echo ""
echo "[1/3] Copying scanner → $DEST_DIR/premarket_gappers_scanner.py"
cp "$SCANNER_SRC" "$DEST_DIR/premarket_gappers_scanner.py"
chmod +x "$DEST_DIR/premarket_gappers_scanner.py"
echo "      ✓ Done"

# 2. Install plist
echo ""
echo "[2/3] Installing launchd plist → $LAUNCH_AGENTS/$PLIST_LABEL.plist"
mkdir -p "$LAUNCH_AGENTS"
cp "$PLIST_SRC" "$LAUNCH_AGENTS/$PLIST_LABEL.plist"
echo "      ✓ Done"

# 3. Load the job (unload first in case it was already loaded)
echo ""
echo "[3/3] Loading launchd job …"
launchctl unload "$LAUNCH_AGENTS/$PLIST_LABEL.plist" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS/$PLIST_LABEL.plist"
echo "      ✓ Done"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  Installation complete!"
echo ""
echo "  Scanner fires every morning at 06:00 (local time)."
echo "  Output:  ~/Documents/premarket_gappers_YYYY-MM-DD.json"
echo "  Logs:    ~/Documents/premarket_gappers.log"
echo ""
echo "  To verify:  launchctl list | grep premarket"
echo "  To unload:  launchctl unload ~/Library/LaunchAgents/$PLIST_LABEL.plist"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  (This window will close in 10 seconds)"
sleep 10
