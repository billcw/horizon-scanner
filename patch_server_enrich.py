"""
patch_server_enrich.py

Adds a /api/thesis/enrich endpoint to server.py that runs the Step 5.5
EDGAR enrichment pass on an already-generated thesis.

The job:
  - Reads entities_ring1-4 from the DB for a given thesis_id
  - For each company, calls resolve_cik() + find_licensing_mentions()
  - Writes cik, verified_name, ticker_verified, ticker_corrected,
    licensing_hits, edgar_enriched back onto each company object
  - Persists mutated ring JSON via db.update_thesis_rings()
  - Reports companies_enriched, companies_skipped, total_hits

Run from C:\\Projects\\horizon-scanner:
    python patch_server_enrich.py

Idempotent: aborts if sentinel already present or anchors not found exactly once.
"""

import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "server.py")

SENTINEL = '"/api/thesis/enrich"'

# Route anchor: insert BEFORE the deepen route
ROUTE_ANCHOR = '            if route == "/api/thesis/deepen":'

ROUTE_INSERTION = '''\
            if route == "/api/thesis/enrich":
                self._handle_enrich()
                return

'''

# Handler anchor: insert BEFORE _handle_deepen
HANDLER_ANCHOR = '    # -- Deepen counterparties job -----------------------------------------'

HANDLER_INSERTION = '''\
    # -- EDGAR enrichment backfill job --------------------------------------

    def _handle_enrich(self):
        """
        Trigger Step 5.5 EDGAR enrichment on an already-generated thesis.
        Allows enriching theses that pre-date the enrichment feature.

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
                if (j.get("kind") == "enrich"
                        and j.get("thesis_id") == thesis_id
                        and j.get("status") == "running"):
                    self._send_json({"ok": True, "job_id": j["job_id"],
                                     "already": True})
                    return

        job_id = str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "job_id": job_id,
                "kind": "enrich",
                "thesis_id": thesis_id,
                "status": "running",
                "step": "starting",
                "companies_enriched": 0,
                "companies_skipped": 0,
                "total_hits": 0,
                "error": None,
                "started": datetime.now(timezone.utc).isoformat(),
                "finished": None,
            }

        t = threading.Thread(
            target=self._run_enrich_job,
            args=(job_id, thesis_id),
            daemon=True,
        )
        t.start()
        self._send_json({"ok": True, "job_id": job_id})

    def _run_enrich_job(self, job_id: str, thesis_id: str):
        import json as _json

        def _set(**kw):
            with _JOBS_LOCK:
                _JOBS[job_id].update(kw)

        try:
            from ..enrichment.edgar_client import (
                resolve_cik,
                find_licensing_mentions,
            )

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

            all_rings = [ring1, ring2, ring3, ring4]
            companies_enriched = 0
            companies_skipped = 0
            total_hits = 0

            for ring in all_rings:
                for co in ring:
                    if not isinstance(co, dict):
                        continue
                    ticker = (co.get("ticker") or "").strip()
                    company = (co.get("company") or "").strip()
                    lookup = ticker or company
                    if not lookup:
                        companies_skipped += 1
                        continue

                    _set(step="resolving {}".format(lookup))

                    # CIK resolution
                    try:
                        ident = resolve_cik(lookup)
                    except Exception as e:
                        logger.warning("Enrich: resolve_cik failed for %s: %s",
                                       lookup, e)
                        ident = {}

                    if not ident:
                        # Try company name if ticker didn't work
                        if ticker and company:
                            try:
                                ident = resolve_cik(company)
                            except Exception:
                                ident = {}

                    if ident:
                        co["cik"] = ident.get("cik")
                        co["verified_name"] = ident.get("title", "")
                        co["ticker_verified"] = True
                        if ticker and ident.get("ticker", "").upper() != ticker.upper():
                            co["ticker_corrected"] = ident.get("ticker", "")
                    else:
                        co["ticker_verified"] = False
                        co.setdefault("cik", None)
                        co.setdefault("verified_name", "")

                    # Licensing hits
                    hits = []
                    if ident:
                        _set(step="EDGAR search: {}".format(lookup))
                        try:
                            result = find_licensing_mentions(lookup)
                            hits = result.get("hits", [])
                        except Exception as e:
                            logger.warning("Enrich: find_licensing_mentions "
                                           "failed for %s: %s", lookup, e)
                            hits = []

                    co["licensing_hits"] = hits
                    co["edgar_enriched"] = True
                    total_hits += len(hits)
                    companies_enriched += 1
                    _set(
                        companies_enriched=companies_enriched,
                        companies_skipped=companies_skipped,
                        total_hits=total_hits,
                    )

            # Persist all four rings back
            db.update_thesis_rings(
                thesis_id,
                ring1=ring1 if ring1 else None,
                ring2=ring2 if ring2 else None,
                ring3=ring3 if ring3 else None,
                ring4=ring4 if ring4 else None,
            )

            _set(
                status="done",
                step="complete",
                companies_enriched=companies_enriched,
                companies_skipped=companies_skipped,
                total_hits=total_hits,
                finished=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as e:
            logger.error("Enrich job %s failed: %s", job_id, e)
            logger.debug(traceback.format_exc())
            _set(status="error", error=str(e),
                 finished=datetime.now(timezone.utc).isoformat())

    # -- Deepen counterparties job -----------------------------------------
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

    # --- Patch 1: route ---
    count = src.count(ROUTE_ANCHOR)
    if count != 1:
        print("ERROR: route anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(ROUTE_ANCHOR, ROUTE_INSERTION + ROUTE_ANCHOR, 1)

    # --- Patch 2: handler (search updated src) ---
    count2 = src.count(HANDLER_ANCHOR)
    if count2 != 1:
        print("ERROR: handler anchor found {} times (expected 1).".format(count2))
        sys.exit(1)
    src = src.replace(HANDLER_ANCHOR, HANDLER_INSERTION, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)

    print("Patched {} successfully.".format(TARGET))
    print("Added: /api/thesis/enrich route + _handle_enrich + _run_enrich_job")


if __name__ == "__main__":
    main()
