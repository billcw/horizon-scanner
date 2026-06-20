"""
patch_l5_html_v2.py

Targeted fix for the Outcomes tab button and view div.
The existing dashboard uses data-view="..." buttons, not onclick="showTab(...)".
This patch inserts:
  1. The Outcomes tab button (data-view="outcomes") after the Decision Log button
  2. The Outcomes view div after the decisions view div
  3. A hook in the tab-switch logic to call loadOutcomesTab() when outcomes is selected

Run from project root:
    python patch_l5_html_v2.py
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
# Patch 1: Add Outcomes tab button after the Decision Log button
# ---------------------------------------------------------------------------
P1_CHECK  = 'data-view="outcomes"'
P1_ANCHOR = 'data-view="decisions">Decision Log</button>'
P1_INSERT = 'data-view="decisions">Decision Log</button>\n  <button data-view="outcomes">Outcomes</button>'

if P1_CHECK not in text:
    if P1_ANCHOR in text:
        text = text.replace(P1_ANCHOR, P1_INSERT, 1)
        print("  [+] Added Outcomes tab button")
        changed = True
    else:
        print("  [!] Cannot find Decision Log button anchor -- aborting")
        print("      Looking for:", repr(P1_ANCHOR))
        sys.exit(1)
else:
    print("  [=] Outcomes tab button already present")

# ---------------------------------------------------------------------------
# Patch 2: Add Outcomes view div after the decisions view div
# ---------------------------------------------------------------------------
P2_CHECK  = 'id="view-outcomes"'

# Find the closing </div> of the decisions view div.
# Strategy: locate <!-- DECISIONS VIEW --> comment, then find the matching
# closing </div> by counting open/close div tags from the opening div.
if P2_CHECK not in text:
    start_marker = '<!-- DECISIONS VIEW -->'
    if start_marker not in text:
        # fallback: find the div by id
        start_marker = 'id="view-decisions"'

    marker_pos = text.find(start_marker)
    if marker_pos == -1:
        print("  [!] Cannot find decisions view div anchor -- aborting")
        sys.exit(1)

    # Find the opening <div of the decisions view
    open_pos = text.find('<div', marker_pos)
    if open_pos == -1:
        print("  [!] Cannot find opening <div after decisions marker -- aborting")
        sys.exit(1)

    # Walk forward counting div depth to find the matching close
    depth = 0
    pos = open_pos
    close_end = -1
    while pos < len(text):
        open_tag = text.find('<div', pos)
        close_tag = text.find('</div>', pos)

        if open_tag == -1 and close_tag == -1:
            break
        if open_tag == -1:
            open_tag = len(text)
        if close_tag == -1:
            close_tag = len(text)

        if open_tag < close_tag:
            depth += 1
            pos = open_tag + 4
        else:
            depth -= 1
            pos = close_tag + 6
            if depth == 0:
                close_end = pos
                break

    if close_end == -1:
        print("  [!] Could not find closing </div> of decisions view -- aborting")
        sys.exit(1)

    OUTCOMES_VIEW = """
  <!-- OUTCOMES VIEW -->
  <div class="view" id="view-outcomes">

    <!-- Outcome recorder -->
    <div class="panel" style="margin-bottom:18px">
      <div class="panel-head">
        Record Outcome
        <span style="font-size:10px;color:var(--ink-faint)">select a decision, fill in what happened, then resolve</span>
      </div>
      <div class="panel-body" style="padding:14px">
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px">
          <div>
            <label class="field-label">Decision</label>
            <select id="oc-decision-select" style="width:100%;background:var(--panel-2);border:1px solid var(--edge);color:var(--ink);padding:6px 8px;border-radius:4px;font-family:var(--mono);font-size:12px"
                    onchange="outcomeLoadDecision(this.value)">
              <option value="">-- select --</option>
            </select>
          </div>
          <div>
            <label class="field-label">Price at decision</label>
            <input id="oc-price-entry" type="number" step="0.01" placeholder="e.g. 128.40"
                   style="width:100%;background:var(--panel-2);border:1px solid var(--edge);color:var(--ink-dim);padding:6px 8px;border-radius:4px;font-family:var(--mono);font-size:12px" readonly>
          </div>
          <div>
            <label class="field-label">Price at outcome</label>
            <input id="oc-price-outcome" type="number" step="0.01" placeholder="e.g. 194.20"
                   style="width:100%;background:var(--panel-2);border:1px solid var(--edge);color:var(--ink);padding:6px 8px;border-radius:4px;font-family:var(--mono);font-size:12px">
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px">
          <div>
            <label class="field-label">30-day note</label>
            <input id="oc-30d" type="text" placeholder="e.g. down 8%, thesis still intact"
                   style="width:100%;background:var(--panel-2);border:1px solid var(--edge);color:var(--ink);padding:6px 8px;border-radius:4px;font-family:var(--mono);font-size:12px">
          </div>
          <div>
            <label class="field-label">90-day note</label>
            <input id="oc-90d" type="text" placeholder="e.g. broke out after earnings"
                   style="width:100%;background:var(--panel-2);border:1px solid var(--edge);color:var(--ink);padding:6px 8px;border-radius:4px;font-family:var(--mono);font-size:12px">
          </div>
          <div>
            <label class="field-label">365-day note</label>
            <input id="oc-365d" type="text" placeholder="e.g. +62%, held full position"
                   style="width:100%;background:var(--panel-2);border:1px solid var(--edge);color:var(--ink);padding:6px 8px;border-radius:4px;font-family:var(--mono);font-size:12px">
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <button onclick="outcomeSaveDraft()">Save draft</button>
          <button onclick="outcomeResolve()" style="background:var(--caution);border-color:var(--caution);color:#000">Resolve + run post-mortem</button>
          <span id="oc-status" style="font-family:var(--mono);font-size:11px;color:var(--ink-dim)"></span>
        </div>
        <div id="oc-pm-result" style="display:none;margin-top:14px;padding:12px;
             background:var(--panel-2);border:1px solid var(--edge);border-radius:6px">
          <div style="font-family:var(--mono);font-size:11px;color:var(--ink-dim);
                      letter-spacing:1px;margin-bottom:6px">POST-MORTEM RESULT</div>
          <div id="oc-pm-tag" style="font-family:var(--mono);font-size:13px;color:var(--signal);margin-bottom:6px"></div>
          <div id="oc-pm-summary" style="color:var(--ink);line-height:1.6"></div>
        </div>
      </div>
    </div>

    <!-- Decision history table -->
    <div class="panel" style="margin-bottom:18px">
      <div class="panel-head" style="display:flex;align-items:center;gap:10px">
        Decision History
        <input id="oc-filter" placeholder="filter..." oninput="renderOutcomesTable()"
               style="font-size:11px;padding:3px 8px;background:var(--panel-2);
                      border:1px solid var(--edge);color:var(--ink);border-radius:4px;
                      font-family:var(--mono)">
      </div>
      <div class="panel-body" style="padding:0;overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px">
          <thead>
            <tr style="border-bottom:1px solid var(--edge);color:var(--ink-dim)">
              <th style="padding:8px 12px;text-align:left;font-weight:400">Date</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Ticker</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Type</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Entry $</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Exit $</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Return</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Pattern</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Resolved</th>
              <th style="padding:8px 12px;text-align:left;font-weight:400">Flag</th>
            </tr>
          </thead>
          <tbody id="oc-table-body"></tbody>
        </table>
      </div>
    </div>

    <!-- Pattern summary -->
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

    text = text[:close_end] + OUTCOMES_VIEW + text[close_end:]
    print("  [+] Added Outcomes view div")
    changed = True
