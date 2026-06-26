"""
dashboard/server.py

Phase 3A + L5 -- Horizon Scanner dashboard backend.

A dependency-free HTTP server (Python stdlib only) that:
  - serves the static dashboard (index.html and assets)
  - exposes a small JSON API over the existing SQLite database and config.yaml
  - can trigger a thesis run on a cluster
  - logs buy/hold/sell decisions with behavioural emotional-flagging
  - records decision outcomes and triggers AI post-mortems (L5-A/B)
  - runs exit discipline checks against live theses (L5-D)

Start it with:  python run.py dashboard
Then open:      http://localhost:8080

Design notes:
  - No Flask, no FastAPI. http.server keeps the install footprint at zero new
    packages, which matters on the Windows/PowerShell target environment.
  - Config edits are written back to BOTH copies of config.yaml (root + package)
    so config.py reads the same values it always has.
  - Thesis runs, pipeline refreshes, and post-mortem jobs all happen in
    background threads so HTTP requests return immediately; the UI polls
    /api/jobs to watch progress.
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
from ..database import DecisionLockedError
from . import export as export_mod

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory job registry for background thesis runs and post-mortems
# ---------------------------------------------------------------------------
# Maps job_id -> dict(status, kind, ..., error, started, finished)
_JOBS = {}
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
    try:
        from ..config import reset_config_cache
        reset_config_cache()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Emotional flagging logic (behavioural, pre-price-data)
# ---------------------------------------------------------------------------

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
      1. A BUY decision overrides a WATCH/INSUFFICIENT confidence thesis.
      2. A BUY decision is made within 48h of thesis generation.
      3. The stated reason contains FOMO / hype language.
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

            # L5: full outcomes + pattern data
            if route == "/api/outcomes":
                self._send_json(export_mod.outcomes_payload())
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

            # /api/decision/<id>  -- single decision detail (for outcome form)
            if route.startswith("/api/decision/") and not route.endswith("/postmortem"):
                decision_id = route[len("/api/decision/"):].strip("/")
                d = db.get_decision_by_id(decision_id)
                if d:
                    d["emotional_flag"] = bool(d.get("emotional_flag"))
                    d["outcome_resolved"] = bool(d.get("outcome_resolved"))
                    self._send_json({"decision": d})
                else:
                    self._send_json({"error": "not found"}, 404)
                return

            # /api/thesis/<id>/versions -- version history
            # THESIS-VERSIONING-SERVER
            if route.startswith("/api/thesis/") and route.endswith("/versions"):
                thesis_id = route[len("/api/thesis/"):-len("/versions")].strip("/")
                versions = db.get_thesis_versions(thesis_id)
                self._send_json({"versions": versions})
                return

            # L4-MONITORING-SERVER
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

            # L5-A: record outcome data for a decision
            if route == "/api/decision/outcome":
                self._handle_outcome_record()
                return

            # L5-B: trigger AI post-mortem for a resolved decision
            if route == "/api/decision/postmortem":
                self._handle_postmortem_trigger()
                return

            # L5-D: exit discipline check for a live thesis
            if route == "/api/thesis/enrich":
                self._handle_enrich()
                return

            if route == "/api/thesis/deepen":
                self._handle_deepen()
                return

            if route == "/api/thesis/exit-check":
                self._handle_exit_check()
                return

            if route == "/api/thesis/rerun":
                self._handle_thesis_rerun()
                return

            if route == "/api/sources":
                self._handle_source_add()
                return

            if route == "/api/sources/toggle":
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
            logger.error("POST %s failed: %s", route, e)
            logger.debug(traceback.format_exc())
            self._send_json({"error": str(e)}, 500)

    # ---- DELETE -----------------------------------------------------------

    def do_DELETE(self):
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            if route.startswith("/api/decision/"):
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
                return

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
        updates = self._read_json_body()
        if not isinstance(updates, dict) or not updates:
            self._send_json({"error": "Empty or invalid config payload"}, 400)
            return
        cfg = get_config()
        _deep_merge(cfg, updates)
        _write_config(cfg)
        self._send_json({"ok": True, "message": "Settings saved. Takes effect on next run."})

    def _handle_thesis_rerun(self):
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
        self._send_json({"ok": True, "summary": summary})

    def _handle_thesis_run(self):
        body = self._read_json_body()
        cluster_id = body.get("cluster_id")
        if not cluster_id:
            self._send_json({"error": "cluster_id required"}, 400)
            return

        job_id = str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "job_id": job_id,
                "kind": "thesis",
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
        body = self._read_json_body()
        source = (body.get("source") or "all").lower()
        if source not in ("all", "arxiv", "reddit", "trends", "uspto"):
            self._send_json({"error": f"Unknown source: {source}"}, 400)
            return

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
        def _set(**kw):
            with _JOBS_LOCK:
                _JOBS[job_id].update(kw)

        try:
            from ..collectors.arxiv_collector  import run as run_arxiv
            from ..collectors.reddit_collector import run as run_reddit
            from ..collectors.trends_collector import run as run_trends
            from ..collectors.uspto_collector  import run as run_uspto

            all_sources = {"arxiv": run_arxiv, "reddit": run_reddit,
                           "trends": run_trends, "uspto": run_uspto}
            if source == "all":
                targets = list(all_sources.items())
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

            _set(step="classifying signals")
            from ..classifier.signal_classifier import run_classifier

            classified = 0
            for _ in range(100):
                n = run_classifier(batch_size=100) or 0
                if n == 0:
                    break
                classified += n
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
                 finished=datetime.now(timezone.utc).isoformat())

        except Exception as e:
            logger.error("Refresh job %s failed: %s", job_id, e)
            logger.debug(traceback.format_exc())
            _set(status="error", error=str(e),
                 finished=datetime.now(timezone.utc).isoformat())

    def _handle_source_add(self):
        body = self._read_json_body()
        source_type = (body.get("source_type") or "").lower()
        value = body.get("value", "")
        label = body.get("label", "")
        # SOURCE-TYPE-USPTO-ALLOWED
        if source_type not in ("arxiv", "trends", "reddit", "uspto"):
            self._send_json({"error": "source_type must be arxiv, trends, reddit, or uspto"}, 400)
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
        body = self._read_json_body()
        decision_type = body.get("decision_type")
        stated_reason = body.get("stated_reason", "")
        thesis_id = body.get("thesis_id")
        ticker = body.get("ticker")

        if not decision_type:
            self._send_json({"error": "decision_type required (BUY/HOLD/SELL/PASS/WATCH)"}, 400)
            return

        # Optional price at decision time (L5-A)
        price_at_decision = body.get("price_at_decision")
        if price_at_decision is not None:
            try:
                price_at_decision = float(price_at_decision)
            except (ValueError, TypeError):
                price_at_decision = None

        thesis = export_mod.get_thesis_dict(thesis_id) if thesis_id else {}
        flag, reason = _evaluate_emotional_flag(decision_type, stated_reason, thesis)

        decision_id = db.log_decision(
            decision_type=decision_type,
            stated_reason=stated_reason,
            thesis_id=thesis_id,
            ticker=ticker,
            thesis_snapshot=thesis or None,
            emotional_flag=flag,
            emotional_reason=reason,
            pattern_tag=body.get("pattern_tag", ""),
            price_at_decision=price_at_decision,
        )
        self._send_json({
            "ok": True,
            "decision_id": decision_id,
            "emotional_flag": flag,
            "emotional_reason": reason,
        })

    # -- L5-A: record outcome -----------------------------------------------

    def _handle_outcome_record(self):
        """
        Record outcome data for a decision (price, notes, resolved flag).
        Body:
          {
            "decision_id": "...",
            "price_at_outcome": 142.50,       -- optional
            "outcome_30d": "...",              -- optional free text
            "outcome_90d": "...",              -- optional
            "outcome_365d": "...",             -- optional
            "resolved": true | false           -- lock and trigger post-mortem if true
          }
        """
        body = self._read_json_body()
        decision_id = body.get("decision_id")
        if not decision_id:
            self._send_json({"error": "decision_id required"}, 400)
            return

        price_at_outcome = body.get("price_at_outcome")
        if price_at_outcome is not None:
            try:
                price_at_outcome = float(price_at_outcome)
            except (ValueError, TypeError):
                price_at_outcome = None

        resolved = bool(body.get("resolved", False))

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
            return

        response = {"ok": True, "resolved": resolved}

        # If resolved, kick off the post-mortem job automatically
        if resolved:
            job_id = self._start_postmortem_job(decision_id)
            response["postmortem_job_id"] = job_id

        self._send_json(response)

    # -- L5-B: post-mortem job trigger --------------------------------------

    def _handle_postmortem_trigger(self):
        """
        Manually trigger a post-mortem for a decision (re-run or first run).
        Body: {"decision_id": "..."}
        """
        body = self._read_json_body()
        decision_id = body.get("decision_id")
        if not decision_id:
            self._send_json({"error": "decision_id required"}, 400)
            return

        decision = db.get_decision_by_id(decision_id)
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
        self._send_json({"ok": True, "job_id": job_id})

    def _start_postmortem_job(self, decision_id: str) -> str:
        """Register and start a background post-mortem job. Returns job_id."""
        job_id = str(uuid.uuid4())
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "job_id": job_id,
                "kind": "postmortem",
                "decision_id": decision_id,
                "status": "running",
                "pattern_tag": None,
                "error": None,
                "started": datetime.now(timezone.utc).isoformat(),
                "finished": None,
            }
        t = threading.Thread(
            target=self._run_postmortem_job,
            args=(job_id, decision_id),
            daemon=True,
        )
        t.start()
        return job_id

    def _run_postmortem_job(self, job_id: str, decision_id: str):
        from ..thesis.postmortem_loop import run_postmortem

        def _set(**kw):
            with _JOBS_LOCK:
                _JOBS[job_id].update(kw)

        try:
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
        except Exception as e:
            logger.error("Post-mortem job %s failed: %s", job_id, e)
            logger.debug(traceback.format_exc())
            _set(
                status="error",
                error=str(e),
                finished=datetime.now(timezone.utc).isoformat(),
            )

    # -- L5-D: exit discipline check ----------------------------------------

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

    def _handle_exit_check(self):  # EXIT-CHECK-RESTORED
        """
        Run an exit discipline check for a live thesis.
        Body: {"thesis_id": "...", "proposed_reason": "..."}
        Returns immediately with the AI verdict (synchronous -- typically < 5s).
        """
        body = self._read_json_body()
        thesis_id = body.get("thesis_id")
        if not thesis_id:
            self._send_json({"error": "thesis_id required"}, 400)
            return

        proposed_reason = body.get("proposed_reason", "")

        try:
            from ..thesis.postmortem_loop import run_exit_check
            result = run_exit_check(thesis_id, proposed_reason)
            self._send_json({"ok": True, "result": result})
        except ValueError as e:
            self._send_json({"error": str(e)}, 404)
        except Exception as e:
            logger.error("Exit check failed for thesis %s: %s", thesis_id, e)
            logger.debug(traceback.format_exc())
            self._send_json({"error": str(e)}, 500)


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
