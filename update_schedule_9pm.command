#!/bin/bash
# Updates the premarket scanner schedule to 9:00 PM HKT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.bruce.premarket-gappers.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.bruce.premarket-gappers.plist"
LABEL="com.bruce.premarket-gappers"

echo "Updating schedule to 9:00 PM HKT …"
cp "$PLIST_SRC" "$PLIST_DEST"
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"
echo "✅ Done — scanner now fires at 21:00 HKT daily."
echo "(This window will close in 5 seconds)"
sleep 5
