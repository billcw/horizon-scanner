import ast, sys

path = r"C:\Projects\horizon-scanner\horizon_scanner\database.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

SENTINEL = "# THESIS-VERSIONING-DB"
if SENTINEL in src:
    print("Patch already applied. Nothing to do.")
    sys.exit(0)

# --- Change 1: add thesis_versions table to SCHEMA ---
OLD1 = 'CREATE INDEX IF NOT EXISTS idx_decisions_thesis     ON decisions(thesis_id);'
NEW1 = (
    'CREATE INDEX IF NOT EXISTS idx_decisions_thesis     ON decisions(thesis_id);\n'
    '\n'
    '-- Thesis version history (snapshot before each re-run)\n'
    '-- THESIS-VERSIONING-DB\n'
    'CREATE TABLE IF NOT EXISTS thesis_versions (\n'
    '    id              TEXT PRIMARY KEY,\n'
    '    thesis_id       TEXT NOT NULL,\n'
    '    version_number  INTEGER NOT NULL,\n'
    '    snapshotted_at  TEXT NOT NULL,\n'
    '    trigger         TEXT NOT NULL,      -- manual_rerun | scheduled | signal_spike\n'
    '    snapshot        TEXT NOT NULL       -- full JSON of thesis row at that moment\n'
    ');\n'
    '\n'
    'CREATE INDEX IF NOT EXISTS idx_thesis_versions_thesis ON thesis_versions(thesis_id);'
)
count1 = src.count(OLD1)
if count1 != 1:
    print(f"ERROR: anchor 1 found {count1} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD1, NEW1, 1)

# --- Change 2: update collector_sources source_type comment ---
OLD2 = "source_type   TEXT NOT NULL,          -- arxiv | trends | reddit"
NEW2 = "source_type   TEXT NOT NULL,          -- arxiv | trends | reddit | uspto"
count2 = src.count(OLD2)
if count2 != 1:
    print(f"ERROR: anchor 2 found {count2} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD2, NEW2, 1)

# --- Change 3: add versioning functions before get_connection ---
OLD3 = 'def get_connection() -> sqlite3.Connection:'
NEW3 = (
    '# ---------------------------------------------------------------------------\n'
    '# Thesis versioning\n'
    '# ---------------------------------------------------------------------------\n'
    '\n'
    'def snapshot_thesis_version(thesis_id: str, trigger: str = "manual_rerun") -> int:\n'
    '    """\n'
    '    Snapshot the current thesis row into thesis_versions before a re-run.\n'
    '    Returns the new version_number, or 0 if thesis not found.\n'
    '    Trigger values: manual_rerun | scheduled | signal_spike\n'
    '    """\n'
    '    with get_connection() as conn:\n'
    '        row = conn.execute(\n'
    '            "SELECT * FROM theses WHERE id=?", (thesis_id,)\n'
    '        ).fetchone()\n'
    '        if row is None:\n'
    '            return 0\n'
    '        count = conn.execute(\n'
    '            "SELECT COUNT(*) FROM thesis_versions WHERE thesis_id=?",\n'
    '            (thesis_id,)\n'
    '        ).fetchone()[0]\n'
    '        version_number = count + 1\n'
    '        version_id = str(uuid.uuid4())\n'
    '        now = datetime.now(timezone.utc).isoformat()\n'
    '        snapshot = json.dumps(dict(row))\n'
    '        conn.execute(\n'
    '            """INSERT INTO thesis_versions\n'
    '               (id, thesis_id, version_number, snapshotted_at, trigger, snapshot)\n'
    '               VALUES (?, ?, ?, ?, ?, ?)""",\n'
    '            (version_id, thesis_id, version_number, now, trigger, snapshot)\n'
    '        )\n'
    '        return version_number\n'
    '\n'
    '\n'
    'def get_thesis_versions(thesis_id: str) -> list:\n'
    '    """\n'
    '    Return all prior versions of a thesis, oldest first.\n'
    '    Each entry is a dict with version_number, snapshotted_at, trigger,\n'
    '    and the full snapshot parsed back to a dict.\n'
    '    """\n'
    '    with get_connection() as conn:\n'
    '        rows = conn.execute(\n'
    '            """SELECT * FROM thesis_versions\n'
    '               WHERE thesis_id=?\n'
    '               ORDER BY version_number ASC""",\n'
    '            (thesis_id,)\n'
    '        ).fetchall()\n'
    '        result = []\n'
    '        for r in rows:\n'
    '            entry = dict(r)\n'
    '            entry["snapshot"] = json.loads(entry["snapshot"])\n'
    '            result.append(entry)\n'
    '        return result\n'
    '\n'
    '\n'
    'def get_connection() -> sqlite3.Connection:'
)
count3 = src.count(OLD3)
if count3 != 1:
    print(f"ERROR: anchor 3 found {count3} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD3, NEW3, 1)

try:
    ast.parse(src)
    print("AST parse OK")
except SyntaxError as e:
    print(f"AST ERROR: {e}")
    sys.exit(1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("Patch applied. thesis_versions table + snapshot/get functions added to database.py.")
