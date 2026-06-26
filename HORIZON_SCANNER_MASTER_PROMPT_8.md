# HORIZON SCANNER - SESSION 8 MASTER PROMPT

## WHO YOU ARE TALKING TO
Bill. SCADA/OT/EMS background. Solo technical build. Windows + PowerShell.
Python venv at C:\Projects\horizon-scanner (deliberately outside OneDrive).
GitHub: github.com/billcw/horizon-scanner (private). Username: billcw, email: billcw@users.noreply.github.com.
Editable install: pip install -e . (setup.py at root). Launch: python run.py dashboard.

## WHAT THIS SYSTEM IS
Horizon Scanner: personal AI-powered investment signal synthesis system.
Surfaces emerging technology opportunities before mainstream adoption.
Enforces structured decision discipline (counters the "MU mistake" -- emotionally-driven investing).
Automates ingestion from arXiv, Reddit, Google Trends, USPTO patents, then runs structured
reasoning loops to produce scored investment theses with scenario trees, entity mapping,
and adversarial review.

## DATA FLOW (how the pieces fit)
arXiv + Trends + USPTO (L1 collectors)
  -> signals -> classifier (L2, Claude Haiku/Sonnet) -> clusters
  -> cluster hits 3-signal threshold -> thesis loop (L3, 8 steps, Claude + Perplexity)
  -> thesis -> EDGAR enrichment (Step 5.5, SEC API + Haiku, manual per-thesis trigger)
  -> L4 monitoring (signal-spike / quiet detection on Refresh All or Check Monitoring)
  -> L5 decision discipline

Source roles:
- arXiv: category CODES only (cs.AI, cs.HC, quant-ph) -- NOT keyword phrases
- Trends/USPTO: keyword phrases
- EDGAR: free SEC API, no key, requires real email in User-Agent; enrichment only (not a collector)
- Perplexity: web-augmented research inside L3 thesis loop
- Anthropic/Claude: L2 classifier, L3 loop, EDGAR counterparty extraction (Haiku), L5 post-mortems

## CURRENT SYSTEM STATE (end of Session 8)

### FULLY OPERATIONAL LAYERS
- L1 collectors: arXiv, Trends, USPTO (Reddit disabled -- see below)
- L2 classifier/clusterer
- L3 thesis generation loop (8 steps including adversarial challenge)
- L4 monitoring: NOW A WORKING LAYER (was only a foundation at end of Session 7).
  Signal-spike and signal-quiet detection over active theses, baseline-driven,
  surfaced in a dedicated Monitoring tab. See "NEW THIS SESSION" below.
- L5 decision discipline: outcome recording, AI post-mortems (postmortem_loop.py),
  exit-discipline check, full decision immutability (DecisionLockedError / HTTP 409 / amber UI banner)
- Dashboard: full single-page app (server.py, export.py, index.html) with
  Theses tab, Decision Log tab, Outcomes tab, Settings tab, Graph tab, Monitoring tab
- EDGAR enrichment (Step 5.5) fully deployed: enrich + deepen counterparties, panel in thesis detail
- Force-directed Graph tab fully deployed (D3 v7): bottleneck/ring/counterparty nodes,
  edge hover tooltips, zoom/pan/drag
- Thesis versioning (Session 7): thesis_versions table, /api/thesis/rerun, version timeline UI

### NEW THIS SESSION (Session 8)

