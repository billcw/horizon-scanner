"""
patch_edgar_panel.py

Adds a per-thesis EDGAR Enrichment panel to the thesis detail view.
Renders the Step 5.5 enrichment data that already reaches the browser but is
currently invisible: verified company name, CIK (linked to its SEC EDGAR page),
licensing-filing count with dated links, and the 10-K IP summary -- grouped by
ring. Theses generated before Step 5.5 show a graceful "not enriched" state.

This is a pure front-end patch. export.py already ships entities_ring* with the
enrichment fields, so no backend change is needed.

Two edits to index.html:
  1. Inject the panel markup between the Bottleneck Map and Scenario Tree
     sections inside renderThesis's template.
  2. Add the renderEdgarPanel() helper function (and a small escape helper
     reuse) before renderThesis.

Run from the project root:
  python patch_edgar_panel.py
"""
import sys
import os

TARGET = r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\index.html"

# ---- Edit 1: inject panel markup before the Scenario Tree section ----------
# Anchored on the two-line section opener (robust to surrounding whitespace).
ANCHOR_MARKUP = '''    <section class="block">
      <h3>Scenario Tree</h3>'''

NEW_MARKUP = '''    <section class="block">
      <h3>EDGAR Enrichment</h3>
      ${renderEdgarPanel(t)}
    </section>
    <section class="block">
      <h3>Scenario Tree</h3>'''

# ---- Edit 2: add the helper function before renderThesis -------------------
ANCHOR_FN = 'function renderThesis(t){'

HELPER_FN = '''function _edgarSecUrl(cik){
  // Zero-pad CIK to 10 digits for the EDGAR browse URL.
  var s = String(cik);
  while (s.length < 10) s = "0" + s;
  return "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=" + s + "&type=&dateb=&owner=include&count=40";
}

function _edgarCompanyRow(co){
  if (!co || typeof co !== "object") return "";
  var name = esc(co.company || co.ticker || "Unknown");
  var verified = co.ticker_verified === true;
  var badge = verified
    ? '<span class="edgar-ok">verified</span>'
    : '<span class="edgar-no">unverified</span>';

  var cikPart = "";
  if (co.cik) {
    cikPart = ' &middot; CIK <a href="' + _edgarSecUrl(co.cik) +
              '" target="_blank" rel="noopener">' + esc(String(co.cik)) + '</a>';
  }

  var vname = "";
  if (co.verified_name && co.verified_name !== co.company) {
    vname = '<div class="edgar-vname">' + esc(co.verified_name) + '</div>';
  }

  var lic = "";
  var hits = Array.isArray(co.licensing_hits) ? co.licensing_hits : [];
  if (hits.length) {
    var links = hits.slice(0, 6).map(function(h){
      var date = esc(h.filing_date || "filing");
      var url = h.index_url || "#";
      return '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + date + '</a>';
    }).join(", ");
    var more = hits.length > 6 ? ' (+' + (hits.length - 6) + ' more)' : '';
    lic = '<div class="edgar-lic"><span class="edgar-lic-label">licensing filings (' +
          hits.length + '):</span> ' + links + more + '</div>';
  }

  var ip = "";
  if (co.ip_summary) {
    var ipdate = co.ip_filing_date ? ' <span class="edgar-ipdate">(' + esc(co.ip_filing_date) + ')</span>' : '';
    ip = '<div class="edgar-ip">' + esc(co.ip_summary) + ipdate + '</div>';
  }

  return '<div class="edgar-co">' +
           '<div class="edgar-co-head"><span class="edgar-co-name">' + name + '</span> ' +
           badge + cikPart + '</div>' +
           vname + lic + ip +
         '</div>';
}

function renderEdgarPanel(t){
  var rings = [
    ["Ring 1 - Direct",    t.entities_ring1],
    ["Ring 2 - Enabling",  t.entities_ring2],
    ["Ring 3 - Benefiting",t.entities_ring3],
    ["Ring 4 - Threatened",t.entities_ring4]
  ];

  // Detect whether ANY company carries enrichment fields.
  var enriched = false;
  rings.forEach(function(pair){
    (pair[1] || []).forEach(function(co){
      if (co && (co.edgar_enriched || co.ticker_verified || co.cik)) enriched = true;
    });
  });

  if (!enriched) {
    return '<div class="edgar-empty">No EDGAR enrichment on this thesis yet. ' +
           'Re-run the thesis with Step 5.5 enabled (Settings &rarr; EDGAR Enrichment) to populate ' +
           'verified tickers, CIKs, licensing filings, and IP summaries.</div>';
  }

  var blocks = rings.map(function(pair){
    var label = pair[0];
    var cos = pair[1] || [];
    if (!cos.length) return "";
    var rows = cos.map(_edgarCompanyRow).join("");
    return '<div class="edgar-ring"><div class="edgar-ring-label">' + esc(label) +
           '</div>' + rows + '</div>';
  }).join("");

  return '<div class="edgar-panel">' + blocks + '</div>';
}

function renderThesis(t){'''

