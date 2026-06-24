# HORIZON SCANNER - SESSION 6 MASTER PROMPT

## WHO YOU ARE TALKING TO
Bill. SCADA/OT/EMS background. Solo technical build. Windows + PowerShell.
Python venv at C:\Projects\horizon-scanner (deliberately outside OneDrive).
GitHub: github.com/billcw/horizon-scanner (private). Username: billcw, email: billcw@users.noreply.github.com.

## WHAT THIS SYSTEM IS
Horizon Scanner: personal AI-powered investment signal synthesis system.
Surfaces emerging technology opportunities before mainstream adoption.
Enforces structured decision discipline (counters the "MU mistake" -- emotionally-driven investing).
Automates ingestion from arXiv, Reddit, Google Trends, USPTO patents, then runs structured reasoning loops to produce scored investment theses with scenario trees, entity mapping, and adversarial review.

## CURRENT SYSTEM STATE (as of end of Session 5)

### FULLY OPERATIONAL LAYERS
- L1 collectors: arXiv, Reddit (403 blocked currently), Google Trends, USPTO
- L2 classifier/clusterer
- L3 thesis generation loop (8 steps including adversarial challenge)
- L4 monitoring foundation
- L5 decision discipline: outcome recording, AI post-mortems (postmortem_loop.py), exit-discipline check, full decision immutability (DecisionLockedError / HTTP 409 / amber UI banner)
- Dashboard: full single-page app (server.py, export.py, index.html) with Theses tab, Decision Log tab, Outcomes tab, Settings tab, Graph tab
- Launch: python run.py dashboard

### EDGAR ENRICHMENT (Step 5.5) - FULLY DEPLOYED
- enrichment/edgar_client.py: resolve_cik(), get_recent_filings(), get_ip_section(), find_licensing_mentions(), resolve_filing_documents(), extract_counterparties(), deepen_counterparties()
- EDGAR enrichment panel renders in thesis detail view with verified badges, CIK links, licensing filing dates
- "Run EDGAR Enrichment" button: appears on un-enriched theses; triggers /api/thesis/enrich background job that runs Step 5.5 on any existing thesis (backfill capability)
- "Deepen Counterparties" button: appears on enriched theses; triggers /api/thesis/deepen background job that reads filing documents and extracts named counterparties via Haiku
- Both buttons poll via /api/jobs, show live status, reload thesis on completion
- Counterparty rows now appear inline in EDGAR panel under each company (edgar-cp-row CSS)
- update_thesis_rings() added to database.py for persisting mutated ring JSON

### FORCE-DIRECTED GRAPH TAB - FULLY DEPLOYED
- D3 v7 loaded from cdnjs on first use
- Thesis picker select at top; auto-populates from State.theses
- Nodes: bottleneck (amber), ring1 (cyan), ring2 (green), ring3 (violet), ring4 (red), external counterparties (gray)
- Edges: bottleneck spine (amber solid), ring adjacency (dim), relationship edges (colored, dashed if approximate)
- Edge labels: visible 9px dim text at midpoints with pointer-events:none
- Edge hover: transparent 16px hit-area stroke on each relationship edge; mouseover shows tooltip with relationship type, confidence, source -> target
- Node hover: tooltip with company name, ticker, ring, counterparty list
- Zoom/pan/drag all working
- Legend in toolbar; node/edge count in status line

### KNOWN ISSUES FIXED THIS SESSION
- _handle_exit_check method was corrupted (def line consumed by patch anchor); restored by patch_server_fix_exit_check.py
- Edge hover proximity detection (coordinate math approach) replaced with DOM-event transparent hit-area approach
- uspto_collector.py: patch_graph_readability.py caused indentation error at line 405; fixed by patch_uspto_fix.py

### PENDING AT SESSION END
- patch_uspto_fix.py: READY TO RUN -- fixes indentation error in uspto_collector.py and adds auth probe
- USPTO key session inheritance: key is set as Windows system env var but must be set inline for active sessions:
    $env:USPTO_ODP_KEY = "your-key-here"
  Then run dashboard and refresh. Auth probe will now log "USPTO auth OK (HTTP 200)" or "USPTO auth FAILED (HTTP 401/403)"
- Reddit collector: 403 blocked on all subreddits (Reddit blocked anonymous API access). Needs OAuth or PRAW. Low priority.

