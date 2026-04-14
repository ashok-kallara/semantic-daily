"""SQLite-based cache for deduplication across runs."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_DB_PATH = Path("data/seen_articles.db")


class ArticleCache:
    """Thread-safe SQLite cache tracking previously seen articles.

    Used to prevent re-sending the same article across daily runs.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_articles (
                url_hash    TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                title       TEXT NOT NULL,
                source      TEXT NOT NULL,
                first_seen  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_first_seen
            ON seen_articles(first_seen)
            """
        )
        conn.commit()
        log.debug("article_cache.initialized", db_path=str(self.db_path))

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10,
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @staticmethod
    def hash_url(url: str) -> str:
        """Create a stable hash of a normalized URL."""
        return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]

    def is_seen(self, url: str) -> bool:
        """Check if a URL has been seen before."""
        url_hash = self.hash_url(url)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM seen_articles WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row is not None

    def mark_seen(self, url: str, title: str, source: str) -> None:
        """Record an article as seen."""
        url_hash = self.hash_url(url)
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO seen_articles (url_hash, url, title, source, first_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url_hash, url, title, source, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    def mark_batch_seen(
        self, articles: list[tuple[str, str, str]]
    ) -> None:
        """Record multiple articles as seen: [(url, title, source), ...]."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            """
            INSERT OR IGNORE INTO seen_articles (url_hash, url, title, source, first_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (self.hash_url(url), url, title, source, now)
                for url, title, source in articles
            ],
        )
        conn.commit()
        log.debug("article_cache.batch_marked", count=len(articles))

    def prune_old(self, days: int = 7) -> int:
        """Remove entries older than `days`. Returns count deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM seen_articles WHERE first_seen < ?", (cutoff,)
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted:
            log.info("article_cache.pruned", deleted=deleted, days=days)
        return deleted

    def count(self) -> int:
        """Return the total number of cached articles."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM seen_articles").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
