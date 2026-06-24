import ast, sys

path = r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\index.html"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

SENTINEL = "THESIS-VERSIONING-UI"
if SENTINEL in src:
    print("Patch already applied. Nothing to do.")
    sys.exit(0)

# --- Change 1: CSS for version history ---
OLD1 = '  .edgar-panel { display: flex; flex-direction: column; gap: 14px; }'
NEW1 = (
    '  .edgar-panel { display: flex; flex-direction: column; gap: 14px; }\n'
    '  /* THESIS-VERSIONING-UI */\n'
    '  .ver-timeline { display:flex; flex-direction:column; gap:8px; margin-top:8px; }\n'
    '  .ver-row { background:var(--surface2); border-radius:6px; padding:10px 14px; cursor:pointer; }\n'
    '  .ver-row:hover { background:var(--surface3,#2a2a3a); }\n'
    '  .ver-meta { font-size:11px; color:var(--ink-dim); margin-bottom:4px; }\n'
    '  .ver-deltas { display:flex; gap:16px; flex-wrap:wrap; }\n'
    '  .ver-delta { font-size:12px; }\n'
    '  .ver-delta.changed { color:var(--signal); }\n'
    '  .ver-delta.same { color:var(--ink-dim); }\n'
    '  .ver-detail { display:none; margin-top:10px; font-size:12px; color:var(--ink-dim);\n'
    '                border-top:1px solid var(--border); padding-top:8px; }\n'
    '  .ver-detail.open { display:block; }\n'
    '  .ver-empty { color:var(--ink-dim); font-size:13px; padding:8px 0; }'
)
count1 = src.count(OLD1)
if count1 != 1:
    print(f"ERROR: anchor 1 found {count1} times. Aborting.")
    sys.exit(1)
src = src.replace(OLD1, NEW1, 1)

# --- Change 2: Version History section between EDGAR and Scenario Tree ---
OLD2 = ('    <section class="block">\n'
        '      <h3>Scenario Tree</h3>')
NEW2 = (
    '    <section class="block">\n'
    '      <h3 style="cursor:pointer;user-select:none" id="ver-toggle"\n'
    '          onclick="toggleVersionHistory(this)">Version History &#9656;</h3>\n'
    '      <div id="ver-history-wrap" style="display:none">\n'
    '        <div style="margin-bottom:10px">\n'
    '          <button class="ghost" id="ver-rerun-btn"\n'
    '                  onclick="triggerRerun()">Re-run thesis loop</button>\n'
    '          <span id="ver-rerun-status" style="font-size:12px;color:var(--ink-dim);margin-left:10px"></span>\n'
    '        </div>\n'
    '        <div class="ver-timeline" id="ver-timeline">\n'
    '          <div class="ver-empty">Expand to load version history.</div>\n'
    '        </div>\n'
    '      </div>\n'
    '    </section>\n'
    '\n'
    '    <section class="block">\n'
    '      <h3>Scenario Tree</h3>'
)
count2 = src.count(OLD2)
if count2 != 1:
    print(f"ERROR: anchor 2 found {count2} times. Aborting.")
    sys.exit(1)
src = src.replace(OLD2, NEW2, 1)

# --- Change 3: track current thesis id after render ---
OLD3 = '  drawLegend(t);\n  wireDecisionDock(t);\n}'
NEW3 = '  drawLegend(t);\n  wireDecisionDock(t);\n  _currentThesisId = t.id;\n}'
count3 = src.count(OLD3)
if count3 != 1:
    print(f"ERROR: anchor 3 found {count3} times. Aborting.")
    sys.exit(1)
src = src.replace(OLD3, NEW3, 1)

