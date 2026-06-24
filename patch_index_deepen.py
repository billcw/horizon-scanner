"""
patch_index_deepen.py

Adds to horizon_scanner/dashboard/index.html:
  1. "Graph" tab in the nav bar
  2. Graph view div (with thesis picker and D3 force-directed SVG)
  3. Graph CSS
  4. Deepen Counterparties button + poll logic in the EDGAR panel
  5. Full graph JS: buildGraphData(), renderGraph(), pollDeepen()

D3 v7 loaded from cdnjs. No other new dependencies.

Run from C:\\Projects\\horizon-scanner:
    python patch_index_deepen.py

Idempotent: aborts if sentinel present or anchors not found exactly once.
"""

import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "index.html")

SENTINEL = 'id="view-graph"'

# ---------------------------------------------------------------------------
# Patch 1: add Graph tab to nav
# ---------------------------------------------------------------------------
NAV_ANCHOR = '  <button data-view="settings">Settings</button>'
NAV_INSERTION = '  <button data-view="graph">Graph</button>\n'

# ---------------------------------------------------------------------------
# Patch 2: add graph view div before closing </main>
# ---------------------------------------------------------------------------
VIEW_ANCHOR = '</main>'
GRAPH_VIEW = '''\

  <!-- GRAPH VIEW -->
  <div class="view" id="view-graph">
    <div class="graph-toolbar">
      <div class="graph-pick-wrap">
        <label class="graph-pick-label">Thesis</label>
        <select id="graph-thesis-select">
          <option value="">-- select a thesis --</option>
        </select>
      </div>
      <div class="graph-legend-row" id="graph-legend-row"></div>
      <div id="graph-status" class="graph-status"></div>
    </div>
    <div id="graph-canvas-wrap">
      <div id="graph-empty" class="empty">Select a thesis above to render its company relationship graph.</div>
      <svg id="graph-svg" style="display:none;width:100%;height:640px"></svg>
    </div>
    <div id="graph-tooltip" class="graph-tooltip" style="display:none"></div>
  </div>

</main>'''

# ---------------------------------------------------------------------------
# Patch 3: CSS -- insert before closing </style>
# ---------------------------------------------------------------------------
CSS_ANCHOR = '  .toast { position: fixed;'
GRAPH_CSS = '''\
  /* ---- Supply-line graph -----------------------------------------------*/
  .graph-toolbar {
    display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
    padding: 14px 0 12px; border-bottom: 1px solid var(--edge); margin-bottom: 16px;
  }
  .graph-pick-wrap { display: flex; align-items: center; gap: 8px; }
  .graph-pick-label {
    font-family: var(--mono); font-size: 10px; color: var(--ink-faint);
    text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap;
  }
  #graph-thesis-select {
    background: var(--panel); border: 1px solid var(--edge); color: var(--ink);
    border-radius: 5px; padding: 6px 10px; font-family: var(--mono); font-size: 12px;
    min-width: 220px;
  }
  .graph-legend-row { display: flex; gap: 14px; flex-wrap: wrap; }
  .graph-leg-item {
    display: flex; align-items: center; gap: 5px;
    font-family: var(--mono); font-size: 10px; color: var(--ink-dim);
  }
  .graph-leg-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .graph-status {
    font-family: var(--mono); font-size: 11px; color: var(--signal);
    margin-left: auto;
  }
  #graph-canvas-wrap {
    background: var(--panel); border: 1px solid var(--edge); border-radius: 8px;
    overflow: hidden; position: relative; min-height: 200px;
  }
  #graph-svg { display: block; }
  .graph-tooltip {
    position: fixed; pointer-events: none; z-index: 30;
    background: var(--panel-2); border: 1px solid var(--edge);
    border-radius: 6px; padding: 9px 12px; max-width: 280px;
    font-family: var(--mono); font-size: 11px; color: var(--ink);
    box-shadow: 0 4px 16px rgba(0,0,0,0.4); line-height: 1.5;
  }
  .graph-tooltip .gt-name { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .graph-tooltip .gt-dim  { color: var(--ink-dim); }
  .graph-tooltip .gt-cp   { margin-top: 6px; }
  .graph-tooltip .gt-cp-row { color: var(--ink-faint); margin-top: 2px; }

'''

