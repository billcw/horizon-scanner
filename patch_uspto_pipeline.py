"""
patch_uspto_pipeline.py

Wire the USPTO collector into the refresh pipeline and dashboard.

Server (server.py):
  1. Add "uspto" to the source whitelist in _handle_pipeline_refresh
  2. Import run_uspto and add it to the all_sources dict in _run_refresh_job

Dashboard (index.html):
  3. Add a "USPTO" refresh button to the refresh-group
  4. Add a "uspto" group to SOURCE_GROUPS (keyword library management)
  5. Add a USPTO enabled/keywords note to the Settings collectors block

Idempotent: checks for its own markers before inserting.

Run from project root:
    python patch_uspto_pipeline.py
"""

from pathlib import Path
import sys

ROOT = Path(r"C:\Projects\horizon-scanner\horizon_scanner\dashboard")
SERVER = ROOT / "server.py"
HTML = ROOT / "index.html"

if not SERVER.exists() or not HTML.exists():
    print("ERROR: server.py or index.html not found")
    sys.exit(1)

# ===========================================================================
# SERVER PATCHES
# ===========================================================================

srv = SERVER.read_text(encoding="utf-8-sig")
srv_changed = False

# ---- 1. Source whitelist --------------------------------------------------
OLD_WHITELIST = 'if source not in ("all", "arxiv", "reddit", "trends"):'
NEW_WHITELIST = 'if source not in ("all", "arxiv", "reddit", "trends", "uspto"):'

if '"uspto"' not in srv.split("all_sources")[0]:  # rough check on whitelist region
    if OLD_WHITELIST in srv:
        srv = srv.replace(OLD_WHITELIST, NEW_WHITELIST, 1)
        print("  [+] server: added 'uspto' to source whitelist")
        srv_changed = True
    else:
        print("  [!] server: whitelist anchor not found")
else:
    print("  [=] server: whitelist already includes uspto")

# ---- 2. Collector import + dict -------------------------------------------
OLD_IMPORTS = """            from ..collectors.arxiv_collector  import run as run_arxiv
            from ..collectors.reddit_collector import run as run_reddit
            from ..collectors.trends_collector import run as run_trends

            all_sources = {"arxiv": run_arxiv, "reddit": run_reddit, "trends": run_trends}"""

NEW_IMPORTS = """            from ..collectors.arxiv_collector  import run as run_arxiv
            from ..collectors.reddit_collector import run as run_reddit
            from ..collectors.trends_collector import run as run_trends
            from ..collectors.uspto_collector  import run as run_uspto

            all_sources = {"arxiv": run_arxiv, "reddit": run_reddit,
                           "trends": run_trends, "uspto": run_uspto}"""

if "run_uspto" not in srv:
    if OLD_IMPORTS in srv:
        srv = srv.replace(OLD_IMPORTS, NEW_IMPORTS, 1)
        print("  [+] server: added uspto import and dict entry")
        srv_changed = True
    else:
        print("  [!] server: import/dict anchor not found -- check formatting")
else:
    print("  [=] server: uspto collector already wired")

if srv_changed:
    SERVER.write_text(srv, encoding="utf-8")
    print(f"  server.py written.")

# ===========================================================================
# HTML PATCHES
# ===========================================================================

html = HTML.read_text(encoding="utf-8-sig")
html_changed = False

# ---- 3. Refresh button ----------------------------------------------------
OLD_BTN = '''    <button class="ghost src" data-source="trends">Trends</button>
  </div>'''
NEW_BTN = '''    <button class="ghost src" data-source="trends">Trends</button>
    <button class="ghost src" data-source="uspto">USPTO</button>
  </div>'''

if 'data-source="uspto"' not in html:
    if OLD_BTN in html:
        html = html.replace(OLD_BTN, NEW_BTN, 1)
        print("  [+] html: added USPTO refresh button")
        html_changed = True
    else:
        print("  [!] html: refresh button anchor not found")
else:
    print("  [=] html: USPTO refresh button already present")

# ---- 4. SOURCE_GROUPS entry (keyword library) -----------------------------
OLD_GROUPS = '''  { type:"reddit", title:"Subreddits", placeholder:"e.g. energy",
    hint:"Subreddit names without the r/ prefix" },
];'''
NEW_GROUPS = '''  { type:"reddit", title:"Subreddits", placeholder:"e.g. energy",
    hint:"Subreddit names without the r/ prefix" },
  { type:"uspto",  title:"USPTO keywords", placeholder:"e.g. solid state battery",
    hint:"Technology phrases searched against patent invention titles" },
];'''

if 'type:"uspto"' not in html:
    if OLD_GROUPS in html:
        html = html.replace(OLD_GROUPS, NEW_GROUPS, 1)
        print("  [+] html: added uspto group to SOURCE_GROUPS")
        html_changed = True
    else:
        print("  [!] html: SOURCE_GROUPS anchor not found")
else:
    print("  [=] html: uspto SOURCE_GROUPS entry already present")

# ---- 5. Settings collectors block -----------------------------------------
OLD_SETTINGS = '''      <div class="set-row"><label>Trends geo</label><input id="co_trends_geo" value="${esc((co.google_trends||{}).geo||"")}"></div>
    </div>'''
NEW_SETTINGS = '''      <div class="set-row"><label>Trends geo</label><input id="co_trends_geo" value="${esc((co.google_trends||{}).geo||"")}"></div>
      <div class="set-row"><label>USPTO max requests / run</label>${numInput("co_uspto_maxreq", (co.uspto||{}).max_requests_per_run)}</div>
      <div class="set-row"><label>USPTO lookback days</label>${numInput("co_uspto_lookback", (co.uspto||{}).lookback_days)}</div>
    </div>'''

if 'co_uspto_maxreq' not in html:
    if OLD_SETTINGS in html:
        html = html.replace(OLD_SETTINGS, NEW_SETTINGS, 1)
        print("  [+] html: added USPTO fields to Settings collectors block")
        html_changed = True
    else:
        print("  [!] html: settings collectors anchor not found")
else:
    print("  [=] html: USPTO settings fields already present")

if html_changed:
    HTML.write_text(html, encoding="utf-8")
    print(f"  index.html written.")

# ===========================================================================
print()
if srv_changed or html_changed:
    print("Done. Verify server.py parses:")
    print("  python -c \"import ast; ast.parse(open(r'C:\\\\Projects\\\\horizon-scanner\\\\horizon_scanner\\\\dashboard\\\\server.py', encoding='utf-8-sig').read()); print('VALID')\"")
    print("Then restart: python run.py dashboard")
else:
    print("Nothing to patch -- all USPTO wiring already present.")
