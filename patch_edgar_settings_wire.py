"""
patch_edgar_settings_wire.py
Wires the two EDGAR settings hooks into the existing load/save flow:
  1. _edgarApplyConfig(data.config)  -- called after renderSettings on load
  2. _edgarCollect(payload)          -- called before the POST on save
Run from the project root:
  python patch_edgar_settings_wire.py
"""
import sys
import os

TARGETS = [
    r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\index.html",
]

# --- patch 1: apply on load ---
OLD_LOAD = '    el.innerHTML = renderSettings(data.config);\n    wireSettings();'
NEW_LOAD = '    el.innerHTML = renderSettings(data.config);\n    _edgarApplyConfig(data.config);\n    wireSettings();'

# --- patch 2: collect on save ---
OLD_SAVE = '    try {\n      const r = await api("/api/config", {'
NEW_SAVE = '    _edgarCollect(payload);\n    try {\n      const r = await api("/api/config", {'

def patch_file(path):
    if not os.path.exists(path):
        print("ERROR: file not found: " + path)
        return False

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    changed = False

    if OLD_LOAD in src:
        src = src.replace(OLD_LOAD, NEW_LOAD, 1)
        print("OK  patch 1 (applyConfig on load) applied")
        changed = True
    elif NEW_LOAD in src:
        print("SKIP patch 1 already present")
    else:
        print("ERROR patch 1 anchor not found -- check index.html manually")
        return False

    if OLD_SAVE in src:
        src = src.replace(OLD_SAVE, NEW_SAVE, 1)
        print("OK  patch 2 (edgarCollect on save) applied")
        changed = True
    elif NEW_SAVE in src:
        print("SKIP patch 2 already present")
    else:
        print("ERROR patch 2 anchor not found -- check index.html manually")
        return False

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        print("WRITTEN " + path)

    return True

ok = True
for t in TARGETS:
    if not patch_file(t):
        ok = False

sys.exit(0 if ok else 1)
