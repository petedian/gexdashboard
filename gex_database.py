"""
GEX Database Layer (SQLite) - stores GEX snapshots, the historical moat.
"""
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = "gex_history.db"
_db_lock = threading.Lock()

def init_db(db_path=DB_PATH):
    with _db_lock:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gex_snapshots (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at  TEXT    NOT NULL,
                product      TEXT    NOT NULL,
                expiration   TEXT,
                spot_price   REAL,
                call_wall    REAL,
                put_wall     REAL,
                gamma_flip   REAL,
                total_net_gex REAL,
                num_strikes  INTEGER
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gex_strike_detail (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id  INTEGER NOT NULL,
                strike       REAL    NOT NULL,
                call_gex     REAL,
                put_gex      REAL,
                net_gex      REAL,
                FOREIGN KEY (snapshot_id) REFERENCES gex_snapshots(id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_snap_product_time ON gex_snapshots(product, captured_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_snap_product_time_desc ON gex_snapshots(product, captured_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_detail_snapshot ON gex_strike_detail(snapshot_id)")
        # GEX Profile page's data -- deliberately a separate table from
        # gex_strike_detail rather than adding columns to it. gex_strike_detail
        # blends all 4 nearest expirations into one row per strike (that's what
        # the wall/gamma-flip math on the main dashboard and chart page reads),
        # so it can't also hold real per-expiration volume/IV rows without
        # changing what every existing reader gets back. This table is
        # additive and 1:1 linked to gex_snapshots via snapshot_id.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strike_volume_detail (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id  INTEGER NOT NULL,
                expiration   TEXT    NOT NULL,
                strike       REAL    NOT NULL,
                call_volume  INTEGER,
                put_volume   INTEGER,
                call_iv      REAL,
                put_iv       REAL,
                FOREIGN KEY (snapshot_id) REFERENCES gex_snapshots(id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_svd_snapshot ON strike_volume_detail(snapshot_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_svd_snapshot_exp ON strike_volume_detail(snapshot_id, expiration)")

        # 0DTE-only walls/gamma-flip, alongside the existing 4-expiration-blended
        # ones -- computed from a second FuturesGEXCalculator in collect_one()
        # that's only fed gamma/OI for the nearest expiration. Nullable/additive
        # columns on the existing table (not a new one, since this is just 3
        # more scalars per snapshot, not per-strike detail) -- CREATE TABLE IF
        # NOT EXISTS above won't retroactively add columns to an existing table,
        # so this ALTER runs every init_db() call and no-ops once each column
        # exists. dte_expiration records which expiration was actually used,
        # since "nearest listed expiration" isn't always literally today
        # (weekends, holidays, products with no same-day listing).
        for col, coltype in [("call_wall_0dte", "REAL"), ("put_wall_0dte", "REAL"),
                              ("gamma_flip_0dte", "REAL"), ("dte_expiration", "TEXT")]:
            try:
                cur.execute(f"ALTER TABLE gex_snapshots ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
        conn.close()

def save_snapshot(product, expiration, spot_price, levels, strike_rows, db_path=DB_PATH,
                   levels_0dte=None, dte_expiration=None):
    """levels_0dte/dte_expiration are optional -- callers that don't compute a
    0DTE-only view (or products with no same-day expiration) just leave them
    None, and the new columns stay NULL for that row."""
    captured_at = datetime.now(timezone.utc).isoformat()
    levels_0dte = levels_0dte or {}
    with _db_lock:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gex_snapshots
                (captured_at, product, expiration, spot_price,
                 call_wall, put_wall, gamma_flip, total_net_gex, num_strikes,
                 call_wall_0dte, put_wall_0dte, gamma_flip_0dte, dte_expiration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            captured_at, product, str(expiration), spot_price,
            levels.get("call_wall"), levels.get("put_wall"),
            levels.get("gamma_flip"), levels.get("total_net_gex"),
            levels.get("num_strikes"),
            levels_0dte.get("call_wall"), levels_0dte.get("put_wall"),
            levels_0dte.get("gamma_flip"), dte_expiration,
        ))
        snapshot_id = cur.lastrowid
        if strike_rows:
            cur.executemany("""
                INSERT INTO gex_strike_detail
                    (snapshot_id, strike, call_gex, put_gex, net_gex)
                VALUES (?, ?, ?, ?, ?)
            """, [(snapshot_id, k, cg, pg, ng) for (k, cg, pg, ng) in strike_rows])
        conn.commit()
        conn.close()
    return snapshot_id

def save_strike_volume_detail(snapshot_id, rows, db_path=DB_PATH):
    """rows: list of (expiration, strike, call_volume, put_volume, call_iv,
    put_iv) tuples, one per (expiration, strike) -- see
    futures_gex_engine.VolumeIVTracker.get_rows(). Linked 1:1 to the
    gex_snapshots row via snapshot_id, same pattern as gex_strike_detail."""
    if not rows:
        return
    with _db_lock:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.executemany("""
            INSERT INTO strike_volume_detail
                (snapshot_id, expiration, strike, call_volume, put_volume, call_iv, put_iv)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [(snapshot_id, exp, k, cv, pv, civ, piv) for (exp, k, cv, pv, civ, piv) in rows])
        conn.commit()
        conn.close()


def get_strike_volume_detail(snapshot_id, expiration=None, db_path=DB_PATH):
    """All (expiration, strike, call_volume, put_volume, call_iv, put_iv) rows
    for one snapshot, optionally filtered to a single expiration."""
    with _db_lock:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if expiration:
            cur.execute("""
                SELECT expiration, strike, call_volume, put_volume, call_iv, put_iv
                FROM strike_volume_detail WHERE snapshot_id = ? AND expiration = ?
                ORDER BY strike
            """, (snapshot_id, expiration))
        else:
            cur.execute("""
                SELECT expiration, strike, call_volume, put_volume, call_iv, put_iv
                FROM strike_volume_detail WHERE snapshot_id = ?
                ORDER BY expiration, strike
            """, (snapshot_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    return rows


def get_last_two_snapshot_ids(product, db_path=DB_PATH):
    """The two most recent snapshot ids for `product` (newest first) -- used
    by the GEX Profile page's Session-total-vs-10-min-delta toggle. Second
    element is None if fewer than 2 snapshots exist yet."""
    with _db_lock:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM gex_snapshots WHERE product = ?
            ORDER BY captured_at DESC LIMIT 2
        """, (product,))
        ids = [r[0] for r in cur.fetchall()]
        conn.close()
    while len(ids) < 2:
        ids.append(None)
    return ids[0], ids[1]


def get_latest_snapshot(product, db_path=DB_PATH):
    """Single most recent snapshot for `product`, or None. Shared by
    Dashboard.py's cards, the GEX Chart page's quick-access buttons, and the
    GEX Profile page (which also needs `id` to join strike_volume_detail)
    -- no duplicate query logic."""
    with _db_lock:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, captured_at, product, spot_price, call_wall, put_wall,
                   gamma_flip, num_strikes, call_wall_0dte, put_wall_0dte,
                   gamma_flip_0dte, dte_expiration
            FROM gex_snapshots WHERE product = ?
            ORDER BY captured_at DESC LIMIT 1
        """, (product,))
        row = cur.fetchone()
        conn.close()
    return dict(row) if row else None


def get_recent_snapshots(product, limit=10, db_path=DB_PATH):
    with _db_lock:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT captured_at, product, spot_price, call_wall, put_wall,
                   gamma_flip, num_strikes
            FROM gex_snapshots WHERE product = ?
            ORDER BY captured_at DESC LIMIT ?
        """, (product, limit))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    return rows

def count_snapshots(db_path=DB_PATH):
    with _db_lock:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM gex_snapshots")
        n = cur.fetchone()[0]
        conn.close()
    return n

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Saving a test snapshot...")
    fake_levels = {"call_wall": 7600.0, "put_wall": 7550.0, "gamma_flip": 7565.0,
                   "total_net_gex": 1234567.0, "num_strikes": 3}
    fake_strikes = [(7550.0, 0.0, 500000.0, -500000.0),
                    (7565.0, 250000.0, 250000.0, 0.0),
                    (7600.0, 800000.0, 0.0, 800000.0)]
    sid = save_snapshot("/ES", "2026-07-06", 7556.25, fake_levels, fake_strikes)
    print(f"  Saved snapshot id={sid}")
    print("\nReading it back:")
    for row in get_recent_snapshots("/ES"):
        print(" ", row)
    print(f"\nTotal snapshots in DB: {count_snapshots()}")
    print("\nDatabase module OK.")
