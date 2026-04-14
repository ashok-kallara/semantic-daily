"""Abstract base collector with retry logic and rate-limit awareness."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from src.models.article import Article
from src.utils.logger import get_logger

log = get_logger(__name__)


class BaseCollector(ABC):
    """Base class for all news source collectors.

    Subclasses must implement `_collect()` which returns raw articles.
    The base class provides retry logic and timing instrumentation.
    """

    source_name: str = "unknown"
    max_retries: int = 3
    base_delay: float = 1.0  # seconds, doubles on each retry

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.enabled = config.get("enabled", True)

    async def collect(self) -> list[Article]:
        """Collect articles with automatic retry and error handling."""
        if not self.enabled:
            log.info("collector.skipped", source=self.source_name, reason="disabled")
            return []

        for attempt in range(1, self.max_retries + 1):
            try:
                start = time.monotonic()
                articles = await self._collect()
                elapsed = time.monotonic() - start
                log.info(
                    "collector.success",
                    source=self.source_name,
                    articles=len(articles),
                    elapsed_s=round(elapsed, 2),
                    attempt=attempt,
                )
                return articles

            except Exception as exc:
                delay = self.base_delay * (2 ** (attempt - 1))
                log.warning(
                    "collector.retry",
                    source=self.source_name,
                    attempt=attempt,
                    max_retries=self.max_retries,
                    error=str(exc),
                    next_delay_s=delay,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)

        log.error(
            "collector.failed",
            source=self.source_name,
            message="All retries exhausted",
        )
        return []

    @abstractmethod
    async def _collect(self) -> list[Article]:
        """Implement source-specific collection logic.

        Must return a list of Article objects. Errors will be caught
        by the base class retry logic.
        """
        ...
