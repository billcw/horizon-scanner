"""
patch_counterparties_4.py

Idempotent fix: EFTS tells us the EXACT document its phrase matched (the part
of _id after the colon), but fulltext_search discarded it and downstream code
re-guessed the document by exhibit rank. This patch:

  1. fulltext_search(): parse the matched filename from _id, add "matched_doc"
     and "matched_doc_url" (a direct URL to that document) to each hit.
  2. deepen_counterparties(): prefer matched_doc_url (read the exact document
     EFTS matched) over index resolution; fall back to is_index resolution
     only when matched_doc_url is absent.

Run from project root:

    python patch_counterparties_4.py
"""

import ast
import io
import os
import sys

TARGET = os.path.join("horizon_scanner", "enrichment", "edgar_client.py")

SENTINEL = "# matched_doc_url support (patch_counterparties_4)"

# --- Change 1: in fulltext_search, capture matched filename + direct URL ----

OLD_ID = (
    "        src = h.get(\"_source\", {})\n"
    "        _id = h.get(\"_id\", \"\")\n"
    "        accession = _id.split(\":\")[0] if \":\" in _id else _id\n"
    "        ciks = src.get(\"ciks\", [])\n"
    "        first_cik = ciks[0] if ciks else \"\"\n"
    "        index_url = \"\"\n"
    "        if accession and first_cik:\n"
    "            acc_nodash = accession.replace(\"-\", \"\")\n"
    "            index_url = (\n"
    "                f\"https://www.sec.gov/Archives/edgar/data/\"\n"
    "                f\"{int(first_cik)}/{acc_nodash}/{accession}-index.htm\"\n"
    "            )\n"
)

NEW_ID = (
    "        src = h.get(\"_source\", {})\n"
    "        _id = h.get(\"_id\", \"\")\n"
    "        # matched_doc_url support (patch_counterparties_4)\n"
    "        # EFTS _id is 'accession:filename'; the filename is the EXACT\n"
    "        # document the phrase matched. Keep it -- do not re-guess later.\n"
    "        if \":\" in _id:\n"
    "            accession, matched_doc = _id.split(\":\", 1)\n"
    "        else:\n"
    "            accession, matched_doc = _id, \"\"\n"
    "        ciks = src.get(\"ciks\", [])\n"
    "        first_cik = ciks[0] if ciks else \"\"\n"
    "        index_url = \"\"\n"
    "        matched_doc_url = \"\"\n"
    "        if accession and first_cik:\n"
    "            acc_nodash = accession.replace(\"-\", \"\")\n"
    "            index_url = (\n"
    "                f\"https://www.sec.gov/Archives/edgar/data/\"\n"
    "                f\"{int(first_cik)}/{acc_nodash}/{accession}-index.htm\"\n"
    "            )\n"
    "            if matched_doc:\n"
    "                matched_doc_url = (\n"
    "                    f\"https://www.sec.gov/Archives/edgar/data/\"\n"
    "                    f\"{int(first_cik)}/{acc_nodash}/{matched_doc}\"\n"
    "                )\n"
)

# Add the two new fields to the appended hit dict.
OLD_APPEND = (
    "            \"accession\": accession,\n"
    "            \"index_url\": index_url,\n"
    "        })\n"
)
NEW_APPEND = (
    "            \"accession\": accession,\n"
    "            \"index_url\": index_url,\n"
    "            \"matched_doc\": matched_doc,\n"
    "            \"matched_doc_url\": matched_doc_url,\n"
    "        })\n"
)

# --- Change 2: deepen_counterparties prefers matched_doc_url ----------------

OLD_DEEPEN = (
    "            index_url = hit.get(\"index_url\") or hit.get(\"doc_url\") or \"\"\n"
    "            if not index_url:\n"
    "                continue\n"
    "            phrase = hit.get(\"matched_phrase\") or \"\"\n"
    "            used += 1\n"
    "            filings_read += 1\n"
    "            try:\n"
    "                found = extract_counterparties(\n"
    "                    index_url, subject,\n"
    "                    client=client, model=mdl,\n"
    "                    match_phrase=phrase,\n"
    "                    is_index=True,\n"
    "                    max_docs=max_docs_per_filing,\n"
    "                )\n"
)

NEW_DEEPEN = (
    "            # Prefer the exact document EFTS matched; fall back to index\n"
    "            # resolution only if we don't have it.\n"
    "            matched_doc_url = hit.get(\"matched_doc_url\") or \"\"\n"
    "            index_url = hit.get(\"index_url\") or hit.get(\"doc_url\") or \"\"\n"
    "            target = matched_doc_url or index_url\n"
    "            if not target:\n"
    "                continue\n"
    "            use_index = not matched_doc_url\n"
    "            phrase = hit.get(\"matched_phrase\") or \"\"\n"
    "            used += 1\n"
    "            filings_read += 1\n"
    "            try:\n"
    "                found = extract_counterparties(\n"
    "                    target, subject,\n"
    "                    client=client, model=mdl,\n"
    "                    match_phrase=phrase,\n"
    "                    is_index=use_index,\n"
    "                    max_docs=max_docs_per_filing,\n"
    "                )\n"
)


def main():
    if not os.path.exists(TARGET):
        print("ERROR: %s not found. Run from project root." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Already patched (sentinel present). No changes made.")
        return

    for label, old in (("id-parse", OLD_ID),
                       ("hit-append", OLD_APPEND),
                       ("deepen", OLD_DEEPEN)):
        if src.count(old) != 1:
            print("ERROR: anchor '%s' not found exactly once (found %d). "
                  "Aborting without writing." % (label, src.count(old)))
            sys.exit(2)

    patched = src
    patched = patched.replace(OLD_ID, NEW_ID, 1)
    patched = patched.replace(OLD_APPEND, NEW_APPEND, 1)
    patched = patched.replace(OLD_DEEPEN, NEW_DEEPEN, 1)

    try:
        ast.parse(patched)
    except SyntaxError as e:
        print("ERROR: patched source does not parse: %s. Aborting." % e)
        sys.exit(3)

    try:
        patched.encode("ascii")
    except UnicodeEncodeError as e:
        print("ERROR: not pure ASCII: %s. Aborting." % e)
        sys.exit(4)

    with io.open(TARGET, "w", encoding="utf-8", newline="\n") as f:
        f.write(patched)

    print("Patched %s." % TARGET)
    print("fulltext_search now carries matched_doc + matched_doc_url; "
          "deepen_counterparties reads the exact matched document.")


if __name__ == "__main__":
    main()
