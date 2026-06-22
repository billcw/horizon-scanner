"""
inspect_enriched.py
Dumps the enriched Ring 1 company objects from the one enriched thesis so we
can see the real field shape (licensing_hits, co_filed, ticker_verified, etc.)
before building the supply-line graph.

Run from the project root:
  python inspect_enriched.py
"""
import sqlite3
import json

DB = r"C:\Projects\horizon-scanner\data\horizon_scanner.db"

c = sqlite3.connect(DB)
row = c.execute(
    "SELECT id, title, bottleneck_entity, bottleneck_ticker, "
    "entities_ring1, entities_ring2 "
    "FROM theses WHERE title LIKE 'Quantum circuit optimization%'"
).fetchone()

if not row:
    print("No 'Quantum circuit optimization' thesis found.")
    raise SystemExit(0)

tid, title, bn_entity, bn_ticker, r1, r2 = row
print("THESIS ID:", tid)
print("TITLE:", title)
print("BOTTLENECK:", bn_entity, "/", bn_ticker)
print("=" * 60)

ring1 = json.loads(r1) if r1 else []
print("RING1 COUNT:", len(ring1))
print("-" * 60)

# Show full first object so we see every field present.
if ring1:
    print("FIRST RING1 OBJECT (full):")
    print(json.dumps(ring1[0], indent=2))
    print("-" * 60)

# Show the KEYS present across all ring1 objects (union), so we know what
# enrichment actually attached.
keys = set()
for obj in ring1:
    if isinstance(obj, dict):
        keys.update(obj.keys())
print("UNION OF ALL RING1 KEYS:", sorted(keys))
print("-" * 60)

# If licensing_hits exists, show one hit's shape -- this decides whether
# licensing edges can connect two companies or only badge one.
for obj in ring1:
    if isinstance(obj, dict) and obj.get("licensing_hits"):
        print("SAMPLE licensing_hits (from", obj.get("company"), "):")
        hits = obj["licensing_hits"]
        print(json.dumps(hits[:2] if isinstance(hits, list) else hits, indent=2))
        break
else:
    print("No licensing_hits populated on any Ring1 company.")
