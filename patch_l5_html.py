"""
patch_l5_html.py

Run this once from the project root to patch index.html with L5 additions:
  1. Adds an "Outcomes" tab button in the nav bar
  2. Adds the full Outcomes tab view (outcome recorder + patterns panel)
  3. Adds an "Exit Check" button in the thesis viewer
  4. Adds the JS for all L5 interactions

Usage (from project root, venv active):
    python patch_l5_html.py

The script is idempotent: it checks for its own markers before patching
so running it twice won't double-insert anything.
"""

import re
import sys
from pathlib import Path

HTML_PATH = Path(r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\index.html")

# ---------------------------------------------------------------------------
# Patch 1: Add "Outcomes" tab button to the nav bar
# Anchor: the existing "Decision Log" tab button
# ---------------------------------------------------------------------------

PATCH1_ANCHOR = '<button onclick="showTab(\'decisions\')"'
PATCH1_CHECK  = "showTab('outcomes')"
PATCH1_INSERT = """<button onclick="showTab('outcomes')" id="tab-outcomes">Outcomes</button>
"""

# ---------------------------------------------------------------------------
# Patch 2: Add the Outcomes tab view div
# Anchor: closing tag of the decisions view div -- we insert right after it
# ---------------------------------------------------------------------------

PATCH2_ANCHOR = "<!-- end decisions view -->"
PATCH2_FALLBACK = "</div><!-- end decisions -->"   # fallback if comment absent
PATCH2_CHECK  = "id=\"view-outcomes\""
PATCH2_INSERT = """

<!-- ===== Outcomes + Patterns Tab ===== -->
<div id="view-outcomes" class="view">

  <!-- ---- Outcome recorder ---- -->
  <div class="panel" style="margin-bottom:18px">
    <div class="panel-head">
      Record Outcome
      <span style="font-size:10px;color:var(--ink-faint)">select a decision below, fill in what happened, then resolve</span>
    </div>
    <div class="panel-body" style="padding:14px">
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px">
        <div>
          <label class="field-label">Decision</label>
          <select id="oc-decision-select" style="width:100%"
                  onchange="outcomeLoadDecision(this.value)">
            <option value="">-- select --</option>
          </select>
        </div>
        <div>
          <label class="field-label">Price at decision</label>
          <input id="oc-price-entry" type="number" step="0.01" placeholder="e.g. 128.40"
                 style="width:100%" readonly>
        </div>
        <div>
          <label class="field-label">Price at outcome</label>
          <input id="oc-price-outcome" type="number" step="0.01" placeholder="e.g. 194.20"
                 style="width:100%">
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px">
        <div>
          <label class="field-label">30-day note</label>
          <input id="oc-30d" type="text" placeholder="e.g. down 8%, thesis still intact"
                 style="width:100%">
        </div>
        <div>
          <label class="field-label">90-day note</label>
          <input id="oc-90d" type="text" placeholder="e.g. broke out after earnings"
                 style="width:100%">
        </div>
        <div>
          <label class="field-label">365-day note</label>
          <input id="oc-365d" type="text" placeholder="e.g. +62%, held full position"
                 style="width:100%">
        </div>
      </div>
      <div style="display:flex;gap:10px;align-items:center">
        <button onclick="outcomeSaveDraft()">Save draft</button>
        <button onclick="outcomeResolve()" class="btn-caution">Resolve + run post-mortem</button>
        <span id="oc-status" style="font-family:var(--mono);font-size:11px;color:var(--ink-dim)"></span>
      </div>
      <!-- post-mortem result box (shown after job completes) -->
      <div id="oc-pm-result" style="display:none;margin-top:14px;padding:12px;
           background:var(--panel-2);border:1px solid var(--edge);border-radius:6px">
        <div style="font-family:var(--mono);font-size:11px;color:var(--ink-dim);
                    letter-spacing:1px;margin-bottom:6px">POST-MORTEM RESULT</div>
        <div id="oc-pm-tag" style="font-family:var(--mono);font-size:13px;
                                   color:var(--signal);margin-bottom:6px"></div>
        <div id="oc-pm-summary" style="color:var(--ink);line-height:1.6"></div>
      </div>
    </div>
  </div>

  <!-- ---- All decisions table with outcome status ---- -->
  <div class="panel" style="margin-bottom:18px">
    <div class="panel-head">Decision History
      <input id="oc-filter" placeholder="filter..." oninput="renderOutcomesTable()"
             style="font-size:11px;padding:3px 8px;background:var(--panel-2);
                    border:1px solid var(--edge);color:var(--ink);border-radius:4px;
                    font-family:var(--mono);margin-left:8px">
    </div>
    <div class="panel-body" style="padding:0;overflow-x:auto">
      <table id="oc-table" style="width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px">
        <thead>
          <tr style="border-bottom:1px solid var(--edge);color:var(--ink-dim)">
            <th style="padding:8px 12px;text-align:left">Date</th>
            <th style="padding:8px 12px;text-align:left">Ticker</th>
            <th style="padding:8px 12px;text-align:left">Type</th>
            <th style="padding:8px 12px;text-align:left">Entry $</th>
            <th style="padding:8px 12px;text-align:left">Exit $</th>
            <th style="padding:8px 12px;text-align:left">Return</th>
            <th style="padding:8px 12px;text-align:left">Pattern</th>
            <th style="padding:8px 12px;text-align:left">Resolved</th>
            <th style="padding:8px 12px;text-align:left">Flag</th>
          </tr>
        </thead>
        <tbody id="oc-table-body"></tbody>
      </table>
    </div>
  </div>

  <!-- ---- Pattern summary ---- -->
  <div class="panel">
    <div class="panel-head">Mistake Patterns</div>
    <div class="panel-body" style="padding:14px">
      <div id="oc-patterns" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px">
        <span style="color:var(--ink-faint);font-size:12px">No patterns yet -- resolve a decision to generate a post-mortem.</span>
      </div>
    </div>
  </div>
</div>
"""

# ---------------------------------------------------------------------------
# Patch 3: Add "Check Exit" button to the thesis viewer action row
# Anchor: the existing "Log Decision" button area in the decision dock
# ---------------------------------------------------------------------------

PATCH3_ANCHOR = 'id="dd-btn-submit"'
PATCH3_CHECK  = "checkExit("
PATCH3_INSERT_AFTER_LINE = """        <button onclick="checkExit()" style="margin-left:8px;background:var(--panel-2);border-color:var(--edge)">Check Exit</button>"""

# ---------------------------------------------------------------------------
# Patch 4: L5 JavaScript block
# Anchor: the closing </script> tag
# ---------------------------------------------------------------------------

PATCH4_CHECK  = "// === L5 OUTCOMES ==="
PATCH4_INSERT_BEFORE = """
// === L5 OUTCOMES ===

let _outcomesData = { decisions: [], with_outcomes: [], pattern_summary: [] };
let _ocSelectedId = null;
let _ocPmPollTimer = null;

// ---- Tab load ------------------------------------------------------------

function loadOutcomesTab() {
  fetch('/api/outcomes')
    .then(r => r.json())
    .then(data => {
      _outcomesData = data;
      populateDecisionSelect(data.decisions);
      renderOutcomesTable();
      renderPatterns(data.pattern_summary);
    })
    .catch(e => console.error('outcomes load failed:', e));
}

function populateDecisionSelect(decisions) {
  const sel = document.getElementById('oc-decision-select');
  const prev = sel.value;
  sel.innerHTML = '<option value="">-- select a decision --</option>';
  decisions.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d.id;
    const date = (d.created_at || '').slice(0, 10);
    const ticker = d.ticker || 'N/A';
    const resolved = d.outcome_resolved ? ' [resolved]' : '';
    opt.textContent = `${date}  ${d.decision_type}  ${ticker}${resolved}`;
    sel.appendChild(opt);
  });
  if (prev) sel.value = prev;
}

function outcomeLoadDecision(id) {
  _ocSelectedId = id;
  clearPmResult();
  if (!id) return;
  const d = _outcomesData.decisions.find(x => x.id === id);
  if (!d) return;
  document.getElementById('oc-price-entry').value  = d.price_at_decision != null ? d.price_at_decision : '';
  document.getElementById('oc-price-outcome').value = d.price_at_outcome != null ? d.price_at_outcome : '';
  document.getElementById('oc-30d').value  = d.outcome_30d  || '';
  document.getElementById('oc-90d').value  = d.outcome_90d  || '';
  document.getElementById('oc-365d').value = d.outcome_365d || '';
  document.getElementById('oc-status').textContent = '';
  // If already has a post-mortem, show it
  if (d.postmortem_summary) {
    showPmResult(d.pattern_tag, d.postmortem_summary);
  }
}

// ---- Save / Resolve ------------------------------------------------------

function _buildOutcomePayload(resolved) {
  return {
    decision_id:    _ocSelectedId,
    price_at_outcome: parseFloat(document.getElementById('oc-price-outcome').value) || null,
    outcome_30d:    document.getElementById('oc-30d').value,
    outcome_90d:    document.getElementById('oc-90d').value,
    outcome_365d:   document.getElementById('oc-365d').value,
    resolved:       resolved,
  };
}

function outcomeSaveDraft() {
  if (!_ocSelectedId) { alert('Select a decision first.'); return; }
  setOcStatus('Saving...');
  fetch('/api/decision/outcome', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(_buildOutcomePayload(false)),
  })
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      setOcStatus('Draft saved.');
      loadOutcomesTab();
    } else {
      setOcStatus('Error: ' + (data.error || 'unknown'));
    }
  });
}

function outcomeResolve() {
  if (!_ocSelectedId) { alert('Select a decision first.'); return; }
  if (!confirm('Mark this decision as resolved and run an AI post-mortem?')) return;
  setOcStatus('Resolving + starting post-mortem...');
  clearPmResult();
  fetch('/api/decision/outcome', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(_buildOutcomePayload(true)),
  })
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      setOcStatus('Resolved. Post-mortem running...');
      loadOutcomesTab();
      if (data.postmortem_job_id) {
        pollPmJob(data.postmortem_job_id);
      }
    } else {
      setOcStatus('Error: ' + (data.error || 'unknown'));
    }
  });
}

// ---- Poll post-mortem job ------------------------------------------------

function pollPmJob(jobId) {
  if (_ocPmPollTimer) clearInterval(_ocPmPollTimer);
  _ocPmPollTimer = setInterval(() => {
    fetch('/api/jobs')
      .then(r => r.json())
      .then(data => {
        const job = (data.jobs || []).find(j => j.job_id === jobId);
        if (!job) return;
        if (job.status === 'done') {
          clearInterval(_ocPmPollTimer);
          setOcStatus('Post-mortem complete.');
          loadOutcomesTab();  // reload to get the saved result
          // Also show inline from job data
          if (job.pattern_tag) {
            // Reload decision to get full summary
            fetch('/api/outcomes')
              .then(r => r.json())
              .then(d => {
                const dec = (d.decisions || []).find(x => x.id === _ocSelectedId);
                if (dec && dec.postmortem_summary) {
                  showPmResult(dec.pattern_tag, dec.postmortem_summary);
                }
              });
          }
        } else if (job.status === 'error') {
          clearInterval(_ocPmPollTimer);
          setOcStatus('Post-mortem failed: ' + (job.error || 'unknown error'));
        }
      });
  }, 1500);
}

// ---- Outcomes table ------------------------------------------------------

function renderOutcomesTable() {
  const filter = (document.getElementById('oc-filter').value || '').toLowerCase();
  const tbody = document.getElementById('oc-table-body');
  if (!tbody) return;
  const decisions = _outcomesData.decisions || [];
  tbody.innerHTML = '';
  decisions
    .filter(d => {
      if (!filter) return true;
      return (d.ticker || '').toLowerCase().includes(filter)
          || (d.decision_type || '').toLowerCase().includes(filter)
          || (d.pattern_tag || '').toLowerCase().includes(filter)
          || (d.stated_reason || '').toLowerCase().includes(filter);
    })
    .forEach(d => {
      const entry  = d.price_at_decision;
      const exit   = d.price_at_outcome;
      let ret = '';
      if (entry && exit) {
        const pct = ((exit - entry) / entry * 100).toFixed(1);
        const col = pct >= 0 ? 'var(--good)' : 'var(--danger)';
        ret = `<span style="color:${col}">${pct >= 0 ? '+' : ''}${pct}%</span>`;
      }
      const flagBadge = d.emotional_flag
        ? '<span style="color:var(--caution)">FLAG</span>' : '';
      const resolved = d.outcome_resolved
        ? '<span style="color:var(--good)">yes</span>'
        : '<span style="color:var(--ink-faint)">no</span>';
      const patternColor = d.pattern_tag ? 'var(--violet)' : 'var(--ink-faint)';
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--edge-soft)';
      tr.innerHTML = `
        <td style="padding:7px 12px">${(d.created_at || '').slice(0,10)}</td>
        <td style="padding:7px 12px">${d.ticker || '-'}</td>
        <td style="padding:7px 12px">${d.decision_type || ''}</td>
        <td style="padding:7px 12px">${entry != null ? '$' + entry : '-'}</td>
        <td style="padding:7px 12px">${exit  != null ? '$' + exit  : '-'}</td>
        <td style="padding:7px 12px">${ret || '-'}</td>
        <td style="padding:7px 12px;color:${patternColor}">${d.pattern_tag || '-'}</td>
        <td style="padding:7px 12px">${resolved}</td>
        <td style="padding:7px 12px">${flagBadge}</td>
      `;
      // Click to load into the form
      tr.style.cursor = 'pointer';
      tr.onclick = () => {
        document.getElementById('oc-decision-select').value = d.id;
        outcomeLoadDecision(d.id);
      };
      tbody.appendChild(tr);
    });
}

// ---- Pattern cards -------------------------------------------------------

function renderPatterns(summary) {
  const container = document.getElementById('oc-patterns');
  if (!container) return;
  if (!summary || summary.length === 0) {
    container.innerHTML = '<span style="color:var(--ink-faint);font-size:12px">No patterns yet -- resolve a decision to generate a post-mortem.</span>';
    return;
  }
  const max = summary[0].count || 1;
  container.innerHTML = summary.map(p => {
    const width = Math.round((p.count / max) * 100);
    const tag = p.pattern_tag || '';
    // Color coding by tag type
    let col = 'var(--ink-dim)';
    if (tag.includes('FOMO') || tag.includes('EARLY') || tag.includes('LONG') || tag.includes('MISSED')) col = 'var(--caution)';
    if (tag.includes('VALIDATED') || tag.includes('CORRECT') || tag.includes('TRIGGERED')) col = 'var(--good)';
    if (tag.includes('INVALID') || tag.includes('CONFIRMED') || tag.includes('ERROR')) col = 'var(--danger)';
    return `
      <div style="background:var(--panel-2);border:1px solid var(--edge);
                  border-radius:6px;padding:12px">
        <div style="font-family:var(--mono);font-size:11px;color:${col};
                    margin-bottom:6px;letter-spacing:0.5px">${tag}</div>
        <div style="background:var(--edge);border-radius:3px;height:4px;margin-bottom:6px">
          <div style="background:${col};width:${width}%;height:4px;border-radius:3px"></div>
        </div>
        <div style="font-family:var(--mono);font-size:13px;color:var(--ink)">${p.count}x</div>
      </div>`;
  }).join('');
}

// ---- Helpers -------------------------------------------------------------

function setOcStatus(msg) {
  const el = document.getElementById('oc-status');
  if (el) el.textContent = msg;
}

function clearPmResult() {
  const box = document.getElementById('oc-pm-result');
  if (box) box.style.display = 'none';
}

function showPmResult(tag, summary) {
  const box = document.getElementById('oc-pm-result');
  if (!box) return;
  box.style.display = 'block';
  document.getElementById('oc-pm-tag').textContent = tag || '';
  document.getElementById('oc-pm-summary').textContent = summary || '';
}

// === L5-D EXIT CHECK ===

let _exitCheckThesisId = null;

function checkExit() {
  // _currentThesisId is the ID of the thesis currently open in the viewer
  // It should already be set by the thesis viewer load logic
  const thesisId = window._currentThesisId;
  if (!thesisId) { alert('Open a thesis first.'); return; }
  const reason = prompt('Optional: why are you considering exiting? (Leave blank for signal-only check)') || '';
  document.getElementById('exit-check-result').style.display = 'none';
  document.getElementById('exit-check-status').textContent = 'Running exit check...';
  fetch('/api/thesis/exit-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thesis_id: thesisId, proposed_reason: reason }),
  })
  .then(r => r.json())
  .then(data => {
    document.getElementById('exit-check-status').textContent = '';
    if (!data.ok) {
      document.getElementById('exit-check-status').textContent = 'Error: ' + (data.error || 'unknown');
      return;
    }
    renderExitCheckResult(data.result);
  })
  .catch(e => {
    document.getElementById('exit-check-status').textContent = 'Error: ' + e.message;
  });
}

function renderExitCheckResult(result) {
  const box = document.getElementById('exit-check-result');
  if (!box) return;
  box.style.display = 'block';
  const rec = result.recommendation || 'REVIEW';
  let recColor = 'var(--signal)';
  if (rec === 'SELL') recColor = 'var(--danger)';
  if (rec === 'HOLD') recColor = 'var(--good)';

  const flags = [];
  if (result.kill_criteria_triggered) flags.push('<span style="color:var(--danger)">KILL CRITERION TRIGGERED</span>');
  if (result.emotional_exit_risk)     flags.push('<span style="color:var(--caution)">EMOTIONAL EXIT RISK</span>');
  if (!result.thesis_still_intact)    flags.push('<span style="color:var(--caution)">THESIS INTEGRITY WEAKENED</span>');

  box.innerHTML = `
    <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:10px">
      <span style="font-family:var(--mono);font-size:18px;font-weight:700;
                   color:${recColor}">${rec}</span>
      <span style="font-family:var(--mono);font-size:11px;color:var(--ink-dim)">
        Signal: ${result.signal_direction || 'UNKNOWN'}
      </span>
    </div>
    ${flags.length ? '<div style="margin-bottom:8px">' + flags.join(' &nbsp; ') + '</div>' : ''}
    <div style="color:var(--ink);line-height:1.6;margin-bottom:6px">${result.reasoning || ''}</div>
    ${result.triggered_criterion ? `<div style="font-family:var(--mono);font-size:11px;color:var(--danger);margin-top:6px">Triggered: ${result.triggered_criterion}</div>` : ''}
  `;
}

"""

# ---------------------------------------------------------------------------
# showTab patch: call loadOutcomesTab when outcomes tab is shown
# ---------------------------------------------------------------------------

PATCH5_CHECK  = "loadOutcomesTab()"
PATCH5_ANCHOR = "function showTab(name) {"
PATCH5_OLD    = "function showTab(name) {"
PATCH5_NEW    = """function showTab(name) {
  if (name === 'outcomes') loadOutcomesTab();"""

# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

def patch(html: str) -> str:
    changed = False

    # ---- Patch 1: nav tab button ----
    if PATCH1_CHECK not in html:
        if PATCH1_ANCHOR in html:
            html = html.replace(PATCH1_ANCHOR, PATCH1_INSERT + PATCH1_ANCHOR, 1)
            print("  [+] Added Outcomes nav tab button")
            changed = True
        else:
            print("  [!] Could not find anchor for Outcomes tab button -- skipping")
    else:
        print("  [=] Outcomes tab button already present")

    # ---- Patch 2: Outcomes view div ----
    if PATCH2_CHECK not in html:
        # Try comment anchor first, then fallback
        inserted = False
        if PATCH2_ANCHOR in html:
            html = html.replace(PATCH2_ANCHOR, PATCH2_ANCHOR + PATCH2_INSERT, 1)
            inserted = True
        elif PATCH2_FALLBACK in html:
            # find last occurrence of the fallback (end of decisions div)
            idx = html.rfind(PATCH2_FALLBACK)
            if idx != -1:
                html = html[:idx + len(PATCH2_FALLBACK)] + PATCH2_INSERT + html[idx + len(PATCH2_FALLBACK):]
                inserted = True
        if inserted:
            print("  [+] Added Outcomes view div")
            changed = True
        else:
            print("  [!] Could not find anchor for Outcomes view div -- skipping")
            print("      Add this after your decisions view div manually:")
            print("      <!-- end decisions view -->")
    else:
        print("  [=] Outcomes view div already present")

    # ---- Patch 3: Exit Check button ----
    if PATCH3_CHECK not in html:
        if PATCH3_ANCHOR in html:
            # Insert the button on the next line after the anchor line
            html = html.replace(PATCH3_ANCHOR, PATCH3_ANCHOR + "\n" + PATCH3_INSERT_AFTER_LINE, 1)
            print("  [+] Added Exit Check button")
            changed = True
        else:
            print("  [!] Could not find anchor for Exit Check button (id='dd-btn-submit') -- skipping")
    else:
        print("  [=] Exit Check button already present")

    # ---- Patch 4: L5 JS block ----
    if PATCH4_CHECK not in html:
        last_script_close = html.rfind("</script>")
        if last_script_close != -1:
            html = html[:last_script_close] + PATCH4_INSERT_BEFORE + html[last_script_close:]
            print("  [+] Added L5 JavaScript block")
            changed = True
        else:
            print("  [!] Could not find </script> to insert JS -- skipping")
    else:
        print("  [=] L5 JS block already present")

    # ---- Patch 5: loadOutcomesTab call in showTab ----
    if PATCH5_CHECK not in html:
        if PATCH5_OLD in html:
            html = html.replace(PATCH5_OLD, PATCH5_NEW, 1)
            print("  [+] Patched showTab() to call loadOutcomesTab()")
            changed = True
        else:
            print("  [!] Could not find showTab function to patch -- skipping")
    else:
        print("  [=] showTab loadOutcomesTab call already present")

    # ---- Patch 6: exit-check result elements + status inside thesis viewer ----
    # These are inline containers that the JS writes into.
    EC_CHECK = "exit-check-result"
    EC_STATUS_CHECK = "exit-check-status"
    if EC_CHECK not in html:
        # Insert just before the closing of the decision dock panel-body
        DOCK_ANCHOR = 'id="dd-btn-submit"'
        if DOCK_ANCHOR in html:
            EC_ELEMENTS = """
      <span id="exit-check-status" style="font-family:var(--mono);font-size:11px;color:var(--ink-dim);margin-left:10px"></span>
      <div id="exit-check-result" style="display:none;margin-top:14px;padding:12px;
           background:var(--panel-2);border:1px solid var(--edge);border-radius:6px"></div>"""
            # find the closing </div> of the dd-actions row and insert after it
            anchor_pos = html.find(DOCK_ANCHOR)
            # walk forward to find next </div>
            close_pos = html.find("</div>", anchor_pos)
            if close_pos != -1:
                html = html[:close_pos + 6] + EC_ELEMENTS + html[close_pos + 6:]
                print("  [+] Added exit-check result containers")
                changed = True
        else:
            print("  [!] Could not find dd-btn-submit to anchor exit-check elements -- skipping")
    else:
        print("  [=] exit-check result containers already present")

    return html, changed


def main():
    if not HTML_PATH.exists():
        print(f"ERROR: {HTML_PATH} not found.")
        sys.exit(1)

    print(f"\nPatching: {HTML_PATH}")
    original = HTML_PATH.read_text(encoding="utf-8-sig")

    patched, changed = patch(original)

    if not changed:
        print("\nNothing to patch -- all L5 additions already present.")
        return

    # Write patched file
    HTML_PATH.write_text(patched, encoding="utf-8")
    print(f"\nDone. {HTML_PATH} updated.")
    print("Verify with: python -c \"print('OK')\"")
    print("Then restart the dashboard: python run.py dashboard")


if __name__ == "__main__":
    main()
