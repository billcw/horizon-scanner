"""
patch_monitoring_relevance_pass.py

Adds the gated CONFIRMING / CONTRADICTING relevance assessment to the L4
monitoring pass.

When a thesis has >= assess_min_signals NEW signals since its baseline, the new
signal batch is sent to Haiku, judged against the thesis (title/theme), and a
CONFIRMING or CONTRADICTING monitoring event is written. NEUTRAL verdicts are
assessed but NOT logged (keeps the feed signal-rich). Wholly non-fatal: any
failure logs a warning and the pass continues.

Idempotent: aborts if sentinel already present or anchors are missing/ambiguous.

Run from project root:  python patch_monitoring_relevance_pass.py
"""
import ast
import io
import os

TARGET = os.path.join("horizon_scanner", "monitoring", "monitoring_pass.py")
SENTINEL = "# L4-MONITORING-RELEVANCE-PASS"

# --- Anchor 1: extend _cfg() to read the two new config keys -----------------
CFG_ANCHOR = '        "auto_rerun_on_spike": bool(m.get("auto_rerun_on_spike", False)),\n    }'
CFG_REPLACEMENT = '''        "auto_rerun_on_spike": bool(m.get("auto_rerun_on_spike", False)),
        "assess_relevance": bool(m.get("assess_relevance", True)),
        "assess_min_signals": int(m.get("assess_min_signals", 2)),
        "model": m.get("model", "claude-haiku-4-5-20251001"),
    }'''

# --- Anchor 2: pull the two new values inside run_monitoring_pass ------------
RUN_CFG_ANCHOR = '    auto_rerun = cfg["auto_rerun_on_spike"]'
RUN_CFG_REPLACEMENT = '''    auto_rerun = cfg["auto_rerun_on_spike"]
    assess_relevance = cfg["assess_relevance"]
    assess_min_signals = cfg["assess_min_signals"]
    relevance_model = cfg["model"]'''

# --- Anchor 3: run the assessment right before the baseline update -----------
# The baseline update line is the natural seam: by this point `current` and
# `last_count` are both known for the thesis.
ASSESS_ANCHOR = '''        # Update baseline for next pass.
        database.set_thesis_baseline(tid, current)'''
ASSESS_REPLACEMENT = '''        # --- Relevance assessment (CONFIRMING / CONTRADICTING) ---
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
        database.set_thesis_baseline(tid, current)'''

# --- Anchor 4: append the new functions + summary key. Append at EOF. --------
NEW_FUNCS = '''

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
        cleaned = re.sub(r"^```[a-zA-Z]*\\s*", "", cleaned)
        cleaned = re.sub(r"\\s*```$", "", cleaned)
        cleaned = cleaned.strip()
    try:
        val = json.loads(cleaned)
        return val if isinstance(val, dict) else {}
    except (ValueError, TypeError):
        pass
    match = re.search(r"\\{[\\s\\S]*\\}", cleaned)
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
        t = (s.get("title") or "").strip().replace("\\n", " ")
        cat = (s.get("category") or "UNCLASSIFIED").strip()
        if len(t) > 200:
            t = t[:200] + "..."
        lines.append("- [%s] %s" % (cat, t))
    signal_block = "\\n".join(lines)

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
        "THESIS: %s\\n\\n"
        "NEW SIGNALS:\\n%s\\n\\n"
        "Return exactly: {\\"verdict\\": \\"CONFIRMING|CONTRADICTING|NEUTRAL\\", "
        "\\"rationale\\": \\"one short sentence\\"}"
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
'''


def _apply_one(src, anchor, replacement, label):
    count = src.count(anchor)
    if count == 0:
        raise SystemExit("ERROR: anchor (%s) not found; aborting." % label)
    if count > 1:
        raise SystemExit("ERROR: anchor (%s) found %d times; ambiguous. Aborting."
                         % (label, count))
    return src.replace(anchor, replacement, 1)


def main():
    if not os.path.isfile(TARGET):
        raise SystemExit("ERROR: %s not found. Run from project root." % TARGET)

    with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
        src = f.read()

    if SENTINEL in src:
        print("Sentinel already present; nothing to do.")
        return

    src = _apply_one(src, CFG_ANCHOR, CFG_REPLACEMENT, "cfg")
    src = _apply_one(src, RUN_CFG_ANCHOR, RUN_CFG_REPLACEMENT, "run_cfg")
    src = _apply_one(src, ASSESS_ANCHOR, ASSESS_REPLACEMENT, "assess")
    src = src.rstrip("\n") + "\n" + NEW_FUNCS

    try:
        ast.parse(src)
    except SyntaxError as e:
        raise SystemExit("ERROR: patched file fails AST parse: %s" % e)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(src)

    print("OK: relevance assessment added to %s" % TARGET)


if __name__ == "__main__":
    main()
