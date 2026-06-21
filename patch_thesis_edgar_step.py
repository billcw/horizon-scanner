"""
patch_thesis_edgar_step.py  (v2, fixed escaping)

Insert Step 5.5 (EDGAR enrichment) into the thesis loop, between Step 5
(entity mapping) and Step 6 (platform classification).

Run from project root:
    python patch_thesis_edgar_step.py
"""

from pathlib import Path
import sys

PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\thesis\thesis_loop.py")

if not PATH.exists():
    print("ERROR: thesis_loop.py not found")
    sys.exit(1)

text = PATH.read_text(encoding="utf-8-sig")
changed = False

# ---------------------------------------------------------------------------
# 1. Add the step5_5_edgar wrapper before the Step 6 section header
# ---------------------------------------------------------------------------

WRAPPER_CHECK = "def step5_5_edgar("
ANCHOR = """# ---------------------------------------------------------------------------
# Step 6 - Platform / Product Classification
# ---------------------------------------------------------------------------"""

WRAPPER = """# ---------------------------------------------------------------------------
# Step 5.5 - EDGAR Verification & Enrichment
# Grounds the LLM-produced entity rings against real SEC filings:
#   - verifies/corrects tickers (cheap, all rings if enabled)
#   - pulls 10-K IP sections + licensing mentions (configurable ring depth)
# Non-fatal: handled inside edgar_enrichment; loop try/except is a 2nd net.
# Controls live in config.yaml -> thesis (edgar_verify_tickers,
# edgar_enrichment_depth, edgar_ip_excerpt_chars, edgar_max_companies).
# ---------------------------------------------------------------------------

def step5_5_edgar(state: ThesisState, client) -> ThesisState:
    logger.info("Step 5.5: EDGAR Verification & Enrichment")
    from .edgar_enrichment import run_edgar_enrichment
    return run_edgar_enrichment(state, _thesis_cfg())


# ---------------------------------------------------------------------------
# Step 6 - Platform / Product Classification
# ---------------------------------------------------------------------------"""

if WRAPPER_CHECK not in text:
    if ANCHOR in text:
        text = text.replace(ANCHOR, WRAPPER, 1)
        print("  [+] added step5_5_edgar wrapper function")
        changed = True
    else:
        print("  [!] could not find Step 6 section anchor -- aborting")
        sys.exit(1)
else:
    print("  [=] step5_5_edgar wrapper already present")

# ---------------------------------------------------------------------------
# 2. Insert into the steps list
# ---------------------------------------------------------------------------

OLD_STEPS = '''        ("Step 5: Entity Mapping",             step5_entities),
        ("Step 6: Platform Classification",    step6_platform),'''

NEW_STEPS = '''        ("Step 5: Entity Mapping",             step5_entities),
        ("Step 5.5: EDGAR Enrichment",         step5_5_edgar),
        ("Step 6: Platform Classification",    step6_platform),'''

if '"Step 5.5: EDGAR Enrichment"' not in text:
    if OLD_STEPS in text:
        text = text.replace(OLD_STEPS, NEW_STEPS, 1)
        print("  [+] inserted Step 5.5 into the steps list")
        changed = True
    else:
        print("  [!] could not find steps list anchor -- aborting")
        sys.exit(1)
else:
    print("  [=] Step 5.5 already in steps list")

# ---------------------------------------------------------------------------
# 3. Add 'edgar' to ThesisState TypedDict
# ---------------------------------------------------------------------------

OLD_STATE = """    platform_class:   dict
    adversarial:      dict"""
NEW_STATE = """    platform_class:   dict
    edgar:            dict
    adversarial:      dict"""

if "edgar:            dict" not in text:
    if OLD_STATE in text:
        text = text.replace(OLD_STATE, NEW_STATE, 1)
        print("  [+] added 'edgar' key to ThesisState TypedDict")
        changed = True
    else:
        print("  [=] ThesisState anchor not found (non-critical; setdefault handles it)")
else:
    print("  [=] ThesisState already has edgar key")

# ---------------------------------------------------------------------------
# 4. Initialise state['edgar'] in the state dict literal
# ---------------------------------------------------------------------------

OLD_INIT = '''        "platform_class": {},
        "adversarial":    {},'''
NEW_INIT = '''        "platform_class": {},
        "edgar":          {},
        "adversarial":    {},'''

if '"edgar":          {},' not in text:
    if OLD_INIT in text:
        text = text.replace(OLD_INIT, NEW_INIT, 1)
        print("  [+] initialised state['edgar'] in run_thesis_loop")
        changed = True
    else:
        print("  [=] state init anchor not found (non-critical; setdefault handles it)")
else:
    print("  [=] state['edgar'] already initialised")

# ---------------------------------------------------------------------------
if changed:
    PATH.write_text(text, encoding="utf-8")
    print("")
    print("Done. thesis_loop.py updated.")
    print("Verify the file parses with a simple ast.parse check.")
else:
    print("")
    print("No changes made -- already patched.")
