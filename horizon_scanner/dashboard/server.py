"""
dashboard/server.py

Phase 3A - Horizon Scanner dashboard backend.

A dependency-free HTTP server (Python stdlib only) that:
  - serves the static dashboard (index.html and assets)
  - exposes a small JSON API over the existing SQLite database and config.yaml
  - can trigger a thesis run on a cluster
  - logs buy/hold/sell decisions with behavioural emotional-flagging

Start it with:  python run.py dashboard
Then open:      http://localhost:8080

Design notes:
  - No Flask, no FastAPI. http.server keeps the install footprint at zero new
    packages, which matters on the Windows/PowerShell target environment.
  - Config edits are written back to BOTH copies of config.yaml (root + package)
    so config.py reads the same values it always has.
  - Thesis runs happen in a background thread so the HTTP request returns
    immediately; the UI polls /api/jobs to watch progress.
"""

import json
import logging
import os
import threading
import traceback
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from ..config import (
    get_config, get_project_root, PACKAGE_DIR
)
from .. import database as db
from . import export as export_mod

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory job registry for background thesis runs
# ---------------------------------------------------------------------------
# Maps job_id -> dict(status, cluster_id, theme, thesis_id, error, started, finished)
_JOBS = {}
_JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Config file writing (back to disk, both copies)
# ---------------------------------------------------------------------------

def _config_paths():
    """Return the list of config.yaml paths to keep in sync."""
    root = get_project_root()
    paths = [
        os.path.join(root, "config.yaml"),
        os.path.join(PACKAGE_DIR, "config.yaml"),
    ]
    return [p for p in paths if os.path.exists(p)]


def _write_config(new_cfg: dict):
    """
    Write the config dict back to every config.yaml copy.
    Uses yaml.safe_dump with sort_keys=False to preserve a readable layout.
    """
    import yaml
    for path in _config_paths():
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(new_cfg, f, sort_keys=False, default_flow_style=False,
                           allow_unicode=False, width=100)
    # Force the config module to reload on next get_config()
    try:
        from ..config import reset_config_cache
        reset_config_cache()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Emotional flagging logic (behavioural, pre-price-data)
# ---------------------------------------------------------------------------

# Phrases that suggest FOMO / hype-driven reasoning
_FOMO_PHRASES = [
    "can't miss", "cant miss", "everyone is talking", "everyone's talking",
    "obvious", "sure thing", "guaranteed", "to the moon", "fomo",
    "before it's too late", "before its too late", "no brainer", "no-brainer",
    "easy money", "all in", "yolo",
]


