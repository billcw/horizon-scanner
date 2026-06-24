"""
patch_counterparties.py

Idempotent patch: appends counterparty-extraction support to
horizon_scanner/enrichment/edgar_client.py.

Adds:
  - _get_anthropic_client()      Anthropic client factory (ANTHR_HORIZON)
  - _extract_json_array()        tolerant JSON-array parser
  - extract_counterparties()     Haiku pass over one filing document
  - deepen_counterparties()      pass over a thesis's enriched company objects

Safe to run multiple times. If the block is already present it does nothing.
Run from project root:

    python patch_counterparties.py
"""

import ast
import io
import os
import sys

TARGET = os.path.join(
    "horizon_scanner", "enrichment", "edgar_client.py"
)

SENTINEL = "# === COUNTERPARTY EXTRACTION (patch_counterparties) ==="

# Anchor: we insert BEFORE the standalone self-test section so the new
# functions sit with the rest of the library code, not after __main__.
ANCHOR = (
    "# ---------------------------------------------------------------------------\n"
    "# Self-test (run standalone; no API key needed)\n"
    "# ---------------------------------------------------------------------------"
)

NEW_BLOCK = r'''# === COUNTERPARTY EXTRACTION (patch_counterparties) ===
# ---------------------------------------------------------------------------
# Counterparty extraction (LLM pass)
# ---------------------------------------------------------------------------
# A licensing-phrase hit tells you a filing mentions a license; it does NOT
# tell you WHO the other party is. This layer reads the filing text and asks
# Haiku to name the counterparties. It is deliberately NOT run inline in every
# thesis run (cost: N companies x M filings x Haiku). It is a separate,
# explicitly-triggered "deepen" pass over an existing thesis's licensing hits.
#
# Honest caveat carried into the data: relationship_type is approximate. EFTS
# hits are a grab-bag; the model will sometimes mislabel an acquisition as a
# license. Each record carries a confidence value and a derived-from note so
# the UI can show, not hide, the uncertainty.

_COUNTERPARTY_MODEL_DEFAULT = "claude-haiku-4-5-20251001"
_COUNTERPARTY_PROMPT_CHARS = 6000


def _get_anthropic_client():
    """
    Anthropic client factory. Same pattern as thesis_loop / postmortem_loop:
    raw anthropic.Anthropic keyed off the ANTHR_HORIZON env var. Imported
    lazily so edgar_client stays importable without the SDK present (the rest
    of this module needs no Anthropic key).
    """
    import anthropic
    api_key = os.environ.get("ANTHR_HORIZON")
    if not api_key:
        raise RuntimeError(
            "ANTHR_HORIZON environment variable not set. "
            "Set it in Windows environment variables."
        )
    return anthropic.Anthropic(api_key=api_key)


def _counterparty_model() -> str:
    """Model string for the extraction pass; configurable, Haiku by default."""
    try:
        from ..config import get_config
        cfg = get_config()
        m = (cfg.get("enrichment", {})
                .get("edgar", {})
                .get("counterparty_model") or "").strip()
        if m:
            return m
    except Exception:
        pass
    return _COUNTERPARTY_MODEL_DEFAULT


def _extract_json_array(text: str) -> list:
    """
    Pull the first JSON array out of a model response that may contain prose
    or code fences. Returns [] on any parse failure (non-fatal by design).
    """
    import json
    if not text:
        return []
    cleaned = text.strip()
    # Strip ```json ... ``` fences if present.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
    # Try a direct parse first.
    try:
        val = json.loads(cleaned)
        return val if isinstance(val, list) else []
    except (ValueError, TypeError):
        pass
    # Find the first [...] block.
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if match:
        try:
            val = json.loads(match.group(0))
            return val if isinstance(val, list) else []
        except (ValueError, TypeError):
            return []
    return []


_VALID_REL_TYPES = {
    "acquisition", "license", "joint_venture",
    "supply", "partnership", "other",
}


def extract_counterparties(doc_url: str, subject_company: str,
                           client=None, model: str = None,
                           max_chars: int = _COUNTERPARTY_PROMPT_CHARS) -> list:
    """
    Read one SEC filing document and identify the OTHER companies that are
    parties to an agreement with subject_company.

    doc_url:          a filing document URL (e.g. an index_url from a
                      licensing hit, or a primary-doc URL). _fetch_document_text
                      handles the fetch + tag strip.
    subject_company:  the filer / company whose filing this is.
    client:           optional pre-built Anthropic client (reuse across calls).
    model:            optional model override; defaults to Haiku.

    Returns a list of dicts:
        {name, ticker, relationship_type, confidence, source_url}
    relationship_type is one of _VALID_REL_TYPES.
    confidence is a float in [0, 1] (best-effort; model-reported).

    Non-fatal throughout: any failure returns [] and logs a warning. This
    mirrors the discipline of the rest of Step 5.5 enrichment.
    """
    if not doc_url or not subject_company:
        return []

    text = _fetch_document_text(doc_url, max_chars=max_chars * 4)
    if not text:
        logger.warning("Counterparty extraction: no text fetched from %s", doc_url)
        return []

    snippet = text[:max_chars]

    system = (
        "You read SEC filing text and identify counterparties to agreements. "
        "You answer only with a JSON array, no prose, no code fences."
    )
    user = (
        "This is an excerpt from an SEC filing by "
        f"\"{subject_company}\". Identify other companies that are parties to "
        "an agreement with them (a license, acquisition, joint venture, supply "
        "deal, or partnership). Do NOT include the subject company itself. Do "
        "NOT include law firms, auditors, underwriters, banks acting only as "
        "financial intermediaries, or government agencies unless they are an "
        "actual counterparty to a business agreement.\n\n"
        "Return a JSON array. Each element:\n"
        '  {"name": str, "ticker": str or null, '
        '"relationship_type": one of '
        '["acquisition","license","joint_venture","supply","partnership","other"], '
        '"confidence": number between 0 and 1}\n'
        "confidence reflects how clearly the text supports both the company "
        "AND the relationship type. If no counterparties are present, return [].\n\n"
        "FILING EXCERPT:\n"
        f"{snippet}"
    )

    if client is None:
        try:
            client = _get_anthropic_client()
        except Exception as e:
            logger.warning("Counterparty extraction: no Anthropic client: %s", e)
            return []

    mdl = model or _counterparty_model()
    try:
        response = client.messages.create(
            model=mdl,
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = response.content[0].text.strip()
    except Exception as e:
        logger.warning("Counterparty extraction call failed (%s): %s", doc_url, e)
        return []

    parsed = _extract_json_array(raw)
    out = []
    subj_low = subject_company.strip().lower()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        if name.lower() == subj_low:
            continue  # never list the subject as its own counterparty
        rel = (item.get("relationship_type") or "other").strip().lower()
        if rel not in _VALID_REL_TYPES:
            rel = "other"
        ticker = item.get("ticker")
        if isinstance(ticker, str):
            ticker = ticker.strip().upper() or None
        else:
            ticker = None
        try:
            conf = float(item.get("confidence"))
            if conf < 0.0:
                conf = 0.0
            elif conf > 1.0:
                conf = 1.0
        except (TypeError, ValueError):
            conf = 0.0
        out.append({
            "name": name,
            "ticker": ticker,
            "relationship_type": rel,
            "confidence": round(conf, 2),
            "source_url": doc_url,
            "derived_from": "licensing-phrase match (approximate)",
        })
    return out


def deepen_counterparties(entities: list, max_filings_per_company: int = 3,
                          client=None, model: str = None) -> dict:
    """
    Explicitly-triggered "deepen counterparties" pass over the enriched company
    objects of a single thesis ring (or a flat list of company objects).

    For each company object that carries licensing_hits, read up to
    max_filings_per_company of those filings, extract counterparties, dedup by
    (name, relationship_type), and write the merged list onto a new
    "counterparties" field on that company object (mutated in place).

    entities: a list of company-object dicts. Each may carry:
                - "verified_name" or "name"     (subject company label)
                - "licensing_hits"              (list of {index_url, ...})
    Returns a summary dict: {companies_processed, filings_read,
                             counterparties_found}.

    One Anthropic client is built once and reused across all calls. Wholly
    non-fatal: a failure on one company does not abort the rest.
    """
    if not entities:
        return {"companies_processed": 0, "filings_read": 0,
                "counterparties_found": 0}

    if client is None:
        try:
            client = _get_anthropic_client()
        except Exception as e:
            logger.warning("deepen_counterparties: no Anthropic client: %s", e)
            return {"companies_processed": 0, "filings_read": 0,
                    "counterparties_found": 0, "error": str(e)}

    mdl = model or _counterparty_model()
    companies_processed = 0
    filings_read = 0
    counterparties_found = 0

    for comp in entities:
        if not isinstance(comp, dict):
            continue
        subject = (comp.get("verified_name") or comp.get("name") or "").strip()
        hits = comp.get("licensing_hits") or []
        if not subject or not hits:
            continue

        merged = {}
        used = 0
        for hit in hits:
            if used >= max_filings_per_company:
                break
            url = ""
            if isinstance(hit, dict):
                url = hit.get("index_url") or hit.get("doc_url") or ""
            if not url:
                continue
            used += 1
            filings_read += 1
            try:
                found = extract_counterparties(url, subject,
                                               client=client, model=mdl)
            except Exception as e:
                logger.warning("deepen_counterparties: %s on %s failed: %s",
                               subject, url, e)
                found = []
            for cp in found:
                key = (cp["name"].lower(), cp["relationship_type"])
                prior = merged.get(key)
                # Keep the higher-confidence instance of a duplicate.
                if prior is None or cp["confidence"] > prior["confidence"]:
                    merged[key] = cp

        comp["counterparties"] = sorted(
            merged.values(),
            key=lambda c: c["confidence"],
            reverse=True,
        )
        counterparties_found += len(comp["counterparties"])
        companies_processed += 1

    return {
        "companies_processed": companies_processed,
        "filings_read": filings_read,
        "counterparties_found": counterparties_found,
    }


'''


def main():
    if not os.path.exists(TARGET):
        print("ERROR: %s not found. Run from the project root "
              "(C:\\Projects\\horizon-scanner)." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Already patched (sentinel present). No changes made.")
        return

    count = src.count(ANCHOR)
    if count != 1:
        print("ERROR: expected exactly 1 anchor match, found %d. Aborting "
              "without writing. (The self-test section header may have changed.)"
              % count)
        sys.exit(2)

    patched = src.replace(ANCHOR, NEW_BLOCK + ANCHOR, 1)

    # Validate: parses cleanly and is ASCII-only.
    try:
        ast.parse(patched)
    except SyntaxError as e:
        print("ERROR: patched source does not parse: %s. Aborting." % e)
        sys.exit(3)

    try:
        patched.encode("ascii")
    except UnicodeEncodeError as e:
        print("ERROR: patched source is not pure ASCII: %s. Aborting." % e)
        sys.exit(4)

    with io.open(TARGET, "w", encoding="utf-8", newline="\n") as f:
        f.write(patched)

    print("Patched %s" % TARGET)
    print("Added: extract_counterparties(), deepen_counterparties(), helpers.")


if __name__ == "__main__":
    main()
