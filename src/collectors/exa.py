"""Exa.ai neural search collector — finds trending AI/tech content across the web."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.collectors.base import BaseCollector
from src.models.article import Article, MediaType, Source
from src.utils.logger import get_logger

log = get_logger(__name__)


class ExaCollector(BaseCollector):
    """Searches the web for AI/tech news using Exa's neural search API.

    Exa returns results ranked by relevance and authority — if something
    shows up, it's already been deemed notable by the search engine.
    """

    source_name = "exa"

    async def _collect(self) -> list[Article]:
        api_key: str = self.config.get("api_key", "")
        if not api_key:
            log.warning("exa.no_api_key")
            return []

        queries: list[str] = self.config.get("queries", [
            "latest AI and machine learning news",
            "LLM breakthroughs",
        ])
        max_results: int = self.config.get("max_results", 30)
        exclude_domains: list[str] = self.config.get("exclude_domains", [
            "pinterest.com", "facebook.com",
        ])
        include_domains: list[str] = self.config.get("include_domains", [])
        lookback_hours: int = self.config.get("lookback_hours", 36)

        from exa_py import Exa
        exa = Exa(api_key=api_key)

        start_date = (
            datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_articles: list[Article] = []

        for query in queries:
            try:
                import asyncio
                search_kwargs: dict[str, Any] = {
                    "num_results": max_results,
                    "start_published_date": start_date,
                    "use_autoprompt": True,
                    "type": "neural",
                    "text": True,
                }
                if include_domains:
                    search_kwargs["include_domains"] = include_domains
                if exclude_domains:
                    search_kwargs["exclude_domains"] = exclude_domains

                results = await asyncio.to_thread(
                    exa.search_and_contents, query, **search_kwargs
                )

                for result in results.results:
                    # Determine media type from URL
                    media_type = MediaType.ARTICLE
                    url = result.url or ""
                    if "youtube.com" in url or "youtu.be" in url:
                        media_type = MediaType.VIDEO

                    # Parse timestamp
                    ts = None
                    if result.published_date:
                        try:
                            ts = datetime.fromisoformat(
                                result.published_date.replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            pass

                    # Extract text content
                    text = ""
                    if hasattr(result, "text") and result.text:
                        text = result.text[:2000]
                    elif hasattr(result, "highlights") and result.highlights:
                        text = " ".join(result.highlights)[:2000]

                    # Exa score is a float relevance score
                    exa_score = int(getattr(result, "score", 0) * 100)

                    all_articles.append(
                        Article(
                            title=result.title or url[:100],
                            url=url,
                            source=Source.EXA,
                            score=exa_score,
                            author=getattr(result, "author", None),
                            timestamp=ts,
                            raw_content=text,
                            source_detail=f"exa:{query[:30]}",
                            media_type=media_type,
                        )
                    )

                log.debug(
                    "exa.query_done",
                    query=query[:50],
                    results=len(results.results),
                )

            except Exception as exc:
                log.error("exa.query_error", query=query[:50], error=str(exc))

        log.info("exa.total_collected", count=len(all_articles))
        return all_articles
