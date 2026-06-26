"""
patch_monitoring_config.py -- add monitoring: section to config.yaml.
Idempotent. Patches BOTH root config.yaml and the package copy
(horizon_scanner/config.yaml) if present, to keep them in sync.
Run from project root: python patch_monitoring_config.py
"""
import io
import os

BLOCK = """
# L4-MONITORING-CONFIG
monitoring:
  # Minimum number of NEW signals (since the last check) on a thesis's cluster
  # to fire a SIGNAL_SPIKE monitoring event.
  spike_threshold: 3
  # If no new signal has been collected for a thesis's cluster in this many days,
  # fire a SIGNAL_QUIET monitoring event.
  quiet_days: 30
  # When true, a SIGNAL_SPIKE also auto-triggers a thesis re-run
  # (trigger="signal_spike"). Off by default to avoid burning thesis-loop runs.
  auto_rerun_on_spike: false
"""

CANDIDATES = [
    "config.yaml",
    os.path.join("horizon_scanner", "config.yaml"),
]


def patch_one(path):
    if not os.path.exists(path):
        return "missing"
    with io.open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if "L4-MONITORING-CONFIG" in src or "\nmonitoring:" in src or src.startswith("monitoring:"):
        return "already"
    new_src = src.rstrip() + "\n" + BLOCK
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)
    return "patched"


def main():
    any_found = False
    for path in CANDIDATES:
        status = patch_one(path)
        if status != "missing":
            any_found = True
        print("%-32s %s" % (path, status))
    if not any_found:
        print("ABORT: no config.yaml found. Run from project root.")


if __name__ == "__main__":
    main()
