# HORIZON SCANNER - MASTER PROMPT (v4)

_Last updated: 2026-06-22. Paste this at the start of a new session so Claude picks up exactly where we left off._

---

## 0. What this document is

This is the running status and working-agreement document for **Horizon Scanner**, Bill's personal AI-powered investment signal synthesis system. Read it fully before doing anything. It captures the project's purpose, current state, conventions, and the queue of what comes next. When a session ends, update this document before starting a new one.

---

## 1. Purpose & context

Horizon Scanner is a personal, self-directed research infrastructure project - not a team or commercial effort. Bill has a SCADA/OT/EMS background and approaches this as a technical build.

The motivating insight: publicly available research has historically contained the information needed to identify major long-term investment opportunities years in advance, but no synthesis layer existed to connect those scattered signals into actionable theses. Horizon Scanner is that synthesis layer. It continuously ingests signals (research papers, patents, social trends, market data), then runs structured multi-step reasoning loops to produce scored investment theses with scenario trees, entity mapping, and adversarial review.

A secondary goal: apply structured analytical discipline to avoid emotionally-driven investment decisions (internally the "MU mistake").

Working relationship: Bill frequently asks for Claude's design recommendations, confirms with short answers, and defers to Claude's judgment on architecture and UI. He values blunt, accurate feedback over speed. If something is a bad idea, say so plainly.

---

## 2. Architecture (L0-L5)

- **L0 / L1 - Collect:** Signal collectors pull from sources into the database. Collectors: arXiv, Reddit (public JSON API, no creds), Google Trends, USPTO patents. Refresh buttons run collection + classification ONLY (L0+L2); company/ticker linking and enrichment happen downstream in L3.
- **L2 - Classify:** Signal classifier with Haiku/Sonnet routing; dedup and cluster management. Clusters escalate to L3 at a signal-count threshold (3).
- **L3 - Thesis:** The 8-step thesis generation loop (context, viability, bottleneck, scenarios, entities, platform classification, adversarial challenge, scoring), plus Step 5.5 EDGAR enrichment between steps 5 and 6.
- **L4 - Monitor:** Intended to watch live theses, re-check on schedule, alert on kill-criteria trips, write to the `monitoring_events` table (exists but empty). Largely unbuilt.
- **L5 - Decide:** Decision log with emotional flagging, outcome recording, AI post-mortems, exit-discipline checks. Resolved decisions are fully immutable.

---

## 3. Current state (what's done)

### Phases 0-3 complete and pushed
- **Phase 0:** DB schema, config system, three collectors, portable structure
- **Phase 1:** L2 classifier with Haiku/Sonnet routing and cluster management
- **Phase 2:** Full 8-step L3 thesis loop
- **Phase 3:** Complete dashboard - Python stdlib HTTP server (ThreadingHTTPServer, no Flask), single-page UI with Theses / Decision Log / Outcomes / Settings tabs, pipeline refresh, collector source library

### L5 decision discipline complete
- `run_postmortem` and `run_exit_check`
- Emotional flagging fires on: BUY overriding WATCH/INSUFFICIENT thesis; BUY within 48h of generation; FOMO language in stated reasoning. Surfaces via a preview endpoint before commit.
- Outcomes tab: outcome recorder, decision-history table, mistake-patterns panel
- Resolved-decision immutability: DB-layer lock (`DecisionLockedError`), HTTP 409 responses, amber locked-state UI banner; exactly one post-resolution write permitted (the post-mortem summary)

