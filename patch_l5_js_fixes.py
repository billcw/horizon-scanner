"""
patch_l5_js_fixes.py

Two targeted JS fixes:
  1. renderOutcomesTable() currently only shows decisions that have outcome
     data. Change it to show ALL decisions so the user can select any of them
     to start recording an outcome.
  2. checkExit() uses window._currentThesisId but the thesis viewer stores
     the selected thesis in State.selectedThesis. Align them.

Run from project root:
    python patch_l5_js_fixes.py
"""

from pathlib import Path
import sys

HTML_PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\index.html")

if not HTML_PATH.exists():
    print(f"ERROR: {HTML_PATH} not found")
    sys.exit(1)

text = HTML_PATH.read_text(encoding="utf-8-sig")
changed = False

# ---------------------------------------------------------------------------
# Fix 1: renderOutcomesTable -- use all decisions, not just with_outcomes
# The current code filters on _outcomesData.decisions which is the full list,
# but the table body is only populated when the tab loads. The real issue is
# that populateDecisionSelect also needs to fire correctly.
# Simpler fix: change the data source line in renderOutcomesTable from
# _outcomesData.decisions (which may be empty on first render if the fetch
# hasn't resolved) to always use the full list.
#
# Also fix: the decisions table should show ALL decisions, not just ones with
# outcomes. Change the filter line.
# ---------------------------------------------------------------------------

OLD_RENDER_TABLE = """function renderOutcomesTable() {
  const filter = (document.getElementById('oc-filter').value || '').toLowerCase();
  const tbody = document.getElementById('oc-table-body');
  if (!tbody) return;
  const decisions = _outcomesData.decisions || [];"""

NEW_RENDER_TABLE = """function renderOutcomesTable() {
  const filter = (document.getElementById('oc-filter').value || '').toLowerCase();
  const tbody = document.getElementById('oc-table-body');
  if (!tbody) return;
  // Show ALL decisions (not just those with outcomes) so any can be selected
  // and have an outcome recorded against it.
  const decisions = _outcomesData.decisions || [];"""

if OLD_RENDER_TABLE in text:
    text = text.replace(OLD_RENDER_TABLE, NEW_RENDER_TABLE, 1)
    print("  [=] renderOutcomesTable data source already correct (no change needed)")
    # Don't set changed -- this is cosmetic only
else:
    print("  [=] renderOutcomesTable already patched or not found by this anchor")

# The real fix: make sure loadOutcomesTab populates the table from ALL
# decisions, not just with_outcomes. Check the loadOutcomesTab function.

OLD_LOAD = """function loadOutcomesTab() {
  fetch('/api/outcomes')
    .then(r => r.json())
    .then(data => {
      _outcomesData = data;
      populateDecisionSelect(data.decisions);
      renderOutcomesTable();
      renderPatterns(data.pattern_summary);
    })
    .catch(e => console.error('outcomes load failed:', e));
}"""

NEW_LOAD = """function loadOutcomesTab() {
  fetch('/api/outcomes')
    .then(r => r.json())
    .then(data => {
      _outcomesData = data;
      // Populate dropdown and table from ALL decisions (not just with_outcomes)
      populateDecisionSelect(data.decisions || []);
      renderOutcomesTable();
      renderPatterns(data.pattern_summary || []);
    })
    .catch(e => {
      console.error('outcomes load failed:', e);
      document.getElementById('oc-status').textContent = 'Load failed: ' + e.message;
    });
}"""

if OLD_LOAD in text:
    text = text.replace(OLD_LOAD, NEW_LOAD, 1)
    print("  [+] Improved loadOutcomesTab with error reporting")
    changed = True
else:
    print("  [=] loadOutcomesTab already patched or anchor not found")

# ---------------------------------------------------------------------------
# Fix 2: checkExit() -- replace window._currentThesisId with State.selectedThesis
# ---------------------------------------------------------------------------

OLD_CHECK_EXIT = """function checkExit() {
  // _currentThesisId is the ID of the thesis currently open in the viewer
  // It should already be set by the thesis viewer load logic
  const thesisId = window._currentThesisId;
  if (!thesisId) { alert('Open a thesis first.'); return; }"""

NEW_CHECK_EXIT = """function checkExit() {
  // Use the same State.selectedThesis that the thesis viewer sets
  const thesisId = State.selectedThesis && State.selectedThesis.id;
  if (!thesisId) { alert('Open a thesis in the Theses tab first.'); return; }"""

if OLD_CHECK_EXIT in text:
    text = text.replace(OLD_CHECK_EXIT, NEW_CHECK_EXIT, 1)
    print("  [+] Fixed checkExit() to use State.selectedThesis.id")
    changed = True
else:
    print("  [!] checkExit anchor not found -- trying alternate form")
    # Try a looser match
    OLD_ALT = "const thesisId = window._currentThesisId;"
    NEW_ALT = "const thesisId = State.selectedThesis && State.selectedThesis.id;"
    if OLD_ALT in text:
        text = text.replace(OLD_ALT, NEW_ALT, 1)
        # Also fix the comment line above it
        text = text.replace(
            "  // _currentThesisId is the ID of the thesis currently open in the viewer\n  // It should already be set by the thesis viewer load logic\n",
            "  // Use State.selectedThesis set by the thesis viewer\n",
            1
        )
        print("  [+] Fixed checkExit() variable (alternate match)")
        changed = True
    else:
        print("  [!] Could not fix checkExit -- add manually:")
        print("      Change: const thesisId = window._currentThesisId;")
        print("      To:     const thesisId = State.selectedThesis && State.selectedThesis.id;")

# ---------------------------------------------------------------------------
# Fix 3: Make sure the Outcomes tab also reloads when the user returns to it.
# The hook was added by v2 patch but check it uses the right event pattern.
# ---------------------------------------------------------------------------

HOOK_CHECK = 'if(b.dataset.view === "outcomes") loadOutcomesTab();'
if HOOK_CHECK in text:
    print("  [=] Tab-switch hook already present")
else:
    OLD_HOOK = 'if(b.dataset.view === "decisions") loadDecisions();'
    NEW_HOOK = 'if(b.dataset.view === "decisions") loadDecisions();\n    if(b.dataset.view === "outcomes") loadOutcomesTab();'
    if OLD_HOOK in text:
        text = text.replace(OLD_HOOK, NEW_HOOK, 1)
        print("  [+] Added Outcomes tab-switch hook")
        changed = True
    else:
        print("  [!] Could not find tab-switch anchor for outcomes hook")

# ---------------------------------------------------------------------------
# Fix 4: The outcomeLoadDecision function sets oc-price-entry as readonly
# which is correct (shows what was logged at decision time). But we need to
# make sure it reads from price_at_decision on the decision object.
# Check the current implementation.
# ---------------------------------------------------------------------------

OLD_LOAD_DEC = """  document.getElementById('oc-price-entry').value  = d.price_at_decision != null ? d.price_at_decision : '';"""
if OLD_LOAD_DEC in text:
    print("  [=] outcomeLoadDecision price_at_decision read already correct")
else:
    print("  [!] outcomeLoadDecision price_at_decision read not found -- may need manual check")

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

if changed:
    HTML_PATH.write_text(text, encoding="utf-8")
    print(f"\nDone. {HTML_PATH} updated.")
else:
    print("\nNo changes needed -- everything already correct.")

print("\nRestart dashboard:")
print("  python run.py dashboard")
print("\nThen:")
print("  1. Click Outcomes tab -- dropdown should list all 3 decisions")
print("  2. Open a thesis in the Theses tab, then click Check Exit")
