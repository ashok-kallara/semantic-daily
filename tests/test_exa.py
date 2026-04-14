"""Tests for Exa.ai collector."""

import asyncio
import sys
from unittest.mock import MagicMock, patch

from src.collectors.exa import ExaCollector
from src.models.article import Source


class TestExaCollector:
    def _make_collector(self, **overrides):
        config = {
            "enabled": True,
            "api_key": "test-key",
            "queries": ["AI news"],
            "max_results": 10,
            "lookback_hours": 36,
            **overrides,
        }
        return ExaCollector(config)

    def test_disabled_returns_empty(self):
        c = self._make_collector(enabled=False)
        result = asyncio.run(c.collect())
        assert result == []

    def test_no_api_key_returns_empty(self):
        c = self._make_collector(api_key="")
        result = asyncio.run(c.collect())
        assert result == []

    def test_collects_articles(self):
        mock_result = MagicMock()
        mock_result.title = "GPT-5 Released"
        mock_result.url = "https://example.com/gpt5"
        mock_result.published_date = "2026-04-10T12:00:00Z"
        mock_result.score = 0.95
        mock_result.author = "Tech Blog"
        mock_result.text = "OpenAI released GPT-5 today..."
        mock_result.highlights = ["GPT-5 released"]

        mock_search = MagicMock()
        mock_search.results = [mock_result]

        mock_exa = MagicMock()
        mock_exa.search_and_contents.return_value = mock_search

        mock_exa_module = MagicMock()
        mock_exa_module.Exa.return_value = mock_exa

        with patch.dict(sys.modules, {"exa_py": mock_exa_module}):
            c = self._make_collector()
            result = asyncio.run(c.collect())

        assert len(result) == 1
        assert result[0].title == "GPT-5 Released"
        assert result[0].source == Source.EXA
        assert result[0].score == 95  # 0.95 * 100

    def test_handles_search_error(self):
        mock_exa = MagicMock()
        mock_exa.search_and_contents.side_effect = Exception("API error")

        mock_exa_module = MagicMock()
        mock_exa_module.Exa.return_value = mock_exa

        with patch.dict(sys.modules, {"exa_py": mock_exa_module}):
            c = self._make_collector()
            result = asyncio.run(c.collect())
        assert result == []

    def test_multiple_queries(self):
        mock_search = MagicMock()
        mock_search.results = []
        mock_exa = MagicMock()
        mock_exa.search_and_contents.return_value = mock_search

        mock_exa_module = MagicMock()
        mock_exa_module.Exa.return_value = mock_exa

        with patch.dict(sys.modules, {"exa_py": mock_exa_module}):
            c = self._make_collector(queries=["query1", "query2", "query3"])
            asyncio.run(c.collect())

        assert mock_exa.search_and_contents.call_count == 3
