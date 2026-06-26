import sqlite3
c = sqlite3.connect('data/horizon_scanner.db')
cur = c.cursor()
cur.execute("SELECT id, title, cluster_id, state FROM theses WHERE state IN ('WATCH','BUILDING','CANDIDATE','ACTIVE')")
rows = cur.fetchall()
print('active theses:', len(rows))
for r in rows:
    tid, title, cid, state = r
    n = 0
    if cid:
        n = cur.execute('SELECT COUNT(*) FROM signals WHERE cluster_id=?', (cid,)).fetchone()[0]
    print(f'  {state:10} cluster={str(cid)[:8] if cid else None!s:10} signals={n}  {str(title)[:40]}')
cur.execute('SELECT thesis_id, last_count FROM thesis_signal_baseline')
print('baselines stored:', cur.fetchall())
c.close()
