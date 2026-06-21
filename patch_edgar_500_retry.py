"""
patch_edgar_500_retry.py

The remaining EFTS 500 is transient, not phrase-specific (the probe showed it
firing between phrases that both succeeded). EFTS occasionally 500s under rapid
sequential requests. Fix: give 5xx its own retry branch with a real backoff,
like the 429 handling, and slow the rate limiter slightly so bursts of phrase
queries don't trip it.

Changes:
  1. _get: explicit 5xx (500/502/503/504) retry with exponential backoff.
  2. _RateLimiter default interval 0.2s -> 0.34s (~3 req/s) for gentler bursts.

Run from project root:
    python patch_edgar_500_retry.py
"""

from pathlib import Path
import sys

PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\enrichment\edgar_client.py")

if not PATH.exists():
    print("ERROR: edgar_client.py not found")
    sys.exit(1)

text = PATH.read_text(encoding="utf-8-sig")
changed = False

# ---------------------------------------------------------------------------
# 1. Add explicit 5xx retry branch before the catch-all
# ---------------------------------------------------------------------------

OLD_TAIL = '''        if resp.status_code == 404:
            return None  # legitimately not found; caller handles
        logger.warning("EDGAR HTTP %d for %s", resp.status_code, url)
        time.sleep(0.5 * attempt)
    return None'''

NEW_TAIL = '''        if resp.status_code == 404:
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
    return None'''

if "transient); backing off" in text:
    print("  [=] 5xx retry branch already present")
elif OLD_TAIL in text:
    text = text.replace(OLD_TAIL, NEW_TAIL, 1)
    print("  [+] added explicit 5xx retry branch with backoff")
    changed = True
else:
    print("  [!] _get tail anchor not found")

# ---------------------------------------------------------------------------
# 2. Bump max_retries default from 3 to 4 so 5xx has more attempts
# ---------------------------------------------------------------------------

OLD_SIG = "def _get(url, params=None, json_accept=True, max_retries=3, timeout=30):"
NEW_SIG = "def _get(url, params=None, json_accept=True, max_retries=4, timeout=30):"
if OLD_SIG in text:
    text = text.replace(OLD_SIG, NEW_SIG, 1)
    print("  [+] raised _get max_retries 3 -> 4")
    changed = True
else:
    print("  [=] _get signature already updated or not found")

# ---------------------------------------------------------------------------
# 3. Gentler rate limiter: 0.2s -> 0.34s (~3 req/s)
# ---------------------------------------------------------------------------

OLD_RATE = "def __init__(self, min_interval=0.2):"
NEW_RATE = "def __init__(self, min_interval=0.34):"
if OLD_RATE in text:
    text = text.replace(OLD_RATE, NEW_RATE, 1)
    print("  [+] rate limiter eased 0.2s -> 0.34s (~3 req/s)")
    changed = True
else:
    print("  [=] rate limiter already eased or not found")

# ---------------------------------------------------------------------------
if changed:
    PATH.write_text(text, encoding="utf-8")
    print("")
    print("Done. Re-test:  python probe_edgar_phrases.py")
    print("Then full client: python -m horizon_scanner.enrichment.edgar_client")
else:
    print("")
    print("No changes made -- already patched.")
