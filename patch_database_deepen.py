"""
patch_database_deepen.py

Adds update_thesis_rings() to horizon_scanner/database.py.
This is the persistence function the deepen-counterparties job calls
to write mutated ring JSON back into the theses table.

Run from C:\\Projects\\horizon-scanner:
    python patch_database_deepen.py

Idempotent: aborts cleanly if anchor is not found exactly once,
or if the sentinel shows the patch was already applied.
"""

import os
import sys

TARGET = os.path.join("horizon_scanner", "database.py")

SENTINEL = "def update_thesis_rings("

ANCHOR = "def update_thesis_state(thesis_id: str, new_state: str, note: str = \"\"):"

INSERTION = '''
def update_thesis_rings(
    thesis_id: str,
    ring1: list = None,
    ring2: list = None,
    ring3: list = None,
    ring4: list = None,
) -> bool:
    """
    Persist updated entities_ring1-4 JSON back to a thesis row.
    Called by the deepen-counterparties background job after
    deepen_counterparties() mutates company objects in place.

    Only writes rings that are passed as non-None (None means unchanged).
    Returns True if a row was updated.
    """
    now = datetime.now(timezone.utc).isoformat()
    updates = []
    params = []
    if ring1 is not None:
        updates.append("entities_ring1 = ?")
        params.append(json.dumps(ring1))
    if ring2 is not None:
        updates.append("entities_ring2 = ?")
        params.append(json.dumps(ring2))
    if ring3 is not None:
        updates.append("entities_ring3 = ?")
        params.append(json.dumps(ring3))
    if ring4 is not None:
        updates.append("entities_ring4 = ?")
        params.append(json.dumps(ring4))
    if not updates:
        return False
    updates.append("last_updated = ?")
    params.append(now)
    params.append(thesis_id)
    sql = "UPDATE theses SET " + ", ".join(updates) + " WHERE id = ?"
    with get_connection() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount > 0


'''

def main():
    if not os.path.exists(TARGET):
        print("ERROR: {} not found. Run from project root.".format(TARGET))
        sys.exit(1)

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    # Idempotency check
    if SENTINEL in src:
        print("Patch already applied (sentinel found). Nothing to do.")
        sys.exit(0)

    # Anchor must appear exactly once
    count = src.count(ANCHOR)
    if count == 0:
        print("ERROR: anchor string not found in {}:".format(TARGET))
        print("  " + ANCHOR)
        sys.exit(1)
    if count > 1:
        print("ERROR: anchor string found {} times (expected 1). Aborting.".format(count))
        sys.exit(1)

    # Insert BEFORE the anchor (new function goes just above update_thesis_state)
    new_src = src.replace(ANCHOR, INSERTION + ANCHOR, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)

    print("Patched {} successfully.".format(TARGET))
    print("Added: update_thesis_rings()")


if __name__ == "__main__":
    main()
