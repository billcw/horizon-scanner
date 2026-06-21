"""
collectors/uspto_collector.py

Pulls recent patent applications from the USPTO Open Data Portal (ODP).

Endpoint:  POST https://api.uspto.gov/api/v1/patent/applications/search
Auth:      x-api-key header. Key read from the USPTO_ODP_KEY environment
           variable (set it as a Windows environment variable, same pattern
           as ANTHR_HORIZON / PERPLEX_HORIZON).

The legacy developer.uspto.gov/ibd-api endpoint was decommissioned 2026-06-05;
this collector targets the current ODP API.

QUERY STRATEGY (keyword-first):
  The ODP search 'q' parameter does free-form / simple-query-string search over
  bibliographic fields (invention title, abstract text, applicant, etc.). The
  documented field set does NOT clearly expose CPC classification as a search
  field, so this collector defaults to KEYWORD mode: it searches technology
  keywords against the invention-title field, which is fully documented and
  certain to return results.

  A CPC mode is included but OFF by default. It attempts a CPC classification
  filter using the most likely field name; if that errors or returns nothing,
  it logs a warning. Validate the exact CPC field with a live test call before
  relying on CPC mode (see verify_cpc_field() helper at the bottom).

SOURCES:
  Keywords are read from the collector_sources library (source_type='uspto',
  one keyword phrase per row), falling back to config.yaml collectors.uspto
  if the library has no uspto rows. This mirrors arxiv/reddit/trends.

RATE LIMITS (important):
  ODP returns HTTP 429 on rate-limit. Worse, exceeding the download quota
  triggers a SEVEN DAY lockout from first key use. This collector is therefore
  deliberately conservative:
    - small page size, capped total pages per run
    - capped total requests per run (hard ceiling)
    - exponential backoff on 429, then abort the run cleanly
  Tune the caps in config.yaml once you know your real quota.
"""

import hashlib
import logging
import os
import time
from datetime import datetime, timezone

import requests

from ..config import get_config
from ..database import insert_signal, get_enabled_source_values

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"
API_KEY_ENV = "USPTO_ODP_KEY"

# The field we search keywords against (documented, reliable).
TITLE_FIELD = "applicationMetaData.inventionTitle"

# Candidate CPC field names to try in CPC mode. The first that returns a
# non-error, non-empty result wins. Update once verified with a live call.
CPC_FIELD_CANDIDATES = [
    "applicationMetaData.cpcClassificationBag",
    "applicationMetaData.cpcClassification",
]

# Conservative defaults; overridable from config.yaml collectors.uspto
DEFAULT_PAGE_LIMIT = 25          # records per page (ODP default is 25)
DEFAULT_MAX_PAGES = 4            # pages per keyword per run
DEFAULT_MAX_REQUESTS = 40        # hard ceiling on total HTTP calls per run
DEFAULT_LOOKBACK_DAYS = 30       # only applications filed in the last N days
DEFAULT_BACKOFF_BASE = 2.0       # seconds; exponential on 429
DEFAULT_MAX_RETRIES = 4          # 429 retries before aborting the run


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

def _resolve_keywords(uspto_cfg) -> list:
    """Prefer enabled keywords from the source library; fall back to config."""
    try:
        library = get_enabled_source_values("uspto")
    except Exception as e:
        logger.warning(f"Could not read source library, using config: {e}")
        library = []
    if library:
        return library
    # config fallback: collectors.uspto.keywords, else derive nothing
    return uspto_cfg.get("keywords", [])


def _resolve_cpc_codes(uspto_cfg) -> list:
    """CPC codes come from config.yaml (collectors.uspto.cpc_codes)."""
    return uspto_cfg.get("cpc_codes", [])


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    return key


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _lookback_range(days: int) -> tuple:
    """Return (from_date, to_date) ISO strings for a filing-date range filter."""
    from datetime import timedelta
    to_dt = datetime.now(timezone.utc).date()
    from_dt = to_dt - timedelta(days=days)
    return from_dt.isoformat(), to_dt.isoformat()


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------

def _build_keyword_body(keyword: str, offset: int, limit: int,
                        date_from: str, date_to: str) -> dict:
    """
    Keyword-mode POST body: search the phrase against the invention-title
    field, restricted to recently filed applications, newest first.
    """
    return {
        "q": f'{TITLE_FIELD}:"{keyword}"',
        "rangeFilters": [
            {
                "field": "applicationMetaData.filingDate",
                "valueFrom": date_from,
                "valueTo": date_to,
            }
        ],
        "sort": [
            {"field": "applicationMetaData.filingDate", "order": "desc"}
        ],
        "fields": [
            "applicationNumberText",
            "applicationMetaData.inventionTitle",
            "applicationMetaData.filingDate",
            "applicationMetaData.firstApplicantName",
            "applicationMetaData.applicantBag",
            "applicationMetaData.firstInventorName",
            "applicationMetaData.applicationTypeLabelName",
        ],
        "pagination": {"offset": offset, "limit": limit},
    }


