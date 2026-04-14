"""RSS collector for scraping configured blogs and newsletters."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
import feedparser

from src.collectors.base import BaseCollector
from src.models.article import Article, Source
from src.utils.logger import get_logger

log = get_logger(__name__)


class RSSCollector(BaseCollector):
    """Collects latest articles from configured RSS/Atom feeds."""

    source_name = "rss"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.enabled = config.get("enabled", True)
        self.feeds = config.get("feeds", [])

    async def _collect(self) -> list[Article]:
        if not self.enabled or not self.feeds:
            return []

        articles: list[Article] = []

        headers = {
            "User-Agent": "semantic-daily-bot/1.0",
        }
        
        async with aiohttp.ClientSession(headers=headers) as session:
            tasks = [self._fetch_feed(session, feed) for feed in self.feeds]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    log.warning("rss.fetch_failed", error=str(result))
                elif isinstance(result, list):
                    articles.extend(result)
                    
        return articles

    async def _fetch_feed(self, session: aiohttp.ClientSession, url: str) -> list[Article]:
        """Fetch and parse a single RSS feed."""
        for attempt in range(self.max_retries):
            try:
                async with session.get(url, timeout=15) as resp:
                    resp.raise_for_status()
                    xml_content = await resp.text()
                    
                    parsed = feedparser.parse(xml_content)
                    if parsed.bozo and parsed.bozo_exception:
                        log.debug("rss.parse_warning", url=url, warning=str(parsed.bozo_exception))
                        
                    return self._parse_entries(parsed, url)
                    
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise e
                await asyncio.sleep(self.base_delay * (2 ** attempt))
                
        return []

    def _parse_entries(self, parsed: Any, feed_url: str) -> list[Article]:
        """Convert feedparser entries into Article models."""
        articles = []
        
        # Determine a source detail name
        feed_title = parsed.feed.get("title", feed_url)
        
        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            # Parse date
            timestamp = None
            if "published_parsed" in entry and entry.published_parsed:
                try:
                    timestamp = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
                except (ValueError, TypeError, OverflowError):
                    pass
                    
            content = ""
            if "content" in entry and entry.content:
                content = entry.content[0].value
            elif "summary" in entry:
                content = entry.summary

            from bs4 import BeautifulSoup
            if content:
                # Strip simple HTML from description/content
                try:
                    soup = BeautifulSoup(content, "html.parser")
                    content = soup.get_text(separator=" ").strip()
                except Exception:
                    pass

            article = Article(
                title=title,
                url=link,
                source=Source.RSS,
                source_detail=feed_title[:50],
                author=entry.get("author", "Unknown"),
                timestamp=timestamp,
                raw_content=content[:3000],
                score=10, # default base score for direct RSS
            )
            articles.append(article)
            
        return articles
