# HORIZON SCANNER - SESSION 7 MASTER PROMPT

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
  -> L4 monitoring -> L5 decision discipline

Source roles:
- arXiv: category CODES only (cs.AI, cs.HC, quant-ph) -- NOT keyword phrases
- Trends/USPTO: keyword phrases
- EDGAR: free SEC API, no key, requires real email in User-Agent; enrichment only (not a collector)
- Perplexity: web-augmented research inside L3 thesis loop
- Anthropic/Claude: L2 classifier, L3 loop, EDGAR counterparty extraction (Haiku), L5 post-mortems

## CURRENT SYSTEM STATE (end of Session 7)

### FULLY OPERATIONAL LAYERS
- L1 collectors: arXiv, Trends, USPTO (Reddit disabled -- see below)
- L2 classifier/clusterer
- L3 thesis generation loop (8 steps including adversarial challenge)
- L4 monitoring foundation (monitoring_events table exists; deeper build-out still pending)
- L5 decision discipline: outcome recording, AI post-mortems (postmortem_loop.py),
  exit-discipline check, full decision immutability (DecisionLockedError / HTTP 409 / amber UI banner)
- Dashboard: full single-page app (server.py, export.py, index.html) with
  Theses tab, Decision Log tab, Outcomes tab, Settings tab, Graph tab
- EDGAR enrichment (Step 5.5) fully deployed: enrich + deepen counterparties, panel in thesis detail
- Force-directed Graph tab fully deployed (D3 v7): bottleneck/ring/counterparty nodes,
  edge hover tooltips, zoom/pan/drag

