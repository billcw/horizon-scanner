"""
horizon_scanner/database.py

Single source of truth for all database operations.
SQLite -- portable, no server needed, file lives in data/ folder.
"""

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import get_config


class DecisionLockedError(Exception):
    """Raised when an operation is attempted on a resolved (locked) decision."""
    pass

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
-- Raw signals from all collectors
CREATE TABLE IF NOT EXISTS signals (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,          -- arxiv | reddit | google_trends | uspto | news
    title           TEXT,
    content         TEXT,
    url             TEXT,
    author          TEXT,
    published_at    TEXT,
    collected_at    TEXT NOT NULL,
    content_hash    TEXT NOT NULL,          -- for deduplication
    category        TEXT DEFAULT 'UNCLASSIFIED',  -- NOISE|FAD|CULTURAL|EMERGING|STRUCTURAL
    category_confidence REAL DEFAULT 0.0,
    theme           TEXT,                   -- short label from classifier
    time_horizon    TEXT,                   -- short|medium|long|structural
    cluster_id      TEXT,                   -- assigned when clustered
    escalated       INTEGER DEFAULT 0,      -- 1 if sent to L3
    metadata        TEXT DEFAULT '{}'       -- JSON blob for source-specific fields
);

-- Signal clusters (grouped by theme for L3 escalation)
CREATE TABLE IF NOT EXISTS signal_clusters (
    id              TEXT PRIMARY KEY,
    theme           TEXT NOT NULL,
    signal_count    INTEGER DEFAULT 0,
    first_signal_at TEXT NOT NULL,
    last_signal_at  TEXT NOT NULL,
    escalated       INTEGER DEFAULT 0,
    escalated_at    TEXT,
    thesis_id       TEXT                    -- linked thesis if escalated
);

-- Thesis registry (output of L3 loops)
CREATE TABLE IF NOT EXISTS theses (
    id                      TEXT PRIMARY KEY,
    cluster_id              TEXT,
    title                   TEXT NOT NULL,
    theme                   TEXT,
    company_type            TEXT,           -- INFRASTRUCTURE|ENABLER|CYCLICAL|STORY|FRAUD_CANDIDATE
    technology_trl          INTEGER,        -- 1-9
    trl_source              TEXT,
    bottleneck_entity       TEXT,
    bottleneck_ticker       TEXT,
    timeline_years_low      INTEGER,
    timeline_years_high     INTEGER,
    scenarios               TEXT,           -- JSON array
    entities_ring1          TEXT,           -- JSON array
    entities_ring2          TEXT,
    entities_ring3          TEXT,
    entities_ring4          TEXT,
    scoring_card            TEXT,           -- JSON object
    thesis_quality_score    REAL,
    buy_now_score           REAL,
    adversarial_summary     TEXT,
    kill_criteria           TEXT,           -- JSON array
    risk_profile            TEXT,           -- LOW|MEDIUM|HIGH|VERY HIGH
    confidence_rating       TEXT,           -- WATCH|BUILDING|CANDIDATE|INSUFFICIENT
    sources                 TEXT,           -- JSON array
    state                   TEXT DEFAULT 'WATCH',  -- WATCH|BUILDING|CANDIDATE|ACTIVE|RESOLVED|ARCHIVED
    created_at              TEXT NOT NULL,
    last_updated            TEXT NOT NULL,
    resolved_at             TEXT,
    resolution_note         TEXT
);

-- Monitoring log (L4 -- updates to thesis probability/state)
CREATE TABLE IF NOT EXISTS monitoring_events (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,          -- CONFIRMING|CONTRADICTING|NEUTRAL|MILESTONE|STATE_CHANGE
    description     TEXT,
    signal_id       TEXT,
    old_state       TEXT,
    new_state       TEXT,
    probability_delta REAL,
    created_at      TEXT NOT NULL
);

