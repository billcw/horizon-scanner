"""
patch_graph_edge_hover.py

Improves graph edge labels and adds reliable hover tooltips:

1. Keeps edge labels visible (9px, dim) at the midpoint of each edge
2. Adds a thick transparent stroke on each edge line as a hit area --
   standard D3 pattern, reliable across zoom/pan without coordinate math
3. On edge hover (line or label): enlarges the label to 13px, brightens it,
   and shows the full tooltip (relationship, confidence, source -> target)
4. On edge mouseout: restores label to normal

Also fixes the _run_deepen_job / _run_enrich_job rfile bug in server.py:
those jobs called self._read_json_body() in a background thread after the
HTTP connection was closed. The fix: pass thesis_id as a direct argument
instead of re-reading the request body.

Run from C:\\Projects\\horizon-scanner:
    python patch_graph_edge_hover.py
"""

import os
import sys

TARGET_HTML   = os.path.join("horizon_scanner", "dashboard", "index.html")
TARGET_SERVER = os.path.join("horizon_scanner", "dashboard", "server.py")

SENTINEL_HTML   = "// EDGE-HOVER-V2"
SENTINEL_SERVER = "# RFILE-BUG-FIXED"

# ---------------------------------------------------------------------------
# HTML Patch 1: Replace edge label block + add hit-area lines + hover
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
    '  // EDGE-HOVER-V2\n'
    '  // Visible edge labels at midpoint\n'
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
    '      .attr("pointer-events", "all")\n'
    '      .attr("cursor", "default")\n'
    '      .text(function(e){\n'
    '        var lbl = e.type.replace(/_/g," ");\n'
    '        if (e.confidence) lbl += " " + Math.round(e.confidence*100) + "%";\n'
    '        return lbl;\n'
    '      })\n'
    '      .on("mouseover", function(event, e){\n'
    '        d3.select(this).attr("font-size", 13).attr("fill", "#d7e0ea");\n'
    '        _showEdgeTooltip(event, e);\n'
    '      })\n'
    '      .on("mousemove", function(event, e){\n'
    '        _showEdgeTooltip(event, e);\n'
    '      })\n'
    '      .on("mouseout", function(event, e){\n'
    '        d3.select(this).attr("font-size", 9).attr("fill", "#4a5a6a");\n'
    '        tooltip.style.display = "none";\n'
    '      });\n'
    '\n'
    '  // Invisible thick stroke on each relationship edge as a reliable hit area\n'
    '  var edgeHitSel = g.insert("g", ".edge-labels").attr("class","edge-hits")\n'
    '    .selectAll("line")\n'
    '    .data(simEdges.filter(function(e){\n'
    '      return e.type !== "bottleneck" && e.type !== "ring";\n'
    '    }))\n'
    '    .enter().append("line")\n'
    '      .attr("stroke", "transparent")\n'
    '      .attr("stroke-width", 16)\n'
    '      .attr("cursor", "default")\n'
    '      .on("mouseover", function(event, e){\n'
    '        _showEdgeTooltip(event, e);\n'
    '      })\n'
    '      .on("mousemove", function(event, e){\n'
    '        _showEdgeTooltip(event, e);\n'
    '      })\n'
    '      .on("mouseout", function(){\n'
    '        tooltip.style.display = "none";\n'
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
# HTML Patch 2: add edgeHitSel to tick handler
# ---------------------------------------------------------------------------

TICK_ANCHOR = (
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
    '    edgeLabelSel\n'
    '      .attr("x", function(e){ return (e.source.x + e.target.x)/2; })\n'
    '      .attr("y", function(e){ return (e.source.y + e.target.y)/2; });\n'
    '\n'
    '    edgeHitSel\n'
    '      .attr("x1", function(e){ return e.source.x; })\n'
    '      .attr("y1", function(e){ return e.source.y; })\n'
    '      .attr("x2", function(e){ return e.target.x; })\n'
    '      .attr("y2", function(e){ return e.target.y; });\n'
    '\n'
    '    nodeSel.attr("transform", function(d){\n'
    '      return "translate(" + d.x + "," + d.y + ")";\n'
    '    });\n'
    '  });'
)

# ---------------------------------------------------------------------------
# Server Patch: fix rfile bug in _run_deepen_job and _run_enrich_job
# Both jobs incorrectly called self._read_json_body() in a background thread.
# The thesis_id is already parsed in the handler -- pass it as argument.
# ---------------------------------------------------------------------------

