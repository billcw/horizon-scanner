"""
Quick diagnostic: tests several query forms against the USPTO ODP API
to find what syntax actually returns results.
Run from the project root with the venv active.
"""
import os, json, requests
from datetime import datetime, timezone, timedelta

API_KEY_ENV = "USPTO_ODP_KEY"
SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"

key = os.environ.get(API_KEY_ENV, "").strip()
if not key:
    print(f"ERROR: {API_KEY_ENV} not set.")
    raise SystemExit(1)

headers = {
    "x-api-key": key,
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "HorizonScanner/1.0 (research tool)",
}

to_dt   = datetime.now(timezone.utc).date().isoformat()
from_dt = (datetime.now(timezone.utc).date() - timedelta(days=365)).isoformat()

range_filter = [{"field": "applicationMetaData.filingDate",
                 "valueFrom": from_dt, "valueTo": to_dt}]

tests = [
    ("1. unquoted single word (probe style)",
     {"q": "quantum",
      "rangeFilters": range_filter,
      "pagination": {"offset": 0, "limit": 3}}),

    ("2. quoted single word",
     {"q": '"quantum"',
      "rangeFilters": range_filter,
      "pagination": {"offset": 0, "limit": 3}}),

    ("3. quoted multi-word phrase",
     {"q": '"solid state battery"',
      "rangeFilters": range_filter,
      "pagination": {"offset": 0, "limit": 3}}),

    ("4. unquoted multi-word (OR semantics)",
     {"q": "solid state battery",
      "rangeFilters": range_filter,
      "pagination": {"offset": 0, "limit": 3}}),

    ("5. AND multi-word",
     {"q": "solid AND state AND battery",
      "rangeFilters": range_filter,
      "pagination": {"offset": 0, "limit": 3}}),

    ("6. no range filter, quoted phrase",
     {"q": '"solid state battery"',
      "pagination": {"offset": 0, "limit": 3}}),

    ("7. no range filter, unquoted multi-word",
     {"q": "solid state battery",
      "pagination": {"offset": 0, "limit": 3}}),

    ("8. blank body (should return everything)",
     {"pagination": {"offset": 0, "limit": 1}}),
]

for label, body in tests:
    resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        count = len(data.get("patentFileWrapperDataBag") or [])
        total = data.get("count", "?")
        print(f"[{resp.status_code}] {label}")
        print(f"         hits={count}, total={total}")
        if count:
            title = (data["patentFileWrapperDataBag"][0]
                     .get("applicationMetaData", {})
                     .get("inventionTitle", "(no title)"))
            print(f"         first title: {title}")
    else:
        print(f"[{resp.status_code}] {label}")
        print(f"         {resp.text[:120]}")
    print()
