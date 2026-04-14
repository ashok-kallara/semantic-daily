"""GitHub collector to fetch top daily and weekly trending repositories."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import aiohttp

from src.collectors.base import BaseCollector
from src.models.article import Article, Source
from src.utils.logger import get_logger

log = get_logger(__name__)


class GitHubCollector(BaseCollector):
    """Collects top new GitHub repositories by stars."""

    source_name = "github"
    GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.enabled = config.get("enabled", True)
        self.token = config.get("token", None)
        self.limit = 15

    async def _collect(self) -> list[Article]:
        if not self.enabled:
            return []

        articles: list[Article] = []
        
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "semantic-daily-bot/1.0",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        now = datetime.now(timezone.utc)
        yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        last_week_str = (now - timedelta(days=7)).strftime('%Y-%m-%d')

        queries = [
            (f"created:>{yesterday_str}", "Daily Top Repos"),
            (f"created:>{last_week_str}", "Weekly Top Repos"),
        ]

        async with aiohttp.ClientSession(headers=headers) as session:
            for query, mode in queries:
                try:
                    params = {
                        "q": query,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": str(self.limit)
                    }
                    url = f"{self.GITHUB_SEARCH_URL}?{urlencode(params)}"
                    
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 403:
                            log.warning("github.rate_limited", mode=mode)
                            continue
                            
                        resp.raise_for_status()
                        data = await resp.json()
                        articles.extend(self._parse_repos(data, mode))
                        
                    await asyncio.sleep(2)  # Github search rate limits are strict
                except Exception as e:
                    log.warning("github.fetch_failed", mode=mode, error=str(e))
                    
        return articles

    def _parse_repos(self, data: dict[str, Any], mode: str) -> list[Article]:
        """Convert GitHub repositories to Article models."""
        articles = []
        items = data.get("items", [])
        
        for item in items:
            name = item.get("full_name", "")
            if not name:
                continue
                
            stars = item.get("stargazers_count", 0)
            desc = item.get("description", "") or "No description provided."
            lang = item.get("language", "")
            html_url = item.get("html_url", "")
            
            created_at = item.get("created_at")
            timestamp = None
            if created_at:
                try:
                    timestamp = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            content = f"Language: {lang}\nDescription: {desc}"

            article = Article(
                title=f"GitHub Trending ({mode}): {name}",
                url=html_url,
                source=Source.GITHUB,
                source_detail=mode,
                score=stars,
                author=item.get("owner", {}).get("login", ""),
                timestamp=timestamp,
                raw_content=content,
                like_count=stars,
            )
            articles.append(article)
            
        return articles
