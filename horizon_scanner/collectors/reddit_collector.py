"""
collectors/reddit_collector.py
Pulls top posts from configured subreddits.
Uses public Reddit JSON API - no OAuth needed for read-only access.

Subreddits are read from the collector_sources library table (enabled rows),
falling back to config.yaml when the library has no reddit rows.
"""

import hashlib
import logging
import time
from datetime import datetime, timezone

import requests

from ..config import get_config, get_reddit_creds
from ..database import insert_signal, get_enabled_source_values

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "HorizonScanner/1.0 (research tool)"}


def _resolve_subreddits(red_cfg) -> list:
    """Prefer enabled subreddits from the source library; fall back to config."""
    try:
        library = get_enabled_source_values("reddit")
    except Exception as e:
        logger.warning(f"Could not read source library, using config: {e}")
        library = []
    if library:
        return library
    return red_cfg.get("subreddits", [])


def _fetch_public(subreddit: str, limit: int, min_score: int) -> list:
    """Fetch top posts via public Reddit JSON endpoint."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit={limit}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        posts = resp.json()["data"]["children"]
        return [
            p["data"] for p in posts
            if p["data"].get("score", 0) >= min_score
        ]
    except Exception as e:
        logger.error(f"Reddit public fetch failed for r/{subreddit}: {e}")
        return []


def run():
    cfg     = get_config()
    red_cfg = cfg["collectors"]["reddit"]

    if not red_cfg.get("enabled", True):
        logger.info("Reddit collector disabled.")
        return

    subreddits = _resolve_subreddits(red_cfg)
    limit      = red_cfg.get("post_limit", 25)
    min_score  = red_cfg.get("min_score", 50)

    logger.info(f"Reddit collecting across {len(subreddits)} subreddits: {subreddits}")

    total_new = 0
    for sub in subreddits:
        posts = _fetch_public(sub, limit, min_score)
        logger.info(f"r/{sub}: {len(posts)} posts above score {min_score}.")

        for post in posts:
            title     = post.get("title", "")
            selftext  = post.get("selftext", "")
            url_link  = f"https://reddit.com{post.get('permalink', '')}"
            author    = post.get("author", "")
            score     = post.get("score", 0)
            num_comms = post.get("num_comments", 0)
            created   = datetime.fromtimestamp(
                post.get("created_utc", 0), tz=timezone.utc
            ).isoformat()

            content      = f"{title}\n\n{selftext}".strip()
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            signal_id = insert_signal(
                source       = "reddit",
                content_hash = content_hash,
                title        = title,
                content      = content[:2000],  # cap at 2000 chars
                url          = url_link,
                author       = author,
                published_at = created,
                metadata     = {
                    "subreddit":    sub,
                    "score":        score,
                    "num_comments": num_comms,
                },
            )
            if signal_id:
                total_new += 1
        time.sleep(2)  # be polite to Reddit

    logger.info(f"Reddit collector complete. {total_new} new signals stored.")
    return total_new


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
