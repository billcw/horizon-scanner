"""
dashboard/export.py

Phase 3A + L5 -- data export layer for the dashboard.

Reads the existing SQLite database via the database module and shapes rows
into JSON-friendly payloads for the dashboard API. All JSON-encoded columns
(scenarios, entity rings, scoring card, kill criteria) are parsed back into
real objects here so the front end receives structured data, not strings.

This module is read-only against the DB except where it delegates to
database.log_decision via the server.
"""

import json
import logging

from .. import database as db
from ..config import get_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safe JSON parsing for TEXT columns that hold JSON
# ---------------------------------------------------------------------------

def _loads(value, default):
    """Parse a JSON string column; return default on any failure."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

def clusters_payload() -> dict:
    """
    All clusters with signal counts and escalation status, plus the current
    escalation threshold so the UI can show which clusters are 'ready'.
    """
    cfg = get_config()
    threshold = cfg.get("classifier", {}).get("cluster_escalation_threshold", 3)

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, theme, signal_count, first_signal_at, last_signal_at,
                      escalated, escalated_at, thesis_id
               FROM signal_clusters
               ORDER BY signal_count DESC, last_signal_at DESC"""
        ).fetchall()

    clusters = []
    for r in rows:
        d = dict(r)
        d["escalated"] = bool(d.get("escalated"))
        d["ready"] = (d.get("signal_count", 0) >= threshold) and not d["escalated"]
        clusters.append(d)

    return {"threshold": threshold, "clusters": clusters}


# ---------------------------------------------------------------------------
# Theses
# ---------------------------------------------------------------------------

def _shape_thesis(row: dict) -> dict:
    """Parse all JSON columns of a thesis row into structured objects."""
    d = dict(row)
    d["scenarios"]      = _loads(d.get("scenarios"), [])
    d["entities_ring1"] = _loads(d.get("entities_ring1"), [])
    d["entities_ring2"] = _loads(d.get("entities_ring2"), [])
    d["entities_ring3"] = _loads(d.get("entities_ring3"), [])
    d["entities_ring4"] = _loads(d.get("entities_ring4"), [])
    d["scoring_card"]   = _loads(d.get("scoring_card"), {})
    d["kill_criteria"]  = _loads(d.get("kill_criteria"), [])
    d["sources"]        = _loads(d.get("sources"), [])
    return d


def theses_payload() -> dict:
    """All theses (newest first), fully parsed."""
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM theses ORDER BY created_at DESC"
        ).fetchall()
    return {"theses": [_shape_thesis(r) for r in rows]}


def get_thesis_dict(thesis_id: str) -> dict:
    """Single thesis by id, fully parsed. Returns {} if not found."""
    if not thesis_id:
        return {}
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM theses WHERE id=?", (thesis_id,)
        ).fetchone()
    return _shape_thesis(row) if row else {}


# ---------------------------------------------------------------------------
# Decisions (general log)
# ---------------------------------------------------------------------------

def _shape_decision(row: dict) -> dict:
    """Parse and normalise a single decisions row."""
    d = dict(row)
    d["emotional_flag"]   = bool(d.get("emotional_flag"))
    d["outcome_resolved"] = bool(d.get("outcome_resolved"))
    d["thesis_snapshot"]  = _loads(d.get("thesis_snapshot"), {})
    # Numeric fields: coerce None to null-safe float/None
    for col in ("price_at_decision", "price_at_outcome"):
        val = d.get(col)
        d[col] = float(val) if val is not None else None
    return d


def decisions_payload() -> dict:
    """Decision history (newest first), with thesis_snapshot parsed."""
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC"
        ).fetchall()
    return {"decisions": [_shape_decision(dict(r)) for r in rows]}


# ---------------------------------------------------------------------------
# L5 Outcomes + patterns
# ---------------------------------------------------------------------------

def outcomes_payload() -> dict:
    """
    All decisions that have outcome data or a post-mortem, plus the
    pattern-tag aggregate for the Patterns section.
    Returns:
      {
        "decisions": [...],          -- all decisions (for Outcomes tab full list)
        "with_outcomes": [...],      -- only those with outcome data filled in
        "pattern_summary": [...],    -- [{pattern_tag, count}, ...]
      }
    """
    all_decisions = [_shape_decision(d) for d in db.get_all_decisions()]
    with_outcomes = [_shape_decision(d) for d in db.get_decisions_with_outcomes()]
    pattern_summary = db.get_pattern_summary()

    return {
        "decisions": all_decisions,
        "with_outcomes": with_outcomes,
        "pattern_summary": pattern_summary,
    }


# ---------------------------------------------------------------------------
# Config (for the Settings panel)
# ---------------------------------------------------------------------------

# Only these sections/keys are exposed to and editable from the UI.
# Everything else in config.yaml stays server-side only.
_EDITABLE = {
    "thesis": [
        "step_model", "adversarial_model", "step_max_tokens", "step_models",
        "max_signals_in_context", "signal_abstract_chars", "context_doc_max_chars",
        "web_search_max_tokens", "perplexity_model", "step_timeout_seconds",
    ],
    "classifier": [
        "model", "fallback_model", "confidence_threshold",
        "dedup_similarity_threshold", "cluster_escalation_threshold",
    ],
    "collectors": ["arxiv", "reddit", "google_trends"],
    "logging": ["level"],
}

# Known model strings offered as datalist suggestions (free-text still allowed).
_MODEL_SUGGESTIONS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]


def config_payload() -> dict:
    """
    Return only the editable slice of config, plus model suggestions for the
    datalist dropdowns.
    """
    cfg = get_config()
    editable = {}

    for section, keys in _EDITABLE.items():
        src = cfg.get(section, {})
        if section == "collectors":
            editable["collectors"] = {
                "arxiv": {
                    "max_results_per_run": src.get("arxiv", {}).get("max_results_per_run"),
                    "enabled": src.get("arxiv", {}).get("enabled"),
                },
                "reddit": {
                    "post_limit": src.get("reddit", {}).get("post_limit"),
                    "min_score": src.get("reddit", {}).get("min_score"),
                    "enabled": src.get("reddit", {}).get("enabled"),
                },
                "google_trends": {
                    "geo": src.get("google_trends", {}).get("geo"),
                    "enabled": src.get("google_trends", {}).get("enabled"),
                },
                "uspto": {
                    "enabled": src.get("uspto", {}).get("enabled"),
                    "mode": src.get("uspto", {}).get("mode"),
                    "max_requests_per_run": src.get("uspto", {}).get("max_requests_per_run"),
                    "lookback_days": src.get("uspto", {}).get("lookback_days"),
                },
            }
        else:
            editable[section] = {k: src.get(k) for k in keys if k in src}

    return {
        "config": editable,
        "model_suggestions": _MODEL_SUGGESTIONS,
    }
