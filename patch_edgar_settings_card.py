"""
patch_edgar_settings_card.py
Adds the missing EDGAR Enrichment settings card to renderSettings() in index.html.

The wiring helpers (_edgarApplyConfig / _edgarCollect) and their call sites already
exist, but the actual HTML controls (set_edgar_verify, set_edgar_depth) were never
added -- so the helpers find nothing and silently no-op. This adds them.

Line-ending-agnostic: anchors on a unique single-line marker, preserves whatever
newline style the line already uses.

Run from the project root:
  python patch_edgar_settings_card.py
"""
import sys
import os

TARGET = r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\index.html"

# Unique single-line anchor: the step-timeout row. We insert the EDGAR card AFTER
# the card-closing </div> that follows this row. We find the row, then find the next
# "    </div>" after it, and insert the new card there.
ROW_MARKER = 'numInput("th_timeout", th.step_timeout_seconds)'

EDGAR_CARD_LINES = [
    '',
    '    <div class="set-card">',
    '      <h3>EDGAR Enrichment</h3>',
    '      <div class="set-row"><label>Verify tickers (SEC)</label><select id="set_edgar_verify"><option value="true">On</option><option value="false">Off</option></select></div>',
    '      <div class="set-row"><label>Deep enrichment depth</label><select id="set_edgar_depth"><option value="0">0 - off</option><option value="1">1 - ring 1</option><option value="2">2 - rings 1-2</option><option value="3">3 - rings 1-3</option><option value="4">4 - all rings</option></select></div>',
    '      <div style="font-family:var(--mono);font-size:10px;color:var(--ink-faint);margin:10px 0 0;line-height:1.5">Ticker verify is cheap and runs on all rings. Deep enrichment pulls 10-K IP sections and licensing hits and is more expensive the deeper it goes.</div>',
    '    </div>',
]


def main():
    if not os.path.exists(TARGET):
        print("ERROR: file not found: " + TARGET)
        return 1

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if 'id="set_edgar_verify"' in src:
        print("SKIP card already present")
        return 0

    # Detect newline style.
    nl = "\r\n" if "\r\n" in src else "\n"
    lines = src.split(nl)

    # Find the step-timeout row.
    row_idx = None
    for i, ln in enumerate(lines):
        if ROW_MARKER in ln:
            row_idx = i
            break
    if row_idx is None:
        print("ERROR step-timeout row not found -- check index.html manually")
        return 1

    # Find the next card-closing </div> after that row.
    close_idx = None
    for j in range(row_idx + 1, len(lines)):
        if lines[j].strip() == "</div>":
            close_idx = j
            break
    if close_idx is None:
        print("ERROR could not find closing </div> of Context card")
        return 1

    # Insert the EDGAR card right after that closing </div>.
    new_lines = lines[:close_idx + 1] + EDGAR_CARD_LINES + lines[close_idx + 1:]
    out = nl.join(new_lines)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(out)

    print("OK EDGAR card inserted after Context & Search card")
    print("newline style: " + repr(nl))
    print("WRITTEN " + TARGET)
    return 0


sys.exit(main())
