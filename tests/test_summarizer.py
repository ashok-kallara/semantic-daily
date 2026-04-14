"""Tests for the LLM summarizer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.article import Article, Source
from src.processing.summarizer import Summarizer


def _make_article(title="Test Article", content="Some content about AI"):
    return Article(
        title=title,
        url="https://example.com/test",
        source=Source.EXA,
        score=100,
        raw_content=content,
    )


class TestSummarizer:
    def _make_summarizer(self, **overrides):
        config = {
            "provider": "ollama",
            "model": "llama3.2",
            "ollama_base_url": "http://localhost:11434",
            "max_summary_length": 280,
            "batch_size": 5,
            "fallback_truncate_length": 200,
            **overrides,
        }
        return Summarizer(config)

    def test_fallback_summary_short(self):
        s = self._make_summarizer()
        article = _make_article(content="Short content")
        result = s._fallback_summary(article)
        assert result == "Short content"

    def test_fallback_summary_truncates(self):
        s = self._make_summarizer(fallback_truncate_length=20)
        article = _make_article(
            content="This is a very long content that should be truncated"
        )
        result = s._fallback_summary(article)
        assert len(result) <= 25  # 20 + room for "..."
        assert result.endswith("...")

    def test_fallback_summary_uses_title(self):
        s = self._make_summarizer()
        article = _make_article(title="Title only", content="")
        result = s._fallback_summary(article)
        assert result == "Title only"

    @patch("src.processing.summarizer.Summarizer._ollama_generate")
    def test_summarize_articles_success(self, mock_gen):
        async def _mock_gen(prompt):
            return "AI made a breakthrough in reasoning."

        mock_gen.side_effect = _mock_gen

        s = self._make_summarizer()
        articles = [_make_article(), _make_article(title="Another")]

        result = asyncio.run(s.summarize_articles(articles))
        assert len(result) == 2
        assert all(a.summary for a in result)

    @patch("src.processing.summarizer.Summarizer._ollama_generate")
    def test_summarize_falls_back_on_error(self, mock_gen):
        async def _fail(prompt):
            raise ConnectionError("Ollama is down")

        mock_gen.side_effect = _fail

        s = self._make_summarizer()
        articles = [_make_article(content="Fallback content here")]

        result = asyncio.run(s.summarize_articles(articles))
        assert len(result) == 1
        assert result[0].summary == "Fallback content here"

    @patch("src.processing.summarizer.Summarizer._ollama_generate")
    def test_summary_length_enforced(self, mock_gen):
        long_summary = "A" * 500

        async def _long(prompt):
            return long_summary

        mock_gen.side_effect = _long

        s = self._make_summarizer(max_summary_length=100)
        articles = [_make_article()]

        result = asyncio.run(s.summarize_articles(articles))
        assert len(result[0].summary) <= 100

    def test_empty_articles(self):
        s = self._make_summarizer()
        result = asyncio.run(s.summarize_articles([]))
        assert result == []
