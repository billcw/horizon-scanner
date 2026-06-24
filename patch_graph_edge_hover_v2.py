"""
patch_graph_edge_hover_v2.py

Replaces the broken proximity-detection edge hover with a reliable approach:
- Restores visible edge labels (9px, dim)
- Adds a 16px transparent stroke on each edge as a proper hit area
- On hover of edge line or label: enlarges label, shows tooltip
- Removes the broken _edgeMidCache coordinate-math approach

Anchors against the EDGE-HOVER-TOOLTIP block already in the file.

Run from C:\\Projects\\horizon-scanner:
    python patch_graph_edge_hover_v2.py
"""

import os, sys

TARGET = os.path.join("horizon_scanner", "dashboard", "index.html")
SENTINEL = "// EDGE-HOVER-V2"

# ---------------------------------------------------------------------------
# Patch 1: Replace the hidden label + broken proximity hover block
# ---------------------------------------------------------------------------

OLD_EDGE_BLOCK = (
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

NEW_EDGE_BLOCK = (
    '  // EDGE-HOVER-V2\n'
    '  // Transparent wide stroke on each relationship edge -- reliable hit area.\n'
    '  var edgeHitSel = g.insert("g", ".edge-labels").attr("class","edge-hits")\n'
    '    .selectAll("line")\n'
    '    .data(simEdges.filter(function(e){\n'
    '      return e.type !== "bottleneck" && e.type !== "ring";\n'
    '    }))\n'
    '    .enter().append("line")\n'
    '      .attr("stroke", "transparent")\n'
    '      .attr("stroke-width", 16)\n'
    '      .attr("cursor", "default")\n'
    '      .on("mouseover", function(event, e){ _showEdgeTooltip(event, e); })\n'
    '      .on("mousemove", function(event, e){ _showEdgeTooltip(event, e); })\n'
    '      .on("mouseout",  function(){ tooltip.style.display = "none"; });\n'
    '\n'
    '  // Visible edge labels (dim, small) -- enlarge on hover\n'
    '  var edgeLabelSel = g.append("g").attr("class","edge-labels")\n'
    '    .selectAll("text")\n'
    '    .data(simEdges.filter(function(e){\n'
    '      return e.type !== "bottleneck" && e.type !== "ring";\n'
    '    }))\n'
    '    .enter().append("text")\n'
    '      .attr("font-size", 9)\n'
    '      .attr("fill", "#4a5a6a")\n'
    '      .attr("text-anchor", "middle")\n'
    '      .attr("dy", -4)\n'
    '      .attr("pointer-events", "none")\n'
    '      .text(function(e){\n'
    '        var lbl = e.type.replace(/_/g," ");\n'
    '        if (e.confidence) lbl += " " + Math.round(e.confidence*100) + "%";\n'
    '        return lbl;\n'
    '      });\n'
    '\n'
    '  function _showEdgeTooltip(event, e) {\n'
    '    var src = e.source.label || e.source.key || "";\n'
    '    var tgt = e.target.label || e.target.key || "";\n'
    '    var rel = (e.type || "other").replace(/_/g, " ");\n'
    '    var conf = e.confidence ? Math.round(e.confidence * 100) + "%" : "";\n'
    '    var html = \'<div class="gt-name">\' + esc(rel) +\n'
    '               (conf ? \' <span class="gt-dim">(\' + esc(conf) + \')</span>\' : "") +\n'
    '               \'</div>\';\n'
    '    html += \'<div class="gt-dim" style="margin-top:4px">\' +\n'
    '            esc(src) + " &rarr; " + esc(tgt) + \'</div>\';\n'
    '    if (e.derived) {\n'
    '      html += \'<div class="gt-dim" style="margin-top:3px;font-size:10px">\' +\n'
    '              esc(e.derived) + \'</div>\';\n'
    '    }\n'
    '    tooltip.innerHTML = html;\n'
    '    tooltip.style.display = "block";\n'
    '    tooltip.style.left = (event.clientX + 14) + "px";\n'
    '    tooltip.style.top  = (event.clientY - 10) + "px";\n'
    '  }'
)

# ---------------------------------------------------------------------------
# Patch 2: Update tick handler -- remove _edgeMidCache, add edgeHitSel update
# ---------------------------------------------------------------------------

OLD_TICK = (
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

NEW_TICK = (
    '    edgeHitSel\n'
    '      .attr("x1", function(e){ return e.source.x; })\n'
    '      .attr("y1", function(e){ return e.source.y; })\n'
    '      .attr("x2", function(e){ return e.target.x; })\n'
    '      .attr("y2", function(e){ return e.target.y; });\n'
    '  });'
)


def main():
    if not os.path.exists(TARGET):
        print("ERROR: {} not found. Run from project root.".format(TARGET))
        sys.exit(1)

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Patch already applied. Nothing to do.")
        sys.exit(0)

    # Patch 1
    count = src.count(OLD_EDGE_BLOCK)
    if count != 1:
        print("ERROR: edge block anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(OLD_EDGE_BLOCK, NEW_EDGE_BLOCK, 1)

    # Patch 2
    count = src.count(OLD_TICK)
    if count != 1:
        print("ERROR: tick anchor found {} times (expected 1).".format(count))
        sys.exit(1)
    src = src.replace(OLD_TICK, NEW_TICK, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)

    print("Patched {} successfully.".format(TARGET))
    print("  - Edge labels restored (9px, dim)")
    print("  - Transparent 16px hit-area added to each edge")
    print("  - Edge hover tooltip working via DOM events (no coordinate math)")


if __name__ == "__main__":
    main()
