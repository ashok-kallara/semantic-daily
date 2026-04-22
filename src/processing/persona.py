"""Persona-driven relevance filter and query generator."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from src.models.article import Article
from src.utils.llm import LLMClient
from src.utils.logger import get_logger

log = get_logger(__name__)



SYSTEM_MSG_QUERY = """You are an expert AI configuration tool. 
Given a user's 'Persona' and 'Interests', generate highly targeted search queries, keywords, and handles to fetch relevant news and articles.
Consider specific subreddits, exact GitHub usernames, and YouTube channels if applicable.

Please output exactly a JSON object in this format (no markdown, no extra text):
{
  "exa": ["neural web search query 1", "neural web search query 2"],
  "twitter": ["keyword1", "keyword2"],
  "reddit": ["subreddit1", "subreddit2"],
  "youtube": ["youtube search query 1", "youtube search query 2"],
  "categories": ["🚀 Category 1", "🧠 Category 2", "... (generate exactly 10 broad categories covering the topics)"]
}

Make sure keywords and queries are highly specific to the given Persona and Interests."""


class PersonaProcessor:
    """Uses LLM to dynamically generate search config and evaluate articles."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.llm_generator = LLMClient(config.get("llm", {}), role="query_generator")
        self.llm_evaluator = LLMClient(config.get("llm", {}), role="evaluator")
        self.user_cfg = config.get("user", {})
        self.persona = self.user_cfg.get("persona", "")
        self.interests = self.user_cfg.get("interests", [])
        self.active_categories = [
            "🚀 Product Launches", "🧠 Research & Papers", "💼 Business & Strategy", 
            "🛠️ Tools & Dev", "🤖 AI Agents", "📈 Hardware", "🛡️ Safety & Policy", 
            "🔮 Ecosystem & Funding", "✨ General Updates", "🔥 Best Takes"
        ]

    @property
    def is_enabled(self) -> bool:
        return bool(self.persona and self.interests)

    async def expand_config(self, full_config: dict[str, Any]) -> None:
        """Modifies the full_config deeply by dynamically generating the source queries and appending them."""
        if not self.is_enabled:
            return

        log.info("persona.generating_queries", persona=self.persona)
        
        prompt = f"Persona: {self.persona}\nInterests: {', '.join(self.interests)}\n\nGenerate the JSON now:"
        try:
            response = await self.llm_generator.generate(SYSTEM_MSG_QUERY, prompt, max_tokens=2000)
            if not response:
                log.warning("persona.query_generation_empty")
                return

            response_clean = response.strip()
            match = re.search(r"\{.*\}", response_clean, re.DOTALL)
            if match:
                response_clean = match.group(0)
            
            data = json.loads(response_clean)
            
            # Apply to config (Supplemental appending)
            self.active_categories = data.get("categories", self.active_categories)
            if not isinstance(self.active_categories, list) or len(self.active_categories) == 0:
                self.active_categories = ["✨ General Updates"]
            # Enforce max 10 categories
            self.active_categories = self.active_categories[:10]
            log.info("persona.categories_generated", categories=self.active_categories)
            
            sources = full_config.setdefault("sources", {})
            if "exa" in data and isinstance(data["exa"], list):
                cfg = sources.setdefault("exa", {})
                cfg["queries"] = list(set(cfg.get("queries", []) + data["exa"]))
            if "twitter" in data and isinstance(data["twitter"], list):
                cfg = sources.setdefault("apify", {})
                cfg["twitter_keywords"] = list(set(cfg.get("twitter_keywords", []) + data["twitter"]))
            if "reddit" in data and isinstance(data["reddit"], list):
                cfg = sources.setdefault("apify", {})
                cfg["reddit_subreddits"] = list(set(cfg.get("reddit_subreddits", []) + data["reddit"]))
            if "youtube" in data and isinstance(data["youtube"], list):
                cfg = sources.setdefault("youtube", {})
                cfg["queries"] = list(set(cfg.get("queries", []) + data["youtube"]))

            log.info("persona.queries_generated_successfully", keys=list(data.keys()))
        except Exception as e:
            log.error("persona.query_generation_failed", error=str(e))

    def _build_eval_system_prompt(self) -> str:
        """Build the evaluation system prompt dynamically from active_categories."""
        cat_list_str = ", ".join('"' + c + '"' for c in self.active_categories)
        example_cat = self.active_categories[0] if self.active_categories else "General Updates"
        return (
            "You are an expert AI news judge scoring articles across three dimensions:\n"
            "1. Relevance (1-10): How valuable is this specific article to the provided Persona and Interests?\n"
            '2. Wit/Spicy (1-10): How much humor, cleverness, or "spicy" hot take energy does this article/snippet contain?\n'
            "3. Category (string): You MUST pick exactly ONE of these "
            + str(len(self.active_categories))
            + " exact categories: "
            + cat_list_str
            + ".\n\n"
            "Output exactly a JSON list of objects. DO NOT INCLUDE NOISE OR MARKDOWN. Example:\n"
            '[{"index": 0, "relevance": 8, "wit": 2, "category": "'
            + example_cat
            + '"}]'
        )

    async def evaluate_articles(self, articles: list[Article]) -> list[Article]:
        """Evaluates articles for relevance and wit, dropping irrelevant ones."""
        if not self.is_enabled or not articles:
            return articles

        log.info("persona.evaluating_articles", count=len(articles))
        
        batch_size = 5
        evaluated = []
        
        eval_prompt_base = self._build_eval_system_prompt()
        
        semaphore = asyncio.Semaphore(15)
        
        async def _eval_batch(batch: list[Article]) -> list[Article]:
            prompt = f"Persona: {self.persona}\nInterests: {', '.join(self.interests)}\n\nArticles to score:\n"
            for j, a in enumerate(batch):
                prompt += f"[{j}] Title: {a.title}\nContent: {(a.raw_content or '')[:300]}\n\n"
            
            async with semaphore:
                try:
                    response = await self.llm_evaluator.generate(eval_prompt_base, prompt, max_tokens=2500)
                    if not response:
                        log.warning("persona.evaluate_empty_response", batch_size=len(batch))
                        return batch
                    
                    response_clean = response.strip()
                    
                    scores = []
                    try:
                        match = re.search(r"\[.*\]", response_clean, re.DOTALL)
                        json_str = match.group(0) if match else response_clean
                        scores = json.loads(json_str)
                    except Exception as e:
                        log.warning("persona.json_salvage_mode", error=str(e))
                        # Salvage individual complete objects if the array is truncated
                        for obj_str in re.findall(r"\{[^{}]*\}", response_clean):
                            try:
                                scores.append(json.loads(obj_str))
                            except Exception:
                                pass
                    
                    batch_evaluated = []
                    for score_data in scores:
                        idx = score_data.get("index", -1)
                        rel = score_data.get("relevance", 0)
                        wit = score_data.get("wit", 0)
                        raw_cat = score_data.get("category", "✨ General Updates")
                        
                        valid_cats = self.active_categories
                        cat = raw_cat if raw_cat in valid_cats else (valid_cats[-1] if valid_cats else "✨ General Updates")
                        
                        if 0 <= idx < len(batch):
                            article = batch[idx]
                            # Discard heavily irrelevant articles
                            if rel >= 5:
                                article.score = max(article.score, rel) # embed the relevance score
                                article.category = cat
                                
                                # Add a custom tag if it's very witty to be used during summarization
                                if wit >= 8:
                                    article.category = "🔥 Best Takes"
                                
                                batch_evaluated.append(article)
                    return batch_evaluated

                except Exception as e:
                    log.warning("persona.evaluating_failed_for_batch", error=str(e))
                    # Fallback: keep them all if generation failed
                    return batch

        tasks = []
        for i in range(0, len(articles), batch_size):
            batch = articles[i:i+batch_size]
            tasks.append(_eval_batch(batch))
            
        results = await asyncio.gather(*tasks)
        for res in results:
            evaluated.extend(res)

        log.info("persona.evaluated", original=len(articles), remaining=len(evaluated))
        return evaluated
