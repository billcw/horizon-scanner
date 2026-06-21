# HORIZON SCANNER — MASTER PROMPT (v3)

_Last updated: 2026-06-21. Paste this at the start of a new session so Claude picks up exactly where we left off._

---

## 0. What this document is

This is the running status + working-agreement doc for **Horizon Scanner**, Bill's personal AI-powered investment signal synthesis system. Read it fully before doing anything. It captures the project's purpose, current state, conventions, and the queue of what's next. When a session ends, update this doc before starting a new one.

---

## 1. Purpose & context

Horizon Scanner is a personal, self-directed research infrastructure project (not a team or commercial effort). The core thesis: publicly available research has historically contained enough signal to identify major long-term investment opportunities, but no synthesis layer existed to connect those signals into actionable theses. Horizon Scanner automates that synthesis — ingesting signals from research papers, patents, social trends, and market data, then running structured multi-step reasoning loops to produce scored investment theses with scenario trees, entity mapping, and adversarial review.

A key personal goal is enforcing analytical discipline to avoid emotionally-driven decisions (the "MU mistake"). The behavioral flagging layer and the L5 exit/post-mortem discipline are direct expressions of this.

Bill has a SCADA/OT/EMS background. He often checks "is this a good idea?" before architectural/UI choices and generally defers to Claude's judgment on design, confirming with short answers and moving forward.

---

## 2. Architecture overview (the layered pipeline)

- **L0 — Collection:** Collectors pull raw items into the `signals` table. Sources: arXiv, Reddit, Google Trends, and (new) USPTO. Triggered by the dashboard refresh buttons (Refresh All or per-source).
- **L2 — Classification & clustering:** The classifier (Haiku) scores each signal (NOISE/FAD/CULTURAL/EMERGING/STRUCTURAL), assigns a theme + time horizon, and clusters by theme into `signal_clusters`. When a cluster crosses the escalation threshold it's "ready" for L3.
- **L3 — Thesis loop:** An 8-step (now 8.5-step) structured reasoning loop that turns a ready cluster into a scored thesis. Triggered on-demand per cluster. **This is where company/ticker linking happens** — not at collection time.
- **L4 — Monitoring:** STILL UNBUILT. Intended to watch live theses, re-check on schedule, alert on kill-criteria trips, write to the `monitoring_events` table (which exists but is empty).
- **L5 — Decision/exit discipline:** Decision log with emotional flagging, outcome recording, AI post-mortems, exit-discipline checks. Resolved decisions are now fully immutable.

Refresh buttons run L0+L2 only. They get USPTO patents into the system as themed, clustered signals carrying applicant company names **as text** — but ticker resolution and entity/licensing intelligence happen downstream in L3.

---

## 3. Current state (what's done)

### Confirmed complete & pushed to GitHub
- **Phase 0–3:** DB schema, config, collectors, L2 classifier, L3 8-step thesis loop, full dashboard (Theses / Decision Log / Outcomes / Settings tabs, source-library management, pipeline refresh).
- **L5 post-mortem/exit discipline layer**, including:
  - `run_postmortem` and `run_exit_check`
  - Emotional flagging (fires on: BUY overriding WATCH/INSUFFICIENT thesis; BUY within 48h reflection window; FOMO language in reasoning; surfaces via preview endpoint before commit)
  - Outcomes tab: outcome recorder, decision-history table, mistake-patterns panel
  - **Resolved-decision immutability** (NEW this session): once a decision is resolved it cannot be edited, re-run, or deleted. Enforced at the DB layer via `DecisionLockedError`, HTTP 409 from the server, and a locked UI state with an amber banner. The one allowed post-resolution write is the single post-mortem summary write (blocked once a summary exists).

### NEW this session (2026-06-21)

