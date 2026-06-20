"""
classifier/signal_classifier.py

L2 — classifies raw signals into NOISE / FAD / CULTURAL / EMERGING / STRUCTURAL.
Uses Haiku for speed/cost, falls back to Sonnet if confidence is low.
Also handles semantic deduplication and cluster management.
"""

import json
import logging
from datetime import datetime, timezone

import anthropic
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from ..config import get_config, get_anthropic_key
from ..database import (
    get_unclassified_signals,
    update_signal_classification,
    upsert_cluster,
    get_clusters_ready_for_escalation,
    get_signals_by_category,
    insert_signal,
)

logger = logging.getLogger(__name__)

# Load embedding model once (cached after first load)
_embed_model = None

def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        logger.info("Loading sentence-transformer model (first run only)...")
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a technology and market intelligence classifier for an investment research system.

Your job is to classify incoming signals (news, papers, trends, patents, posts) into one of five categories:

NOISE       — No actionable content. Duplicate reporting, celebrity gossip, political opinion 
              without economic substance, off-topic content.

FAD         — Real phenomenon but likely short-lived. Consumer trend with no structural 
              technology or regulatory basis. Think goat yoga, fidget spinners.

CULTURAL    — Generational or behavioral shift with identifiable long-duration economic effects.
              Think Gen Z financial behavior, remote work, aging demographics.

EMERGING    — Recurring pattern across multiple independent sources, novel technology with 
              a plausible commercial pathway, or industry shift with identifiable beneficiaries.
              This is the key category — err toward EMERGING when uncertain between FAD and EMERGING.

STRUCTURAL  — Technology, regulatory, or demographic shift that will change the operating 
              environment for entire sectors for 5+ years. Examples: CUDA/GPU for AI (2006-2012),
              mRNA platform validation (2020), shale fracking (2005-2010).

Return ONLY valid JSON. No preamble, no explanation, no markdown:
{
  "category": "NOISE|FAD|CULTURAL|EMERGING|STRUCTURAL",
  "confidence": 0.0,
  "theme": "2-5 word label",
  "time_horizon": "short|medium|long|structural",
  "reason": "one concise sentence explaining the classification"
}"""

USER_TEMPLATE = """Classify this signal:

SOURCE: {source}
TITLE: {title}
CONTENT: {content}"""


def _classify_single(client, signal: dict, model: str) -> dict:
    """Call the LLM to classify one signal. Returns parsed JSON dict."""
    content_preview = (signal.get("content") or "")[:800]

    response = client.messages.create(
        model=model,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_TEMPLATE.format(
                source  = signal.get("source", ""),
                title   = signal.get("title", ""),
                content = content_preview,
            )
        }]
    )

    raw = response.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ---------------------------------------------------------------------------
# Semantic deduplication
# ---------------------------------------------------------------------------

def _is_semantic_duplicate(signal: dict, threshold: float) -> bool:
    """
    Check if this signal is semantically too similar to recent signals.
    Uses cached embeddings from the last 90 days.
    """
    # For Phase 0 we use a simplified version — just check content hash 
    # (already done at insert time). Full embedding-based dedup added in Phase 1
    # when ChromaDB is integrated.
    return False


# ---------------------------------------------------------------------------
# Main classifier run
# ---------------------------------------------------------------------------

def run_classifier(batch_size: int = 50):
    """
    Classify all unclassified signals in the database.
    Run after each collector batch.
    """
    cfg       = get_config()
    cls_cfg   = cfg["classifier"]

    primary_model   = cls_cfg.get("model", "claude-haiku-4-5-20251001")
    fallback_model  = cls_cfg.get("fallback_model", "claude-sonnet-4-6")
    conf_threshold  = cls_cfg.get("confidence_threshold", 0.70)

    client    = anthropic.Anthropic(api_key=get_anthropic_key())
    signals   = get_unclassified_signals(limit=batch_size)

    if not signals:
        logger.info("No unclassified signals to process.")
        return 0

    logger.info(f"Classifying {len(signals)} signals...")

    classified = 0
    errors     = 0

    for signal in signals:
        try:
            result = _classify_single(client, signal, primary_model)

            # Fallback to Sonnet if confidence is low
            if result.get("confidence", 0) < conf_threshold:
                logger.debug(f"Low confidence ({result['confidence']:.2f}), retrying with Sonnet...")
                result = _classify_single(client, signal, fallback_model)

            update_signal_classification(
                signal_id    = signal["id"],
                category     = result.get("category", "NOISE"),
                confidence   = result.get("confidence", 0.0),
                theme        = result.get("theme", ""),
                time_horizon = result.get("time_horizon", ""),
            )

            # Cluster EMERGING and STRUCTURAL signals
            if result.get("category") in ("EMERGING", "STRUCTURAL"):
                theme = result.get("theme", "general")
                upsert_cluster(theme, signal["id"])

            classified += 1

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error classifying signal {signal['id']}: {e}")
            errors += 1
        except Exception as e:
            logger.error(f"Error classifying signal {signal['id']}: {e}")
            errors += 1

    logger.info(f"Classifier complete. {classified} classified, {errors} errors.")
    return classified


# ---------------------------------------------------------------------------
# Escalation check
# ---------------------------------------------------------------------------

def check_escalations() -> list:
    """
    Return clusters that have hit the threshold and are ready for L3.
    Does NOT trigger L3 — that's the orchestrator's job.
    """
    cfg       = get_config()
    threshold = cfg["classifier"]["cluster_escalation_threshold"]
    ready     = get_clusters_ready_for_escalation(threshold)

    if ready:
        logger.info(f"{len(ready)} cluster(s) ready for L3 escalation: "
                    f"{[c['theme'] for c in ready]}")
    return ready


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_classifier()
    check_escalations()
