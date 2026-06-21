"""
horizon_scanner/enrichment/edgar_client.py

SEC EDGAR client for L3 entity enrichment.

This is a STANDALONE, read-only client. It does not touch the thesis loop yet;
it's the lower layer that the L3 entity-mapping step will call later. Built so
it can be tested on its own (EDGAR needs no API key).

What it does:
  - Resolve a company name or ticker to a CIK (SEC's company identifier)
  - List a company's recent filings (10-K, 10-Q, 8-K, etc.)
  - Pull the Intellectual Property section text from the latest 10-K
  - Full-text search filings for licensing / patent language

What it deliberately does NOT do:
  - Judge or synthesize. It returns raw filing text and metadata. The LLM in
    the thesis loop does the reasoning. This keeps the client dumb and testable.

SEC API facts (verified 2026):
  - No API key. REQUIRES a User-Agent header with name + email, or you get 403.
  - Rate limit: 10 requests/second across all SEC endpoints. Exceeding it gets
    a ~10-minute IP block. This client self-throttles conservatively.
  - Base hosts:
      data.sec.gov         -> submissions, company facts
      www.sec.gov          -> company_tickers.json, filing archives
      efts.sec.gov/LATEST  -> full-text search

CONFIG:
  Set your contact string in config.yaml under enrichment.edgar.user_agent,
  e.g. "HorizonScanner research (you@example.com)". The SEC asks for a real
  contact so they can reach you if your usage causes problems. A generic
  string works but a real email is the courteous (and policy-compliant) choice.
"""

import logging
import re
import time
import threading
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
FULLTEXT_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"

DEFAULT_USER_AGENT = "HorizonScanner research (contact-not-set@example.com)"


# ---------------------------------------------------------------------------
# Rate limiter (process-wide, conservative)
# ---------------------------------------------------------------------------
# SEC allows 10 req/s. We cap well under that to be safe across threads.

class _RateLimiter:
    def __init__(self, min_interval=0.34):
        self._min_interval = min_interval     # 5 req/s max, half the limit
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


_RATE = _RateLimiter()


# ---------------------------------------------------------------------------
# Config / headers
# ---------------------------------------------------------------------------

def _user_agent() -> str:
    try:
        from ..config import get_config
        cfg = get_config()
        ua = (cfg.get("enrichment", {}).get("edgar", {}).get("user_agent") or "").strip()
        if ua:
            return ua
    except Exception:
        pass
    return DEFAULT_USER_AGENT


def _headers(json_accept=True) -> dict:
    h = {"User-Agent": _user_agent()}
    if json_accept:
        h["Accept"] = "application/json"
    return h


# ---------------------------------------------------------------------------
# Low-level GET with rate limiting + light retry
# ---------------------------------------------------------------------------

def _get(url, params=None, json_accept=True, max_retries=4, timeout=30):
    """Rate-limited GET. Returns requests.Response or None on hard failure."""
    for attempt in range(1, max_retries + 1):
        _RATE.wait()
        try:
            resp = requests.get(url, params=params, headers=_headers(json_accept),
                                timeout=timeout)
        except requests.RequestException as e:
            logger.warning("EDGAR GET error (%s), attempt %d: %s", url, attempt, e)
            time.sleep(1.0 * attempt)
            continue

        if resp.status_code == 200:
            return resp
        if resp.status_code == 429:
            # Rate-limited; back off harder
            wait = 2.0 * attempt
            logger.warning("EDGAR 429 rate-limit; backing off %.1fs.", wait)
            time.sleep(wait)
            continue
        if resp.status_code == 403:
            logger.error("EDGAR 403 Forbidden -- check the User-Agent header is set "
                         "(enrichment.edgar.user_agent in config.yaml).")
            return None
        if resp.status_code == 404:
            return None  # legitimately not found; caller handles
        if resp.status_code in (500, 502, 503, 504):
            # EFTS throws transient 5xx under rapid sequential queries.
            # Back off and retry rather than giving up.
            wait = 1.5 * attempt
            logger.warning("EDGAR HTTP %d (transient); backing off %.1fs (attempt %d/%d).",
                           resp.status_code, wait, attempt, max_retries)
            time.sleep(wait)
            continue
        logger.warning("EDGAR HTTP %d for %s", resp.status_code, url)
        time.sleep(0.5 * attempt)
    return None


