"""
thesis/edgar_enrichment.py

L3 Step 5.5 -- EDGAR verification & enrichment.

Runs AFTER Step 5 (entity mapping) and BEFORE Step 6 (platform classification).
Takes the LLM-produced entity rings and grounds them against real SEC filings:

  - Ticker verification (cheap, all rings if enabled): confirm each company is
    real and publicly traded; correct near-miss tickers; flag private/unfindable.
  - Deep enrichment (expensive, configurable ring depth): for companies in the
    enriched rings, pull the latest 10-K IP-section excerpt and recent licensing
    mentions from full-text search.

Results are folded back into the company objects in state["entities"] so they
flow into Step 6 and get stored in the entities_ring* columns -- which is also
the data source for the future supply-line graph.

NON-FATAL: every EDGAR call is wrapped. If SEC is unreachable or a company is
not found, that company is flagged and the loop continues. A failure here never
breaks a thesis run.

Config (config.yaml -> thesis):
  edgar_verify_tickers: true            # cheap ticker-verify across all rings
  edgar_enrichment_depth: 1             # 0=off, 1=ring1, 2=rings1-2, 3=1-3, 4=all
  edgar_ip_excerpt_chars: 1500          # chars of IP section to keep per company
  edgar_max_companies: 30               # hard ceiling on companies enriched/run
"""

import logging

logger = logging.getLogger(__name__)

# Ring keys in the order Step 5 produces them
_RING_KEYS = ["ring1_direct", "ring2_enabling", "ring3_benefiting", "ring4_threatened"]


def _cfg(thesis_cfg, key, default):
    return thesis_cfg.get(key, default)


def _verify_one_ticker(company_obj, edgar):
    """
    Verify/correct a single company's ticker against EDGAR.
    Mutates company_obj in place, adding:
      cik, ticker_verified (bool), verified_name, ticker_corrected (bool)
    """
    name = (company_obj.get("company") or "").strip()
    claimed_ticker = (company_obj.get("ticker") or "").strip()

    # Try ticker first (most reliable), then company name
    ident = {}
    try:
        if claimed_ticker and claimed_ticker.lower() not in ("null", "none", "private", ""):
            ident = edgar.resolve_cik(claimed_ticker)
        if not ident and name:
            ident = edgar.resolve_cik(name)
    except Exception as e:
        logger.warning("EDGAR ticker verify error for %s: %s", name, e)
        ident = {}

    if ident:
        company_obj["cik"] = ident.get("cik")
        company_obj["verified_name"] = ident.get("title", "")
        resolved_ticker = ident.get("ticker", "")
        company_obj["ticker_verified"] = True
        # Note a correction if the resolved ticker differs from the claim
        if resolved_ticker and resolved_ticker.upper() != claimed_ticker.upper():
            company_obj["ticker_corrected"] = True
            company_obj["ticker_original"] = claimed_ticker
            company_obj["ticker"] = resolved_ticker
        else:
            company_obj["ticker_corrected"] = False
    else:
        company_obj["cik"] = None
        company_obj["ticker_verified"] = False
        company_obj["ticker_corrected"] = False
    return company_obj


def _deep_enrich_one(company_obj, edgar, ip_chars):
    """
    Deep-enrich a single company that has a verified CIK:
      - latest 10-K IP-section excerpt
      - recent licensing mentions
    Mutates company_obj in place, adding ip_summary, ip_filing_date,
    licensing_hits (list), edgar_enriched (bool).
    """
    cik = company_obj.get("cik")
    if not cik:
        company_obj["edgar_enriched"] = False
        return company_obj

    # IP section
    try:
        ip = edgar.get_ip_section(cik, max_chars=ip_chars)
        if ip.get("found"):
            company_obj["ip_summary"] = ip.get("text", "")[:ip_chars]
            company_obj["ip_filing_date"] = ip.get("filing_date", "")
            company_obj["ip_doc_url"] = ip.get("doc_url", "")
    except Exception as e:
        logger.warning("EDGAR IP-section error for CIK %s: %s", cik, e)

    # Licensing mentions
    try:
        lic = edgar.find_licensing_mentions(
            company_obj.get("ticker") or str(cik)
        )
        hits = lic.get("hits", []) if lic.get("resolved") else []
        # Keep a compact form: form, date, entity
        company_obj["licensing_hits"] = [
            {
                "form": h.get("form", ""),
                "filing_date": h.get("filing_date", ""),
                "index_url": h.get("index_url", ""),
            }
            for h in hits[:5]
        ]
    except Exception as e:
        logger.warning("EDGAR licensing error for CIK %s: %s", cik, e)
        company_obj["licensing_hits"] = []

    company_obj["edgar_enriched"] = True
    return company_obj


def run_edgar_enrichment(state, thesis_cfg):
    """
    Step 5.5 entry point. Mutates and returns state.

    state["entities"] is expected to have ring1_direct..ring4_threatened lists.
    Reads config from thesis_cfg. Wholly non-fatal.
    """
    verify = bool(_cfg(thesis_cfg, "edgar_verify_tickers", True))
    depth = int(_cfg(thesis_cfg, "edgar_enrichment_depth", 1))
    ip_chars = int(_cfg(thesis_cfg, "edgar_ip_excerpt_chars", 1500))
    max_companies = int(_cfg(thesis_cfg, "edgar_max_companies", 30))

    if not verify and depth <= 0:
        logger.info("Step 5.5: EDGAR enrichment disabled (verify off, depth 0). Skipping.")
        state.setdefault("edgar", {})["skipped"] = True
        return state

    # Import the client lazily so a missing module never breaks the loop
    try:
        from ..enrichment import edgar_client as edgar
    except Exception as e:
        logger.warning("Step 5.5: EDGAR client unavailable (%s). Skipping enrichment.", e)
        state.setdefault("edgar", {})["error"] = str(e)
        return state

    entities = state.get("entities", {})
    if not entities:
        logger.info("Step 5.5: no entities to enrich. Skipping.")
        return state

    verified_count = 0
    enriched_count = 0
    processed = 0

    for ring_index, ring_key in enumerate(_RING_KEYS):
        companies = entities.get(ring_key, [])
        if not isinstance(companies, list):
            continue

        # Deep enrichment applies only to rings within the configured depth.
        # depth=1 -> ring_index 0 ; depth=2 -> ring_index 0,1 ; etc.
        deep_this_ring = (ring_index < depth)

        for company in companies:
            if not isinstance(company, dict):
                continue
            if processed >= max_companies:
                logger.info("Step 5.5: hit edgar_max_companies cap (%d).", max_companies)
                break

            # Ticker verification (cheap) -- all rings if enabled
            if verify:
                _verify_one_ticker(company, edgar)
                if company.get("ticker_verified"):
                    verified_count += 1

            # Deep enrichment (expensive) -- only enriched rings, only if verified
            if deep_this_ring:
                # If verification is off, we still need a CIK; try a lookup.
                if not verify and not company.get("cik"):
                    _verify_one_ticker(company, edgar)
                if company.get("cik"):
                    _deep_enrich_one(company, edgar, ip_chars)
                    if company.get("edgar_enriched"):
                        enriched_count += 1

            processed += 1

        if processed >= max_companies:
            break

    state["entities"] = entities
    state.setdefault("edgar", {}).update({
        "verified_count": verified_count,
        "enriched_count": enriched_count,
        "depth": depth,
        "verify": verify,
    })
    logger.info("Step 5.5: EDGAR enrichment complete -- %d tickers verified, "
                "%d companies deep-enriched.", verified_count, enriched_count)
    return state
