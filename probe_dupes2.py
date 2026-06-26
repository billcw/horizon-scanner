"""
probe_dupes2.py -- list clusters with multiple active theses, full IDs + timestamps.
Run from project root: python probe_dupes2.py
"""
import sqlite3

c = sqlite3.connect("data/horizon_scanner.db")
c.row_factory = sqlite3.Row
cur = c.cursor()

cur.execute(
    "SELECT cluster_id, COUNT(*) n FROM theses "
    "WHERE state IN ('WATCH','BUILDING','CANDIDATE','ACTIVE') "
    "GROUP BY cluster_id HAVING n > 1 ORDER BY n DESC"
)
dupes = cur.fetchall()

print("clusters with multiple active theses:")
for d in dupes:
    print("  cluster=%s  count=%d" % (d["cluster_id"], d["n"]))
    rows = cur.execute(
        "SELECT id, created_at, last_updated, state FROM theses "
        "WHERE cluster_id=? ORDER BY created_at",
        (d["cluster_id"],),
    ).fetchall()
    for r in rows:
        print("      %s  created=%s  updated=%s" % (
            r["id"], r["created_at"], r["last_updated"]))

c.close()
