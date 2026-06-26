# HORIZON SCANNER - SESSION 9 MASTER PROMPT

## WHO YOU ARE TALKING TO
Bill. SCADA/OT/EMS background. Solo technical build. Windows + PowerShell.
Python venv at C:\Projects\horizon-scanner (deliberately outside OneDrive).
GitHub: github.com/billcw/horizon-scanner (private). Username: billcw, email: billcw@users.noreply.github.com.
Editable install: pip install -e . (setup.py at root). Launch: python run.py dashboard.

Bill typically confirms design with short answers and defers architectural decisions to Claude.
Working rhythm: build -> validate -> present as downloads -> Bill places files -> test -> commit.

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
  -> L4 monitoring (spike / quiet / relevance detection on Refresh All or Check Monitoring)
  -> L5 decision discipline

Source roles:
- arXiv: category CODES only (cs.AI, cs.HC, quant-ph) -- NOT keyword phrases
- Trends/USPTO: keyword phrases
- EDGAR: free SEC API, no key, requires real email in User-Agent; enrichment only (not a collector)
- Perplexity: web-augmented research inside L3 thesis loop
- Anthropic/Claude: L2 classifier, L3 loop, EDGAR counterparty extraction (Haiku),
  L4 relevance assessment (Haiku, NEW this session), L5 post-mortems

## CURRENT SYSTEM STATE (end of Session 9)

### FULLY OPERATIONAL LAYERS
- L1 collectors: arXiv, Trends, USPTO (Reddit disabled -- see below)
- L2 classifier/clusterer
- L3 thesis generation loop (8 steps including adversarial challenge)
- L4 monitoring: signal-spike, signal-quiet, AND relevance (CONFIRMING/CONTRADICTING) detection.
  Baseline-driven, surfaced in a dedicated Monitoring tab. Relevance is NEW this session.
- L5 decision discipline: outcome recording, AI post-mortems (postmortem_loop.py),
  exit-discipline check, full decision immutability (DecisionLockedError / HTTP 409 / amber UI banner)
- Dashboard: full single-page app (server.py, export.py, index.html) with
  Theses tab, Decision Log tab, Outcomes tab, Settings tab, Graph tab, Monitoring tab
- EDGAR enrichment (Step 5.5) fully deployed: enrich + deepen counterparties, panel in thesis detail
- Force-directed Graph tab fully deployed (D3 v7): bottleneck/ring/counterparty nodes,
  edge hover tooltips, zoom/pan/drag
- Thesis versioning (Session 7): thesis_versions table, /api/thesis/rerun, version timeline UI

### NEW THIS SESSION (Session 9)

