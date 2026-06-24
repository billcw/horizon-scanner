"""
Targeted probe: tests exactly what the dashboard sends vs the working probe.
Logs the full request body for each call so we can see precisely what is transmitted.
"""
import os, json, requests
from datetime import datetime, timezone, timedelta

SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"
key = os.environ.get("USPTO_ODP_KEY", "").strip()
if not key:
    print("ERROR: USPTO_ODP_KEY not set.")
    raise SystemExit(1)

headers = {
    "x-api-key": key,
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "HorizonScanner/1.0 (research tool)",
}

def post(label, body):
    print(f"\n--- {label} ---")
    print(f"BODY: {json.dumps(body)}")
    resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=30)
    data = resp.json() if resp.status_code == 200 else {}
    count = len(data.get("patentFileWrapperDataBag") or [])
    total = data.get("count", "?")
    print(f"HTTP {resp.status_code}  hits={count}  total={total}")
    if resp.status_code != 200:
        print(f"  {resp.text[:200]}")
    elif count:
        title = (data["patentFileWrapperDataBag"][0]
                 .get("applicationMetaData", {})
                 .get("inventionTitle", "(no title)"))
        print(f"  first: {title}")

# Reproduce exactly what the dashboard sends
to_dt   = datetime.now(timezone.utc).date()
from_30 = (to_dt - timedelta(days=30)).isoformat()
from_90 = (to_dt - timedelta(days=90)).isoformat()
to_str  = to_dt.isoformat()

keyword = "solid state battery"

# Exact dashboard body (30-day window)
post("A: dashboard exact (30d, quoted phrase)", {
    "q": f'"{keyword}"',
    "rangeFilters": [{"field": "applicationMetaData.filingDate",
                      "valueFrom": from_30, "valueTo": to_str}],
    "sort": [{"field": "applicationMetaData.filingDate", "order": "desc"}],
    "fields": ["applicationNumberText",
               "applicationMetaData.inventionTitle",
               "applicationMetaData.filingDate",
               "applicationMetaData.firstApplicantName",
               "applicationMetaData.applicantBag",
               "applicationMetaData.firstInventorName",
               "applicationMetaData.applicationTypeLabelName"],
    "pagination": {"offset": 0, "limit": 25},
})

# Same but 90d
post("B: 90-day window, quoted phrase", {
    "q": f'"{keyword}"',
    "rangeFilters": [{"field": "applicationMetaData.filingDate",
                      "valueFrom": from_90, "valueTo": to_str}],
    "pagination": {"offset": 0, "limit": 25},
})

# No range filter at all
post("C: no range filter, quoted phrase", {
    "q": f'"{keyword}"',
    "pagination": {"offset": 0, "limit": 25},
})

# Drop the fields list (maybe a bad field name causes 404?)
post("D: 30d, quoted phrase, NO fields list", {
    "q": f'"{keyword}"',
    "rangeFilters": [{"field": "applicationMetaData.filingDate",
                      "valueFrom": from_30, "valueTo": to_str}],
    "pagination": {"offset": 0, "limit": 25},
})

# Try "AI infrastructure" too
post("E: 30d, AI infrastructure", {
    "q": '"AI infrastructure"',
    "rangeFilters": [{"field": "applicationMetaData.filingDate",
                      "valueFrom": from_30, "valueTo": to_str}],
    "pagination": {"offset": 0, "limit": 25},
})
