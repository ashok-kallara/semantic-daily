"""Upstash Redis-based cache for deduplication across CI runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import redis

from src.utils.logger import get_logger

log = get_logger(__name__)


class RedisArticleCache:
    """Thread-safe Redis cache tracking previously seen articles.

    Used to prevent re-sending the same article across daily runs.
    Utilizes Redis TTL for automatic pruning.
    """

    def __init__(self, redis_url: str, redis_token: str, ttl_days: int = 7) -> None:
        self.ttl_seconds = ttl_days * 86400
        # Use rediss:// for secure connection string often provided by Upstash
        # If url doesn't start with redis:// or rediss://, we might need to prepend.
        # But usually Upstash URL is complete. We pass token as password.
        self._client = redis.from_url(redis_url, password=redis_token, decode_responses=True)
        log.debug("redis_cache.initialized", ttl_days=ttl_days)

    @staticmethod
    def hash_url(url: str) -> str:
        """Create a stable hash of a normalized URL."""
        return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]

    def _key(self, url_hash: str) -> str:
        return f"seen:{url_hash}"

    def is_seen(self, url: str) -> bool:
        """Check if a URL has been seen before."""
        url_hash = self.hash_url(url)
        return bool(self._client.exists(self._key(url_hash)))

    def mark_seen(self, url: str, title: str, source: str) -> None:
        """Record an article as seen with TTL."""
        url_hash = self.hash_url(url)
        key = self._key(url_hash)
        
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "url": url,
            "title": title,
            "source": source,
            "first_seen": now
        }
        
        # NX = Only set if not exists
        self._client.set(key, json.dumps(data), ex=self.ttl_seconds, nx=True)

    def mark_batch_seen(self, articles: list[tuple[str, str, str]]) -> None:
        """Record multiple articles as seen: [(url, title, source), ...]."""
        if not articles:
            return
            
        now = datetime.now(timezone.utc).isoformat()
        pipe = self._client.pipeline()
        
        for url, title, source in articles:
            url_hash = self.hash_url(url)
            key = self._key(url_hash)
            data = {
                "url": url,
                "title": title,
                "source": source,
                "first_seen": now
            }
            pipe.set(key, json.dumps(data), ex=self.ttl_seconds, nx=True)
            
        pipe.execute()
        log.debug("redis_cache.batch_marked", count=len(articles))

    def prune_old(self, days: int = 7) -> int:
        """No-op. Upstash Redis handles this automatically via TTL mapping."""
        return 0

    def count(self) -> int:
        """Return an approximation of seen articles by scanning Keys or DBSIZE.
        Since DBSIZE includes all keys, we use a scan for `seen:*` to be safe, 
        or just rely on dbsize if it's a dedicated db.
        """
        # Note: SCAN might be slow for huge DBs, but fine for our daily digest scale.
        cursor = '0'
        total = 0
        while cursor != 0:
            cursor, keys = self._client.scan(cursor=cursor, match='seen:*', count=1000)
            total += len(keys)
            if cursor == '0' or cursor == 0: # Handle different redis-py versions
                break
        return total

    def close(self) -> None:
        """Close connection pool."""
        self._client.close()
