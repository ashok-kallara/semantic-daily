"""LLM-powered article summarization with Ollama and OpenRouter support."""

from __future__ import annotations

import asyncio
from typing import Any

from src.models.article import Article
from src.utils.logger import get_logger

log = get_logger(__name__)

SUMMARY_PROMPT = """Summarize this news article in 1-2 concise sentences (max {max_len} characters).
Focus on: what happened, why it matters, who's involved.
Do NOT include any preamble like "Here is a summary" — just the summary text.

Title: {title}
Content: {content}"""

SYSTEM_MSG = "You are a concise news summarizer. Output ONLY the summary, nothing else."


class Summarizer:
    """Generates short summaries for articles using Ollama or OpenRouter.

    Providers:
      - ollama: Local LLM via Ollama (free, requires ollama serve on host)
      - openrouter: Cloud LLMs via OpenRouter (OpenAI-compatible API, pay-per-token)

    Falls back to simple truncation if the LLM is unavailable.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.provider: str = config.get("provider", "ollama")
        self.model: str = config.get("model", "llama3.2")
        
        if "roles" in config and "summarizer" in config["roles"]:
            role_cfg = config["roles"]["summarizer"]
            self.provider = role_cfg.get("provider", self.provider)
            self.model = role_cfg.get("model", self.model)
            
        self.base_url: str = config.get(
            "ollama_base_url", "http://host.docker.internal:11434"
        )
        self.openrouter_base: str = config.get(
            "openrouter_base_url", "https://openrouter.ai/api/v1"
        )
        self.openrouter_key: str = config.get("openrouter_api_key", "")
        self.max_len: int = config.get("max_summary_length", 280)
        self.batch_size: int = config.get("batch_size", 10)
        self.fallback_len: int = config.get("fallback_truncate_length", 200)
        self.user_cfg: dict[str, Any] = config.get("user", {})
        self.persona: str = self.user_cfg.get("persona", "")
        self.interests: list[str] = self.user_cfg.get("interests", [])
        
        self._ollama_client = None
        self._openrouter_client = None

    def _get_ollama_client(self):
        """Lazy-init the Ollama client."""
        if self._ollama_client is None:
            import ollama

            self._ollama_client = ollama.AsyncClient(host=self.base_url)
        return self._ollama_client

    def _get_openrouter_client(self):
        """Lazy-init the OpenRouter client (OpenAI-compatible)."""
        if self._openrouter_client is None:
            from openai import AsyncOpenAI

            self._openrouter_client = AsyncOpenAI(
                base_url=self.openrouter_base,
                api_key=self.openrouter_key,
                default_headers={
                    "HTTP-Referer": "https://github.com/semantic-daily-bot",
                    "X-Title": "News Feed Aggregator",
                },
            )
        return self._openrouter_client

    async def summarize_articles(
        self, articles: list[Article]
    ) -> list[Article]:
        """Add summaries to all articles. Processes in batches."""
        if not articles:
            return articles

        log.info(
            "summarizer.start",
            provider=self.provider,
            model=self.model,
            article_count=len(articles),
        )

        # Process in batches to respect rate limits
        for i in range(0, len(articles), self.batch_size):
            batch = articles[i : i + self.batch_size]
            tasks = [self._summarize_one(article) for article in batch]
            await asyncio.gather(*tasks)

        success = sum(1 for a in articles if a.summary)
        fallback = len(articles) - success
        log.info(
            "summarizer.complete",
            success=success,
            fallback=fallback,
        )

        return articles

    async def _summarize_one(self, article: Article) -> None:
        """Summarize a single article, with fallback on failure."""
        try:
            content = article.raw_content or article.title
            prompt = SUMMARY_PROMPT.format(
                max_len=self.max_len,
                title=article.title,
                content=content[:2000],  # Cap input length
            )
            sys_msg = SYSTEM_MSG
            if self.persona:
                sys_msg += f"\nTailor the summary specifically for this Persona: {self.persona}. "
                sys_msg += f"Focus on how it relates to these interests: {', '.join(self.interests)}."
                
            if article.category == "🔥 Best Takes":
                prompt = f"Extract the funniest, most clever, or spiciest direct quote/take from this text. Keep it brief.\n\nTitle: {article.title}\nContent: {content[:2000]}"
                sys_msg = "You are a witty news curator. Output only the best take or quote, nothing else."

            if self.provider == "ollama":
                summary = await self._ollama_generate(prompt, sys_msg)
            elif self.provider == "openrouter":
                summary = await self._openrouter_generate(prompt, sys_msg)
            else:
                log.warning("summarizer.unknown_provider", provider=self.provider)
                summary = None

            if summary:
                # Enforce max length
                if len(summary) > self.max_len:
                    summary = summary[: self.max_len - 3].rsplit(" ", 1)[0] + "..."
                article.summary = summary
            else:
                article.summary = self._fallback_summary(article)

        except Exception as exc:
            log.debug(
                "summarizer.article_error",
                title=article.title[:60],
                error=str(exc),
            )
            article.summary = self._fallback_summary(article)

    async def _ollama_generate(self, prompt: str, system_msg: str) -> str | None:
        """Call local Ollama instance for generation."""
        try:
            client = self._get_ollama_client()
            response = await client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.3, "num_predict": 150},
            )
            return self._clean_summary(response["message"]["content"])

        except Exception as exc:
            log.warning("summarizer.ollama_error", error=str(exc))
            return None

    async def _openrouter_generate(self, prompt: str, system_msg: str) -> str | None:
        """Call OpenRouter API (OpenAI-compatible) for generation."""
        try:
            client = self._get_openrouter_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
            )
            content = response.choices[0].message.content if response.choices else None
            return self._clean_summary(content) if content else None

        except Exception as exc:
            log.warning("summarizer.openrouter_error", error=str(exc))
            return None

    @staticmethod
    def _clean_summary(text: str) -> str | None:
        """Strip common LLM preamble patterns from a summary."""
        text = text.strip()
        for prefix in [
            "Here is a summary:",
            "Summary:",
            "Here's a summary:",
        ]:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix) :].strip()
        return text if text else None

    def _fallback_summary(self, article: Article) -> str:
        """Simple truncation fallback when LLM is unavailable."""
        text = article.raw_content or article.title
        if len(text) <= self.fallback_len:
            return text
        return text[: self.fallback_len].rsplit(" ", 1)[0] + "..."

    async def health_check(self) -> bool:
        """Check if the configured LLM provider is reachable."""
        if self.provider == "ollama":
            return await self._ollama_health()
        elif self.provider == "openrouter":
            return await self._openrouter_health()
        return False

    async def _ollama_health(self) -> bool:
        try:
            client = self._get_ollama_client()
            models = await client.list()
            available = [m.get("name", "") for m in models.get("models", [])]
            log.info(
                "summarizer.health_ok",
                provider="ollama",
                models_available=len(available),
                target_model=self.model,
                model_found=self.model in str(available),
            )
            return True
        except Exception as exc:
            log.warning("summarizer.health_fail", provider="ollama", error=str(exc))
            return False

    async def _openrouter_health(self) -> bool:
        try:
            client = self._get_openrouter_client()
            models = await client.models.list()
            log.info(
                "summarizer.health_ok",
                provider="openrouter",
                models_available=len(models.data) if models.data else 0,
            )
            return True
        except Exception as exc:
            log.warning("summarizer.health_fail", provider="openrouter", error=str(exc))
            return False
