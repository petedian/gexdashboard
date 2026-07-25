"""ORT system database layer (SQLite) -- separate file from gex_history.db
on purpose: this is a manual-trading-structure tool, unrelated to the GEX
collector, and shouldn't share a file with something actively written to by
a live systemd service every 10 minutes.
"""
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = "ort_history.db"
_db_lock = threading.Lock()


def init_db(db_path=DB_PATH):
    with _db_lock:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ort_boxes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT    NOT NULL,
                symbol      TEXT    NOT NULL,
                box_high    REAL    NOT NULL,
                box_low     REAL    NOT NULL,
                locked_at   TEXT    NOT NULL,
                UNIQUE(trade_date, symbol)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_box_symbol_date ON ort_boxes(symbol, trade_date)")
        conn.commit()
        conn.close()


def save_box(trade_date, symbol, box_high, box_low, db_path=DB_PATH):
    """Idempotent on (trade_date, symbol) -- calling this again for the same
    day/symbol just overwrites, so a page rerun can't create duplicate boxes."""
    locked_at = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ort_boxes (trade_date, symbol, box_high, box_low, locked_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, symbol) DO UPDATE SET
                box_high=excluded.box_high, box_low=excluded.box_low, locked_at=excluded.locked_at
        """, (trade_date, symbol, box_high, box_low, locked_at))
        conn.commit()
        conn.close()


def get_box(trade_date, symbol, db_path=DB_PATH):
    with _db_lock:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""SELECT trade_date, symbol, box_high, box_low, locked_at
            FROM ort_boxes WHERE trade_date = ? AND symbol = ?""", (trade_date, symbol))
        row = cur.fetchone()
        conn.close()
    return dict(row) if row else None


def get_recent_boxes(symbol, limit=20, db_path=DB_PATH):
    with _db_lock:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""SELECT trade_date, symbol, box_high, box_low, locked_at
            FROM ort_boxes WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?""", (symbol, limit))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    return rows
