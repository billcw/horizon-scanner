"""
run.py — Horizon Scanner entry point

Usage (from project root):
  python run.py init
  python run.py collect
  python run.py collect --source arxiv
  python run.py classify
  python run.py escalate
  python run.py stats
  python run.py seed --topic "neuromorphic computing"
  python run.py schedule
"""

import argparse
import logging
import os
import sys

# ── Fix Python path BEFORE any local imports ─────────────────────────────────
# This makes the project work whether run as "python run.py" or "python -m ..."
# and regardless of where Python looks for packages.
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# ─────────────────────────────────────────────────────────────────────────────

# Now local imports will work
from horizon_scanner.config import get_config
from horizon_scanner.database import initialize_database, get_stats

# Set up logging
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(ROOT, "logs", "horizon_scanner.log"),
            encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger("horizon_scanner")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_init(args):
    """Initialize the database."""
    initialize_database()
    print("\n✓ Database initialized.")
    print("✓ Next step: copy .env.template to .env and add your ANTHROPIC_API_KEY")
    print("✓ Then run: python run.py collect\n")


def cmd_collect(args):
    """Run signal collectors."""
    from horizon_scanner.collectors.arxiv_collector  import run as run_arxiv
    from horizon_scanner.collectors.reddit_collector import run as run_reddit
    from horizon_scanner.collectors.trends_collector import run as run_trends

    collectors = {
        "arxiv":  run_arxiv,
        "reddit": run_reddit,
        "trends": run_trends,
    }

    source = getattr(args, "source", None)
    if source and source not in collectors:
        print(f"Unknown source: {source}. Available: {list(collectors.keys())}")
        return

    targets = {source: collectors[source]} if source else collectors

    total = 0
    for name, fn in targets.items():
        print(f"\n→ Running {name} collector...")
        try:
            n = fn()
            total += (n or 0)
            print(f"  {name}: {n or 0} new signals")
        except Exception as e:
            print(f"  {name}: ERROR — {e}")
            logger.exception(f"Collector error: {name}")

    print(f"\n✓ Collection complete. {total} total new signals.\n")


def cmd_classify(args):
    """Run the L2 classifier on pending signals."""
    from horizon_scanner.classifier.signal_classifier import run_classifier
    print("\n→ Running signal classifier...")
    n = run_classifier(batch_size=100)
    print(f"✓ Classified {n} signals.\n")


def cmd_escalate(args):
    """Check for clusters ready to escalate to L3."""
    from horizon_scanner.classifier.signal_classifier import check_escalations
    ready = check_escalations()
    if not ready:
        print("\n→ No clusters ready for escalation yet.\n")
    else:
        print(f"\n→ {len(ready)} cluster(s) ready for L3 thesis loop:\n")
        for c in ready:
            print(f"   • [{c['signal_count']} signals] {c['theme']}  (id: {c['id'][:8]}...)")
        print("\nRun: python run.py thesis --cluster <id>  to generate a thesis.\n")


def cmd_stats(args):
    """Print database statistics."""
    stats = get_stats()
    print("\n══════════════════════════════════")
    print("  HORIZON SCANNER — DATABASE STATS")
    print("══════════════════════════════════")
    s = stats["signals"]
    print(f"  Signals:    {s['total']} total  |  {s['classified']} classified")
    c = stats["clusters"]
    print(f"  Clusters:   {c['total']} total  |  {c['pending']} pending escalation")
    t = stats["theses"]
    print(f"  Theses:     {t['total']} total  |  {t['watch']} WATCH  "
          f"{t['building']} BUILDING  {t['candidate']} CANDIDATE")
    d = stats["decisions"]
    print(f"  Decisions:  {d['total']} logged  |  {d['emotional_flags']} emotional flags")
    print("══════════════════════════════════\n")


def cmd_seed(args):
    """Manually seed a thesis topic without waiting for L2 clustering."""
    import hashlib
    from horizon_scanner.database import (
        insert_signal, update_signal_classification, upsert_cluster
    )

    topic = getattr(args, "topic", None)
    if not topic:
        print("Usage: python run.py seed --topic 'neuromorphic computing'")
        return

    print(f"\n→ Seeding manual thesis topic: '{topic}'")

    def make_signal(suffix=""):
        h = hashlib.sha256(f"manual_seed:{topic}:{suffix}".encode()).hexdigest()
        sid = insert_signal(
            source="manual_seed",
            content_hash=h,
            title=f"Manual seed: {topic}{' ' + suffix if suffix else ''}",
            content=f"Manually seeded topic for thesis generation: {topic}",
            metadata={"manual": True},
        )
        if sid:
            update_signal_classification(sid, "EMERGING", 1.0, topic, "long")
            upsert_cluster(topic, sid)
        return sid

    ids = [make_signal(), make_signal("2"), make_signal("3")]
    created = [i for i in ids if i]
    print(f"  ✓ Created {len(created)} signals for topic '{topic}'.")
    print("  Run: python run.py escalate  to confirm cluster is ready.\n")


def cmd_schedule(args):
    """Run collectors on a continuous schedule (daemon mode)."""
    import schedule
    import time

    print("\n→ Starting scheduler (Ctrl+C to stop)...\n")

    schedule.every().day.at("06:00").do(
        lambda: cmd_collect(argparse.Namespace(source="arxiv")))
    schedule.every().day.at("07:00").do(
        lambda: cmd_collect(argparse.Namespace(source="trends")))
    schedule.every(6).hours.do(
        lambda: cmd_collect(argparse.Namespace(source="reddit")))
    schedule.every(6).hours.do(lambda: cmd_classify(None))
    schedule.every().hour.do(lambda: cmd_escalate(None))

    # Run once immediately on start
    cmd_collect(argparse.Namespace(source=None))
    cmd_classify(None)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Horizon Scanner — AI technology & trend intelligence"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init",     help="Initialize database")
    sub.add_parser("classify", help="Classify pending signals")
    sub.add_parser("escalate", help="Check clusters ready for L3")
    sub.add_parser("stats",    help="Show database statistics")
    sub.add_parser("schedule", help="Run on continuous schedule")

    p_collect = sub.add_parser("collect", help="Run signal collectors")
    p_collect.add_argument(
        "--source", choices=["arxiv", "reddit", "trends"],
        help="Run only this collector"
    )

    p_seed = sub.add_parser("seed", help="Manually seed a thesis topic")
    p_seed.add_argument("--topic", required=True, help="Topic to seed")

    args = parser.parse_args()

    commands = {
        "init":     cmd_init,
        "collect":  cmd_collect,
        "classify": cmd_classify,
        "escalate": cmd_escalate,
        "stats":    cmd_stats,
        "seed":     cmd_seed,
        "schedule": cmd_schedule,
    }

    if args.command not in commands:
        parser.print_help()
        return

    commands[args.command](args)


if __name__ == "__main__":
    main()
