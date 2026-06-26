"""
patch_monitoring_db.py -- L4 monitoring DB layer.
Idempotent. Sentinel-anchored. Adds read_flag column + monitoring functions.
Run from project root: python patch_monitoring_db.py
"""
import ast
import io
import os
import sys

TARGET = os.path.join("horizon_scanner", "database.py")
SENTINEL = "# L4-MONITORING-DB"

NEW_CODE = '''

# L4-MONITORING-DB
def _monitoring_ensure_read_flag(conn):
    """Idempotently add read_flag column to monitoring_events."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(monitoring_events)")
    cols = [r[1] for r in cur.fetchall()]
    if "read_flag" not in cols:
        cur.execute("ALTER TABLE monitoring_events ADD COLUMN read_flag INTEGER DEFAULT 0")
        conn.commit()


def insert_monitoring_event(thesis_id, event_type, description,
                            signal_id=None, old_state=None, new_state=None,
                            probability_delta=None):
    """Insert a monitoring event. Returns the new event id."""
    import uuid as _uuid
    from datetime import datetime as _dt
    conn = get_connection()
    try:
        _monitoring_ensure_read_flag(conn)
        eid = str(_uuid.uuid4())
        now = _dt.utcnow().isoformat()
        conn.execute(
            "INSERT INTO monitoring_events "
            "(id, thesis_id, event_type, description, signal_id, "
            "old_state, new_state, probability_delta, created_at, read_flag) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (eid, thesis_id, event_type, description, signal_id,
             old_state, new_state, probability_delta, now),
        )
        conn.commit()
        return eid
    finally:
        conn.close()


def get_monitoring_events(limit=100, unread_only=False):
    """Return monitoring events newest-first, joined with thesis title."""
    conn = get_connection()
    try:
        _monitoring_ensure_read_flag(conn)
        q = (
            "SELECT m.id, m.thesis_id, t.title, m.event_type, m.description, "
            "m.signal_id, m.old_state, m.new_state, m.probability_delta, "
            "m.created_at, m.read_flag "
            "FROM monitoring_events m "
            "LEFT JOIN theses t ON t.id = m.thesis_id "
        )
        if unread_only:
            q += "WHERE m.read_flag = 0 "
        q += "ORDER BY m.created_at DESC LIMIT ?"
        cur = conn.execute(q, (limit,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_unread_monitoring_count():
    conn = get_connection()
    try:
        _monitoring_ensure_read_flag(conn)
        cur = conn.execute(
            "SELECT COUNT(*) FROM monitoring_events WHERE read_flag = 0")
        return cur.fetchone()[0]
    finally:
        conn.close()


def mark_monitoring_event_read(event_id):
    conn = get_connection()
    try:
        _monitoring_ensure_read_flag(conn)
        conn.execute(
            "UPDATE monitoring_events SET read_flag = 1 WHERE id = ?",
            (event_id,))
        conn.commit()
    finally:
        conn.close()


def mark_all_monitoring_read():
    conn = get_connection()
    try:
        _monitoring_ensure_read_flag(conn)
        conn.execute("UPDATE monitoring_events SET read_flag = 1 WHERE read_flag = 0")
        conn.commit()
    finally:
        conn.close()


# Baseline table for spike detection (between-pass signal deltas).
def _monitoring_ensure_baseline_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS thesis_signal_baseline ("
        "thesis_id TEXT PRIMARY KEY, "
        "last_count INTEGER DEFAULT 0, "
        "last_checked TEXT)")
    conn.commit()


def get_thesis_baseline(thesis_id):
    """Return (last_count, last_checked) or (None, None) if absent."""
    conn = get_connection()
    try:
        _monitoring_ensure_baseline_table(conn)
        cur = conn.execute(
            "SELECT last_count, last_checked FROM thesis_signal_baseline "
            "WHERE thesis_id = ?", (thesis_id,))
        row = cur.fetchone()
        if row is None:
            return (None, None)
        return (row[0], row[1])
    finally:
        conn.close()


def set_thesis_baseline(thesis_id, count):
    from datetime import datetime as _dt
    conn = get_connection()
    try:
        _monitoring_ensure_baseline_table(conn)
        now = _dt.utcnow().isoformat()
        conn.execute(
            "INSERT INTO thesis_signal_baseline (thesis_id, last_count, last_checked) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(thesis_id) DO UPDATE SET last_count = ?, last_checked = ?",
            (thesis_id, count, now, count, now))
        conn.commit()
    finally:
        conn.close()
'''


def main():
    if not os.path.exists(TARGET):
        print("ABORT: %s not found. Run from project root." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Already applied (sentinel present). No change.")
        return

    new_src = src.rstrip() + "\n" + NEW_CODE

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print("ABORT: resulting file fails AST parse: %s" % e)
        sys.exit(1)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)
    print("OK: appended L4 monitoring DB functions to %s" % TARGET)


if __name__ == "__main__":
    main()
