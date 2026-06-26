import sqlite3
conn = sqlite3.connect('data/horizon_scanner.db')
cur = conn.cursor()
for t in ('signals','signal_clusters'):
    cur.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,))
    print('=== ' + t + ' ===')
    print(cur.fetchone()[0])
    print()
conn.close()