else:
    print("  [=] Outcomes view div already present")

# ---------------------------------------------------------------------------
# Patch 3: Hook loadOutcomesTab() into the tab-switch logic
# The existing code uses data-view buttons; find the click handler that
# switches views and add the outcomes hook.
# ---------------------------------------------------------------------------
P3_CHECK  = "loadOutcomesTab()"
# The tab switching block loads decisions when decisions tab is clicked.
# Find that line and add the outcomes equivalent next to it.
P3_ANCHOR = 'if(b.dataset.view === "decisions") loadDecisions();'
P3_NEW    = 'if(b.dataset.view === "decisions") loadDecisions();\n    if(b.dataset.view === "outcomes") loadOutcomesTab();'

if P3_CHECK not in text:
    if P3_ANCHOR in text:
        text = text.replace(P3_ANCHOR, P3_NEW, 1)
        print("  [+] Hooked loadOutcomesTab() into tab-switch logic")
        changed = True
    else:
        print("  [!] Could not find tab-switch anchor -- skipping hook")
        print("      Add manually: if(b.dataset.view === 'outcomes') loadOutcomesTab();")
else:
    print("  [=] loadOutcomesTab() hook already present")

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------
if changed:
    HTML_PATH.write_text(text, encoding="utf-8")
    print(f"\nDone. {HTML_PATH} updated.")
    print("\nVerify syntax (no Python equivalent for HTML, just restart dashboard):")
    print("  python run.py dashboard")
else:
    print("\nNothing to patch -- all additions already present.")
