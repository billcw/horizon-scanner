"""
patch_monitoring_relevance_config.py

Inserts assess_relevance and assess_min_signals into the EXISTING monitoring:
section of config.yaml (merge, not append -- per the Session 8 false-positive
lesson). Inserts them right after the auto_rerun_on_spike line, which is a
unique anchor inside the monitoring block.

Idempotent: aborts if the keys are already present or the anchor is missing.

Run from project root:  python patch_monitoring_relevance_config.py
"""
import io
import os

TARGET = "config.yaml"
ANCHOR = "  auto_rerun_on_spike: false\n"
INSERT = (
    "  assess_relevance: true\n"
    "  assess_min_signals: 2\n"
)
MARKER = "assess_relevance:"


def main():
    if not os.path.isfile(TARGET):
        raise SystemExit("ERROR: %s not found. Run from project root." % TARGET)

    with io.open(TARGET, "r", encoding="utf-8", newline="") as f:
        src = f.read()

    if MARKER in src:
        print("assess_relevance already present; nothing to do.")
        return

    count = src.count(ANCHOR)
    if count == 0:
        raise SystemExit(
            "ERROR: anchor 'auto_rerun_on_spike: false' not found; aborting. "
            "Check the monitoring: block in config.yaml.")
    if count > 1:
        raise SystemExit("ERROR: anchor found %d times; ambiguous. Aborting." % count)

    new_src = src.replace(ANCHOR, ANCHOR + INSERT, 1)

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)

    print("OK: assess_relevance + assess_min_signals inserted into monitoring section.")


if __name__ == "__main__":
    main()
