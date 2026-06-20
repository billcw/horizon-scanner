"""
collectors/trends_collector.py

Pulls rising Google Trends data for configured seed topics.
Uses pytrends (unofficial but stable Google Trends API wrapper).
No API key needed.
"""

import hashlib
import logging
import time
from datetime import datetime, timezone

from pytrends.request import TrendReq

from ..config import get_config
from ..database import insert_signal

logger = logging.getLogger(__name__)


def run():
    cfg      = get_config()
    tr_cfg   = cfg["collectors"]["google_trends"]

    if not tr_cfg.get("enabled", True):
        logger.info("Google Trends collector disabled.")
        return

    geo          = tr_cfg.get("geo", "US")
    seed_topics  = tr_cfg.get("seed_topics", [])

    pytrends  = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
    total_new = 0
    now       = datetime.now(timezone.utc).isoformat()

    for topic in seed_topics:
        try:
            # Get related rising queries for this seed topic
            pytrends.build_payload([topic], cat=0, timeframe="today 3-m", geo=geo)
            related = pytrends.related_queries()

            rising_df = related.get(topic, {}).get("rising")
            if rising_df is None or rising_df.empty:
                logger.info(f"No rising queries for: {topic}")
                time.sleep(3)
                continue

            logger.info(f"Trends [{topic}]: {len(rising_df)} rising queries.")

            for _, row in rising_df.iterrows():
                query       = str(row.get("query", ""))
                value       = int(row.get("value", 0))  # % increase
                content     = f"Rising search query: '{query}' related to '{topic}' — {value}% increase"
                content_hash = hashlib.sha256(f"trends:{query}:{topic}".encode()).hexdigest()

                signal_id = insert_signal(
                    source       = "google_trends",
                    content_hash = content_hash,
                    title        = f"Rising: {query}",
                    content      = content,
                    url          = f"https://trends.google.com/trends/explore?q={query.replace(' ', '+')}",
                    published_at = now,
                    metadata     = {
                        "seed_topic":      topic,
                        "rising_query":    query,
                        "percent_increase": value,
                        "geo":             geo,
                    },
                )
                if signal_id:
                    total_new += 1

            time.sleep(5)  # Google Trends rate limits aggressively

        except Exception as e:
            logger.error(f"Trends error for '{topic}': {e}")
            time.sleep(10)

    logger.info(f"Google Trends collector complete. {total_new} new signals stored.")
    return total_new


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