# Deepen job: remove the body = self._read_json_body() call
DEEPEN_BUG_ANCHOR = (
    '        import json as _json\n'
    '\n'
    '        def _set(**kw):\n'
    '            with _JOBS_LOCK:\n'
    '                _JOBS[job_id].update(kw)\n'
    '\n'
    '        try:\n'
    '            from ..enrichment.edgar_client import deepen_counterparties\n'
    '\n'
    '            # Load ring data from DB\n'
    '            with db.get_connection() as conn:\n'
    '                row = conn.execute(\n'
    '                    "SELECT entities_ring1, entities_ring2, "\n'
    '                    "       entities_ring3, entities_ring4 "\n'
    '                    "FROM theses WHERE id = ?",\n'
    '                    (thesis_id,),\n'
    '                ).fetchone()'
)

DEEPEN_BUG_ANCHOR_CHECK = "from ..enrichment.edgar_client import deepen_counterparties"

# Enrich job: same pattern
ENRICH_BUG_ANCHOR_CHECK = "from ..enrichment.edgar_client import ("


def _fix_rfile_bug(src):
    # Check for the bad pattern: _read_json_body() inside a _run_*_job method
    # The bug: these methods call self._read_json_body() but the socket is closed.
    # The thesis_id is already available as a parameter -- just use it directly.
    # We patch by removing the body = self._read_json_body() lines that appear
    # inside _run_deepen_job and _run_enrich_job.

    # Both job runners receive thesis_id as a parameter already.
    # The bug line pattern is: "        body = self._read_json_body()"
    # followed by using body.get("thesis_id"). Since thesis_id is already
    # a parameter, we just remove those two lines.

    BAD_PATTERN = '        body = self._read_json_body()\n'
    if BAD_PATTERN not in src:
        print("  Server: rfile bug pattern not found -- may already be fixed.")
        return src

    # Count occurrences -- should be in deepen and enrich jobs
    count = src.count(BAD_PATTERN)
    print("  Server: found {} occurrence(s) of rfile bug pattern.".format(count))

    # Remove the bad lines. Each is followed by lines that use body.get(...)
    # which we also need to remove since thesis_id is already a parameter.
    import re
    # Pattern: body = self._read_json_body() then thesis_id = body.get(...)
    bad_re = re.compile(
        r'        body = self\._read_json_body\(\)\n'
        r'        thesis_id = \(body\.get\("thesis_id"\) or ""\)\.strip\(\)\n'
    )
    new_src = bad_re.sub('', src)
    removed = src.count('\n') - new_src.count('\n')
    if removed > 0:
        print("  Server: removed {} bug lines.".format(removed))
        src = new_src
    else:
        print("  Server: regex did not match body+thesis_id lines; skipping server patch.")
    return src


def main():
    for path in [TARGET_HTML, TARGET_SERVER]:
        if not os.path.exists(path):
            print("ERROR: {} not found. Run from project root.".format(path))
            sys.exit(1)

    with open(TARGET_HTML, "r", encoding="utf-8") as f:
        html_src = f.read()
    with open(TARGET_SERVER, "r", encoding="utf-8") as f:
        srv_src = f.read()

    # --- HTML patch ---
    if SENTINEL_HTML in html_src:
        print("HTML edge hover patch already applied. Skipping.")
    else:
        # Patch 1: edge label + hover
        count = html_src.count(EDGE_LABEL_ANCHOR)
        if count != 1:
            print("ERROR: edge label anchor found {} times (expected 1).".format(count))
            sys.exit(1)
        html_src = html_src.replace(EDGE_LABEL_ANCHOR, EDGE_HOVER_REPLACEMENT, 1)

        # Patch 2: tick handler update
        count = html_src.count(TICK_ANCHOR)
        if count != 1:
            print("ERROR: tick anchor found {} times (expected 1).".format(count))
            sys.exit(1)
        html_src = html_src.replace(TICK_ANCHOR, TICK_REPLACEMENT, 1)

        with open(TARGET_HTML, "w", encoding="utf-8") as f:
            f.write(html_src)
        print("Patched {}: edge labels visible + hover tooltips added".format(TARGET_HTML))

    # --- Server patch ---
    if SENTINEL_SERVER in srv_src:
        print("Server rfile patch already applied. Skipping.")
    else:
        orig_len = len(srv_src)
        srv_src = _fix_rfile_bug(srv_src)
        if len(srv_src) != orig_len:
            # Mark as fixed
            srv_src = srv_src.replace(
                "import json as _json",
                "import json as _json  # RFILE-BUG-FIXED",
                1
            )
            with open(TARGET_SERVER, "w", encoding="utf-8") as f:
                f.write(srv_src)
            print("Patched {}: rfile bug removed from background jobs".format(TARGET_SERVER))
        else:
            print("Server: no changes made (bug may already be fixed or pattern differs).")


if __name__ == "__main__":
    main()
