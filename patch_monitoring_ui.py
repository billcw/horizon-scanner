"""
patch_monitoring_ui.py -- L4 monitoring Monitoring tab UI.
Idempotent, anchor-guarded. Run from project root: python patch_monitoring_ui.py

Adds: Monitoring tab button + unread badge, #view-monitoring section,
monitoring CSS, tab-switch wiring, JS (loadMonitoring/checkMonitoring/
markMonRead/markAllMonRead/refreshMonBadge/monEventCard), boot badge refresh,
and a badge refresh after Refresh all completes.
"""
import io
import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "index.html")
SENTINEL = "L4-MONITORING-UI"


def _require(src, anchor, label):
    c = src.count(anchor)
    if c != 1:
        print("ABORT: anchor for [%s] found %d times (expected 1). No change." % (label, c))
        sys.exit(1)


EDITS = []

# 1) Tab button + badge.
EDITS.append((
    "tab_button",
    '''  <button data-view="settings">Settings</button>
  <button data-view="graph">Graph</button>

</nav>''',
    '''  <button data-view="settings">Settings</button>
  <button data-view="graph">Graph</button>
  <button data-view="monitoring">Monitoring <span id="mon-badge" class="mon-badge" style="display:none">0</span></button>

</nav>''',
))

# 2) View div before </main>.
EDITS.append((
    "view_div",
    '''
</main>''',
    '''  <!-- MONITORING VIEW -- L4-MONITORING-UI -->
  <div class="view" id="view-monitoring">
    <div class="mon-toolbar">
      <button class="act" id="mon-check-btn" onclick="checkMonitoring()">Check Monitoring</button>
      <button class="ghost" id="mon-readall-btn" onclick="markAllMonRead()">Mark all read</button>
      <label class="mon-unread-toggle">
        <input type="checkbox" id="mon-unread-only" onchange="loadMonitoring()"> unread only
      </label>
      <span id="mon-status" class="mon-status"></span>
    </div>
    <div id="mon-feed"><div class="empty">No monitoring events yet. Run a Refresh all or Check Monitoring.</div></div>
  </div>

</main>''',
))

# 3) CSS block.
EDITS.append((
    "css",
    '''  main { padding: 22px; max-width: 1400px; margin: 0 auto; }
  .view { display: none; }
  .view.active { display: block; }

  /* ---- Cluster list --------------------------------------------------*/''',
    '''  main { padding: 22px; max-width: 1400px; margin: 0 auto; }
  .view { display: none; }
  .view.active { display: block; }

  /* ---- L4 Monitoring (L4-MONITORING-UI) ------------------------------*/
  .mon-badge {
    display: inline-block; min-width: 16px; padding: 1px 5px; margin-left: 4px;
    font-size: 10px; font-weight: 700; line-height: 14px; text-align: center;
    border-radius: 9px; background: var(--caution, #d08020); color: #0b0b0b;
    vertical-align: middle;
  }
  .mon-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
  .mon-unread-toggle { font-size: 12px; color: var(--ink-dim); display: flex; align-items: center; gap: 5px; cursor: pointer; }
  .mon-status { font-size: 12px; color: var(--ink-dim); margin-left: auto; }
  .mon-event {
    border: 1px solid var(--edge); border-left-width: 3px; border-radius: 6px;
    padding: 11px 13px; margin-bottom: 9px; background: var(--panel);
    display: flex; gap: 12px; align-items: flex-start;
  }
  .mon-event.unread { border-left-color: var(--caution, #d08020); background: rgba(208,128,32,0.05); }
  .mon-event.read { border-left-color: var(--edge); opacity: 0.72; }
  .mon-event .mon-main { flex: 1; min-width: 0; }
  .mon-event .mon-type {
    font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: 0.5px;
    padding: 2px 6px; border-radius: 4px; display: inline-block; margin-bottom: 4px;
  }
  .mon-type.SIGNAL_SPIKE { background: rgba(208,128,32,0.18); color: var(--caution, #d08020); }
  .mon-type.SIGNAL_QUIET { background: rgba(120,120,140,0.18); color: var(--ink-dim); }
  .mon-type.STATE_CHANGE, .mon-type.CONFIRMING, .mon-type.CONTRADICTING,
  .mon-type.NEUTRAL, .mon-type.MILESTONE { background: rgba(80,140,200,0.16); color: var(--signal); }
  .mon-event .mon-thesis { font-weight: 600; color: var(--ink); font-size: 13px; }
  .mon-event .mon-desc { color: var(--ink-dim); font-size: 12px; margin-top: 3px; }
  .mon-event .mon-time { color: var(--ink-dim); font-size: 10px; font-family: var(--mono); margin-top: 5px; }
  .mon-event .mon-mark { font-size: 11px; white-space: nowrap; }

  /* ---- Cluster list --------------------------------------------------*/''',
))

