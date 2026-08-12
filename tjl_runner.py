#!/usr/bin/env python3
"""Cron-friendly TJL HK scanner runner. Imports and runs tjl_live_futu.py as a module."""
import sys, os
os.chdir("/Users/jaydensmac/.openclaw/workspace")
sys.path.insert(0, "/Users/jaydensmac/.openclaw/workspace")
# Load and exec the main module
src = open("/Users/jaydensmac/.openclaw/workspace/tjl_live_futu.py").read()
# Strip the shebang line if any
if src.startswith("#!"):
    src = "\n".join(src.split("\n")[1:])
g = {"__name__": "__main__", "__file__": "/Users/jaydensmac/.openclaw/workspace/tjl_live_futu.py"}
exec(compile(src, "/Users/jaydensmac/.openclaw/workspace/tjl_live_futu.py", "exec"), g)
