"""Tests for per-category curation — relevance-first ranking with diversity caps."""

from __future__ import annotations

from src.models.article import Article, Source
from src.processing.curation import curate_articles


def _make_article(
    title="Test",
    url="https://example.com",
    source=Source.EXA,
    category="cat",
    score=0,
    relevance=0,
    author=None,
):
    return Article(
        title=title,
        url=url,
        source=source,
        category=category,
        score=score,
        relevance=relevance,
        author=author,
    )


class TestCurateArticles:
    def test_relevance_outranks_raw_engagement(self):
        # Low-engagement but highly relevant article should be picked over a
        # viral but only borderline-relevant one from a different source.
        relevant = _make_article(
            "Relevant", "https://a.com/1", source=Source.RSS, relevance=9, score=10
        )
        viral = _make_article(
            "Viral", "https://b.com/2", source=Source.REDDIT, relevance=5, score=3000
        )
        result = curate_articles([relevant, viral], max_per_category=25, max_per_author=3)
        assert result[0].title == "Relevant"
        assert result[1].title == "Viral"

    def test_engagement_breaks_ties_within_same_relevance(self):
        low_engagement = _make_article(
            "Low", "https://a.com/1", source=Source.RSS, relevance=8, score=10
        )
        high_engagement = _make_article(
            "High", "https://b.com/2", source=Source.HACKERNEWS, relevance=8, score=500
        )
        result = curate_articles(
            [low_engagement, high_engagement], max_per_category=25, max_per_author=3
        )
        assert result[0].title == "High"
        assert result[1].title == "Low"

    def test_respects_max_per_category(self):
        articles = [
            _make_article(f"A{i}", f"https://a.com/{i}", relevance=5 + (i % 5), author=f"user{i}")
            for i in range(30)
        ]
        result = curate_articles(articles, max_per_category=10, max_per_author=3)
        assert len(result) == 10

    def test_respects_max_per_author(self):
        articles = [
            _make_article(f"A{i}", f"https://a.com/{i}", relevance=5, author="same_author")
            for i in range(10)
        ]
        result = curate_articles(articles, max_per_category=25, max_per_author=3)
        assert len(result) == 3

    def test_categories_curated_independently(self):
        cat_a = [
            _make_article(f"A{i}", f"https://a.com/{i}", category="A", relevance=5, author=f"a{i}")
            for i in range(5)
        ]
        cat_b = [
            _make_article(f"B{i}", f"https://b.com/{i}", category="B", relevance=5, author=f"b{i}")
            for i in range(5)
        ]
        result = curate_articles(cat_a + cat_b, max_per_category=3, max_per_author=3)
        assert sum(1 for a in result if a.category == "A") == 3
        assert sum(1 for a in result if a.category == "B") == 3

    def test_diversifies_across_sources_round_robin(self):
        reddit_heavy = [
            _make_article(
                f"R{i}", f"https://r.com/{i}", source=Source.REDDIT, relevance=9, author=f"r{i}"
            )
            for i in range(10)
        ]
        single_exa = [_make_article("E1", "https://e.com/1", source=Source.EXA, relevance=9, author="e1")]
        result = curate_articles(reddit_heavy + single_exa, max_per_category=3, max_per_author=3)
        sources = {a.source for a in result}
        assert Source.EXA in sources

    def test_empty_list(self):
        assert curate_articles([], max_per_category=25, max_per_author=3) == []
