import asyncio
from src.utils.config import load_config
from src.collectors.exa import ExaCollector
from src.utils.logger import setup_logging

async def main():
    setup_logging(level="DEBUG")
    config = load_config("config/config.toml")
    exa_cfg = config.get("sources", {}).get("exa", {})
    collector = ExaCollector(exa_cfg)
    res = await collector.collect()
    print("FINISHED:", len(res))

asyncio.run(main())