# ---------------------------------------------------------------------------
# CIK resolution
# ---------------------------------------------------------------------------

_TICKER_CACHE = {"data": None, "fetched_at": 0.0}
_TICKER_CACHE_TTL = 24 * 3600  # refresh the ticker map once a day


def _load_ticker_map() -> dict:
    """
    Load and cache company_tickers.json. Returns a dict keyed by uppercase
    ticker -> {cik_str, title}. Also usable for name matching.
    """
    now = time.time()
    if (_TICKER_CACHE["data"] is not None
            and now - _TICKER_CACHE["fetched_at"] < _TICKER_CACHE_TTL):
        return _TICKER_CACHE["data"]

    resp = _get(TICKERS_URL)
    if not resp:
        return _TICKER_CACHE["data"] or {}
    try:
        raw = resp.json()
    except ValueError:
        logger.error("EDGAR ticker map was not valid JSON.")
        return _TICKER_CACHE["data"] or {}

    # raw is keyed by arbitrary index -> {cik_str, ticker, title}
    by_ticker = {}
    for _, row in raw.items():
        ticker = (row.get("ticker") or "").upper()
        if ticker:
            by_ticker[ticker] = {
                "cik": int(row.get("cik_str")),
                "title": row.get("title", ""),
            }
    _TICKER_CACHE["data"] = by_ticker
    _TICKER_CACHE["fetched_at"] = now
    logger.info("EDGAR ticker map loaded: %d tickers.", len(by_ticker))
    return by_ticker


def resolve_cik(ticker_or_name: str) -> dict:
    """
    Resolve a ticker or company name to {cik, title, ticker}.
    Ticker match is exact (fast). Name match is a case-insensitive substring
    search over company titles (best-effort). Returns {} if nothing found.
    """
    if not ticker_or_name:
        return {}
    q = ticker_or_name.strip()
    tmap = _load_ticker_map()
    if not tmap:
        return {}

    # 1. Exact ticker match
    up = q.upper()
    if up in tmap:
        return {"cik": tmap[up]["cik"], "title": tmap[up]["title"], "ticker": up}

    # 2. Name substring match (return the shortest title that contains the query,
    #    which tends to be the parent company rather than a subsidiary)
    ql = q.lower()
    candidates = [
        {"cik": v["cik"], "title": v["title"], "ticker": t}
        for t, v in tmap.items()
        if ql in v["title"].lower()
    ]
    if candidates:
        candidates.sort(key=lambda c: len(c["title"]))
        return candidates[0]

    return {}


def _cik10(cik: int) -> str:
    return str(int(cik)).zfill(10)


# ---------------------------------------------------------------------------
# Filing list
# ---------------------------------------------------------------------------

def get_recent_filings(cik: int, forms=None, limit: int = 20) -> list:
    """
    List a company's recent filings. forms is an optional list like
    ["10-K", "8-K"] to filter. Returns a list of dicts with form, filing_date,
    accession, primary_doc, and a direct document URL.
    """
    url = SUBMISSIONS_URL.format(cik10=_cik10(cik))
    resp = _get(url)
    if not resp:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms_list = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    primary_desc = recent.get("primaryDocDescription", [])

    wanted = set(f.upper() for f in forms) if forms else None
    out = []
    for i in range(len(forms_list)):
        form = forms_list[i]
        if wanted and form.upper() not in wanted:
            continue
        accession = accessions[i] if i < len(accessions) else ""
        accession_nodash = accession.replace("-", "")
        doc = primary_docs[i] if i < len(primary_docs) else ""
        doc_url = ""
        if accession_nodash and doc:
            doc_url = ARCHIVE_DOC_URL.format(
                cik=int(cik), accession_nodash=accession_nodash, doc=doc
            )
        out.append({
            "form": form,
            "filing_date": dates[i] if i < len(dates) else "",
            "accession": accession,
            "primary_doc": doc,
            "description": primary_desc[i] if i < len(primary_desc) else "",
            "doc_url": doc_url,
        })
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Document fetch + IP section extraction
# ---------------------------------------------------------------------------

