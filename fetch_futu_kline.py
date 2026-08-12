#!/usr/bin/env python3
"""Fetch HK oil & gas stock kline data from Futu OpenAPI"""
from futu import OpenQuoteContext, SubType, KLType, AuType
import json, time

STOCKS = ['HK.00568', 'HK.02178', 'HK.01033', 'HK.01921', 'HK.00883']
SHORT_CODES = ['568', '2178', '1033', '1921', '883']

# Map: subscription subtype -> (KLType for get_cur_kline, output key)
KL_MAP = [
    (SubType.K_5M,  KLType.K_5M,  '5m'),
    (SubType.K_15M, KLType.K_15M, '15m'),
    (SubType.K_60M, KLType.K_60M, '1h'),
    (SubType.K_DAY, KLType.K_DAY, '1D'),
]

host = '127.0.0.1'
port = 11111

def fetch_all():
    all_data = {}
    
    for sc in SHORT_CODES:
        all_data[sc] = {}
    
    try:
        quote_ctx = OpenQuoteContext(host=host, port=port)
        print("Connected to FutuOpenD!")
        
        # Subscribe to all
        for stock in STOCKS:
            for sub_type, _, _ in KL_MAP:
                ret, _ = quote_ctx.subscribe(stock, sub_type)
                if ret != 0:
                    print(f"  Subscribe {stock} {sub_type}: FAILED ret={ret}")
                else:
                    print(f"  Subscribe {stock} {sub_type}: OK")
            time.sleep(0.3)
        
        time.sleep(2)  # Wait for data to propagate
        
        # Fetch data
        for i, stock in enumerate(STOCKS):
            short_code = SHORT_CODES[i]
            
            for sub_type, kl_type, tf_name in KL_MAP:
                ret, data = quote_ctx.get_cur_kline(stock, num=100, ktype=kl_type)
                
                if ret != 0:
                    print(f"  ERROR {short_code} {tf_name}: ret={ret} data={data}")
                    all_data[short_code][tf_name] = []
                    continue
                
                # Convert DataFrame to list of candles
                candles = []
                for _, row in data.iterrows():
                    # Parse timestamp from time_key column (format: '2026-06-18 00:00:00')
                    import pandas as pd
                    ts_str = row['time_key']
                    if isinstance(ts_str, str):
                        ts_dt = pd.to_datetime(ts_str)
                        ts_ms = int(ts_dt.timestamp() * 1000)
                    else:
                        ts_ms = 0
                    
                    candle = {
                        'tu': 0,  # not used by analysis script
                        'c': float(row['close']),
                        't': ts_ms,
                        'v': float(row['volume']),
                        'h': float(row['high']),
                        'l': float(row['low']),
                        'o': float(row['open']),
                    }
                    candles.append(candle)
                
                all_data[short_code][tf_name] = candles
                print(f"  {short_code} {tf_name}: {len(candles)} candles")
            
            # 4h: aggregate every 4 candles from 1h data
            h1_data = all_data[short_code].get('1h', [])
            if h1_data:
                # Group 4 x 1h candles into 4h candles
                four_h_candles = []
                for j in range(0, len(h1_data), 4):
                    group = h1_data[j:j+4]
                    if len(group) == 4:
                        cand = {
                            'tu': group[0]['tu'],
                            'o': group[0]['o'],
                            'h': max(c['h'] for c in group),
                            'l': min(c['l'] for c in group),
                            'c': group[-1]['c'],
                            'v': sum(c['v'] for c in group),
                            't': group[-1]['t'],  # use last candle's timestamp
                        }
                        four_h_candles.append(cand)
                all_data[short_code]['4h'] = four_h_candles
                print(f"  {short_code} 4h: {len(four_h_candles)} aggregated candles")
            else:
                all_data[short_code]['4h'] = []
            
            time.sleep(1)
        
        quote_ctx.close()
        
    except Exception as e:
        print(f"Connection error: {e}")
        import traceback; traceback.print_exc()
        return {}
    
    # Save
    out_file = '/Users/jaydensmac/.openclaw/workspace/oil_gas_data/kline_data.json'
    with open(out_file, 'w') as f:
        json.dump(all_data, f)
    print(f"\nSaved to {out_file}")
    return all_data

if __name__ == '__main__':
    fetch_all()
