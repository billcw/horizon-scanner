# HORIZON SCANNER - MASTER PROMPT (v5)

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

### USPTO collector (built, wired, KEY NOW ACTIVE)
- `collectors/uspto_collector.py`, keyword-first (technology phrases vs. patent invention titles); experimental CPC mode included but off by default
- Targets current ODP API `POST https://api.uspto.gov/api/v1/patent/applications/search`, `x-api-key` header (legacy `developer.uspto.gov/ibd-api/v1` was decommissioned 2026-06-05)
- Captures `firstApplicantName` + full `applicantBag` (co-applicants = partnership/JV signal); stores `applicants` list + `co_filed` flag in signal metadata
- Reads key from `USPTO_ODP_KEY` env var; skips gracefully if unset
- Quota-safe: conservative pagination, hard request ceiling per run, 429 backoff. WARNING: exceeding the ODP download quota triggers a 7-DAY lockout from first key use. Keep defaults small; raise slowly.
- Seeded via `seed_uspto_keywords.py` from enabled Google Trends topics only (arXiv codes and subreddit names don't work as patent-title search phrases)
- **Status: ID.me verified, key obtained and set as `USPTO_ODP_KEY`. The first run is now unblocked.** Has not yet been run. When running the first time, keep the request ceiling small and watch for 429s - the 7-day lockout on quota-exhaustion is real.

### SEC EDGAR enrichment client (tested, working)
- `enrichment/edgar_client.py` - free, no API key, but requires a User-Agent header with a real email (SEC 403s placeholder contacts; email set in config)
- It is a MODULE OF FUNCTIONS, not a class. Key functions: `resolve_cik()`, `get_recent_filings()`, `get_ip_section()`, `fulltext_search()`, `find_licensing_mentions()`, plus low-level `_get(url, ...)` (returns a requests.Response) and `_fetch_document_text(doc_url, max_chars)` (fetches + cleans filing text)
- Full-text search lessons baked in: use `file_type`/`root_form` not `form_type`; `sort=desc` for recency; OR-chains break EFTS (HTTP 500) so run sequential single-phrase queries and merge/dedup by accession; hyphens inside quoted phrases trip Elasticsearch (`"cross-license"` -> `"cross license"`); 5xx are transient burst-load, so retry-with-backoff; rate limiter at 0.34s
- The module imports `os` (added this session - `_get_anthropic_client` needs it)

### L3 Step 5.5 EDGAR enrichment (wired, tested live)
- Runs between Step 5 (entity mapping) and Step 6 (platform classification)
- Cheap pass: ticker verification across all rings. Expensive pass: configurable deep enrichment of 10-K IP sections + licensing hits.
- Folds into existing `entities_ring1`-`ring4` JSON columns. Wholly non-fatal.
- Enriched company objects gain: `cik`, `verified_name`, `ticker_verified`, `ticker_corrected`, `licensing_hits` (list of {form, filing_date, index_url, matched_phrase, **matched_doc, matched_doc_url**}), `ip_summary`, `ip_doc_url`, `ip_filing_date`, `edgar_enriched`
- Enrichment is NOT retroactive - it only runs during a thesis run. Currently exactly ONE thesis carries enrichment ("Quantum circuit optimization"); the other five predate Step 5.5.

### EDGAR Settings UI wiring (done earlier)
- `_edgarApplyConfig` (load) and `_edgarCollect` (save) helpers wired into the settings load/save flow
- The visible EDGAR Enrichment settings card (controls `set_edgar_verify`, `set_edgar_depth`) renders and persists

### EDGAR Enrichment panel in thesis detail view (done earlier)
- `renderEdgarPanel(t)` helper + CSS, injected between the Bottleneck Map and Scenario Tree sections in `renderThesis`
- Per-company display grouped by ring: verified name, CIK linked to its SEC EDGAR page, licensing-filing count with dated `index_url` links, IP summary
- Graceful "not enriched yet - re-run thesis to populate" state for the five pre-Step-5.5 theses

### Counterparty extraction (BUILT AND VALIDATED THIS SESSION) - the licensing-edge unlock
This is the work that makes a real supply-line graph possible. A licensing-phrase hit tells you a filing mentions a license; it does NOT name the other party. This layer reads the matched filing text and asks Haiku to name counterparties. Now working end to end against live IBM data.

New functions in `enrichment/edgar_client.py`:
- `extract_counterparties(doc_url, subject_company, client=None, model=None, match_phrase="", is_index=False, radius=3000, max_docs=2)` - reads a filing document (or resolves an index URL to its best documents if `is_index=True`), windows on `match_phrase`, asks Haiku for counterparties. Returns a list of `{name, ticker, relationship_type, confidence, source_url, derived_from}`. `relationship_type` in {acquisition, license, joint_venture, supply, partnership, other}. Non-fatal throughout: returns [] on any failure.
- `deepen_counterparties(entities, max_filings_per_company=3, client=None, model=None, max_docs_per_filing=2)` - the explicitly-triggered pass over a list of enriched company objects. For each company with `licensing_hits`, reads up to N filings, extracts counterparties, dedups by (name, relationship_type) keeping higher confidence, writes a new `counterparties` field onto each company object IN PLACE. Returns `{companies_processed, filings_read, counterparties_found}`. Builds one Anthropic client and reuses it.
- Helpers: `resolve_filing_documents(index_url)` (index page -> ranked real document URLs, exhibits first, graphics dropped, `/ix?doc=` viewer wrappers stripped); `_window_around_phrase(text, phrase, radius)`; `_exhibit_rank`; `_strip_ix_wrapper`; `_extract_json_array` (tolerant array parse: strips code fences, finds first `[...]`); `_get_anthropic_client` (raw `anthropic.Anthropic` keyed off `ANTHR_HORIZON`, lazy import); `_counterparty_model` (configurable via `enrichment.edgar.counterparty_model`, defaults to Haiku `claude-haiku-4-5-20251001`).

Config knob (optional): `enrichment.edgar.counterparty_model` overrides the extraction model. Defaults to Haiku.

Cost discipline: extraction is NOT inline in the thesis run. It is a separate, explicitly-triggered "deepen counterparties" pass. One Anthropic client reused across all calls in a pass.

---

## 4. Current data state

- 565 signals collected/classified; 481 clusters; 6 theses
- Bottleneck Map (radial ring diagram) already exists in the thesis detail view - shows companies by ring proximity to the bottleneck. NOTE: it shows position/exposure, NOT relationships between companies.
- One enriched thesis: "Quantum circuit optimization" (bottleneck IBM/IBM; Ring 1 = IBM, GOOGL, IONQ, RGTI; IBM enriched to CIK 51143, INTERNATIONAL BUSINESS MACHINES CORP, 5 licensing hits)
- `monitoring_events` table exists but is empty
- **Counterparty extraction validated on live IBM filings:** `deepen_counterparties` over IBM's licensing hits returned named counterparties (Kyndryl, The Prudential Insurance Company of America, Metropolitan Life Insurance Company) from IBM's 2023 10-K. Real edge data now demonstrably extractable.

---

## 5. THE NEXT BUILD: supply-line graph (counterparty extraction is DONE)

This is the active thread. The hard prerequisite - turning licensing hits into named edges - is now built and validated. Next session goes straight to wiring the trigger and building the graph tab.

### The goal
A force-directed company-relationship graph (new dashboard tab) where EDGES are the point - actual relationship lines between companies, not just radial proximity. Distinct from the existing Bottleneck Map (which shows exposure tiers, not connections). Single-thesis picker first, merged view later.

### Edge types and their data reality
- **Bottleneck edges** - solid data (`bottleneck_entity`/`bottleneck_ticker`). The spine.
- **Ring adjacency edges** - solid data (ring number = proximity).
- **Licensing/counterparty edges** - NOW AVAILABLE. `deepen_counterparties` writes a `counterparties` field onto each enriched company object: `[{name, ticker, relationship_type, confidence, source_url, derived_from}]`. These are the real inter-company edges.
- **Co-filing edges (USPTO `applicantBag`)** - real relationships (co-applicants on a patent). Now unblocked (key active); needs a USPTO run plus a join from patent co-applicants to thesis companies. See section 5b.

### What counterparty extraction actually yields (honest caveats - carry these into the UI)
Validated behavior, not theory:
1. **Nodes/edges are real; edge LABELS are approximate.** Extraction reliably surfaces the right company NAMES, but Haiku's `relationship_type` is noisy. Live example: it labeled Kyndryl an "acquisition" when Kyndryl was IBM's 2021 SPIN-OFF, not an acquisition. Right node, wrong edge label.
2. **Every edge carries `confidence` and `derived_from: "licensing-phrase match (approximate)"`.** The UI MUST show edges as approximate - label with the confidence value and the derived-from note. Do not imply precision. This is a feature, not a hedge: it keeps the discipline honest.
3. **Run-to-run variance is real.** Two identical extraction calls returned the same three names but reordered with slightly different confidences (0.9/0.85 swapped). LLM nondeterminism. IMPLICATION: run the pass ONCE and STORE it; do not re-run and expect stable output. Cache results into the company object / DB.
4. **The counterparty is often a company OUTSIDE the thesis** (Kyndryl/Prudential/MetLife aren't quantum companies). This is the whole point - it reveals a company's wider relationship web. Show both intra-thesis and external counterparties, visually distinguished (thesis companies highlighted; external counterparties styled differently).

### The matched-doc lesson (do not regress this)
The single most important fix this session: EFTS's `_id` is `accession:filename`. The filename is the EXACT document the phrase matched. Earlier code split on `:` and KEPT ONLY the accession, then re-guessed the document by exhibit rank - which read the wrong page (earnings boilerplate) and found nothing. `fulltext_search` now carries `matched_doc` and `matched_doc_url`, and `deepen_counterparties` reads that exact document (falling back to index resolution only when `matched_doc_url` is absent). Reading the right document was the difference between zero counterparties and real ones.

### Planned implementation (next session starts here)
1. **A per-thesis "deepen counterparties" trigger.** A button in the thesis detail view (or a dashboard action) that runs `deepen_counterparties` over that thesis's ring company objects, then PERSISTS the `counterparties` results back into the `entities_ring*` JSON columns (so it survives and isn't re-run). Background job + polling, same pattern as the refresh button (shared in-memory `_JOBS` dict, browser polls ~1.2-1.5s). Non-fatal; surfaces a summary (`companies_processed`, `filings_read`, `counterparties_found`).
2. **Persistence:** decide where `counterparties` lives. Simplest: fold it into the existing `entities_ring*` company objects (already JSON) and have `export.py` ship it. No schema change needed.
3. **The graph tab itself:** force-directed (D3, in keeping with the existing SVG dashboard; no new heavy deps). Nodes = companies; node styling distinguishes bottleneck / thesis-ring / external-counterparty. Edges = bottleneck spine + ring adjacency + counterparty edges + (later) USPTO co-filing. Edge styling encodes type; counterparty edges show `relationship_type` + `confidence` and visibly carry the "approximate" caveat. Single-thesis picker first.
4. Build against REAL data shape first (inspection script) - the quantum thesis already has IBM enriched, and once its counterparties are deepened it becomes the test fixture.

### Sequencing rationale
Option 3 (make enrichment visible - the EDGAR panel) was done earlier. Option 1 (counterparty extraction) is DONE and validated this session. What remains is wiring (trigger + persistence) and the graph tab. Option 2 (USPTO co-filing edges) is now unblocked by the active key.

---

## 5b. USPTO co-filing edges (now unblocked - parallel workstream)

The USPTO key is active, so this becomes a real near-term source of graph edges. The signal: when two companies are co-applicants on the same patent (`applicantBag` has more than one applicant), that is a genuine partnership/JV relationship - higher-quality than a licensing-phrase match because there is no LLM interpretation in the middle; the co-filing is a hard fact in the patent record.

### Steps to make it yield edges
1. **First run, carefully.** Run the USPTO collector with a SMALL request ceiling. The 7-day quota lockout from first key use is real - do not raise limits until a clean run is confirmed. Seed from enabled Google Trends topics (`seed_uspto_keywords.py`).
2. **Confirm `co_filed` signals land.** The collector already stores an `applicants` list and a `co_filed` flag in signal metadata. Inspect a few stored signals to confirm co-applicant capture works against the live ODP response shape (inspection-first - the response shape may differ from assumptions).
3. **Join co-applicants to thesis companies.** A co-filing edge is only graph-relevant when at least one applicant maps to a company already in a thesis (bottleneck or a ring). Build that match (name normalization will be fuzzy - "INTERNATIONAL BUSINESS MACHINES CORP" vs "IBM" vs "IBM Corp"; reuse/extend whatever normalization the EDGAR `resolve_cik` name-matching already does).
4. **Edge styling:** co-filing edges are HIGHER trust than licensing edges (hard record, no LLM). Style them distinctly and do NOT tag them "approximate" the way counterparty edges are - but DO note they reflect a patent co-application, which is a specific kind of relationship (shared R&D / JV), not a general partnership.

### Honest caveat
Co-applicant data is clean, but "co-filed a patent" is a narrow relationship. Don't over-read it as a broad alliance. Label the edge for what it is: shared patent application.

---

## 6. Other future features (queued, not started)

- **L4 monitoring:** populate `monitoring_events`; sub-idea is watching 8-K filings for companies in active theses
- **Deeper EDGAR-grounded reasoning:** feed real filing text into L3 Steps 6/7
- **Thesis versioning**
- **L5 post-mortem loop closure:** use existing `outcome_30d/90d/365d` and `pattern_tag` columns
- **SVG pan/zoom for the Bottleneck Map / future graph** (browser zoom covers whole-page needs; custom pan/zoom only worth it for a single crowded SVG element - the force-directed graph may be the first place it's warranted)
- **Retroactive enrichment / deepening:** Step 5.5 and counterparty extraction only run on demand. Five theses predate Step 5.5; all six will need a deepen pass before a merged-view graph is meaningful.

---

## 7. How we work (conventions - follow these)

### Build/test loop
1. Claude builds the change as a **patch script** (idempotent, anchors precisely to existing markup with unique-string checks that abort cleanly if the anchor is not found exactly once) or a complete file - never raw diffs
2. Claude validates it before presenting: ASCII-only, no BOM, parses cleanly (`ast.parse`); where practical, dry-runs the patch against a local copy and smoke-tests pure-logic helpers
3. Bill places the file in `C:\Projects\horizon-scanner\` and runs it in PowerShell
4. Bill tests - for dashboard changes, launch and click through; for client changes, run a small probe one-liner
5. On success, Bill commits and pushes
6. Claude confirms before moving to the next phase

### Inspection-first discipline (this paid off repeatedly this session)
Before building against data, look at the real data shape with a small probe. This session that discipline caught, in order: (a) `index_url` points to a document LIST, not the document; (b) the matched phrase wasn't even in the document we were reading because we discarded the matched filename from the EFTS `_id`; (c) IBM's "license agreement" hits in some exhibits are GAAP boilerplate with no counterparty. None of these were guessable from the schema - only from looking at fetched bytes. Do not build against assumed shapes.

### Hard-won gotchas (do not relearn these)
- **Missing-import trap:** a function that uses `os.environ` needs `import os` at module top. `edgar_client.py` originally imported only logging/re/time/threading/datetime/requests; `_get_anthropic_client` failed with "name 'os' is not defined" until `import os` was added. When adding a helper, check its imports exist.
- **EFTS `_id` = `accession:filename`:** the filename after the colon is the exact matched document. Keep it. Splitting and keeping only the accession, then re-guessing the doc, reads the wrong page.
- **Dual `config.yaml` trap:** root copy vs. package copy. `config.py` loads the PACKAGE copy. Hand edits must update both or save through the dashboard, or changes are silently ignored.
- **Patch-script escaping:** over-escaped backslashes in print statements cause a SyntaxError that aborts the script before writing any files. Always verify the patch script itself parses cleanly before delivery.
- **Anchor uniqueness / whitespace:** anchor patches on distinctive multi-line blocks; a trailing `</section>` with differing whitespace once caused a 0-match abort. Prefer content anchors over line numbers; line numbers shift as patches accumulate. For replace-a-span patches, anchor a START string and an END string and verify each appears exactly once and in order.
- **EFTS query constraints:** OR-chains break it (HTTP 500); hyphens inside quoted phrases trip it; sequential single-phrase queries with merge/dedup is correct. Transient 5xx are burst-load - retry-with-backoff rides through them.
- **False-alarm pattern:** duplicate matches in `Select-String` can be JS comment blocks, not real code duplicates - confirm context.
- **Token-limit discipline:** Step 7 (Adversarial) truncated at 2000 tokens (`BEAR VERDICT: None`); fixed by raising to 3000 + concise schema fields.
- **Licensing data limit / relationship_type noise:** a licensing-phrase hit is NOT a clean licensing relationship; EFTS matches are a grab-bag. AND the LLM's `relationship_type` label is approximate (it called IBM's Kyndryl spin-off an "acquisition"). Trust the NODE, treat the EDGE LABEL as a hint. Always carry `confidence` + `derived_from`.
- **LLM run-to-run variance:** extraction reorders / re-scores across identical calls. Run once, store the result; never re-run expecting stability.
- **USPTO 7-day lockout:** exceeding the ODP download quota from first key use triggers a 7-day lockout. Start small.
- **`_get` returns a requests.Response** (use `.text`); `_fetch_document_text` returns cleaned text.

### File / encoding conventions
- All generated files: plain ASCII only. No Unicode arrows, bullets, em-dashes, or box-drawing characters (Windows encoding corruption). Validate before presenting.
- Patch scripts over here-string PowerShell (avoids quote-escaping hell). Idempotent with unique string anchors and a sentinel that makes re-runs a clean no-op.
- Raw strings (`r'...'`) required in PowerShell `python -c` invocations containing backslash paths. Better still: write a small `.py` file rather than fighting inline quoting.
- PowerShell syntax, not cmd. One command per line (PowerShell concatenates pasted multi-command lines).

---

## 8. Tools & environment

- **OS/shell:** Windows, PowerShell
- **Project root:** `C:\Projects\horizon-scanner` (deliberately OUTSIDE OneDrive to avoid file-locking corruption)
- **Python:** venv; editable install via `pip install -e .` with `setup.py` at root
- **Database:** `C:\Projects\horizon-scanner\data\horizon_scanner.db` (SQLite, NOT inside the package dir)
- **Launch dashboard:** `python run.py dashboard` (bare `python run.py` prints usage - it needs a subcommand)
- **Version control:** GitHub `github.com/billcw/horizon-scanner` (private); git email `billcw@users.noreply.github.com`
- **API keys (Windows env vars):** `ANTHR_HORIZON` (Anthropic), `PERPLEX_HORIZON` (Perplexity), `USPTO_ODP_KEY` (USPTO ODP - NOW ACTIVE). EDGAR is free/no key. Reddit uses public JSON API (no creds).
- **Models:** Claude as reasoning engine (Haiku for cheap classification/extraction, Sonnet for thesis steps); Perplexity for web-grounded research steps. Counterparty extraction uses Haiku by default (override: `enrichment.edgar.counterparty_model`).
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

### Cleanup pending from this session
The four counterparty patch scripts (`patch_counterparties.py`, `_2`, `_3`, `_4`) have served their purpose; their changes are baked into `edgar_client.py`. Delete them after the commit is confirmed.

---

## 10. Immediate next step

Counterparty extraction is done and validated. Next:
1. Wire a per-thesis "deepen counterparties" trigger (background job) that runs `deepen_counterparties` over the thesis's ring company objects and PERSISTS `counterparties` back into the `entities_ring*` JSON (so it isn't re-run; remember the run-to-run variance - store once).
2. Run that pass on the quantum thesis to populate real edge data as the graph test fixture.
3. Build the force-directed supply-line graph tab on top of bottleneck + ring + counterparty edges; single-thesis picker first.
In parallel: do the first careful USPTO run (small ceiling), confirm `co_filed` signals land, then add co-filing edges (section 5b) as a higher-trust edge type.
