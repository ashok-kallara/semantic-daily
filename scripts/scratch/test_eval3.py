import asyncio
from src.utils.config import load_config
from src.utils.llm import LLMClient

async def main():
    config = load_config("config/config.toml")
    client = LLMClient(config.get("llm", {}))
    
    prompt = "Persona: A senior AI leader\nInterests: Open source large language models\n\nArticles:\n[0] Title: Good\nContent: Good\n\n"
    system_msg = "You are an expert AI news judge scoring articles... Output exactly JSON with index, relevance, wit, category."
    
    # Try the raw completion
    api_client = client._get_openrouter_client()
    try:
        response = await api_client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=250,
        )
        print("OPENROUTER RESPONSE:")
        print(repr(response))
    except Exception as e:
        print("EXCEPTION RAISED:")
        print(repr(e))

asyncio.run(main())
