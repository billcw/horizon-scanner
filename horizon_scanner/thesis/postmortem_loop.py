"""
horizon_scanner/thesis/postmortem_loop.py

L5-B: Post-mortem reasoning loop.
L5-D: Exit discipline check.

Both are lightweight 2-3 step AI loops that run against an existing thesis
and a completed (or live) decision.  They use the same Anthropic client
pattern as thesis_loop.py but are deliberately short -- the goal is a
structured judgment, not a full 8-step synthesis.

Post-mortem (run_postmortem):
  Step 1 -- Compare thesis predictions vs. what actually happened.
  Step 2 -- Identify right/wrong/silent thesis elements.
  Step 3 -- Produce a pattern_tag and 2-3 sentence narrative summary.

Exit discipline check (run_exit_check):
  Step 1 -- Review the thesis kill_criteria against current cluster signals.
  Step 2 -- Produce a HOLD/SELL recommendation with reasoning, subject to
            the same emotional-flag discipline as entry decisions.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid pattern tags (post-mortem classification vocabulary)
# ---------------------------------------------------------------------------
# These are intentional, opinionated labels.  They read as a ledger of
# specific mistakes and validations, not vague performance buckets.

PATTERN_TAGS = [
    "SOLD_WINNER_EARLY",       # exited a position that kept running
    "HELD_LOSER_TOO_LONG",     # failed to act on kill criteria
    "FOMO_ENTRY_CONFIRMED",    # emotional flag was correct; entry was premature
    "FOMO_ENTRY_UNFOUNDED",    # emotional flag fired but trade was actually fine
    "THESIS_VALIDATED",        # thesis predicted correctly; outcome matched scenario
    "THESIS_INVALIDATED",      # thesis was wrong on the core call
    "KILL_CRITERIA_TRIGGERED", # a kill criterion fired and position was correctly exited
    "KILL_CRITERIA_MISSED",    # a kill criterion fired but position was NOT exited
    "CORRECT_BEAR",            # PASS/EXIT decision was correct; thesis didn't play out
    "PREMATURE_PASS",          # PASS/WATCH decision missed a real opportunity
    "POSITION_SIZE_ERROR",     # thesis was right but position was too small/large
    "TIMING_ERROR",            # thesis direction was right but timing was wrong
    "INSUFFICIENT_DATA",       # not enough outcome data to classify yet
]

# ---------------------------------------------------------------------------
# Anthropic client (same pattern as thesis_loop.py)
# ---------------------------------------------------------------------------

def _get_client():
    import anthropic
    api_key = os.environ.get("ANTHR_HORIZON")
    if not api_key:
        raise RuntimeError(
            "ANTHR_HORIZON environment variable not set. "
            "Set it in Windows environment variables."
        )
    return anthropic.Anthropic(api_key=api_key)


def _call(client, model: str, system: str, user: str, max_tokens: int = 1200) -> str:
    """Single synchronous Anthropic call. Returns the text content."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


def _extract_json(text: str) -> dict:
    """
    Pull the first JSON object out of a response that may contain prose.
    Falls back to {} on any parse failure.
    """
    # Try raw parse first
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    # Find first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except (ValueError, TypeError):
            pass
    return {}


# ---------------------------------------------------------------------------
# Post-mortem loop (L5-B)
# ---------------------------------------------------------------------------

_PM_SYSTEM = """
You are a post-mortem analyst for a structured investment decision log.
Your job is to compare what a thesis predicted against what actually happened
after a decision was made, then produce a concise, honest verdict.

Rules:
- Be blunt.  The purpose is learning, not consolation.
- Do not invent information.  If outcome data is thin, say so and use
  INSUFFICIENT_DATA as the pattern tag.
- The pattern_tag must be exactly one of the values in the provided list.
- Output valid JSON only, no prose outside the JSON object.
"""