def _fetch_document_text(doc_url: str, max_chars: int = 400_000) -> str:
    """Fetch a filing document (HTML) and strip tags to plain text."""
    if not doc_url:
        return ""
    resp = _get(doc_url, json_accept=False)
    if not resp:
        return ""
    html = resp.text[:max_chars]
    # Crude tag strip -- good enough to locate sections and feed an LLM.
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# Patterns that mark the start of an IP discussion in a 10-K
_IP_HEADINGS = [
    "intellectual property",
    "patents and trademarks",
    "patents, trademarks",
    "proprietary rights",
    "patents and proprietary",
]


def get_ip_section(cik: int, max_chars: int = 6000) -> dict:
    """
    Pull the Intellectual Property discussion from the company's latest 10-K.
    Returns {found, filing_date, doc_url, text}. text is a window starting at
    the IP heading, capped at max_chars. Best-effort: 10-K formatting varies.
    """
    filings = get_recent_filings(cik, forms=["10-K"], limit=1)
    if not filings:
        return {"found": False, "text": "", "doc_url": "", "filing_date": ""}

    f = filings[0]
    full = _fetch_document_text(f["doc_url"])
    if not full:
        return {"found": False, "text": "", "doc_url": f["doc_url"],
                "filing_date": f["filing_date"]}

    low = full.lower()
    start = -1
    for heading in _IP_HEADINGS:
        idx = low.find(heading)
        if idx != -1:
            start = idx
            break

    if start == -1:
        return {"found": False, "text": "", "doc_url": f["doc_url"],
                "filing_date": f["filing_date"]}

    section = full[start:start + max_chars]
    return {
        "found": True,
        "filing_date": f["filing_date"],
        "doc_url": f["doc_url"],
        "text": section,
    }


# ---------------------------------------------------------------------------
# Full-text search (licensing / patent language)
# ---------------------------------------------------------------------------

def fulltext_search(query: str, forms=None, cik: int = None,
                    date_from: str = None, date_to: str = None,
                    size: int = 10) -> list:
    """
    Search inside filing text via efts.sec.gov. Returns a list of filing hits
    with form, entity, filing_date, accession, and a filing-index URL.

    query: phrase or boolean expression (wrap exact phrases in quotes upstream).
    forms: optional list, e.g. ["8-K", "10-K"].
    cik:   optional, restrict to one company.
    """
    params = {"q": query, "from": 0, "sort": "desc"}
    if forms:
        params["forms"] = ",".join(forms)
    if cik:
        params["ciks"] = _cik10(cik)
    if date_from:
        params["startdt"] = date_from
    if date_to:
        params["enddt"] = date_to

    resp = _get(FULLTEXT_URL, params=params)
    if not resp:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []

    hits = data.get("hits", {}).get("hits", [])
    out = []
    for h in hits[:size]:
        src = h.get("_source", {})
        _id = h.get("_id", "")
        accession = _id.split(":")[0] if ":" in _id else _id
        ciks = src.get("ciks", [])
        first_cik = ciks[0] if ciks else ""
        index_url = ""
        if accession and first_cik:
            acc_nodash = accession.replace("-", "")
            index_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(first_cik)}/{acc_nodash}/{accession}-index.htm"
            )
        # EFTS _source field naming varies; pick the first present form key.
        form_val = ""
        for _k in ("file_type", "form_type", "root_form"):
            _v = src.get(_k)
            if _v:
                form_val = _v
                break
        if not form_val:
            _forms = src.get("forms")
            if isinstance(_forms, list) and _forms:
                form_val = _forms[0]
            elif isinstance(_forms, str):
                form_val = _forms
        out.append({
            "form": form_val,
            "entity": (src.get("display_names") or [src.get("entity_name", "")])[0]
                      if isinstance(src.get("display_names"), list)
                      else src.get("entity_name", ""),
            "filing_date": src.get("file_date", ""),
            "accession": accession,
            "index_url": index_url,
        })
    return out


