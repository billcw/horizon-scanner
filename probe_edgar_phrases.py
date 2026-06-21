"""
probe_edgar_phrases.py

One-at-a-time probe to find which licensing phrase(s) EFTS rejects with a 500.
Runs each phrase as its own search against Apple's CIK and reports OK/FAIL.
Run from project root:
    python probe_edgar_phrases.py
"""
from horizon_scanner.enrichment import edgar_client as ec

phrases = [
    '"license agreement"',
    '"licensing agreement"',
    '"patent license"',
    '"technology license"',
    '"cross license"',
    '"licensing arrangement"',
]

APPLE_CIK = 320193

for p in phrases:
    try:
        hits = ec.fulltext_search(
            query=p, cik=APPLE_CIK,
            forms=["10-K", "10-Q", "8-K"],
            date_from="2015-01-01", size=3,
        )
        print(f"  OK   {p:28} -> {len(hits)} hits")
    except Exception as e:
        print(f"  FAIL {p:28} -> {e}")
