"""
patch_l5_immutable_html.py

Lock the Outcomes UI when a resolved decision is selected:
  - All outcome inputs become read-only
  - "Save draft" and "Resolve" buttons are disabled
  - A "LOCKED" banner shows with the resolution date
  - The post-mortem result is displayed read-only
  - 409 (locked) responses from the server are surfaced clearly

Run from project root:
    python patch_l5_immutable_html.py
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
# 1. Replace outcomeLoadDecision with a version that locks resolved decisions
# ---------------------------------------------------------------------------

OLD_LOAD_DEC = '''function outcomeLoadDecision(id) {
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
}'''

NEW_LOAD_DEC = '''function outcomeLoadDecision(id) {
  _ocSelectedId = id;
  clearPmResult();
  if (!id) { setOutcomeFormLocked(false); return; }
  const d = _outcomesData.decisions.find(x => x.id === id);
  if (!d) return;
  document.getElementById('oc-price-entry').value  = d.price_at_decision != null ? d.price_at_decision : '';
  document.getElementById('oc-price-outcome').value = d.price_at_outcome != null ? d.price_at_outcome : '';
  document.getElementById('oc-30d').value  = d.outcome_30d  || '';
  document.getElementById('oc-90d').value  = d.outcome_90d  || '';
  document.getElementById('oc-365d').value = d.outcome_365d || '';
  document.getElementById('oc-status').textContent = '';

  // If resolved, this decision is a permanent locked record.
  if (d.outcome_resolved) {
    const when = (d.outcome_date || '').slice(0, 10);
    setOutcomeFormLocked(true, when);
    if (d.postmortem_summary) {
      showPmResult(d.pattern_tag, d.postmortem_summary);
    }
  } else {
    setOutcomeFormLocked(false);
    if (d.postmortem_summary) {
      showPmResult(d.pattern_tag, d.postmortem_summary);
    }
  }
}

function setOutcomeFormLocked(locked, when) {
  const ids = ['oc-price-outcome', 'oc-30d', 'oc-90d', 'oc-365d'];
  ids.forEach(i => {
    const el = document.getElementById(i);
    if (el) {
      el.readOnly = locked;
      el.style.opacity = locked ? '0.55' : '1';
    }
  });
  // Disable the action buttons
  const btns = document.querySelectorAll('#view-outcomes button[onclick^="outcomeSaveDraft"], #view-outcomes button[onclick^="outcomeResolve"]');
  btns.forEach(b => {
    b.disabled = locked;
    b.style.opacity = locked ? '0.4' : '1';
    b.style.cursor = locked ? 'not-allowed' : 'pointer';
  });
  // Lock banner
  let banner = document.getElementById('oc-lock-banner');
  if (locked) {
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'oc-lock-banner';
      banner.style.cssText = 'margin-top:10px;padding:8px 12px;background:rgba(224,163,74,0.12);' +
        'border:1px solid var(--caution);border-radius:6px;font-family:var(--mono);' +
        'font-size:11px;color:var(--caution);letter-spacing:0.5px';
      const status = document.getElementById('oc-status');
      status.parentNode.insertBefore(banner, status.nextSibling);
    }
    banner.textContent = 'LOCKED -- resolved' + (when ? ' on ' + when : '') +
      '. This decision is a permanent record and cannot be altered or deleted.';
    banner.style.display = 'block';
  } else if (banner) {
    banner.style.display = 'none';
  }
}'''

if OLD_LOAD_DEC in text:
    text = text.replace(OLD_LOAD_DEC, NEW_LOAD_DEC, 1)
    print("  [+] Replaced outcomeLoadDecision with locking version")
    changed = True
else:
    print("  [=] outcomeLoadDecision already patched or anchor not found")

# ---------------------------------------------------------------------------
# 2. Make outcomeSaveDraft / outcomeResolve surface 409 (locked) clearly
# ---------------------------------------------------------------------------

OLD_SAVE = '''  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      setOcStatus('Draft saved.');
      loadOutcomesTab();
    } else {
      setOcStatus('Error: ' + (data.error || 'unknown'));
    }
  });
}'''

NEW_SAVE = '''  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      setOcStatus('Draft saved.');
      loadOutcomesTab();
    } else if (data.locked) {
      setOcStatus('LOCKED: ' + data.error);
    } else {
      setOcStatus('Error: ' + (data.error || 'unknown'));
    }
  });
}'''

if OLD_SAVE in text:
    text = text.replace(OLD_SAVE, NEW_SAVE, 1)
    print("  [+] outcomeSaveDraft now reports locked state")
    changed = True
else:
    print("  [=] outcomeSaveDraft already patched or anchor not found")

OLD_RESOLVE = '''  .then(r => r.json())
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
}'''

NEW_RESOLVE = '''  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      setOcStatus('Resolved. Post-mortem running...');
      loadOutcomesTab();
      if (data.postmortem_job_id) {
        pollPmJob(data.postmortem_job_id);
      }
    } else if (data.locked) {
      setOcStatus('LOCKED: ' + data.error);
    } else {
      setOcStatus('Error: ' + (data.error || 'unknown'));
    }
  });
}'''

if OLD_RESOLVE in text:
    text = text.replace(OLD_RESOLVE, NEW_RESOLVE, 1)
    print("  [+] outcomeResolve now reports locked state")
    changed = True
else:
    print("  [=] outcomeResolve already patched or anchor not found")

# ---------------------------------------------------------------------------
# 3. In the Decision Log tab, the delete handler should surface 409 clearly.
#    Find the existing delete fetch in the decisions view and add locked
#    handling. The decisions table delete uses deleteDecision(id).
# ---------------------------------------------------------------------------

# Look for a deleteDecision function
if "function deleteDecision" in text:
    # Add locked handling. We look for the typical pattern of a DELETE fetch
    # followed by a reload. Try to patch the .then result handling.
    # Most likely form:
    OLD_DEL_FN_PATTERNS = [
        ('''    const res = await api("/api/decision/" + id, { method: "DELETE" });''',
         '''    let res;
    try {
      res = await api("/api/decision/" + id, { method: "DELETE" });
    } catch (e) {
      alert("Could not delete: " + e.message);
      return;
    }
    if (res && res.locked) { alert(res.error); return; }'''),
    ]
    patched_del = False
    for old, new in OLD_DEL_FN_PATTERNS:
        if old in text and "res.locked" not in text:
            text = text.replace(old, new, 1)
            print("  [+] deleteDecision now reports locked state")
            patched_del = True
            changed = True
            break
    if not patched_del:
        print("  [=] deleteDecision delete-fetch pattern not matched -- "
              "locked deletes will still be blocked server-side, just with a")
        print("      generic error. Safe to leave; UI guard is secondary.")
else:
    print("  [=] No deleteDecision function found by name -- skipping UI delete guard")

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

if changed:
    HTML_PATH.write_text(text, encoding="utf-8")
    print(f"\nDone. {HTML_PATH} updated.")
else:
    print("\nNo changes made -- already patched.")

print("\nRestart dashboard:")
print("  python run.py dashboard")