-- Decision log (L5 -- every human decision, good or bad)
CREATE TABLE IF NOT EXISTS decisions (
    id                  TEXT PRIMARY KEY,
    thesis_id           TEXT,
    ticker              TEXT,
    decision_type       TEXT NOT NULL,          -- BUY|ADD|TRIM|EXIT|PASS
    stated_reason       TEXT,
    emotional_flag      INTEGER DEFAULT 0,      -- 1 if system flagged as emotional
    emotional_reason    TEXT,
    thesis_snapshot     TEXT,                   -- JSON snapshot of thesis at decision time
    created_at          TEXT NOT NULL,
    -- L5-A: outcome recording (filled in later by the user)
    price_at_decision   REAL,                   -- price entered when logging the decision
    price_at_outcome    REAL,                   -- price entered when recording the outcome
    outcome_date        TEXT,                   -- ISO date when the outcome was recorded
    outcome_30d         TEXT,                   -- short free-text note: what happened at 30d
    outcome_90d         TEXT,
    outcome_365d        TEXT,
    outcome_resolved    INTEGER DEFAULT 0,      -- 1 once the user marks this resolved
    -- L5-B: post-mortem (filled in by AI after outcome is resolved)
    postmortem_summary  TEXT,                   -- 2-3 sentence AI narrative
    pattern_tag         TEXT                    -- SOLD_WINNER_EARLY|FOMO_ENTRY_CONFIRMED|etc.
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_signals_source       ON signals(source);
CREATE INDEX IF NOT EXISTS idx_signals_category     ON signals(category);
CREATE INDEX IF NOT EXISTS idx_signals_cluster      ON signals(cluster_id);
CREATE INDEX IF NOT EXISTS idx_signals_hash         ON signals(content_hash);
CREATE INDEX IF NOT EXISTS idx_signals_collected    ON signals(collected_at);
CREATE INDEX IF NOT EXISTS idx_theses_state         ON theses(state);
CREATE INDEX IF NOT EXISTS idx_theses_confidence    ON theses(confidence_rating);
CREATE INDEX IF NOT EXISTS idx_monitoring_thesis    ON monitoring_events(thesis_id);
CREATE INDEX IF NOT EXISTS idx_decisions_thesis     ON decisions(thesis_id);

-- Thesis version history (snapshot before each re-run)
-- THESIS-VERSIONING-DB
CREATE TABLE IF NOT EXISTS thesis_versions (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL,
    version_number  INTEGER NOT NULL,
    snapshotted_at  TEXT NOT NULL,
    trigger         TEXT NOT NULL,      -- manual_rerun | scheduled | signal_spike
    snapshot        TEXT NOT NULL       -- full JSON of thesis row at that moment
);

CREATE INDEX IF NOT EXISTS idx_thesis_versions_thesis ON thesis_versions(thesis_id);

-- Thesis version history (snapshot before each re-run)
-- THESIS-VERSIONING-DB
CREATE TABLE IF NOT EXISTS thesis_versions (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL,
    version_number  INTEGER NOT NULL,
    snapshotted_at  TEXT NOT NULL,
    trigger         TEXT NOT NULL,      -- manual_rerun | scheduled | signal_spike
    snapshot        TEXT NOT NULL       -- full JSON of thesis row at that moment
);

CREATE INDEX IF NOT EXISTS idx_thesis_versions_thesis ON thesis_versions(thesis_id);

-- Manageable collector source library (arxiv categories, trends topics, subreddits)
CREATE TABLE IF NOT EXISTS collector_sources (
    id            TEXT PRIMARY KEY,
    source_type   TEXT NOT NULL,          -- arxiv | trends | reddit | uspto | uspto
    value         TEXT NOT NULL,          -- e.g. cs.AI | solid state battery | Futurology
    label         TEXT,                   -- optional human note
    enabled       INTEGER NOT NULL DEFAULT 1,
    added_at      TEXT NOT NULL,
    UNIQUE(source_type, value)
);
"""

# ---------------------------------------------------------------------------
# L5 column migration
# Run once on startup: adds the new L5-A/B columns to the decisions table
# if they were created before this version of database.py.
# ---------------------------------------------------------------------------

_L5_MIGRATIONS = [
    "ALTER TABLE decisions ADD COLUMN price_at_decision  REAL",
    "ALTER TABLE decisions ADD COLUMN price_at_outcome   REAL",
    "ALTER TABLE decisions ADD COLUMN outcome_date       TEXT",
    "ALTER TABLE decisions ADD COLUMN outcome_resolved   INTEGER DEFAULT 0",
    "ALTER TABLE decisions ADD COLUMN postmortem_summary TEXT",
]

# Index on the new column -- created here (after migration) not in SCHEMA,
# because the column doesn't exist on old databases when SCHEMA runs.
_L5_POST_MIGRATION_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_decisions_resolved ON decisions(outcome_resolved)",
]


def _run_migrations(conn: sqlite3.Connection):
    """
    Apply any missing L5 columns.  SQLite ALTER TABLE ADD COLUMN is
    idempotent-safe: we catch 'duplicate column name' errors and skip them.
    Then create any indexes that depend on the new columns.
    """
    for stmt in _L5_MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    # Create indexes that reference L5 columns (must run after columns exist)
    for stmt in _L5_POST_MIGRATION_SQL:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # already exists


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Thesis versioning
# ---------------------------------------------------------------------------

def snapshot_thesis_version(thesis_id: str, trigger: str = "manual_rerun") -> int:
    """
    Snapshot the current thesis row into thesis_versions before a re-run.
    Returns the new version_number, or 0 if thesis not found.
    Trigger values: manual_rerun | scheduled | signal_spike
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM theses WHERE id=?", (thesis_id,)
        ).fetchone()
        if row is None:
            return 0
        count = conn.execute(
            "SELECT COUNT(*) FROM thesis_versions WHERE thesis_id=?",
            (thesis_id,)
        ).fetchone()[0]
        version_number = count + 1
        version_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        snapshot = json.dumps(dict(row))
        conn.execute(
            """INSERT INTO thesis_versions
               (id, thesis_id, version_number, snapshotted_at, trigger, snapshot)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (version_id, thesis_id, version_number, now, trigger, snapshot)
        )
        return version_number


def get_thesis_versions(thesis_id: str) -> list:
    """
    Return all prior versions of a thesis, oldest first.
    Each entry is a dict with version_number, snapshotted_at, trigger,
    and the full snapshot parsed back to a dict.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM thesis_versions
               WHERE thesis_id=?
               ORDER BY version_number ASC""",
            (thesis_id,)
        ).fetchall()
        result = []
        for r in rows:
            entry = dict(r)
            entry["snapshot"] = json.loads(entry["snapshot"])
            result.append(entry)
        return result


# ---------------------------------------------------------------------------
# Thesis versioning
# ---------------------------------------------------------------------------

def snapshot_thesis_version(thesis_id: str, trigger: str = "manual_rerun") -> int:
    """
    Snapshot the current thesis row into thesis_versions before a re-run.
    Returns the new version_number, or 0 if thesis not found.
    Trigger values: manual_rerun | scheduled | signal_spike
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM theses WHERE id=?", (thesis_id,)
        ).fetchone()
        if row is None:
            return 0
        count = conn.execute(
            "SELECT COUNT(*) FROM thesis_versions WHERE thesis_id=?",
            (thesis_id,)
        ).fetchone()[0]
        version_number = count + 1
        version_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        snapshot = json.dumps(dict(row))
        conn.execute(
            """INSERT INTO thesis_versions
               (id, thesis_id, version_number, snapshotted_at, trigger, snapshot)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (version_id, thesis_id, version_number, now, trigger, snapshot)
        )
        return version_number


def get_thesis_versions(thesis_id: str) -> list:
    """
    Return all prior versions of a thesis, oldest first.
    Each entry is a dict with version_number, snapshotted_at, trigger,
    and the full snapshot parsed back to a dict.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM thesis_versions
               WHERE thesis_id=?
               ORDER BY version_number ASC""",
            (thesis_id,)
        ).fetchall()
        result = []
        for r in rows:
            entry = dict(r)
            entry["snapshot"] = json.loads(entry["snapshot"])
            result.append(entry)
        return result


def get_connection() -> sqlite3.Connection:
    """Return a connection to the database, creating it if needed."""
    cfg = get_config()
    db_path = Path(cfg["database"]["path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row          # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL") # better concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_database():
    """Create all tables and indexes. Safe to call repeatedly."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
    print("Database initialized.")


# ---------------------------------------------------------------------------
# Signal operations
# ---------------------------------------------------------------------------

def insert_signal(
    source: str,
    content_hash: str,
    title: str = "",
    content: str = "",
    url: str = "",
    author: str = "",
    published_at: str = "",
    metadata: dict = None,
) -> Optional[str]:
    """
    Insert a raw signal. Returns the new signal ID, or None if duplicate.
    """
    with get_connection() as conn:
        # Deduplication check
        existing = conn.execute(
            "SELECT id FROM signals WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            return None  # already have this one

        signal_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO signals
               (id, source, title, content, url, author, published_at,
                collected_at, content_hash, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id, source, title, content, url, author,
                published_at, now, content_hash,
                json.dumps(metadata or {}),
            ),
        )
        return signal_id


def update_signal_classification(
    signal_id: str,
    category: str,
    confidence: float,
    theme: str,
    time_horizon: str,
):
    with get_connection() as conn:
        conn.execute(
            """UPDATE signals
               SET category=?, category_confidence=?, theme=?, time_horizon=?
               WHERE id=?""",
            (category, confidence, theme, time_horizon, signal_id),
        )


def get_unclassified_signals(limit: int = 100) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM signals
               WHERE category = 'UNCLASSIFIED'
               ORDER BY collected_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_signals_by_category(category: str, limit: int = 500) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE category=? ORDER BY collected_at DESC LIMIT ?",
            (category, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Cluster operations
# ---------------------------------------------------------------------------

def upsert_cluster(theme: str, signal_id: str) -> str:
    """Add a signal to an existing cluster or create a new one. Returns cluster_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, signal_count FROM signal_clusters WHERE theme=? AND escalated=0",
            (theme,),
        ).fetchone()

        if existing:
            cluster_id = existing["id"]
            conn.execute(
                """UPDATE signal_clusters
                   SET signal_count=signal_count+1, last_signal_at=?
                   WHERE id=?""",
                (now, cluster_id),
            )
        else:
            cluster_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO signal_clusters
                   (id, theme, signal_count, first_signal_at, last_signal_at)
                   VALUES (?, ?, 1, ?, ?)""",
                (cluster_id, theme, now, now),
            )

        conn.execute(
            "UPDATE signals SET cluster_id=? WHERE id=?",
            (cluster_id, signal_id),
        )
        return cluster_id


def get_clusters_ready_for_escalation(threshold: int = 3) -> list:
    """Return clusters with signal_count >= threshold that haven't been escalated."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM signal_clusters
               WHERE signal_count >= ? AND escalated = 0
               ORDER BY signal_count DESC""",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_cluster_escalated(cluster_id: str, thesis_id: str):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE signal_clusters
               SET escalated=1, escalated_at=?, thesis_id=?
               WHERE id=?""",
            (now, thesis_id, cluster_id),
        )
        conn.execute(
            "UPDATE signals SET escalated=1 WHERE cluster_id=?",
            (cluster_id,),
        )


# ---------------------------------------------------------------------------
# Thesis operations
# ---------------------------------------------------------------------------

def insert_thesis(thesis: dict) -> str:
    """Insert a new thesis. thesis dict should match the schema fields."""
    thesis_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO theses (
                id, cluster_id, title, theme, company_type, technology_trl,
                trl_source, bottleneck_entity, bottleneck_ticker,
                timeline_years_low, timeline_years_high, scenarios,
                entities_ring1, entities_ring2, entities_ring3, entities_ring4,
                scoring_card, thesis_quality_score, buy_now_score,
                adversarial_summary, kill_criteria, risk_profile,
                confidence_rating, sources, state, created_at, last_updated
            ) VALUES (
                :id, :cluster_id, :title, :theme, :company_type, :technology_trl,
                :trl_source, :bottleneck_entity, :bottleneck_ticker,
                :timeline_years_low, :timeline_years_high, :scenarios,
                :entities_ring1, :entities_ring2, :entities_ring3, :entities_ring4,
                :scoring_card, :thesis_quality_score, :buy_now_score,
                :adversarial_summary, :kill_criteria, :risk_profile,
                :confidence_rating, :sources, :state, :created_at, :last_updated
            )""",
            {
                "id": thesis_id,
                "created_at": now,
                "last_updated": now,
                "state": "WATCH",
                **{k: json.dumps(v) if isinstance(v, (dict, list)) else v
                   for k, v in thesis.items()},
            },
        )
    return thesis_id


