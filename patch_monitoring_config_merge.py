"""
patch_monitoring_config_merge.py -- insert spike_threshold / quiet_days /
auto_rerun_on_spike into the EXISTING monitoring: section of config.yaml.
Idempotent. Patches root + package copy. Run from project root.
"""
import io
import os

ANCHOR = "monitoring:\n"
INSERT = (
    "  # L4 signal-spike / quiet detection (added Session 8)\n"
    "  spike_threshold: 3\n"
    "  quiet_days: 30\n"
    "  auto_rerun_on_spike: false\n"
)

CANDIDATES = [
    "config.yaml",
    os.path.join("horizon_scanner", "config.yaml"),
]


def patch_one(path):
    if not os.path.exists(path):
        return "missing"
    with io.open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if "spike_threshold:" in src:
        return "already"
    # Match the monitoring: line followed by a newline (handle CRLF too).
    if "monitoring:\r\n" in src:
        anchor = "monitoring:\r\n"
    elif "monitoring:\n" in src:
        anchor = "monitoring:\n"
    else:
        return "no-monitoring-section"
    if src.count(anchor) != 1:
        return "anchor-not-unique"
    new_src = src.replace(anchor, anchor + INSERT, 1)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_src)
    return "patched"


def main():
    for path in CANDIDATES:
        print("%-32s %s" % (path, patch_one(path)))


if __name__ == "__main__":
    main()
