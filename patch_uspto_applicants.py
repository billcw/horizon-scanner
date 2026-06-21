"""
patch_uspto_applicants.py

Enhance uspto_collector.py to capture the full applicantBag (all applicants
on a patent, not just the first). Co-applicants are a genuine partnership /
joint-venture signal -- when two companies co-file, that relationship is real
and recorded, unlike licensing which is private.

Changes:
  1. Add 'applicationMetaData.applicantBag' to the keyword-mode fields list.
  2. In _store_record, extract all applicant names from applicantBag and store
     them in metadata['applicants'] (list) plus a joined string in content,
     while keeping firstApplicantName as the primary author.

Run from project root:
    python patch_uspto_applicants.py
"""

from pathlib import Path
import sys

COLL = Path(r"C:\Projects\horizon-scanner\horizon_scanner\collectors\uspto_collector.py")

if not COLL.exists():
    print(f"ERROR: {COLL} not found")
    sys.exit(1)

text = COLL.read_text(encoding="utf-8-sig")
changed = False

# ---------------------------------------------------------------------------
# 1. Add applicantBag to the keyword-mode fields list
# ---------------------------------------------------------------------------

OLD_FIELDS = '''        "fields": [
            "applicationNumberText",
            "applicationMetaData.inventionTitle",
            "applicationMetaData.filingDate",
            "applicationMetaData.firstApplicantName",
            "applicationMetaData.firstInventorName",
            "applicationMetaData.applicationTypeLabelName",
        ],'''

NEW_FIELDS = '''        "fields": [
            "applicationNumberText",
            "applicationMetaData.inventionTitle",
            "applicationMetaData.filingDate",
            "applicationMetaData.firstApplicantName",
            "applicationMetaData.applicantBag",
            "applicationMetaData.firstInventorName",
            "applicationMetaData.applicationTypeLabelName",
        ],'''

if '"applicationMetaData.applicantBag"' not in text:
    if OLD_FIELDS in text:
        text = text.replace(OLD_FIELDS, NEW_FIELDS, 1)
        print("  [+] added applicantBag to keyword-mode fields list")
        changed = True
    else:
        print("  [!] fields list anchor not found -- check formatting")
else:
    print("  [=] applicantBag already in fields list")

# ---------------------------------------------------------------------------
# 2. Extract applicantBag in _store_record
# ---------------------------------------------------------------------------

OLD_EXTRACT = '''    applicant = meta.get("firstApplicantName") or ""
    inventor = meta.get("firstInventorName") or ""
    filing_date = meta.get("filingDate") or ""
    app_type = meta.get("applicationTypeLabelName") or ""

    # USPTO front-page search does not return the abstract in this field set,
    # so content is the title plus applicant context. The classifier still has
    # the title + applicant + query theme to work with.
    content_bits = [title]
    if applicant:
        content_bits.append(f"Applicant: {applicant}")
    if inventor:
        content_bits.append(f"Inventor: {inventor}")
    content = ". ".join(content_bits)'''

NEW_EXTRACT = '''    applicant = meta.get("firstApplicantName") or ""
    inventor = meta.get("firstInventorName") or ""
    filing_date = meta.get("filingDate") or ""
    app_type = meta.get("applicationTypeLabelName") or ""

    # Pull ALL applicants from applicantBag. Co-applicants (multiple companies
    # on one filing) are a real partnership / joint-venture signal -- unlike
    # licensing, co-filing is publicly recorded. Each entry may carry the name
    # under one of a few keys depending on the record shape.
    applicants = []
    for a in (meta.get("applicantBag") or []):
        if isinstance(a, dict):
            name = (a.get("applicantNameText")
                    or a.get("nameText")
                    or a.get("name")
                    or "")
        else:
            name = str(a)
        name = (name or "").strip()
        if name and name not in applicants:
            applicants.append(name)
    # Ensure the firstApplicantName is represented even if the bag was empty
    if applicant and applicant not in applicants:
        applicants.insert(0, applicant)

    # USPTO front-page search does not return the abstract in this field set,
    # so content is the title plus applicant context. The classifier still has
    # the title + applicant(s) + query theme to work with.
    content_bits = [title]
    if applicants:
        if len(applicants) > 1:
            content_bits.append("Applicants: " + "; ".join(applicants))
        else:
            content_bits.append(f"Applicant: {applicants[0]}")
    elif applicant:
        content_bits.append(f"Applicant: {applicant}")
    if inventor:
        content_bits.append(f"Inventor: {inventor}")
    content = ". ".join(content_bits)'''

if "applicantBag" not in text.split("_store_record")[-1]:
    if OLD_EXTRACT in text:
        text = text.replace(OLD_EXTRACT, NEW_EXTRACT, 1)
        print("  [+] _store_record now extracts all applicants from applicantBag")
        changed = True
    else:
        print("  [!] _store_record extract anchor not found -- check formatting")
else:
    print("  [=] _store_record already extracts applicantBag")

# ---------------------------------------------------------------------------
# 3. Add applicants list to the stored metadata
# ---------------------------------------------------------------------------

OLD_META = '''        metadata={
            "application_number": app_num,
            "filing_date": filing_date,
            "application_type": app_type,
            "query": query_label,
        },'''

NEW_META = '''        metadata={
            "application_number": app_num,
            "filing_date": filing_date,
            "application_type": app_type,
            "applicants": applicants,
            "co_filed": len(applicants) > 1,
            "query": query_label,
        },'''

if '"applicants": applicants' not in text:
    if OLD_META in text:
        text = text.replace(OLD_META, NEW_META, 1)
        print("  [+] added applicants list + co_filed flag to signal metadata")
        changed = True
    else:
        print("  [!] metadata anchor not found -- check formatting")
else:
    print("  [=] metadata already includes applicants")

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

if changed:
    COLL.write_text(text, encoding="utf-8")
    print(f"\nDone. {COLL} updated.")
    print("Verify:")
    print("  python -c \"import ast; ast.parse(open(r'C:\\\\Projects\\\\horizon-scanner\\\\horizon_scanner\\\\collectors\\\\uspto_collector.py', encoding='utf-8-sig').read()); print('VALID')\"")
else:
    print("\nNo changes made -- already patched.")
