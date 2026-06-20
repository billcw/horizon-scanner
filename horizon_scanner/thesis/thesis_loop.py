"""
thesis/thesis_loop.py

L3 — 8-step thesis generation loop.
Takes a signal cluster, runs structured reasoning, produces a scored thesis.

Steps:
  1. Context Assembly
  2. Technology Viability Assessment
  3. Bottleneck Mapping
  4. Scenario Tree Generation
  5. Entity Mapping (4 rings)
  6. Platform / Product Classification
  7. Adversarial Challenge
  8. Scoring & Output
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TypedDict, Optional

import anthropic
import requests

from ..config import get_config, get_anthropic_key, get_perplexity_key
from ..database import (
    get_connection, insert_thesis, mark_cluster_escalated
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State object passed between loop steps
# ---------------------------------------------------------------------------

class ThesisState(TypedDict):
    cluster_id:       str
    theme:            str
    signals:          list           # raw signal dicts from DB
    context_doc:      str            # Step 1 output
    viability:        dict           # Step 2 output
    bottleneck:       dict           # Step 3 output
    scenarios:        list           # Step 4 output
    entities:         dict           # Step 5 output (rings 1-4)
    platform_class:   dict           # Step 6 output
    adversarial:      dict           # Step 7 output
    scoring:          dict           # Step 8 output
    errors:           list
    thesis_id:        Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_cluster_signals(cluster_id: str) -> tuple[str, list]:
    """Fetch cluster theme and all its signals from the DB."""
    with get_connection() as conn:
        cluster = conn.execute(
            "SELECT theme FROM signal_clusters WHERE id=?", (cluster_id,)
        ).fetchone()
        if not cluster:
            raise ValueError(f"Cluster not found: {cluster_id}")
        theme = cluster["theme"]

        signals = conn.execute(
            """SELECT title, content, url, source, published_at
               FROM signals WHERE cluster_id=? ORDER BY collected_at ASC""",
            (cluster_id,)
        ).fetchall()
        return theme, [dict(s) for s in signals]


def _call_claude(client, system: str, user: str, model: str = None,
                 max_tokens: int = 2000) -> str:
    """Single Claude API call. Returns text content."""
    cfg = get_config()
    if model is None:
        model = cfg["thesis"]["step_model"]

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    return response.content[0].text.strip()


def _parse_json(text: str) -> dict:
    """Parse JSON from LLM output, tolerant of common malformations."""
    import re
    text = text.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        lines = text.split(chr(10))
        if lines[-1].strip() == fence:
            text = chr(10).join(lines[1:-1])
        else:
            text = chr(10).join(lines[1:])
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass
    try:
        repaired = text[text.index("{"):text.rindex("}") + 1]
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
        return json.loads(repaired)
    except (ValueError, json.JSONDecodeError):
        pass
    logger.warning("Could not parse JSON, empty dict. First 200: " + text[:200])
    return {}
def _web_search(query: str) -> str:
    """Search via Perplexity Sonar API. Falls back gracefully if key missing."""
    try:
        key = get_perplexity_key()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "sonar",
            "messages": [
                {"role": "system", "content": "You are a technology research assistant. Be concise and factual."},
                {"role": "user", "content": query}
            ],
            "max_tokens": 500
        }
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers, json=payload, timeout=20
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"Web search failed (non-fatal): {e}")
        return f"[Web search unavailable: {e}]"


# ---------------------------------------------------------------------------
# Step 1 — Context Assembly
# ---------------------------------------------------------------------------

def step1_context(state: ThesisState, client) -> ThesisState:
    logger.info("Step 1: Context Assembly")

    signals_text = "\n\n".join([
        f"PAPER: {s['title']}\nABSTRACT: {s['content'][:500]}\nURL: {s['url']}"
        for s in state["signals"]
    ])

    # Web search for current state of the technology
    search_result = _web_search(
        f"Current state of {state['theme']} technology 2025 2026 commercial progress companies"
    )

    context = f"""THESIS TOPIC: {state['theme']}

TRIGGERING SIGNALS ({len(state['signals'])} papers):
{signals_text}

