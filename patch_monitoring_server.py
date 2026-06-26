"""
patch_monitoring_server.py -- L4 monitoring server wiring.
Idempotent, anchor-guarded. Run from project root: python patch_monitoring_server.py

Adds:
  - module-level start_thesis_rerun + _run_thesis_rerun_worker
  - delegates _handle_thesis_rerun to start_thesis_rerun
  - POST /api/monitoring/check, /api/monitoring/read-all,
    /api/monitoring/events/<id>/read
  - GET  /api/monitoring/events, /api/monitoring/unread-count
  - _handle_monitoring_check method
  - monitoring pass hook in Refresh All (source == "all")
"""
import ast
import io
import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "server.py")
SENTINEL = "# L4-MONITORING-SERVER"


def _require(src, anchor, label):
    c = src.count(anchor)
    if c != 1:
        print("ABORT: anchor for [%s] found %d times (expected 1). No change." % (label, c))
        sys.exit(1)


EDITS = []

# 1) Module-level rerun functions after job registry globals.
EDITS.append((
    "globals_rerun",
    "_JOBS = {}\n_JOBS_LOCK = threading.Lock()\n",
    '''_JOBS = {}
_JOBS_LOCK = threading.Lock()


# L4-MONITORING-SERVER
# Module-level thesis rerun (shared by HTTP handler and L4 monitoring auto-rerun).
def _run_thesis_rerun_worker(job_id, thesis_id, trigger):
    """Background worker: snapshot then re-run thesis loop."""
    from ..thesis.thesis_loop import run_thesis_loop
    try:
        version_num = db.snapshot_thesis_version(thesis_id, trigger)
        logger.info("Thesis %s snapshotted as version %s", thesis_id, version_num)

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT cluster_id FROM theses WHERE id=?", (thesis_id,)
            ).fetchone()
        if row is None or not row["cluster_id"]:
            raise ValueError("Thesis has no cluster_id, cannot rerun.")
        cluster_id = row["cluster_id"]

        new_thesis_id, _state = run_thesis_loop(cluster_id)
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done"
            _JOBS[job_id]["thesis_id"] = new_thesis_id
            _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.error("Thesis rerun job %s failed: %s", job_id, e)
        logger.debug(traceback.format_exc())
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["error"] = str(e)
            _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()


def start_thesis_rerun(thesis_id, trigger="manual_rerun"):
    """Snapshot + re-run a thesis loop in a background thread.

    Dedups against any already-running rerun for the same thesis.
    Returns a dict suitable for JSON response:
        {"ok": True, "job_id": "...", "already": bool}
    """
    with _JOBS_LOCK:
        for j in _JOBS.values():
            if (j.get("kind") == "thesis_rerun"
                    and j.get("thesis_id") == thesis_id
                    and j.get("status") == "running"):
                return {"ok": True, "job_id": j["job_id"], "already": True}

    job_id = str(uuid.uuid4())
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "kind": "thesis_rerun",
            "thesis_id": thesis_id,
            "status": "running",
            "error": None,
            "started": datetime.now(timezone.utc).isoformat(),
            "finished": None,
        }

    t = threading.Thread(
        target=_run_thesis_rerun_worker,
        args=(job_id, thesis_id, trigger),
        daemon=True,
    )
    t.start()
    return {"ok": True, "job_id": job_id}
''',
))