### NEW THIS SESSION (Session 7)
1. USPTO keyword search FIXED and WORKING
   - Root cause of prior 404s: field-scoped exact-phrase title search
     (applicationMetaData.inventionTitle:"phrase") returns 404 for multi-word phrases
     that do not appear verbatim in invention titles.
   - Fix: free-form phrase search. _build_keyword_body now sends q_value = f'"{keyword}"'
     (quoted phrase, no field prefix) which matches across all searchable fields.
   - Patch applied: patch_uspto_keyword_freeform.py (sentinel: # USPTO-KEYWORD-FREEFORM-SEARCH)
   - lookback_days raised from 30 to 90 in config.yaml uspto section.
     30-day window genuinely returns near-zero results for these niche keywords;
     90-day window returns results (confirmed: "solid state battery" returns records).
   - Auth probe confirms USPTO auth OK (HTTP 200) at collector start.
   - Diagnostic probes built: probe_uspto.py, probe_uspto2.py (test exact request bodies;
     keep for future USPTO debugging).

2. USPTO accepted as a source_type in Settings UI
   - Prior bug: server validation rejected adding USPTO keywords
     ("source_type must be arxiv, trends, or reddit").
   - Patch applied: patch_server_uspto_sourcetype.py (sentinel: # SOURCE-TYPE-USPTO-ALLOWED)
   - Now accepts arxiv | trends | reddit | uspto.

3. THESIS VERSIONING fully built and deployed
   - DB: new thesis_versions table (id, thesis_id, version_number, snapshotted_at, trigger, snapshot JSON).
     New functions in database.py: snapshot_thesis_version(thesis_id, trigger),
     get_thesis_versions(thesis_id).
     Patch applied: patch_thesis_versioning_db.py (sentinel: # THESIS-VERSIONING-DB)
   - Server: POST /api/thesis/rerun (snapshots current thesis, then re-runs loop on same cluster_id),
     GET /api/thesis/<id>/versions. Background job kind="thesis_rerun".
     Patch applied: patch_thesis_versioning_server.py (sentinel: # THESIS-VERSIONING-SERVER)
   - UI: collapsible "Version History" section in thesis detail (between EDGAR and Scenario Tree),
     "Re-run thesis loop" button, timeline showing per-version deltas
     (score, confidence, bottleneck), click row to expand adversarial summary + kill criteria.
     Patch applied: patch_thesis_versioning_ui.py (sentinel: THESIS-VERSIONING-UI)
   - VERIFIED WORKING: v1 and v2 snapshots render with deltas; re-run completes and reloads.

4. "Virtual reality" added to Trends, USPTO keywords, and cs.HC added to arXiv categories
   (demonstrates the cross-source add workflow; new topics take several collection cycles
    to accumulate enough signals to form a cluster and generate a thesis).

### ONE-TIME SCHEMA CATCH-UP (important pattern)
- When a NEW table is added to the schema after the DB file already exists, the running
  dashboard will throw "no such table: X" until initialize_database() runs.
- Fix: python -c "from horizon_scanner import database; database.initialize_database()"
  then restart dashboard. All CREATE TABLE use IF NOT EXISTS so this is safe and idempotent.
- FUTURE: include the table-creation call inside the patch itself to avoid this manual step.

### DATABASE LOCATION (confirmed this session)
- REAL database: C:\Projects\horizon-scanner\data\horizon_scanner.db (the one with all tables/data)
- There is a stray empty 4KB C:\Projects\horizon-scanner\horizon_scanner.db (root) -- ignore it.
- Any DB maintenance script MUST point at the data\ path.
- Real tables: signals, signal_clusters, theses, monitoring_events, decisions,
  collector_sources, thesis_versions
- wipe_db.py (at root) clears signals/theses/decisions/signal_clusters and VACUUMs.
  NOTE: VACUUM cannot run inside a transaction -- commit first, or set isolation_level=None.

### DISK SPACE
- venv is ~1 GB (the real space hog); database is only ~3 MB.
- Wiping the DB barely affects disk. To reclaim space, delete+recreate venv:
    deactivate; Remove-Item -Recurse -Force venv; python -m venv venv;
    .\venv\Scripts\Activate.ps1; pip install -e .
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
- Dry-run validation against actual uploaded files before delivery (copy to /home/claude scratch).
- Complete files not diffs when file is small enough.
- CRLF awareness: Windows files use \r\n. Multi-line anchors that span lines can fail on CRLF;
  prefer SINGLE-LINE anchors or two-line section-opener anchors. (This session, single-line
  anchors on distinctive lines worked reliably where multi-line CRLF anchors counted 0.)
- PowerShell inline Python with complex quotes RELIABLY FAILS -- always write a .py file.
- Inspect real data before building code that assumes structure (probe scripts, paste output).

## EDGAR QUIRKS (hard-won)
- EFTS full-text search: OR-chain queries cause HTTP 500 via URL encoding; use sequential
  single-phrase searches and merge.
- Hyphens inside quoted phrases act as NOT operators; use spaces ("cross license" not "cross-license").
- EFTS _id field encodes accession:filename -- the filename is the exact document with the
  matched phrase; do not discard it and re-guess by exhibit rank.
- index_url points to SEC index pages (document tables), not text; use resolve_filing_documents().
- _window_around_phrase() centered on matched_phrase (+-3000 chars) for counterparty extraction.
- Transient 500s from EFTS: retry with backoff.
- Counterparty extraction uses a Haiku LLM pass (confirmed working on IBM: Kyndryl, Prudential, MetLife).

## USPTO QUIRKS (hard-won)
- Legacy endpoint developer.uspto.gov/ibd-api/v1 decommissioned 2026-06-05.
  Current: api.uspto.gov/api/v1/patent/applications/search
- Free-form phrase search q='"phrase"' works; field-scoped title phrase search 404s for most keywords.
- 404 "No matching records found" is a genuine no-results response, NOT a syntax error.
- 30-day lookback returns near-zero for niche keywords; use 90.
- 429 backoff with hard request ceiling to avoid 7-day quota lockout.

## OPEN ITEMS / NEXT PRIORITIES
1. L4 monitoring fuller build-out (HIGHEST VALUE NEXT):
   - monitoring_events table exists but layer is only a foundation.
   - Needs: scheduled re-scoring of watched theses, alerting on signal spikes,
     surfacing monitoring events in the dashboard.
   - Natural tie-in: a signal spike could auto-trigger /api/thesis/rerun with trigger="signal_spike"
     (the versioning system already supports that trigger value).
2. USPTO schedule enforcement: config has schedule: weekly but collector runs every Refresh All
   regardless; needs a last-run timestamp check.
3. Include table-creation in future schema patches (avoid the manual initialize_database() step).
4. Reddit OAuth/PRAW fix (LOW priority).
5. Move project to external disk (deferred).
6. Optional: lower cluster escalation threshold temporarily to fast-track a VR thesis for testing.

## SESSION 7 PATCH SCRIPTS APPLIED (in order, all succeeded)
1. patch_uspto_keyword_freeform.py   -- free-form USPTO phrase search
2. patch_server_uspto_sourcetype.py  -- allow uspto as source_type in Settings UI
3. patch_thesis_versioning_db.py     -- thesis_versions table + snapshot/get functions
4. patch_thesis_versioning_server.py -- /api/thesis/rerun + /api/thesis/<id>/versions
5. patch_thesis_versioning_ui.py     -- Version History UI + Re-run button
   (plus one-time: initialize_database() to create thesis_versions in the existing DB file)

## DIAGNOSTIC TOOLS AT PROJECT ROOT
- probe_uspto.py, probe_uspto2.py -- test exact USPTO request bodies (8 query-form variants)
- wipe_db.py -- clear data tables + VACUUM (points at data\horizon_scanner.db)

## CURRENT STATUS TO UPDATE EACH SESSION
- Last confirmed working: USPTO keyword collection (90-day, free-form); USPTO keyword add in Settings;
  thesis versioning end-to-end (snapshot, re-run, version timeline with deltas);
  Graph tab; EDGAR enrich + deepen.
- Git: commit Session 7 work
  (USPTO fix, USPTO settings, thesis versioning) if not already committed.
- Next: L4 monitoring fuller build-out.
