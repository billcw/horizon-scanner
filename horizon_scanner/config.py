"""
horizon_scanner/config.py
Loads config.yaml and .env. Everything else imports from here.
"""

import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

# _ROOT is the package directory (horizon_scanner/), where the second config.yaml
# copy lives. PACKAGE_DIR is exported for the dashboard so it can sync both copies.
_ROOT = Path(__file__).parent
PACKAGE_DIR = str(_ROOT)

load_dotenv(_ROOT / ".env")

# Cached config dict. Loaded lazily, can be cleared with reset_config_cache().
_CONFIG_CACHE = None


def get_project_root() -> str:
    """
    Return the project root (the folder ABOVE the package), where run.py and
    the root copy of config.yaml live.
    """
    return str(_ROOT.parent)


def get_config() -> dict:
    """Load and cache config.yaml. Call get_config() anywhere."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        config_path = _ROOT / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f)
    return _CONFIG_CACHE


def reset_config_cache():
    """
    Clear the cached config so the next get_config() re-reads config.yaml from
    disk. The dashboard calls this after writing edited settings, so changes
    take effect on the next thesis run without restarting the process.
    """
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


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
    return get_secret("PERPLEX_HORIZON")


def get_reddit_creds() -> dict:
    return {
        "client_id":     os.getenv("REDDIT_CLIENT_ID", ""),
        "client_secret": os.getenv("REDDIT_CLIENT_SECRET", ""),
        "user_agent":    os.getenv("REDDIT_USER_AGENT", "HorizonScanner/1.0"),
    }