# ---------------------------------------------------------------------------
# Patch 4: Deepen button in EDGAR panel (renderEdgarPanel function)
# Anchor: the closing line of the enriched branch return statement.
# We inject the Deepen button just before the panel div closes.
# ---------------------------------------------------------------------------
EDGAR_ANCHOR = "  return '<div class=\"edgar-panel\">' + blocks + '</div>';"
EDGAR_DEEPEN_REPLACEMENT = '''\
  // Deepen button: only shown when enrichment is present
  var deepenBtn = '<div style="margin-top:10px">' +
    '<button class="ghost" id="deepen-btn" onclick="triggerDeepen()" ' +
    'style="font-size:11px;padding:6px 12px">Deepen counterparties</button>' +
    ' <span id="deepen-status" style="font-family:var(--mono);font-size:11px;' +
    'color:var(--signal);margin-left:8px"></span></div>';
  return '<div class="edgar-panel">' + blocks + deepenBtn + '</div>';'''

# ---------------------------------------------------------------------------
# Patch 5: JS -- insert graph JS + tab wiring before the closing </script>
# ---------------------------------------------------------------------------
JS_ANCHOR = '// === EDGAR enrichment settings hooks ==='
GRAPH_JS = '''\
// === GRAPH TAB ===

// Deepen counterparties trigger (called from EDGAR panel button)
var _deepenPollTimer = null;

function triggerDeepen() {
  var t = State.selectedThesis;
  if (!t || !t.id) { toast("No thesis selected"); return; }
  var btn = document.getElementById("deepen-btn");
  var st  = document.getElementById("deepen-status");
  if (btn) { btn.disabled = true; btn.textContent = "Running..."; }
  if (st)  { st.textContent = ""; }

  fetch("/api/thesis/deepen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thesis_id: t.id }),
  })
  .then(function(r){ return r.json(); })
  .then(function(data){
    if (!data.ok) {
      if (st) st.textContent = "Error: " + (data.error || "unknown");
      if (btn) { btn.disabled = false; btn.textContent = "Deepen counterparties"; }
      return;
    }
    if (data.already) {
      if (st) st.textContent = "Already running";
      if (btn) { btn.disabled = false; btn.textContent = "Deepen counterparties"; }
    }
    pollDeepen(data.job_id, t.id);
  })
  .catch(function(e){
    if (st) st.textContent = "Error: " + e.message;
    if (btn) { btn.disabled = false; btn.textContent = "Deepen counterparties"; }
  });
}

function pollDeepen(jobId, thesisId) {
  if (_deepenPollTimer) clearInterval(_deepenPollTimer);
  var st  = document.getElementById("deepen-status");
  var btn = document.getElementById("deepen-btn");
  if (st) st.textContent = "running...";

  _deepenPollTimer = setInterval(function(){
    fetch("/api/jobs")
      .then(function(r){ return r.json(); })
      .then(function(data){
        var j = (data.jobs || []).find(function(x){ return x.job_id === jobId; });
        if (!j) return;
        if (j.status === "running") {
          if (st) st.textContent = "running...";
        }
        if (j.status === "done") {
          clearInterval(_deepenPollTimer);
          if (st) st.textContent =
            "done -- " + j.counterparties_found + " counterpart" +
            (j.counterparties_found === 1 ? "y" : "ies") +
            " found across " + j.companies_processed + " co.";
          if (btn) { btn.disabled = false; btn.textContent = "Deepen counterparties"; }
          // Reload thesis data so graph + EDGAR panel see the new counterparties
          loadTheses().then(function(){
            var updated = State.theses.find(function(x){ return x.id === thesisId; });
            if (updated) {
              State.selectedThesis = updated;
              // Re-render graph if we are on the graph tab
              if (document.getElementById("view-graph").classList.contains("active")) {
                renderGraph(updated);
              }
            }
          });
        }
        if (j.status === "error") {
          clearInterval(_deepenPollTimer);
          if (st) st.textContent = "error: " + (j.error || "unknown");
          if (btn) { btn.disabled = false; btn.textContent = "Deepen counterparties"; }
        }
      })
      .catch(function(){ /* keep polling */ });
  }, 1500);
}

// ---- Graph tab wiring ---------------------------------------------------

function initGraphTab() {
  var sel = document.getElementById("graph-thesis-select");
  if (!sel) return;
  // Populate picker from State.theses (already loaded at boot)
  sel.innerHTML = '<option value="">-- select a thesis --</option>';
  State.theses.forEach(function(t){
    var opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = t.title || t.theme || t.id.slice(0,8);
    // Pre-select if there is already a selected thesis
    if (State.selectedThesis && t.id === State.selectedThesis.id) {
      opt.selected = true;
    }
    sel.appendChild(opt);
  });
  sel.onchange = function(){
    var t = State.theses.find(function(x){ return x.id === sel.value; });
    if (t) renderGraph(t); else clearGraph();
  };
  // Auto-render if we have a pre-selected thesis
  if (State.selectedThesis) {
    renderGraph(State.selectedThesis);
  }
}

function clearGraph() {
  document.getElementById("graph-svg").style.display = "none";
  document.getElementById("graph-empty").style.display = "";
  document.getElementById("graph-empty").textContent =
    "Select a thesis above to render its company relationship graph.";
  document.getElementById("graph-legend-row").innerHTML = "";
  document.getElementById("graph-status").textContent = "";
}

// ---- Build graph data from a thesis object ------------------------------
// Node kinds: bottleneck | ring1 | ring2 | ring3 | ring4 | external
// Edge types: bottleneck | ring | license | joint_venture | acquisition |
//             supply | partnership | other

var NODE_COLORS = {
  bottleneck: "var(--caution)",
  ring1:      "var(--signal)",
  ring2:      "var(--good)",
  ring3:      "var(--violet)",
  ring4:      "var(--danger)",
  external:   "#667080",
};

var EDGE_COLORS = {
  bottleneck:     "var(--caution)",
  ring:           "#2a3d4e",
  license:        "#5ab4e0",
  joint_venture:  "var(--good)",
  acquisition:    "var(--caution)",
  supply:         "var(--violet)",
  partnership:    "#4ec98f",
  other:          "#3e4e5e",
};

function buildGraphData(t) {
  var nodes = [];
  var edges = [];
  var nodeIndex = {};   // key -> node index

  function addNode(key, label, ticker, kind) {
    if (nodeIndex[key] !== undefined) return nodeIndex[key];
    var idx = nodes.length;
    nodeIndex[key] = idx;
    nodes.push({ key: key, label: label, ticker: ticker, kind: kind,
                 counterparties: [] });
    return idx;
  }

  function addEdge(src, tgt, type, conf, derived) {
    edges.push({ source: src, target: tgt, type: type,
                 confidence: conf || null,
                 derived: derived || null });
  }

  // ---- Bottleneck node ----
  var bnKey = (t.bottleneck_ticker || t.bottleneck_entity || "BN").toUpperCase();
  var bnLabel = t.bottleneck_entity || bnKey;
  var bnIdx = addNode(bnKey, bnLabel, t.bottleneck_ticker || "", "bottleneck");

  // ---- Ring nodes + bottleneck edges ----
  var RING_KINDS = ["ring1","ring2","ring3","ring4"];
  var RING_FIELDS = ["entities_ring1","entities_ring2","entities_ring3","entities_ring4"];

  RING_FIELDS.forEach(function(field, ri){
    var kind = RING_KINDS[ri];
    var cos = t[field] || [];
    cos.forEach(function(co){
      if (!co) return;
      var key = (co.ticker || co.company || "").toUpperCase() || ("co_" + Math.random());
      var label = co.company || co.ticker || key;
      var idx = addNode(key, label, co.ticker || "", kind);
      nodes[idx].counterparties = co.counterparties || [];
      // Bottleneck edge (spine)
      addEdge(bnIdx, idx, "bottleneck", null, null);
      // Ring adjacency to ring1 nodes for rings 2-4 (shows layering)
      if (ri > 0) {
        var r1cos = t["entities_ring1"] || [];
        r1cos.slice(0,2).forEach(function(r1co){
          if (!r1co) return;
          var r1key = (r1co.ticker || r1co.company || "").toUpperCase();
          var r1idx = nodeIndex[r1key];
          if (r1idx !== undefined && r1idx !== idx) {
            addEdge(r1idx, idx, "ring", null, null);
          }
        });
      }
      // Counterparty edges
      (co.counterparties || []).forEach(function(cp){
        if (!cp || !cp.name) return;
        var cpKey = (cp.ticker || cp.name || "").toUpperCase() || ("cp_" + Math.random());
        var cpLabel = cp.name;
        var cpKind = nodeIndex[cpKey] !== undefined ? nodes[nodeIndex[cpKey]].kind : "external";
        var cpIdx = addNode(cpKey, cpLabel, cp.ticker || "", cpKind);
        var relType = cp.relationship_type || "other";
        addEdge(idx, cpIdx, relType, cp.confidence, cp.derived_from || null);
      });
    });
  });

  return { nodes: nodes, edges: edges, nodeIndex: nodeIndex };
}

// ---- D3 force-directed render -------------------------------------------

function renderGraph(t) {
  if (typeof d3 === "undefined") {
    document.getElementById("graph-status").textContent = "Loading D3...";
    var s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js";
    s.onload = function(){ renderGraph(t); };
    s.onerror = function(){
      document.getElementById("graph-status").textContent = "D3 load failed";
    };
    document.head.appendChild(s);
    return;
  }

  var data = buildGraphData(t);
  if (!data.nodes.length) {
    clearGraph();
    document.getElementById("graph-empty").textContent =
      "No company data found for this thesis.";
    return;
  }

  var svgEl = document.getElementById("graph-svg");
  var wrap   = document.getElementById("graph-canvas-wrap");
  var empty  = document.getElementById("graph-empty");
  var tooltip = document.getElementById("graph-tooltip");
  empty.style.display = "none";
  svgEl.style.display = "block";

  var W = wrap.clientWidth  || 900;
  var H = 640;

  // Clear previous render
  d3.select(svgEl).selectAll("*").remove();

  var svg = d3.select(svgEl)
    .attr("viewBox", "0 0 " + W + " " + H)
    .attr("preserveAspectRatio", "xMidYMid meet");

  // Arrow markers per edge color
  var defs = svg.append("defs");
  Object.keys(EDGE_COLORS).forEach(function(type){
    var col = EDGE_COLORS[type];
    // Resolve CSS vars to static fallback colors for SVG markers
    var staticCol = col.startsWith("var(") ? "#3e4e5e" : col;
    defs.append("marker")
      .attr("id", "arr-" + type)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 18)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", staticCol);
  });

  var g = svg.append("g");

  // Zoom + pan
  svg.call(d3.zoom()
    .scaleExtent([0.25, 4])
    .on("zoom", function(event){ g.attr("transform", event.transform); })
  );

  // Build D3 link/node arrays (d3 simulation uses object refs)
  var simNodes = data.nodes.map(function(n){ return Object.assign({}, n); });
  var simEdges = data.edges.map(function(e){
    return {
      source: simNodes[e.source],
      target: simNodes[e.target],
      type:   e.type,
      confidence: e.confidence,
      derived: e.derived,
    };
  });

  var sim = d3.forceSimulation(simNodes)
    .force("link",   d3.forceLink(simEdges).id(function(d){ return d.key; })
                       .distance(function(e){
                         if (e.type === "bottleneck") return 110;
                         if (e.type === "ring")       return 130;
                         return 160;
                       }).strength(0.6))
    .force("charge", d3.forceManyBody().strength(-380))
    .force("center", d3.forceCenter(W/2, H/2))
    .force("collision", d3.forceCollide(28));

  // Edges
  var edgeSel = g.append("g").attr("class","edges")
    .selectAll("line")
    .data(simEdges)
    .enter().append("line")
      .attr("stroke-width", function(e){
        if (e.type === "bottleneck") return 2;
        if (e.type === "ring") return 1;
        return e.confidence ? (0.8 + e.confidence) : 1.2;
      })
      .attr("stroke-opacity", function(e){
        if (e.type === "bottleneck") return 0.7;
        if (e.type === "ring") return 0.2;
        return e.confidence ? (0.4 + e.confidence * 0.4) : 0.5;
      })
      .attr("stroke-dasharray", function(e){
        // Dashed for approximate/LLM-derived edges
        return (e.derived && e.derived.indexOf("approximate") !== -1) ? "4 3" : null;
      })
      .attr("stroke", function(e){
        var col = EDGE_COLORS[e.type] || EDGE_COLORS.other;
        // CSS vars won't resolve in SVG attributes; map known ones
        var MAP = {
          "var(--caution)": "#e0a34a",
          "var(--signal)":  "#38d2c4",
          "var(--good)":    "#7fc97f",
          "var(--violet)":  "#a99be0",
          "var(--danger)":  "#e06c75",
        };
        return MAP[col] || col;
      })
      .attr("marker-end", function(e){
        if (e.type === "ring" || e.type === "bottleneck") return null;
        return "url(#arr-" + e.type + ")";
      });

  // Edge label (relationship type, for non-structural edges)
  var edgeLabelSel = g.append("g").attr("class","edge-labels")
    .selectAll("text")
    .data(simEdges.filter(function(e){
      return e.type !== "bottleneck" && e.type !== "ring";
    }))
    .enter().append("text")
      .attr("font-size", 8)
      .attr("fill", "#5a6573")
      .attr("text-anchor", "middle")
      .attr("dy", -3)
      .text(function(e){
        var lbl = e.type.replace("_"," ");
        if (e.confidence) lbl += " " + Math.round(e.confidence*100) + "%";
        return lbl;
      });

  // Nodes
  var nodeSel = g.append("g").attr("class","nodes")
    .selectAll("g")
    .data(simNodes)
    .enter().append("g")
      .attr("cursor","pointer")
      .call(d3.drag()
        .on("start", function(event, d){
          if (!event.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", function(event, d){
          d.fx = event.x; d.fy = event.y;
        })
        .on("end", function(event, d){
          if (!event.active) sim.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
      )
      .on("mousemove", function(event, d){
        var html = '<div class="gt-name">' + esc(d.label) + '</div>';
        if (d.ticker) html += '<div class="gt-dim">' + esc(d.ticker) + '</div>';
        html += '<div class="gt-dim" style="margin-top:3px">Ring: ' + esc(d.kind) + '</div>';
        var cps = d.counterparties || [];
        if (cps.length) {
          html += '<div class="gt-cp"><div class="gt-dim">Counterparties:</div>';
          cps.slice(0,5).forEach(function(cp){
            html += '<div class="gt-cp-row">' +
              esc(cp.name) + (cp.ticker ? " (" + esc(cp.ticker) + ")" : "") +
              ' &mdash; ' + esc(cp.relationship_type || "other") +
              (cp.confidence ? " (" + Math.round(cp.confidence*100) + "%)" : "") +
              '</div>';
          });
          if (cps.length > 5) html += '<div class="gt-cp-row">+' + (cps.length-5) + ' more</div>';
          html += '</div>';
        }
        tooltip.innerHTML = html;
        tooltip.style.display = "block";
        tooltip.style.left = (event.clientX + 14) + "px";
        tooltip.style.top  = (event.clientY - 10) + "px";
      })
      .on("mouseleave", function(){
        tooltip.style.display = "none";
      });

  // Node circles
  var NODE_COLOR_MAP = {
    bottleneck: "#e0a34a",
    ring1:      "#38d2c4",
    ring2:      "#7fc97f",
    ring3:      "#a99be0",
    ring4:      "#e06c75",
    external:   "#667080",
  };
  nodeSel.append("circle")
    .attr("r", function(d){ return d.kind === "bottleneck" ? 18 : 12; })
    .attr("fill", function(d){ return NODE_COLOR_MAP[d.kind] || "#667080"; })
    .attr("fill-opacity", function(d){ return d.kind === "external" ? 0.5 : 0.85; })
    .attr("stroke", function(d){ return NODE_COLOR_MAP[d.kind] || "#667080"; })
    .attr("stroke-width", function(d){ return d.kind === "bottleneck" ? 2 : 1; })
    .attr("stroke-opacity", 0.6);

  // Node labels
  nodeSel.append("text")
    .attr("text-anchor","middle")
    .attr("dy", function(d){ return d.kind === "bottleneck" ? -22 : -16; })
    .attr("font-size", function(d){ return d.kind === "bottleneck" ? 11 : 9; })
    .attr("font-family","ui-monospace,monospace")
    .attr("fill","#d7e0ea")
    .text(function(d){ return d.ticker || d.label.slice(0,8); });

  // Tick
  sim.on("tick", function(){
    edgeSel
      .attr("x1", function(e){ return e.source.x; })
      .attr("y1", function(e){ return e.source.y; })
      .attr("x2", function(e){ return e.target.x; })
      .attr("y2", function(e){ return e.target.y; });

    edgeLabelSel
      .attr("x", function(e){ return (e.source.x + e.target.x)/2; })
      .attr("y", function(e){ return (e.source.y + e.target.y)/2; });

    nodeSel.attr("transform", function(d){
      return "translate(" + d.x + "," + d.y + ")";
    });
  });

  // Legend
  var legEl = document.getElementById("graph-legend-row");
  var LEGEND = [
    { kind:"bottleneck", label:"Bottleneck" },
    { kind:"ring1",      label:"Ring 1 Direct" },
    { kind:"ring2",      label:"Ring 2 Enabling" },
    { kind:"ring3",      label:"Ring 3 Benefiting" },
    { kind:"ring4",      label:"Ring 4 Threatened" },
    { kind:"external",   label:"External counterparty" },
  ];
  legEl.innerHTML = LEGEND.map(function(item){
    var col = NODE_COLOR_MAP[item.kind] || "#667080";
    return '<div class="graph-leg-item">' +
           '<div class="graph-leg-dot" style="background:' + col + '"></div>' +
           esc(item.label) + '</div>';
  }).join("");

  // Status
  var nEdges = simEdges.filter(function(e){
    return e.type !== "bottleneck" && e.type !== "ring";
  }).length;
  document.getElementById("graph-status").textContent =
    data.nodes.length + " nodes, " + nEdges + " relationship edges";

  // Stop sim after settling
  sim.on("end", function(){ sim.stop(); });
}

// ---- Wire graph tab on switch -------------------------------------------
// Patch the tab click handler to also init the graph tab

(function(){
  var _origTabHandler = null;
  // Find the graph tab button and hook it
  var tabs = document.querySelectorAll("nav.tabs button");
  tabs.forEach(function(b){
    if (b.dataset.view === "graph") {
      b.addEventListener("click", function(){
        // Give React/DOM a tick to make the view active before sizing SVG
        setTimeout(function(){
          // Populate picker from latest State.theses
          initGraphTab();
        }, 50);
      });
    }
  });
})();

// === EDGAR enrichment settings hooks ===
'''

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

    # --- Patch 1: Graph nav tab ---
    count = src.count(NAV_ANCHOR)
    if count != 1:
        print("ERROR: nav anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(NAV_ANCHOR, NAV_ANCHOR + "\n" + NAV_INSERTION, 1)

    # --- Patch 2: Graph view div (replace </main>) ---
    count = src.count(VIEW_ANCHOR)
    if count != 1:
        print("ERROR: </main> anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(VIEW_ANCHOR, GRAPH_VIEW, 1)

    # --- Patch 3: CSS ---
    count = src.count(CSS_ANCHOR)
    if count != 1:
        print("ERROR: CSS anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(CSS_ANCHOR, GRAPH_CSS + CSS_ANCHOR, 1)

    # --- Patch 4: Deepen button in EDGAR panel ---
    count = src.count(EDGAR_ANCHOR)
    if count != 1:
        print("ERROR: EDGAR anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(EDGAR_ANCHOR, EDGAR_DEEPEN_REPLACEMENT, 1)

    # --- Patch 5: Graph JS (replaces the EDGAR settings comment anchor) ---
    count = src.count(JS_ANCHOR)
    if count != 1:
        print("ERROR: JS anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(JS_ANCHOR, GRAPH_JS, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)

    print("Patched {} successfully.".format(TARGET))
    print("Added: Graph tab nav, graph view div, graph CSS, deepen button, graph JS")


if __name__ == "__main__":
    main()
