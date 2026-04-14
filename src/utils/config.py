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
    return config


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