CURRENT STATE (web search):
{search_result}
"""
    state["context_doc"] = context
    return state


# ---------------------------------------------------------------------------
# Step 2 — Technology Viability Assessment
# ---------------------------------------------------------------------------

STEP2_SYSTEM = """You are a technology analyst assessing the scientific and commercial viability 
of an emerging technology. Be rigorous and cite specific evidence from the provided context.
Return ONLY valid JSON, no preamble."""

STEP2_SCHEMA = """{
  "is_scientifically_plausible": true,
  "plausibility_reasoning": "...",
  "current_trl": 4,
  "trl_reasoning": "TRL 1=basic research, 9=proven in production",
  "engineering_barriers": ["barrier 1", "barrier 2", "barrier 3"],
  "timeline_years_low": 5,
  "timeline_years_high": 15,
  "timeline_reasoning": "...",
  "key_evidence": ["evidence 1", "evidence 2"]
}"""

def step2_viability(state: ThesisState, client) -> ThesisState:
    logger.info("Step 2: Technology Viability Assessment")

    user = f"""Assess the technology viability for: {state['theme']}

CONTEXT:
{state['context_doc'][:3000]}

Return JSON matching this schema exactly:
{STEP2_SCHEMA}"""

    result = _call_claude(client, STEP2_SYSTEM, user, max_tokens=1500)
    state["viability"] = _parse_json(result)
    return state


# ---------------------------------------------------------------------------
# Step 3 — Bottleneck Mapping
# ---------------------------------------------------------------------------

STEP3_SYSTEM = """You are a supply chain and technology infrastructure analyst.
Your job is to identify the critical bottlenecks in a technology's path to scale,
and the companies positioned to solve them. Return ONLY valid JSON."""

STEP3_SCHEMA = """{
  "primary_bottleneck": "the single most critical constraint to scaling",
  "bottleneck_type": "materials|manufacturing|energy|compute|talent|regulatory|capital",
  "bottleneck_reasoning": "...",
  "bottleneck_company": "company name most likely to solve this",
  "bottleneck_ticker": "TICKER or null if private",
  "secondary_bottlenecks": ["bottleneck 2", "bottleneck 3"],
  "ten_x_breaks_first": "if this technology becomes 10x bigger, what fails first and why"
}"""

def step3_bottleneck(state: ThesisState, client) -> ThesisState:
    logger.info("Step 3: Bottleneck Mapping")

    search = _web_search(
        f"What are the main technical and manufacturing bottlenecks limiting {state['theme']} scalability"
    )

    user = f"""Identify the critical bottlenecks for: {state['theme']}

TECHNOLOGY CONTEXT:
{state['context_doc'][:2000]}

ADDITIONAL RESEARCH:
{search}

Return JSON matching this schema exactly:
{STEP3_SCHEMA}"""

    result = _call_claude(client, STEP3_SYSTEM, user, max_tokens=1000)
    state["bottleneck"] = _parse_json(result)
    return state


# ---------------------------------------------------------------------------
# Step 4 — Scenario Tree
# ---------------------------------------------------------------------------

STEP4_SYSTEM = """You are a scenario planning analyst. Generate plausible future scenarios
for a technology investment thesis. Be specific about conditions and timelines.
Return ONLY valid JSON."""

STEP4_SCHEMA = """{
  "scenarios": [
    {
      "label": "Base Case",
      "description": "most likely outcome given current evidence",
      "conditions": ["condition 1", "condition 2"],
      "probability": 0.50,
      "timeline_years": 8,
      "investment_implication": "..."
    },
    {
      "label": "Bull Case",
      "description": "accelerated adoption scenario",
      "conditions": ["condition 1", "condition 2"],
      "probability": 0.25,
      "timeline_years": 5,
      "investment_implication": "..."
    },
    {
      "label": "Bear Case",
      "description": "thesis failure scenario",
      "conditions": ["condition 1", "condition 2"],
      "probability": 0.20,
      "timeline_years": 15,
      "investment_implication": "..."
    },
    {
      "label": "Black Swan",
      "description": "unexpected breakthrough or collapse",
      "conditions": ["condition 1"],
      "probability": 0.05,
      "timeline_years": 3,
      "investment_implication": "..."
    }
  ]
}"""

def step4_scenarios(state: ThesisState, client) -> ThesisState:
    logger.info("Step 4: Scenario Tree Generation")

    user = f"""Generate scenario tree for investment thesis: {state['theme']}

VIABILITY ASSESSMENT:
TRL: {state['viability'].get('current_trl')}
Timeline: {state['viability'].get('timeline_years_low')}-{state['viability'].get('timeline_years_high')} years
Barriers: {state['viability'].get('engineering_barriers')}

PRIMARY BOTTLENECK: {state['bottleneck'].get('primary_bottleneck')}

