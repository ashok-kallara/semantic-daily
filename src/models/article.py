"""Data models for the news feed aggregator."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Source(str, Enum):
    """Supported news sources."""

    HACKERNEWS = "hackernews"
    EXA = "exa"
    BLUESKY = "bluesky"
    REDDIT = "reddit"
    RSS = "rss"
    GITHUB = "github"
    YOUTUBE = "youtube"
    PODCAST = "podcast"


class MediaType(str, Enum):
    """Content media type for formatting decisions."""

    ARTICLE = "article"
    VIDEO = "video"
    PODCAST = "podcast"


class Article(BaseModel):
    """A single news article, video, or podcast from any source."""

    model_config = ConfigDict(use_enum_values=True)

    title: str
    url: str
    source: Source
    category: str = "uncategorized"
    score: int = 0
    author: Optional[str] = None
    timestamp: Optional[datetime] = None
    raw_content: Optional[str] = None
    summary: Optional[str] = None
    source_detail: Optional[str] = None  # e.g., subreddit, HN, @handle, channel
    url_hash: Optional[str] = None  # For dedup cache
    media_type: MediaType = MediaType.ARTICLE

    # Engagement metrics (populated by Apify / YouTube / ListenNotes)
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    retweet_count: Optional[int] = None
    reply_count: Optional[int] = None
    comment_count: Optional[int] = None
    listen_score: Optional[int] = None  # ListenNotes relevance (0-100)
    duration_seconds: Optional[int] = None  # Podcast/video duration

    @property
    def engagement_score(self) -> int:
        """Normalized engagement score across sources for sorting.

        Combines available metrics into a single comparable number.
        """
        if self.score > 0:
            return self.score

        total = 0
        if self.like_count:
            total += self.like_count
        if self.retweet_count:
            total += self.retweet_count * 2  # Retweets worth more
        if self.reply_count:
            total += self.reply_count
        if self.view_count:
            total += self.view_count // 1000  # Normalize large view counts
        if self.listen_score:
            total += self.listen_score * 10
        return total

    @property
    def duration_display(self) -> str | None:
        """Human-readable duration for podcasts/videos."""
        if not self.duration_seconds:
            return None
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"


class Digest(BaseModel):
    """A complete daily digest ready for delivery."""

    date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    articles: list[Article] = Field(default_factory=list)
    total_collected: int = 0
    duplicates_removed: int = 0
    sources_used: list[str] = Field(default_factory=list)

    @property
    def by_category(self) -> dict[str, list[Article]]:
        """Group articles by category."""
        grouped: dict[str, list[Article]] = {}
        for article in self.articles:
            grouped.setdefault(article.category, []).append(article)
        # Sort each category by engagement score descending
        for cat in grouped:
            grouped[cat].sort(key=lambda a: a.engagement_score, reverse=True)
        return grouped

    @property
    def article_count(self) -> int:
        return len(self.articles)
