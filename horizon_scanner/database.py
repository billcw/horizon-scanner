"""
horizon_scanner/database.py

Single source of truth for all database operations.
SQLite — portable, no server needed, file lives in data/ folder.
"""

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import get_config

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

-- Monitoring log (L4 — updates to thesis probability/state)
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

-- Decision log (L5 — every human decision, good or bad)
CREATE TABLE IF NOT EXISTS decisions (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT,
    ticker          TEXT,
    decision_type   TEXT NOT NULL,          -- BUY|ADD|TRIM|EXIT|PASS
    stated_reason   TEXT,
    emotional_flag  INTEGER DEFAULT 0,      -- 1 if system flagged as emotional
    emotional_reason TEXT,
    thesis_snapshot TEXT,                   -- JSON snapshot of thesis at decision time
    created_at      TEXT NOT NULL,
    outcome_30d     TEXT,                   -- filled in later
    outcome_90d     TEXT,
    outcome_365d    TEXT,
    pattern_tag     TEXT                    -- Early Seller | FOMO Buyer | etc.
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
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

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
) -> str:
    decision_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO decisions
               (id, thesis_id, ticker, decision_type, stated_reason,
                emotional_flag, emotional_reason, thesis_snapshot,
                created_at, pattern_tag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id, thesis_id, ticker, decision_type, stated_reason,
                int(emotional_flag), emotional_reason,
                json.dumps(thesis_snapshot or {}), now, pattern_tag,
            ),
        )
    return decision_id


def delete_decision(decision_id: str) -> bool:
    """
    Hard-delete a single decision by id. Returns True if a row was removed.
    """
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM decisions WHERE id=?", (decision_id,)
        )
        return cur.rowcount > 0



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

    return {
        "signals":         {"total": total_signals, "classified": classified},
        "clusters":        {"total": total_clusters, "pending": pending_clusters},
        "theses":          {"total": total_theses, "watch": watch, "building": building, "candidate": candidate},
        "decisions":       {"total": total_decisions, "emotional_flags": emotional_sells},
    }