### USPTO collector (built, wired, blocked on key)
- `collectors/uspto_collector.py`, keyword-first (technology phrases vs. patent invention titles); experimental CPC mode included but off by default
- Targets current ODP API `POST https://api.uspto.gov/api/v1/patent/applications/search`, `x-api-key` header (legacy `developer.uspto.gov/ibd-api/v1` was decommissioned 2026-06-05)
- Captures `firstApplicantName` + full `applicantBag` (co-applicants = partnership/JV signal); stores `applicants` list + `co_filed` flag in signal metadata
- Reads key from `USPTO_ODP_KEY` env var; skips gracefully if unset
- Quota-safe: conservative pagination, hard request ceiling per run, 429 backoff. WARNING: exceeding the ODP download quota triggers a 7-DAY lockout from first key use. Keep defaults small; raise slowly.
- Seeded via `seed_uspto_keywords.py` from enabled Google Trends topics only (arXiv codes and subreddit names don't work as patent-title search phrases)
- Status: Bill completed ID.me verification and linked it to his USPTO account. Key activation / first run is the pending step.

### SEC EDGAR enrichment client (tested, working)
- `enrichment/edgar_client.py` - free, no API key, but requires a User-Agent header with a real email (SEC 403s placeholder contacts; email set in config)
- It is a MODULE OF FUNCTIONS, not a class. Key functions: `resolve_cik()`, `get_recent_filings()`, `get_ip_section()`, `fulltext_search()`, `find_licensing_mentions()`, plus low-level `_get(url, ...)` (returns a requests.Response) and `_fetch_document_text(doc_url, max_chars)` (fetches + cleans filing text)
- Full-text search lessons baked in: use `file_type`/`root_form` not `form_type`; `sort=desc` for recency; OR-chains break EFTS (HTTP 500) so run sequential single-phrase queries and merge/dedup by accession; hyphens inside quoted phrases trip Elasticsearch (`"cross-license"` -> `"cross license"`); 5xx are transient burst-load, so retry-with-backoff; rate limiter at 0.34s

### L3 Step 5.5 EDGAR enrichment (wired, tested live)
- Runs between Step 5 (entity mapping) and Step 6 (platform classification)
- Cheap pass: ticker verification across all rings. Expensive pass: configurable deep enrichment of 10-K IP sections + licensing hits.
- Folds into existing `entities_ring1`-`ring4` JSON columns. Wholly non-fatal.
- Enriched company objects gain: `cik`, `verified_name`, `ticker_verified`, `ticker_corrected`, `licensing_hits` (list of {form, filing_date, index_url}), `ip_summary`, `ip_doc_url`, `ip_filing_date`, `edgar_enriched`
- Enrichment is NOT retroactive - it only runs during a thesis run. Currently exactly ONE thesis carries enrichment ("Quantum circuit optimization"); the other five predate Step 5.5.

### EDGAR Settings UI wiring (complete this session)
- `_edgarApplyConfig` (load) and `_edgarCollect` (save) helpers wired into the settings load/save flow
- The visible EDGAR Enrichment settings card (controls `set_edgar_verify`, `set_edgar_depth`) was missing from `renderSettings` and was added this session; it now renders and persists

### EDGAR Enrichment panel in thesis detail view (complete this session)
- New `renderEdgarPanel(t)` helper + CSS, injected between the Bottleneck Map and Scenario Tree sections in `renderThesis`
- Per-company display grouped by ring: verified name, CIK linked to its SEC EDGAR page, licensing-filing count with dated `index_url` links, IP summary
- Graceful "not enriched yet - re-run thesis to populate" state for the five pre-Step-5.5 theses
- Pure front-end patch; `export.py` already ships `entities_ring*` with enrichment fields, so no backend change needed
- This made previously-invisible EDGAR work visible in the UI ("option 3" of the supply-line sequencing)

---

## 4. Current data state

- 565 signals collected/classified; 481 clusters; 6 theses
- Bottleneck Map (radial ring diagram) already exists in the thesis detail view - shows companies by ring proximity to the bottleneck. NOTE: it shows position/exposure, NOT relationships between companies.
- One enriched thesis: "Quantum circuit optimization" (bottleneck IBM/IBM; Ring 1 = IBM, GOOGL, IONQ, RGTI; IBM enriched to CIK 51143, INTERNATIONAL BUSINESS MACHINES CORP, 5 licensing hits)
- `monitoring_events` table exists but is empty

---

## 5. THE NEXT BUILD: supply-line graph + counterparty extraction

This is the active thread. Background and decisions made, so the next session can go straight to building.

### The goal
A force-directed company-relationship graph (new dashboard tab) where EDGES are the point - actual relationship lines between companies, not just radial proximity. This is distinct from the existing Bottleneck Map (which shows exposure tiers, not connections). Single-thesis picker first, merged view later.

### Edge types and their data reality (investigated this session)
- **Bottleneck edges** - solid data (`bottleneck_entity`/`bottleneck_ticker`). The spine.
- **Ring adjacency edges** - solid data (ring number = proximity).
- **Licensing edges** - NOT directly available. `licensing_hits` are just filing references (form, filing_date, index_url) with NO counterparty name. They badge a node, they don't connect two. To make them edges we must parse the filing text for counterparty company names. THIS IS THE WORK.
- **Co-filing edges (USPTO `applicantBag`)** - real relationships (co-applicants on a patent), but not in thesis data yet; blocked on USPTO key/first run.

### Investigation findings (this session) on licensing counterparty extraction
We fetched a real IBM licensing hit end to end. Findings:
1. The hit was an 8-K about Lenovo acquiring IBM's PC division - matched a licensing phrase in EFTS but is really an acquisition. EFTS phrase-matching yields a grab-bag: acquisitions, alliances, actual licenses, boilerplate mentions.
2. The counterparty IS often cleanly named in the opening text ("IBM and Lenovo Group Limited announced a definitive agreement..."), sometimes with tickers ("Lenovo (HKSE: 992; ADR: LNVGY)"). Front-loaded in the first ~1,500 chars.
3. The counterparty is often a company OUTSIDE the thesis (Lenovo isn't in the quantum thesis).

### Design decisions made (Bill chose these)
- **Graph scope:** show BOTH intra-thesis and external counterparties, visually distinguished (thesis companies highlighted; external counterparties shown but styled differently). This turns the external-counterparty fact into a feature: you see a company's whole relationship web.
- **Extraction method:** LLM pass (Haiku). Regex is too fragile given the variety; Haiku nailed the Lenovo example trivially.

### Planned implementation (next session starts here)
- New function in `edgar_client.py`: `extract_counterparties(doc_url, subject_company)`
  - Reuse `_fetch_document_text` (proven to work)
  - Send opening ~6,000 chars to Haiku with a tight prompt: "This is an SEC filing by {subject_company}. Identify other companies that are parties to an agreement with them. Return JSON list of {name, ticker_if_stated, relationship_type, confidence}. relationship_type in {acquisition, license, joint_venture, supply, partnership, other}. If none, return []."
  - Parse JSON; non-fatal on failure (same discipline as the rest of Step 5.5)
- Run it NOT inline in every thesis run (too expensive: N companies x M filings x Haiku). Make it a separate, explicitly-triggered "deepen counterparties" pass over an existing thesis's `licensing_hits`, writing results into a new `counterparties` field on each company object.
- Honest caveat to carry into the UI: relationship_type is approximate (EFTS hits are a grab-bag; Haiku will sometimes mislabel an acquisition as a license). Label edges with the `confidence` value and a "derived from licensing-phrase match" note rather than implying precision.
- Then build the graph tab on top of the `counterparties` + bottleneck + ring data.

### Sequencing rationale
Option 3 (make enrichment visible - the EDGAR panel) is DONE. Option 1 (counterparty extraction, above) is the real prerequisite for a supply-line graph worth the name. Option 2 (USPTO co-filing edges) just needs the key cleared.

---

## 6. Other future features (queued, not started)

- **L4 monitoring:** populate `monitoring_events`; sub-idea is watching 8-K filings for companies in active theses
- **Deeper EDGAR-grounded reasoning:** feed real filing text into L3 Steps 6/7
- **Thesis versioning**
- **L5 post-mortem loop closure:** use existing `outcome_30d/90d/365d` and `pattern_tag` columns
- **SVG pan/zoom for the Bottleneck Map / future graph** (browser zoom covers whole-page needs; custom pan/zoom only worth it for a single crowded SVG element)

---

## 7. How we work (conventions - follow these)

### Build/test loop
1. Claude builds the change as a **patch script** (idempotent, anchors precisely to existing markup with unique-string checks that abort cleanly if the anchor is not found exactly once) or a complete file - never raw diffs
2. Claude validates it before presenting: ASCII-only, no BOM, parses cleanly (`ast.parse`)
3. Bill places the file in `C:\Projects\horizon-scanner\` and runs it in PowerShell
4. Bill tests - for dashboard changes, launch and click through
5. On success, Bill commits and pushes
6. Claude confirms before moving to the next phase

### Hard-won gotchas (do not relearn these)
- **Dual `config.yaml` trap:** root copy vs. package copy. `config.py` loads the PACKAGE copy. Hand edits must update both or save through the dashboard, or changes are silently ignored.
- **Patch-script escaping:** over-escaped backslashes in print statements cause a SyntaxError that aborts the script before writing any files. Always verify the patch script itself parses cleanly before delivery.
- **Anchor uniqueness / whitespace:** anchor patches on distinctive multi-line blocks; a trailing `</section>` with differing whitespace once caused a 0-match abort. Prefer a 2-line section opener over a 3-line block that includes a preceding closing tag. Line numbers shift between the uploaded file and the live file as patches accumulate - rely on content anchors, not line numbers.
- **EFTS query constraints:** OR-chains break it; hyphens inside quoted phrases trip it; sequential single-phrase queries with merge/dedup is correct.
- **False-alarm pattern:** duplicate matches in `Select-String` can be JS comment blocks, not real code duplicates - confirm context (e.g. "EDGAR Enrichment" once matched the card heading AND a `// === EDGAR enrichment ===` comment).
- **Token-limit discipline:** Step 7 (Adversarial) truncated at 2000 tokens (`BEAR VERDICT: None`); fixed by raising to 3000 + concise schema fields.
- **Licensing data limit:** a licensing-phrase hit is NOT a clean licensing relationship; EFTS matches are a grab-bag. License != assignment; the hit may be an acquisition or boilerplate.
- **`_get` returns a requests.Response** (use `.text`); `_fetch_document_text` returns cleaned text.

### File / encoding conventions
- All generated files: plain ASCII only. No Unicode arrows, bullets, em-dashes, or box-drawing characters (Windows encoding corruption). Validate before presenting.
- Patch scripts over here-string PowerShell (avoids quote-escaping hell). Idempotent with unique string anchors.
- Raw strings (`r'...'`) required in PowerShell `python -c` invocations containing backslash paths. Better still: write a small `.py` file rather than fighting inline quoting.
- PowerShell syntax, not cmd. One command per line (PowerShell concatenates pasted multi-command lines).

### Inspection-first discipline
Before building against data, look at the real data shape (a small inspection script). This session that discipline caught: wrong column names (`bottleneck_company` -> `bottleneck_entity`), the four-field vs enriched company-object difference, and the licensing-hit-has-no-counterparty reality. Do not build against assumed schemas.

---

## 8. Tools & environment

- **OS/shell:** Windows, PowerShell
- **Project root:** `C:\Projects\horizon-scanner` (deliberately OUTSIDE OneDrive to avoid file-locking corruption)
- **Python:** venv; editable install via `pip install -e .` with `setup.py` at root
- **Database:** `C:\Projects\horizon-scanner\data\horizon_scanner.db` (SQLite, NOT inside the package dir)
- **Launch dashboard:** `python run.py dashboard` (bare `python run.py` prints usage - it needs a subcommand)
- **Version control:** GitHub `github.com/billcw/horizon-scanner` (private); git email `billcw@users.noreply.github.com`
- **API keys (Windows env vars):** `ANTHR_HORIZON` (Anthropic), `PERPLEX_HORIZON` (Perplexity), `USPTO_ODP_KEY` (USPTO ODP). EDGAR is free/no key. Reddit uses public JSON API (no creds).
- **Models:** Claude as reasoning engine (Haiku for cheap classification/extraction, Sonnet for thesis steps); Perplexity for web-grounded research steps
- **Frontend:** single-page dashboard; `<datalist>` model dropdowns accept suggestions + free text

### run.py subcommands
`init`, `classify`, `escalate`, `stats`, `schedule`, `collect`, `thesis`, `dashboard`, `seed`

---

## 9. Session-end checklist

Before ending a session:
1. Commit and push all working changes
2. Update this master prompt's sections 3-5 to reflect what changed
3. Note any new loose ends or blocked items
4. Optionally remove one-time patch/probe scripts (`patch_*.py`, `inspect_*.py`, `probe_*.py`) - keep `seed_uspto_keywords.py` until USPTO keyword library is confirmed seeded

---

## 10. Immediate next step

Build `extract_counterparties(doc_url, subject_company)` in `edgar_client.py` (Haiku pass, design in section 5), validate it against the IBM/Lenovo filing we already inspected, then wire a "deepen counterparties" pass that writes a `counterparties` field onto enriched company objects. Once that yields real edge data, build the supply-line graph tab. USPTO first-run is a parallel unblock whenever the key is active.
