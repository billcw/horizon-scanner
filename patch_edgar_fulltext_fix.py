"""
patch_edgar_fulltext_fix.py

Fix three issues in edgar_client.py's full-text search, surfaced by the first
live thesis run:

  1. HTTP 500s: the OR-chain query trips EFTS when URL-encoded. Replace with a
     single reliable quoted phrase.
  2. Empty "form" field: EFTS _source uses file_type / root_form / form, not
     form_type. Read several candidate keys defensively.
  3. Old dates: add sort=desc and a date floor so recent licensing surfaces
     first instead of decades-old filings.

Run from project root:
    python patch_edgar_fulltext_fix.py
"""

from pathlib import Path
import sys

PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\enrichment\edgar_client.py")

if not PATH.exists():
    print("ERROR: edgar_client.py not found")
    sys.exit(1)

text = PATH.read_text(encoding="utf-8-sig")
changed = False

# ---------------------------------------------------------------------------
# 1. fulltext_search: add sort=desc
# ---------------------------------------------------------------------------

OLD_FT_PARAMS = '''    params = {"q": query, "from": 0}
    if forms:'''
NEW_FT_PARAMS = '''    params = {"q": query, "from": 0, "sort": "desc"}
    if forms:'''

if '"sort": "desc"' not in text:
    if OLD_FT_PARAMS in text:
        text = text.replace(OLD_FT_PARAMS, NEW_FT_PARAMS, 1)
        print("  [+] fulltext_search: added sort=desc")
        changed = True
    else:
        print("  [!] fulltext_search params anchor not found")
else:
    print("  [=] fulltext_search already sorts desc")

# ---------------------------------------------------------------------------
# 2. fulltext_search: read form from candidate keys (clean helper, no ternary)
# ---------------------------------------------------------------------------

OLD_FORM_READ = '''        out.append({
            "form": src.get("form_type", src.get("root_form", "")),'''
NEW_FORM_READ = '''        # EFTS _source field naming varies; pick the first present form key.
        form_val = ""
        for _k in ("file_type", "form_type", "root_form"):
            _v = src.get(_k)
            if _v:
                form_val = _v
                break
        if not form_val:
            _forms = src.get("forms")
            if isinstance(_forms, list) and _forms:
                form_val = _forms[0]
            elif isinstance(_forms, str):
                form_val = _forms
        out.append({
            "form": form_val,'''

if 'for _k in ("file_type"' not in text:
    if OLD_FORM_READ in text:
        text = text.replace(OLD_FORM_READ, NEW_FORM_READ, 1)
        print("  [+] fulltext_search: read form from candidate keys")
        changed = True
    else:
        print("  [!] fulltext_search form-read anchor not found")
else:
    print("  [=] fulltext_search form-read already fixed")

# ---------------------------------------------------------------------------
# 3. find_licensing_mentions: single phrase + forms filter
# ---------------------------------------------------------------------------

OLD_LIC = '''    # Search this company's own filings for licensing language.
    hits = fulltext_search(
        query='"license agreement" OR "licensing agreement" OR "patent license"',
        cik=cik,
        date_from=date_from,
        size=10,
    )'''

NEW_LIC = '''    # Search this company's own filings for licensing language.
    # A single quoted phrase is reliable; the OR-chain trips EFTS on encoding.
    # Restrict to substantive forms; recency sort is handled in fulltext_search.
    hits = fulltext_search(
        query='"license agreement"',
        cik=cik,
        forms=["10-K", "10-Q", "8-K"],
        date_from=date_from,
        size=10,
    )'''

if "the OR-chain trips EFTS" not in text:
    if OLD_LIC in text:
        text = text.replace(OLD_LIC, NEW_LIC, 1)
        print("  [+] find_licensing_mentions: single-phrase query + forms filter")
        changed = True
    else:
        print("  [!] find_licensing_mentions anchor not found")
else:
    print("  [=] find_licensing_mentions already fixed")

# ---------------------------------------------------------------------------
if changed:
    PATH.write_text(text, encoding="utf-8")
    print("")
    print("Done. edgar_client.py updated.")
    print("Re-test standalone:  python -m horizon_scanner.enrichment.edgar_client")
else:
    print("")
    print("No changes made -- already patched.")
