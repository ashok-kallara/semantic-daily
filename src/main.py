"""Main pipeline orchestrator — collects, deduplicates, summarizes, and delivers."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.collectors.exa import ExaCollector
from src.collectors.hackernews import HackerNewsCollector
from src.collectors.listennotes import ListenNotesCollector
from src.collectors.youtube import YouTubeCollector
from src.collectors.reddit import RedditCollector
from src.collectors.bluesky import BlueskyCollector
from src.collectors.rss import RSSCollector
from src.collectors.github import GitHubCollector
from src.delivery.telegram import TelegramSender
from src.delivery.web import HTMLPublisher
from src.models.article import Article, Digest
from src.processing.dedup import Deduplicator, normalize_url
from src.processing.persona import PersonaProcessor
from src.processing.summarizer import Summarizer
from src.utils.cache import ArticleCache
from src.utils.config import load_config
from src.utils.logger import get_logger, setup_logging

log = get_logger(__name__)



async def run_pipeline(
    config: dict[str, Any],
    dry_run: bool = False,
    test_telegram: bool = False,
) -> Digest:
    """Execute the full news aggregation pipeline.

    1. Collect from all enabled sources
    2. Categorize articles
    3. Deduplicate (URL + title + cache)
    4. Summarize via LLM
    5. Deliver via Telegram
    """
    log.info("pipeline.start", dry_run=dry_run)

    # --- Initialize components ---
    dedup_cfg = config.get("dedup", {})
    db_path = dedup_cfg.get("db_path", "data/seen_articles.db")
    cache = ArticleCache(Path(db_path))
    cache.prune_old(days=dedup_cfg.get("cache_ttl_days", 7))

    # --- 0. Dynamic Configuration via Persona ---
    persona_processor = PersonaProcessor(config)
    await persona_processor.expand_config(config)

    # --- 1. Collect ---
    collectors = []
    sources = config.get("sources", {})

    # Exa.ai — neural search (primary web content discovery)
    exa_cfg = sources.get("exa", {})
    if exa_cfg.get("enabled", False):
        collectors.append(ExaCollector(exa_cfg))

    # HackerNews — Firebase API (kept from original)
    hn_cfg = sources.get("hackernews", {})
    if hn_cfg.get("enabled", False):
        collectors.append(HackerNewsCollector(hn_cfg))

    # Reddit - Free .json API
    reddit_cfg = sources.get("reddit", {})
    if reddit_cfg.get("enabled", False):
        collectors.append(RedditCollector(reddit_cfg))

    # Bluesky - AT Protocol public search
    bluesky_cfg = sources.get("bluesky", {})
    if bluesky_cfg.get("enabled", False):
        collectors.append(BlueskyCollector(bluesky_cfg))

    # RSS - Tech feeds
    rss_cfg = sources.get("rss", {})
    if rss_cfg.get("enabled", False):
        collectors.append(RSSCollector(rss_cfg))

    # GitHub - Trending repos
    gh_cfg = sources.get("github", {})
    if gh_cfg.get("enabled", False):
        collectors.append(GitHubCollector(gh_cfg))

    # YouTube — popular videos
    yt_cfg = sources.get("youtube", {})
    if yt_cfg.get("enabled", False):
        collectors.append(YouTubeCollector(yt_cfg))

    if not collectors:
        log.warning("pipeline.no_collectors_enabled")
        return Digest()

    # Run all collectors concurrently
    all_articles: list[Article] = []
    results = await asyncio.gather(
        *[c.collect() for c in collectors], return_exceptions=True
    )
    sources_used = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error(
                "pipeline.collector_exception",
                collector=collectors[i].source_name,
                error=str(result),
            )
        elif isinstance(result, list):
            all_articles.extend(result)
            if result:
                sources_used.append(collectors[i].source_name)

    log.info("pipeline.collected", total=len(all_articles), sources=sources_used)
    _save_intermediate("1_collected", all_articles)

    if not all_articles:
        log.warning("pipeline.no_articles")
        return Digest(sources_used=sources_used)

    # --- 2. Deduplicate ---
    dedup = Deduplicator(dedup_cfg, cache)
    total_before = len(all_articles)
    deduped = dedup.deduplicate(all_articles)
    dupes_removed = total_before - len(deduped)
    _save_intermediate("2_deduplicated", deduped)

    # --- 3. Persona Evaluation, Filtering & Dynamic Categorization ---
    deduped = await persona_processor.evaluate_articles(deduped)
    _save_intermediate("3_evaluated", deduped)

    # --- 4. Summarize ---
    # Cap articles per category before summarization to keep digest concise
    max_per_cat = config.get("web", {}).get("max_articles_per_category", 25)
    max_per_author = config.get("collection", {}).get("max_per_author", 3)
    
    grouped = {}
    for a in deduped:
        grouped.setdefault(a.category, []).append(a)

    curated_articles = []
    for cat, items in grouped.items():
        # Group by source to ensure diversity
        by_source = {}
        for item in items:
            by_source.setdefault(item.source, []).append(item)
            
        for src_items in by_source.values():
            src_items.sort(key=lambda x: x.engagement_score, reverse=True)
            
        cat_curated = []
        author_counts = {}
        while by_source and len(cat_curated) < max_per_cat:
            for src in list(by_source.keys()):
                if len(cat_curated) >= max_per_cat:
                    break
                if by_source[src]:
                    candidate = by_source[src].pop(0)
                    auth_key = candidate.author or candidate.source_detail or "unknown"
                    if author_counts.get(auth_key, 0) < max_per_author:
                        author_counts[auth_key] = author_counts.get(auth_key, 0) + 1
                        cat_curated.append(candidate)
                else:
                    del by_source[src]
                    
        # Sort the final curated mix by engagement score for nice rendering
        cat_curated.sort(key=lambda x: x.engagement_score, reverse=True)
        curated_articles.extend(cat_curated)

    _save_intermediate("4_curated", curated_articles)

    llm_cfg = config.get("llm", {})
    summarizer = Summarizer(llm_cfg)
    summarized = await summarizer.summarize_articles(curated_articles)

    # --- 5. Build digest ---
    digest = Digest(
        date=datetime.now(timezone.utc),
        articles=summarized,
        total_collected=total_before,
        duplicates_removed=dupes_removed,
        sources_used=sources_used,
    )

    log.info(
        "pipeline.digest_ready",
        articles=digest.article_count,
        categories=len(digest.by_category),
        duplicates_removed=dupes_removed,
    )

    # --- 6. Deliver ---
    
    # Render Web HTML (always render to keep docs up to date)
    web_publisher = HTMLPublisher(config)
    
    if dry_run:
        log.info("pipeline.dry_run_skip_delivery")
        await web_publisher.publish(digest)
        _print_digest_preview(digest)
    elif test_telegram:
        telegram = _build_telegram(config)
        if telegram:
            await telegram.send_text(
                "🧪 <b>Test message</b> — Telegram integration is working!"
            )
    else:
        # Publish HTML to docs/public folder
        html_path = await web_publisher.publish(digest)
        
        # Deploy to Surge.sh
        try:
            log.info("pipeline.deploying_to_surge")
            surge_domain = config.get("web", {}).get("surge_domain", "semantic-daily.surge.sh")
            # Surge uses SURGE_LOGIN and SURGE_TOKEN from the environment
            subprocess.run(
                ["npx", "--yes", "surge", "./public", surge_domain],
                check=True,
                capture_output=True,
                text=True
            )
            log.info("pipeline.surge_deploy_success", domain=surge_domain)
        except subprocess.CalledProcessError as e:
            log.warning("pipeline.surge_deploy_failed", error=e.stderr)
        except Exception as e:
            log.warning("pipeline.surge_deploy_failed", error=str(e))
        
        # Mark articles as seen in the database so they never appear in future digests
        cache.mark_batch_seen(
            [(normalize_url(a.url), a.title, a.source) for a in summarized]
        )
        log.info("pipeline.cache_updated", marked_seen=len(summarized))

        telegram = _build_telegram(config)
        if telegram:
            web_cfg = config.get("web", {})
            base_url = web_cfg.get("surge_domain", "semantic-daily.surge.sh").rstrip("/")
            if base_url and not base_url.startswith("http"):
                base_url = f"https://{base_url}"
            
            if base_url:
                # Send just the link
                link = f"{base_url}/{html_path.name}"
                header = config.get("telegram", {}).get("digest_header", "📰 Semantic Daily")
                msg = f"✅ <b>{header}</b>\n\nYour latest web digest is ready! Discover the bleeding edge trends and {digest.article_count} new curated articles right here:\n<a href='{link}'>{link}</a>"
                await telegram.send_text(msg)
            else:
                log.warning("pipeline.telegram_link_skipped_no_base_url")
        else:
            log.info("pipeline.telegram_not_configured_skipping_telegram")

    log.info("pipeline.complete")
    return digest


def _save_intermediate(name: str, articles: list[Article]) -> None:
    """Save raw article data to a JSON file for debugging and validation."""
    debug_dir = Path("data/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    filepath = debug_dir / f"{name}.json"
    
    out = [a.model_dump(mode="json") for a in articles]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


def _build_telegram(config: dict[str, Any]) -> TelegramSender | None:
    """Build a TelegramSender from config."""
    tg_cfg = config.get("telegram", {})
    token = tg_cfg.get("bot_token", "")
    chat_id = str(tg_cfg.get("chat_id", ""))
    if not token or not chat_id:
        return None
    return TelegramSender(token, chat_id, tg_cfg)


def _print_digest_preview(digest: Digest) -> None:
    """Print a preview of the digest to stdout AND save to a file."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append(f"  DIGEST PREVIEW — {digest.date.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"  {digest.article_count} articles, {digest.duplicates_removed} dupes removed")
    lines.append(f"  Sources: {', '.join(digest.sources_used)}")
    lines.append("=" * 60)

    for cat, articles in digest.by_category.items():
        lines.append(f"\n  {cat}")
        lines.append("  " + "-" * 40)
        for i, a in enumerate(articles, 1):
            media = {"video": "🎬", "podcast": "🎙️", "article": "📰"}.get(
                a.media_type, "📰"
            )
            score_str = f" [{a.engagement_score}⬆]" if a.engagement_score else ""
            src = f" ({a.source_detail})" if a.source_detail else ""
            duration = f" [{a.duration_display}]" if a.duration_display else ""
            lines.append(f"  {i}. {media} {a.title[:100]}{score_str}{src}{duration}")
            if a.summary:
                lines.append(f"     → {a.summary[:200]}")
            lines.append(f"     🔗 {a.url}")

    lines.append("\n" + "=" * 60)

    # Print to stdout
    output = "\n".join(lines)
    print("\n" + output + "\n")

    # Save to file
    digest_dir = Path("data/digests")
    digest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"digest_{digest.date.strftime('%Y-%m-%d_%H%M')}.txt"
    filepath = digest_dir / filename
    filepath.write_text(output, encoding="utf-8")

    log.info("pipeline.dry_run_saved", path=str(filepath))
    print(f"  💾 Saved to: {filepath}\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Daily News Feed Aggregator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and process but don't send to Telegram",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test message to verify Telegram integration",
    )
    parser.add_argument(
        "--config",
        default="config/config.toml",
        help="Path to config TOML file",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Setup logging from config
    log_cfg = config.get("logging", {})
    setup_logging(level=log_cfg.get("level", "INFO"))

    asyncio.run(
        run_pipeline(
            config,
            dry_run=args.dry_run,
            test_telegram=args.test_telegram,
        )
    )


if __name__ == "__main__":
    main()