1. L4 RELEVANCE ASSESSMENT -- CONFIRMING / CONTRADICTING events (the session's headline)
   - When a thesis accrues NEW signals since its baseline, the new signal batch is judged
     against the thesis by a Haiku pass and classified CONFIRMING / CONTRADICTING / NEUTRAL.
   - GATED to control cost: assessment fires only when (current - last_count) >= assess_min_signals
     (default 2). Single stray signals never trigger a Haiku call.
   - NEUTRAL verdicts are assessed but intentionally NOT logged (keeps the Monitoring feed
     signal-rich -- no "nothing changed" noise). Only CONFIRMING/CONTRADICTING write events.
   - Wholly NON-FATAL: missing SDK, missing ANTHR_HORIZON key, bad/unparseable response, or any
     exception -> logs and the pass continues. Never aborts monitoring.
   - Runs ALONGSIDE the existing spike/quiet checks in the same per-thesis loop; independent.
   - DESIGN NOTE -- count-based delta, not timestamp filter: signals.collected_at is written with
     datetime.now(timezone.utc).isoformat() (carries a +00:00 suffix) while baseline last_checked
     uses datetime.utcnow().isoformat() (naive, no suffix). String-comparing them in SQL is
     unreliable. So "new signals" = the newest (current - last_count) rows on the cluster, ordered
     by collected_at DESC. Sidesteps the format mismatch and matches how spike detection reasons.
   - Reuses the project's exact Haiku convention: lazy `import anthropic`,
     anthropic.Anthropic(api_key=os.environ["ANTHR_HORIZON"]),
     client.messages.create(model, max_tokens, system, messages=[...]),
     parse response.content[0].text. Same pattern as edgar_client / thesis_loop / postmortem_loop.
   - BASELINE SEMANTICS still apply: the first monitoring pass after deploying establishes
     baselines and fires NO relevance events (the gate needs a prior last_count to measure
     a delta against). Expected, not a bug.

   Patch scripts applied (all idempotent, sentinel-anchored, AST-validated, ASCII-only):
   a. patch_monitoring_relevance_db.py    (sentinel # L4-MONITORING-RELEVANCE-DB)
      - Adds get_recent_cluster_signals(cluster_id, limit=10) to database.py:
        newest-first signals on a cluster (id, title, category, theme, collected_at).
      - Inserted just before the baseline-table section, with the other monitoring helpers.
   b. patch_monitoring_relevance_pass.py  (sentinel # L4-MONITORING-RELEVANCE-PASS)
      - Extends _cfg() to read assess_relevance (bool, default True), assess_min_signals
        (int, default 2), and model (default claude-haiku-4-5-20251001).
      - Adds _get_anthropic_client(), _extract_json_object(text), _VALID_VERDICTS,
        and _assess_relevance(thesis, cluster_id, new_count, model, summary).
      - Calls _assess_relevance right before the baseline update, gated on
        (current - last_count) >= assess_min_signals, wrapped non-fatal.
      - summary gains an optional "relevance": [(thesis_id, verdict), ...] key.
   c. patch_monitoring_relevance_config.py
      - MERGE patch (not append) inserting assess_relevance: true and assess_min_signals: 2
        into the EXISTING monitoring: section, right after auto_rerun_on_spike
        (applies the Session 8 false-positive lesson).
   - VERIFIED WORKING end-to-end: forced a delta with probe_force_delta.py, ran Check Monitoring,
     a CONFIRMING/CONTRADICTING event landed in the Monitoring tab with a one-line rationale.

2. NEW DIAGNOSTIC TOOL: probe_force_delta.py (at project root)
   - Test helper for the relevance feature. Burns NO API itself; only rewrites one
     thesis_signal_baseline row. Safe and reversible (next full pass re-records the real baseline).
   - `python probe_force_delta.py --list`           -> active theses with signal counts + baselines
   - `python probe_force_delta.py --thesis <ID>`     -> sets that thesis's baseline 3 below current
   - `python probe_force_delta.py --thesis <ID> --delta 5`  -> custom delta
   - Then click Check Monitoring; the forced thesis crosses the gate and a single Haiku judgment runs.
   - If Haiku returns NEUTRAL, no event is written (correct) -- try another thesis with more
     clearly directional new signals.

3. DECISIONS THIS SESSION (deliberately scoped OUT)
   - USPTO schedule enforcement: DECIDED AGAINST building automated last-run gating.
     Manual control is sufficient -- USPTO is one niche feeder among several, has 429 backoff,
     and Bill is a solo user not running on a cron. Dropped from the priority list.
     (If the patent stream ever looks thin, just run a Refresh All.)
   - Auto-rerun on spike: reviewed and DEFERRED again (not against it). The manual flow
     (see spike in Monitoring tab -> decide -> click Re-run) gives better control over when
     thesis-loop API budget is spent. Plumbing remains ready if/when wanted (see Open Items).

### DATABASE (confirmed, unchanged structurally except the relevance helper is a read-only addition)
- REAL database: C:\Projects\horizon-scanner\data\horizon_scanner.db
- Stray empty 4KB C:\Projects\horizon-scanner\horizon_scanner.db (root) -- still ignore it.
- Any DB maintenance script MUST point at the data\ path.
- Real tables: signals, signal_clusters, theses, monitoring_events, decisions,
  collector_sources, thesis_versions, thesis_signal_baseline
- monitoring_events.event_type vocabulary in use: SIGNAL_SPIKE, SIGNAL_QUIET,
  CONFIRMING, CONTRADICTING (NEW). STATE_CHANGE still designed-for but not yet generated.
- theses.state vocabulary: WATCH|BUILDING|CANDIDATE|ACTIVE|RESOLVED|ARCHIVED
  (separate from theses.confidence_rating: WATCH|BUILDING|CANDIDATE|INSUFFICIENT).
  There is NO "BUY" state; BUY lives in the decisions ledger, not the thesis.
- Signals link to clusters via signals.cluster_id = signal_clusters.id;
  a thesis links via theses.cluster_id. Count signals for a thesis:
  SELECT COUNT(*) FROM signals WHERE cluster_id = <thesis.cluster_id>.
- signals.category vocabulary: NOISE | FAD | CULTURAL | EMERGING | STRUCTURAL
  (plus UNCLASSIFIED). Signals also carry title, theme, content, collected_at.
- get_connection() (database.py ~line 331) resolves path from config["database"]["path"].

### DISK SPACE (unchanged)
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
- horizon_scanner/monitoring/monitoring_pass.py
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
  apply patch, confirm idempotency on re-run, AST/py_compile, inspect output).
- For HTML/JS edits, extract the inline <script> and run `node --check` on it; confirm
  tab/view parity (every data-view has a matching id="view-...").
- Complete files not diffs when file is small enough.
- CRLF awareness: Windows files use \r\n. Prefer SINGLE-LINE anchors or two-line
  section-opener anchors. Multi-line anchors that span lines can fail on CRLF.
- UPLOAD THE BIG FILES: when a patch targets server.py or index.html, ask Bill to upload
  the current file. Working from the real file (not greps) makes patches exact on the first try.
  (This session: the files Bill named didn't render in the document view but WERE on disk at
  /mnt/user-data/uploads/ -- always check disk with ls before assuming an upload failed.)
- PowerShell here-string Python with f-strings and \" escapes RELIABLY FAILS. ALWAYS deliver
  probes as downloadable .py files using %-formatting and plain double quotes -- never inline.
- Inspect real data before building code that assumes structure (probe scripts, paste output).
- For a new LLM call, COPY the existing Haiku/Sonnet convention from edgar_client.py rather than
  inventing one (lazy import anthropic, ANTHR_HORIZON, messages.create, response.content[0].text).

## LESSONS CARRIED FORWARD
- CONFIG FALSE-POSITIVE: a section-add patch that checks `if "monitoring:" in src` skips when
  an older section of the same name exists. Adding keys to a possibly-existing top-level key ->
  MERGE patch (insert after a unique line inside the block), not append.
- DEDUP KEEP-RULE: when collapsing duplicate iterated rows, keep most-recently-UPDATED, not
  most-recently-created. last_updated tracks real work; idle re-escalations make newer junk rows.
- INSPECT-THEN-EXTRACT for shared logic: confirm module-level globals exist, then extract a plain
  module function the handler delegates to (one implementation, multiple callers).
- BASELINE SEMANTICS: first monitoring pass after any change only (re)records baselines and fires
  no spike/relevance events. Expected; explain it rather than debugging it.
- TIMESTAMP FORMAT MISMATCH: signals.collected_at has a +00:00 suffix; baseline last_checked is
  naive UTC. Don't string-compare them. Use count-based deltas (newest current-last_count rows).
- SCHEMA CHANGES post-DB-creation: fold idempotent in-code table/column creation into the patch
  (in-code ensure-helpers), avoiding a manual initialize_database() step.
- Step 7 adversarial challenge needs max_tokens ~3000 to avoid JSON truncation -> BEAR VERDICT: None.

## EDGAR QUIRKS (hard-won, unchanged)
- EFTS full-text search: OR-chain queries cause HTTP 500; use sequential single-phrase searches and merge.
- Hyphens inside quoted phrases act as NOT operators; use spaces ("cross license").
- EFTS _id field encodes accession:filename -- the filename is the exact document with the matched
  phrase; do not discard it and re-guess by exhibit rank.
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

1. SEED THESIS -- manual thesis from ticker/company name (NEXT SESSION HEADLINE)
   - Top-down path: Bill enters a ticker or company name -> a thesis is generated around it,
     rather than emerging bottom-up from a signal cluster crossing the 3-signal threshold.
   - Must fit in so the rest of the system treats it like any other thesis: monitoring (spike/
     quiet/relevance), EDGAR enrichment, decisions, versioning, graph -- all work identically.
   - Proposed shape (a "seed thesis" path):
     a. Create a synthetic/seed cluster keyed to the entered company as the subject.
     b. Run the same L3 8-step thesis loop against it (Perplexity research seeded by the company).
     c. Insert the result as a normal thesis row -- indistinguishable from an organic one.
     d. From there EDGAR enrichment, monitoring, decisions all work with no special-casing.
   - Effort: moderate-to-significant. The thesis loop is reusable; the work is the "seed" layer
     that manufactures a starting point + a small UI entry point (likely a button on the Theses tab).
   - Worth its own focused session.

2. AUTO-RERUN ON SPIKE (deferred, plumbing ready -- NOT decided against)
   - auto_rerun_on_spike is false. Flipping true makes SIGNAL_SPIKE call
     start_thesis_rerun(thesis_id, trigger="signal_spike"). Shared refactor + rerun-archive fix
     mean this is safe (spike -> rerun -> old archived, no dup).
   - Before enabling, add a per-thesis cooldown guard (e.g. no auto-rerun more than once per
     N hours) so a spike storm can't burn thesis-loop API budget.
   - Currently deferred in favor of manual control; revisit if the manual flow gets tedious.

3. MONITORING DEPTH -- remaining event types (optional)
   - STATE_CHANGE events: emit when a thesis state changes (the event_type vocabulary already
     anticipates this; not yet generated).
   - Optional scheduled/background monitoring timer: run_monitoring_pass is already a standalone
     callable, so a timer would just invoke it on an interval (cost-aware: this would auto-fire
     Haiku relevance calls, so gate/throttle accordingly).

4. Reddit OAuth/PRAW fix (LOW priority).

5. Move project to external disk (deferred; project is self-contained).

6. HOUSEKEEPING (optional, low effort): the repo root has accumulated ~15 probe_*.py and
   ~10 patch_*.py one-off files (all committed at 916d317). Harmless but cluttering. Options:
   move spent probes/patches into an archive/ folder (git mv batch), and/or add probe_*.py to
   .gitignore so future diagnostics aren't committed (keep patch_*.py tracked as change records).

## OPERATIONAL GUIDE (accumulating -- for the end-of-project usage reference)
This section collects "how to actually run/use it" process notes. Grow it every session.

- RUNNING / TESTING L4 MONITORING:
  * Use the "Check Monitoring" button -> runs a standalone monitoring pass, NO collector quota cost.
  * Do NOT use "Refresh All" just to test monitoring -- Refresh All runs the collectors (burns
    arXiv/Trends/USPTO quota) AND fires a monitoring pass at the end (only when source == "all").
  * First monitoring pass after ANY code change only (re)records baselines -- no spike or relevance
    events fire on that first pass. This is correct behavior, not a failure.
  * Relevance (CONFIRMING/CONTRADICTING) fires only when (current signal count - baseline last_count)
    >= assess_min_signals (default 2). NEUTRAL is assessed but never logged.
  * To force a relevance event for testing: probe_force_delta.py --thesis <ID> lowers that thesis's
    baseline by 3, then click Check Monitoring. A single Haiku judgment runs for that thesis.
- AFTER PATCHING CODE:
  * Restart the dashboard after editing .py files (Python module changes do NOT hot-reload;
    the running process holds the old code in memory). Ctrl+C, then python run.py dashboard.
  * config.yaml changes DO hot-reload via reset_config_cache() -- no restart needed for yaml-only edits.
- LAUNCH / USAGE:
  * python run.py dashboard   -> launch the dashboard.
  * python run.py             -> prints usage.

## DELIVERY CONVENTION REMINDER FOR NEXT SESSION (seed thesis)
- The seed-thesis feature will touch server.py (new endpoint), index.html (UI entry point),
  database.py (seed-cluster/thesis insert), and reuse thesis_loop. ASK BILL TO UPLOAD the current
  server.py, index.html, database.py, and thesis_loop.py before building, and inspect the real
  thesis-loop entry signature (how run_thesis_loop is invoked, what state it expects) before
  designing the seed path. Probe the cluster/thesis insert path first.

## SESSION 9 PATCH SCRIPTS APPLIED (in order, all succeeded)
1. patch_monitoring_relevance_db.py     -- get_recent_cluster_signals() in database.py
2. patch_monitoring_relevance_pass.py   -- gated CONFIRMING/CONTRADICTING relevance assessment
3. patch_monitoring_relevance_config.py -- assess_relevance + assess_min_signals into monitoring:
(plus probe_force_delta.py delivered as a test helper, not a patch.)

Git: committed at 916d317
  "L4 monitoring: gated CONFIRMING/CONTRADICTING relevance events"
  (that commit also swept in carried-over scratch files -- see Housekeeping item 6).

## CURRENT STATUS TO UPDATE EACH SESSION
- Last confirmed working: L4 relevance assessment end-to-end (forced a delta via probe_force_delta.py,
  Check Monitoring produced a CONFIRMING/CONTRADICTING event with rationale in the Monitoring tab).
  Spike/quiet detection, duplicate cleanup (one active thesis per cluster), and rerun-archive fix
  all still in place from Session 8.
- Next: SEED THESIS feature (manual thesis from a ticker/company name, folded into the existing
  thesis/monitoring/EDGAR/decision machinery). Then optionally auto-rerun-on-spike with cooldown,
  and/or STATE_CHANGE events.
