"""ListenNotes podcast collector — finds popular AI/tech podcast episodes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiohttp

from src.collectors.base import BaseCollector
from src.models.article import Article, MediaType, Source
from src.utils.logger import get_logger

log = get_logger(__name__)

LISTENNOTES_BASE = "https://listen-api.listennotes.com/api/v2"


class ListenNotesCollector(BaseCollector):
    """Searches for recent AI/tech podcast episodes via ListenNotes API.

    Uses the /search endpoint to find episodes matching configured
    keywords, sorted by relevance (which factors in popularity).
    """

    source_name = "listennotes"

    async def _collect(self) -> list[Article]:
        api_key: str = self.config.get("api_key", "")
        if not api_key:
            log.warning("listennotes.no_api_key")
            return []

        queries: list[str] = self.config.get("queries", [
            "artificial intelligence",
            "machine learning",
        ])
        max_results: int = self.config.get("max_results", 15)
        sort_by: str = self.config.get("sort_by", "relevance")  # or "date"
        language: str = self.config.get("language", "English")

        headers = {"X-ListenAPI-Key": api_key}
        all_articles: list[Article] = []

        async with aiohttp.ClientSession(headers=headers) as session:
            for query in queries:
                try:
                    articles = await self._search_episodes(
                        session, query, max_results, sort_by, language
                    )
                    all_articles.extend(articles)
                except Exception as exc:
                    log.error(
                        "listennotes.query_error",
                        query=query[:50],
                        error=str(exc),
                    )

        log.info("listennotes.total_collected", count=len(all_articles))
        return all_articles

    async def _search_episodes(
        self,
        session: aiohttp.ClientSession,
        query: str,
        max_results: int,
        sort_by: str,
        language: str,
    ) -> list[Article]:
        """Search for podcast episodes matching a query."""
        params = {
            "q": query,
            "type": "episode",
            "sort_by_date": 1 if sort_by == "date" else 0,
            "len_min": 5,  # At least 5 minutes
            "language": language,
            "page_size": min(max_results, 10),  # API max is 10 per page
            "published_after": int(
                (datetime.now(timezone.utc).timestamp() - 7 * 86400) * 1000
            ),  # Last 7 days in ms
        }

        async with session.get(
            f"{LISTENNOTES_BASE}/search",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 429:
                log.warning("listennotes.rate_limited")
                return []
            if resp.status != 200:
                log.warning("listennotes.http_error", status=resp.status)
                return []

            data = await resp.json()

        articles: list[Article] = []
        results = data.get("results", [])

        for ep in results:
            title = ep.get("title_original", "")
            podcast_name = ep.get("podcast", {}).get("title_original", "")
            audio_url = ep.get("audio", "")
            listennotes_url = ep.get("listennotes_url", "")
            link = ep.get("link", listennotes_url) or audio_url

            # Parse timestamp (ms since epoch)
            ts = None
            pub_date_ms = ep.get("pub_date_ms")
            if pub_date_ms:
                ts = datetime.fromtimestamp(pub_date_ms / 1000, tz=timezone.utc)

            # Duration in seconds
            duration = ep.get("audio_length_sec", 0)

            # Listen score is a podcast-level metric (0-100)
            listen_score = ep.get("podcast", {}).get("listen_score")
            if listen_score is not None:
                listen_score = int(listen_score)

            # Build content from description
            content = ep.get("description_original", "")[:1000]

            articles.append(
                Article(
                    title=title,
                    url=link,
                    source=Source.PODCAST,
                    score=listen_score * 10 if listen_score else 0,
                    author=podcast_name,
                    timestamp=ts,
                    raw_content=content,
                    source_detail=podcast_name,
                    media_type=MediaType.PODCAST,
                    listen_score=listen_score,
                    duration_seconds=duration,
                )
            )

        log.debug(
            "listennotes.query_done",
            query=query[:50],
            fetched=len(articles),
        )
        return articles
