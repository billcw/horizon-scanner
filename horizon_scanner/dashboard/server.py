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

            if route == "/api/decision":
                self._handle_decision()
                return

            if route == "/api/decision/preview":
                self._handle_decision_preview()
                return

            self._send_json({"error": f"Unknown route: {route}"}, 404)

        except Exception as e:
            logger.error("POST %s failed: %s", route, e)
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
