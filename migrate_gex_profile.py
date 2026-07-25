"""One-off migration for the GEX Profile page: adds the strike_volume_detail
table (see gex_database.py::init_db()). Idempotent -- CREATE TABLE/INDEX IF NOT
EXISTS, safe to re-run. Requires a pre-change backup copy of gex_history.db to
already exist before it will touch the live db."""
import os
import sys
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "gex_history.db")
BACKUP_PATH = os.path.join(HERE, "gex_history_pre_volume_profile_backup.db")

if not os.path.exists(BACKUP_PATH):
    print(f"Refusing to migrate: no backup found at {BACKUP_PATH}. "
          f"Run `cp gex_history.db gex_history_pre_volume_profile_backup.db` first.")
    sys.exit(1)

from gex_database import init_db  # noqa: E402  (after the backup guard, on purpose)

init_db(DB_PATH)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='strike_volume_detail'")
exists = cur.fetchone() is not None
cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_svd_%'")
indexes = [r[0] for r in cur.fetchall()]
conn.close()

print(f"strike_volume_detail table exists: {exists}")
print(f"strike_volume_detail indexes: {indexes}")
print("Migration OK." if exists and len(indexes) == 2 else "Migration INCOMPLETE.")
