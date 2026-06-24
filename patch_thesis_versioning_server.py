import ast, sys

path = r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\server.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

SENTINEL = "# THESIS-VERSIONING-SERVER"
if SENTINEL in src:
    print("Patch already applied. Nothing to do.")
    sys.exit(0)

# --- Change 1: add GET route for thesis versions ---
OLD1 = ('            self._send_json({"error": f"Unknown route: {route}"}, 404)\n'
        '\n'
        '        except Exception as e:\n'
        '            logger.error("GET %s failed: %s", route, e)')
NEW1 = ('            # /api/thesis/<id>/versions -- version history\n'
        '            # THESIS-VERSIONING-SERVER\n'
        '            if route.startswith("/api/thesis/") and route.endswith("/versions"):\n'
        '                thesis_id = route[len("/api/thesis/"):-len("/versions")].strip("/")\n'
        '                versions = db.get_thesis_versions(thesis_id)\n'
        '                self._send_json({"versions": versions})\n'
        '                return\n'
        '\n'
        '            self._send_json({"error": f"Unknown route: {route}"}, 404)\n'
        '\n'
        '        except Exception as e:\n'
        '            logger.error("GET %s failed: %s", route, e)')

count1 = src.count(OLD1)
if count1 != 1:
    print(f"ERROR: anchor 1 found {count1} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD1, NEW1, 1)

# --- Change 2: add POST route for rerun ---
OLD2 = ('            if route == "/api/thesis/exit-check":\n'
        '                self._handle_exit_check()\n'
        '                return')
NEW2 = ('            if route == "/api/thesis/exit-check":\n'
        '                self._handle_exit_check()\n'
        '                return\n'
        '\n'
        '            if route == "/api/thesis/rerun":\n'
        '                self._handle_thesis_rerun()\n'
        '                return')

count2 = src.count(OLD2)
if count2 != 1:
    print(f"ERROR: anchor 2 found {count2} times (expected 1). Aborting.")
    sys.exit(1)
src = src.replace(OLD2, NEW2, 1)

# --- Change 3: add rerun handler methods before _handle_thesis_run ---
OLD3 = '    def _handle_thesis_run(self):'
NEW3 = (
    '    def _handle_thesis_rerun(self):\n'
    '        """Re-run the thesis loop on an existing thesis, snapshotting first.\n'
    '        Body: {"thesis_id": "...", "trigger": "manual_rerun"}\n'
    '        """\n'
    '        body = self._read_json_body()\n'
    '        thesis_id = (body.get("thesis_id") or "").strip()\n'
    '        trigger = (body.get("trigger") or "manual_rerun").strip()\n'
    '        if not thesis_id:\n'
    '            self._send_json({"error": "thesis_id required"}, 400)\n'
    '            return\n'
    '\n'
    '        with _JOBS_LOCK:\n'
    '            for j in _JOBS.values():\n'
    '                if (j.get("kind") == "thesis_rerun"\n'
    '                        and j.get("thesis_id") == thesis_id\n'
    '                        and j.get("status") == "running"):\n'
    '                    self._send_json({"ok": True, "job_id": j["job_id"], "already": True})\n'
    '                    return\n'
    '\n'
    '        job_id = str(uuid.uuid4())\n'
    '        with _JOBS_LOCK:\n'
    '            _JOBS[job_id] = {\n'
    '                "job_id": job_id,\n'
    '                "kind": "thesis_rerun",\n'
    '                "thesis_id": thesis_id,\n'
    '                "status": "running",\n'
    '                "error": None,\n'
    '                "started": datetime.now(timezone.utc).isoformat(),\n'
    '                "finished": None,\n'
    '            }\n'
    '\n'
    '        t = threading.Thread(\n'
    '            target=self._run_thesis_rerun_job,\n'
    '            args=(job_id, thesis_id, trigger),\n'
    '            daemon=True\n'
    '        )\n'
    '        t.start()\n'
    '        self._send_json({"ok": True, "job_id": job_id})\n'
    '\n'
    '    def _run_thesis_rerun_job(self, job_id: str, thesis_id: str, trigger: str):\n'
    '        """Background worker: snapshot then re-run thesis loop."""\n'
    '        from ..thesis.thesis_loop import run_thesis_loop\n'
    '        try:\n'
    '            version_num = db.snapshot_thesis_version(thesis_id, trigger)\n'
    '            logger.info("Thesis %s snapshotted as version %s", thesis_id, version_num)\n'
    '\n'
    '            with db.get_connection() as conn:\n'
    '                row = conn.execute(\n'
    '                    "SELECT cluster_id FROM theses WHERE id=?", (thesis_id,)\n'
    '                ).fetchone()\n'
    '            if row is None or not row["cluster_id"]:\n'
    '                raise ValueError("Thesis has no cluster_id, cannot rerun.")\n'
    '            cluster_id = row["cluster_id"]\n'
    '\n'
    '            new_thesis_id, _state = run_thesis_loop(cluster_id)\n'
    '            with _JOBS_LOCK:\n'
    '                _JOBS[job_id]["status"] = "done"\n'
    '                _JOBS[job_id]["thesis_id"] = new_thesis_id\n'
    '                _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()\n'
    '        except Exception as e:\n'
    '            logger.error("Thesis rerun job %s failed: %s", job_id, e)\n'
    '            logger.debug(traceback.format_exc())\n'
    '            with _JOBS_LOCK:\n'
    '                _JOBS[job_id]["status"] = "error"\n'
    '                _JOBS[job_id]["error"] = str(e)\n'
    '                _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()\n'
    '\n'
    '    def _handle_thesis_run(self):'
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

print("Patch applied. New routes: POST /api/thesis/rerun, GET /api/thesis/<id>/versions.")