def get_active_theses() -> list:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM theses
               WHERE state NOT IN ('RESOLVED', 'ARCHIVED')
               ORDER BY last_updated DESC""",
        ).fetchall()
        return [dict(r) for r in rows]



def update_thesis_rings(
    thesis_id: str,
    ring1: list = None,
    ring2: list = None,
    ring3: list = None,
    ring4: list = None,
) -> bool:
    """
    Persist updated entities_ring1-4 JSON back to a thesis row.
    Called by the deepen-counterparties background job after
    deepen_counterparties() mutates company objects in place.

    Only writes rings that are passed as non-None (None means unchanged).
    Returns True if a row was updated.
    """
    now = datetime.now(timezone.utc).isoformat()
    updates = []
    params = []
    if ring1 is not None:
        updates.append("entities_ring1 = ?")
        params.append(json.dumps(ring1))
    if ring2 is not None:
        updates.append("entities_ring2 = ?")
        params.append(json.dumps(ring2))
    if ring3 is not None:
        updates.append("entities_ring3 = ?")
        params.append(json.dumps(ring3))
    if ring4 is not None:
        updates.append("entities_ring4 = ?")
        params.append(json.dumps(ring4))
    if not updates:
        return False
    updates.append("last_updated = ?")
    params.append(now)
    params.append(thesis_id)
    sql = "UPDATE theses SET " + ", ".join(updates) + " WHERE id = ?"
    with get_connection() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount > 0


def update_thesis_state(thesis_id: str, new_state: str, note: str = ""):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE theses
               SET state=?, last_updated=?, resolution_note=?
               WHERE id=?""",
            (new_state, now, note, thesis_id),
        )


