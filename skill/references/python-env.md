# Python environment for TJL scanner

The scanner script depends on `yfinance`, `pandas`, and `numpy`. On this Mac, the situation is messy:

```
/usr/bin/python3                         # Python 3.9 — has yfinance + pandas installed BUT numpy wheel is broken
~/.hermes/hermes-agent/venv/bin/python   # Python 3.11 — has numpy 2.4 (works) but NO yfinance/pandas
```

So:
- **`python3` from a fresh shell** → `ImportError: numpy._core._multiarray_umath`
- **Hermes venv python** → no `yfinance` / `pandas` installed

## Diagnose first

Before claiming a scan will work, run this and only proceed if it prints `ok`:

```bash
/usr/bin/python3 -c "import yfinance, pandas, numpy; print('ok')"
```

If it fails with the `_multiarray_umath` ImportError, the system numpy is the wrong wheel. Two fixes:

### Option A — reinstall numpy into system Python

```bash
/usr/bin/python3 -m pip install --user --force-reinstall numpy==2.0.0
/usr/bin/python3 -c "import yfinance, pandas, numpy; print('ok')"
```

Pin to 2.0.0 (not 2.4+) because Python 3.9 wheels for numpy ≥2.1 dropped support.

### Option B — install yfinance/pandas into Hermes venv

```bash
~/.hermes/hermes-agent/venv/bin/pip install yfinance pandas
~/.hermes/hermes-agent/venv/bin/python -c "import yfinance, pandas, numpy; print('ok')"
```

Then use the Hermes venv python to invoke the scanner.

## Which option to pick

- **Pick Option A** if you want to keep using the same Python the user already uses for openclaw workflows — minimal disruption, matches their existing setup.
- **Pick Option B** if the system Python is fundamentally broken for other reasons and you're willing to maintain a separate env for this script.

Either way, **store the working interpreter path** in this file's notes section below so future invocations don't re-diagnose.

## Once you've picked

Set a shell alias for convenience (suggest to the user, don't auto-write their shell rc):

```bash
# In ~/.zshrc or ~/.bashrc:
alias tjl-py='/usr/bin/python3'   # or ~/.hermes/hermes-agent/venv/bin/python
```

Then the skill's invocation snippets become:

```bash
tjl-py ~/.openclaw/workspace/tjl_live_us.py
```

## Working interpreter (recorded)

This was resolved on 2026-08-03 by **Option B** (installing `yfinance`, `pandas` into the Hermes venv):

```
TJL_PY=/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python
```

Verified import test that succeeds:

```bash
/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python -c "import yfinance, pandas, numpy; print('OK')"
# → yfinance 1.5.2 / pandas 3.0.5 / numpy 2.4.3 / OK
```

If a future scan fails with `ModuleNotFoundError`, run `~/.hermes/hermes-agent/venv/bin/pip install yfinance pandas` to recover.

System Python (`/usr/bin/python3`) still has the broken numpy wheel — **do not switch back to it without first reinstalling `numpy==2.0.0`** per Option A above.