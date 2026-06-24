import ast, sys

path = r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\server.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

SENTINEL = "# SOURCE-TYPE-USPTO-ALLOWED"
if SENTINEL in src:
    print("Patch already applied. Nothing to do.")
    sys.exit(0)

OLD1 = 'if source_type not in ("arxiv", "trends", "reddit"):'
NEW1 = '# SOURCE-TYPE-USPTO-ALLOWED\n        if source_type not in ("arxiv", "trends", "reddit", "uspto"):'

count1 = src.count(OLD1)
if count1 != 1:
    print(f"ERROR: anchor 1 found {count1} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD1, NEW1, 1)

OLD2 = '"source_type must be arxiv, trends, or reddit"'
NEW2 = '"source_type must be arxiv, trends, reddit, or uspto"'

count2 = src.count(OLD2)
if count2 != 1:
    print(f"ERROR: anchor 2 found {count2} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD2, NEW2, 1)

try:
    ast.parse(src)
    print("AST parse OK")
except SyntaxError as e:
    print(f"AST ERROR: {e}")
    sys.exit(1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("Patch applied. Restart dashboard to pick up the change.")
