"""
horizon_scanner/config.py

Loads config.yaml and .env. Everything else imports from here.
"""

import os
from pathlib import Path
from functools import lru_cache

import yaml
from dotenv import load_dotenv

# Load .env from the project root (works from any subdirectory)
_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Load and cache config.yaml. Call get_config() anywhere."""
    config_path = _ROOT / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_secret(key: str) -> str:
    """Fetch an API key from environment. Raises clearly if missing."""
    value = os.getenv(key, "")
    if not value:
        raise EnvironmentError(
            f"Missing environment variable: {key}\n"
            f"Copy .env.template to .env and fill in your keys."
        )
    return value


def get_anthropic_key() -> str:
    return get_secret("ANTHR_HORIZON")


def get_perplexity_key() -> str:
    return get_secret("PERPLEXITY_API_KEY")


def get_reddit_creds() -> dict:
    return {
        "client_id":     os.getenv("REDDIT_CLIENT_ID", ""),
        "client_secret": os.getenv("REDDIT_CLIENT_SECRET", ""),
        "user_agent":    os.getenv("REDDIT_USER_AGENT", "HorizonScanner/1.0"),
    }
