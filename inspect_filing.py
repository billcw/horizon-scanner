"""
inspect_filing.py
Walks ONE IBM licensing filing end to end so we can see what counterparty
extraction has to work with, using the real edgar_client functions.

Chain: stored index_url -> fetch index page -> find primary document ->
fetch document text -> show a slice.

Run from project root:
  python inspect_filing.py
"""
import json
import sqlite3

from horizon_scanner.enrichment import edgar_client as ec

DB = r"C:\Projects\horizon-scanner\data\horizon_scanner.db"

c = sqlite3.connect(DB)
row = c.execute(
    "SELECT entities_ring1 FROM theses "
    "WHERE title LIKE 'Quantum circuit optimization%'"
).fetchone()
ring1 = json.loads(row[0])
ibm = next((x for x in ring1 if x.get("ticker") == "IBM"), ring1[0])
hits = ibm.get("licensing_hits", [])

print("Company:", ibm.get("company"), "/ CIK", ibm.get("cik"))
print("Licensing hit count:", len(hits))
if not hits:
    raise SystemExit(0)

first = hits[0]
print("First hit:", json.dumps(first, indent=2))
print("=" * 60)

index_url = first.get("index_url")
print("Index URL:", index_url)

# Fetch the index page (HTML) via the low-level _get.
resp = ec._get(index_url, json_accept=False)
html = resp.text if hasattr(resp, "text") else str(resp)
print("Index page length:", len(html), "chars")
print("-" * 60)

# Show the part of the index page that lists documents, so we can see how to
# find the primary exhibit (the .htm/.txt document URLs).
# Just dump the first chunk -- we are eyeballing structure.
print(html[:3000])
print("-" * 60)
print("NOTE: looking for the document table / .htm links above.")
