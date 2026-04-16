"""HTML Web Publisher for generating static visual digests."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models.article import Article, Digest
from src.utils.logger import get_logger

log = get_logger(__name__)

# Premium glassmorphism dark-mode CSS snippet
CSS_STYLES = """
:root {
    --bg-color: #0d1117;
    --card-bg: rgba(22, 27, 34, 0.4);
    --hover-bg: rgba(46, 52, 60, 0.6);
    --border: rgba(255, 255, 255, 0.08);
    --text-main: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --accent-glow: rgba(88, 166, 255, 0.15);
    --font-sans: 'Inter', system-ui, sans-serif;
    --font-mono: 'Fira Code', ui-monospace, monospace;
}

body {
    background-color: var(--bg-color);
    color: var(--text-main);
    font-family: var(--font-sans);
    margin: 0;
    padding: 0;
    line-height: 1.4;
    background-image: radial-gradient(circle at top right, rgba(46, 160, 67, 0.05), transparent 400px),
                      radial-gradient(circle at bottom left, var(--accent-glow), transparent 400px);
    background-attachment: fixed;
}

.container { max-width: 1100px; margin: 0 auto; padding: 2rem 1rem; }

header {
    border-bottom: 1px solid var(--border);
    padding-bottom: 1rem;
    margin-bottom: 2rem;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
}

.title { font-size: 2rem; font-weight: 700; margin: 0 0 0.25rem 0; }
.subtitle { color: var(--text-muted); font-size: 0.95rem; }

.stats-bar {
    display: flex; gap: 1.5rem; font-family: var(--font-mono); font-size: 0.85rem; text-align: right;
}
.stat { display: flex; flex-direction: column; }
.stat span:first-child { color: var(--text-muted); font-size: 0.75rem; }
.stat span:last-child { color: var(--accent); font-weight: 600; }

/* Tabs styling */
.tabs-container {
    margin-bottom: 2rem; display: flex; gap: 1rem;
    border-bottom: 1px solid var(--border); padding-bottom: 0.5rem;
}

.tab-btn {
    background: transparent; border: none; color: var(--text-muted);
    font-family: var(--font-sans); font-size: 1.1rem; font-weight: 500;
    cursor: pointer; padding: 0.5rem 1rem; border-radius: 6px; transition: all 0.2s ease;
}

.tab-btn:hover { color: var(--text-main); background: rgba(255, 255, 255, 0.05); }
.tab-btn.active { color: var(--accent); background: rgba(88, 166, 255, 0.1); font-weight: 600; }

.tab-content { display: none; animation: fadeIn 0.3s ease; }
.tab-content.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

/* Common card styling */
.category-group {
    margin-bottom: 2rem; background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden; backdrop-filter: blur(8px);
}

/* Express View Accordion */
.accordion-header {
    width: 100%; display: flex; justify-content: space-between; align-items: center;
    background: rgba(255,255,255,0.03); border: none; border-bottom: 1px solid var(--border);
    padding: 1rem 1.5rem; color: var(--text-main); font-size: 1.1rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);
    cursor: pointer; transition: background 0.15s ease;
}
.accordion-header:hover { background: rgba(255, 255, 255, 0.06); }
.accordion-header::after { content: '▼'; font-size: 0.8rem; transition: transform 0.3s ease; color: var(--text-muted); }
.accordion-header.open::after { transform: rotate(-180deg); }
.accordion-body { max-height: 0; overflow: hidden; transition: max-height 0.4s ease-out; background: transparent; }

/* Category masonry */
.categories-masonry { column-count: 2; column-gap: 2rem; }
.masonry-item { break-inside: avoid; margin-bottom: 2rem; }
.masonry-item .category-title {
    font-size: 1rem; font-weight: 600; color: var(--text-main); margin: 0; padding: 0.75rem 1rem;
    background: rgba(255,255,255,0.03); border-bottom: 1px solid var(--border);
    text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);
}

.article-list { display: flex; flex-direction: column; }
.article-item {
    display: flex; padding: 1rem 1.5rem; border-bottom: 1px solid var(--border);
    transition: background 0.15s ease; text-decoration: none; color: inherit; gap: 1.25rem; align-items: flex-start;
}
.masonry-item .article-item { padding: 0.75rem 1rem; gap: 1rem; }
.article-item:last-child { border-bottom: none; }
.article-item:hover { background: var(--hover-bg); }

