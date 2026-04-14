"""Telegram delivery — sends basic notifications."""

from __future__ import annotations

from typing import Any
from src.utils.logger import get_logger

log = get_logger(__name__)


class TelegramSender:
    """Sends simple notification messages via the Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str, config: dict[str, Any]) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._config = config
        self._bot = None

    async def _get_bot(self):
        if self._bot is None:
            from telegram import Bot
            self._bot = Bot(token=self._token)
        return self._bot

    async def send_text(self, text: str) -> bool:
        """Send a simple text message (like the digest link)."""
        try:
            bot = await self._get_bot()
            await bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            log.info("telegram.link_sent")
            return True
        except Exception as exc:
            log.error("telegram.send_text_error", error=str(exc))
            return False

    async def send_document(self, document_path: str | Path, caption: str = "") -> bool:
        """Send a document file (like the html file) with an optional caption."""
        from pathlib import Path
        try:
            bot = await self._get_bot()
            with open(Path(document_path), 'rb') as doc:
                await bot.send_document(
                    chat_id=self._chat_id,
                    document=doc,
                    caption=caption,
                    parse_mode="HTML"
                )
            log.info("telegram.document_sent", path=str(document_path))
            return True
        except Exception as exc:
            log.error("telegram.send_document_error", error=str(exc))
            return False

    async def health_check(self) -> bool:
        """Verify bot token and chat_id are valid."""
        try:
            bot = await self._get_bot()
            me = await bot.get_me()
            log.info("telegram.health_ok", bot_name=me.username)
            return True
        except Exception as exc:
            log.warning("telegram.health_fail", error=str(exc))
            return False


def send_latest_cli() -> None:
    """Standalone CLI to send the latest generated HTML digest as a Telegram message."""
    import argparse
    import asyncio
    import sys
    from pathlib import Path
    from src.utils.config import load_config

    parser = argparse.ArgumentParser(description="Send latest digest via Telegram")
    parser.add_argument("--config", default="config/config.toml")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"Error: {args.config} not found.", file=sys.stderr)
        sys.exit(1)

    tg_cfg = config.get("telegram", {})
    token = tg_cfg.get("bot_token", "")
    chat_id = str(tg_cfg.get("chat_id", ""))
    
    if not token or not chat_id:
        print("❌ Telegram bot_token or chat_id not configured.", file=sys.stderr)
        sys.exit(1)

    public_dir = Path("public")
    if not public_dir.exists():
        print("❌ No public directory found. Have you generated a digest yet?", file=sys.stderr)
        sys.exit(1)

    html_files = list(public_dir.glob("News-digest-*.html"))
    if not html_files:
        print("❌ No HTML digests found in public/.", file=sys.stderr)
        sys.exit(1)

    # Sort by modification time to get the latest
    latest_html = max(html_files, key=lambda p: p.stat().st_mtime)

    sender = TelegramSender(token, chat_id, tg_cfg)
    
    web_cfg = config.get("web", {})
    base_url = web_cfg.get("surge_domain", "semantic-daily.surge.sh").rstrip("/")
    if base_url and not base_url.startswith("http"):
        base_url = f"https://{base_url}"
        
    link = f"{base_url}/{latest_html.name}"
    header = tg_cfg.get("digest_header", "📰 Semantic Daily")
    
    msg = f"✅ <b>{header}</b>\n\nYour latest web digest is ready! Discover the bleeding edge trends right here:\n<a href='{link}'>{link}</a>"

    async def _send():
        print(f"🚀 Sending '{latest_html.name}' to Telegram...", end=" ")
        # Sending as a document allows them to download the raw HTML file or view it directly in app
        success = await sender.send_document(latest_html, caption=msg)
        if success:
            print("✅ Done!")
        else:
            print("❌ Failed.")
            sys.exit(1)

    asyncio.run(_send())

