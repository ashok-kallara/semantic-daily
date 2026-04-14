"""Reddit collector using the free public JSON endpoints."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from src.collectors.base import BaseCollector
from src.models.article import Article, Source
from src.utils.logger import get_logger

log = get_logger(__name__)


class RedditCollector(BaseCollector):
    """Collects top posts from specified subreddits via the free Reddit .json API."""

    source_name = "reddit"
    max_retries = 3
    base_delay = 2.0

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        
        # The config passed is already the reddit block
        self.subreddits = config.get("subreddits", config.get("reddit_subreddits", []))
        self.enabled = config.get("enabled", config.get("reddit_enabled", True))

        self.limit = 30
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.5",
        }

    async def _collect(self) -> list[Article]:
        if not self.enabled or not self.subreddits:
            log.info("reddit.skipped", reason="disabled_or_no_subreddits")
            return []

        articles: list[Article] = []

        async with aiohttp.ClientSession(headers=self.headers) as session:
            for sub in self.subreddits:
                try:
                    sub_arts = await self._fetch_subreddit(session, sub)
                    articles.extend(sub_arts)
                    # Respect rate limits between subreddit checks
                    await asyncio.sleep(1.5)
                except Exception as e:
                    log.warning("reddit.fetch_failed", subreddit=sub, error=str(e))
                    
        return articles

    async def _fetch_subreddit(self, session: aiohttp.ClientSession, subreddit: str) -> list[Article]:
        """Fetch top recent posts from a specific subreddit."""
        sub = subreddit.lstrip("r/").strip()
        url = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit={self.limit}&raw_json=1"
        
        for attempt in range(self.max_retries):
            try:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After", self.base_delay * (2 ** attempt))
                        delay = float(retry_after)
                        log.warning("reddit.rate_limited", subreddit=sub, delay=delay)
                        await asyncio.sleep(delay)
                        continue
                        
                    resp.raise_for_status()
                    
                    content_type = resp.headers.get("Content-Type", "")
                    if "json" not in content_type:
                        log.warning("reddit.anti_bot_hit", subreddit=sub, content_type=content_type)
                        return []
                        
                    data = await resp.json()
                    return self._parse_posts(data)
                    
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise e
                await asyncio.sleep(self.base_delay * (2 ** attempt))
                
        return []

    def _parse_posts(self, data: dict[str, Any]) -> list[Article]:
        """Parse Reddit listing JSON into Article models."""
        articles = []
        children = data.get("data", {}).get("children", [])
        
        for child in children:
            if child.get("kind") != "t3":
                continue
                
            post = child.get("data", {})
            permalink = str(post.get("permalink", "")).strip()
            if not permalink:
                continue
                
            score = int(post.get("score", 0) or 0)
            num_comments = int(post.get("num_comments", 0) or 0)
            author = str(post.get("author", "[deleted]"))
            subreddit = str(post.get("subreddit", ""))
            created_utc = post.get("created_utc")
            
            timestamp = None
            if created_utc:
                try:
                    timestamp = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                except (ValueError, TypeError):
                    pass
            
            article = Article(
                title=str(post.get("title", "")).strip(),
                url=f"https://www.reddit.com{permalink}",
                source=Source.REDDIT,
                source_detail=f"r/{subreddit}",
                score=score,
                author=author,
                timestamp=timestamp,
                raw_content=post.get("selftext", "")[:2000],
                comment_count=num_comments,
            )
            articles.append(article)
            
        return articles
