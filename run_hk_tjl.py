#!/usr/bin/env python3
import sys, os, runpy

# Use system Python 3.9 explicitly — it has the real futu/futuquant.
# Hermes venv python3.11 has a broken futu stub.
_real_futu = "/Users/jaydensmac/Library/Python/3.9/lib/python/site-packages"
if _real_futu not in sys.path:
    sys.path.insert(0, _real_futu)

SCRIPT = os.path.expanduser("~/.openclaw/workspace/tjl_live_futu.py")
if not os.path.exists(SCRIPT):
    print("FATAL: scanner not found", file=sys.stderr)
    sys.exit(2)
sys.argv[0] = SCRIPT
runpy.run_path(SCRIPT, run_name="__main__")
