"""Tests for HackerNews collector."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.collectors.hackernews import HackerNewsCollector
from src.models.article import Source


class TestHackerNewsCollector:
    def _make_collector(self, **overrides):
        config = {
            "enabled": True,
            "limit": 5,
            "min_score": 10,
            **overrides,
        }
        return HackerNewsCollector(config)

    def test_disabled_returns_empty(self):
        c = self._make_collector(enabled=False)
        result = asyncio.run(c.collect())
        assert result == []