# ---------------------------------------------------------------------------
# Decision log operations
# ---------------------------------------------------------------------------

def log_decision(
    decision_type: str,
    stated_reason: str,
    thesis_id: str = None,
    ticker: str = None,
    thesis_snapshot: dict = None,
    emotional_flag: bool = False,
    emotional_reason: str = "",
    pattern_tag: str = "",
    price_at_decision: float = None,
) -> str:
    decision_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO decisions
               (id, thesis_id, ticker, decision_type, stated_reason,
                emotional_flag, emotional_reason, thesis_snapshot,
                created_at, pattern_tag, price_at_decision)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id, thesis_id, ticker, decision_type, stated_reason,
                int(emotional_flag), emotional_reason,
                json.dumps(thesis_snapshot or {}), now, pattern_tag,
                price_at_decision,
            ),
        )
    return decision_id


def delete_decision(decision_id: str) -> bool:
    """
    Hard-delete a single decision by id. Returns True if a row was removed.
    Refuses (raises DecisionLockedError) if the decision is resolved -- a
    resolved decision is a permanent ledger entry and cannot be deleted.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT outcome_resolved FROM decisions WHERE id=?", (decision_id,)
        ).fetchone()
        if row is None:
            return False
        if row["outcome_resolved"]:
            raise DecisionLockedError(
                "This decision is resolved and cannot be deleted."
            )
        cur = conn.execute(
            "DELETE FROM decisions WHERE id=?", (decision_id,)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# L5-A: Outcome recording
# ---------------------------------------------------------------------------

def record_outcome(
    decision_id: str,
    price_at_outcome: float = None,
    outcome_30d: str = "",
    outcome_90d: str = "",
    outcome_365d: str = "",
    outcome_date: str = None,
    resolved: bool = False,
) -> bool:
    """
    Update a decision with outcome data.  Call with resolved=True when the
    user wants to lock the record and trigger a post-mortem job.
    Returns True if a row was updated.

    Refuses (raises DecisionLockedError) if the decision is ALREADY resolved.
    Once resolved, a decision is a permanent, immutable ledger entry.
    """
    now = outcome_date or datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT outcome_resolved FROM decisions WHERE id=?", (decision_id,)
        ).fetchone()
        if existing is None:
            return False
        if existing["outcome_resolved"]:
            raise DecisionLockedError(
                "This decision is resolved and locked. No further edits allowed."
            )
        cur = conn.execute(
            """UPDATE decisions
               SET price_at_outcome = ?,
                   outcome_30d      = ?,
                   outcome_90d      = ?,
                   outcome_365d     = ?,
                   outcome_date     = ?,
                   outcome_resolved = ?
               WHERE id = ?""",
            (
                price_at_outcome,
                outcome_30d or "",
                outcome_90d or "",
                outcome_365d or "",
                now,
                int(bool(resolved)),
                decision_id,
            ),
        )
        return cur.rowcount > 0


def get_decision_by_id(decision_id: str) -> Optional[dict]:
    """Return a single decision row as a dict, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM decisions WHERE id=?", (decision_id,)
        ).fetchone()
        return dict(row) if row else None


