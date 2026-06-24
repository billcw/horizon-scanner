"""
patch_index_enrich.py

Replaces the static "No EDGAR enrichment" message in index.html with a
"Run EDGAR Enrichment" button that triggers the /api/thesis/enrich job
and polls to completion, then reloads the thesis so the panel updates.

Also adds triggerEnrich() and pollEnrich() JS functions.

Run from C:\\Projects\\horizon-scanner:
    python patch_index_enrich.py

Idempotent: aborts if sentinel present or anchors not found exactly once.
"""

import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "index.html")

SENTINEL = "triggerEnrich"

# --- Patch 1: replace the static no-enrichment div return ---
# The exact string returned when !enriched
EDGAR_EMPTY_ANCHOR = (
    "  if (!enriched) {\n"
    "    return '<div class=\"edgar-empty\">No EDGAR enrichment on this thesis yet. ' +\n"
    "           'Re-run the thesis with Step 5.5 enabled (Settings &rarr; EDGAR Enrichment) to populate ' +\n"
    "           'verified tickers, CIKs, licensing filings, and IP summaries.</div>';\n"
    "  }"
)

EDGAR_EMPTY_REPLACEMENT = """\
  if (!enriched) {
    return '<div class="edgar-empty">' +
           '<p style="margin:0 0 10px">No EDGAR enrichment on this thesis yet.</p>' +
           '<button class="ghost" id="enrich-btn" onclick="triggerEnrich()" ' +
           'style="font-size:11px;padding:6px 12px">Run EDGAR Enrichment</button>' +
           ' <span id="enrich-status" style="font-family:var(--mono);font-size:11px;' +
           'color:var(--signal);margin-left:8px"></span>' +
           '</div>';
  }"""

# --- Patch 2: add JS functions before the graph JS block ---
JS_ANCHOR = "// === GRAPH TAB ==="

ENRICH_JS = """\
// === EDGAR ENRICHMENT BACKFILL ===

var _enrichPollTimer = null;

function triggerEnrich() {
  var t = State.selectedThesis;
  if (!t || !t.id) { toast("No thesis selected"); return; }
  var btn = document.getElementById("enrich-btn");
  var st  = document.getElementById("enrich-status");
  if (btn) { btn.disabled = true; btn.textContent = "Running..."; }
  if (st)  { st.textContent = ""; }

  fetch("/api/thesis/enrich", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thesis_id: t.id }),
  })
  .then(function(r){ return r.json(); })
  .then(function(data){
    if (!data.ok) {
      if (st) st.textContent = "Error: " + (data.error || "unknown");
      if (btn) { btn.disabled = false; btn.textContent = "Run EDGAR Enrichment"; }
      return;
    }
    if (data.already) {
      if (st) st.textContent = "Already running";
      if (btn) { btn.disabled = false; btn.textContent = "Run EDGAR Enrichment"; }
    }
    pollEnrich(data.job_id, t.id);
  })
  .catch(function(e){
    if (st) st.textContent = "Error: " + e.message;
    if (btn) { btn.disabled = false; btn.textContent = "Run EDGAR Enrichment"; }
  });
}

function pollEnrich(jobId, thesisId) {
  if (_enrichPollTimer) clearInterval(_enrichPollTimer);
  var st  = document.getElementById("enrich-status");
  var btn = document.getElementById("enrich-btn");
  if (st) st.textContent = "starting...";

  _enrichPollTimer = setInterval(function(){
    fetch("/api/jobs")
      .then(function(r){ return r.json(); })
      .then(function(data){
        var j = (data.jobs || []).find(function(x){ return x.job_id === jobId; });
        if (!j) return;
        if (j.status === "running") {
          if (st) st.textContent = (j.step || "running") +
            (j.companies_enriched ? " (" + j.companies_enriched + " done)" : "");
        }
        if (j.status === "done") {
          clearInterval(_enrichPollTimer);
          if (st) st.textContent =
            "done -- " + j.companies_enriched + " co. enriched, " +
            j.total_hits + " filing hit" + (j.total_hits === 1 ? "" : "s");
          if (btn) { btn.disabled = false; btn.textContent = "Run EDGAR Enrichment"; }
          // Reload thesis data so the EDGAR panel re-renders with enrichment
          loadTheses().then(function(){
            var updated = State.theses.find(function(x){ return x.id === thesisId; });
            if (updated) {
              State.selectedThesis = updated;
              renderThesis(updated);
            }
          });
        }
        if (j.status === "error") {
          clearInterval(_enrichPollTimer);
          if (st) st.textContent = "error: " + (j.error || "unknown");
          if (btn) { btn.disabled = false; btn.textContent = "Run EDGAR Enrichment"; }
        }
      })
      .catch(function(){ /* keep polling */ });
  }, 1500);
}

// === GRAPH TAB ===
"""


def main():
    if not os.path.exists(TARGET):
        print("ERROR: {} not found. Run from project root.".format(TARGET))
        sys.exit(1)

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    # Idempotency
    if SENTINEL in src:
        print("Patch already applied (sentinel found). Nothing to do.")
        sys.exit(0)

    # --- Patch 1: EDGAR empty panel ---
    count = src.count(EDGAR_EMPTY_ANCHOR)
    if count != 1:
        print("ERROR: EDGAR empty anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(EDGAR_EMPTY_ANCHOR, EDGAR_EMPTY_REPLACEMENT, 1)

    # --- Patch 2: enrich JS ---
    count2 = src.count(JS_ANCHOR)
    if count2 != 1:
        print("ERROR: JS anchor found {} times (expected 1).".format(count2))
        sys.exit(1)
    src = src.replace(JS_ANCHOR, ENRICH_JS, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)

    print("Patched {} successfully.".format(TARGET))
    print("Added: Run EDGAR Enrichment button + triggerEnrich/pollEnrich JS")


if __name__ == "__main__":
    main()
