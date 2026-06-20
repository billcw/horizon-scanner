"""
collectors/arxiv_collector.py

Pulls recent papers from arXiv in configured categories.
Uses the arXiv Atom feed — no API key needed.
"""

import hashlib
import logging
from datetime import datetime, timezone

import feedparser

from ..config import get_config
from ..database import insert_signal

logger = logging.getLogger(__name__)


def run():
    """Fetch recent arXiv papers and store new ones in the signal database."""
    cfg = get_config()
    arxiv_cfg = cfg["collectors"]["arxiv"]

    if not arxiv_cfg.get("enabled", True):
        logger.info("arXiv collector disabled in config.")
        return

    categories  = arxiv_cfg.get("categories", ["cs.AI"])
    max_results = arxiv_cfg.get("max_results_per_run", 100)
    base_url    = cfg["apis"]["arxiv_base"]

    total_new = 0

    for category in categories:
        url = (
            f"{base_url}?search_query=cat:{category}"
            f"&start=0&max_results={max_results}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )

        try:
            feed = feedparser.parse(url)
            logger.info(f"arXiv [{category}]: fetched {len(feed.entries)} entries.")

            for entry in feed.entries:
                title    = entry.get("title", "").strip().replace("\n", " ")
                abstract = entry.get("summary", "").strip().replace("\n", " ")
                url_link = entry.get("link", "")
                authors  = ", ".join(
                    a.get("name", "") for a in entry.get("authors", [])
                )
                published = entry.get("published", "")

                # Content hash on title + abstract (catches near-identical reposts)
                content_hash = hashlib.sha256(
                    f"{title}{abstract}".encode()
                ).hexdigest()

                signal_id = insert_signal(
                    source       = "arxiv",
                    content_hash = content_hash,
                    title        = title,
                    content      = abstract,
                    url          = url_link,
                    author       = authors,
                    published_at = published,
                    metadata     = {"category": category},
                )

                if signal_id:
                    total_new += 1

        except Exception as e:
            logger.error(f"arXiv collector error for {category}: {e}")

    logger.info(f"arXiv collector complete. {total_new} new signals stored.")
    return total_new


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
