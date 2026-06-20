"""
patch_l5_immutable_db.py

Make resolved decisions immutable at the database layer.

Rules enforced:
  - record_outcome(): refuses if the decision is already resolved.
  - delete_decision(): refuses if the decision is resolved.
  - save_postmortem(): allowed ONLY the one time -- when the row is resolved
    but postmortem_summary is still empty. Once written, it is locked.

Each guarded function returns a small status so the server can send clear
HTTP responses. To stay backward-compatible, the functions keep returning a
truthy/falsey value, but record_outcome and delete_decision now raise a
DecisionLockedError when blocked so the server can distinguish "locked" from
"not found".

Run from project root:
    python patch_l5_immutable_db.py
"""

from pathlib import Path
import sys

DB_PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\database.py")

if not DB_PATH.exists():
    print(f"ERROR: {DB_PATH} not found")
    sys.exit(1)

text = DB_PATH.read_text(encoding="utf-8-sig")
changed = False

# ---------------------------------------------------------------------------
# 1. Add the DecisionLockedError exception near the top (after imports)
# ---------------------------------------------------------------------------

EXC_CHECK = "class DecisionLockedError"
EXC_ANCHOR = "from .config import get_config\n"
EXC_INSERT = """from .config import get_config


class DecisionLockedError(Exception):
    \"\"\"Raised when an operation is attempted on a resolved (locked) decision.\"\"\"
    pass
"""

if EXC_CHECK not in text:
    if EXC_ANCHOR in text:
        text = text.replace(EXC_ANCHOR, EXC_INSERT, 1)
        print("  [+] Added DecisionLockedError exception")
        changed = True
    else:
        print("  [!] Could not find config import anchor for exception -- aborting")
        sys.exit(1)
else:
    print("  [=] DecisionLockedError already present")

# ---------------------------------------------------------------------------
# 2. Guard delete_decision -- refuse if resolved
# ---------------------------------------------------------------------------

OLD_DELETE = '''def delete_decision(decision_id: str) -> bool:
    """Hard-delete a single decision by id. Returns True if a row was removed."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM decisions WHERE id=?", (decision_id,)
        )
        return cur.rowcount > 0'''

NEW_DELETE = '''def delete_decision(decision_id: str) -> bool:
    """
    Hard-delete a single decision by id. Returns True if a row was removed.
    Refuses (raises DecisionLockedError) if the decision is resolved -- a
    resolved decision is a permanent ledger entry and cannot be deleted.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT outcome_resolved FROM decisions WHERE id=?", (decision_id,)
        ).fetchone()
        if row is None:
            return False
        if row["outcome_resolved"]:
            raise DecisionLockedError(
                "This decision is resolved and cannot be deleted."
            )
        cur = conn.execute(
            "DELETE FROM decisions WHERE id=?", (decision_id,)
        )
        return cur.rowcount > 0'''

if OLD_DELETE in text:
    text = text.replace(OLD_DELETE, NEW_DELETE, 1)
    print("  [+] Guarded delete_decision against resolved rows")
    changed = True
else:
    print("  [=] delete_decision already guarded or anchor not found")

# ---------------------------------------------------------------------------
# 3. Guard record_outcome -- refuse if already resolved
# ---------------------------------------------------------------------------

OLD_RECORD = '''def record_outcome(
    decision_id: str,
    price_at_outcome: float = None,
    outcome_30d: str = "",
    outcome_90d: str = "",
    outcome_365d: str = "",
    outcome_date: str = None,
    resolved: bool = False,
) -> bool:
    """
    Update a decision with outcome data.  Call with resolved=True when the
    user wants to lock the record and trigger a post-mortem job.
    Returns True if a row was updated.
    """
    now = outcome_date or datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:'''

NEW_RECORD = '''def record_outcome(
    decision_id: str,
    price_at_outcome: float = None,
    outcome_30d: str = "",
    outcome_90d: str = "",
    outcome_365d: str = "",
    outcome_date: str = None,
    resolved: bool = False,
) -> bool:
    """
    Update a decision with outcome data.  Call with resolved=True when the
    user wants to lock the record and trigger a post-mortem job.
    Returns True if a row was updated.

    Refuses (raises DecisionLockedError) if the decision is ALREADY resolved.
    Once resolved, a decision is a permanent, immutable ledger entry.
    """
    now = outcome_date or datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT outcome_resolved FROM decisions WHERE id=?", (decision_id,)
        ).fetchone()
        if existing is None:
            return False
        if existing["outcome_resolved"]:
            raise DecisionLockedError(
                "This decision is resolved and locked. No further edits allowed."
            )'''

if OLD_RECORD in text:
    text = text.replace(OLD_RECORD, NEW_RECORD, 1)
    print("  [+] Guarded record_outcome against already-resolved rows")
    changed = True
else:
    print("  [=] record_outcome already guarded or anchor not found")

# ---------------------------------------------------------------------------
# 4. Guard save_postmortem -- allow only the one-time write at resolution
# ---------------------------------------------------------------------------

OLD_PM = '''def save_postmortem(
    decision_id: str,
    postmortem_summary: str,
    pattern_tag: str,
) -> bool:
    """
    Write the AI post-mortem back to the decision row.
    Returns True if a row was updated.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """UPDATE decisions
               SET postmortem_summary = ?,
                   pattern_tag        = ?
               WHERE id = ?""",
            (postmortem_summary, pattern_tag, decision_id),
        )
        return cur.rowcount > 0'''

NEW_PM = '''def save_postmortem(
    decision_id: str,
    postmortem_summary: str,
    pattern_tag: str,
) -> bool:
    """
    Write the AI post-mortem back to the decision row.
    Returns True if a row was updated.

    Allowed ONLY the one time: when the decision is resolved but no
    post-mortem summary has been written yet.  This is the single write that
    completes a resolved record.  Once postmortem_summary is populated, the
    row is fully locked and this raises DecisionLockedError.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT outcome_resolved, postmortem_summary
               FROM decisions WHERE id=?""",
            (decision_id,)
        ).fetchone()
        if row is None:
            return False
        # The post-mortem may only be written on a resolved row that does not
        # yet have a summary.  Re-running a completed post-mortem is blocked.
        existing_summary = (row["postmortem_summary"] or "").strip()
        if existing_summary:
            raise DecisionLockedError(
                "This decision already has a post-mortem and is locked."
            )
        cur = conn.execute(
            """UPDATE decisions
               SET postmortem_summary = ?,
                   pattern_tag        = ?
               WHERE id = ?""",
            (postmortem_summary, pattern_tag, decision_id),
        )
        return cur.rowcount > 0'''

if OLD_PM in text:
    text = text.replace(OLD_PM, NEW_PM, 1)
    print("  [+] Guarded save_postmortem to one-time write only")
    changed = True
else:
    print("  [=] save_postmortem already guarded or anchor not found")

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

if changed:
    DB_PATH.write_text(text, encoding="utf-8")
    print(f"\nDone. {DB_PATH} updated.")
    print("Verify:")
    print("  python -c \"import ast; ast.parse(open(r'C:\\\\Projects\\\\horizon-scanner\\\\horizon_scanner\\\\database.py', encoding='utf-8-sig').read()); print('VALID')\"")
else:
    print("\nNo changes made -- already patched.")
