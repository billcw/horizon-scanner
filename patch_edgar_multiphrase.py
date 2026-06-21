"""
patch_edgar_multiphrase.py  (Option B)

Upgrade find_licensing_mentions to run several reliable single-phrase searches
and merge/dedupe the results, instead of one phrase. Catches wording variants
("license agreement", "licensing arrangement", "patent license", "technology
license", "cross-license") that a single phrase misses -- accuracy over speed.

Each query is a clean single quoted phrase (reliable; the OR-chain broke EFTS).
Results merged, deduped by accession, sorted newest-first.

This patch anchors on the POST-fulltext-fix state of find_licensing_mentions
(single "license agreement" phrase with forms filter). Run the fulltext fix
first if you haven't.

Run from project root:
    python patch_edgar_multiphrase.py
"""

from pathlib import Path
import sys

PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\enrichment\edgar_client.py")

if not PATH.exists():
    print("ERROR: edgar_client.py not found")
    sys.exit(1)

text = PATH.read_text(encoding="utf-8-sig")

# Anchor: the post-fix single-phrase block
OLD = '''    # Search this company's own filings for licensing language.
    # A single quoted phrase is reliable; the OR-chain trips EFTS on encoding.
    # Restrict to substantive forms; recency sort is handled in fulltext_search.
    hits = fulltext_search(
        query='"license agreement"',
        cik=cik,
        forms=["10-K", "10-Q", "8-K"],
        date_from=date_from,
        size=10,
    )'''

NEW = '''    # Search this company's own filings for licensing language.
    # Accuracy over speed: run several reliable single-phrase queries and merge.
    # A single quoted phrase per call is reliable; an OR-chain trips EFTS on
    # encoding. Sequential clean queries catch wording variants a single phrase
    # would miss. Recency sort + forms filter handled in fulltext_search.
    licensing_phrases = [
        '"license agreement"',
        '"licensing agreement"',
        '"patent license"',
        '"technology license"',
        '"cross-license"',
    ]
    merged = {}
    for phrase in licensing_phrases:
        try:
            phrase_hits = fulltext_search(
                query=phrase,
                cik=cik,
                forms=["10-K", "10-Q", "8-K"],
                date_from=date_from,
                size=10,
            )
        except Exception as e:
            logger.warning("EDGAR licensing phrase %s failed: %s", phrase, e)
            phrase_hits = []
        for h in phrase_hits:
            key = h.get("accession") or (h.get("index_url") or "")
            if not key:
                continue
            if key not in merged:
                h["matched_phrase"] = phrase.strip('"')
                merged[key] = h
    # Sort merged hits newest-first by filing_date
    hits = sorted(
        merged.values(),
        key=lambda x: x.get("filing_date", ""),
        reverse=True,
    )'''

if "licensing_phrases = [" in text:
    print("  [=] multi-phrase licensing already present")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    PATH.write_text(text, encoding="utf-8")
    print("  [+] find_licensing_mentions: now runs 5 phrases, merged + deduped")
    print("")
    print("Done. edgar_client.py updated.")
    print("Re-test:  python -m horizon_scanner.enrichment.edgar_client")
else:
    print("  [!] anchor not found. Your find_licensing_mentions may not have the")
    print("      fulltext-fix applied yet, or has different text. Paste the function")
    print("      and I'll rewrite the patch to match.")
    sys.exit(1)
