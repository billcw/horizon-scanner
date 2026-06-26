"""
cleanup_duplicate_theses.py -- one-time dedup of active theses per cluster.

Keep-rule: for each cluster with >1 active thesis
(state in WATCH/BUILDING/CANDIDATE/ACTIVE), keep the one with the most recent
last_updated; archive the rest (state='ARCHIVED'). Also deletes orphaned
thesis_signal_baseline rows for archived theses so monitoring stops tracking them.

Version history in thesis_versions is preserved regardless.

DRY-RUN by default. To apply:  python cleanup_duplicate_theses.py --commit
Run from project root.
"""
import sqlite3
import sys

DB = "data/horizon_scanner.db"
ACTIVE = ("WATCH", "BUILDING", "CANDIDATE", "ACTIVE")


def main():
    commit = "--commit" in sys.argv

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    placeholders = ",".join("?" for _ in ACTIVE)
    cur.execute(
        "SELECT cluster_id, COUNT(*) n FROM theses "
        "WHERE state IN (%s) AND cluster_id IS NOT NULL "
        "GROUP BY cluster_id HAVING n > 1" % placeholders,
        ACTIVE,
    )
    dup_clusters = [r["cluster_id"] for r in cur.fetchall()]

    if not dup_clusters:
        print("No duplicated active clusters found. Nothing to do.")
        conn.close()
        return

    to_archive = []   # list of (thesis_id, cluster_id)
    keep = []         # list of (thesis_id, cluster_id)

    for cid in dup_clusters:
        rows = cur.execute(
            "SELECT id, last_updated, created_at FROM theses "
            "WHERE cluster_id=? AND state IN (%s) "
            "ORDER BY last_updated DESC, created_at DESC" % placeholders,
            (cid,) + ACTIVE,
        ).fetchall()
        # First row is the keeper (most recently updated).
        keeper = rows[0]
        keep.append((keeper["id"], cid))
        for r in rows[1:]:
            to_archive.append((r["id"], cid))

    print("=" * 70)
    print("DUPLICATE THESIS CLEANUP  (%s)" % ("COMMIT" if commit else "DRY-RUN"))
    print("=" * 70)
    for kid, cid in keep:
        n_arch = sum(1 for _, c in to_archive if c == cid)
        print("\ncluster %s" % cid)
        print("  KEEP    %s" % kid)
        for aid, c in to_archive:
            if c == cid:
                print("  ARCHIVE %s" % aid)

    print("\nSummary: keep %d, archive %d, across %d cluster(s)."
          % (len(keep), len(to_archive), len(dup_clusters)))

    if not commit:
        print("\nDRY-RUN only. Re-run with --commit to apply.")
        conn.close()
        return

    # Apply: archive + drop orphaned baselines.
    archived_ids = [aid for aid, _ in to_archive]
    cur.execute("SELECT MAX(rowid) FROM theses")  # touch to ensure write conn
    for aid in archived_ids:
        cur.execute(
            "UPDATE theses SET state='ARCHIVED' WHERE id=?", (aid,))
        cur.execute(
            "DELETE FROM thesis_signal_baseline WHERE thesis_id=?", (aid,))
    conn.commit()

    # Verify.
    cur.execute(
        "SELECT cluster_id, COUNT(*) n FROM theses "
        "WHERE state IN (%s) AND cluster_id IS NOT NULL "
        "GROUP BY cluster_id HAVING n > 1" % placeholders,
        ACTIVE,
    )
    remaining = cur.fetchall()
    print("\nApplied. Archived %d theses." % len(archived_ids))
    if remaining:
        print("WARNING: still duplicated:")
        for r in remaining:
            print("  %s  count=%d" % (r["cluster_id"], r["n"]))
    else:
        print("Verified: no duplicated active clusters remain.")

    conn.close()


if __name__ == "__main__":
    main()
