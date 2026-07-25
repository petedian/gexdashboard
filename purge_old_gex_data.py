"""Rolling retention for gex_history.db -- deletes snapshots (and their strike
detail rows) older than RETENTION_DAYS, then reclaims disk space. Run on a
schedule via the gex-purge.timer systemd unit, not manually."""
import sqlite3
from datetime import datetime, timedelta, timezone
from gex_database import init_db

DB_PATH = "/home/finance/Tastytrade-API-GEX-Dashboard/gex_history.db"
RETENTION_DAYS = 5

init_db(DB_PATH)  # guarantees strike_volume_detail exists regardless of run order

cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("SELECT id FROM gex_snapshots WHERE captured_at < ?", (cutoff,))
old_ids = [r[0] for r in cur.fetchall()]

if old_ids:
    cur.executemany("DELETE FROM gex_strike_detail WHERE snapshot_id = ?", [(i,) for i in old_ids])
    cur.executemany("DELETE FROM strike_volume_detail WHERE snapshot_id = ?", [(i,) for i in old_ids])
    cur.executemany("DELETE FROM gex_snapshots WHERE id = ?", [(i,) for i in old_ids])
    conn.commit()

cur.execute("SELECT COUNT(*) FROM gex_snapshots")
remaining = cur.fetchone()[0]
conn.close()

conn = sqlite3.connect(DB_PATH)
conn.execute("VACUUM")
conn.close()

print(f"{datetime.now(timezone.utc).isoformat()} purge: deleted {len(old_ids)} snapshots older than "
      f"{RETENTION_DAYS}d, {remaining} remain")