_PM_STEP1_PROMPT = """
THESIS SNAPSHOT AT DECISION TIME:
{thesis_json}

DECISION MADE:
Type: {decision_type}
Ticker: {ticker}
Stated reason: {stated_reason}
Emotional flag fired: {emotional_flag}
Emotional flag reason: {emotional_reason}
Price at decision: {price_at_decision}

OUTCOME DATA (filled in by the user):
Price at outcome: {price_at_outcome}
30-day note: {outcome_30d}
90-day note: {outcome_90d}
365-day note: {outcome_365d}

VALID PATTERN TAGS:
{pattern_tags}

Respond with a JSON object:
{{
  "thesis_right": ["list of thesis elements that proved correct"],
  "thesis_wrong": ["list of thesis elements that proved incorrect"],
  "thesis_silent": ["list of thesis elements where outcome is unknown/too early"],
  "kill_criteria_status": "NONE_TRIGGERED | ONE_OR_MORE_TRIGGERED | UNKNOWN",
  "outcome_direction": "UP | DOWN | FLAT | UNKNOWN",
  "pattern_tag": "one of the valid pattern tags above",
  "draft_summary": "2-3 sentence honest post-mortem narrative"
}}
"""

_PM_STEP2_PROMPT = """
Review your draft post-mortem and tighten it.

Draft:
{draft}

Rules:
- The summary must be 2-3 sentences.  No more.
- It must name the specific thesis element that was right or wrong (not just
  "the thesis was correct").
- It must connect the emotional_flag result to the outcome where relevant.
- Keep the same pattern_tag unless the draft analysis contradicts it.
- Output valid JSON only:
{{
  "pattern_tag": "...",
  "postmortem_summary": "2-3 sentence final narrative"
}}
"""


def run_postmortem(decision_id: str) -> tuple[str, str]:
    """
    Run the post-mortem loop for a resolved decision.
    Returns (pattern_tag, postmortem_summary).
    Raises on API or data errors.
    """
    from .. import database as db

    decision = db.get_decision_by_id(decision_id)
    if not decision:
        raise ValueError(f"Decision {decision_id} not found")

    thesis_snapshot = decision.get("thesis_snapshot") or "{}"
    if isinstance(thesis_snapshot, str):
        try:
            thesis_snapshot = json.loads(thesis_snapshot)
        except (ValueError, TypeError):
            thesis_snapshot = {}

    client = _get_client()
    # Use Sonnet -- this is a reasoning task, not a data-heavy synthesis
    from ..config import get_config
    cfg = get_config()
    model = cfg.get("thesis", {}).get("step_model", "claude-sonnet-4-6")

    # Step 1: compare thesis vs. outcome
    step1_user = _PM_STEP1_PROMPT.format(
        thesis_json=json.dumps(thesis_snapshot, indent=2)[:3000],
        decision_type=decision.get("decision_type", ""),
        ticker=decision.get("ticker") or "N/A",
        stated_reason=decision.get("stated_reason") or "",
        emotional_flag=bool(decision.get("emotional_flag")),
        emotional_reason=decision.get("emotional_reason") or "",
        price_at_decision=decision.get("price_at_decision") or "not recorded",
        price_at_outcome=decision.get("price_at_outcome") or "not recorded",
        outcome_30d=decision.get("outcome_30d") or "not recorded",
        outcome_90d=decision.get("outcome_90d") or "not recorded",
        outcome_365d=decision.get("outcome_365d") or "not recorded",
        pattern_tags="\n".join(f"  - {t}" for t in PATTERN_TAGS),
    )

    logger.info("Post-mortem step 1: comparing thesis vs. outcome for decision %s", decision_id)
    step1_raw = _call(client, model, _PM_SYSTEM, step1_user, max_tokens=1500)
    step1 = _extract_json(step1_raw)

    if not step1:
        logger.warning("Post-mortem step 1 returned no parseable JSON; raw: %s", step1_raw[:200])
        return "INSUFFICIENT_DATA", "Post-mortem analysis could not be completed: insufficient structured data."

    # Step 2: tighten the narrative
    step2_user = _PM_STEP2_PROMPT.format(draft=json.dumps(step1, indent=2))
    logger.info("Post-mortem step 2: tightening narrative for decision %s", decision_id)
    step2_raw = _call(client, model, _PM_SYSTEM, step2_user, max_tokens=600)
    step2 = _extract_json(step2_raw)

    pattern_tag = step2.get("pattern_tag") or step1.get("pattern_tag") or "INSUFFICIENT_DATA"
    # Validate the tag against the known list; default if unrecognised
    if pattern_tag not in PATTERN_TAGS:
        logger.warning("Unrecognised pattern_tag '%s'; defaulting to INSUFFICIENT_DATA", pattern_tag)
        pattern_tag = "INSUFFICIENT_DATA"

    summary = (
        step2.get("postmortem_summary")
        or step1.get("draft_summary")
        or "No summary produced."
    )

    logger.info("Post-mortem complete: tag=%s", pattern_tag)
    return pattern_tag, summary


