import sqlite3
conn = sqlite3.connect('data/horizon_scanner.db')
cur = conn.cursor()
cur.execute('SELECT DISTINCT status FROM theses')
print([r[0] for r in cur.fetchall()])
conn.close()
