"""
patch_monitoring_pass.py -- creates horizon_scanner/monitoring/monitoring_pass.py
Idempotent: skips if file already contains the sentinel.
Run from project root: python patch_monitoring_pass.py
"""
import ast
import io
import os
import sys

PKG_DIR = os.path.join("horizon_scanner", "monitoring")
INIT_PATH = os.path.join(PKG_DIR, "__init__.py")
TARGET = os.path.join(PKG_DIR, "monitoring_pass.py")
SENTINEL = "# L4-MONITORING-PASS"

MODULE_SRC = '''# L4-MONITORING-PASS
"""
L4 monitoring pass.

Standalone, side-effect-only callable. Compares current signal counts for each
active thesis against a stored baseline and emits monitoring events on spikes
or prolonged quiet. Safe to call after Refresh All or from the Check Monitoring
button. Burns no collector quota.
"""
from datetime import datetime, timedelta

from horizon_scanner import database
from horizon_scanner.config import get_config

# States considered "live" and worth monitoring.
ACTIVE_STATES = ("WATCH", "BUILDING", "CANDIDATE", "ACTIVE")


def _cfg():
    cfg = get_config()
    m = cfg.get("monitoring", {}) if isinstance(cfg, dict) else {}
    return {
        "spike_threshold": int(m.get("spike_threshold", 3)),
        "quiet_days": int(m.get("quiet_days", 30)),
        "auto_rerun_on_spike": bool(m.get("auto_rerun_on_spike", False)),
    }


def _active_theses(conn):
    placeholders = ",".join("?" for _ in ACTIVE_STATES)
    cur = conn.execute(
        "SELECT id, title, cluster_id, last_updated "
        "FROM theses WHERE state IN (%s)" % placeholders,
        ACTIVE_STATES,
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _signal_count(conn, cluster_id):
    if not cluster_id:
        return 0
    cur = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE cluster_id = ?", (cluster_id,))
    return cur.fetchone()[0]


def _latest_signal_at(conn, cluster_id):
    if not cluster_id:
        return None
    cur = conn.execute(
        "SELECT MAX(collected_at) FROM signals WHERE cluster_id = ?",
        (cluster_id,))
    row = cur.fetchone()
    return row[0] if row else None


def run_monitoring_pass(trigger="manual"):
    """
    Run one monitoring pass over all active theses.

    Returns a summary dict:
        {
          "theses_checked": int,
          "events_created": int,
          "spikes": [thesis_id, ...],
          "quiets": [thesis_id, ...],
          "trigger": str,
        }
    """
    cfg = _cfg()
    spike_threshold = cfg["spike_threshold"]
    quiet_days = cfg["quiet_days"]
    auto_rerun = cfg["auto_rerun_on_spike"]

    summary = {
        "theses_checked": 0,
        "events_created": 0,
        "spikes": [],
        "quiets": [],
        "trigger": trigger,
    }

    conn = database.get_connection()
    try:
        theses = _active_theses(conn)
    finally:
        conn.close()

    now = datetime.utcnow()

    for th in theses:
        summary["theses_checked"] += 1
        tid = th["id"]
        cluster_id = th.get("cluster_id")

        # Count current signals (own connection per helper call is fine;
        # these are cheap reads).
        conn = database.get_connection()
        try:
            current = _signal_count(conn, cluster_id)
            latest_at = _latest_signal_at(conn, cluster_id)
        finally:
            conn.close()

        last_count, last_checked = database.get_thesis_baseline(tid)

        # --- Spike detection ---
        if last_count is not None:
            delta = current - last_count
            if delta >= spike_threshold:
                desc = (
                    "Signal spike: +%d new signals since last check "
                    "(%d -> %d)." % (delta, last_count, current))
                database.insert_monitoring_event(
                    thesis_id=tid,
                    event_type="SIGNAL_SPIKE",
                    description=desc,
                    probability_delta=None,
                )
                summary["events_created"] += 1
                summary["spikes"].append(tid)

                if auto_rerun:
                    _try_auto_rerun(tid)

        # --- Quiet detection ---
        if latest_at:
            try:
                latest_dt = datetime.fromisoformat(latest_at)
                if (now - latest_dt) > timedelta(days=quiet_days):
                    desc = (
                        "Signal quiet: no new signals in over %d days "
                        "(last signal %s)." % (quiet_days, latest_at[:10]))
                    database.insert_monitoring_event(
                        thesis_id=tid,
                        event_type="SIGNAL_QUIET",
                        description=desc,
                    )
                    summary["events_created"] += 1
                    summary["quiets"].append(tid)
            except (ValueError, TypeError):
                pass

        # Update baseline for next pass.
        database.set_thesis_baseline(tid, current)

    return summary


def _try_auto_rerun(thesis_id):
    """
    Best-effort hook: trigger a thesis re-run on spike. Imported lazily so a
    missing/renamed rerun entrypoint never breaks the monitoring pass.
    """
    try:
        from horizon_scanner.dashboard.server import start_thesis_rerun
        start_thesis_rerun(thesis_id, trigger="signal_spike")
    except Exception:
        # Never let auto-rerun failure abort monitoring.
        pass
'''


def main():
    if not os.path.isdir("horizon_scanner"):
        print("ABORT: run from project root (horizon_scanner/ not found).")
        sys.exit(1)

    os.makedirs(PKG_DIR, exist_ok=True)

    if not os.path.exists(INIT_PATH):
        with io.open(INIT_PATH, "w", encoding="utf-8", newline="") as f:
            f.write("")
        print("OK: created %s" % INIT_PATH)

    if os.path.exists(TARGET):
        with io.open(TARGET, "r", encoding="utf-8") as f:
            existing = f.read()
        if SENTINEL in existing:
            print("Already applied (sentinel present). No change.")
            return
        print("ABORT: %s exists without sentinel. Inspect manually." % TARGET)
        sys.exit(1)

    try:
        ast.parse(MODULE_SRC)
    except SyntaxError as e:
        print("ABORT: module fails AST parse: %s" % e)
        sys.exit(1)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(MODULE_SRC)
    print("OK: wrote %s" % TARGET)


if __name__ == "__main__":
    main()
