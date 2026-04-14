import asyncio
from src.utils.config import load_config
from src.processing.persona import PersonaProcessor
from src.models.article import Article, Source
import json

async def main():
    config = load_config("config/config.toml")
    pp = PersonaProcessor(config)
    prompt = "Persona: A senior AI leader\nInterests: Open source large language models\n\nArticles:\n[0] Title: Good\nContent: Good\n\n"
    res = await pp.llm_client.generate("You are an expert AI news judge scoring articles... Output exactly JSON with index, relevance, wit, category.", prompt, max_tokens=250)
    print("RAW RESPONSE Kimi:")
    print(repr(res))

asyncio.run(main())