def find_licensing_mentions(company: str, lookback_years: int = 2) -> dict:
    """
    Convenience method for the L3 layer: given a company name or ticker, find
    filings that mention licensing of its technology. Returns structured hits
    plus the resolved company identity. Does NOT interpret -- the LLM does that.
    """
    ident = resolve_cik(company)
    if not ident:
        return {"resolved": False, "company": company, "hits": []}

    cik = ident["cik"]
    year = datetime.now(timezone.utc).year
    date_from = f"{year - lookback_years}-01-01"

    # Search this company's own filings for licensing language.
    # Accuracy over speed: run several reliable single-phrase queries and merge.
    # A single quoted phrase per call is reliable; an OR-chain trips EFTS on
    # encoding. Sequential clean queries catch wording variants a single phrase
    # would miss. Recency sort + forms filter handled in fulltext_search.
    licensing_phrases = [
        '"license agreement"',
        '"licensing agreement"',
        '"patent license"',
        '"technology license"',
        '"cross license"',
        '"licensing arrangement"',
    ]
    merged = {}
    for phrase in licensing_phrases:
        try:
            phrase_hits = fulltext_search(
                query=phrase,
                cik=cik,
                forms=["10-K", "10-Q", "8-K"],
                date_from=date_from,
                size=10,
            )
        except Exception as e:
            logger.warning("EDGAR licensing phrase %s failed: %s", phrase, e)
            phrase_hits = []
        for h in phrase_hits:
            key = h.get("accession") or (h.get("index_url") or "")
            if not key:
                continue
            if key not in merged:
                h["matched_phrase"] = phrase.strip('"')
                merged[key] = h
    # Sort merged hits newest-first by filing_date
    hits = sorted(
        merged.values(),
        key=lambda x: x.get("filing_date", ""),
        reverse=True,
    )
    return {
        "resolved": True,
        "company": ident["title"],
        "ticker": ident.get("ticker", ""),
        "cik": cik,
        "hits": hits,
    }


# ---------------------------------------------------------------------------
# Self-test (run standalone; no API key needed)
# ---------------------------------------------------------------------------

def selftest():
    """
    Manual smoke test. Run:
        python -m horizon_scanner.enrichment.edgar_client
    Exercises CIK resolution, filing list, IP section, and full-text search
    against a known company (Apple) so you can see real EDGAR data flow.
    """
    print("=== EDGAR client self-test ===")
    print(f"User-Agent: {_user_agent()}")
    if "not-set" in _user_agent():
        print("WARNING: set enrichment.edgar.user_agent in config.yaml to a real "
              "contact. Tests may still work but it's SEC policy to identify yourself.")

    print("\n[1] Resolve 'AAPL' ...")
    ident = resolve_cik("AAPL")
    print(f"    -> {ident}")
    if not ident:
        print("    CIK resolution failed; aborting (check network / User-Agent).")
        return

    cik = ident["cik"]
    print("\n[2] Recent 10-K and 8-K filings ...")
    filings = get_recent_filings(cik, forms=["10-K", "8-K"], limit=5)
    for f in filings:
        print(f"    {f['form']:6} {f['filing_date']}  {f['doc_url']}")

    print("\n[3] IP section from latest 10-K ...")
    ip = get_ip_section(cik, max_chars=600)
    print(f"    found={ip['found']}  date={ip['filing_date']}")
    if ip["found"]:
        print(f"    excerpt: {ip['text'][:300]}...")

    print("\n[4] Full-text search: 'license agreement' in Apple filings ...")
    res = find_licensing_mentions("AAPL")
    print(f"    resolved={res['resolved']} company={res.get('company')}")
    for h in res.get("hits", [])[:5]:
        print(f"    {h['form']:6} {h['filing_date']}  {h['entity']}")

    print("\n=== self-test complete ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    selftest()