def _build_cpc_body(cpc_field: str, cpc_code: str, offset: int, limit: int,
                    date_from: str, date_to: str) -> dict:
    """
    CPC-mode POST body (experimental). Filters on a CPC classification field.
    Field name is unverified; see CPC_FIELD_CANDIDATES.
    """
    return {
        "filters": [
            {"name": cpc_field, "value": [cpc_code]}
        ],
        "rangeFilters": [
            {
                "field": "applicationMetaData.filingDate",
                "valueFrom": date_from,
                "valueTo": date_to,
            }
        ],
        "sort": [
            {"field": "applicationMetaData.filingDate", "order": "desc"}
        ],
        "pagination": {"offset": offset, "limit": limit},
    }


# ---------------------------------------------------------------------------
# HTTP with 429-aware backoff
# ---------------------------------------------------------------------------

class QuotaAbort(Exception):
    """Raised to abort the whole run cleanly when rate-limited past retries."""
    pass


def _post_search(body: dict, api_key: str, max_retries: int,
                 backoff_base: float) -> dict:
    """
    POST to the search endpoint with 429-aware exponential backoff.
    Returns parsed JSON, or raises QuotaAbort if repeatedly rate-limited.
    """
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "HorizonScanner/1.0 (research tool)",
    }

    attempt = 0
    while True:
        try:
            resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=60)
        except requests.RequestException as e:
            logger.error(f"USPTO request error: {e}")
            return {}

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                logger.error("USPTO returned 200 but body was not JSON.")
                return {}

        if resp.status_code == 429:
            attempt += 1
            if attempt > max_retries:
                logger.error(
                    "USPTO 429 rate-limit persisted past %d retries. Aborting run "
                    "to protect the 7-day quota.", max_retries
                )
                raise QuotaAbort()
            wait = backoff_base ** attempt
            logger.warning("USPTO 429 rate-limit; backing off %.1fs (attempt %d/%d).",
                           wait, attempt, max_retries)
            time.sleep(wait)
            continue

        if resp.status_code in (401, 403):
            logger.error(
                "USPTO auth failed (HTTP %d). Check the %s environment variable "
                "and that your key/ID.me verification is active.",
                resp.status_code, API_KEY_ENV
            )
            raise QuotaAbort()

        # Any other status: log and give up on this request (not the whole run)
        logger.error("USPTO search HTTP %d: %s", resp.status_code, resp.text[:300])
        return {}


# ---------------------------------------------------------------------------
# Response -> signals
# ---------------------------------------------------------------------------

def _extract_records(payload: dict) -> list:
    """
    Pull the application records out of an ODP search response.
    The response wraps results in patentFileWrapperDataBag.
    """
    if not payload:
        return []
    return payload.get("patentFileWrapperDataBag", []) or []


