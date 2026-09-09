"""Per-category curation — caps articles while enforcing source and author diversity."""

from __future__ import annotations

from src.models.article import Article


def curate_articles(
    articles: list[Article],
    max_per_category: int,
    max_per_author: int,
) -> list[Article]:
    """Select up to `max_per_category` articles per category.

    Round-robins across sources within a category so no single source
    dominates, capping repeats per author/subreddit/channel. Selection and
    final ordering both rank by `Article.rank_score` (persona relevance
    first, engagement as a tiebreaker) rather than raw engagement alone.
    """
    grouped: dict[str, list[Article]] = {}
    for article in articles:
        grouped.setdefault(article.category, []).append(article)

    curated: list[Article] = []
    for items in grouped.values():
        by_source: dict[str, list[Article]] = {}
        for item in items:
            by_source.setdefault(item.source, []).append(item)

        for src_items in by_source.values():
            src_items.sort(key=lambda x: x.rank_score, reverse=True)

        cat_curated: list[Article] = []
        author_counts: dict[str, int] = {}
        while by_source and len(cat_curated) < max_per_category:
            for src in list(by_source.keys()):
                if len(cat_curated) >= max_per_category:
                    break
                if by_source[src]:
                    candidate = by_source[src].pop(0)
                    auth_key = candidate.author or candidate.source_detail or "unknown"
                    if author_counts.get(auth_key, 0) < max_per_author:
                        author_counts[auth_key] = author_counts.get(auth_key, 0) + 1
                        cat_curated.append(candidate)
                else:
                    del by_source[src]

        cat_curated.sort(key=lambda x: x.rank_score, reverse=True)
        curated.extend(cat_curated)

    return curated
