# 📰 Semantic Daily

A **100% free** agentic news aggregator that discovers trending AI & technology content from Native APIs (**Reddit**, **Bluesky**, **GitHub**, **RSS**, **HackerNews**, **YouTube**, and **Exa.ai**) — deduplicates, categorizes using a multi-agent LLM pipeline over OpenRouter, and delivers a curated daily digest directly to your **Telegram** or as a **Web Dashboard**.

---

## 📑 Table of Contents

- [✨ Features](#-features)
- [🏗️ Architecture](#️-architecture)
- [📁 Project Structure](#-project-structure)
- [🚀 Quick Start](#-quick-start)
- [⚙️ Configuration](#️-configuration)
- [🔒 Security](#-security)
- [📬 Sample Digest Output](#-sample-digest-output)
- [🔧 CLI Reference](#-cli-reference)
- [📄 License](#-license)

---

## ✨ Features

- **7 Native Content Sources** — Reddit API, Bluesky AT Protocol, GitHub trending repos, RSS Feeds, HackerNews, YouTube, and Exa.ai neural search. No paid scraper SaaS tools required.
- **Agentic Multi-Model Pipeline** — Uses `kimi-k2.5` to intelligently invent deep search queries based on your Persona, and `claude-3.5-haiku` to categorize, grade, and structure the articles.
- **Smart Deduplication** — 3-layer engine: URL normalization → fuzzy title matching (Jaro-Winkler) → historical SQLite cache.
- **Dual Delivery Modes** — 
  1. **Telegram:** Rich HTML delivery natively sent to your chat.
  2. **Static Web Generation:** The pipeline automatically behaves as a Static Site Generator, outputting a high-quality Glassmorphism HTML layout to `public/` that is automatically deployed to the edge via **Surge.sh**!
- **Single config file** — Everything in one local `config.toml` (no `.env` needed)
- **uv-managed** — Modern Python dependency management with `uv`

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  ⏰ ScheduleTrigger (e.g. Cron)                             │
│    │                                                        │
│    │  [1] Persona Query Generation (Kimi-k2.5)              │
│    ▼                                                        │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                     NATIVE SCRAPERS                   │  │
│  │ ┌──────┐ ┌──────┐ ┌────────┐ ┌──────┐ ┌──────┐ ┌────┐ │  │
│  │ │ Exa  │ │Reddit│ │Bluesky │ │Github│ │  RSS │ │ HN │ │  │
│  │ └──────┘ └──────┘ └────────┘ └──────┘ └──────┘ └────┘ │  │
│  └──────────────────────────┬────────────────────────────┘  │
│                             ▼                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Deduplicator (SQLite seen_articles.db + Jaro Math)   │  │
│  └──────────────────────────┬────────────────────────────┘  │
│                             ▼                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Categorizer LLM (Claude-3.5-Haiku JSON)              │  │
│  └──────────────────────────┬────────────────────────────┘  │
│                             ▼                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Summarizer LLM (OpenRouter fallback)                 │  │
│  └────┬──────────────────────────────────────────────┬───┘  │
│       ▼                                              ▼      │
│  ┌──────────────┐                        ┌───────────────┐  │
│  │  Telegram    │                        │ Web Publisher │  │
│  │ Rich Message │                        │ (Static HTML) │  │
│  └──────────────┘                        └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
semantic-daily/
├── pyproject.toml                # uv project manifest + dependencies
├── config/
│   ├── config.example.toml       # Template — copy to config.toml
│   └── config.toml               # ← YOUR config (git-ignored, has API keys)
│
├── src/
│   ├── main.py                   # Pipeline orchestrator (entry point)
│   ├── models/
│   │   └── article.py            # Article, Digest, Source Enum
│   ├── collectors/
│   │   ├── base.py               # Abstract base collector
│   │   ├── exa.py                # Exa.ai neural search
│   │   ├── hackernews.py         # HN via Firebase API
│   │   ├── reddit.py             # Reddit Native Search
│   │   ├── bluesky.py            # Bluesky AT Firehose
│   │   ├── github.py             # GitHub Trending Data
│   │   ├── rss.py                # Generic RSS Parser
│   │   └── youtube.py            # YouTube Data API
│   ├── processing/
│   │   ├── dedup.py              # URL normalization + cache
│   │   ├── persona.py            # Mult-Model Generative AI Prompts
│   │   └── summarizer.py         # 1 sentence article reduction
│   ├── delivery/
│   │   ├── telegram.py           # Rich Telegram Delivery
│   │   └── web.py                # Ultra-dense Glassmorphism UI Builder
│   └── utils/
│       ├── config.py             # TOML config loader
│       └── cache.py              # SQLite dedup cache
│
├── public/                       # Generated Static Digest Web Output!
└── scripts/                      # Utility runners and scratchpads
```

---

## 🚀 Quick Start

### Prerequisites
*   **uv** package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### 1. Clone & Configure
```bash
git clone <your-repo-url> semantic-daily
cd semantic-daily
cp config/config.example.toml config/config.toml
```

### 2. Add API Keys
The beauty of the V2 Pipeline is that **virtually all collectors are completely free.** You only need keys for the specific things you want:
- `openrouter_api_key`: Required for LLM categorization.
- `exa_api_key`: (Optional) Required if you want Neural Web Searches. 
- `bot_token`/`chat_id`: (Optional) Required if you want Telegram output instead of just Web HTML.

### 3. Run Locally
```bash
uv sync --dev

# Dry-run: Collect, run LLMs, Print to terminal, and render HTML locally
uv run python -m src.main --dry-run
open public/index.html   # Immediately view the beautiful digest UX

# Full run: Same as above but pushes to Telegram and permanently modifies SQLite cache
uv run python -m src.main
```

---

## ⚙️ Configuration

Your `config.toml` acts as the mastermind for the entire operation.

### The Persona
The query generator reads your persona and dynamically creates highly-targeted search phrases across all social media and web targets!
```toml
[user]
persona = "A senior AI leader looking for latest papers, bleeding edge and cutting edge AI trends and real-world implementations"
interests = ["RAG architectures", "Agentic Workflows"]
```

### Multi-Model LLM Matrix
We explicitly map different models to different cognitive roles to optimize performance and cost:
```toml
[llm]
provider = "openrouter"
openrouter_api_key = "sk-or-x..."

[llm.roles.evaluator]
model = "anthropic/claude-3.5-haiku"  # Fast, flawless JSON parsing

[llm.roles.query_generator]
model = "moonshotai/kimi-k2.5"        # Exceptional complex search reasoning
```

### Web Publishing Details
The pipeline outputs `public/News-digest-<slug>-YYYY-MM-DD.html`.
It automatically deploys this directory to the web using **Surge.sh**. Provide your base domain in `config.toml`, and set `SURGE_LOGIN` and `SURGE_TOKEN` environment variables so the script can smoothly deploy without prompts. The pipeline specifically creates an `index.html` file alongside the digest that auto-redirects mobile/desktop visitors to the most recently generated digest. 



## 🔧 CLI Reference

```bash
# Full execution (Scrape -> Process -> Save DB -> Telegram + Surge Deploy)
uv run python -m src.main

# Dry run (No Telegram execution, but DOES output HTML preview)
uv run python -m src.main --dry-run

# Test Telegram connectivity directly
uv run python -m src.main --test-telegram

# Standalone command to ONLY deploy the existing public/ folder to Surge.sh
uv run publish-surge

# Standalone command to send the latest generated HTML digest as a Telegram file
uv run publish-telegram
```

---

## 📄 License

Apache 2.0 — feel free to use, modify, and distribute.