1. L4 MONITORING LAYER built and deployed (the session's headline work)
   - New package: horizon_scanner/monitoring/monitoring_pass.py
     - run_monitoring_pass(trigger) iterates all ACTIVE theses
       (state IN WATCH|BUILDING|CANDIDATE|ACTIVE), counts signals on each thesis's
       cluster, compares against a stored baseline, and emits monitoring events:
         * SIGNAL_SPIKE  when (current - baseline) >= spike_threshold
         * SIGNAL_QUIET  when no signal collected on the cluster in > quiet_days
     - Returns a summary dict {theses_checked, events_created, spikes, quiets, trigger}.
     - Baseline-driven: first pass on any thesis only RECORDS the baseline
       (no spike can fire until a later pass sees growth). This is correct, not a bug.
   - DB layer (patch_monitoring_db.py, sentinel # L4-MONITORING-DB):
     - Adds read_flag column to monitoring_events (idempotent ALTER, guarded by
       _monitoring_ensure_read_flag).
     - New thesis_signal_baseline table (thesis_id, last_count, last_checked),
       created idempotently in-code via _monitoring_ensure_baseline_table
       (NO manual initialize_database() step needed -- applied the Session 7 lesson).
     - Functions: insert_monitoring_event, get_monitoring_events(limit, unread_only),
       get_unread_monitoring_count, mark_monitoring_event_read, mark_all_monitoring_read,
       get_thesis_baseline, set_thesis_baseline.
   - Server (patch_monitoring_server.py, sentinel # L4-MONITORING-SERVER):
     - POST /api/monitoring/check     -> runs pass standalone (no collectors). "Check Monitoring" button.
     - GET  /api/monitoring/events    -> ?unread=1 filter supported
     - GET  /api/monitoring/unread-count
     - POST /api/monitoring/read-all
     - POST /api/monitoring/events/<id>/read
     - Refresh All hook: run_monitoring_pass(trigger="refresh_all") fires AFTER
       classification, ONLY when source == "all" (per-source refreshes do not run it).
   - UI (patch_monitoring_ui.py, sentinel L4-MONITORING-UI):
     - New Monitoring tab with unread-count badge (amber), event feed (newest first),
       per-event "mark read", "Mark all read", "unread only" toggle, "Check Monitoring" button.
     - Badge refreshes on boot and after a Refresh All completes.
     - Event-type CSS color coding (SIGNAL_SPIKE amber, SIGNAL_QUIET gray, others blue).
   - Config (monitoring: section in config.yaml):
     - spike_threshold: 3, quiet_days: 30, auto_rerun_on_spike: false
     - IMPORTANT: an OLDER monitoring: stub already existed
       (model, schedule, probability_alert_threshold, archive_after_days).
       The first append-style config patch FALSE-POSITIVED on the existing "monitoring:" key
       and skipped. Fixed with patch_monitoring_config_merge.py which inserts the three
       new keys INTO the existing section (preserving the old keys).
   - VERIFIED WORKING: Check Monitoring runs over 14 active theses, writes 14 baselines,
     0 spikes on first pass (correct). Monitoring tab renders, badge updates.

2. SHARED THESIS-RERUN REFACTOR (enabling clean auto-rerun)
   - Extracted module-level start_thesis_rerun(thesis_id, trigger) and
     _run_thesis_rerun_worker(job_id, thesis_id, trigger) in server.py.
   - The HTTP handler _handle_thesis_rerun now DELEGATES to start_thesis_rerun.
   - The monitoring pass calls start_thesis_rerun directly when auto_rerun_on_spike
     is true (currently OFF by default). One implementation, multiple callers.
   - Rationale: the old rerun logic lived inside a request-handler method (needed self),
     so monitoring could not reuse it. Now it is a plain module function.

3. DUPLICATE-THESIS ROOT-CAUSE FIX (Plan B)
   - Problem discovered while inspecting monitoring data: run_thesis_loop() always
     calls insert_thesis() -> a NEW thesis row every run. Reruns AND repeat cluster
     escalations were piling up multiple ACTIVE theses on the same cluster
     (cluster 400fb6b2 had 5 active copies; fdecc957 had 3). This would have produced
     duplicate monitoring events (one per copy) on every spike.
   - Part 1 -- stop recurrence (patch_rerun_archive_old.py, sentinel # RERUN-ARCHIVE-OLD):
     After a successful rerun, if new_thesis_id != old thesis_id, the OLD thesis is
     set state='ARCHIVED' and its baseline row deleted. Rerun is now a true supersede:
     old -> ARCHIVED, new -> active. Version history preserved in thesis_versions.
   - Part 2 -- one-time cleanup (cleanup_duplicate_theses.py):
     Keep-rule = most recently UPDATED thesis per cluster (NOT most recently created --
     the actively-iterated thesis is the one with the latest last_updated, even if an
     idle re-escalation created a newer row afterward). Archives the rest, deletes their
     orphaned baselines. DRY-RUN by default; --commit to apply.
   - APPLIED: kept d1d64590 (battery) and 0db193cb (quantum error correction),
     archived 6, verified one active thesis per cluster afterward.

### DATABASE (confirmed this session)
- REAL database: C:\Projects\horizon-scanner\data\horizon_scanner.db
- Stray empty 4KB C:\Projects\horizon-scanner\horizon_scanner.db (root) -- still ignore it.
- Any DB maintenance script MUST point at the data\ path.
- Real tables: signals, signal_clusters, theses, monitoring_events, decisions,
  collector_sources, thesis_versions, thesis_signal_baseline (NEW this session)
- theses.state vocabulary: WATCH|BUILDING|CANDIDATE|ACTIVE|RESOLVED|ARCHIVED
  (separate from theses.confidence_rating: WATCH|BUILDING|CANDIDATE|INSUFFICIENT).
  There is NO "BUY" state; BUY lives in the decisions ledger, not the thesis.
- Signals link to clusters via signals.cluster_id = signal_clusters.id;
  a thesis links via theses.cluster_id. Count signals for a thesis:
  SELECT COUNT(*) FROM signals WHERE cluster_id = <thesis.cluster_id>.
- get_connection() (database.py ~line 331) resolves path from config["database"]["path"].

### DISK SPACE (unchanged from Session 7)
- venv is ~1 GB (the real space hog); database is only ~3 MB.
- To reclaim space, delete+recreate venv (deactivate; Remove-Item -Recurse -Force venv;
  python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -e .).
- Plan to move whole project to external disk eventually (deferred). Project is self-contained.

## ENVIRONMENT VARIABLES
- ANTHR_HORIZON: Anthropic API key (system env var)
- PERPLEX_HORIZON: Perplexity API key (system env var)
- USPTO_ODP_KEY: USPTO ODP key. Set as BOTH user and system env var (ID.me verification done).
  For an already-open PowerShell session that predates the var, set inline:
    $env:USPTO_ODP_KEY = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment").USPTO_ODP_KEY

## REDDIT (disabled)
- enabled: false in config.yaml. Reddit 403-blocks anonymous API access.
- Fixing requires OAuth/PRAW. LOW PRIORITY.

## KEY FILES
- horizon_scanner/collectors/uspto_collector.py
- horizon_scanner/enrichment/edgar_client.py
- horizon_scanner/monitoring/monitoring_pass.py        (NEW this session)
- horizon_scanner/dashboard/server.py
- horizon_scanner/dashboard/index.html (static dir, served as root)
- horizon_scanner/database.py
- horizon_scanner/thesis/thesis_loop.py
- horizon_scanner/thesis/postmortem_loop.py
- config.yaml (root + package copy kept in sync)

## DELIVERY CONVENTIONS (CRITICAL - maintain across sessions)
- All code as runnable patch scripts, delivered as DOWNLOADS (present_files), placed at
  project root C:\Projects\horizon-scanner\, run in PowerShell.
- Idempotent patch scripts with sentinel-anchor pattern; abort cleanly on anchor mismatch.
- Unique-string anchors (not line numbers); validate uniqueness (count == 1) before writing.
- ASCII-only output (no Unicode arrows, bullets, box-drawing -- Windows encoding corruption).
- AST parse validation before presenting any .py file.
- Dry-run validation against actual uploaded files before delivery (copy to scratch,
  apply patch, diff against hand-edited version, confirm IDENTICAL). This session that
  caught nothing broken but confirmed every server.py / index.html patch byte-for-byte.
- For HTML/JS edits, extract the inline <script> and run `node --check` on it; confirm
  tab/view parity (every data-view has a matching id="view-..."). Both caught zero errors
  this session but are now part of the standard validation.
- Complete files not diffs when file is small enough.
- CRLF awareness: Windows files use \r\n. Prefer SINGLE-LINE anchors or two-line
  section-opener anchors. Multi-line anchors that span lines can fail on CRLF.
- UPLOAD THE BIG FILES: when a patch targets server.py or index.html, ask Bill to upload
  the current file. Working from the real file (not greps) made the Session 8 server/UI
  patches exact on the first try.
- PowerShell here-string Python with f-strings and \" escapes RELIABLY FAILS
  (SyntaxError: unexpected character after line continuation). ALWAYS deliver probes as
  downloadable .py files using %-formatting and plain double quotes -- never inline.
- Inspect real data before building code that assumes structure (probe scripts, paste output).

## NEW PATTERNS / LESSONS (Session 8)
- CONFIG FALSE-POSITIVE: a section-add patch that checks `if "\nmonitoring:" in src`
  will skip when an unrelated older section of the same name exists. When adding keys to
  a config that MIGHT already have the top-level key, probe the existing block first and
  write a MERGE patch (insert keys after the section header) rather than an append patch.
- DEDUP KEEP-RULE: when collapsing duplicate rows that represent an iterated entity,
  keep most-recently-UPDATED, not most-recently-created. A stray idle row created later
  is not the live one; last_updated tracks real work.
- INSPECT-THEN-EXTRACT for shared logic: the rerun logic was trapped in a handler method.
  Confirm globals (_JOBS, _JOBS_LOCK, logger, db) are module-level, then extract a plain
  module function the handler delegates to. Keeps one implementation for HTTP + internal callers.
- BASELINE SEMANTICS: spike detection needs a stored baseline so "spike since last check"
  is meaningful for the on-demand Check button (not just "signals since thesis.last_updated").
  First pass establishes baselines and fires nothing; this is expected behavior to explain.

## EDGAR QUIRKS (hard-won, unchanged)
- EFTS full-text search: OR-chain queries cause HTTP 500 via URL encoding; use sequential
  single-phrase searches and merge.
- Hyphens inside quoted phrases act as NOT operators; use spaces ("cross license").
- EFTS _id field encodes accession:filename -- the filename is the exact document with the
  matched phrase; do not discard it and re-guess by exhibit rank.
- index_url points to SEC index pages (document tables), not text; use resolve_filing_documents().
- _window_around_phrase() centered on matched_phrase (+-3000 chars) for counterparty extraction.
- Transient 500s from EFTS: retry with backoff.
- Counterparty extraction uses a Haiku LLM pass (confirmed on IBM: Kyndryl, Prudential, MetLife).

## USPTO QUIRKS (hard-won, unchanged)
- Legacy endpoint developer.uspto.gov/ibd-api/v1 decommissioned 2026-06-05.
  Current: api.uspto.gov/api/v1/patent/applications/search
- Free-form phrase search q='"phrase"' works; field-scoped title phrase search 404s for most keywords.
- 404 "No matching records found" is a genuine no-results response, NOT a syntax error.
- 30-day lookback returns near-zero for niche keywords; use 90.
- 429 backoff with hard request ceiling to avoid 7-day quota lockout.

## OPEN ITEMS / NEXT PRIORITIES
1. WIRE AUTO-RERUN ON SPIKE (low effort, high payoff now that plumbing exists):
   - auto_rerun_on_spike is currently false. Flipping it true makes SIGNAL_SPIKE call
     start_thesis_rerun(thesis_id, trigger="signal_spike"). The shared refactor + the
     rerun-archive fix mean this is now safe (spike -> rerun -> old archived, no dup).
   - Before enabling, consider a guard so a thesis cannot auto-rerun more than once per
     N hours (avoid spike storms burning thesis-loop API budget).
2. MONITORING DEPTH (optional next build-out):
   - STATE_CHANGE / CONFIRMING / CONTRADICTING events (the original event_type vocabulary
     the monitoring_events table was designed for) are not yet generated -- only
     SIGNAL_SPIKE / SIGNAL_QUIET are. Could emit STATE_CHANGE when a thesis state changes,
     or CONFIRMING/CONTRADICTING from classifier category on new signals in a watched cluster.
   - Optional: scheduled/background monitoring timer (the pass is already a standalone
     callable, so a timer would just call run_monitoring_pass on an interval).
3. USPTO schedule enforcement: config has schedule: weekly but collector runs every
   Refresh All regardless; needs a last-run timestamp check.
4. Include table-creation in future schema patches (DONE this session for the baseline
   table; keep doing it -- avoids the manual initialize_database() step).
5. Reddit OAuth/PRAW fix (LOW priority).
6. Move project to external disk (deferred).

## SESSION 8 PATCH SCRIPTS APPLIED (in order, all succeeded)
1. patch_monitoring_db.py            -- monitoring DB funcs + read_flag + baseline table
2. patch_monitoring_config.py        -- (reported "already": false-positived on old monitoring: stub)
3. patch_monitoring_pass.py          -- monitoring/monitoring_pass.py module
4. patch_monitoring_server.py        -- shared rerun refactor + monitoring endpoints + Refresh hook
5. patch_monitoring_ui.py            -- Monitoring tab, badge, Check Monitoring button
6. patch_monitoring_config_merge.py  -- insert spike_threshold/quiet_days/auto_rerun_on_spike
                                        into existing monitoring: section (fix for #2)
7. patch_rerun_archive_old.py        -- rerun archives the superseded thesis (# RERUN-ARCHIVE-OLD)
8. cleanup_duplicate_theses.py --commit -- one-time dedup (kept 2, archived 6)

## DIAGNOSTIC TOOLS AT PROJECT ROOT
- probe_uspto.py, probe_uspto2.py    -- test exact USPTO request bodies
- probe_dupes2.py                    -- list clusters with multiple active theses (full IDs + timestamps)
- cleanup_duplicate_theses.py        -- dedup tool, safe to re-run (dry-run unless --commit)
- wipe_db.py                         -- clear data tables + VACUUM (points at data\horizon_scanner.db)
- (assorted probe_*.py from this session: probe_monitoring, probe_states, probe_theses_schema,
   probe_signals_schema, probe_moncfg, probe_monblock, probe_monstate -- safe to delete)

## CURRENT STATUS TO UPDATE EACH SESSION
- Last confirmed working: L4 monitoring end-to-end (Check Monitoring over 14 active theses,
  14 baselines written, 0 spikes first pass as expected, Monitoring tab + badge render);
  duplicate cleanup applied (one active thesis per cluster); rerun-archive fix deployed.
- Git: commit Session 8 work
  (L4 monitoring layer, shared rerun refactor, duplicate root-cause fix + cleanup).
  Suggested: git add -A && git commit -m "L4 monitoring + shared rerun + thesis dedup fix"
- Next: wire auto_rerun_on_spike (with a per-thesis cooldown guard), then optionally
  deeper monitoring event types (STATE_CHANGE / CONFIRMING / CONTRADICTING).
