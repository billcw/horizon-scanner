"""
probe_force_delta.py

Test helper for the L4 relevance assessment (CONFIRMING/CONTRADICTING).

Forces a monitoring delta on ONE thesis by setting its signal baseline N below
the current signal count. The next "Check Monitoring" pass will then see
(current - last_count) >= N new signals and run the Haiku judgment for that
thesis.

This does NOT call any API itself and burns no collector quota. It only rewrites
one row in the thesis_signal_baseline table. Safe and reversible -- the next
full pass re-records the real baseline afterward.

USAGE (from project root):

    # List active theses and their cluster signal counts, pick one:
    python probe_force_delta.py --list

    # Force a +3 delta on a specific thesis id:
    python probe_force_delta.py --thesis <THESIS_ID>

    # Force a custom delta (e.g. +5):
    python probe_force_delta.py --thesis <THESIS_ID> --delta 5

Then click "Check Monitoring" in the dashboard (or run a monitoring pass) and
look for a CONFIRMING/CONTRADICTING event on that thesis. Note: if Haiku judges
the new signals NEUTRAL, no event is written (correct behavior) -- try another
thesis or a cluster with more clearly directional new signals.
"""
import argparse
import sys

from horizon_scanner import database

ACTIVE_STATES = ("WATCH", "BUILDING", "CANDIDATE", "ACTIVE")


def _cluster_count(conn, cluster_id):
    if not cluster_id:
        return 0
    return conn.execute(
        "SELECT COUNT(*) FROM signals WHERE cluster_id = ?", (cluster_id,)
    ).fetchone()[0]


def list_theses():
    conn = database.get_connection()
    try:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        rows = conn.execute(
            "SELECT id, title, cluster_id, state FROM theses "
            "WHERE state IN (%s) ORDER BY last_updated DESC" % placeholders,
            ACTIVE_STATES,
        ).fetchall()
        if not rows:
            print("No active theses found.")
            return
        print("%-38s  %-7s  %-6s  %s" % ("THESIS ID", "SIGNALS", "STATE", "TITLE"))
        print("-" * 100)
        for r in rows:
            cid = r["cluster_id"]
            n = _cluster_count(conn, cid)
            base_count, _ = database.get_thesis_baseline(r["id"])
            base_str = "-" if base_count is None else str(base_count)
            title = (r["title"] or "")[:46]
            print("%-38s  %-7s  %-6s  %s  (baseline=%s)" % (
                r["id"], n, r["state"], title, base_str))
    finally:
        conn.close()


def force_delta(thesis_id, delta):
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT cluster_id, title FROM theses WHERE id = ?", (thesis_id,)
        ).fetchone()
        if row is None:
            print("ERROR: no thesis with id %s" % thesis_id)
            return 1
        cluster_id = row["cluster_id"]
        title = row["title"] or "(untitled)"
        current = _cluster_count(conn, cluster_id)
    finally:
        conn.close()

    if not cluster_id:
        print("ERROR: thesis '%s' has no cluster_id; nothing to measure." % title)
        return 1
    if current == 0:
        print("ERROR: cluster has 0 signals; can't force a delta. Pick another thesis.")
        return 1

    new_baseline = max(0, current - delta)
    effective_delta = current - new_baseline
    database.set_thesis_baseline(thesis_id, new_baseline)

    print("Thesis : %s" % title)
    print("Cluster current signal count : %d" % current)
    print("Baseline set to              : %d" % new_baseline)
    print("Effective delta on next pass : +%d" % effective_delta)
    if effective_delta < 2:
        print("WARNING: effective delta < 2 (the default assess_min_signals "
              "gate). Cluster may not have enough signals to cross the gate. "
              "Relevance assessment may not fire.")
    else:
        print("OK: next 'Check Monitoring' will run a Haiku judgment for this "
              "thesis.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Force a monitoring delta for testing.")
    ap.add_argument("--list", action="store_true",
                    help="List active theses with signal counts and baselines.")
    ap.add_argument("--thesis", help="Thesis id to force a delta on.")
    ap.add_argument("--delta", type=int, default=3,
                    help="How far below current to set the baseline (default 3).")
    args = ap.parse_args()

    if args.list:
        list_theses()
        return 0
    if args.thesis:
        return force_delta(args.thesis, args.delta)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
