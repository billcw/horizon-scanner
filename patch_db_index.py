"""
patch_db_index.py

Fix: remove idx_decisions_resolved from the SCHEMA constant (it references
a column that doesn't exist on old DBs until the migration runs), and instead
create it inside _run_migrations after the column is added.

Run from project root:
    python patch_db_index.py
"""
from pathlib import Path
import sys

DB_PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\database.py")

if not DB_PATH.exists():
    print(f"ERROR: {DB_PATH} not found")
    sys.exit(1)

text = DB_PATH.read_text(encoding="utf-8-sig")

# ---- Remove the bad index line from SCHEMA --------------------------------
OLD_INDEX = "CREATE INDEX IF NOT EXISTS idx_decisions_resolved   ON decisions(outcome_resolved);\n"
if OLD_INDEX not in text:
    # Try with spaces normalised
    OLD_INDEX = "CREATE INDEX IF NOT EXISTS idx_decisions_resolved   ON decisions(outcome_resolved);\n"

# Also try the version with different spacing
ALT_INDEX = "CREATE INDEX IF NOT EXISTS idx_decisions_resolved   ON decisions(outcome_resolved);"
found = False
for variant in [
    "CREATE INDEX IF NOT EXISTS idx_decisions_resolved   ON decisions(outcome_resolved);\n",
    "CREATE INDEX IF NOT EXISTS idx_decisions_resolved  ON decisions(outcome_resolved);\n",
    "CREATE INDEX IF NOT EXISTS idx_decisions_resolved ON decisions(outcome_resolved);\n",
]:
    if variant in text:
        text = text.replace(variant, "", 1)
        print(f"  [+] Removed bad index line from SCHEMA: {variant.strip()}")
        found = True
        break

if not found:
    # Try without newline
    for variant in [
        "CREATE INDEX IF NOT EXISTS idx_decisions_resolved   ON decisions(outcome_resolved);",
        "CREATE INDEX IF NOT EXISTS idx_decisions_resolved  ON decisions(outcome_resolved);",
        "CREATE INDEX IF NOT EXISTS idx_decisions_resolved ON decisions(outcome_resolved);",
    ]:
        if variant in text:
            text = text.replace(variant, "", 1)
            print(f"  [+] Removed bad index line from SCHEMA: {variant.strip()}")
            found = True
            break

if not found:
    print("  [!] Could not find idx_decisions_resolved in SCHEMA -- printing surrounding context")
    idx = text.find("idx_decisions_resolved")
    if idx != -1:
        print(repr(text[max(0,idx-10):idx+80]))
    else:
        print("  [!] idx_decisions_resolved not found at all in file")

# ---- Add the index creation inside _run_migrations after the last migration
OLD_MIGRATIONS_END = '''    "ALTER TABLE decisions ADD COLUMN postmortem_summary TEXT",
]'''
NEW_MIGRATIONS_END = '''    "ALTER TABLE decisions ADD COLUMN postmortem_summary TEXT",
]

# Index on the new column -- created here (after migration) not in SCHEMA,
# because the column doesn't exist on old databases when SCHEMA runs.
_L5_POST_MIGRATION_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_decisions_resolved ON decisions(outcome_resolved)",
]'''

if OLD_MIGRATIONS_END in text:
    text = text.replace(OLD_MIGRATIONS_END, NEW_MIGRATIONS_END, 1)
    print("  [+] Added _L5_POST_MIGRATION_SQL list after _L5_MIGRATIONS")
else:
    print("  [!] Could not find _L5_MIGRATIONS closing bracket -- check file manually")

# ---- Patch _run_migrations to also run the post-migration index -----------
OLD_RUN_MIGRATIONS = '''def _run_migrations(conn: sqlite3.Connection):
    """
    Apply any missing L5 columns.  SQLite ALTER TABLE ADD COLUMN is
    idempotent-safe: we catch 'duplicate column name' errors and skip them.
    """
    for stmt in _L5_MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise'''

NEW_RUN_MIGRATIONS = '''def _run_migrations(conn: sqlite3.Connection):
    """
    Apply any missing L5 columns.  SQLite ALTER TABLE ADD COLUMN is
    idempotent-safe: we catch 'duplicate column name' errors and skip them.
    Then create any indexes that depend on the new columns.
    """
    for stmt in _L5_MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    # Create indexes that reference L5 columns (must run after columns exist)
    for stmt in _L5_POST_MIGRATION_SQL:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # already exists'''

if OLD_RUN_MIGRATIONS in text:
    text = text.replace(OLD_RUN_MIGRATIONS, NEW_RUN_MIGRATIONS, 1)
    print("  [+] Patched _run_migrations to also run post-migration indexes")
else:
    print("  [!] Could not find _run_migrations body to patch -- check file manually")

DB_PATH.write_text(text, encoding="utf-8")
print(f"\nDone. Written to {DB_PATH}")
print("\nVerify:")
print("  python -c \"import ast; ast.parse(open(r'C:\\Projects\\horizon-scanner\\horizon_scanner\\database.py', encoding='utf-8-sig').read()); print('VALID')\"")