.article-item.read-article { opacity: 0.5; }
.article-item.read-article .headline { color: var(--text-muted); }

.score {
    min-width: 45px; font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent);
    background: rgba(88, 166, 255, 0.1); padding: 0.25rem 0; text-align: center; border-radius: 4px; margin-top: 0.15rem;
}
.content { flex: 1; min-width: 0; }
.headline { font-weight: 500; font-size: 1.05rem; margin: 0 0 0.35rem 0; color: var(--text-main); flex-wrap: wrap; display: flex; align-items: baseline; gap: 0.5rem; }
.summary {
    font-size: 0.9rem; color: var(--text-muted); margin: 0; display: -webkit-box;
    -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.5;
}
.view-all {
    display: block; text-align: center; padding: 0.75rem; color: var(--accent); text-decoration: none; font-weight: 500; font-size: 0.9rem; transition: background 0.15s;
}
.view-all:hover { background: rgba(88, 166, 255, 0.05); }

@media (max-width: 1024px) {
    .categories-masonry { column-count: 1; }
    header { flex-direction: column; align-items: flex-start; gap: 1rem; }
    .stats-bar { text-align: left; }
}
"""

class HTMLPublisher:
    """Generates and saving standard HTML digest versions suited for GitHub Pages."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.output_dir = Path("public")
        self.output_dir.mkdir(exist_ok=True)
        
        user_cfg = config.get("user", {})
        raw_persona = user_cfg.get("persona", "default")
        # slugify up to 3 words
        slug = re.sub(r'[^a-z0-9\s-]', '', raw_persona.lower())
        words = slug.split()[:3]
        self.persona_slug = "-".join(words) if words else "default"

    async def publish(self, digest: Digest) -> Path:
        """Render the HTML and return the saved path."""
        date_str = digest.date.strftime('%Y-%m-%d')
        filename = f"News-digest-{self.persona_slug}-{date_str}.html"
        filepath = self.output_dir / filename
        
        html_content = self._render_html(digest, date_str)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        log.info("web.published", filepath=str(filepath))
        
        # Optionally update an index.html file to redirect to this newest one
        self._update_index(filename)
        
        return filepath

    def _update_index(self, latest_filename: str) -> None:
        """Writes an index.html that auto-redirects to the latest digest."""
        index_path = self.output_dir / "index.html"
        content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0; url={latest_filename}">
    <title>Redirecting to latest digest</title>
</head>
<body style="background:#0d1117; color:#c9d1d9; font-family:sans-serif; text-align:center; padding-top:5rem;">
    <p>Redirecting to the latest digest: <a href="{latest_filename}" style="color:#58a6ff;">{latest_filename}</a></p>
