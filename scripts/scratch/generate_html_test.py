import asyncio
import json
from pathlib import Path

from src.delivery.web import HTMLPublisher
from src.models.article import Article, Digest
from src.utils.config import load_config

async def main():
    config = load_config()
    
    # Load the evaluated JSON items saved by the pipeline right before summarization
    curated_path = Path("data/debug/4_curated.json")
    if not curated_path.exists():
        print(f"File not found: {curated_path}")
        return
        
    with open(curated_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    articles = [Article.model_validate(item) for item in data]
    
    # Create a mock digest object
    digest = Digest(
        articles=articles,
        total_collected=613,      # Based on logs
        duplicates_removed=286,   # Based on logs
        sources_used=["exa", "hackernews", "reddit", "rss", "github", "youtube"]
    )
    
    publisher = HTMLPublisher(config)
    path = await publisher.publish(digest)
    print(f"✅ Success! HTML generated at: {path}")

if __name__ == "__main__":
    asyncio.run(main())
