import sqlite3
conn = sqlite3.connect('data/horizon_scanner.db')
cur = conn.cursor()
cur.execute("SELECT sql FROM sqlite_master WHERE name='monitoring_events'")
print(cur.fetchone())
conn.close()
