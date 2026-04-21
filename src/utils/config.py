"""Unified TOML configuration loader."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

# Python 3.11+ has tomllib in stdlib; older versions need tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        raise ImportError(
            "Python <3.11 requires the 'tomli' package. Install with: uv add tomli"
        )

DEFAULT_CONFIG_PATH = Path("config/config.toml")


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Overlay environment variables onto config for CI/CD."""
    import os
    env_map = [
        # (env_var, config_path)
        ("EXA_API_KEY",          ["sources", "exa", "api_key"]),
        ("BLUESKY_APP_PASSWORD", ["sources", "bluesky", "app_password"]),
        ("YOUTUBE_API_KEY",      ["sources", "youtube", "api_key"]),
        ("OPENROUTER_API_KEY",   ["llm", "openrouter_api_key"]),
        ("TELEGRAM_BOT_TOKEN",   ["telegram", "bot_token"]),
        ("TELEGRAM_CHAT_ID",     ["telegram", "chat_id"]),
    ]
    for env_var, path in env_map:
        val = os.environ.get(env_var)
        if val:
            d = config
            for key in path[:-1]:
                d = d.setdefault(key, {})
            d[path[-1]] = val
    return config

def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from a TOML file.

    Priority: explicit path arg > CONFIG_PATH env var > default location.
    """
    import os

    if path is None:
        path = os.environ.get("CONFIG_PATH", str(DEFAULT_CONFIG_PATH))

    config_path = Path(path)

    if not config_path.exists():
        # Fall back to example config if main config doesn't exist
        example_path = config_path.with_suffix(".example.toml")
        if example_path.exists():
            log.warning(
                "config.using_example",
                message=f"config.toml not found, using {example_path.name}. "
                f"Copy it to {config_path.name} and fill in your credentials.",
            )
            config_path = example_path
        else:
            raise FileNotFoundError(
                f"Config file not found: {config_path} "
                f"(copy config.example.toml to config.toml)"
            )

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    log.info("config.loaded", path=str(config_path))
    return _apply_env_overrides(config)


def get_nested(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get a nested config value.

    Usage: get_nested(config, "llm", "model", default="llama3.2")
    """
    current = config
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current
