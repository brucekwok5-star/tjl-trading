"""
TJL Model Effectiveness Tracker
==============================
SQLite-backed record of every live signal. Tracks open → closed outcomes,
computes rolling WR / PF / expectancy per model, and flags DROP models.

DROP criteria (per model, rolling last 20 closed trades):
  WR < 30%  OR  PF <= 1.0  →  model excluded from dispatch

Usage (from tjl_live_futu.py):
  from tjl_model_tracker import ModelTracker
  tracker = ModelTracker()
  tracker.check_resolved(ctx)          # at start of run_scan
  tracker.record_signals(all_signals)   # after signals built
  active = tracker.get_active_models()  # returns set of model letters to USE
  tracker.log_status()                 # logs summary + DROP list
  tracker.close()

SQLite schema:
  signals(
    id          INTEGER PRIMARY KEY,
    ticker      TEXT, name TEXT, model TEXT,
    direction   TEXT, entry_price REAL,
    sl          REAL, tp REAL, atr REAL,
    rr_ratio    REAL,
    outcome     TEXT DEFAULT NULL,   -- NULL=OPEN, TP, SL, TIMEOUT
    recorded_at TEXT,
    resolved_at TEXT DEFAULT NULL
  )
"""

import sqlite3, os, time
from datetime import datetime, date, timedelta

DB_PATH = os.path.expanduser("~/.tjl_model_tracker.db")
ROLLING_N = 20          # closed trades to consider per model
TIMEOUT_DAYS = 5         # open >5 days → force-close as TIMEOUT

# ── helpers ───────────────────────────────────────────────────────────────────

def _hkt():
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8)))

def _today():
    return date.today()

# ── ModelTracker ──────────────────────────────────────────────────────────────

