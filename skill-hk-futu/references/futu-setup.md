# Futu OpenD Setup

The HK TJL scanner needs a running Futu OpenD instance. This reference covers
install, login, port config, and common failure modes.

## What is Futu OpenD?

**Futu OpenD** (Open Interface Gateway) is Futu Securities' free local gateway
that exposes real-time HK/US/CN market data over a TCP socket. It's the
official way to get free real-time HK stock data programmatically — no API key
required, but **you need a Futu brokerage account**.

**Website:** https://www.futunn.com / https://www.futuhk.com

## Install (macOS)

1. Download Futu OpenD from the official site
2. Install the `.dmg` to `/Applications/FutuOpenD.app`
3. Launch it (will appear in menu bar)
4. Log in with your Futu account credentials
5. Confirm the OpenD is running by checking port 11111 (default):
   ```bash
   lsof -i :11111
   # Should show: Futu OpenD ... TCP 127.0.0.1:11111 (LISTEN)
   ```

If you see no listener, OpenD is not running. Open the app and log in.

## Install (Linux/Windows)

Same binary from the Futu download page. Linux runs the OpenD as a daemon;
Windows as a service. Port and login flow identical.

## Python client

The scanner uses the `futu` Python package. Install:

```bash
pip install futu-api
# or in the Hermes venv:
~/.hermes/hermes-agent/venv/bin/pip install futu-api
```

Verify the install:

```bash
python3 -c "import futu as ft; print('futu', ft.__version__)"
```

## Connection defaults

The scanner uses:
- **Host:** `127.0.0.1`
- **Port:** `11111` (Futu OpenD default)

If you changed the port in OpenD settings, edit the scanner:

```python
# In tjl_live_futu.py line ~222:
ctx = ft.OpenQuoteContext(host='127.0.0.1', port=YOUR_PORT)
```

## Common errors

### `Connection refused` (errno 61)

Futu OpenD is not running. Start it.

### `futu.common.Err.UnknownCode: -1`

Usually means you're not logged in to OpenD, or the OpenD version is older
than the Python `futu-api` client. Update both to latest.

### Quote data empty / subscription failed

- Market is closed (HK is `09:30–16:00 HKT` for normal session, with
  pre-market auction at 09:00–09:30 and closing auction at 16:00–16:10)
- OpenD lost connection — close and re-open
- Account has expired or been suspended

### Code not found

Some codes are HK-listed but not in Futu's default list. Try `ft.SecurityType`
variants, or use the code lookup API:

```python
ret, df = ctx.get_stock_basicinfo(market=ft.Market.HK, stock_type=ft.SecurityType.STOCK)
```

## Local API rate limits

Futu OpenD has per-second call limits. The default `tjl_live_futu.py` does ~40
calls per scan (1 subscribe + 1 quote per ticker, plus 1 history_kline per
ticker). With 35 tickers, that's ~140 calls per scan — well within limits.

For continuous scans at 30s intervals: ~280 calls/min, still safe.

## Adding the `--notify` flag (parity with US scanners)

To add Telegram delivery to the Futu variant, mirror the pattern in
`tjl_live_us.py`:

```python
def notify_telegram(payload):
    """Send HK scan summary to Telegram via `hermes send`."""
    import subprocess
    lines = [
        f"📊 *TJL HK Scan (Futu)* — {payload['scanned_at']}",
        f"Source: Futu OpenD",
        f"Signals: *{len(payload.get('signals', []))}*",
    ]
    if payload.get("signals"):
        lines += ["", "```", f"{'Ticker':<18} {'Price':>8} {'R:R':>5}", "-" * 40]
        for s in sorted(payload["signals"], key=lambda x: -x["rr_ratio"]):
            lines.append(f"{s['name']:<18} {s['price']:>8.2f} {s['rr_ratio']:>5.1f}")
        lines.append("```")
    text = "\n".join(lines)
    try:
        r = subprocess.run(["hermes", "send", "--to", "telegram"],
                           input=text, text=True, capture_output=True, timeout=30)
        log(f"📨 Telegram: {r.stdout.strip() or r.stderr.strip()}")
    except Exception as e:
        log(f"⚠ Telegram delivery failed: {e}")


# Then in run_scan(), at the end:
# if args.notify:
#     notify_telegram({"scanned_at": now_str, "signals": signals})
```

Add the CLI flag in `main()`:

```python
parser.add_argument("--notify", action="store_true", help="Send results to Telegram")
```

And pass `args.notify` through to `run_scan()`.

## Security notes

- Futu OpenD only listens on `127.0.0.1` by default — no external access.
  Don't change this.
- Your Futu account credentials are stored in the OpenD app, not in the
  Python script. The script only needs OpenD to be running and logged in.
- If you script OpenD startup, use the macOS Keychain or a secrets manager
  for the Futu password.