def get_decisions_with_outcomes() -> list:
    """
    All decisions that have at least one outcome field filled in,
    newest first.  Used by the Outcomes tab.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM decisions
               WHERE outcome_30d IS NOT NULL
                  OR outcome_90d IS NOT NULL
                  OR outcome_365d IS NOT NULL
                  OR price_at_outcome IS NOT NULL
               ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_decisions() -> list:
    """All decisions, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# L5-B: Post-mortem storage
# ---------------------------------------------------------------------------

def save_postmortem(
    decision_id: str,
    postmortem_summary: str,
    pattern_tag: str,
) -> bool:
    """
    Write the AI post-mortem back to the decision row.
    Returns True if a row was updated.

    Allowed ONLY the one time: when the decision is resolved but no
    post-mortem summary has been written yet.  This is the single write that
    completes a resolved record.  Once postmortem_summary is populated, the
    row is fully locked and this raises DecisionLockedError.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT outcome_resolved, postmortem_summary
               FROM decisions WHERE id=?""",
            (decision_id,)
        ).fetchone()
        if row is None:
            return False
        # The post-mortem may only be written on a resolved row that does not
        # yet have a summary.  Re-running a completed post-mortem is blocked.
        existing_summary = (row["postmortem_summary"] or "").strip()
        if existing_summary:
            raise DecisionLockedError(
                "This decision already has a post-mortem and is locked."
            )
        cur = conn.execute(
            """UPDATE decisions
               SET postmortem_summary = ?,
                   pattern_tag        = ?
               WHERE id = ?""",
            (postmortem_summary, pattern_tag, decision_id),
        )
        return cur.rowcount > 0


