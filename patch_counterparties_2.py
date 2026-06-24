"""
patch_counterparties_2.py

Second idempotent patch for
horizon_scanner/enrichment/edgar_client.py.

Depends on patch_counterparties.py having run first (it requires the
counterparty block to exist). This patch:

  1. Adds resolve_filing_documents(index_url) -> ranked list of real document
     URLs (exhibits first, graphics/xml dropped, /ix?doc= viewer wrapper
     stripped).
  2. Replaces extract_counterparties() with a version that:
       - accepts an optional match_phrase and centers a keyword-window on it
         (falls back to document opening if the phrase is not found),
       - accepts is_index=True to resolve an index_url to its best document(s)
         before reading.
  3. Replaces deepen_counterparties() to resolve each licensing hit's
     index_url to its best document and pass the hit's matched_phrase through.

Safe to run multiple times. Run from project root:

    python patch_counterparties_2.py
"""

import ast
import io
import os
import re
import sys

TARGET = os.path.join("horizon_scanner", "enrichment", "edgar_client.py")

SENTINEL_1 = "# === COUNTERPARTY EXTRACTION (patch_counterparties) ==="
SENTINEL_2 = "# === COUNTERPARTY EXTRACTION v2 (patch_counterparties_2) ==="

# We replace from the start of the v1 def extract_counterparties through the
# end of deepen_counterparties (i.e. everything from the first function
# signature down to the self-test header). Anchors:
START_ANCHOR = "_VALID_REL_TYPES = {"
END_ANCHOR = (
    "# ---------------------------------------------------------------------------\n"
    "# Self-test (run standalone; no API key needed)\n"
    "# ---------------------------------------------------------------------------"
)

