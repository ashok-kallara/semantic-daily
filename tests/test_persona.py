"""Tests for persona-driven relevance filtering and query/category generation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from src.models.article import Article, Source
from src.processing.persona import UNCATEGORIZED, PersonaProcessor


def _config(**user_overrides):
    return {
        "llm": {"provider": "openrouter", "openrouter_api_key": "test-key"},
        "user": {
            "persona": "Senior AI researcher",
            "interests": ["RAG architectures", "Agentic workflows"],
            **user_overrides,
        },
        "sources": {},
    }


def _make_article(title="Test", content="Some content", score=0):
    return Article(
        title=title,
        url=f"https://example.com/{title}",
        source=Source.REDDIT,
        raw_content=content,
        score=score,
    )


class TestCategoryInitialization:
    def test_defaults_when_no_categories_pinned(self):
        p = PersonaProcessor(_config())
        assert len(p.active_categories) == 10
        assert p.pinned_categories == []

    def test_uses_pinned_categories(self):
        p = PersonaProcessor(_config(categories=["🔍 RAG", "🤖 Agents"]))
        assert p.active_categories == ["🔍 RAG", "🤖 Agents"]

    def test_pinned_categories_capped_at_ten(self):
        pinned = [f"Cat {i}" for i in range(15)]
        p = PersonaProcessor(_config(categories=pinned))
        assert len(p.active_categories) == 10


class TestEvaluateArticles:
    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_sets_relevance_without_touching_score(self, mock_generate):
        mock_generate.return_value = json.dumps(
            [{"index": 0, "relevance": 9, "wit": 1, "category": "✨ General Updates"}]
        )
        p = PersonaProcessor(_config())
        # Simulate a Reddit article with a large raw upvote count already in `score`.
        article = _make_article(score=1500)

        result = asyncio.run(p.evaluate_articles([article]))

        assert len(result) == 1
        assert result[0].relevance == 9
        assert result[0].score == 1500  # untouched — no more max(score, rel) conflation

    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_drops_articles_below_relevance_threshold(self, mock_generate):
        mock_generate.return_value = json.dumps(
            [{"index": 0, "relevance": 3, "wit": 0, "category": "✨ General Updates"}]
        )
        p = PersonaProcessor(_config())
        result = asyncio.run(p.evaluate_articles([_make_article()]))
        assert result == []

    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_unmatched_category_falls_back_to_uncategorized(self, mock_generate):
        mock_generate.return_value = json.dumps(
            [{"index": 0, "relevance": 8, "wit": 0, "category": "🎲 Not A Real Category"}]
        )
        p = PersonaProcessor(_config(categories=["✨ General Updates"]))
        result = asyncio.run(p.evaluate_articles([_make_article()]))
        assert result[0].category == UNCATEGORIZED

    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_high_wit_overrides_category(self, mock_generate):
        mock_generate.return_value = json.dumps(
            [{"index": 0, "relevance": 8, "wit": 9, "category": "✨ General Updates"}]
        )
        p = PersonaProcessor(_config(categories=["✨ General Updates"]))
        result = asyncio.run(p.evaluate_articles([_make_article()]))
        assert result[0].category == "🔥 Best Takes"


class TestExpandConfig:
    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_pinned_categories_survive_llm_response(self, mock_generate):
        mock_generate.return_value = json.dumps(
            {
                "exa": ["q1"],
                "reddit": ["sub1"],
                "youtube": ["yt1"],
                "categories": ["🤖 LLM Invented Category"],
            }
        )
        config = _config(categories=["🔍 RAG", "🤖 Agents"])
        p = PersonaProcessor(config)
        asyncio.run(p.expand_config(config))
        assert p.active_categories == ["🔍 RAG", "🤖 Agents"]

    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_categories_generated_when_not_pinned(self, mock_generate):
        mock_generate.return_value = json.dumps(
            {"exa": [], "reddit": [], "youtube": [], "categories": ["🚀 Generated"]}
        )
        config = _config()
        p = PersonaProcessor(config)
        asyncio.run(p.expand_config(config))
        assert p.active_categories == ["🚀 Generated"]

    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_reddit_queries_go_to_real_reddit_config_not_apify(self, mock_generate):
        mock_generate.return_value = json.dumps(
            {"exa": [], "reddit": ["LocalLLaMA", "RAG"], "youtube": [], "categories": []}
        )
        config = _config()
        config["sources"]["reddit"] = {"subreddits": ["existing_sub"]}
        p = PersonaProcessor(config)
        asyncio.run(p.expand_config(config))

        assert "apify" not in config["sources"]
        subreddits = config["sources"]["reddit"]["subreddits"]
        assert "existing_sub" in subreddits  # user's curated list preserved
        assert "LocalLLaMA" in subreddits
        assert "RAG" in subreddits

    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_exa_queries_replace_generic_fallback(self, mock_generate):
        mock_generate.return_value = json.dumps(
            {"exa": ["targeted RAG query"], "reddit": [], "youtube": [], "categories": []}
        )
        config = _config()
        config["sources"]["exa"] = {"queries": ["generic fallback query"]}
        p = PersonaProcessor(config)
        asyncio.run(p.expand_config(config))

        assert config["sources"]["exa"]["queries"] == ["targeted RAG query"]

    @patch("src.processing.persona.LLMClient.generate", new_callable=AsyncMock)
    def test_disabled_when_no_persona(self, mock_generate):
        config = _config()
        config["user"]["persona"] = ""
        p = PersonaProcessor(config)
        asyncio.run(p.expand_config(config))
        mock_generate.assert_not_called()
