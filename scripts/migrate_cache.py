"""Migrate seen_articles from SQLite → Upstash Redis."""

import os
import json
from upstash_redis import Redis
from pathlib import Path

def migrate():
    print("🚀 Starting migration from SQLite -> Upstash Redis...")
    
    if "UPSTASH_REDIS_URL" not in os.environ or "UPSTASH_REDIS_TOKEN" not in os.environ:
        print("❌ Error: UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN must be set.")
        print("Example: export UPSTASH_REDIS_URL='https://...upstash.io'")
        return

    # 1. Read all rows from SQLite
    try:
        from src.utils.cache import ArticleCache
        sqlite_cache = ArticleCache()
        conn = sqlite_cache._get_conn()
        rows = conn.execute("SELECT url_hash, url, title, source, first_seen FROM seen_articles").fetchall()
    except Exception as e:
        print(f"❌ Failed to reach local sqlite db: {e}")
        return

    if not rows:
        print("ℹ️ Local SQLite DB is empty. Nothing to migrate.")
        return

    print(f"📦 Found {len(rows)} articles in local cache.")

    # 2. Connect to Upstash via REST API
    try:
        r = Redis(url=os.environ["UPSTASH_REDIS_URL"], token=os.environ["UPSTASH_REDIS_TOKEN"])
        r.exists("ping_test") # Quick dummy query to check connection
    except Exception as e:
        print(f"❌ Failed to connect to Upstash Redis: {e}")
        return
    
    # 3. Pipeline write with 7-day TTL
    print("⏳ Migrating entries to Redis...")
    try:
        pipe = r.pipeline()
        for row in rows:
            key = f"seen:{row['url_hash']}"
            value = json.dumps({
                "url": row["url"], 
                "title": row["title"], 
                "source": row["source"],
                "first_seen": row["first_seen"],
            })
            pipe.set(key, value, ex=7*86400)  # 7-day TTL
        pipe.exec()
    except Exception as e:
         print(f"❌ Failed during Redis pipeline write: {e}")
         return

    print(f"✅ Migrated {len(rows)} entries from SQLite → Upstash Redis")

if __name__ == "__main__":
    migrate()
