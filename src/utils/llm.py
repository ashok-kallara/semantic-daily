"""Shared LLM client for Ollama and OpenRouter."""

from __future__ import annotations

import collections
import json
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

class LLMClient:
    """Client for LLM APIs (Ollama/OpenRouter)."""

    def __init__(self, config: dict[str, Any], role: str | None = None) -> None:
        self.provider: str = config.get("provider", "ollama")
        self.model: str = config.get("model", "llama3.2")
        
        if role and "roles" in config and role in config["roles"]:
            role_cfg = config["roles"][role]
            self.provider = role_cfg.get("provider", self.provider)
            self.model = role_cfg.get("model", self.model)
            
        self.base_url: str = config.get(
            "ollama_base_url", "http://host.docker.internal:11434"
        )
        self.openrouter_base: str = config.get(
            "openrouter_base_url", "https://openrouter.ai/api/v1"
        )
        self.openrouter_key: str = config.get("openrouter_api_key", "")
        self._ollama_client = None
        self._openrouter_client = None

    def _get_ollama_client(self):
        if self._ollama_client is None:
            import ollama
            self._ollama_client = ollama.AsyncClient(host=self.base_url)
        return self._ollama_client

    def _get_openrouter_client(self):
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

    async def generate(self, system_msg: str, prompt: str, max_tokens: int = 1500, temperature: float = 0.3) -> str | None:
        """Generate response from the configured LLM."""
        try:
            if self.provider == "ollama":
                client = self._get_ollama_client()
                response = await client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt},
                    ],
                    options={"temperature": temperature, "num_predict": max_tokens},
                )
                return response["message"]["content"]
            elif self.provider == "openrouter":
                client = self._get_openrouter_client()
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content if response.choices else None
        except Exception as exc:
            log.warning("llm.generate_error", provider=self.provider, error=str(exc))
            return None
        return None
