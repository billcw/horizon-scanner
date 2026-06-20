# Horizon Scanner

**AI-powered technology and trend intelligence system.**  
Finds early signals in patents, research papers, social trends, and market data.  
Generates structured investment theses with scenario trees, entity mapping, and adversarial review.

---

## Quick Start (Windows)

### 1. Prerequisites

- Python 3.11+ — download from [python.org](https://www.python.org/downloads/)
- Git — download from [git-scm.com](https://git-scm.com/)

### 2. Clone and set up

```cmd
git clone https://github.com/YOUR_USERNAME/horizon-scanner.git
cd horizon-scanner
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure API keys

```cmd
copy .env.template .env
notepad .env
```

Fill in your keys in `.env`:
- **ANTHROPIC_API_KEY** — required. Get at [console.anthropic.com](https://console.anthropic.com)
- **PERPLEXITY_API_KEY** — needed for L3 thesis loops. Get at [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api)
- Reddit, USPTO — optional for now, public access works at lower rate limits

### 4. Initialize and run

```cmd
python run.py init
python run.py collect
python run.py classify
python run.py stats
```

### 5. Seed a manual thesis topic (fastest way to test the system)

```cmd
python run.py seed --topic "neuromorphic computing"
python run.py escalate
```

---

## Project Structure

```
horizon_scanner/
├── config.yaml              ← All settings (safe to commit)
├── .env.template            ← Copy to .env, fill in keys (never commit .env)
├── .env                     ← Your secrets (gitignored)
├── requirements.txt
├── run.py                   ← Main entry point
│
├── collectors/              ← L1: Signal ingestion
│   ├── arxiv_collector.py
│   ├── reddit_collector.py
│   └── trends_collector.py
│
├── classifier/              ← L2: Signal classification & clustering
│   └── signal_classifier.py
│
├── thesis/                  ← L3: Thesis generation loops (Phase 2)
│
├── monitoring/              ← L4: Thesis tracking & alerts (Phase 3)
│
├── dashboard/               ← HTML dashboard (Phase 3)
│
├── skills/                  ← Sector-specific research templates (Phase 4)
│
├── data/                    ← Local data (gitignored)
│   ├── horizon_scanner.db   ← SQLite database
│   ├── chromadb/            ← Vector store for embeddings
│   └── exports/             ← Thesis export files
│
└── logs/                    ← Log files (gitignored)
```

---

## Commands

| Command | What it does |
|---------|-------------|
| `python run.py init` | Create database tables (run once) |
| `python run.py collect` | Run all collectors (arXiv, Reddit, Google Trends) |
| `python run.py collect --source arxiv` | Run one collector |
| `python run.py classify` | Classify all pending signals (requires ANTHROPIC_API_KEY) |
| `python run.py escalate` | Check which signal clusters are ready for thesis generation |
| `python run.py stats` | Show counts for signals, clusters, theses, decisions |
| `python run.py seed --topic "..."` | Manually seed a thesis topic for testing |
| `python run.py schedule` | Run continuously on schedule (daemon mode) |

---

## Phase Status

- [x] **Phase 0** — Foundation: database, collectors, config, portable structure
- [ ] **Phase 1** — Classification: ChromaDB embeddings, full semantic dedup, clustering
- [ ] **Phase 2** — Thesis Loop: 8-step LangGraph loop, scenario trees, entity mapping
- [ ] **Phase 3** — Monitoring: live thesis tracking, alerts, HTML dashboard, exit loop
- [ ] **Phase 4** — Expansion: SBIR, USPTO, VC funding, sector skill documents

---

## Cost Estimate

Using Claude as the reasoning engine (current June 2026 pricing):

| Activity | Cost |
|----------|------|
| L2 classification (per signal) | ~$0.001 |
| Full L3 thesis loop (8 steps) | ~$0.60–$0.90 |
| Monthly (moderate use, ~20 theses) | ~$30–$35 |

Set `classifier.model` to `claude-haiku-4-5-20251001` in config.yaml to minimize classification costs.

---

## Moving to a New Computer

1. Push to GitHub: `git push`
2. On the new machine: `git clone`, `pip install -r requirements.txt`
3. Copy your `.env` file over (or re-enter keys)
4. If you want your data: copy `data/horizon_scanner.db` and `data/chromadb/` folder
5. Run `python run.py init` (safe to re-run — won't overwrite existing data)

---

## Architecture Reference

See `docs/Horizon_Scanner_v2_Unified.docx` for the full architecture specification.