def _evaluate_emotional_flag(decision_type: str, stated_reason: str,
                             thesis: dict) -> tuple[bool, str]:
    """
    Behavioural emotional-flag heuristic. Returns (flag, reason).

    Fires when any of:
      1. A BUY decision overrides a WATCH/INSUFFICIENT confidence thesis
         (the thesis itself says "not ready", but you're buying anyway).
      2. A BUY decision is made within 48h of the thesis being generated
         (insufficient reflection time - the MU mistake in reverse).
      3. The stated reason contains FOMO / hype language.

    Price-movement triggers (condition 4) are added in Phase 4 once L4
    monitoring supplies live ticker data.
    """
    reasons = []
    dtype = (decision_type or "").upper()

    if dtype == "BUY" and thesis:
        confidence = (thesis.get("confidence_rating") or "").upper()
        if confidence in ("WATCH", "INSUFFICIENT"):
            reasons.append(
                f"BUY overrides a {confidence} thesis - the analysis flagged this "
                f"as not yet actionable."
            )

        created = thesis.get("created_at")
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600.0
                if age_hours < 48:
                    reasons.append(
                        f"BUY made {age_hours:.0f}h after thesis generation "
                        f"(under the 48h reflection window)."
                    )
            except (ValueError, AttributeError):
                pass

    low = (stated_reason or "").lower()
    for phrase in _FOMO_PHRASES:
        if phrase in low:
            reasons.append(f"Stated reason contains FOMO language: '{phrase}'.")
            break

    if reasons:
        return True, " ".join(reasons)
    return False, ""


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class HorizonHandler(BaseHTTPRequestHandler):

    # Silence the default noisy logging; route through our logger instead
    def log_message(self, fmt, *args):
        logger.debug("%s - %s", self.address_string(), fmt % args)

    # ---- helpers ----------------------------------------------------------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json({"error": f"Not found: {os.path.basename(path)}"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    @property
    def _static_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    # ---- GET --------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            if route in ("/", "/index.html"):
                self._send_file(os.path.join(self._static_dir, "index.html"),
                                "text/html; charset=utf-8")
                return

            if route == "/api/clusters":
                self._send_json(export_mod.clusters_payload())
                return

            if route == "/api/theses":
                self._send_json(export_mod.theses_payload())
                return

            if route == "/api/decisions":
                self._send_json(export_mod.decisions_payload())
                return

            if route == "/api/stats":
                self._send_json(db.get_stats())
                return

            if route == "/api/config":
                self._send_json(export_mod.config_payload())
                return

            if route == "/api/jobs":
                with _JOBS_LOCK:
                    self._send_json({"jobs": list(_JOBS.values())})
                return

            if route == "/api/sources":
                self._send_json({"sources": db.list_sources()})
                return

            # Unknown route
            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("GET %s failed: %s", route, e)
            logger.debug(traceback.format_exc())
            self._send_json({"error": str(e)}, 500)

    # ---- POST -------------------------------------------------------------

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            if route == "/api/config":
                self._handle_config_save()
                return

            if route == "/api/thesis/run":
                self._handle_thesis_run()
                return

            if route == "/api/pipeline/refresh":
                self._handle_pipeline_refresh()
                return

            if route == "/api/decision":
                self._handle_decision()
                return

            if route == "/api/decision/preview":
                self._handle_decision_preview()
                return

            if route == "/api/sources":
                self._handle_source_add()
                return

            if route == "/api/sources/toggle":
                self._handle_source_toggle()
                return

            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("POST %s failed: %s", route, e)
            logger.debug(traceback.format_exc())
            self._send_json({"error": str(e)}, 500)

    # ---- DELETE -----------------------------------------------------------

    def do_DELETE(self):
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            # /api/decision/<id>
            if route.startswith("/api/decision/"):
                decision_id = route[len("/api/decision/"):].strip("/")
                if not decision_id:
                    self._send_json({"error": "decision id required"}, 400)
                    return
                removed = db.delete_decision(decision_id)
                if removed:
                    self._send_json({"ok": True, "deleted": decision_id})
                else:
                    self._send_json({"error": "decision not found"}, 404)
                return

            # /api/sources/<id>
            if route.startswith("/api/sources/"):
                source_id = route[len("/api/sources/"):].strip("/")
                if not source_id:
                    self._send_json({"error": "source id required"}, 400)
                    return
                removed = db.delete_source(source_id)
                if removed:
                    self._send_json({"ok": True, "deleted": source_id})
                else:
                    self._send_json({"error": "source not found"}, 404)
                return

            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("DELETE %s failed: %s", route, e)
            logger.debug(traceback.format_exc())
            self._send_json({"error": str(e)}, 500)

    # ---- POST handlers ----------------------------------------------------

    def _handle_config_save(self):
        """Merge posted settings into config.yaml and write to disk."""
        updates = self._read_json_body()
        if not isinstance(updates, dict) or not updates:
            self._send_json({"error": "Empty or invalid config payload"}, 400)
            return

        cfg = get_config()
        # Deep-merge only the sections the UI is allowed to edit
        _deep_merge(cfg, updates)
        _write_config(cfg)
        self._send_json({"ok": True, "message": "Settings saved. Takes effect on next run."})

    def _handle_thesis_run(self):
        """Kick off a thesis loop in a background thread."""
        body = self._read_json_body()
        cluster_id = body.get("cluster_id")
        if not cluster_id:
            self._send_json({"error": "cluster_id required"}, 400)
            return

        job_id = str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "job_id": job_id,
                "cluster_id": cluster_id,
                "theme": body.get("theme", ""),
                "status": "running",
                "thesis_id": None,
                "error": None,
                "started": datetime.now(timezone.utc).isoformat(),
                "finished": None,
            }

        t = threading.Thread(target=self._run_thesis_job, args=(job_id, cluster_id), daemon=True)
        t.start()
        self._send_json({"ok": True, "job_id": job_id})

    def _run_thesis_job(self, job_id, cluster_id):
        """Background worker - runs the 8-step loop, updates the job record."""
        from ..thesis.thesis_loop import run_thesis_loop
        try:
            thesis_id, _state = run_thesis_loop(cluster_id)
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "done"
                _JOBS[job_id]["thesis_id"] = thesis_id
                _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            logger.error("Thesis job %s failed: %s", job_id, e)
            logger.debug(traceback.format_exc())
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "error"
                _JOBS[job_id]["error"] = str(e)
                _JOBS[job_id]["finished"] = datetime.now(timezone.utc).isoformat()

    def _handle_pipeline_refresh(self):
        """Kick off collect-then-classify in a background thread.
        Optional body {"source": "arxiv"|"reddit"|"trends"} limits collection
        to one source; omitted or "all" collects everything."""
        body = self._read_json_body()
        source = (body.get("source") or "all").lower()
        if source not in ("all", "arxiv", "reddit", "trends"):
            self._send_json({"error": f"Unknown source: {source}"}, 400)
            return

        # Only allow one refresh at a time (any source).
        with _JOBS_LOCK:
            for j in _JOBS.values():
                if j.get("kind") == "refresh" and j.get("status") == "running":
                    self._send_json({"ok": True, "job_id": j["job_id"], "already": True})
                    return

        job_id = str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "job_id": job_id,
                "kind": "refresh",
                "source": source,
                "status": "running",
                "step": "starting",
                "collected": 0,
                "classified": 0,
                "error": None,
                "started": datetime.now(timezone.utc).isoformat(),
                "finished": None,
            }

        t = threading.Thread(target=self._run_refresh_job, args=(job_id, source), daemon=True)
        t.start()
        self._send_json({"ok": True, "job_id": job_id})

    def _run_refresh_job(self, job_id, source="all"):
        """
        Background worker: collect from the requested source(s), then classify
        until the queue is drained. Mirrors run.py's cmd_collect + cmd_classify,
        with progress written to the job record for live UI status.
        """
        def _set(**kw):
            with _JOBS_LOCK:
                _JOBS[job_id].update(kw)

        try:
            # ---- Collect --------------------------------------------------
            from ..collectors.arxiv_collector  import run as run_arxiv
            from ..collectors.reddit_collector import run as run_reddit
            from ..collectors.trends_collector import run as run_trends

            all_sources = {"arxiv": run_arxiv, "reddit": run_reddit, "trends": run_trends}
            if source == "all":
                targets = all_sources.items()
            else:
                targets = [(source, all_sources[source])]

            collected = 0
            for name, fn in targets:
                _set(step=f"collecting: {name}")
                try:
                    n = fn() or 0
                    collected += n
                    _set(collected=collected)
                except Exception as e:
                    logger.warning("Collector %s failed during refresh: %s", name, e)

            # ---- Classify (drain the queue) -------------------------------
            _set(step="classifying signals")
            from ..classifier.signal_classifier import run_classifier

            classified = 0
            # Cap iterations so a misbehaving batch can't loop forever.
            for _ in range(100):
                n = run_classifier(batch_size=100) or 0
                if n == 0:
                    break
                classified += n
                _set(classified=classified, step=f"classifying ({classified} so far)")

            _set(status="done", step="complete",
                 finished=datetime.now(timezone.utc).isoformat())

        except Exception as e:
            logger.error("Refresh job %s failed: %s", job_id, e)
            logger.debug(traceback.format_exc())
            _set(status="error", error=str(e),
                 finished=datetime.now(timezone.utc).isoformat())

    def _handle_source_add(self):
        """Add a source to the library. Body: {source_type, value, label?}."""
        body = self._read_json_body()
        source_type = (body.get("source_type") or "").lower()
        value = body.get("value", "")
        label = body.get("label", "")
        if source_type not in ("arxiv", "trends", "reddit"):
            self._send_json({"error": "source_type must be arxiv, trends, or reddit"}, 400)
            return
        if not (value or "").strip():
            self._send_json({"error": "value required"}, 400)
            return
        try:
            sid = db.add_source(source_type, value, label, enabled=True)
            self._send_json({"ok": True, "id": sid})
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)

    def _handle_source_toggle(self):
        """Enable/disable a source. Body: {id, enabled}."""
        body = self._read_json_body()
        source_id = body.get("id")
        enabled = bool(body.get("enabled"))
        if not source_id:
            self._send_json({"error": "id required"}, 400)
            return
        changed = db.set_source_enabled(source_id, enabled)
        if changed:
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "source not found"}, 404)

    def _handle_decision_preview(self):
        """
        Evaluate the emotional flag WITHOUT logging, so the UI can warn the
        user before they commit. Returns {flag, reason}.
        """
        body = self._read_json_body()
        thesis_id = body.get("thesis_id")
        thesis = export_mod.get_thesis_dict(thesis_id) if thesis_id else {}
        flag, reason = _evaluate_emotional_flag(
            body.get("decision_type", ""),
            body.get("stated_reason", ""),
            thesis,
        )
        self._send_json({"flag": flag, "reason": reason})

    def _handle_decision(self):
        """Log a buy/hold/sell decision with emotional flagging."""
        body = self._read_json_body()
        decision_type = body.get("decision_type")
        stated_reason = body.get("stated_reason", "")
        thesis_id = body.get("thesis_id")
        ticker = body.get("ticker")

        if not decision_type:
            self._send_json({"error": "decision_type required (BUY/HOLD/SELL/PASS/WATCH)"}, 400)
            return

        thesis = export_mod.get_thesis_dict(thesis_id) if thesis_id else {}
        flag, reason = _evaluate_emotional_flag(decision_type, stated_reason, thesis)

        # The UI can pass acknowledge=true to log despite the flag
        decision_id = db.log_decision(
            decision_type=decision_type,
            stated_reason=stated_reason,
            thesis_id=thesis_id,
            ticker=ticker,
            thesis_snapshot=thesis or None,
            emotional_flag=flag,
            emotional_reason=reason,
            pattern_tag=body.get("pattern_tag", ""),
        )
        self._send_json({
            "ok": True,
            "decision_id": decision_id,
            "emotional_flag": flag,
            "emotional_reason": reason,
        })


# ---------------------------------------------------------------------------
# Utility: deep merge for config updates
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, updates: dict):
    """Recursively merge updates into base (mutates base)."""
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def serve(host="127.0.0.1", port=8080, open_browser=True):
    """Start the dashboard server. Blocks until Ctrl+C."""
    server = ThreadingHTTPServer((host, port), HorizonHandler)
    url = f"http://{host}:{port}"
    print(f"\n  Horizon Scanner dashboard running at {url}")
    print("  Press Ctrl+C to stop.\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")
    finally:
        server.server_close()
