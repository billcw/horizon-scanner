"""
inspect_filing2.py
Second look: pull the DOCUMENT LINKS out of the IBM filing index page so we can
see what exhibits exist and pick the one likely to contain counterparty names.
Then fetch that document's text and show a slice.

Run from project root:
  python inspect_filing2.py
"""
import json
import re
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
first = hits[0]
index_url = first["index_url"]

print("Index URL:", index_url)
resp = ec._get(index_url, json_accept=False)
html = resp.text

# Pull all hrefs that look like filing documents (Archives paths to real files).
links = re.findall(r'href="([^"]+)"', html)
doc_links = [l for l in links if "/Archives/edgar/data/" in l and
             re.search(r'\.(htm|txt|html)$', l, re.I)]
# Dedup, drop the index page itself.
seen = []
for l in doc_links:
    full = l if l.startswith("http") else "https://www.sec.gov" + l
    if "index" in full.lower():
        continue
    if full not in seen:
        seen.append(full)

print("Document links found:", len(seen))
for i, l in enumerate(seen):
    print(" [%d] %s" % (i, l))
print("=" * 60)

if not seen:
    print("No document links matched. Dumping a middle slice of the index page")
    print("so we can see the real table structure:")
    print(html[3000:6500])
    raise SystemExit(0)

# Fetch the first real document and show a slice of its TEXT (cleaned).
target = seen[0]
print("Fetching document text:", target)
text = ec._fetch_document_text(target, max_chars=400_000)
print("Document text length:", len(text), "chars")
print("-" * 60)
# Show a slice from the start -- contracts usually name parties early
# ("THIS AGREEMENT ... between X and Y").
print(text[:4000])