Return JSON matching this schema exactly:
{STEP4_SCHEMA}"""

    result = _call_claude(client, STEP4_SYSTEM, user, max_tokens=2000)
    data = _parse_json(result)
    state["scenarios"] = data.get("scenarios", [])
    return state


# ---------------------------------------------------------------------------
# Step 5 — Entity Mapping (4 Rings)
# ---------------------------------------------------------------------------

STEP5_SYSTEM = """You are an equity research analyst mapping the investment landscape
around an emerging technology. Identify specific publicly traded companies in each ring.
Be specific — name real companies with real tickers. Return ONLY valid JSON."""

STEP5_SCHEMA = """{
  "ring1_direct": [
    {"company": "Company Name", "ticker": "TICK", "role": "what they do in this space", "confidence": 0.9}
  ],
  "ring2_enabling": [
    {"company": "Company Name", "ticker": "TICK", "role": "what they supply/enable", "confidence": 0.8}
  ],
  "ring3_benefiting": [
    {"company": "Company Name", "ticker": "TICK", "role": "how they benefit indirectly", "confidence": 0.7}
  ],
  "ring4_threatened": [
    {"company": "Company Name", "ticker": "TICK", "role": "how they are threatened", "confidence": 0.6}
  ]
}"""

def step5_entities(state: ThesisState, client) -> ThesisState:
    logger.info("Step 5: Entity Mapping")

    search = _web_search(
        f"public companies investing in {state['theme']} stocks ETFs 2025 2026"
    )

    user = f"""Map the investment landscape for: {state['theme']}

TECHNOLOGY CONTEXT:
TRL: {state['viability'].get('current_trl')}
Bottleneck company: {state['bottleneck'].get('bottleneck_company')} ({state['bottleneck'].get('bottleneck_ticker')})

MARKET RESEARCH:
{search}

Ring definitions:
- Ring 1 DIRECT: Companies building this technology
- Ring 2 ENABLING: Companies supplying materials, components, equipment, or infrastructure
- Ring 3 BENEFITING: Companies whose existing business becomes more valuable if this succeeds
- Ring 4 THREATENED: Companies whose business model is displaced if this succeeds

List 2-4 companies per ring. Use null for ticker if company is private.

Return JSON matching this schema exactly:
{STEP5_SCHEMA}"""

    result = _call_claude(client, STEP5_SYSTEM, user, max_tokens=2000)
    state["entities"] = _parse_json(result)
    return state


# ---------------------------------------------------------------------------
# Step 6 — Platform / Product Classification
# ---------------------------------------------------------------------------

STEP6_SYSTEM = """You are a technology moat analyst. Classify each Ring 1 company by
whether it is building infrastructure/platform vs. a point product. Return ONLY valid JSON."""

STEP6_SCHEMA = """{
  "classifications": [
    {
      "company": "Company Name",
      "ticker": "TICK",
      "platform_type": "INFRASTRUCTURE|ENABLER|CYCLICAL_BENEFICIARY|STORY_STOCK|FRAUD_CANDIDATE",
      "platform_score": 0.85,
      "has_developer_ecosystem": true,
      "has_switching_costs": true,
      "has_pricing_power": false,
      "moat_summary": "one sentence on moat or lack thereof",
      "shovel_or_railroad": "selling shovels|leasing land|owning the railroad|souvenir shirts"
    }
  ],
  "best_platform_candidate": "Company Name",
  "best_platform_ticker": "TICK"
}"""

def step6_platform(state: ThesisState, client) -> ThesisState:
    logger.info("Step 6: Platform/Product Classification")

    ring1 = state["entities"].get("ring1_direct", [])
    ring1_text = "\n".join([
        f"- {e.get('company')} ({e.get('ticker')}): {e.get('role')}"
        for e in ring1
    ])

    user = f"""Classify the platform/moat strength for Ring 1 companies in: {state['theme']}

RING 1 COMPANIES:
{ring1_text}

For each company, assess:
- Is it building infrastructure others depend on, or a point product?
- Does it have switching costs, developer ecosystem, pricing power?
- Is it selling shovels, leasing land, owning the railroad, or selling souvenir shirts?

