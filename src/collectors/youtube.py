"""YouTube Data API collector — finds popular AI/tech videos and podcast episodes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from src.collectors.base import BaseCollector
from src.models.article import Article, MediaType, Source
from src.utils.logger import get_logger

log = get_logger(__name__)

YT_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeCollector(BaseCollector):
    """Searches YouTube for popular AI/tech videos and podcast episodes.

    Uses the YouTube Data API v3 to search by keywords, then fetches
    video statistics (views, likes) to rank by popularity.
    """

    source_name = "youtube"

    async def _collect(self) -> list[Article]:
        api_key: str = self.config.get("api_key", "")
        if not api_key:
            log.warning("youtube.no_api_key")
            return []

        queries: list[str] = self.config.get("queries", [
            "AI news",
            "machine learning",
        ])
        max_results: int = self.config.get("max_results", 10)
        published_after_hours: int = self.config.get("published_after_hours", 48)
        order: str = self.config.get("order", "viewCount")
        min_views: int = self.config.get("min_views", 1000)

        published_after = (
            datetime.now(timezone.utc) - timedelta(hours=published_after_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_articles: list[Article] = []

        async with aiohttp.ClientSession() as session:
            for query in queries:
                try:
                    articles = await self._search_videos(
                        session, api_key, query, max_results,
                        published_after, order, min_views,
                    )
                    all_articles.extend(articles)
                except Exception as exc:
                    log.error(
                        "youtube.query_error",
                        query=query[:50],
                        error=str(exc),
                    )

        log.info("youtube.total_collected", count=len(all_articles))
        return all_articles

    async def _search_videos(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        query: str,
        max_results: int,
        published_after: str,
        order: str,
        min_views: int,
    ) -> list[Article]:
        """Search YouTube and fetch video statistics."""
        # Step 1: Search for videos
        search_params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": order,
            "publishedAfter": published_after,
            "maxResults": max_results,
            "key": api_key,
            "relevanceLanguage": "en",
        }

        async with session.get(
            f"{YT_API_BASE}/search",
            params=search_params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                log.warning(
                    "youtube.search_error",
                    status=resp.status,
                    body=body[:200],
                )
                return []
            search_data = await resp.json()

        items = search_data.get("items", [])
        if not items:
            return []

        # Step 2: Fetch statistics for all video IDs
        video_ids = [
            item["id"]["videoId"]
            for item in items
            if item.get("id", {}).get("videoId")
        ]

        stats = await self._fetch_statistics(session, api_key, video_ids)

        # Step 3: Build Article models
        articles: list[Article] = []
        for item in items:
            video_id = item.get("id", {}).get("videoId", "")
            snippet = item.get("snippet", {})
            video_stats = stats.get(video_id, {})

            views = int(video_stats.get("viewCount", 0))
            likes = int(video_stats.get("likeCount", 0))
            comments = int(video_stats.get("commentCount", 0))
            duration_iso = video_stats.get("duration", "")

            if views < min_views:
                continue

            # Parse publish date
            ts = None
            published = snippet.get("publishedAt")
            if published:
                try:
                    ts = datetime.fromisoformat(
                        published.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            channel = snippet.get("channelTitle", "")
            title = snippet.get("title", "")
            description = snippet.get("description", "")

            # Parse ISO 8601 duration (PT1H2M3S)
            duration_secs = self._parse_iso_duration(duration_iso)

            articles.append(
                Article(
                    title=title,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    source=Source.YOUTUBE,
                    score=views // 100 + likes,  # Normalize for sorting
                    author=channel,
                    timestamp=ts,
                    raw_content=description[:1000],
                    source_detail=channel,
                    media_type=MediaType.VIDEO,
                    view_count=views,
                    like_count=likes,
                    comment_count=comments,
                    duration_seconds=duration_secs,
                )
            )

        log.debug(
            "youtube.query_done",
            query=query[:50],
            fetched=len(articles),
        )
        return articles

    async def _fetch_statistics(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        video_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Fetch view/like counts and duration for a batch of video IDs."""
        if not video_ids:
            return {}

        params = {
            "part": "statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": api_key,
        }

        async with session.get(
            f"{YT_API_BASE}/videos",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()

        result: dict[str, dict[str, Any]] = {}
        for item in data.get("items", []):
            vid = item.get("id", "")
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            result[vid] = {**stats, "duration": content.get("duration", "")}

        return result

    @staticmethod
    def _parse_iso_duration(iso_str: str) -> int | None:
        """Parse ISO 8601 duration (PT1H2M30S) to seconds."""
        if not iso_str or not iso_str.startswith("PT"):
            return None

        import re
        pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
        match = re.match(pattern, iso_str)
        if not match:
            return None

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
