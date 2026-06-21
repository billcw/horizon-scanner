"""
seed_uspto_keywords.py

One-time seed: copy your currently-ENABLED Google Trends topics into the
USPTO keyword library (collector_sources, source_type='uspto').

Why Trends only: of the three existing sources, only Trends topics are real
technology phrases that work as patent-invention-title searches. arXiv codes
(cs.AI, quant-ph) and subreddit names (Futurology, investing) do not match
patent titles, so they are intentionally excluded.

This is a ONE-TIME seed. After running it, the USPTO list is independent --
add, remove, or toggle USPTO keywords from the dashboard without affecting
Trends, and tune them toward patent-attorney phrasing over time.

Idempotent: add_source() is keyed on (source_type, value), so running this
twice will not create duplicates. New Trends topics you enable later will NOT
auto-appear in USPTO (that's the point of a one-time seed) -- re-run this
script if you ever want to pull in newly added Trends topics.

Run from project root:
    python seed_uspto_keywords.py
"""

import sys
from horizon_scanner.database import get_enabled_source_values, add_source, list_sources


def main():
    # Read currently-enabled Trends topics
    try:
        trends = get_enabled_source_values("trends")
    except Exception as e:
        print(f"ERROR reading Trends sources: {e}")
        sys.exit(1)

    if not trends:
        print("No enabled Trends topics found. Nothing to seed.")
        print("Add some Trends topics first, then re-run.")
        return

    # Show what's already in the USPTO library so the user sees the before/after
    existing_uspto = [s["value"] for s in list_sources("uspto")]
    print(f"Found {len(trends)} enabled Trends topics to seed into USPTO.")
    if existing_uspto:
        print(f"USPTO library already has {len(existing_uspto)} keyword(s); "
              f"duplicates will be skipped.")
    print()

    seeded = 0
    skipped = 0
    for topic in trends:
        # add_source is idempotent on (source_type, value)
        if topic in existing_uspto:
            print(f"  [=] already present: {topic}")
            skipped += 1
            continue
        try:
            add_source(
                source_type="uspto",
                value=topic,
                label="seeded from Trends",
                enabled=True,
            )
            print(f"  [+] seeded: {topic}")
            seeded += 1
        except Exception as e:
            print(f"  [!] failed to seed '{topic}': {e}")

    print()
    print(f"Done. {seeded} new keyword(s) added, {skipped} already present.")
    print("The USPTO keyword list is now independent of Trends.")
    print("Manage it from the dashboard: Settings -> Collection sources -> USPTO keywords.")


if __name__ == "__main__":
    main()
