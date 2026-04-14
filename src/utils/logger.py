"""Structured logging configuration."""

from __future__ import annotations

import logging
import os
import sys

import structlog


def setup_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging.

    Secrets are never logged — structlog processors strip any key
    containing 'token', 'secret', 'key', or 'password'.
    """
    level = os.environ.get("LOG_LEVEL", level).upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _secret_scrubber,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
            if os.environ.get("LOG_FORMAT", "console") == "console"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _secret_scrubber(
    logger: object, method_name: str, event_dict: dict
) -> dict:
    """Remove any keys that look like secrets from log output."""
    secret_keys = {"token", "secret", "key", "password", "api_key", "bearer"}
    scrubbed = {}
    for k, v in event_dict.items():
        if any(s in k.lower() for s in secret_keys):
            scrubbed[k] = "***REDACTED***"
        else:
            scrubbed[k] = v
    return scrubbed


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a named logger instance."""
    return structlog.get_logger(name)
