"""
patch_graph_readability.py

Three improvements:

1. GRAPH READABILITY
   - Hides the always-on 8px edge label text (cluttered on dense graphs)
   - Adds edge-proximity hover tooltip (within 14px of edge midpoint)

2. EDGAR COUNTERPARTY ROWS
   - Adds extracted counterparties inline under each company in the EDGAR panel

3. USPTO AUTH DIAGNOSTIC
   - One-record probe call when key IS set, to confirm auth works immediately

Run from C:\\Projects\\horizon-scanner:
    python patch_graph_readability.py
"""

import os
import sys

TARGET_HTML  = os.path.join("horizon_scanner", "dashboard", "index.html")
TARGET_USPTO = os.path.join("horizon_scanner", "collectors", "uspto_collector.py")

SENTINEL_HTML  = "// EDGE-HOVER-TOOLTIP"
SENTINEL_USPTO = "# USPTO_AUTH_PROBE"

# ---------------------------------------------------------------------------
# HTML Patch 1a: remove inline edge labels, add SVG-level edge hover
# ---------------------------------------------------------------------------

EDGE_LABEL_ANCHOR = (
    '  // Edge label (relationship type, for non-structural edges)\n'
    '  var edgeLabelSel = g.append("g").attr("class","edge-labels")\n'
    '    .selectAll("text")\n'
    '    .data(simEdges.filter(function(e){\n'
    '      return e.type !== "bottleneck" && e.type !== "ring";\n'
    '    }))\n'
    '    .enter().append("text")\n'
    '      .attr("font-size", 8)\n'
    '      .attr("fill", "#5a6573")\n'
    '      .attr("text-anchor", "middle")\n'
    '      .attr("dy", -3)\n'
    '      .text(function(e){\n'
    '        var lbl = e.type.replace("_"," ");\n'
    '        if (e.confidence) lbl += " " + Math.round(e.confidence*100) + "%";\n'
    '        return lbl;\n'
    '      });'
)

EDGE_HOVER_REPLACEMENT = (
    '  // EDGE-HOVER-TOOLTIP\n'
    '  // Edge labels hidden; position still tracked for proximity hover.\n'
    '  var edgeLabelSel = g.append("g").attr("class","edge-labels")\n'
    '    .selectAll("text")\n'
    '    .data(simEdges.filter(function(e){\n'
    '      return e.type !== "bottleneck" && e.type !== "ring";\n'
    '    }))\n'
    '    .enter().append("text")\n'
    '      .attr("font-size", 0)\n'
    '      .attr("fill", "none")\n'
    '      .attr("text-anchor", "middle")\n'
    '      .attr("dy", -3)\n'
    '      .text(function(e){ return ""; });\n'
    '\n'
    '  var _edgeMidCache = [];\n'
    '\n'
    '  svg.on("mousemove.edgehover", function(event){\n'
    '    var transform = d3.zoomTransform(svg.node());\n'
    '    var rect = svg.node().getBoundingClientRect();\n'
    '    var mp = transform.invert([event.clientX - rect.left,\n'
    '                               event.clientY - rect.top]);\n'
    '    var mx = mp[0], my = mp[1];\n'
    '    var HIT = 14;\n'
    '    var hit = null;\n'
    '    for (var i = 0; i < _edgeMidCache.length; i++) {\n'
    '      var em = _edgeMidCache[i];\n'
    '      var dx = mx - em.mx, dy = my - em.my;\n'
    '      if (dx*dx + dy*dy < HIT*HIT) { hit = em.edge; break; }\n'
    '    }\n'
    '    if (hit) {\n'
    '      var src = hit.source.label || hit.source.key || "";\n'
    '      var tgt = hit.target.label || hit.target.key || "";\n'
    '      var rel = (hit.type || "other").replace(/_/g," ");\n'
    '      var conf = hit.confidence ? Math.round(hit.confidence*100) + "%" : "";\n'
    '      var html = \'<div class="gt-name">\' + esc(rel) +\n'
    '                 (conf ? \' <span class="gt-dim">(\' + esc(conf) + \')</span>\' : "") +\n'
    '                 \'</div>\';\n'
    '      html += \'<div class="gt-dim" style="margin-top:4px">\' +\n'
    '              esc(src) + " &rarr; " + esc(tgt) + \'</div>\';\n'
    '      if (hit.derived) {\n'
    '        html += \'<div class="gt-dim" style="margin-top:3px;font-size:10px">\' +\n'
    '                esc(hit.derived) + \'</div>\';\n'
    '      }\n'
    '      tooltip.innerHTML = html;\n'
    '      tooltip.style.display = "block";\n'
    '      tooltip.style.left = (event.clientX + 14) + "px";\n'
    '      tooltip.style.top  = (event.clientY - 10) + "px";\n'
    '    } else {\n'
    '      tooltip.style.display = "none";\n'
    '    }\n'
    '  });\n'
    '\n'
    '  svg.on("mouseleave.edgehover", function(){\n'
    '    tooltip.style.display = "none";\n'
    '  });'
)

