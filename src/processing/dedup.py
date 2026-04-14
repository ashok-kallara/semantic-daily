"""Deduplication engine — URL normalization + fuzzy title matching."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from typing import Any

import jellyfish

from src.models.article import Article
from src.utils.cache import ArticleCache
from src.utils.logger import get_logger

log = get_logger(__name__)

# URL parameters to strip (tracking / analytics)
STRIP_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "ref",
    "ref_src",
    "ref_url",
    "source",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison by removing tracking params,
    www prefix, trailing slashes, and lowercasing the domain."""
    try:
        parsed = urlparse(url)

        # Lowercase scheme and host
        scheme = parsed.scheme.lower() or "https"
        host = parsed.netloc.lower()

        # Strip www. prefix
        if host.startswith("www."):
            host = host[4:]

        # Strip tracking parameters
        params = parse_qs(parsed.query, keep_blank_values=False)
        cleaned_params = {
            k: v for k, v in params.items() if k.lower() not in STRIP_PARAMS
        }
        query = urlencode(cleaned_params, doseq=True)

        # Strip trailing slash from path
        path = parsed.path.rstrip("/") or "/"

        return urlunparse((scheme, host, path, parsed.params, query, ""))
    except Exception:
        return url.strip().lower()


def title_similarity(a: str, b: str) -> float:
    """Compute Jaro-Winkler similarity between two article titles.

    Returns a float in [0, 1] where 1 = identical.
    Titles are lowered and stripped of common noise before comparison.
    """
    a_clean = _clean_title(a)
    b_clean = _clean_title(b)
    if not a_clean or not b_clean:
        return 0.0
    return jellyfish.jaro_winkler_similarity(a_clean, b_clean)


def _clean_title(title: str) -> str:
    """Strip punctuation, extra whitespace, and common prefixes from a title."""
    title = title.lower().strip()
    # Remove common editorial prefixes
    for prefix in ["breaking:", "update:", "[oc]", "[d]", "[r]", "[p]", "[n]"]:
        title = title.removeprefix(prefix).strip()
    # Remove non-alphanumeric (keep spaces)
    title = re.sub(r"[^\w\s]", "", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    return title


class Deduplicator:
    """Multi-layer deduplication for collected articles.

    Layer 1: URL normalization — exact match after cleaning
    Layer 2: Fuzzy title similarity — catches same story from different sources
    Layer 3: Historical cache — prevents re-sending across daily runs
    """

    def __init__(self, config: dict[str, Any], cache: ArticleCache) -> None:
        self.threshold: float = config.get("title_similarity_threshold", 0.82)
        self.cache = cache

    def deduplicate(self, articles: list[Article]) -> list[Article]:
        """Remove duplicate articles, keeping the highest-scored version.

        Returns deduplicated list sorted by score descending.
        """
        if not articles:
            return []

        # --- Layer 3: Remove historically seen articles ---
        fresh: list[Article] = []
        cached_count = 0
        for article in articles:
            norm = normalize_url(article.url)
            if self.cache.is_seen(norm):
                cached_count += 1
            else:
                article.url_hash = norm
                fresh.append(article)

        if cached_count:
            log.info("dedup.cache_hits", removed=cached_count)

        # --- Layer 1: URL dedup ---
        url_map: dict[str, Article] = {}
        for article in fresh:
            norm = normalize_url(article.url)
            if norm in url_map:
                existing = url_map[norm]
                # Merge engagement metrics cumulatively
                self._merge_metrics(existing, article)
                
                # Keep the version with the higher score
                if article.score > existing.score:
                    # Merge source attribution
                    article.source_detail = self._merge_sources(
                        article.source_detail, existing.source_detail
                    )
                    url_map[norm] = article
                else:
                    existing.source_detail = self._merge_sources(
                        existing.source_detail, article.source_detail
                    )
            else:
                url_map[norm] = article

        url_deduped = list(url_map.values())
        url_dupes = len(fresh) - len(url_deduped)
        if url_dupes:
            log.info("dedup.url_duplicates", removed=url_dupes)

        # --- Layer 2: Fuzzy title dedup ---
        title_deduped: list[Article] = []
        for article in url_deduped:
            is_dup = False
            for kept in title_deduped:
                sim = title_similarity(article.title, kept.title)
                if sim >= self.threshold:
                    log.debug(
                        "dedup.title_match",
                        title_a=article.title[:60],
                        title_b=kept.title[:60],
                        similarity=round(sim, 3),
                    )
                    # Merge engagement metrics cumulatively
                    self._merge_metrics(kept, article)

                    # Merge into the one with higher score
                    if article.score > kept.score:
                        kept.title = article.title
                        kept.url = article.url
                        kept.score = article.score
                        kept.raw_content = article.raw_content or kept.raw_content
                    kept.source_detail = self._merge_sources(
                        kept.source_detail, article.source_detail
                    )
                    is_dup = True
                    break
            if not is_dup:
                title_deduped.append(article)

        title_dupes = len(url_deduped) - len(title_deduped)
        if title_dupes:
            log.info("dedup.title_duplicates", removed=title_dupes)

        # Sort by score descending
        title_deduped.sort(key=lambda a: a.score, reverse=True)

        total_removed = len(articles) - len(title_deduped)
        log.info(
            "dedup.complete",
            input=len(articles),
            output=len(title_deduped),
            removed=total_removed,
        )

        return title_deduped

    @staticmethod
    def _merge_sources(primary: str | None, secondary: str | None) -> str:
        """Merge two source detail strings, e.g. 'r/ai' + 'HN' → 'r/ai, HN'."""
        parts = set()
        for s in (primary, secondary):
            if s:
                parts.update(p.strip() for p in s.split(","))
        return ", ".join(sorted(parts)) if parts else ""

    @staticmethod
    def _merge_metrics(primary: Article, secondary: Article) -> None:
        """Merge engagement scores so cross-platform stories show cumulative totals."""
        if secondary.like_count:
            primary.like_count = (primary.like_count or 0) + secondary.like_count
        if secondary.retweet_count:
            primary.retweet_count = (primary.retweet_count or 0) + secondary.retweet_count
        if secondary.reply_count:
            primary.reply_count = (primary.reply_count or 0) + secondary.reply_count
        if secondary.comment_count:
            primary.comment_count = (primary.comment_count or 0) + secondary.comment_count
        if secondary.view_count:
            primary.view_count = (primary.view_count or 0) + secondary.view_count
        if secondary.listen_score and not primary.listen_score:
            primary.listen_score = secondary.listen_score

