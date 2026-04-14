"""Bluesky collector using the public AT Protocol Search API."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import aiohttp

from src.collectors.base import BaseCollector
from src.models.article import Article, Source
from src.utils.logger import get_logger

log = get_logger(__name__)


class BlueskyCollector(BaseCollector):
    """Collects top AI/Tech posts from Bluesky via authenticated AT Protocol search."""

    source_name = "bluesky"
    BSKY_AUTH_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"
    BSKY_SEARCH_URL = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.enabled = config.get("enabled", True)
        self.app_password = config.get("app_password", None)
        self.handle = config.get("handle", None)
        
        # In a real app we might query LLM for themes, but for now we query top AI tags
        self.queries = ["#AI", "#MachineLearning", "#LLM", "\"Agentic AI\""]
        self.limit = 30

    async def _collect(self) -> list[Article]:
        if not self.enabled:
            return []

        if not self.handle or not self.app_password:
            log.warning("bluesky.auth_missing", message="handle or app_password not set in config")
            return []

        articles: list[Article] = []
        headers = {"Accept": "application/json"}
        
        async with aiohttp.ClientSession(headers=headers) as session:
            # 1. Authenticate with AT Protocol
            try:
                auth_payload = {"identifier": self.handle, "password": self.app_password}
                async with session.post(self.BSKY_AUTH_URL, json=auth_payload, timeout=10) as auth_resp:
                    auth_resp.raise_for_status()
                    auth_data = await auth_resp.json()
                    jwt = auth_data.get("accessJwt")
                    if not jwt:
                        log.error("bluesky.auth_failed", message="No accessJwt returned from AT Protocol")
                        return []
                    
                    # Apply Bearer token to all subsequent requests in this session
                    session.headers.update({"Authorization": f"Bearer {jwt}"})
                    log.info("bluesky.auth_success", handle=self.handle)
            except Exception as e:
                log.error("bluesky.auth_failed", error=str(e))
                return []

            # 2. Execute search queries against the rich authenticated endpoint
            for query in self.queries:
                try:
                    params = {"q": query, "limit": str(self.limit), "sort": "top"}
                    url = f"{self.BSKY_SEARCH_URL}?{urlencode(params)}"
                    
                    async with session.get(url, timeout=15) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                        articles.extend(self._parse_posts(data))
                        
                    await asyncio.sleep(1)  # polite delay
                except Exception as e:
                    log.warning("bluesky.fetch_failed", query=query, error=str(e))
                    
        return articles

    def _parse_posts(self, data: dict[str, Any]) -> list[Article]:
        """Parse AT Protocol response into Article models."""
        posts = data.get("posts", [])
        articles = []

        for post in posts:
            record = post.get("record", {})
            text = record.get("text", "")
            
            author = post.get("author", {})
            handle = author.get("handle", "unknown")
            display_name = author.get("displayName", handle)
            
            uri = post.get("uri", "")
            rkey = uri.rsplit("/", 1)[-1] if uri else ""
            url = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else ""
            
            if not url:
                continue

            likes = post.get("likeCount", 0)
            reposts = post.get("repostCount", 0)
            replies = post.get("replyCount", 0)
            
            date_str = post.get("indexedAt") or record.get("createdAt")
            timestamp = None
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    timestamp = dt.astimezone(timezone.utc)
                except (ValueError, TypeError):
                    pass

            article = Article(
                title=f"Post by {display_name}",
                url=url,
                source=Source.BLUESKY,
                source_detail=f"@{handle}",
                score=likes + (reposts * 2),
                author=display_name,
                timestamp=timestamp,
                raw_content=text,
                like_count=likes,
                retweet_count=reposts,
                reply_count=replies,
            )
            articles.append(article)

        return articles
