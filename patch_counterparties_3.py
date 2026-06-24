"""
patch_counterparties_3.py

Tiny idempotent fix: edgar_client.py's _get_anthropic_client() uses os.environ
but the module never imported os. Add the import.

Run from project root:

    python patch_counterparties_3.py
"""

import ast
import io
import os
import sys

TARGET = os.path.join("horizon_scanner", "enrichment", "edgar_client.py")

ANCHOR = "import logging\nimport re\nimport time\nimport threading\n"
INSERT = "import logging\nimport os\nimport re\nimport time\nimport threading\n"


def main():
    if not os.path.exists(TARGET):
        print("ERROR: %s not found. Run from project root." % TARGET)
        sys.exit(1)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    # Idempotency: already has a top-level 'import os'?
    if "\nimport os\n" in src:
        print("Already has 'import os'. No changes made.")
        return

    if src.count(ANCHOR) != 1:
        print("ERROR: import anchor not found exactly once "
              "(found %d). Aborting." % src.count(ANCHOR))
        sys.exit(2)

    patched = src.replace(ANCHOR, INSERT, 1)

    try:
        ast.parse(patched)
    except SyntaxError as e:
        print("ERROR: patched source does not parse: %s. Aborting." % e)
        sys.exit(3)

    try:
        patched.encode("ascii")
    except UnicodeEncodeError as e:
        print("ERROR: not pure ASCII: %s. Aborting." % e)
        sys.exit(4)

    with io.open(TARGET, "w", encoding="utf-8", newline="\n") as f:
        f.write(patched)

    print("Patched %s: added 'import os'." % TARGET)


if __name__ == "__main__":
    main()
