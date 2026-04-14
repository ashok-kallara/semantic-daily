import asyncio
from src.utils.config import load_config
from src.processing.persona import PersonaProcessor
from src.models.article import Article, Source

async def main():
    config = load_config("config/config.toml")
    pp = PersonaProcessor(config)
    articles = [
        Article(title="Good", url="http://x.com", source=Source.APIFY_X, raw_content="Good"),
        Article(title="AI Model Breakthrough", url="http://example.com", source=Source.EXA, raw_content="New agentic framework released today by OpenAI"),
    ]
    res = await pp.evaluate_articles(articles)
    print("EVALUATED COUNT:", len(res))
    for a in res:
        print(f"TITLE: {a.title} | CAT: {a.category} | SCORE: {a.score}")

asyncio.run(main())
