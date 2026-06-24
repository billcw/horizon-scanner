import ast, sys

path = r"C:\Projects\horizon-scanner\horizon_scanner\collectors\uspto_collector.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

SENTINEL = "# USPTO-KEYWORD-FREEFORM-SEARCH"
if SENTINEL in src:
    print("Patch already applied. Nothing to do.")
    sys.exit(0)

OLD_COMMENT = '# The field we search keywords against (documented, reliable).\nTITLE_FIELD = "applicationMetaData.inventionTitle"'
NEW_COMMENT = ('# USPTO-KEYWORD-FREEFORM-SEARCH\n'
               '# Free-form search (no field prefix) matches the phrase across all searchable fields.\n'
               '# Field-scoped title search produces 404 for multi-word phrases that rarely appear\n'
               '# verbatim in invention titles. Free-form phrase search is more productive.\n'
               '# TITLE_FIELD kept for reference / CPC mode but not used in keyword query.\n'
               'TITLE_FIELD = "applicationMetaData.inventionTitle"')

count = src.count(OLD_COMMENT)
if count != 1:
    print(f"ERROR: anchor 1 found {count} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD_COMMENT, NEW_COMMENT, 1)

OLD_BODY = '    return {\n        "q": f\'{TITLE_FIELD}:"{keyword}"\','
NEW_BODY = ('    # Free-form phrase search: wraps keyword in quotes so multi-word phrases\n'
            '    # are matched as a phrase across all searchable fields (title, abstract, applicant).\n'
            '    # Field-scoped title search (TITLE_FIELD:"phrase") returns 404 for most keywords\n'
            '    # because exact phrases rarely appear verbatim in invention titles.\n'
            '    q_value = f\'"{keyword}"\'\n'
            '    return {\n'
            '        "q": q_value,')

count = src.count(OLD_BODY)
if count != 1:
    print(f"ERROR: anchor 2 found {count} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD_BODY, NEW_BODY, 1)

try:
    ast.parse(src)
    print("AST parse OK")
except SyntaxError as e:
    print(f"AST ERROR: {e}")
    sys.exit(1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("Patch applied. Restart dashboard and run a collect to test.")
