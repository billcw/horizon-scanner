import sqlite3

db = r"C:\Projects\horizon-scanner\data\horizon_scanner.db"
conn = sqlite3.connect(db)

tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
print("Tables found:", tables)

wipe = ["signals", "clusters", "theses", "decisions",
        "signal_clusters", "thesis_scores", "jobs"]

for t in wipe:
    if t in tables:
        conn.execute(f"DELETE FROM {t}")
        print(f"  Wiped: {t}")
    else:
        print(f"  Skipped (not found): {t}")

conn.execute("VACUUM")
conn.commit()
conn.close()
print("Done. Database compacted.")