**USPTO collector (built, wired, NOT yet runnable — waiting on API key)**
- New collector at `horizon_scanner/collectors/uspto_collector.py`. Keyword-first (searches technology phrases against patent invention titles). Experimental CPC mode included but off by default.
- Reads key from environment variable **`USPTO_ODP_KEY`** (same pattern as `ANTHR_HORIZON`/`PERPLEX_HORIZON`). Skips gracefully with a clear log message if the key is unset.
- Endpoint: `POST https://api.uspto.gov/api/v1/patent/applications/search`, `x-api-key` header. The legacy `developer.uspto.gov/ibd-api/v1` endpoint was decommissioned 2026-06-05.
- Captures `firstApplicantName` + the full `applicantBag` (co-applicants = real partnership/JV signal). Stores `applicants` list + `co_filed` flag in signal metadata.
- Quota-safe: conservative pagination, hard ceiling on requests/run, 429 backoff that aborts cleanly. **IMPORTANT: exceeding the ODP download quota triggers a 7-DAY lockout from first key use.** Defaults are deliberately small; raise slowly.
- Wired into the refresh pipeline: USPTO button in the dashboard, "uspto" in the source whitelist + collector dict, USPTO keywords in the source library, USPTO fields in Settings, `uspto` exposed in `export.py` config slice.
- `seed_uspto_keywords.py` — one-time script that copies the enabled Google Trends topics into the USPTO keyword library (Trends-only because only those are real technology phrases; arXiv codes and subreddit names don't match patent titles). After seeding, the USPTO list is independent. (May or may not have been run yet — check the dashboard USPTO keywords panel.)
- `verify_cpc_field()` helper in the collector — run once the key is live to discover the real CPC field name and confirm auth. Settles keyword-vs-CPC mode with evidence.

**ID.me / USPTO key status:** Bill created a USPTO.gov account. The API key (from `https://data.uspto.gov/myodp`, now also called "Manage API Key") requires ID.me identity verification, which was PENDING at session end. ID.me wanted a driver's license; Bill planned to complete verification later. **Until the key clears and `USPTO_ODP_KEY` is set, the USPTO collector skips gracefully — everything else works.**

**SEC EDGAR enrichment client (built + TESTED, fully working)**
- New package `horizon_scanner/enrichment/` with `__init__.py` and `edgar_client.py`.
- Free, no API key — but **requires a User-Agent header with a real email** (SEC 403s placeholder/fake emails). Bill's contact is set in config: `enrichment.edgar.user_agent: "HorizonScanner research (billcwenz68@gmail.com)"`.
- Four working functions (all verified against live SEC data using Apple):
  1. `resolve_cik(ticker_or_name)` — ticker/name → CIK (loads & caches `company_tickers.json`, ~10,400 tickers)
  2. `get_recent_filings(cik, forms, limit)` — lists 10-K/8-K/etc. with document URLs
  3. `get_ip_section(cik)` — pulls the Intellectual Property section text from the latest 10-K
  4. `find_licensing_mentions(company)` — multi-phrase full-text search for licensing language
- Self-throttling rate limiter (~3 req/s, well under SEC's 10/s). Transient-5xx retry with backoff (EFTS occasionally 500s under burst load; the client now retries rather than giving up — confirmed clean across repeated runs).
- Full-text search reads form type from candidate keys (`file_type`/`form_type`/`root_form`), sorts `desc` for recency, filters to substantive forms (10-K/10-Q/8-K).
- **Multi-phrase licensing search** (accuracy-over-speed, Bill's explicit preference): runs 6 reliable single-phrase queries — "license agreement", "licensing agreement", "patent license", "technology license", "cross license", "licensing arrangement" — then merges + dedupes by accession, sorts newest-first. Each hit carries `matched_phrase` (useful later for labeling supply-line graph edge types). Single phrases per call are reliable; an OR-chain breaks EFTS, and a hyphen inside quotes ("cross-license") trips its parser — both avoided.
- Self-test: `python -m horizon_scanner.enrichment.edgar_client` exercises all four functions against Apple.

**L3 Step 5.5 — EDGAR Verification & Enrichment (built + TESTED, fully working)**
- New module `horizon_scanner/thesis/edgar_enrichment.py`, wired into the thesis loop between Step 5 (entity mapping) and Step 6 (platform classification).
- **Ticker verification (cheap, all rings if enabled):** confirms each LLM-claimed company is real and publicly traded, corrects near-miss tickers, flags private/unfindable. Adds `cik`, `ticker_verified`, `verified_name`, `ticker_corrected` to each company object.
- **Deep enrichment (expensive, configurable ring depth):** for companies in the enriched rings, pulls the latest 10-K IP-section excerpt and recent licensing mentions. Adds `ip_summary`, `ip_filing_date`, `ip_doc_url`, `licensing_hits`, `edgar_enriched`.
- Results fold back into the `entities_ring*` JSON columns (Bill chose fold-in-place over a new column — keeps the future supply-line graph's data in one place, no schema change).
- **Wholly non-fatal:** every EDGAR call is wrapped; SEC down or company-not-found flags the company and the loop continues. A failure here never breaks a thesis run. (Confirmed: a test run hit transient 500s, logged them, and completed normally.)
- **Two UI controls** (both in config, both adjustable from Settings):
  - `edgar_verify_tickers: true` — cheap ticker verify on/off (default on)
  - `edgar_enrichment_depth: 1` — deep enrichment ring depth: 0=off, 1=ring1, 2=rings1-2, 3=rings1-3, 4=all (default ring 1)
  - Plus `edgar_ip_excerpt_chars: 1500` and `edgar_max_companies: 30` (hard ceiling per run)
- **Verified working live:** a thesis run on the "Quantum circuit optimization" cluster verified 13 tickers, deep-enriched 4 Ring-1 companies, correctly resolved "IBM" → CIK 51143 / INTERNATIONAL BUSINESS MACHINES CORP, and pulled real licensing filings.

---

## 4. Loose ends / immediate next steps

1. **EDGAR Settings UI — JS wiring (small, do first).** The `patch_edgar_settings.py` added the two controls (verify toggle, depth dropdown) and two helper functions — `_edgarApplyConfig(cfg)` and `_edgarCollect(payload)` — to `index.html`, BUT those helpers still need to be CALLED from the dashboard's existing settings load/save code. To finish: run
   `Select-String -Path "C:\Projects\horizon-scanner\horizon_scanner\dashboard\index.html" -Pattern "saveSettings|loadConfig|renderSettings|co_arxiv_max|/api/config" -Context 1,1 | Select-Object -First 25`
   and Claude will wire the two calls in exactly. **The feature works on config defaults without this** — it only affects adjusting settings from the UI. (Note: when editing config.yaml by hand you must update BOTH copies — see §6.)

2. **USPTO key (blocked on ID.me).** When the key clears: set `USPTO_ODP_KEY` (Windows env var), open a fresh PowerShell, then run
   `python -c "from horizon_scanner.collectors.uspto_collector import verify_cpc_field; verify_cpc_field()"`
   to confirm auth + discover the real CPC field name (settles keyword-vs-CPC). Then a first conservative run:
   `python -c "from horizon_scanner.collectors.uspto_collector import run; print(run())"`
   Watch for HTTP 429 (rate) and remember the 7-day quota lockout. Seed keywords from the dashboard if not already done.

---

## 5. Future features (discussed, not yet built)

- **Supply-line / company-relationship graph (the payoff visualization).** A force-directed graph (D3 or lightweight vis lib) as a new dashboard tab: nodes = companies, edges = relationships (supplies-to, licenses-from, co-files-with, competes-with), bottleneck at the center. It renders relationships the L3 loop already computes (entity rings + bottleneck) PLUS the new EDGAR data (verified tickers, licensing hits with `matched_phrase` edge labels, USPTO co-applicant partnerships). **Sequencing matters:** this is genuinely useful only AFTER the relationship data feeding it is rich — which is exactly what the EDGAR + USPTO work now provides. Good candidate for an upcoming session. Bill recalled doing something like this in a prior project (Claude has no record of it — may have been a different tool).

- **L4 monitoring (major unbuilt phase).** Watch live theses, re-check on schedule, alert on kill-criteria trips, write to the empty `monitoring_events` table. A sub-idea worth folding in: monitor **8-K filings** (material events) for companies in active theses — an 8-K announcing a licensing deal or patent acquisition is a real, timely signal. That's L4 territory (watching known entities over time), riding on L3's entity identification + the EDGAR client that already exists.

- **EDGAR-grounded licensing in L3 reasoning (deeper integration).** Right now Step 5.5 attaches licensing hits to company objects. A future enhancement: feed those filings' actual text into the Step 6/7 reasoning so the platform classification and bear case are grounded in real 10-K IP-section language and material-contract disclosures, not just the LLM's priors. Note: SEC EDGAR has a free full-text endpoint already wired; deeper parsing of Exhibit-10 material contracts (often where license terms live, though frequently redacted) is the natural extension. **Reminder on licensing limits:** licenses are private contracts and are generally NOT recorded at the USPTO; assignment ≠ license. Licensing intelligence comes from SEC filings / earnings calls / press releases (the EDGAR + web-search layers), not the patent API. Disclosure is asymmetric: companies trumpet licenses they earn royalties from, downplay ones they pay for; private companies disclose little; filed contracts are often redacted.

- **Thesis versioning** (queued from earlier): let a thesis be re-run while keeping history rather than overwriting.

---

## 6. Conventions & working agreement (IMPORTANT — follow these)

**Delivery discipline**
- Complete files only (no diffs) when delivering source, OR small idempotent patch scripts that anchor precisely to existing markup. Patch scripts have been the main delivery mechanism this session and work well.
- **Plain ASCII only in generated Python** — no Unicode arrows, bullets, or box-drawing (Windows encoding corruption risk). No BOM.
- PowerShell syntax throughout (Windows target).
- **Patch-script gotcha learned this session:** over-escaped backslashes in a patch script's own trailing `print()` statements caused a SyntaxError that aborted the script before it wrote anything. Keep patch-script help text simple; verify the patch script itself parses (`ast.parse`) before shipping. When a patch "succeeds" but a Select-String shows the change didn't land, the script crashed before writing — check for this.

**Dev sequencing:** Build → validate (ast.parse / yaml.safe_load) → present files → Bill places them → test → commit. Confirm before proceeding to the next phase.

**File creation:** All files delivered via Claude's file-creation tools with ASCII validation before presenting.

**Config philosophy:** All tunable parameters externalized to `config.yaml` with a `reset_config_cache()` reload mechanism so UI edits take effect without restart.

**CRITICAL — dual config copies:** There are TWO `config.yaml` files that must stay in sync:
- `C:\Projects\horizon-scanner\config.yaml` (root)
- `C:\Projects\horizon-scanner\horizon_scanner\config.yaml` (package — this is the one `config.py` actually loads)
The dashboard's `_write_config` keeps both in sync automatically when you save from Settings. But a HAND edit to only the root copy leaves the package copy stale and the change won't take effect. **This bit us this session.** When editing config.yaml by hand, update BOTH copies (or save through the dashboard). Patch scripts this session were written to update both.

**Background jobs:** Long-running ops (thesis runs, pipeline refresh, post-mortems) use a shared in-memory job registry with browser polling so the UI never blocks.

**Decision style:** Bill often asks "is this a good idea?" and defers to Claude's design judgment; short confirmations, then move forward. Claude should surface honest tradeoffs and recommend, not just present options.

**Project layout note:** `C:\Projects\horizon-scanner\` (project root, has `.git`, `run.py`, `config.yaml`) contains `horizon_scanner\` (the Python package, has `config.py`, `config.yaml`, and all subpackages). A project folder containing a same-named package folder is normal Python layout — not a duplication problem. Quick Access pins in Explorer can make it look like two copies; it isn't.

---

## 7. Tools & resources

- **Language/runtime:** Python, Windows/PowerShell, venv at `C:\Projects\horizon-scanner`. Editable install via `pip install -e .` with `setup.py` at root.
- **Storage:** SQLite at `data/horizon_scanner.db`. (ChromaDB configured for future semantic search; not central yet.)
- **APIs & env vars:**
  - Anthropic — `ANTHR_HORIZON`
  - Perplexity — `PERPLEX_HORIZON`
  - USPTO ODP — `USPTO_ODP_KEY` (PENDING ID.me)
  - SEC EDGAR — no key; User-Agent email in config (`billcwenz68@gmail.com`)
  - All stored as Windows environment variables, not `.env` files.
- **Dashboard:** Single-page app served via Python stdlib HTTP server. Tabs: Theses, Decision Log, Outcomes, Settings. Tab buttons use `data-view="..."`. Thesis viewer state lives in `State.selectedThesis` (NOT `window._currentThesisId`).
- **Signal sources:** arXiv (categories), Reddit (public JSON, no creds), Google Trends, USPTO (keyword). All managed via the `collector_sources` DB table with enable/disable toggles from the Settings UI.
- **Version control:** Git + GitHub (`github.com/billcw/horizon-scanner`, private, username `billcw`, git email `billcw@users.noreply.github.com`).

---

## 8. Key data-model facts

- **`decisions` table** (L5): now includes `price_at_decision`, `price_at_outcome`, `outcome_date`, `outcome_30d/90d/365d`, `outcome_resolved`, `postmortem_summary`, `pattern_tag`. Resolved rows are immutable. Index `idx_decisions_resolved` created via post-migration SQL (after the column exists — index ordering matters; SQLite can't index a column that doesn't exist yet, which is why the post-migration block exists).
- **`theses` table** (L3): entity rings `entities_ring1..4` are JSON arrays of company objects. Step 5.5 ENRICHES these objects in place (adds `cik`, `ticker_verified`, `ip_summary`, `licensing_hits`, etc.). This is the data source for the future supply-line graph.
- **`monitoring_events` table:** exists, empty, awaiting L4.
- **`signal_clusters`:** clusters escalate to L3 at `cluster_escalation_threshold` (default 3).
- **DB migrations:** run on `initialize_database()`. ALTER TABLE ADD COLUMN is wrapped to ignore "duplicate column" so it's safe to re-run. Run `python run.py init` (or call `initialize_database()`) after pulling schema changes — running the dashboard alone does NOT apply migrations.

---

## 9. Per-step config reference (L3 thesis loop)

8 steps + Step 5.5. Per-step `max_tokens` and per-step model overrides live in `config.yaml` under `thesis:`. Notable: Step 7 (adversarial) uses `max_tokens: 3000` to avoid JSON truncation in the bear case (this was a real bug — truncation caused `BEAR VERDICT: None`; raising max_tokens + enforcing concise schema fields fixed it). Token limits matter per-step and should be tuned individually.

EDGAR keys under `thesis:`: `edgar_verify_tickers`, `edgar_enrichment_depth`, `edgar_ip_excerpt_chars`, `edgar_max_companies`.

---

## 10. How to start the next session

1. Paste this doc.
2. Confirm git is clean and pushed (`git -C "C:\Projects\horizon-scanner" status`).
3. Pick up with the EDGAR Settings JS wiring (quick), or jump to whichever of §4/§5 Bill is in the mood for. If the USPTO key has cleared, do the `verify_cpc_field()` step and first run.
4. The supply-line graph is the most exciting next build and now has real data behind it — strong candidate when Bill wants something with a visible payoff.