class ModelTracker:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._ensure_schema()
        self._conn = sqlite3.connect(self.db_path, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Compute active/drop on init
        self._refresh()

    # ── schema ───────────────────────────────────────────────────────────────

    def _ensure_schema(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT,
                name        TEXT,
                model       TEXT,
                direction   TEXT,
                entry_price REAL,
                sl          REAL,
                tp          REAL,
                atr         REAL,
                rr_ratio    REAL,
                outcome     TEXT DEFAULT NULL,
                recorded_at TEXT,
                resolved_at TEXT DEFAULT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_open
            ON signals(model, outcome)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_resolved
            ON signals(resolved_at)
        """)
        conn.commit()
        conn.close()

    # ── core API ──────────────────────────────────────────────────────────────

    def record_signals(self, signals):
        """Insert new OPEN signals. Skip if (ticker, model, entry_price, direction)
        already exists as OPEN — prevents double-counting on continuous scans."""
        now = _hkt().isoformat()
        inserted = 0
        for sig in signals:
            # Skip if already tracked as open
            exists = self._conn.execute("""
                SELECT 1 FROM signals
                WHERE ticker=? AND model=? AND direction=? AND outcome IS NULL
                LIMIT 1
            """, (sig.get('code') or sig.get('ticker'),
                  sig.get('signal_model'),
                  sig.get('direction'))).fetchone()
            if exists:
                continue
            self._conn.execute("""
                INSERT INTO signals
                  (ticker, name, model, direction, entry_price, sl, tp, atr,
                   rr_ratio, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sig.get('code') or sig.get('ticker'),
                sig.get('name'),
                sig.get('signal_model'),
                sig.get('direction'),
                float(sig['price']),
                float(sig['sl']),
                float(sig['tp']),
                float(sig['atr']),
                float(sig.get('rr_ratio', 0)),
                now,
            ))
            inserted += 1
        self._conn.commit()
        if inserted:
            print(f"[Tracker] recorded {inserted} new OPEN signal(s)")
        self._refresh()
        return inserted

    def check_resolved(self, futu_ctx=None):
        """Check all OPEN signals against current price. Resolve as TP, SL,
        or TIMEOUT if open > TIMEOUT_DAYS. Safe to call every scan cycle."""
        today_str = _today().isoformat()
        cutoff_str = (date.today() - timedelta(days=TIMEOUT_DAYS)).isoformat()

        open_rows = self._conn.execute("""
            SELECT id, ticker, direction, entry_price, sl, tp
            FROM signals
            WHERE outcome IS NULL
        """).fetchall()

        resolved = 0
        for row in open_rows:
            row_id, ticker, direction, entry, sl, tp = row

            # Force-timeout old signals
            created_str = self._conn.execute(
                "SELECT recorded_at FROM signals WHERE id=?", (row_id,)
            ).fetchone()[0]
            created_date = created_str[:10] if created_str else today_str
            if created_date < cutoff_str:
                self._resolve(row_id, "TIMEOUT", now_str=today_str)
                resolved += 1
                continue

            # Check live price
            if futu_ctx is None:
                continue
            try:
                code = f"HK.{ticker.zfill(5)}"
                ret, data = futu_ctx.get_market_snapshot([code])
                if ret != 0 or data is None or data.empty:
                    continue
                cur = float(data.iloc[0]['last_price'])
            except Exception:
                continue

            if direction == "LONG":
                if cur >= tp:
                    self._resolve(row_id, "TP", now_str=today_str)
                    resolved += 1
                elif cur <= sl:
                    self._resolve(row_id, "SL", now_str=today_str)
                    resolved += 1
            elif direction == "SHORT":
                if cur <= tp:
                    self._resolve(row_id, "TP", now_str=today_str)
                    resolved += 1
                elif cur >= sl:
                    self._resolve(row_id, "SL", now_str=today_str)
                    resolved += 1

        if resolved:
            print(f"[Tracker] resolved {resolved} signal(s)")
        self._refresh()
        return resolved

    def _resolve(self, row_id, outcome, now_str=None):
        self._conn.execute(
            "UPDATE signals SET outcome=?, resolved_at=? WHERE id=?",
            (outcome, now_str or _hkt().isoformat(), row_id)
        )
        self._conn.commit()

    # ── scoring ───────────────────────────────────────────────────────────────

    def _refresh(self):
        """Re-compute scores from DB."""
        self.scores = {}
        closed = self._conn.execute("""
            SELECT model, outcome
            FROM signals
            WHERE outcome IN ('TP','SL')
            ORDER BY resolved_at DESC
            LIMIT 9999
        """).fetchall()

        # Group by model (last ROLLING_N closed)
        from collections import defaultdict, OrderedDict
        by_model = defaultdict(list)
        for model, outcome in closed:
            by_model[model].append(outcome)

        for model, outcomes in by_model.items():
            recent = outcomes[:ROLLING_N]          # last N
            wins   = sum(1 for o in recent if o == 'TP')
            total  = len(recent)
            loss   = sum(1 for o in recent if o == 'SL')
            wr     = wins / total * 100 if total > 0 else 0.0

            # Avg win/loss from DB (need entry/sl/tp) — approximate from direction
            rows = self._conn.execute("""
                SELECT direction, entry_price, sl, tp
                FROM signals
                WHERE model=? AND outcome IN ('TP','SL')
                ORDER BY resolved_at DESC
                LIMIT ?
            """, (model, ROLLING_N)).fetchall()

            gains = []
            for direction, entry, sl, tp in rows:
                if direction == "LONG":
                    pct = (tp - entry) / entry * 100   # TP
                else:
                    pct = (entry - tp) / entry * 100   # TP for SHORT
                gains.append(pct)

            avg_win  = sum(g for g in gains if g > 0) / max(1, len([g for g in gains if g > 0]))
            avg_loss = abs(sum(g for g in gains if g < 0) / max(1, len([g for g in gains if g < 0])))
            pf       = (wr/100 * avg_win) / ((100-wr)/100 * avg_loss) if avg_loss > 0 and wr < 100 else 0.0
            exp      = sum(gains) / len(gains) if gains else 0.0

            self.scores[model] = {
                'trades': total,
                'wins': wins,
                'losses': loss,
                'wr': wr,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'pf': pf,
                'exp': exp,
            }

        self.open_count = self._conn.execute(
            "SELECT COUNT(*) FROM signals WHERE outcome IS NULL"
        ).fetchone()[0]

    def get_active_models(self):
        """Return set of model letters allowed to dispatch.
        DROP = WR < 30%  OR  PF <= 1.0
        Models with no history are included (unknown = don't block)."""
        drop = set()
        for model, s in self.scores.items():
            if s['trades'] >= 5:       # need minimum sample
                if s['wr'] < 30 or s['pf'] <= 1.0:
                    drop.add(model)
        # All model letters
        ALL = set("DEFGHIJKLMNOPQRST")
        return ALL - drop

    def get_drop_models(self):
        """Return set of model letters explicitly DROP."""
        return set(self.scores.keys()) - self.get_active_models()

    def log_status(self):
        """Print rolling performance table."""
        if not self.scores:
            print("[Tracker] No closed trades yet — all models active")
            return

        print("\n[Tracker] MODEL EFFECTIVENESS — rolling last {} closed trades".format(
            ROLLING_N))
        print("-" * 82)
        print(f"{'Model':<6} {'Trades':<8} {'WR':<8} {'Avg Win':<10} {'Avg Loss':<10} {'Exp':<9} {'PF':<6} Status")
        print("-" * 82)

        sorted_models = sorted(
            self.scores.keys(),
            key=lambda m: (self.scores[m]['wr'] < 30 or self.scores[m]['pf'] <= 1.0, -self.scores[m]['wr'])
        )

        for model in sorted_models:
            s = self.scores[model]
            wr    = s['wr']
            pf    = s['pf']
            trades = s['trades']
            drop  = trades >= 5 and (wr < 30 or pf <= 1.0)

            flag = "✗ DROP" if drop else "✓ ACTIVE"
            print(f"  {model:<4}  {trades:<8} {wr:>5.1f}%  "
                  f"{s['avg_win']:>+7.2f}%  {s['avg_loss']:>8.2f}%  "
                  f"{s['exp']:>+7.2f}%  {pf:>5.2f}  {flag}")

        drop_set = self.get_drop_models()
        if drop_set:
            print(f"\n  → DROP models (silently excluded from dispatch): {sorted(drop_set)}")
        print(f"  → Open signals in tracker: {self.open_count}")
        print("-" * 82)

    def close(self):
        self._conn.close()
