#!/usr/bin/env python3
"""Fetch HK oil & gas stock data from iTick API"""
import requests
import json
import time
import os
from datetime import datetime

TOKEN = "170f4c55d4f34acb9ac7da099d3a0a78d944e10c43b743aea1a0b1304f7f7413"
HEADERS = {"token": TOKEN}
BASE_URL = "https://api0.itick.org"
OUT_DIR = "/Users/jaydensmac/.openclaw/workspace/oil_gas_data"
os.makedirs(OUT_DIR, exist_ok=True)

STOCKS = ["568", "2178", "1033", "1921", "883"]
KTYPES = {"5m": 2, "15m": 3, "1h": 5, "4h": 4, "1D": 1}

def fetch_kline(code, ktype, limit=100):
    url = f"{BASE_URL}/stock/kline?region=HK&code={code}&kType={ktype}&limit={limit}"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            d = r.json()
            if d.get("code") == 0 and d.get("data"):
                return d["data"]
            print(f"  Warning: {code} kType={ktype} returned {len(d.get('data', []))} points")
            return d.get("data", [])
        except Exception as e:
            print(f"  Error {code} kType={ktype}: {e}")
            time.sleep(3)
    return []

def fetch_all():
    all_data = {}
    total_calls = len(STOCKS) * len(KTYPES)
    call_num = 0
    
    for stock in STOCKS:
        all_data[stock] = {}
        print(f"\n=== Fetching {stock} ===")
        for tf_name, ktype in KTYPES.items():
            call_num += 1
            print(f"  [{call_num}/{total_calls}] {stock} {tf_name}...", end=" ", flush=True)
            data = fetch_kline(stock, ktype)
            all_data[stock][tf_name] = data
            print(f"{len(data)} candles")
            if call_num < total_calls:
                print(f"  ...waiting 12s...")
                time.sleep(12)
    
    # Save
    out_file = os.path.join(OUT_DIR, "kline_data.json")
    with open(out_file, "w") as f:
        json.dump(all_data, f)
    print(f"\nSaved to {out_file}")
    return all_data

if __name__ == "__main__":
    fetch_all()