# 4) Tab-switch wiring + JS functions.
EDITS.append((
    "tab_js",
    '''  if(b.dataset.view === "decisions") loadDecisions();
    if(b.dataset.view === "outcomes") loadOutcomesTab();
  if(b.dataset.view === "settings") loadSettings();
});''',
    '''  if(b.dataset.view === "decisions") loadDecisions();
    if(b.dataset.view === "outcomes") loadOutcomesTab();
  if(b.dataset.view === "settings") loadSettings();
  if(b.dataset.view === "monitoring") loadMonitoring();
});

// ---- L4 Monitoring (L4-MONITORING-UI) -------------------------------
async function refreshMonBadge(){
  try {
    const r = await api("/api/monitoring/unread-count");
    const badge = $("#mon-badge");
    if(!badge) return;
    if(r.count > 0){ badge.textContent = r.count; badge.style.display = "inline-block"; }
    else { badge.style.display = "none"; }
  } catch(e){ /* silent */ }
}

function monEventCard(ev){
  const unread = !ev.read_flag;
  const cls = unread ? "unread" : "read";
  const t = (ev.created_at || "").replace("T"," ").slice(0,19);
  const markBtn = unread
    ? `<a href="#" class="mon-mark" onclick="markMonRead('${esc(ev.id)}');return false;">mark read</a>`
    : "";
  return `<div class="mon-event ${cls}">
    <div class="mon-main">
      <span class="mon-type ${esc(ev.event_type)}">${esc(ev.event_type)}</span>
      <div class="mon-thesis">${esc(ev.title || "(thesis "+ (ev.thesis_id||"").slice(0,8) +")")}</div>
      <div class="mon-desc">${esc(ev.description || "")}</div>
      <div class="mon-time">${esc(t)} UTC</div>
    </div>
    <div>${markBtn}</div>
  </div>`;
}

async function loadMonitoring(){
  const feed = $("#mon-feed");
  if(!feed) return;
  const unreadOnly = $("#mon-unread-only") && $("#mon-unread-only").checked;
  feed.innerHTML = `<div class="empty">Loading...</div>`;
  try {
    const r = await api("/api/monitoring/events" + (unreadOnly ? "?unread=1" : ""));
    const events = r.events || [];
    if(events.length === 0){
      feed.innerHTML = `<div class="empty">No monitoring events${unreadOnly?" (unread)":""}. Run a Refresh all or Check Monitoring.</div>`;
    } else {
      feed.innerHTML = events.map(monEventCard).join("");
    }
  } catch(e){
    feed.innerHTML = `<div class="empty">Failed to load: ${esc(e.message)}</div>`;
  }
  refreshMonBadge();
}

async function checkMonitoring(){
  const btn = $("#mon-check-btn");
  const status = $("#mon-status");
  if(btn) btn.disabled = true;
  if(status) status.textContent = "Running monitoring pass...";
  try {
    const r = await api("/api/monitoring/check", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: "{}"
    });
    const s = r.summary || {};
    if(status) status.textContent =
      `Checked ${s.theses_checked||0} theses, ${s.events_created||0} new event(s).`;
    toast(`Monitoring: ${s.events_created||0} new event(s)`);
    await loadMonitoring();
  } catch(e){
    if(status) status.textContent = "Failed: " + e.message;
    toast("Check failed: " + e.message);
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function markMonRead(id){
  try {
    await api(`/api/monitoring/events/${encodeURIComponent(id)}/read`, {method:"POST"});
    await loadMonitoring();
  } catch(e){ toast("Failed: " + e.message); }
}

async function markAllMonRead(){
  try {
    await api("/api/monitoring/read-all", {method:"POST"});
    toast("All marked read");
    await loadMonitoring();
  } catch(e){ toast("Failed: " + e.message); }
}''',
))

# 5) Boot badge refresh.
EDITS.append((
    "boot",
    '''(async function init(){
  wireFilter();
  wireRefresh();
  await loadStats();
  await loadTheses();
  await loadClusters();
})();''',
    '''(async function init(){
  wireFilter();
  wireRefresh();
  await loadStats();
  await loadTheses();
  await loadClusters();
  refreshMonBadge();
})();''',
))

# 6) Badge refresh after Refresh all completes.
EDITS.append((
    "refresh_done",
    '''      if(j.status === "done"){
        clearInterval(State.refreshTimer);
        await loadTheses(); await loadClusters(); await loadStats();
        resetRefreshButtons(buttons);
        const src = j.source && j.source !== "all" ? j.source + ": " : "";
        toast(`${src}${j.collected||0} collected, ${j.classified||0} classified`);
      }''',
    '''      if(j.status === "done"){
        clearInterval(State.refreshTimer);
        await loadTheses(); await loadClusters(); await loadStats();
        resetRefreshButtons(buttons);
        const src = j.source && j.source !== "all" ? j.source + ": " : "";
        toast(`${src}${j.collected||0} collected, ${j.classified||0} classified`);
        refreshMonBadge();
      }''',
))


def main():
    if not os.path.exists(TARGET):
        print("ABORT: %s not found. Run from project root." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Already applied (sentinel present). No change.")
        return

    for label, old, _new in EDITS:
        _require(src, old, label)

    new_src = src
    for label, old, new in EDITS:
        new_src = new_src.replace(old, new, 1)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)
    print("OK: applied L4 monitoring UI (6 edits) to %s" % TARGET)


if __name__ == "__main__":
    main()
