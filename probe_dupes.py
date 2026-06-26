import sqlite3
c = sqlite3.connect('data/horizon_scanner.db')
cur = c.cursor()
# Show the duplicates on 400fb6b2 with timestamps to see if they are rerun-spaced
cur.execute("SELECT id, created_at, last_updated, state FROM theses WHERE cluster_id='400fb6b2' ORDER BY created_at")
for r in cur.fetchall():
    print(r)
print('---versions table---')
cur.execute("SELECT thesis_id, COUNT(*) FROM thesis_versions GROUP BY thesis_id")
print(cur.fetchall())
c.close()
