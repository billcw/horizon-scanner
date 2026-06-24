"""
patch_server_deepen.py

Adds the /api/thesis/deepen endpoint and background job to
horizon_scanner/dashboard/server.py.

The job:
  - Reads entities_ring1-4 from the DB for a given thesis_id
  - Calls deepen_counterparties() over all rings that carry licensing_hits
  - Writes the mutated ring JSON back via db.update_thesis_rings()
  - Reports companies_processed / filings_read / counterparties_found

Run from C:\\Projects\\horizon-scanner:
    python patch_server_deepen.py

Idempotent: aborts if sentinel already present or anchor not found exactly once.
"""

import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "server.py")

SENTINEL = '"/api/thesis/deepen"'

# ---- Patch 1: register the route in do_POST --------------------------------
# Anchor: the exit-check route line (unique, last POST route before the 404)
ROUTE_ANCHOR = '            if route == "/api/thesis/exit-check":'

ROUTE_INSERTION = '''\
            if route == "/api/thesis/deepen":
                self._handle_deepen()
                return

'''

# ---- Patch 2: insert handler methods before the _handle_exit_check method --
HANDLER_ANCHOR = '    def _handle_exit_check(self):'

HANDLER_INSERTION = '''\
    # -- Deepen counterparties job -----------------------------------------

    def _handle_deepen(self):
        """
        Trigger a "deepen counterparties" pass for one thesis.
        Reads entities_ring* from DB, calls deepen_counterparties(),
        persists the mutated ring JSON back. Background job + poll.

        Body: {"thesis_id": "..."}
        Returns: {"ok": True, "job_id": "..."}
        """
        body = self._read_json_body()
        thesis_id = (body.get("thesis_id") or "").strip()
        if not thesis_id:
            self._send_json({"error": "thesis_id required"}, 400)
            return

        # Prevent duplicate runs for the same thesis
        with _JOBS_LOCK:
            for j in _JOBS.values():
                if (j.get("kind") == "deepen"
                        and j.get("thesis_id") == thesis_id
                        and j.get("status") == "running"):
                    self._send_json({"ok": True, "job_id": j["job_id"],
                                     "already": True})
                    return

        job_id = str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "job_id": job_id,
                "kind": "deepen",
                "thesis_id": thesis_id,
                "status": "running",
                "companies_processed": 0,
                "filings_read": 0,
                "counterparties_found": 0,
                "error": None,
                "started": datetime.now(timezone.utc).isoformat(),
                "finished": None,
            }

        t = threading.Thread(
            target=self._run_deepen_job,
            args=(job_id, thesis_id),
            daemon=True,
        )
        t.start()
        self._send_json({"ok": True, "job_id": job_id})

    def _run_deepen_job(self, job_id: str, thesis_id: str):
        import json as _json

        def _set(**kw):
            with _JOBS_LOCK:
                _JOBS[job_id].update(kw)

        try:
            from ..enrichment.edgar_client import deepen_counterparties

            # Load ring data from DB
            with db.get_connection() as conn:
                row = conn.execute(
                    "SELECT entities_ring1, entities_ring2, "
                    "       entities_ring3, entities_ring4 "
                    "FROM theses WHERE id = ?",
                    (thesis_id,),
                ).fetchone()

            if row is None:
                _set(status="error",
                     error="thesis not found: {}".format(thesis_id),
                     finished=datetime.now(timezone.utc).isoformat())
                return

            def _load(col):
                try:
                    v = row[col]
                    return _json.loads(v) if v else []
                except Exception:
                    return []

            ring1 = _load("entities_ring1")
            ring2 = _load("entities_ring2")
            ring3 = _load("entities_ring3")
            ring4 = _load("entities_ring4")

            # Flatten all rings for the pass; deepen mutates in place
            all_entities = ring1 + ring2 + ring3 + ring4

            _set(status="running")
            result = deepen_counterparties(all_entities)

            # Persist mutated rings back (only if they had content)
            db.update_thesis_rings(
                thesis_id,
                ring1=ring1 if ring1 else None,
                ring2=ring2 if ring2 else None,
                ring3=ring3 if ring3 else None,
                ring4=ring4 if ring4 else None,
            )

            _set(
                status="done",
                companies_processed=result.get("companies_processed", 0),
                filings_read=result.get("filings_read", 0),
                counterparties_found=result.get("counterparties_found", 0),
                finished=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as e:
            logger.error("Deepen job %s failed: %s", job_id, e)
            logger.debug(traceback.format_exc())
            _set(status="error", error=str(e),
                 finished=datetime.now(timezone.utc).isoformat())

    # -- L5-D: exit discipline check ----------------------------------------

'''


def main():
    if not os.path.exists(TARGET):
        print("ERROR: {} not found. Run from project root.".format(TARGET))
        sys.exit(1)

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    # Idempotency
    if SENTINEL in src:
        print("Patch already applied (sentinel found). Nothing to do.")
        sys.exit(0)

    # --- Patch 1: route registration ---
    count = src.count(ROUTE_ANCHOR)
    if count != 1:
        print("ERROR: route anchor found {} times (expected 1):".format(count))
        print("  " + ROUTE_ANCHOR)
        sys.exit(1)
    src = src.replace(ROUTE_ANCHOR, ROUTE_INSERTION + ROUTE_ANCHOR, 1)

    # --- Patch 2: handler methods ---
    # After patch 1 the file is modified; search the updated src
    count2 = src.count(HANDLER_ANCHOR)
    if count2 != 1:
        print("ERROR: handler anchor found {} times (expected 1):".format(count2))
        print("  " + HANDLER_ANCHOR)
        sys.exit(1)
    src = src.replace(HANDLER_ANCHOR, HANDLER_INSERTION, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)

    print("Patched {} successfully.".format(TARGET))
    print("Added: /api/thesis/deepen route + _handle_deepen + _run_deepen_job")


if __name__ == "__main__":
    main()