# ---- CSS (injected before the scenario-tree comment block) -----------------
ANCHOR_CSS = '  /* ---- Scenario tree -------------------------------------------------*/'

NEW_CSS = '''  /* ---- EDGAR enrichment panel ---------------------------------------*/
  .edgar-panel { display: flex; flex-direction: column; gap: 14px; }
  .edgar-empty { color: var(--muted, #8a93a3); font-size: 13px; line-height: 1.5; padding: 6px 0; }
  .edgar-ring-label { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted, #8a93a3); margin-bottom: 6px; }
  .edgar-ring { border-left: 2px solid var(--line, #2a3344); padding-left: 12px; }
  .edgar-co { padding: 7px 0; border-bottom: 1px solid var(--line, #1e2430); }
  .edgar-co:last-child { border-bottom: none; }
  .edgar-co-name { font-weight: 600; }
  .edgar-ok { font-size: 10px; color: #4ec98f; border: 1px solid #2f6f52; border-radius: 4px; padding: 1px 5px; margin-left: 4px; }
  .edgar-no { font-size: 10px; color: #c9974e; border: 1px solid #6f5a2f; border-radius: 4px; padding: 1px 5px; margin-left: 4px; }
  .edgar-vname { font-size: 11px; color: var(--muted, #8a93a3); margin-top: 2px; }
  .edgar-lic { font-size: 12px; margin-top: 4px; }
  .edgar-lic-label { color: var(--muted, #8a93a3); }
  .edgar-ip { font-size: 12px; margin-top: 4px; line-height: 1.45; color: var(--fg, #c7cedb); }
  .edgar-ipdate { color: var(--muted, #8a93a3); }

'''

def main():
    if not os.path.exists(TARGET):
        print("ERROR: file not found: " + TARGET)
        return 1

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if "renderEdgarPanel" in src:
        print("SKIP panel already present (renderEdgarPanel found)")
        return 0

    # Edit 1: markup
    n = src.count(ANCHOR_MARKUP)
    if n != 1:
        print("ERROR markup anchor matched " + str(n) + " times (need exactly 1) -- aborting")
        return 1
    src = src.replace(ANCHOR_MARKUP, NEW_MARKUP, 1)
    print("OK  edit 1: panel markup injected")

    # Edit 2: helper function
    n = src.count(ANCHOR_FN)
    if n != 1:
        print("ERROR function anchor matched " + str(n) + " times (need exactly 1) -- aborting")
        return 1
    src = src.replace(ANCHOR_FN, HELPER_FN, 1)
    print("OK  edit 2: renderEdgarPanel helper added")

    # Edit 3: CSS
    n = src.count(ANCHOR_CSS)
    if n != 1:
        print("ERROR css anchor matched " + str(n) + " times (need exactly 1) -- aborting")
        return 1
    src = src.replace(ANCHOR_CSS, NEW_CSS + ANCHOR_CSS, 1)
    print("OK  edit 3: panel CSS injected")

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print("WRITTEN " + TARGET)
    return 0

sys.exit(main())
