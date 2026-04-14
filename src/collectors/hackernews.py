"""HackerNews collector using the Firebase API."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from src.collectors.base import BaseCollector
from src.models.article import Article, Source
from src.utils.logger import get_logger

log = get_logger(__name__)

BASE_URL = "https://hacker-news.firebaseio.com/v0"

# Simple HTML tag stripper (avoids needing BeautifulSoup)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_RE = re.compile(r"&#x([0-9A-Fa-f]+);|&#(\d+);|&(\w+);")

_ENTITY_MAP = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"',
    "apos": "'", "nbsp": " ",
}


def _strip_html(text: str) -> str:
    """Strip HTML tags and decode common entities from HN post text."""
    if not text:
        return ""
    # Remove tags
    text = _HTML_TAG_RE.sub(" ", text)

    # Decode entities
    def _decode(match: re.Match) -> str:
        hex_val, dec_val, name = match.groups()
        if hex_val:
            return chr(int(hex_val, 16))
        if dec_val:
            return chr(int(dec_val))
        if name:
            return _ENTITY_MAP.get(name, f"&{name};")
        return match.group(0)

    text = _HTML_ENTITY_RE.sub(_decode, text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


class HackerNewsCollector(BaseCollector):
    """Collects top stories from Hacker News.

    Uses the public Firebase API (no authentication needed).
    Fetches item details in parallel with aiohttp for speed.
    For link posts (no body text), fetches the first ~2000 chars
    of the linked article so the LLM can generate real summaries.
    """

    source_name = "hackernews"

    async def _collect(self) -> list[Article]:
        limit: int = self.config.get("limit", 30)
        min_score: int = self.config.get("min_score", 100)
        fetch_content: bool = self.config.get("fetch_content", True)

        async with aiohttp.ClientSession() as session:
            # 1. Get the list of top story IDs
            async with session.get(f"{BASE_URL}/topstories.json") as resp:
                resp.raise_for_status()
                story_ids: list[int] = await resp.json()

            # 2. Fetch item details in parallel (limit concurrency)
            story_ids = story_ids[:limit]
            items = await self._fetch_items(session, story_ids)

            # 3. Filter and convert to Article models
            cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
            articles: list[Article] = []

            for item in items:
                if not item or item.get("type") != "story":
                    continue
                if item.get("score", 0) < min_score:
                    continue

                created = datetime.fromtimestamp(
                    item.get("time", 0), tz=timezone.utc
                )
                if created < cutoff:
                    continue

                url = item.get("url", "")
                if not url:
                    # Self/Ask HN posts — use the HN discussion page
                    url = f"https://news.ycombinator.com/item?id={item['id']}"

                # Clean up HN self-post HTML
                raw_content = _strip_html(item.get("text", ""))

                articles.append(
                    Article(
                        title=item.get("title", ""),
                        url=url,
                        source=Source.HACKERNEWS,
                        score=item.get("score", 0),
                        author=item.get("by"),
                        timestamp=created,
                        raw_content=raw_content,
                        source_detail="HN",
                    )
                )

            # 4. Fetch article content for link posts (no body text)
            if fetch_content:
                articles = await self._enrich_articles(session, articles)

        return articles

    async def _fetch_items(
        self, session: aiohttp.ClientSession, ids: list[int]
    ) -> list[dict | None]:
        """Fetch multiple HN items concurrently with a semaphore."""
        sem = asyncio.Semaphore(10)  # max 10 concurrent

        async def _fetch_one(item_id: int) -> dict | None:
            try:
                async with sem:
                    async with session.get(
                        f"{BASE_URL}/item/{item_id}.json"
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        return None
            except Exception as exc:
                log.debug("hn.item_fetch_error", item_id=item_id, error=str(exc))
                return None

        tasks = [_fetch_one(sid) for sid in ids]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def _enrich_articles(
        self, session: aiohttp.ClientSession, articles: list[Article]
    ) -> list[Article]:
        """Fetch article body text from linked URLs for articles missing content."""
        sem = asyncio.Semaphore(5)  # lower concurrency for external sites

        async def _fetch_content(article: Article) -> Article:
            # Skip if already has content or is a HN self-post
            if article.raw_content:
                return article
            if "news.ycombinator.com" in article.url:
                return article

            try:
                async with sem:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (semantic-daily-bot/1.0)",
                        "Accept": "text/html,application/xhtml+xml",
                    }
                    async with session.get(
                        article.url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                        allow_redirects=True,
                    ) as resp:
                        if resp.status != 200:
                            return article
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" not in content_type:
                            return article

                        html = await resp.text(errors="ignore")
                        # Extract text from HTML — simple approach
                        text = _extract_text_from_html(html)
                        if text and len(text) > 50:
                            article.raw_content = text[:2000]
                            log.debug(
                                "hn.content_fetched",
                                url=article.url[:60],
                                chars=len(article.raw_content),
                            )
            except Exception as exc:
                log.debug(
                    "hn.content_fetch_error",
                    url=article.url[:60],
                    error=str(exc),
                )
            return article

        tasks = [_fetch_content(a) for a in articles]
        return list(await asyncio.gather(*tasks))


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML — lightweight, no external deps."""
    # Remove script and style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)

    # Try to find <article> or <main> content first
    for tag in ["article", "main", '[role="main"]']:
        match = re.search(
            rf"<{tag}[^>]*>(.*?)</{tag.split('[')[0]}>",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if match:
            html = match.group(1)
            break

    # Strip all remaining HTML tags
    text = _strip_html(html)

    # Remove runs of whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
