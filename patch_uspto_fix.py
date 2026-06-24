"""
patch_uspto_fix.py

Fixes the indentation-corrupted uspto_collector.py caused by the
patch_graph_readability.py probe insertion going wrong, then adds
the auth probe correctly.

Strategy: replace the entire api_key-not-set block plus the lines
immediately after with a clean version that includes the probe.

Run from C:\\Projects\\horizon-scanner:
    python patch_uspto_fix.py
"""

import os, sys

TARGET = os.path.join("horizon_scanner", "collectors", "uspto_collector.py")
SENTINEL = "# USPTO-AUTH-PROBE-OK"

# The clean block we want -- replaces whatever is currently there
# Anchor: unique line that precedes the broken area
ANCHOR = '    api_key = _get_api_key()\n    if not api_key:'

# Everything from the anchor through "return 0" and into the tunables,
# so we can rewrite it cleanly in one shot
OLD_BLOCK = (
    '    api_key = _get_api_key()\n'
    '    if not api_key:\n'
)

# We just need to find this block and insert the probe AFTER the return 0.
# Safer: replace the whole stanza from api_key through the first tunable line.

FULL_OLD = None  # will be found dynamically

NEW_BLOCK = (
    '    api_key = _get_api_key()\n'
    '    if not api_key:\n'
    '        logger.warning(\n'
    '            "USPTO collector enabled but %s environment variable is not set. "\n'
    '            "Skipping. Set it inline: $env:USPTO_ODP_KEY=your-key before "\n'
    '            "launching, or open a new PowerShell after setting the system var.",\n'
    '            API_KEY_ENV\n'
    '        )\n'
    '        return 0\n'
    '\n'
    '    # USPTO-AUTH-PROBE-OK\n'
    '    # One-record probe to confirm auth before a full run (uses 1 quota request).\n'
    '    logger.info("USPTO: probing auth with a 1-record test call...")\n'
    '    try:\n'
    '        from datetime import timedelta as _td\n'
    '        _to   = datetime.now(timezone.utc).date().isoformat()\n'
    '        _from = (datetime.now(timezone.utc).date() - _td(days=90)).isoformat()\n'
    '        _pb = {\n'
    '            "q": "applicationMetaData.inventionTitle:quantum",\n'
    '            "rangeFilters": [{"field": "applicationMetaData.filingDate",\n'
    '                              "valueFrom": _from, "valueTo": _to}],\n'
    '            "pagination": {"offset": 0, "limit": 1},\n'
    '        }\n'
    '        _ph = {\n'
    '            "x-api-key": api_key,\n'
    '            "Content-Type": "application/json",\n'
    '            "Accept": "application/json",\n'
    '            "User-Agent": "HorizonScanner/1.0 (research tool)",\n'
    '        }\n'
    '        _pr = requests.post(SEARCH_URL, json=_pb, headers=_ph, timeout=30)\n'
    '        if _pr.status_code == 200:\n'
    '            logger.info("USPTO auth OK (HTTP 200). Proceeding with collect.")\n'
    '        elif _pr.status_code in (401, 403):\n'
    '            logger.error(\n'
    '                "USPTO auth FAILED (HTTP %d). Key in %s is set but rejected. "\n'
    '                "Causes: ID.me verification pending, whitespace in key, or expired.",\n'
    '                _pr.status_code, API_KEY_ENV\n'
    '            )\n'
    '            return 0\n'
    '        else:\n'
    '            logger.warning("USPTO auth probe HTTP %d. Proceeding.", _pr.status_code)\n'
    '    except Exception as _pe:\n'
    '        logger.warning("USPTO auth probe exception: %s. Proceeding.", _pe)\n'
    '\n'
    '    # Tunables (conservative defaults)\n'
)

TUNABLES_ANCHOR = '    # Tunables (conservative defaults)\n'


def main():
    if not os.path.exists(TARGET):
        print("ERROR: {} not found. Run from project root.".format(TARGET))
        sys.exit(1)

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Patch already applied. Nothing to do.")
        sys.exit(0)

    # Find the api_key block + everything up to and including the tunables comment
    # Build a dynamic anchor from api_key line through tunables line
    start_marker = '    api_key = _get_api_key()\n    if not api_key:\n'
    end_marker   = '    # Tunables (conservative defaults)\n'

    start_idx = src.find(start_marker)
    if start_idx == -1:
        print("ERROR: start marker not found.")
        sys.exit(1)

    end_idx = src.find(end_marker, start_idx)
    if end_idx == -1:
        print("ERROR: end marker not found after start.")
        sys.exit(1)

    # Replace from start through end_marker (inclusive)
    old_chunk = src[start_idx : end_idx + len(end_marker)]
    count = src.count(old_chunk)
    if count != 1:
        print("ERROR: chunk found {} times (expected 1).".format(count))
        sys.exit(1)

    new_src = src.replace(old_chunk, NEW_BLOCK, 1)

    # Validate it parses
    import ast
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print("ERROR: patched file has SyntaxError: {}".format(e))
        sys.exit(1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)

    print("Patched {} successfully.".format(TARGET))
    print("  - USPTO auth probe added with correct indentation")
    print("  - AST-validated before writing")


if __name__ == "__main__":
    main()