# ---------------------------------------------------------------------------
# Exit discipline check (L5-D)
# ---------------------------------------------------------------------------

_EXIT_SYSTEM = """
You are an exit discipline analyst for a structured investment decision log.
Your role is to evaluate whether an existing holding should be HELD or SOLD
based on the original thesis and its kill criteria.

You are the Skeptic Engine. Your job is to protect the investor from:
  1. Selling winners early on noise or short-term price moves (emotional sell)
  2. Holding losers whose kill criteria have already tripped (denial hold)

Rules:
- Cite the specific kill criterion that is or is not triggered.
- Emotional language in the reason for exiting is a red flag.
- A price spike alone is NOT a kill criterion unless the thesis said it was.
- Output valid JSON only.
"""

_EXIT_STEP1_PROMPT = """
CURRENT THESIS:
Title: {title}
Confidence: {confidence_rating}
State: {state}
Thesis quality score: {quality_score}
Buy-now score: {buy_now_score}
Risk profile: {risk_profile}
Timeline: {timeline_low}-{timeline_high} years

KILL CRITERIA (from original thesis):
{kill_criteria}

ADVERSARIAL SUMMARY (bear case):
{adversarial_summary}

RECENT CLUSTER SIGNALS (last 10, newest first):
{recent_signals}

PROPOSED EXIT REASON (from the user, may be empty):
{proposed_reason}

Respond with JSON:
{{
  "kill_criteria_triggered": true | false,
  "triggered_criterion": "exact text of the criterion, or null",
  "thesis_still_intact": true | false,
  "signal_direction": "CONFIRMING | CONTRADICTING | NEUTRAL | MIXED",
  "emotional_exit_risk": true | false,
  "emotional_exit_reason": "why this looks like an emotional exit, or null",
  "recommendation": "HOLD | SELL | REVIEW",
  "reasoning": "2-3 sentences explaining the recommendation"
}}
"""

_EXIT_STEP2_PROMPT = """
Sharpen your exit check verdict.

Draft:
{draft}

Proposed exit reason from the user:
{proposed_reason}

Rules:
- If emotional_exit_risk is true AND kill_criteria_triggered is false,
  recommendation should be HOLD unless thesis_still_intact is also false.
- If kill_criteria_triggered is true, recommendation should be SELL or REVIEW.
- The reasoning must name the specific kill criterion or signal that drove
  the decision (not just 'the thesis is weakening').
- Keep it to 2-3 sentences.
- Output valid JSON only:
{{
  "recommendation": "HOLD | SELL | REVIEW",
  "kill_criteria_triggered": true | false,
  "emotional_exit_risk": true | false,
  "reasoning": "2-3 sentence final verdict"
}}
"""


