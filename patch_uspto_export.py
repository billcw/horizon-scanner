"""
patch_uspto_export.py

Surface the USPTO collector config in the Settings panel.

export.py's config_payload() only exposes arxiv/reddit/google_trends under
the collectors section. This adds uspto so the dashboard Settings fields
(max_requests_per_run, lookback_days, enabled) populate and save.

Run from project root:
    python patch_uspto_export.py
"""

from pathlib import Path
import sys

EXPORT = Path(r"C:\Projects\horizon-scanner\horizon_scanner\dashboard\export.py")

if not EXPORT.exists():
    print("ERROR: export.py not found")
    sys.exit(1)

text = EXPORT.read_text(encoding="utf-8-sig")
changed = False

# Add a uspto block to the collectors slice in config_payload().
OLD_COLLECTORS = '''                "google_trends": {
                    "geo": src.get("google_trends", {}).get("geo"),
                    "enabled": src.get("google_trends", {}).get("enabled"),
                },
            }'''

NEW_COLLECTORS = '''                "google_trends": {
                    "geo": src.get("google_trends", {}).get("geo"),
                    "enabled": src.get("google_trends", {}).get("enabled"),
                },
                "uspto": {
                    "enabled": src.get("uspto", {}).get("enabled"),
                    "mode": src.get("uspto", {}).get("mode"),
                    "max_requests_per_run": src.get("uspto", {}).get("max_requests_per_run"),
                    "lookback_days": src.get("uspto", {}).get("lookback_days"),
                },
            }'''

if '"uspto":' not in text.split("config_payload")[-1]:
    if OLD_COLLECTORS in text:
        text = text.replace(OLD_COLLECTORS, NEW_COLLECTORS, 1)
        print("  [+] export: added uspto to collectors config slice")
        changed = True
    else:
        print("  [!] export: collectors slice anchor not found")
else:
    print("  [=] export: uspto config slice already present")

if changed:
    EXPORT.write_text(text, encoding="utf-8")
    print("  export.py written.")
    print("\nVerify:")
    print("  python -c \"import ast; ast.parse(open(r'C:\\\\Projects\\\\horizon-scanner\\\\horizon_scanner\\\\dashboard\\\\export.py', encoding='utf-8-sig').read()); print('VALID')\"")
else:
    print("\nNothing to patch.")