# 2) Replace _handle_thesis_rerun body + delete old _run_thesis_rerun_job method.
EDITS.append((
    "rerun_method",
    '''    def _handle_thesis_rerun(self):
        """Re-run the thesis loop on an existing thesis, snapshotting first.
        Body: {"thesis_id": "...", "trigger": "manual_rerun"}
        """
        body = self._read_json_body()
        thesis_id = (body.get("thesis_id") or "").strip()
        trigger = (body.get("trigger") or "manual_rerun").strip()
        if not thesis_id:
            self._send_json({"error": "thesis_id required"}, 400)
            return

        with _JOBS_LOCK:
            for j in _JOBS.values():
                if (j.get("kind") == "thesis_rerun"
                        and j.get("thesis_id") == thesis_id
                        and j.get("status") == "running"):
                    self._send_json({"ok": True, "job_id": j["job_id"], "already": True})
                    return

        job_id = str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "job_id": job_id,
                "kind": "thesis_rerun",
                "thesis_id": thesis_id,
                "status": "running",
                "error": None,
                "started": datetime.now(timezone.utc).isoformat(),
                "finished": None,
            }

        t = threading.Thread(
            target=self._run_thesis_rerun_job,
            args=(job_id, thesis_id, trigger),
            daemon=True
        )
        t.start()
        self._send_json({"ok": True, "job_id": job_id})

    def _run_thesis_rerun_job(self, job_id: str, thesis_id: str, trigger: str):
        """Background worker: snapshot then re-run thesis loop."""
        from ..thesis.thesis_loop import run_thesis_loop
        try:
            version_num = db.snapshot_thesis_version(thesis_id, trigger)
            logger.info("Thesis %s snapshotted as version %s", thesis_id, version_num)

            with db.get_connection() as conn:
                row = conn.execute(
                    "SELECT cluster_id FROM theses WHERE id=?", (thesis_id,)
                ).fetchone()
            if row is None or not row["cluster_id"]:
                raise ValueError("Thesis has no cluster_id, cannot rerun.")
            cluster_id = row["cluster_id"]

            new_thesis_id, _state = run_thesis_loop(cluster_id)
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "done"
                _JOBS[job_id]["thesis_id"] = new_thesis_id
                _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            logger.error("Thesis rerun job %s failed: %s", job_id, e)
            logger.debug(traceback.format_exc())
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "error"
                _JOBS[job_id]["error"] = str(e)
                _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()''',
    '''    def _handle_thesis_rerun(self):
        """Re-run the thesis loop on an existing thesis, snapshotting first.
        Body: {"thesis_id": "...", "trigger": "manual_rerun"}
        Delegates to module-level start_thesis_rerun (shared with L4 monitoring).
        """
        body = self._read_json_body()
        thesis_id = (body.get("thesis_id") or "").strip()
        trigger = (body.get("trigger") or "manual_rerun").strip()
        if not thesis_id:
            self._send_json({"error": "thesis_id required"}, 400)
            return
        result = start_thesis_rerun(thesis_id, trigger)
        self._send_json(result)

    # L4-MONITORING-SERVER
    def _handle_monitoring_check(self):
        """Run the L4 monitoring pass on demand (no collectors). Check Monitoring button."""
        from ..monitoring.monitoring_pass import run_monitoring_pass
        summary = run_monitoring_pass(trigger="manual_check")
        self._send_json({"ok": True, "summary": summary})''',
))

# 3) POST monitoring routes.
EDITS.append((
    "post_routes",
    '''            if route == "/api/sources/toggle":
                self._handle_source_toggle()
                return

            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("POST %s failed: %s", route, e)''',
    '''            if route == "/api/sources/toggle":
                self._handle_source_toggle()
                return

            # L4-MONITORING-SERVER
            if route == "/api/monitoring/check":
                self._handle_monitoring_check()
                return

            if route == "/api/monitoring/read-all":
                db.mark_all_monitoring_read()
                self._send_json({"ok": True})
                return

            if route.startswith("/api/monitoring/events/") and route.endswith("/read"):
                event_id = route[len("/api/monitoring/events/"):-len("/read")].strip("/")
                db.mark_monitoring_event_read(event_id)
                self._send_json({"ok": True, "id": event_id})
                return

            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("POST %s failed: %s", route, e)''',
))

# 4) GET monitoring routes.
EDITS.append((
    "get_routes",
    '''            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("GET %s failed: %s", route, e)''',
    '''            # L4-MONITORING-SERVER
            if route == "/api/monitoring/events":
                qs = parse_qs(parsed.query)
                unread_only = qs.get("unread", ["0"])[0] in ("1", "true", "True")
                events = db.get_monitoring_events(limit=200, unread_only=unread_only)
                self._send_json({"events": events})
                return

            if route == "/api/monitoring/unread-count":
                self._send_json({"count": db.get_unread_monitoring_count()})
                return

            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("GET %s failed: %s", route, e)''',
))

# 5) Refresh All monitoring hook.
EDITS.append((
    "refresh_hook",
    '''                classified += n
                _set(classified=classified, step=f"classifying ({classified} so far)")

            _set(status="done", step="complete",
                 finished=datetime.now(timezone.utc).isoformat())''',
    '''                classified += n
                _set(classified=classified, step=f"classifying ({classified} so far)")

            # L4-MONITORING-SERVER: run monitoring pass after a full refresh.
            if source == "all":
                try:
                    _set(step="monitoring pass")
                    from ..monitoring.monitoring_pass import run_monitoring_pass
                    msum = run_monitoring_pass(trigger="refresh_all")
                    _set(monitoring_events=msum.get("events_created", 0))
                except Exception as e:
                    logger.warning("Monitoring pass failed during refresh: %s", e)

            _set(status="done", step="complete",
                 finished=datetime.now(timezone.utc).isoformat())''',
))


def main():
    if not os.path.exists(TARGET):
        print("ABORT: %s not found. Run from project root." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Already applied (sentinel present). No change.")
        return

    # Validate all anchors are unique BEFORE writing anything.
    for label, old, _new in EDITS:
        _require(src, old, label)

    new_src = src
    for label, old, new in EDITS:
        new_src = new_src.replace(old, new, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print("ABORT: result fails AST parse: %s" % e)
        sys.exit(1)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)
    print("OK: applied L4 monitoring server wiring (5 edits) to %s" % TARGET)


if __name__ == "__main__":
    main()