def run_exit_check(thesis_id: str, proposed_reason: str = "") -> dict:
    """
    Run the exit discipline check for a live thesis.
    Returns a dict with keys: recommendation, kill_criteria_triggered,
    emotional_exit_risk, reasoning.
    """
    from .. import database as db

    with db.get_connection() as conn:
        thesis_row = conn.execute(
            "SELECT * FROM theses WHERE id=?", (thesis_id,)
        ).fetchone()
        if not thesis_row:
            raise ValueError(f"Thesis {thesis_id} not found")
        thesis = dict(thesis_row)

        # Grab the 10 most recent signals for this thesis's cluster
        cluster_id = thesis.get("cluster_id")
        recent_signals = []
        if cluster_id:
            sig_rows = conn.execute(
                """SELECT title, theme, category, collected_at
                   FROM signals WHERE cluster_id=?
                   ORDER BY collected_at DESC LIMIT 10""",
                (cluster_id,)
            ).fetchall()
            recent_signals = [dict(r) for r in sig_rows]

    def _parse(val, default):
        if val is None:
            return default
        if isinstance(val, (list, dict)):
            return val
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return default

    kill_criteria = _parse(thesis.get("kill_criteria"), [])
    kill_text = "\n".join(
        f"  - {c}" if isinstance(c, str) else f"  - {c.get('criterion', str(c))}"
        for c in kill_criteria
    ) or "  (no kill criteria defined)"

    signals_text = "\n".join(
        f"  [{s.get('category','')}] {s.get('title','')[:120]}"
        for s in recent_signals
    ) or "  (no recent signals in this cluster)"

    client = _get_client()
    from ..config import get_config
    cfg = get_config()
    model = cfg.get("thesis", {}).get("step_model", "claude-sonnet-4-6")

    step1_user = _EXIT_STEP1_PROMPT.format(
        title=thesis.get("title", ""),
        confidence_rating=thesis.get("confidence_rating", ""),
        state=thesis.get("state", ""),
        quality_score=thesis.get("thesis_quality_score", "N/A"),
        buy_now_score=thesis.get("buy_now_score", "N/A"),
        risk_profile=thesis.get("risk_profile", "N/A"),
        timeline_low=thesis.get("timeline_years_low", "?"),
        timeline_high=thesis.get("timeline_years_high", "?"),
        kill_criteria=kill_text,
        adversarial_summary=thesis.get("adversarial_summary", "not available")[:1000],
        recent_signals=signals_text,
        proposed_reason=proposed_reason or "(none provided)",
    )

    logger.info("Exit check step 1 for thesis %s", thesis_id)
    step1_raw = _call(client, model, _EXIT_SYSTEM, step1_user, max_tokens=1000)
    step1 = _extract_json(step1_raw)

    if not step1:
        return {
            "recommendation": "REVIEW",
            "kill_criteria_triggered": False,
            "emotional_exit_risk": False,
            "reasoning": "Exit check could not produce a structured result. Review manually.",
        }

    step2_user = _EXIT_STEP2_PROMPT.format(
        draft=json.dumps(step1, indent=2),
        proposed_reason=proposed_reason or "(none provided)",
    )

    logger.info("Exit check step 2 for thesis %s", thesis_id)
    step2_raw = _call(client, model, _EXIT_SYSTEM, step2_user, max_tokens=500)
    step2 = _extract_json(step2_raw)

    return {
        "recommendation": step2.get("recommendation") or step1.get("recommendation", "REVIEW"),
        "kill_criteria_triggered": bool(
            step2.get("kill_criteria_triggered", step1.get("kill_criteria_triggered", False))
        ),
        "emotional_exit_risk": bool(
            step2.get("emotional_exit_risk", step1.get("emotional_exit_risk", False))
        ),
        "reasoning": (
            step2.get("reasoning")
            or step1.get("reasoning")
            or "No reasoning produced."
        ),
        "triggered_criterion": step1.get("triggered_criterion"),
        "thesis_still_intact": step1.get("thesis_still_intact", True),
        "signal_direction": step1.get("signal_direction", "UNKNOWN"),
    }
