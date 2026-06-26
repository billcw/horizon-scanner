"""
patch_monitoring_relevance_db.py

Adds get_recent_cluster_signals() to database.py -- returns the most recent N
signals on a cluster (id, title, category, theme), newest first. Used by the
L4 monitoring relevance assessment to feed new signals to the Haiku judge.

Idempotent: aborts cleanly if the sentinel is already present or the anchor
is missing/ambiguous.

Run from project root:  python patch_monitoring_relevance_db.py
"""
import ast
import io
import os

TARGET = os.path.join("horizon_scanner", "database.py")
SENTINEL = "# L4-MONITORING-RELEVANCE-DB"

# Anchor: the start of the existing baseline section near the end of the file.
# We insert our new function immediately BEFORE this comment block so it lives
# with the other monitoring helpers.
ANCHOR = "# Baseline table for spike detection (between-pass signal deltas)."

NEW_FUNC = '''# L4-MONITORING-RELEVANCE-DB
def get_recent_cluster_signals(cluster_id, limit=10):
    """
    Return the most recent `limit` signals on a cluster, newest first.
    Each row is a dict with id, title, category, theme, collected_at.
    Used by the L4 relevance assessment to judge new signals against a thesis.
    Returns [] if cluster_id is falsy.
    """
    if not cluster_id:
        return []
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, title, category, theme, collected_at "
            "FROM signals WHERE cluster_id = ? "
            "ORDER BY collected_at DESC LIMIT ?",
            (cluster_id, int(limit)))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


'''


def main():
    if not os.path.isfile(TARGET):
        raise SystemExit("ERROR: %s not found. Run from project root." % TARGET)

    with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
        src = f.read()

    if SENTINEL in src:
        print("Sentinel already present; nothing to do.")
        return

    count = src.count(ANCHOR)
    if count == 0:
        raise SystemExit("ERROR: anchor not found; aborting (no changes made).")
    if count > 1:
        raise SystemExit("ERROR: anchor appears %d times; ambiguous. Aborting." % count)

    new_src = src.replace(ANCHOR, NEW_FUNC + ANCHOR, 1)

    # Validate before writing.
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        raise SystemExit("ERROR: patched file fails AST parse: %s" % e)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)

    print("OK: get_recent_cluster_signals added to %s" % TARGET)


if __name__ == "__main__":
    main()
