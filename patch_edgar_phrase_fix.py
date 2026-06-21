"""
patch_edgar_phrase_fix.py

Two of the five licensing phrases throw EFTS 500s. Cause: a hyphen inside a
quoted phrase ("cross-license") is parsed by EFTS/Elasticsearch as a NOT
operator on the following token, producing a malformed query. Fix: remove the
hyphen ("cross license" tokenizes identically) and keep only phrases EFTS
reliably accepts.

Run from project root:
    python patch_edgar_phrase_fix.py
"""

from pathlib import Path
import sys

PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\enrichment\edgar_client.py")

if not PATH.exists():
    print("ERROR: edgar_client.py not found")
    sys.exit(1)

text = PATH.read_text(encoding="utf-8-sig")

OLD = '''    licensing_phrases = [
        '"license agreement"',
        '"licensing agreement"',
        '"patent license"',
        '"technology license"',
        '"cross-license"',
    ]'''

NEW = '''    licensing_phrases = [
        '"license agreement"',
        '"licensing agreement"',
        '"patent license"',
        '"technology license"',
        '"cross license"',
        '"licensing arrangement"',
    ]'''

if '"cross license"' in text:
    print("  [=] phrase set already fixed")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    PATH.write_text(text, encoding="utf-8")
    print("  [+] removed hyphen from cross-license; added 'licensing arrangement'")
    print("")
    print("Done. Re-test:  python -m horizon_scanner.enrichment.edgar_client")
else:
    print("  [!] phrase-list anchor not found -- paste find_licensing_mentions")
    sys.exit(1)
