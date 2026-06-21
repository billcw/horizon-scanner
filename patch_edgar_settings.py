"""
patch_edgar_settings.py  (v2, fixed escaping)

Add the EDGAR enrichment controls to config + Settings UI:
  1. config.yaml (BOTH copies): add the four edgar_* keys under thesis:
  2. export.py: expose them in the editable config slice
  3. index.html: add a toggle (ticker verify) + dropdown (depth) + JS hooks

Run from project root:
    python patch_edgar_settings.py
"""

from pathlib import Path

ROOT = Path(r"C:\Projects\horizon-scanner")
CONFIGS = [
    ROOT / "config.yaml",
    ROOT / "horizon_scanner" / "config.yaml",
]
EXPORT = ROOT / "horizon_scanner" / "dashboard" / "export.py"
HTML = ROOT / "horizon_scanner" / "dashboard" / "index.html"

# ---------------------------------------------------------------------------
# 1. config.yaml -- add edgar_* keys under thesis (both copies)
# ---------------------------------------------------------------------------

CFG_ANCHOR = '  output_dir: "data/exports"'
CFG_ADD = '''  output_dir: "data/exports"

  # --- EDGAR enrichment (Step 5.5) ---
  edgar_verify_tickers: true       # cheap ticker verify/correct across all rings
  edgar_enrichment_depth: 1        # 0=off 1=ring1 2=rings1-2 3=rings1-3 4=all rings
  edgar_ip_excerpt_chars: 1500     # chars of 10-K IP section kept per company
  edgar_max_companies: 30          # hard ceiling on companies enriched per run'''

for cfg_path in CONFIGS:
    if not cfg_path.exists():
        print("  [!] config not found: " + str(cfg_path) + " (skipping)")
        continue
    txt = cfg_path.read_text(encoding="utf-8-sig")
    if "edgar_enrichment_depth" in txt:
        print("  [=] " + cfg_path.name + ": edgar keys already present")
        continue
    if CFG_ANCHOR in txt:
        txt = txt.replace(CFG_ANCHOR, CFG_ADD, 1)
        cfg_path.write_text(txt, encoding="utf-8")
        print("  [+] " + cfg_path.name + ": added edgar keys under thesis")
    else:
        print("  [!] " + cfg_path.name + ": thesis output_dir anchor not found -- add manually")

# ---------------------------------------------------------------------------
# 2. export.py -- expose the keys in the editable thesis slice
# ---------------------------------------------------------------------------

exp = EXPORT.read_text(encoding="utf-8-sig")

OLD_THESIS_KEYS = '''    "thesis": [
        "step_model", "adversarial_model", "step_max_tokens", "step_models",
        "max_signals_in_context", "signal_abstract_chars", "context_doc_max_chars",
        "web_search_max_tokens", "perplexity_model", "step_timeout_seconds",
    ],'''
NEW_THESIS_KEYS = '''    "thesis": [
        "step_model", "adversarial_model", "step_max_tokens", "step_models",
        "max_signals_in_context", "signal_abstract_chars", "context_doc_max_chars",
        "web_search_max_tokens", "perplexity_model", "step_timeout_seconds",
        "edgar_verify_tickers", "edgar_enrichment_depth",
        "edgar_ip_excerpt_chars", "edgar_max_companies",
    ],'''

if "edgar_enrichment_depth" not in exp:
    if OLD_THESIS_KEYS in exp:
        exp = exp.replace(OLD_THESIS_KEYS, NEW_THESIS_KEYS, 1)
        EXPORT.write_text(exp, encoding="utf-8")
        print("  [+] export.py: exposed edgar keys in editable thesis slice")
    else:
        print("  [!] export.py: thesis _EDITABLE anchor not found -- add edgar keys manually")
else:
    print("  [=] export.py: edgar keys already exposed")

# ---------------------------------------------------------------------------
# 3. index.html -- add controls + JS hooks
# ---------------------------------------------------------------------------

html = HTML.read_text(encoding="utf-8-sig")
html_changed = False

EDGAR_BLOCK = '''
      <h3>EDGAR enrichment</h3>
      <div class="set-row">
        <label>Verify tickers (all rings)</label>
        <select id="set_edgar_verify">
          <option value="true">On</option>
          <option value="false">Off</option>
        </select>
      </div>
      <div class="set-row">
        <label>Deep enrichment depth</label>
        <select id="set_edgar_depth">
          <option value="0">Off</option>
          <option value="1">Ring 1</option>
          <option value="2">Rings 1-2</option>
          <option value="3">Rings 1-3</option>
          <option value="4">All rings</option>
        </select>
      </div>
'''

SAVE_ANCHORS = [
    '<button onclick="saveSettings()"',
    '>SAVE SETTINGS<',
    'SAVE SETTINGS',
]

if "set_edgar_depth" not in html:
    inserted = False
    for anchor in SAVE_ANCHORS:
        idx = html.find(anchor)
        if idx != -1:
            line_start = html.rfind("\n", 0, idx)
            if line_start == -1:
                line_start = idx
            html = html[:line_start] + "\n" + EDGAR_BLOCK + html[line_start:]
            inserted = True
            print("  [+] index.html: inserted EDGAR settings block before '" + anchor + "'")
            break
    if not inserted:
        print("  [!] index.html: could not find Save Settings anchor -- insert block manually")
    else:
        html_changed = True
else:
    print("  [=] index.html: EDGAR settings block already present")

# JS hooks
if "function _edgarApplyConfig" not in html:
    JS_BLOCK = '''
// === EDGAR enrichment settings hooks ===
function _edgarApplyConfig(cfg) {
  try {
    var t = (cfg && cfg.thesis) || {};
    var v = document.getElementById("set_edgar_verify");
    var d = document.getElementById("set_edgar_depth");
    if (v && t.edgar_verify_tickers !== undefined)
      v.value = String(t.edgar_verify_tickers);
    if (d && t.edgar_enrichment_depth !== undefined)
      d.value = String(t.edgar_enrichment_depth);
  } catch (e) { console.warn("edgar config apply failed", e); }
}
function _edgarCollect(payload) {
  try {
    payload.thesis = payload.thesis || {};
    var v = document.getElementById("set_edgar_verify");
    var d = document.getElementById("set_edgar_depth");
    if (v) payload.thesis.edgar_verify_tickers = (v.value === "true");
    if (d) payload.thesis.edgar_enrichment_depth = parseInt(d.value, 10);
  } catch (e) { console.warn("edgar collect failed", e); }
  return payload;
}
'''
    last_script = html.rfind("</script>")
    if last_script != -1:
        html = html[:last_script] + JS_BLOCK + html[last_script:]
        print("  [+] index.html: added EDGAR settings JS hooks")
        html_changed = True
    else:
        print("  [!] index.html: no </script> found for JS hooks")
else:
    print("  [=] index.html: JS hooks already present")

if html_changed:
    HTML.write_text(html, encoding="utf-8")

# ---------------------------------------------------------------------------
print("")
print("NOTE -- manual JS wiring likely needed:")
print("  Helper functions _edgarApplyConfig(cfg) and _edgarCollect(payload) were")
print("  added but must be CALLED from your existing settings code:")
print("   - after Settings loads config:  _edgarApplyConfig(cfg)")
print("   - when building the save payload: payload = _edgarCollect(payload)")
print("  Paste your settings load/save JS and I will wire these calls in exactly.")