</body>
</html>"""
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _render_html(self, digest: Digest, date_str: str) -> str:
        """Construct the HTML document natively."""
        express_sections = []
        detail_sections = []
        
        # Iterate over each AI grouping
        for category, articles in digest.by_category.items():
            if not articles:
                continue
                
            express_cards = []
            detail_cards = []
            
            for idx, a in enumerate(articles):
                score_disp = f"↑{a.engagement_score}" if a.engagement_score > 0 else "-"
                summary_text = a.summary or (a.raw_content[:400] + "..." if a.raw_content else "No summary available.")
                
                card_html = f"""
                <a href="{a.url}" target="_blank" class="article-item">
                    <div class="score">{score_disp}</div>
                    <div class="content">
                        <h3 class="headline">{a.title}</h3>
                        <p class="summary">{summary_text}</p>
                    </div>
                </a>
                """
                
                detail_cards.append(card_html)
                if idx < 5:
                    express_cards.append(card_html)
            
            category_title = category.replace('_', ' ')
            
            # Express section logic
            view_all_link = ""
            if len(articles) > 5:
                # Add a link to swap tabs
                view_all_link = f"""<a href="#" class="view-all" onclick="switchTab(event, 'detail')">View all {len(articles)} articles in {category_title} →</a>"""
                
            express_sections.append(f"""
            <div class="category-group">
                <button class="accordion-header" onclick="toggleAccordion(this)">{category_title}</button>
                <div class="accordion-body">
                    <div class="article-list">
                        {''.join(express_cards)}
                        {view_all_link}
                    </div>
                </div>
            </div>
            """)
            
            # Detail section logic
            detail_sections.append(f"""
            <div class="category-group masonry-item">
                <h2 class="category-title">{category_title}</h2>
                <div class="article-list">
                    {''.join(detail_cards)}
                </div>
            </div>
            """)

        full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI News Digest | {date_str}</title>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
    {CSS_STYLES}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1 class="title">AI Pulse Digest</h1>
                <div class="subtitle">Curated insights for {date_str}</div>
            </div>
            <div class="stats-bar">
                <div class="stat"><span>Analyzed</span><span>{digest.total_collected} artifacts</span></div>
                <div class="stat"><span>Filtered</span><span>{digest.duplicates_removed} dupes</span></div>
                <div class="stat"><span>Curated</span><span>{digest.article_count} items</span></div>
            </div>
        </header>

        <div class="tabs-container">
            <button class="tab-btn active" onclick="switchTab(event, 'express')">✨ Highlights (Top 5)</button>
            <button class="tab-btn" onclick="switchTab(event, 'detail')">📚 Deep Dive (All)</button>
        </div>
        
        <main id="express" class="tab-content active">
            {''.join(express_sections)}
        </main>
        
        <main id="detail" class="tab-content categories-masonry">
            {''.join(detail_sections)}
        </main>
    </div>
    <script>
        // Open all accordions by default
        document.addEventListener('DOMContentLoaded', () => {{
            document.querySelectorAll('.accordion-header').forEach(header => {{
                toggleAccordion(header);
            }});
        }});

        // Tab Switching Logic
        function switchTab(e, tabId) {{
            if (e) e.preventDefault();
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            // If triggered by a tab button, set it active, else find the tab button for that tabId
            let tabBtn = (e && e.target && e.target.classList.contains('tab-btn')) ? e.target : document.querySelector(`.tab-btn[onclick*="${{tabId}}"]`);
            if (tabBtn) tabBtn.classList.add('active');

            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            
            // scroll to top if clicked view all
            if (e && e.target && e.target.classList.contains('view-all')) {{
                window.scrollTo(0, 0);
            }}
        }}

        // Accordion Logic
        function toggleAccordion(headerElement) {{
            headerElement.classList.toggle('open');
            const body = headerElement.nextElementSibling;
            if (headerElement.classList.contains('open')) {{
                body.style.maxHeight = body.scrollHeight + "px";
            }} else {{
                body.style.maxHeight = "0";
            }}
        }}

        // Read article persistence
        document.addEventListener("DOMContentLoaded", () => {{
            const STORAGE_KEY = "read_articles";
            let readArticles = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"));
            
            document.querySelectorAll('.article-item').forEach(item => {{
                const url = item.getAttribute('href');
                if (readArticles.has(url)) {{
                    item.classList.add('read-article');
                }}
                
                item.addEventListener('click', () => {{
                    readArticles.add(url);
                    localStorage.setItem(STORAGE_KEY, JSON.stringify([...readArticles]));
                    
                    // Mark all identically-linked items read
                    document.querySelectorAll(`.article-item[href="${{url}}"]`).forEach(i => i.classList.add('read-article'));
                }});
            }});
        }});
    </script>
</body>
</html>
"""
        return full_html


def deploy_surge_cli() -> None:
    """Standalone CLI entry point to just deploy the /public folder to Surge.sh."""
    import argparse
    import subprocess
    import sys
    from src.utils.config import load_config
    
    parser = argparse.ArgumentParser(description="Deploy HTML to Surge")
    parser.add_argument("--config", default="config/config.toml")
    args = parser.parse_args()
    
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"Error: {args.config} not found.", file=sys.stderr)
        sys.exit(1)
        
    surge_domain = config.get("web", {}).get("surge_domain", "semantic-daily.surge.sh")
    print(f"🚀 Deploying ./public to {surge_domain} via Surge.sh...")
    try:
        subprocess.run(["npx", "--yes", "surge", "./public", surge_domain], check=True)
        print("✅ Deploy successful!")
    except subprocess.CalledProcessError as e:
        print("❌ Deploy failed.", file=sys.stderr)
        sys.exit(e.returncode)
