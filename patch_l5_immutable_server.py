"""
patch_l5_immutable_server.py

Make the server return clear responses when an operation is blocked because a
decision is resolved (locked).  Catches DecisionLockedError from the database
layer and returns HTTP 409 Conflict with a clear message, distinct from 404
(not found).

Affected handlers:
  - do_DELETE  -> /api/decision/<id>     (delete blocked when resolved)
  - _handle_outcome_record               (edit blocked when resolved)
  - _handle_postmortem_trigger           (re-run blocked when locked)

Run from project root:
    python patch_l5_immutable_server.py
"""

from pathlib import Path
import sys

SRV_PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\server.py")

if not SRV_PATH.exists():
    print(f"ERROR: {SRV_PATH} not found")
    sys.exit(1)

text = SRV_PATH.read_text(encoding="utf-8-sig")
changed = False

# ---------------------------------------------------------------------------
# 1. Import DecisionLockedError
# ---------------------------------------------------------------------------

IMP_CHECK = "DecisionLockedError"
IMP_ANCHOR = "from .. import database as db\n"
IMP_INSERT = "from .. import database as db\nfrom ..database import DecisionLockedError\n"

if IMP_CHECK not in text:
    if IMP_ANCHOR in text:
        text = text.replace(IMP_ANCHOR, IMP_INSERT, 1)
        print("  [+] Imported DecisionLockedError")
        changed = True
    else:
        print("  [!] Could not find database import anchor -- aborting")
        sys.exit(1)
else:
    print("  [=] DecisionLockedError already imported")

# ---------------------------------------------------------------------------
# 2. Guard the DELETE handler for decisions
# ---------------------------------------------------------------------------

OLD_DELETE_BLOCK = '''            if route.startswith("/api/decision/"):
                decision_id = route[len("/api/decision/"):].strip("/")
                if not decision_id:
                    self._send_json({"error": "decision id required"}, 400)
                    return
                removed = db.delete_decision(decision_id)
                if removed:
                    self._send_json({"ok": True, "deleted": decision_id})
                else:
                    self._send_json({"error": "decision not found"}, 404)
                return'''

NEW_DELETE_BLOCK = '''            if route.startswith("/api/decision/"):
                decision_id = route[len("/api/decision/"):].strip("/")
                if not decision_id:
                    self._send_json({"error": "decision id required"}, 400)
                    return
                try:
                    removed = db.delete_decision(decision_id)
                except DecisionLockedError as e:
                    self._send_json({"error": str(e), "locked": True}, 409)
                    return
                if removed:
                    self._send_json({"ok": True, "deleted": decision_id})
                else:
                    self._send_json({"error": "decision not found"}, 404)
                return'''

if OLD_DELETE_BLOCK in text:
    text = text.replace(OLD_DELETE_BLOCK, NEW_DELETE_BLOCK, 1)
    print("  [+] Guarded DELETE handler against locked decisions")
    changed = True
else:
    print("  [=] DELETE handler already guarded or anchor not found")

# ---------------------------------------------------------------------------
# 3. Guard the outcome-record handler
# ---------------------------------------------------------------------------

OLD_OUTCOME = '''        resolved = bool(body.get("resolved", False))

        updated = db.record_outcome(
            decision_id=decision_id,
            price_at_outcome=price_at_outcome,
            outcome_30d=body.get("outcome_30d", ""),
            outcome_90d=body.get("outcome_90d", ""),
            outcome_365d=body.get("outcome_365d", ""),
            resolved=resolved,
        )

        if not updated:
            self._send_json({"error": "decision not found"}, 404)
            return'''

NEW_OUTCOME = '''        resolved = bool(body.get("resolved", False))

        try:
            updated = db.record_outcome(
                decision_id=decision_id,
                price_at_outcome=price_at_outcome,
                outcome_30d=body.get("outcome_30d", ""),
                outcome_90d=body.get("outcome_90d", ""),
                outcome_365d=body.get("outcome_365d", ""),
                resolved=resolved,
            )
        except DecisionLockedError as e:
            self._send_json({"error": str(e), "locked": True}, 409)
            return

        if not updated:
            self._send_json({"error": "decision not found"}, 404)
            return'''

if OLD_OUTCOME in text:
    text = text.replace(OLD_OUTCOME, NEW_OUTCOME, 1)
    print("  [+] Guarded outcome-record handler against locked decisions")
    changed = True
else:
    print("  [=] outcome-record handler already guarded or anchor not found")

# ---------------------------------------------------------------------------
# 4. Guard the post-mortem trigger handler (manual re-run)
# ---------------------------------------------------------------------------

OLD_PM_TRIGGER = '''        if not db.get_decision_by_id(decision_id):
            self._send_json({"error": "decision not found"}, 404)
            return

        job_id = self._start_postmortem_job(decision_id)
        self._send_json({"ok": True, "job_id": job_id})'''

NEW_PM_TRIGGER = '''        decision = db.get_decision_by_id(decision_id)
        if not decision:
            self._send_json({"error": "decision not found"}, 404)
            return

        # Block manual re-runs once a post-mortem already exists (locked).
        if (decision.get("postmortem_summary") or "").strip():
            self._send_json(
                {"error": "This decision already has a post-mortem and is locked.",
                 "locked": True},
                409,
            )
            return

        job_id = self._start_postmortem_job(decision_id)
        self._send_json({"ok": True, "job_id": job_id})'''

if OLD_PM_TRIGGER in text:
    text = text.replace(OLD_PM_TRIGGER, NEW_PM_TRIGGER, 1)
    print("  [+] Guarded post-mortem trigger against locked decisions")
    changed = True
else:
    print("  [=] post-mortem trigger already guarded or anchor not found")

# ---------------------------------------------------------------------------
# 5. The post-mortem JOB itself calls db.save_postmortem which can now raise
#    DecisionLockedError. Make the job worker handle it gracefully.
# ---------------------------------------------------------------------------

OLD_PM_JOB = '''        try:
            pattern_tag, summary = run_postmortem(decision_id)
            db.save_postmortem(decision_id, summary, pattern_tag)
            _set(
                status="done",
                pattern_tag=pattern_tag,
                finished=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:'''

NEW_PM_JOB = '''        try:
            pattern_tag, summary = run_postmortem(decision_id)
            try:
                db.save_postmortem(decision_id, summary, pattern_tag)
            except DecisionLockedError as e:
                # A post-mortem already exists -- nothing to write.
                _set(
                    status="error",
                    error=str(e),
                    finished=datetime.now(timezone.utc).isoformat(),
                )
                return
            _set(
                status="done",
                pattern_tag=pattern_tag,
                finished=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:'''

if OLD_PM_JOB in text:
    text = text.replace(OLD_PM_JOB, NEW_PM_JOB, 1)
    print("  [+] Made post-mortem job worker handle locked rows")
    changed = True
else:
    print("  [=] post-mortem job worker already guarded or anchor not found")

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

if changed:
    SRV_PATH.write_text(text, encoding="utf-8")
    print(f"\nDone. {SRV_PATH} updated.")
    print("Verify:")
    print("  python -c \"import ast; ast.parse(open(r'C:\\\\Projects\\\\horizon-scanner\\\\horizon_scanner\\\\dashboard\\\\server.py', encoding='utf-8-sig').read()); print('VALID')\"")
else:
    print("\nNo changes made -- already patched.")