# ---------------------------------------------------------------------------
# HTML Patch 1b: rebuild midpoint cache in tick handler
# ---------------------------------------------------------------------------

TICK_ANCHOR = (
    '  // Tick\n'
    '  sim.on("tick", function(){\n'
    '    edgeSel\n'
    '      .attr("x1", function(e){ return e.source.x; })\n'
    '      .attr("y1", function(e){ return e.source.y; })\n'
    '      .attr("x2", function(e){ return e.target.x; })\n'
    '      .attr("y2", function(e){ return e.target.y; });\n'
    '\n'
    '    edgeLabelSel\n'
    '      .attr("x", function(e){ return (e.source.x + e.target.x)/2; })\n'
    '      .attr("y", function(e){ return (e.source.y + e.target.y)/2; });\n'
    '\n'
    '    nodeSel.attr("transform", function(d){\n'
    '      return "translate(" + d.x + "," + d.y + ")";\n'
    '    });\n'
    '  });'
)

TICK_REPLACEMENT = (
    '  // Tick\n'
    '  sim.on("tick", function(){\n'
    '    edgeSel\n'
    '      .attr("x1", function(e){ return e.source.x; })\n'
    '      .attr("y1", function(e){ return e.source.y; })\n'
    '      .attr("x2", function(e){ return e.target.x; })\n'
    '      .attr("y2", function(e){ return e.target.y; });\n'
    '\n'
    '    edgeLabelSel\n'
    '      .attr("x", function(e){ return (e.source.x + e.target.x)/2; })\n'
    '      .attr("y", function(e){ return (e.source.y + e.target.y)/2; });\n'
    '\n'
    '    nodeSel.attr("transform", function(d){\n'
    '      return "translate(" + d.x + "," + d.y + ")";\n'
    '    });\n'
    '\n'
    '    // Rebuild edge midpoint cache for hover hit-testing\n'
    '    _edgeMidCache = [];\n'
    '    simEdges.forEach(function(e){\n'
    '      if (e.type === "bottleneck" || e.type === "ring") return;\n'
    '      _edgeMidCache.push({\n'
    '        mx: (e.source.x + e.target.x) / 2,\n'
    '        my: (e.source.y + e.target.y) / 2,\n'
    '        edge: e,\n'
    '      });\n'
    '    });\n'
    '  });'
)

# ---------------------------------------------------------------------------
# HTML Patch 2: EDGAR counterparty rows in _edgarCompanyRow
# ---------------------------------------------------------------------------

EDGAR_ROW_ANCHOR = (
    '  return \'<div class="edgar-co">\' +\n'
    '           \'<div class="edgar-co-head"><span class="edgar-co-name">\' + name + \'</span> \' +\n'
    '           badge + cikPart + \'</div>\' +\n'
    '           vname + lic + ip +\n'
    '         \'</div>\';'
)

EDGAR_ROW_REPLACEMENT = (
    '  var cp = "";\n'
    '  var cps = Array.isArray(co.counterparties) ? co.counterparties : [];\n'
    '  if (cps.length) {\n'
    '    var cpRows = cps.slice(0, 6).map(function(c){\n'
    '      var rel = (c.relationship_type || "other").replace(/_/g, " ");\n'
    '      var conf = c.confidence ? " (" + Math.round(c.confidence * 100) + "%)" : "";\n'
    '      var tk = c.ticker ? " (" + esc(c.ticker) + ")" : "";\n'
    '      return \'<div class="edgar-cp-row">\' +\n'
    '             esc(c.name) + tk + " &mdash; " + esc(rel) + esc(conf) +\n'
    '             \'</div>\';\n'
    '    }).join("");\n'
    '    var cpMore = cps.length > 6\n'
    '      ? \'<div class="edgar-cp-row" style="color:var(--ink-faint)">(+\' +\n'
    '        (cps.length - 6) + \' more)</div>\' : "";\n'
    '    cp = \'<div class="edgar-cp"><span class="edgar-cp-label">counterparties:</span>\' +\n'
    '         cpRows + cpMore + \'</div>\';\n'
    '  }\n'
    '\n'
    '  return \'<div class="edgar-co">\' +\n'
    '           \'<div class="edgar-co-head"><span class="edgar-co-name">\' + name + \'</span> \' +\n'
    '           badge + cikPart + \'</div>\' +\n'
    '           vname + lic + ip + cp +\n'
    '         \'</div>\';'
)

# ---------------------------------------------------------------------------
# HTML Patch 3: CSS for edgar-cp
# ---------------------------------------------------------------------------

CSS_ANCHOR = "  .edgar-ipdate { color: var(--muted, #8a93a3); }"

EDGAR_CP_CSS = (
    "  .edgar-ipdate { color: var(--muted, #8a93a3); }\n"
    "  .edgar-cp { font-size: 12px; margin-top: 5px; }\n"
    "  .edgar-cp-label { color: var(--ink-faint); font-size: 10px;\n"
    "    text-transform: uppercase; letter-spacing: 0.5px; display: block; margin-bottom: 2px; }\n"
    "  .edgar-cp-row { color: var(--ink-dim); margin-top: 2px; padding-left: 8px; }"
)