def get_pattern_summary() -> list:
    """
    Aggregate pattern_tag counts across all decisions that have one.
    Returns list of {pattern_tag, count} dicts, most common first.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT pattern_tag, COUNT(*) as count
               FROM decisions
               WHERE pattern_tag IS NOT NULL AND pattern_tag != ''
               GROUP BY pattern_tag
               ORDER BY count DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Stats (for dashboard)
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    with get_connection() as conn:
        total_signals    = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        classified       = conn.execute("SELECT COUNT(*) FROM signals WHERE category != 'UNCLASSIFIED'").fetchone()[0]
        total_clusters   = conn.execute("SELECT COUNT(*) FROM signal_clusters").fetchone()[0]
        pending_clusters = conn.execute("SELECT COUNT(*) FROM signal_clusters WHERE escalated=0").fetchone()[0]
        total_theses     = conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0]
        watch            = conn.execute("SELECT COUNT(*) FROM theses WHERE state='WATCH'").fetchone()[0]
        building         = conn.execute("SELECT COUNT(*) FROM theses WHERE state='BUILDING'").fetchone()[0]
        candidate        = conn.execute("SELECT COUNT(*) FROM theses WHERE state='CANDIDATE'").fetchone()[0]
        total_decisions  = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        emotional_sells  = conn.execute("SELECT COUNT(*) FROM decisions WHERE emotional_flag=1").fetchone()[0]
        resolved         = conn.execute("SELECT COUNT(*) FROM decisions WHERE outcome_resolved=1").fetchone()[0]
        postmortems      = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE postmortem_summary IS NOT NULL AND postmortem_summary != ''"
        ).fetchone()[0]

    return {
        "signals":   {"total": total_signals, "classified": classified},
        "clusters":  {"total": total_clusters, "pending": pending_clusters},
        "theses":    {"total": total_theses, "watch": watch, "building": building, "candidate": candidate},
        "decisions": {
            "total": total_decisions,
            "emotional_flags": emotional_sells,
            "resolved": resolved,
            "postmortems": postmortems,
        },
    }


# ---------------------------------------------------------------------------
# Collector source library (manageable from the dashboard)
# ---------------------------------------------------------------------------

def list_sources(source_type: str = None) -> list:
    """All source-library rows, optionally filtered by type. Newest first."""
    with get_connection() as conn:
        if source_type:
            rows = conn.execute(
                """SELECT * FROM collector_sources WHERE source_type=?
                   ORDER BY value ASC""", (source_type,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM collector_sources ORDER BY source_type, value ASC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_enabled_source_values(source_type: str) -> list:
    """Return just the enabled values for a source type (what a collector iterates)."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT value FROM collector_sources
               WHERE source_type=? AND enabled=1 ORDER BY value ASC""",
            (source_type,)
        ).fetchall()
        return [r["value"] for r in rows]


def add_source(source_type: str, value: str, label: str = "", enabled: bool = True) -> str:
    """
    Add a source to the library. Idempotent on (source_type, value): if it
    already exists, returns the existing id without duplicating.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("Source value cannot be empty")
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM collector_sources WHERE source_type=? AND value=?",
            (source_type, value)
        ).fetchone()
        if existing:
            return existing["id"]
        sid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO collector_sources
               (id, source_type, value, label, enabled, added_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sid, source_type, value, label or "", int(bool(enabled)),
             datetime.now(timezone.utc).isoformat())
        )
        return sid


def set_source_enabled(source_id: str, enabled: bool) -> bool:
    """Enable/disable a single source. Returns True if a row changed."""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE collector_sources SET enabled=? WHERE id=?",
            (int(bool(enabled)), source_id)
        )
        return cur.rowcount > 0


def delete_source(source_id: str) -> bool:
    """Hard-delete a source from the library. Returns True if a row was removed."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM collector_sources WHERE id=?", (source_id,)
        )
        return cur.rowcount > 0
