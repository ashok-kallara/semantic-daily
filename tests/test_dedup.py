"""Tests for the deduplication engine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.models.article import Article, Source
from src.processing.dedup import (
    Deduplicator,
    _clean_title,
    normalize_url,
    title_similarity,
)
from src.utils.cache import ArticleCache


# ============================================================================
# URL Normalization
# ============================================================================


class TestNormalizeUrl:
    def test_strips_utm_params(self):
        url = "https://example.com/article?utm_source=twitter&utm_medium=social&id=123"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "id=123" in result

    def test_strips_www(self):
        url = "https://www.example.com/page"
        assert normalize_url(url) == "https://example.com/page"

    def test_strips_trailing_slash(self):
        url = "https://example.com/page/"
        result = normalize_url(url)
        assert not result.endswith("/page/")

    def test_lowercases_domain(self):
        url = "https://Example.COM/Page"
        result = normalize_url(url)
        assert "example.com" in result

    def test_preserves_meaningful_params(self):
        url = "https://example.com/article?id=123&page=2"
        result = normalize_url(url)
        assert "id=123" in result
        assert "page=2" in result

    def test_handles_malformed_url(self):
        url = "not a url"
        result = normalize_url(url)
        # urlparse prepends scheme; just verify it doesn't crash
        assert isinstance(result, str)

    def test_removes_fbclid(self):
        url = "https://example.com/article?fbclid=abc123"
        result = normalize_url(url)
        assert "fbclid" not in result


# ============================================================================
# Title Similarity
# ============================================================================


class TestTitleSimilarity:
    def test_identical_titles(self):
        assert title_similarity("OpenAI releases GPT-5", "OpenAI releases GPT-5") == 1.0

    def test_similar_titles(self):
        a = "OpenAI releases GPT-5 with improved reasoning"
        b = "OpenAI releases GPT-5 featuring better reasoning capabilities"
        sim = title_similarity(a, b)
        assert sim > 0.8

    def test_different_titles(self):
        a = "Apple launches new MacBook"
        b = "Google announces quantum computing breakthrough"
        sim = title_similarity(a, b)
        assert sim < 0.82  # Below the dedup threshold

    def test_empty_titles(self):
        assert title_similarity("", "something") == 0.0
        assert title_similarity("something", "") == 0.0
        assert title_similarity("", "") == 0.0

    def test_strips_editorial_prefix(self):
        a = "Breaking: Major AI breakthrough announced"
        b = "Major AI breakthrough announced"
        sim = title_similarity(a, b)
        assert sim > 0.95


class TestCleanTitle:
    def test_removes_prefix(self):
        assert "major news" in _clean_title("Breaking: Major news")

    def test_removes_punctuation(self):
        result = _clean_title("Hello, World! (2026)")
        assert "," not in result
        assert "!" not in result

    def test_collapses_whitespace(self):
        result = _clean_title("too   many    spaces")
        assert "  " not in result


# ============================================================================
# Deduplicator
# ============================================================================


def _make_article(title="Test", url="https://example.com", score=100, source=Source.EXA):
    return Article(title=title, url=url, source=source, score=score)


class TestDeduplicator:
    @pytest.fixture
    def cache(self, tmp_path):
        return ArticleCache(tmp_path / "test.db")

    @pytest.fixture
    def dedup(self, cache):
        return Deduplicator({"title_similarity_threshold": 0.82}, cache)

    def test_removes_url_duplicates(self, dedup):
        articles = [
            _make_article("Article A", "https://example.com/a", 100),
            _make_article("Article A copy", "https://example.com/a", 50),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1
        assert result[0].score == 100  # Keeps higher score

    def test_removes_url_duplicates_with_tracking(self, dedup):
        articles = [
            _make_article("Article", "https://example.com/a", 100),
            _make_article("Article", "https://example.com/a?utm_source=twitter", 50),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1

    def test_removes_title_duplicates(self, dedup):
        articles = [
            _make_article("OpenAI releases GPT-5 today", "https://site-a.com/1", 200),
            _make_article(
                "OpenAI releases GPT-5 today!", "https://site-b.com/2", 100
            ),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1
        assert result[0].score == 200

    def test_keeps_different_articles(self, dedup):
        articles = [
            _make_article("Apple launches MacBook", "https://a.com/1", 100),
            _make_article("Google quantum breakthrough", "https://b.com/2", 200),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 2

    def test_cache_prevents_resend(self, dedup, cache):
        # Mark an article as seen in a previous run
        cache.mark_seen("https://example.com/old", "Old article", "reddit")

        articles = [
            _make_article("Old article", "https://example.com/old", 500),
            _make_article("New article", "https://example.com/new", 100),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1
        assert result[0].title == "New article"

    def test_empty_list(self, dedup):
        assert dedup.deduplicate([]) == []

    def test_sorts_by_score(self, dedup):
        articles = [
            _make_article("Low", "https://a.com/1", 10),
            _make_article("High", "https://b.com/2", 1000),
            _make_article("Mid", "https://c.com/3", 500),
        ]
        result = dedup.deduplicate(articles)
        assert result[0].score == 1000
        assert result[1].score == 500
        assert result[2].score == 10


# ============================================================================
# Article Cache
# ============================================================================


class TestArticleCache:
    @pytest.fixture
    def cache(self, tmp_path):
        return ArticleCache(tmp_path / "test.db")

    def test_mark_and_check(self, cache):
        assert not cache.is_seen("https://example.com/x")
        cache.mark_seen("https://example.com/x", "Test", "reddit")
        assert cache.is_seen("https://example.com/x")

    def test_count(self, cache):
        assert cache.count() == 0
        cache.mark_seen("https://a.com", "A", "reddit")
        cache.mark_seen("https://b.com", "B", "hn")
        assert cache.count() == 2

    def test_batch_mark(self, cache):
        batch = [
            ("https://a.com", "A", "reddit"),
            ("https://b.com", "B", "hn"),
            ("https://c.com", "C", "x"),
        ]
        cache.mark_batch_seen(batch)
        assert cache.count() == 3
        assert cache.is_seen("https://b.com")

    def test_prune(self, cache):
        cache.mark_seen("https://old.com", "Old", "reddit")
        # Insert with a backdated timestamp
        conn = cache._get_conn()
        conn.execute(
            "UPDATE seen_articles SET first_seen = '2020-01-01T00:00:00'"
        )
        conn.commit()

        deleted = cache.prune_old(days=1)
        assert deleted == 1
        assert cache.count() == 0

    def test_idempotent_mark(self, cache):
        cache.mark_seen("https://a.com", "A", "reddit")
        cache.mark_seen("https://a.com", "A", "reddit")  # Should not error
        assert cache.count() == 1