def _store_record(rec: dict, query_label: str) -> bool:
    """
    Turn one ODP application record into a signal. Returns True if newly stored.
    """
    app_num = rec.get("applicationNumberText", "")
    meta = rec.get("applicationMetaData", {}) or {}

    title = (meta.get("inventionTitle") or "").strip()
    if not title:
        # Nothing useful to classify without a title; skip.
        return False

    applicant = meta.get("firstApplicantName") or ""
    inventor = meta.get("firstInventorName") or ""
    filing_date = meta.get("filingDate") or ""
    app_type = meta.get("applicationTypeLabelName") or ""

    # Pull ALL applicants from applicantBag. Co-applicants (multiple companies
    # on one filing) are a real partnership / joint-venture signal -- unlike
    # licensing, co-filing is publicly recorded. Each entry may carry the name
    # under one of a few keys depending on the record shape.
    applicants = []
    for a in (meta.get("applicantBag") or []):
        if isinstance(a, dict):
            name = (a.get("applicantNameText")
                    or a.get("nameText")
                    or a.get("name")
                    or "")
        else:
            name = str(a)
        name = (name or "").strip()
        if name and name not in applicants:
            applicants.append(name)
    # Ensure the firstApplicantName is represented even if the bag was empty
    if applicant and applicant not in applicants:
        applicants.insert(0, applicant)

    # USPTO front-page search does not return the abstract in this field set,
    # so content is the title plus applicant context. The classifier still has
    # the title + applicant(s) + query theme to work with.
    content_bits = [title]
    if applicants:
        if len(applicants) > 1:
            content_bits.append("Applicants: " + "; ".join(applicants))
        else:
            content_bits.append(f"Applicant: {applicants[0]}")
    elif applicant:
        content_bits.append(f"Applicant: {applicant}")
    if inventor:
        content_bits.append(f"Inventor: {inventor}")
    content = ". ".join(content_bits)

    url = (
        f"https://patents.google.com/?q={app_num}"
        if app_num else ""
    )

    content_hash = hashlib.sha256(
        f"uspto{app_num}{title}".encode()
    ).hexdigest()

    signal_id = insert_signal(
        source="uspto",
        content_hash=content_hash,
        title=title,
        content=content,
        url=url,
        author=applicant or inventor,
        published_at=filing_date,
        metadata={
            "application_number": app_num,
            "filing_date": filing_date,
            "application_type": app_type,
            "applicants": applicants,
            "co_filed": len(applicants) > 1,
            "query": query_label,
        },
    )
    return signal_id is not None


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run():
    """
    Collect recent patent applications from USPTO ODP and store new ones.
    Keyword-first. Returns the number of new signals stored.
    """
    cfg = get_config()
    uspto_cfg = cfg.get("collectors", {}).get("uspto", {})

    if not uspto_cfg.get("enabled", False):
        logger.info("USPTO collector disabled in config.")
        return 0

    api_key = _get_api_key()
    if not api_key:
        logger.warning(
            "USPTO collector enabled but %s environment variable is not set. "
            "Skipping. (Set it after ID.me verification clears your API key.)",
            API_KEY_ENV
        )
        return 0

    # Tunables (conservative defaults)
    page_limit   = int(uspto_cfg.get("page_limit", DEFAULT_PAGE_LIMIT))
    max_pages    = int(uspto_cfg.get("max_pages_per_keyword", DEFAULT_MAX_PAGES))
    max_requests = int(uspto_cfg.get("max_requests_per_run", DEFAULT_MAX_REQUESTS))
    lookback     = int(uspto_cfg.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    backoff_base = float(uspto_cfg.get("backoff_base_seconds", DEFAULT_BACKOFF_BASE))
    max_retries  = int(uspto_cfg.get("max_retries", DEFAULT_MAX_RETRIES))
    mode         = (uspto_cfg.get("mode") or "keyword").lower()

    date_from, date_to = _lookback_range(lookback)

    total_new = 0
    request_count = 0

    try:
        if mode == "cpc":
            logger.info("USPTO collector running in CPC mode (experimental).")
            total_new, request_count = _run_cpc_mode(
                uspto_cfg, api_key, page_limit, max_pages, max_requests,
                date_from, date_to, backoff_base, max_retries
            )
        else:
            keywords = _resolve_keywords(uspto_cfg)
            if not keywords:
                logger.warning(
                    "USPTO keyword mode but no keywords configured. Add rows to the "
                    "source library (source_type='uspto') or collectors.uspto.keywords "
                    "in config.yaml."
                )
                return 0

            logger.info("USPTO collecting (keyword mode) for %d keywords: %s",
                        len(keywords), keywords)

            for kw in keywords:
                for page in range(max_pages):
                    if request_count >= max_requests:
                        logger.info("USPTO hit max_requests_per_run cap (%d).", max_requests)
                        raise StopIteration
                    offset = page * page_limit
                    body = _build_keyword_body(kw, offset, page_limit, date_from, date_to)
                    payload = _post_search(body, api_key, max_retries, backoff_base)
                    request_count += 1

                    records = _extract_records(payload)
                    if not records:
                        break  # no more results for this keyword

                    new_here = 0
                    for rec in records:
                        if _store_record(rec, query_label=kw):
                            new_here += 1
                    total_new += new_here
                    logger.info("USPTO [%s] page %d: %d records, %d new.",
                                kw, page, len(records), new_here)

                    if len(records) < page_limit:
                        break  # last page for this keyword

    except StopIteration:
        pass
    except QuotaAbort:
        logger.error("USPTO run aborted early due to rate-limit/auth. "
                     "Stored %d signals before aborting.", total_new)

    logger.info("USPTO collector complete. %d new signals stored (%d requests).",
                total_new, request_count)
    return total_new


def _run_cpc_mode(uspto_cfg, api_key, page_limit, max_pages, max_requests,
                  date_from, date_to, backoff_base, max_retries):
    """
    Experimental CPC-filter collection. Tries candidate CPC field names until
    one returns results. Returns (total_new, request_count).
    """
    cpc_codes = _resolve_cpc_codes(uspto_cfg)
    if not cpc_codes:
        logger.warning("USPTO CPC mode but no cpc_codes configured.")
        return 0, 0

    # Probe field names with the first code to find one that works.
    working_field = None
    request_count = 0
    for field in CPC_FIELD_CANDIDATES:
        if request_count >= max_requests:
            break
        body = _build_cpc_body(field, cpc_codes[0], 0, page_limit, date_from, date_to)
        payload = _post_search(body, api_key, max_retries, backoff_base)
        request_count += 1
        if _extract_records(payload):
            working_field = field
            logger.info("USPTO CPC field resolved to: %s", field)
            break
        else:
            logger.warning("USPTO CPC field '%s' returned nothing; trying next.", field)

    if not working_field:
        logger.error(
            "USPTO CPC mode could not resolve a working CPC field from candidates %s. "
            "Falling back is recommended: set collectors.uspto.mode='keyword'.",
            CPC_FIELD_CANDIDATES
        )
        return 0, request_count

    total_new = 0
    for code in cpc_codes:
        for page in range(max_pages):
            if request_count >= max_requests:
                logger.info("USPTO hit max_requests_per_run cap (%d).", max_requests)
                return total_new, request_count
            offset = page * page_limit
            body = _build_cpc_body(working_field, code, offset, page_limit,
                                   date_from, date_to)
            payload = _post_search(body, api_key, max_retries, backoff_base)
            request_count += 1

            records = _extract_records(payload)
            if not records:
                break
            new_here = 0
            for rec in records:
                if _store_record(rec, query_label=f"CPC:{code}"):
                    new_here += 1
            total_new += new_here
            logger.info("USPTO [CPC %s] page %d: %d records, %d new.",
                        code, page, len(records), new_here)
            if len(records) < page_limit:
                break

    return total_new, request_count


# ---------------------------------------------------------------------------
# One-shot verification helper (run manually once the key is live)
# ---------------------------------------------------------------------------

def verify_cpc_field():
    """
    Manual helper: run this once after your API key is active to discover the
    correct CPC field name. Prints which candidate (if any) returns results,
    and dumps the applicationMetaData keys of a sample record so you can see
    exactly what classification fields the API exposes.

    Usage:
        python -c "from horizon_scanner.collectors.uspto_collector import verify_cpc_field; verify_cpc_field()"
    """
    api_key = _get_api_key()
    if not api_key:
        print(f"{API_KEY_ENV} not set. Set it first.")
        return

    date_from, date_to = _lookback_range(90)

    # First, a known-good keyword call to confirm auth + see the record shape.
    print("=== Keyword probe (confirms auth + shows record fields) ===")
    body = _build_keyword_body("neural network", 0, 5, date_from, date_to)
    try:
        payload = _post_search(body, api_key, DEFAULT_MAX_RETRIES, DEFAULT_BACKOFF_BASE)
    except QuotaAbort:
        print("Auth or rate-limit problem on the keyword probe. Stop here.")
        return

    records = _extract_records(payload)
    print(f"Keyword probe returned {len(records)} records.")
    if records:
        meta = records[0].get("applicationMetaData", {})
        print("applicationMetaData keys on a sample record:")
        for k in sorted(meta.keys()):
            print(f"  - {k}")
        # Highlight anything classification-looking
        cls = [k for k in meta.keys() if "cpc" in k.lower() or "class" in k.lower()]
        if cls:
            print("\nClassification-looking fields found:")
            for k in cls:
                print(f"  * {k} = {meta.get(k)}")
        else:
            print("\nNo CPC/classification field on the front-page record set. "
                  "CPC filtering likely needs the bulk CPC Master Classification "
                  "files, not this search endpoint. Keyword mode is the right call.")

    print("\n=== CPC candidate probes ===")
    for field in CPC_FIELD_CANDIDATES:
        b = _build_cpc_body(field, "G06N", 0, 3, date_from, date_to)
        try:
            p = _post_search(b, api_key, DEFAULT_MAX_RETRIES, DEFAULT_BACKOFF_BASE)
        except QuotaAbort:
            print(f"  {field}: aborted (rate-limit/auth).")
            return
        n = len(_extract_records(p))
        print(f"  {field}: {n} records")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