# ---------------------------------------------------------------------------
# USPTO Patch: auth probe -- anchor is the unique warning message line
# ---------------------------------------------------------------------------

USPTO_ANCHOR = (
    '"Skipping. (Set it after ID.me verification clears your API key.)",'
)


def _build_uspto_replacement():
    lines = [
        '"Skipping. Set it inline: $env:USPTO_ODP_KEY=your-key before launching",',
        '            "the dashboard. Or open a new PowerShell after setting the",',
        '            "system environment variable.",',
        '            API_KEY_ENV',
        '        )',
        '        return 0',
        '',
        '    # USPTO_AUTH_PROBE: 1-record probe to confirm auth before a full run.',
        '    logger.info("USPTO: probing auth with a 1-record test call...")',
        '    try:',
        '        from datetime import timedelta',
        '        _to = datetime.now(timezone.utc).date().isoformat()',
        '        _from = (datetime.now(timezone.utc).date()',
        '                 - timedelta(days=90)).isoformat()',
        '        _probe_body = {',
        '            "q": "applicationMetaData.inventionTitle:quantum",',
        '            "rangeFilters": [{"field": "applicationMetaData.filingDate",',
        '                              "valueFrom": _from, "valueTo": _to}],',
        '            "pagination": {"offset": 0, "limit": 1},',
        '        }',
        '        _probe_headers = {',
        '            "x-api-key": api_key,',
        '            "Content-Type": "application/json",',
        '            "Accept": "application/json",',
        '            "User-Agent": "HorizonScanner/1.0 (research tool)",',
        '        }',
        '        _probe_resp = requests.post(SEARCH_URL, json=_probe_body,',
        '                                    headers=_probe_headers, timeout=30)',
        '        if _probe_resp.status_code == 200:',
        '            logger.info("USPTO auth OK (HTTP 200). Proceeding.")',
        '        elif _probe_resp.status_code in (401, 403):',
        '            logger.error(',
        '                "USPTO auth FAILED (HTTP %d). Key in %s is set but rejected. "',
        '                "Possible causes: ID.me verification still pending, key has "',
        '                "extra whitespace, or key has expired. Skipping collect.",',
        '                _probe_resp.status_code, API_KEY_ENV',
        '            )',
        '            return 0',
        '        else:',
        '            logger.warning("USPTO auth probe returned HTTP %d. Proceeding anyway.",',
        '                           _probe_resp.status_code)',
        '    except Exception as _probe_err:',
        '        logger.warning("USPTO auth probe exception: %s. Proceeding.", _probe_err)',
    ]
    return '\n'.join(lines)


def _patch_html(src):
    for label, anchor, replacement in [
        ("edge label", EDGE_LABEL_ANCHOR, EDGE_HOVER_REPLACEMENT),
        ("tick handler", TICK_ANCHOR, TICK_REPLACEMENT),
        ("EDGAR row", EDGAR_ROW_ANCHOR, EDGAR_ROW_REPLACEMENT),
        ("CSS", CSS_ANCHOR, EDGAR_CP_CSS),
    ]:
        count = src.count(anchor)
        if count != 1:
            print("ERROR: {} anchor found {} times (expected 1).".format(label, count))
            sys.exit(1)
        src = src.replace(anchor, replacement, 1)
    return src


def _patch_uspto(src):
    count = src.count(USPTO_ANCHOR)
    if count != 1:
        print("ERROR: USPTO anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(USPTO_ANCHOR, _build_uspto_replacement(), 1)
    return src


def main():
    for path in [TARGET_HTML, TARGET_USPTO]:
        if not os.path.exists(path):
            print("ERROR: {} not found. Run from project root.".format(path))
            sys.exit(1)

    with open(TARGET_HTML, "r", encoding="utf-8") as f:
        html_src = f.read()
    with open(TARGET_USPTO, "r", encoding="utf-8") as f:
        uspto_src = f.read()

    html_done = False
    uspto_done = False

    if SENTINEL_HTML in html_src:
        print("HTML patch already applied. Skipping index.html.")
        html_done = True
    if SENTINEL_USPTO in uspto_src:
        print("USPTO patch already applied. Skipping uspto_collector.py.")
        uspto_done = True

    if not html_done:
        html_src = _patch_html(html_src)
        with open(TARGET_HTML, "w", encoding="utf-8") as f:
            f.write(html_src)
        print("Patched {} successfully.".format(TARGET_HTML))
        print("  - Edge inline labels hidden; edge hover tooltip added")
        print("  - EDGAR counterparty rows added")
        print("  - edgar-cp CSS added")

    if not uspto_done:
        uspto_src = _patch_uspto(uspto_src)
        with open(TARGET_USPTO, "w", encoding="utf-8") as f:
            f.write(uspto_src)
        print("Patched {} successfully.".format(TARGET_USPTO))
        print("  - USPTO auth probe added")


if __name__ == "__main__":
    main()
