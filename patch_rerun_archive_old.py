"""
patch_rerun_archive_old.py -- after a successful thesis rerun, archive the
prior thesis so only one active thesis exists per cluster.

Targets the module-level _run_thesis_rerun_worker added by
patch_monitoring_server.py (sentinel L4-MONITORING-SERVER must already be present).

Idempotent, anchor-guarded. Run from project root.
"""
import ast
import io
import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "server.py")
SENTINEL = "# RERUN-ARCHIVE-OLD"

ANCHOR = '''        new_thesis_id, _state = run_thesis_loop(cluster_id)
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done"
            _JOBS[job_id]["thesis_id"] = new_thesis_id
            _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()'''

REPLACEMENT = '''        new_thesis_id, _state = run_thesis_loop(cluster_id)

        # RERUN-ARCHIVE-OLD: supersede the prior thesis so only the new one
        # stays active on this cluster. History is preserved in thesis_versions.
        if new_thesis_id and new_thesis_id != thesis_id:
            try:
                with db.get_connection() as conn:
                    conn.execute(
                        "UPDATE theses SET state='ARCHIVED' WHERE id=?",
                        (thesis_id,))
                    conn.execute(
                        "DELETE FROM thesis_signal_baseline WHERE thesis_id=?",
                        (thesis_id,))
                    conn.commit()
                logger.info("Archived superseded thesis %s (replaced by %s)",
                            thesis_id, new_thesis_id)
            except Exception as e:
                logger.warning("Could not archive old thesis %s: %s", thesis_id, e)

        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done"
            _JOBS[job_id]["thesis_id"] = new_thesis_id
            _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()'''


def main():
    if not os.path.exists(TARGET):
        print("ABORT: %s not found. Run from project root." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Already applied (sentinel present). No change.")
        return

    if "# L4-MONITORING-SERVER" not in src:
        print("ABORT: L4-MONITORING-SERVER sentinel missing. "
              "Run patch_monitoring_server.py first.")
        sys.exit(1)

    c = src.count(ANCHOR)
    if c != 1:
        print("ABORT: anchor found %d times (expected 1). No change." % c)
        sys.exit(1)

    new_src = src.replace(ANCHOR, REPLACEMENT, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print("ABORT: result fails AST parse: %s" % e)
        sys.exit(1)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)
    print("OK: rerun now archives the superseded thesis (%s)" % TARGET)


if __name__ == "__main__":
    main()