# --- Change 4: add JS functions before _edgarApplyConfig ---
OLD4 = 'function _edgarApplyConfig(cfg) {'
NEW4 = (
    '// === Thesis versioning ===\n'
    'var _currentThesisId = null;\n'
    'var _rerunPollTimer = null;\n'
    '\n'
    'function toggleVersionHistory(hdr) {\n'
    '  var wrap = document.getElementById("ver-history-wrap");\n'
    '  if (!wrap) return;\n'
    '  var open = wrap.style.display !== "none";\n'
    '  wrap.style.display = open ? "none" : "block";\n'
    '  hdr.innerHTML = open ? "Version History &#9656;" : "Version History &#9662;";\n'
    '  if (!open && _currentThesisId) loadVersionHistory(_currentThesisId);\n'
    '}\n'
    '\n'
    'function loadVersionHistory(thesisId) {\n'
    '  var tl = document.getElementById("ver-timeline");\n'
    '  if (!tl) return;\n'
    '  tl.innerHTML = \'<div class="ver-empty">Loading...</div>\';\n'
    '  api("/api/thesis/" + thesisId + "/versions")\n'
    '    .then(function(data) {\n'
    '      var versions = data.versions || [];\n'
    '      if (versions.length === 0) {\n'
    '        tl.innerHTML = \'<div class="ver-empty">No prior versions. Re-run the thesis loop to create the first snapshot.</div>\';\n'
    '        return;\n'
    '      }\n'
    '      tl.innerHTML = "";\n'
    '      versions.slice().reverse().forEach(function(v) {\n'
    '        var snap     = v.snapshot || {};\n'
    '        var current  = State.theses.find(function(t){ return t.id === thesisId; }) || {};\n'
    '        var scoreOld = parseFloat(snap.thesis_quality_score) || 0;\n'
    '        var scoreNew = parseFloat(current.thesis_quality_score) || 0;\n'
    '        var scoreDelta = (scoreNew - scoreOld).toFixed(1);\n'
    '        var confOld  = snap.confidence_rating || "-";\n'
    '        var confNew  = current.confidence_rating || "-";\n'
    '        var bnOld    = snap.bottleneck_entity || "-";\n'
    '        var bnNew    = current.bottleneck_entity || "-";\n'
    '        var dt       = (v.snapshotted_at||"").substring(0,16).replace("T"," ");\n'
    '        var scoreClass = Math.abs(parseFloat(scoreDelta)) > 0.5 ? "changed" : "same";\n'
    '        var confClass  = confOld !== confNew ? "changed" : "same";\n'
    '        var bnClass    = bnOld   !== bnNew   ? "changed" : "same";\n'
    '        var detailId   = "ver-detail-" + v.version_number;\n'
    '        var row = document.createElement("div");\n'
    '        row.className = "ver-row";\n'
    '        var killList = [];\n'
    '        try { killList = JSON.parse(snap.kill_criteria || "[]"); } catch(e) {}\n'
    '        row.innerHTML =\n'
    '          \'<div class="ver-meta">v\' + v.version_number\n'
    '          + \' &mdash; \' + esc(dt)\n'
    '          + \' &mdash; \' + esc(v.trigger||"manual_rerun") + \'</div>\'\n'
    '          + \'<div class="ver-deltas">\'\n'
    '          + \'<span class="ver-delta \' + scoreClass + \'">Score: \'\n'
    '            + scoreOld.toFixed(1) + \' &rarr; \' + scoreNew.toFixed(1)\n'
    '            + \' (\' + (parseFloat(scoreDelta)>=0?"+":"") + scoreDelta + \')</span>\'\n'
    '          + \'<span class="ver-delta \' + confClass + \'">Confidence: \'\n'
    '            + esc(confOld) + \' &rarr; \' + esc(confNew) + \'</span>\'\n'
    '          + \'<span class="ver-delta \' + bnClass + \'">Bottleneck: \'\n'
    '            + esc(bnOld) + \' &rarr; \' + esc(bnNew) + \'</span>\'\n'
    '          + \'</div>\'\n'
    '          + \'<div class="ver-detail" id="\' + detailId + \'">\'\n'
    '          + \'<b>Adversarial summary (v\' + v.version_number + \'):</b><br>\'\n'
    '          + esc(snap.adversarial_summary || "None") + \'<br><br>\'\n'
    '          + \'<b>Kill criteria (v\' + v.version_number + \'):</b><br>\'\n'
    '          + esc(killList.join("; ") || "None") + \'</div>\';\n'
    '        row.onclick = function() {\n'
    '          var el = document.getElementById(detailId);\n'
    '          if (el) el.classList.toggle("open");\n'
    '        };\n'
    '        tl.appendChild(row);\n'
    '      });\n'
    '    })\n'
    '    .catch(function() {\n'
    '      tl.innerHTML = \'<div class="ver-empty">Failed to load versions.</div>\';\n'
    '    });\n'
    '}\n'
    '\n'
    'function triggerRerun() {\n'
    '  if (!_currentThesisId) return;\n'
    '  var btn = document.getElementById("ver-rerun-btn");\n'
    '  var st  = document.getElementById("ver-rerun-status");\n'
    '  if (btn) { btn.disabled = true; btn.textContent = "Running..."; }\n'
    '  if (st)  { st.textContent = ""; }\n'
    '  api("/api/thesis/rerun", {\n'
    '    method: "POST",\n'
    '    headers: {"Content-Type": "application/json"},\n'
    '    body: JSON.stringify({thesis_id: _currentThesisId, trigger: "manual_rerun"})\n'
    '  }).then(function(data) {\n'
    '    if (data.ok) {\n'
    '      pollRerun(data.job_id, _currentThesisId);\n'
    '    } else {\n'
    '      if (btn) { btn.disabled = false; btn.textContent = "Re-run thesis loop"; }\n'
    '      if (st)  { st.textContent = "Error: " + (data.error || "unknown"); }\n'
    '    }\n'
    '  }).catch(function() {\n'
    '    if (btn) { btn.disabled = false; btn.textContent = "Re-run thesis loop"; }\n'
    '    if (st)  { st.textContent = "Request failed."; }\n'
    '  });\n'
    '}\n'
    '\n'
    'function pollRerun(jobId, thesisId) {\n'
    '  if (_rerunPollTimer) clearInterval(_rerunPollTimer);\n'
    '  var btn = document.getElementById("ver-rerun-btn");\n'
    '  var st  = document.getElementById("ver-rerun-status");\n'
    '  _rerunPollTimer = setInterval(function() {\n'
    '    api("/api/jobs").then(function(data) {\n'
    '      var job = (data.jobs||[]).find(function(j){ return j.job_id === jobId; });\n'
    '      if (!job) return;\n'
    '      if (job.status === "done") {\n'
    '        clearInterval(_rerunPollTimer);\n'
    '        if (btn) { btn.disabled = false; btn.textContent = "Re-run thesis loop"; }\n'
    '        if (st)  { st.textContent = "Done. Reloading..."; }\n'
    '        setTimeout(function() {\n'
    '          loadTheses().then(function() {\n'
    '            var updated = State.theses.find(function(t){ return t.id === thesisId; });\n'
    '            if (updated) renderThesisDetail(updated);\n'
    '            loadVersionHistory(thesisId);\n'
    '            if (st) st.textContent = "";\n'
    '          });\n'
    '        }, 800);\n'
    '      } else if (job.status === "error") {\n'
    '        clearInterval(_rerunPollTimer);\n'
    '        if (btn) { btn.disabled = false; btn.textContent = "Re-run thesis loop"; }\n'
    '        if (st)  { st.textContent = "Error: " + (job.error || "unknown"); }\n'
    '      } else {\n'
    '        if (st) st.textContent = "Running thesis loop...";\n'
    '      }\n'
    '    });\n'
    '  }, 2000);\n'
    '}\n'
    '\n'
    'function _edgarApplyConfig(cfg) {'
)
count4 = src.count(OLD4)
if count4 != 1:
    print(f"ERROR: anchor 4 found {count4} times. Aborting.")
    sys.exit(1)
src = src.replace(OLD4, NEW4, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("Patch applied. Version History section + Re-run button added to thesis detail view.")
