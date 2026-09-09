"""Tests for the Article/Digest models — relevance vs. engagement separation."""

from __future__ import annotations

from src.models.article import Article, Digest, Source


def _make_article(title="Test", url="https://example.com", category="cat", score=0, relevance=0):
    return Article(title=title, url=url, source=Source.EXA, category=category, score=score, relevance=relevance)


class TestRelevanceField:
    def test_defaults_to_zero(self):
        article = _make_article()
        assert article.relevance == 0

    def test_independent_of_score(self):
        article = _make_article(score=500, relevance=8)
        assert article.score == 500
        assert article.relevance == 8
        assert article.engagement_score == 500  # score still drives engagement_score


class TestRankScore:
    def test_relevance_is_primary_key(self):
        low_score_high_relevance = _make_article(score=10, relevance=9)
        high_score_low_relevance = _make_article(score=3000, relevance=5)
        assert low_score_high_relevance.rank_score > high_score_low_relevance.rank_score

    def test_engagement_breaks_ties(self):
        a = _make_article(score=10, relevance=8)
        b = _make_article(score=500, relevance=8)
        assert b.rank_score > a.rank_score


class TestDigestByCategory:
    def test_sorts_by_relevance_then_engagement(self):
        viral_but_less_relevant = _make_article("Viral", "https://a.com/1", score=3000, relevance=5)
        relevant_but_quiet = _make_article("Relevant", "https://b.com/2", score=10, relevance=9)
        digest = Digest(articles=[viral_but_less_relevant, relevant_but_quiet])
        ordered = digest.by_category["cat"]
        assert ordered[0].title == "Relevant"
        assert ordered[1].title == "Viral"

    def test_groups_by_category(self):
        a = _make_article("A", "https://a.com/1", category="Cat A")
        b = _make_article("B", "https://b.com/2", category="Cat B")
        digest = Digest(articles=[a, b])
        assert set(digest.by_category.keys()) == {"Cat A", "Cat B"}