Return JSON matching this schema exactly:
{STEP6_SCHEMA}"""

    result = _call_claude(client, STEP6_SYSTEM, user, max_tokens=1500)
    state["platform_class"] = _parse_json(result)
    return state


# ---------------------------------------------------------------------------
# Step 7 — Adversarial Challenge
# ---------------------------------------------------------------------------

STEP7_SYSTEM = """You are a skeptical investment analyst whose job is to find every reason
why an investment thesis might be WRONG. Be rigorous, specific, and cite historical precedents
where similar technologies failed. This is not a balanced view — argue the bear case hard.
Return ONLY valid JSON."""

STEP7_SCHEMA = """{
  "strongest_bear_argument": "the single most compelling reason this thesis fails",
  "historical_precedents": ["technology/company that failed in a similar way"],
  "contradicting_evidence": ["specific fact that contradicts the bull case"],
  "overestimated_factors": ["factor the bull case overweights"],
  "underestimated_risks": ["risk the bull case ignores"],
  "timeline_risk": "specific reason the timeline estimate might be wrong",
  "competition_risk": "who could make this thesis obsolete and how",
  "regulatory_risk": "specific regulatory scenario that kills the thesis",
  "verdict": "WEAK_THESIS|MODERATE_THESIS|STRONG_THESIS",
  "verdict_reasoning": "one paragraph summary"
}"""

def step7_adversarial(state: ThesisState, client) -> ThesisState:
    logger.info("Step 7: Adversarial Challenge")
    cfg = get_config()
    adv_model = cfg["thesis"].get("adversarial_model", cfg["thesis"]["step_model"])

    search = _web_search(
        f"criticisms problems failures risks {state['theme']} why it won't work"
    )

    bull_summary = f"""
Theme: {state['theme']}
TRL: {state['viability'].get('current_trl')} — Timeline: {state['viability'].get('timeline_years_low')}-{state['viability'].get('timeline_years_high')} years
Bull scenario: {next((s['description'] for s in state['scenarios'] if 'Bull' in s['label']), 'N/A')}
Key companies: {', '.join([e.get('company','') for e in state['entities'].get('ring1_direct',[])])}
"""

    user = f"""Challenge this investment thesis — argue the bear case:

THESIS SUMMARY:
{bull_summary}

BEAR CASE RESEARCH:
{search}

Find every reason this is wrong. Be specific. Cite precedents.

Return JSON matching this schema exactly:
{STEP7_SCHEMA}"""

    result = _call_claude(client, STEP7_SYSTEM, user,
                          model=adv_model, max_tokens=2000)
    state["adversarial"] = _parse_json(result)
    return state


# ---------------------------------------------------------------------------
# Step 8 — Scoring & Final Output
# ---------------------------------------------------------------------------

STEP8_SYSTEM = """You are a senior investment analyst producing a final scored thesis.
Synthesize all research into a structured investment scorecard. Return ONLY valid JSON."""

STEP8_SCHEMA = """{
  "thesis_quality_score": 72,
  "buy_now_score": 45,
  "score_breakdown": {
    "technical_inevitability": 14,
    "revenue_linkage": 12,
    "moat_platform_strength": 10,
    "market_size_realism": 8,
    "financial_quality": 7,
    "management_credibility": 6,
    "adoption_velocity": 4,
    "balance_sheet_dilution": 3,
    "valuation_reasonableness": 8,
    "hype_fraud_penalty": 0
  },
  "confidence_rating": "WATCH",
  "risk_profile": "HIGH",
  "company_type": "ENABLER",
  "kill_criteria": ["specific measurable fact that would invalidate thesis"],
  "watch_triggers": ["specific event that would upgrade to CANDIDATE"],
  "holding_period_years": 7,
  "position_size_suggestion": "small initial — 1-2% max until TRL advances",
  "one_line_summary": "concise investment thesis summary"
}"""

def step8_scoring(state: ThesisState, client) -> ThesisState:
    logger.info("Step 8: Scoring & Final Output")

    user = f"""Produce final investment scorecard for: {state['theme']}

SYNTHESIS:
- TRL: {state['viability'].get('current_trl')} | Timeline: {state['viability'].get('timeline_years_low')}-{state['viability'].get('timeline_years_high')} years
- Primary bottleneck: {state['bottleneck'].get('primary_bottleneck')}
- Best platform candidate: {state['platform_class'].get('best_platform_candidate')} ({state['platform_class'].get('best_platform_ticker')})
- Bear verdict: {state['adversarial'].get('verdict')}
- Strongest bear argument: {state['adversarial'].get('strongest_bear_argument')}

SCORING WEIGHTS:
- technical_inevitability: 15 points max
- revenue_linkage: 15 points max
- moat_platform_strength: 15 points max
- market_size_realism: 10 points max
- financial_quality: 10 points max
- management_credibility: 10 points max
- adoption_velocity: 5 points max
- balance_sheet_dilution: 5 points max
- valuation_reasonableness: 10 points max
- hype_fraud_penalty: 0 to -10 points