### DATABASE SCHEMA ADDITIONS THIS SESSION
- database.py: update_thesis_rings(thesis_id, ring1, ring2, ring3, ring4) -- persists mutated ring JSON, bumps last_updated

### SERVER ROUTES ADDED THIS SESSION
- POST /api/thesis/enrich -- EDGAR enrichment backfill for existing theses
- POST /api/thesis/deepen -- counterparty extraction pass on enriched theses

### INDEX.HTML ADDITIONS THIS SESSION
- Graph tab: nav button + view-graph div + toolbar + SVG canvas + tooltip div
- Graph CSS: graph-toolbar, graph-pick-wrap, graph-legend-row, graph-status, graph-canvas-wrap, graph-tooltip
- Graph JS: buildGraphData(), renderGraph(), clearGraph(), initGraphTab(), NODE_COLOR_MAP, EDGE_COLORS
- EDGAR empty panel: replaced static message with "Run EDGAR Enrichment" button + triggerEnrich() + pollEnrich()
- EDGAR company rows: counterparty sub-list (edgar-cp, edgar-cp-label, edgar-cp-row CSS)
- Deepen button: triggerDeepen() + pollDeepen() in EDGAR enriched panel
- Edge hover: edgeHitSel (transparent 16px stroke), _showEdgeTooltip(), edgeLabelSel (9px visible text, pointer-events:none)

## PATCH SCRIPTS APPLIED THIS SESSION (in order)
1. patch_database_deepen.py -- added update_thesis_rings() to database.py
2. patch_server_deepen.py -- added /api/thesis/deepen route + job
3. patch_index_deepen.py -- added Graph tab + deepen button + graph JS
4. patch_server_enrich.py -- added /api/thesis/enrich route + job
5. patch_index_enrich.py -- added Run EDGAR Enrichment button + JS
6. patch_graph_readability.py -- PARTIALLY APPLIED: HTML parts OK, USPTO part corrupted uspto_collector.py
7. patch_server_fix_exit_check.py -- restored _handle_exit_check method
8. patch_graph_edge_hover_v2.py -- replaced broken proximity hover with hit-area approach
9. patch_uspto_fix.py -- READY TO RUN (not yet applied on disk)

## ENVIRONMENT VARIABLES
- ANTHR_HORIZON: Anthropic API key (system env var)
- PERPLEX_HORIZON: Perplexity API key (system env var)
- USPTO_ODP_KEY: USPTO ODP key (system env var, but must set inline per session)

## KEY FILES
- horizon_scanner/enrichment/edgar_client.py
- horizon_scanner/dashboard/server.py
- horizon_scanner/dashboard/index.html (= static dir, served as root)
- horizon_scanner/database.py
- horizon_scanner/collectors/uspto_collector.py
- horizon_scanner/thesis/postmortem_loop.py
- config.yaml (root + package copy kept in sync)

## DELIVERY CONVENTIONS (CRITICAL - maintain across sessions)
- All code as runnable patch scripts with PowerShell copy-paste commands
- ASCII-only output (no Unicode arrows, bullets, box-drawing -- Windows encoding)
- AST parse validation before presenting any .py file
- Dry-run validation against actual uploaded files before delivery
- Idempotent patch scripts with sentinel-anchor pattern
- Unique-string anchors (not line numbers); abort cleanly on mismatch
- Inspect real data before building code that assumes structure
- Complete files not diffs when file is small enough
- CRLF awareness: Windows files use \r\n; multi-line anchors must account for this or use dynamic range replacement

## EDGAR QUIRKS (hard-won)
- EFTS full-text search: OR-chain queries cause HTTP 500 via URL encoding; use sequential single-phrase searches and merge
- Hyphens inside quoted phrases act as NOT operators; use spaces ("cross license" not "cross-license")
- index_url fields point to SEC index pages (document tables), not actual text; use resolve_filing_documents() to get real URLs
- Use _window_around_phrase() centered on matched_phrase (+-3000 chars) for counterparty extraction
- Transient 500s from EFTS: retry with backoff

## CURRENT STATUS TO UPDATE EACH SESSION
Update this section at the start of each new session after reviewing what was done:
- Last confirmed working: Graph tab rendering with edge hover, EDGAR enrichment panel with counterparty rows, deepen counterparties job
- Pending: Run patch_uspto_fix.py, then test USPTO collect with $env:USPTO_ODP_KEY set inline
- Next priorities: Validate USPTO auth probe works; consider Reddit OAuth fix; thesis versioning; L4 monitoring fuller implementation
