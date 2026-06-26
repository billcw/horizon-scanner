# L4-MONITORING-PASS
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
        "assess_relevance": bool(m.get("assess_relevance", True)),
        "assess_min_signals": int(m.get("assess_min_signals", 2)),
        "model": m.get("model", "claude-haiku-4-5-20251001"),
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
    assess_relevance = cfg["assess_relevance"]
    assess_min_signals = cfg["assess_min_signals"]
    relevance_model = cfg["model"]

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

        # --- Relevance assessment (CONFIRMING / CONTRADICTING) ---
        # Gated: only when there are at least assess_min_signals NEW signals
        # since the baseline. NEUTRAL verdicts are assessed but not logged.
        if assess_relevance and last_count is not None:
            new_count = current - last_count
            if new_count >= assess_min_signals:
                try:
                    _assess_relevance(
                        th, cluster_id, new_count,
                        relevance_model, summary)
                except Exception:
                    # Never let assessment failure abort the pass.
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


# L4-MONITORING-RELEVANCE-PASS
def _get_anthropic_client():
    """
    Anthropic client factory. Same pattern as edgar_client / thesis_loop:
    raw anthropic.Anthropic keyed off ANTHR_HORIZON. Imported lazily so the
    monitoring module stays importable without the SDK present.
    """
    import os as _os
    import anthropic
    api_key = _os.environ.get("ANTHR_HORIZON")
    if not api_key:
        raise RuntimeError("ANTHR_HORIZON environment variable not set.")
    return anthropic.Anthropic(api_key=api_key)


def _extract_json_object(text):
    """Pull the first JSON object out of a model response. {} on failure."""
    import json
    import re
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
    try:
        val = json.loads(cleaned)
        return val if isinstance(val, dict) else {}
    except (ValueError, TypeError):
        pass
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            val = json.loads(match.group(0))
            return val if isinstance(val, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


_VALID_VERDICTS = ("CONFIRMING", "CONTRADICTING", "NEUTRAL")


def _assess_relevance(thesis, cluster_id, new_count, model, summary):
    """
    Judge the newest `new_count` signals on a cluster against the thesis.
    Writes a CONFIRMING or CONTRADICTING monitoring event when warranted;
    NEUTRAL is assessed but not logged. Best-effort and non-fatal.
    """
    tid = thesis["id"]
    title = thesis.get("title") or "(untitled thesis)"

    # Fetch the newest signals on the cluster. Cap the batch so the prompt
    # stays small even if new_count is large.
    batch_n = min(int(new_count), 12)
    signals = database.get_recent_cluster_signals(cluster_id, limit=batch_n)
    if not signals:
        return

    # Build a compact signal list for the prompt.
    lines = []
    for s in signals:
        t = (s.get("title") or "").strip().replace("\n", " ")
        cat = (s.get("category") or "UNCLASSIFIED").strip()
        if len(t) > 200:
            t = t[:200] + "..."
        lines.append("- [%s] %s" % (cat, t))
    signal_block = "\n".join(lines)

    system = (
        "You assess whether new research/patent/trend signals CONFIRM or "
        "CONTRADICT an existing investment thesis. Be conservative: only say "
        "CONFIRMING when the signals add genuine supporting evidence for the "
        "thesis direction, and CONTRADICTING when they point against it (e.g. "
        "a competing approach displacing it, the bottleneck dissolving, or "
        "the trend reversing). If the signals are merely on-topic but neutral, "
        "say NEUTRAL. Respond ONLY with a JSON object, no prose."
    )
    user = (
        "THESIS: %s\n\n"
        "NEW SIGNALS:\n%s\n\n"
        "Return exactly: {\"verdict\": \"CONFIRMING|CONTRADICTING|NEUTRAL\", "
        "\"rationale\": \"one short sentence\"}"
        % (title, signal_block)
    )

    try:
        client = _get_anthropic_client()
    except Exception as e:
        # No SDK / no key -- skip silently (logged once at debug).
        return

    try:
        response = client.messages.create(
            model=model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = response.content[0].text.strip()
    except Exception:
        return

    obj = _extract_json_object(raw)
    verdict = (obj.get("verdict") or "").strip().upper()
    if verdict not in _VALID_VERDICTS:
        return
    if verdict == "NEUTRAL":
        # Assessed but intentionally not logged.
        return

    rationale = (obj.get("rationale") or "").strip()
    if len(rationale) > 280:
        rationale = rationale[:280] + "..."
    desc = "%s: %s (based on %d new signal%s)" % (
        verdict.capitalize(), rationale or "(no rationale given)",
        len(signals), "" if len(signals) == 1 else "s")

    database.insert_monitoring_event(
        thesis_id=tid,
        event_type=verdict,
        description=desc,
    )
    summary["events_created"] += 1
    summary.setdefault("relevance", []).append((tid, verdict))