confidence_rating options: WATCH | BUILDING | CANDIDATE | INSUFFICIENT
risk_profile options: LOW | MEDIUM | HIGH | VERY HIGH
company_type options: INFRASTRUCTURE | ENABLER | CYCLICAL_BENEFICIARY | STORY_STOCK | FRAUD_CANDIDATE

Return JSON matching this schema exactly:
{STEP8_SCHEMA}"""

    result = _call_claude(client, STEP8_SYSTEM, user, max_tokens=1500)
    state["scoring"] = _parse_json(result)
    return state


# ---------------------------------------------------------------------------
# Main loop runner
# ---------------------------------------------------------------------------

def run_thesis_loop(cluster_id: str) -> str:
    """
    Run the full 8-step thesis loop for a cluster.
    Returns the thesis_id of the saved thesis.
    """
    cfg    = get_config()
    client = anthropic.Anthropic(api_key=get_anthropic_key())

    # Load cluster signals
    theme, signals = _get_cluster_signals(cluster_id)
    logger.info(f"Starting thesis loop for cluster: '{theme}' ({len(signals)} signals)")

    state: ThesisState = {
        "cluster_id":     cluster_id,
        "theme":          theme,
        "signals":        signals,
        "context_doc":    "",
        "viability":      {},
        "bottleneck":     {},
        "scenarios":      [],
        "entities":       {},
        "platform_class": {},
        "adversarial":    {},
        "scoring":        {},
        "errors":         [],
        "thesis_id":      None,
    }

    steps = [
        ("Step 1: Context Assembly",           step1_context),
        ("Step 2: Viability Assessment",       step2_viability),
        ("Step 3: Bottleneck Mapping",         step3_bottleneck),
        ("Step 4: Scenario Tree",              step4_scenarios),
        ("Step 5: Entity Mapping",             step5_entities),
        ("Step 6: Platform Classification",    step6_platform),
        ("Step 7: Adversarial Challenge",      step7_adversarial),
        ("Step 8: Scoring & Output",           step8_scoring),
    ]

    for step_name, step_fn in steps:
        try:
            print(f"  → {step_name}...")
            state = step_fn(state, client)
        except Exception as e:
            logger.error(f"{step_name} failed: {e}")
            state["errors"].append(f"{step_name}: {str(e)}")
            # Continue to next step rather than aborting

    # Assemble thesis record
    scoring  = state["scoring"]
    viability = state["viability"]

    thesis = {
        "cluster_id":           cluster_id,
        "title":                f"{theme} Investment Thesis",
        "theme":                theme,
        "company_type":         scoring.get("company_type", "ENABLER"),
        "technology_trl":       viability.get("current_trl"),
        "trl_source":           "arXiv paper analysis",
        "bottleneck_entity":    state["bottleneck"].get("bottleneck_company"),
        "bottleneck_ticker":    state["bottleneck"].get("bottleneck_ticker"),
        "timeline_years_low":   viability.get("timeline_years_low"),
        "timeline_years_high":  viability.get("timeline_years_high"),
        "scenarios":            json.dumps(state["scenarios"]),
        "entities_ring1":       json.dumps(state["entities"].get("ring1_direct", [])),
        "entities_ring2":       json.dumps(state["entities"].get("ring2_enabling", [])),
        "entities_ring3":       json.dumps(state["entities"].get("ring3_benefiting", [])),
        "entities_ring4":       json.dumps(state["entities"].get("ring4_threatened", [])),
        "scoring_card":         json.dumps(scoring.get("score_breakdown", {})),
        "thesis_quality_score": scoring.get("thesis_quality_score"),
        "buy_now_score":        scoring.get("buy_now_score"),
        "adversarial_summary":  state["adversarial"].get("verdict_reasoning", ""),
        "kill_criteria":        json.dumps(scoring.get("kill_criteria", [])),
        "risk_profile":         scoring.get("risk_profile", "HIGH"),
        "confidence_rating":    scoring.get("confidence_rating", "WATCH"),
        "sources":              json.dumps([s.get("url") for s in signals]),
        "state":                "WATCH",
    }

    thesis_id = insert_thesis(thesis)
    mark_cluster_escalated(cluster_id, thesis_id)

    logger.info(f"Thesis saved: {thesis_id}")
    logger.info(f"Quality score: {scoring.get('thesis_quality_score')}/100")
    logger.info(f"Buy-now score: {scoring.get('buy_now_score')}/100")
    logger.info(f"Confidence: {scoring.get('confidence_rating')}")

    state["thesis_id"] = thesis_id
    return thesis_id, state
