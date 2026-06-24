"""
patch_server_fix_exit_check.py

Fixes the corrupted _handle_exit_check method in server.py.

The earlier patch_server_deepen.py consumed the HANDLER_ANCHOR string
"    def _handle_exit_check(self):" which was the def line of that method,
leaving its body as orphaned module-level code. This caused the
"ValueError: read of closed file" error.

This patch restores _handle_exit_check as a proper method.

Run from C:\\Projects\\horizon-scanner:
    python patch_server_fix_exit_check.py
"""

import os
import sys

TARGET = os.path.join("horizon_scanner", "dashboard", "server.py")
SENTINEL = "# EXIT-CHECK-RESTORED"

# The orphaned body currently sits at wrong indentation after the deepen job.
# Anchor: the comment that precedes it plus the orphaned docstring opening.
BROKEN_ANCHOR = (
    '    # -- L5-D: exit discipline check ----------------------------------------\n'
    '\n'
    '\n'
    '        """\n'
    '        Run an exit discipline check for a live thesis.\n'
    '        Body: {"thesis_id": "...", "proposed_reason": "..."}\n'
    '        Returns immediately with the AI verdict (synchronous -- typically < 5s).\n'
    '        """\n'
    '        body = self._read_json_body()\n'
    '        thesis_id = body.get("thesis_id")\n'
    '        if not thesis_id:\n'
    '            self._send_json({"error": "thesis_id required"}, 400)\n'
    '            return\n'
    '\n'
    '        proposed_reason = body.get("proposed_reason", "")\n'
    '\n'
    '        try:\n'
    '            from ..thesis.postmortem_loop import run_exit_check\n'
    '            result = run_exit_check(thesis_id, proposed_reason)\n'
    '            self._send_json({"ok": True, "result": result})\n'
    '        except ValueError as e:\n'
    '            self._send_json({"error": str(e)}, 404)\n'
    '        except Exception as e:\n'
    '            logger.error("Exit check failed for thesis %s: %s", thesis_id, e)\n'
    '            logger.debug(traceback.format_exc())\n'
    '            self._send_json({"error": str(e)}, 500)\n'
)

FIXED_REPLACEMENT = (
    '    # -- L5-D: exit discipline check ----------------------------------------\n'
    '\n'
    '    def _handle_exit_check(self):  # EXIT-CHECK-RESTORED\n'
    '        """\n'
    '        Run an exit discipline check for a live thesis.\n'
    '        Body: {"thesis_id": "...", "proposed_reason": "..."}\n'
    '        Returns immediately with the AI verdict (synchronous -- typically < 5s).\n'
    '        """\n'
    '        body = self._read_json_body()\n'
    '        thesis_id = body.get("thesis_id")\n'
    '        if not thesis_id:\n'
    '            self._send_json({"error": "thesis_id required"}, 400)\n'
    '            return\n'
    '\n'
    '        proposed_reason = body.get("proposed_reason", "")\n'
    '\n'
    '        try:\n'
    '            from ..thesis.postmortem_loop import run_exit_check\n'
    '            result = run_exit_check(thesis_id, proposed_reason)\n'
    '            self._send_json({"ok": True, "result": result})\n'
    '        except ValueError as e:\n'
    '            self._send_json({"error": str(e)}, 404)\n'
    '        except Exception as e:\n'
    '            logger.error("Exit check failed for thesis %s: %s", thesis_id, e)\n'
    '            logger.debug(traceback.format_exc())\n'
    '            self._send_json({"error": str(e)}, 500)\n'
)


def main():
    if not os.path.exists(TARGET):
        print("ERROR: {} not found. Run from project root.".format(TARGET))
        sys.exit(1)

    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    if SENTINEL in src:
        print("Patch already applied. Nothing to do.")
        sys.exit(0)

    count = src.count(BROKEN_ANCHOR)
    if count == 0:
        print("ERROR: broken anchor not found -- server.py may already be fixed "
              "or have a different structure. Inspect manually.")
        sys.exit(1)
    if count > 1:
        print("ERROR: anchor found {} times (expected 1).".format(count))
        sys.exit(1)

    src = src.replace(BROKEN_ANCHOR, FIXED_REPLACEMENT, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)

    print("Patched {} successfully.".format(TARGET))
    print("Restored _handle_exit_check as a proper method.")


if __name__ == "__main__":
    main()