REPLACEMENT = r'''# === COUNTERPARTY EXTRACTION v2 (patch_counterparties_2) ===
_VALID_REL_TYPES = {
    "acquisition", "license", "joint_venture",
    "supply", "partnership", "other",
}

# Documents we actually want to read, ranked. Material agreements (where a
# named counterparty to a license/acquisition actually appears) rank highest;
# the big financial exhibit (EX-13) and graphics rank lowest / are dropped.
_DOC_EXT_RE = re.compile(r"\.(htm|html|txt)$", re.I)

_INDEX_ROW_RE = re.compile(
    r"<tr[^>]*>\s*"
    r"<td[^>]*>\s*\d+\s*</td>\s*"                                   # Seq
    r"<td[^>]*>.*?</td>\s*"                                         # Description
    r"<td[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>.*?</a>\s*</td>\s*" # Document href
    r"<td[^>]*>\s*([^<]*?)\s*</td>\s*"                              # Type
    r"<td[^>]*>\s*(\d+)\s*</td>",                                   # Size
    re.I | re.S,
)


def _exhibit_rank(doc_type: str) -> int:
    t = (doc_type or "").upper()
    if t.startswith("EX-2"):
        return 0   # plan of acquisition / merger agreement
    if t.startswith("EX-10"):
        return 1   # material contracts -- licenses live here
    if t.startswith("EX-4"):
        return 2   # instruments defining security holders' rights
    if t.startswith("EX-99"):
        return 3   # additional exhibits (press releases, etc.)
    if t in ("10-K", "10-Q", "8-K"):
        return 5   # narrative body -- counterparty usually buried
    if t.startswith("EX-13"):
        return 6   # annual-report financials -- huge, low signal
    return 4


def _strip_ix_wrapper(href: str) -> str:
    """SEC wraps some doc links in the iXBRL viewer: /ix?doc=/Archives/...
    Strip the wrapper so we fetch the raw document."""
    if not href:
        return href
    m = re.search(r"[?&]doc=(/Archives/[^&]+)", href)
    if m:
        return m.group(1)
    return href


def resolve_filing_documents(index_url: str, limit: int = 4) -> list:
    """
    Given a filing index URL (the -index.htm page), return a ranked list of
    real document URLs to read. Exhibits that carry material agreements rank
    first; graphics and data files are dropped. Returns absolute URLs.

    Returns [] if the index cannot be fetched or parsed. Non-fatal.
    """
    if not index_url:
        return []
    resp = _get(index_url, json_accept=False)
    if not resp:
        return []
    html = resp.text

    rows = _INDEX_ROW_RE.findall(html)
    docs = []
    for href, dtype, size in rows:
        href = _strip_ix_wrapper(href.strip())
        if not _DOC_EXT_RE.search(href):
            continue  # drop .jpg/.xml/.json graphics + data
        try:
            size_i = int(size)
        except (TypeError, ValueError):
            size_i = 0
        docs.append({"href": href, "type": dtype.strip(), "size": size_i})

    if not docs:
        return []

    # Rank: best exhibit class first; within a class, smaller first (a focused
    # agreement beats a giant catch-all document).
    docs.sort(key=lambda d: (_exhibit_rank(d["type"]), d["size"]))

    base = "https://www.sec.gov"
    out = []
    for d in docs[:limit]:
        href = d["href"]
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = base + href
        else:
            url = base + "/" + href
        out.append(url)
    return out


def _window_around_phrase(text: str, phrase: str, radius: int = 3000) -> str:
    """
    Return a window of text centered on the first occurrence of phrase
    (case-insensitive). If phrase is empty or not found, return the opening
    of the document instead. radius is chars on EACH side.
    """
    if not text:
        return ""
    if phrase:
        idx = text.lower().find(phrase.lower())
        if idx != -1:
            start = max(0, idx - radius)
            end = min(len(text), idx + len(phrase) + radius)
            return text[start:end]
    # Fallback: document opening.
    return text[: radius * 2]


def extract_counterparties(doc_url: str, subject_company: str,
                           client=None, model: str = None,
                           match_phrase: str = "",
                           is_index: bool = False,
                           radius: int = 3000,
                           max_docs: int = 2) -> list:
    """
    Read SEC filing text and identify OTHER companies that are parties to an
    agreement with subject_company.

    doc_url:          a document URL, OR (if is_index=True) a filing index URL
                      which will be resolved to its best document(s) first.
    subject_company:  the filer whose filing this is.
    match_phrase:     the licensing phrase that matched this filing. If given,
                      extraction reads a keyword-window centered on it rather
                      than the document opening -- the counterparty is usually
                      near the phrase, not in the boilerplate intro.
    is_index:         if True, resolve doc_url (an -index.htm) to ranked
                      documents and read up to max_docs of them.
    radius:           keyword-window half-width in chars.
    client / model:   optional Anthropic client reuse / model override.

    Returns a list of {name, ticker, relationship_type, confidence,
    source_url, derived_from}. Non-fatal throughout: [] on any failure.
    """
    if not doc_url or not subject_company:
        return []

    # Resolve which document URL(s) to actually read.
    if is_index:
        doc_urls = resolve_filing_documents(doc_url, limit=max_docs)
        if not doc_urls:
            logger.warning("Counterparty extraction: index %s resolved to no "
                           "documents.", doc_url)
            return []
    else:
        doc_urls = [doc_url]

    if client is None:
        try:
            client = _get_anthropic_client()
        except Exception as e:
            logger.warning("Counterparty extraction: no Anthropic client: %s", e)
            return []

    mdl = model or _counterparty_model()
    subj_low = subject_company.strip().lower()
    merged = {}

    for url in doc_urls:
        full = _fetch_document_text(url, max_chars=400_000)
        if not full:
            continue
        snippet = _window_around_phrase(full, match_phrase, radius=radius)
        if not snippet:
            continue

        system = (
            "You read SEC filing text and identify counterparties to "
            "agreements. You answer only with a JSON array, no prose, no "
            "code fences."
        )
        user = (
            "This is an excerpt from an SEC filing by "
            f"\"{subject_company}\". Identify other companies that are parties "
            "to an agreement with them (a license, acquisition, joint venture, "
            "supply deal, or partnership). Do NOT include the subject company "
            "itself. Do NOT include law firms, auditors, underwriters, banks "
            "acting only as financial intermediaries, or government agencies "
            "unless they are an actual counterparty to a business agreement.\n\n"
            "Return a JSON array. Each element:\n"
            '  {"name": str, "ticker": str or null, '
            '"relationship_type": one of '
            '["acquisition","license","joint_venture","supply","partnership","other"], '
            '"confidence": number between 0 and 1}\n'
            "confidence reflects how clearly the text supports both the company "
            "AND the relationship type. If no counterparties are present, "
            "return [].\n\n"
            "FILING EXCERPT:\n"
            f"{snippet}"
        )

        try:
            response = client.messages.create(
                model=mdl,
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text.strip()
        except Exception as e:
            logger.warning("Counterparty extraction call failed (%s): %s", url, e)
            continue

        for item in _extract_json_array(raw):
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name or name.lower() == subj_low:
                continue
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
                conf = max(0.0, min(1.0, conf))
            except (TypeError, ValueError):
                conf = 0.0
            rec = {
                "name": name,
                "ticker": ticker,
                "relationship_type": rel,
                "confidence": round(conf, 2),
                "source_url": url,
                "derived_from": "licensing-phrase match (approximate)",
            }
            key = (name.lower(), rel)
            prior = merged.get(key)
            if prior is None or rec["confidence"] > prior["confidence"]:
                merged[key] = rec

    return sorted(merged.values(), key=lambda c: c["confidence"], reverse=True)


def deepen_counterparties(entities: list, max_filings_per_company: int = 3,
                          client=None, model: str = None,
                          max_docs_per_filing: int = 2) -> dict:
    """
    Explicitly-triggered "deepen counterparties" pass over the enriched company
    objects of a single thesis ring (or a flat list of company objects).

    For each company carrying licensing_hits, resolve up to
    max_filings_per_company of those hits' index pages to their best documents,
    extract counterparties from a keyword-window centered on each hit's
    matched_phrase, dedup by (name, relationship_type) keeping the higher
    confidence, and write the merged list onto a new "counterparties" field
    (mutated in place).

    Returns {companies_processed, filings_read, counterparties_found}.
    Wholly non-fatal: a failure on one company/filing does not abort the rest.
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
            if not isinstance(hit, dict):
                continue
            index_url = hit.get("index_url") or hit.get("doc_url") or ""
            if not index_url:
                continue
            phrase = hit.get("matched_phrase") or ""
            used += 1
            filings_read += 1
            try:
                found = extract_counterparties(
                    index_url, subject,
                    client=client, model=mdl,
                    match_phrase=phrase,
                    is_index=True,
                    max_docs=max_docs_per_filing,
                )
            except Exception as e:
                logger.warning("deepen_counterparties: %s on %s failed: %s",
                               subject, index_url, e)
                found = []
            for cp in found:
                key = (cp["name"].lower(), cp["relationship_type"])
                prior = merged.get(key)
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
        print("ERROR: %s not found. Run from the project root." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL_1 not in src:
        print("ERROR: v1 counterparty block not found. Run "
              "patch_counterparties.py first.")
        sys.exit(2)

    if SENTINEL_2 in src:
        print("Already patched to v2 (sentinel present). No changes made.")
        return

    start = src.find(START_ANCHOR)
    if start == -1:
        print("ERROR: start anchor not found. Aborting.")
        sys.exit(3)

    end = src.find(END_ANCHOR)
    if end == -1:
        print("ERROR: end anchor (self-test header) not found. Aborting.")
        sys.exit(4)

    if end <= start:
        print("ERROR: anchors out of order (end<=start). Aborting.")
        sys.exit(5)

    patched = src[:start] + REPLACEMENT + src[end:]

    try:
        ast.parse(patched)
    except SyntaxError as e:
        print("ERROR: patched source does not parse: %s. Aborting." % e)
        sys.exit(6)

    try:
        patched.encode("ascii")
    except UnicodeEncodeError as e:
        print("ERROR: patched source is not pure ASCII: %s. Aborting." % e)
        sys.exit(7)

    with io.open(TARGET, "w", encoding="utf-8", newline="\n") as f:
        f.write(patched)

    print("Patched %s to v2." % TARGET)
    print("Added: resolve_filing_documents(); keyword-window + index "
          "resolution in extract_counterparties(); matched_phrase threading "
          "in deepen_counterparties().")


if __name__ == "__main__":
    main()
