#!/bin/bash
# ============================================================================
# News Feed Aggregator — Container Entrypoint
# ============================================================================
# Runs health checks then starts the cron daemon for scheduled execution.
# Can also be invoked directly for one-shot runs.
# ============================================================================

set -euo pipefail

echo "═══════════════════════════════════════════"
echo "  📰 News Feed Aggregator"
echo "  Started: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "═══════════════════════════════════════════"

# Forward environment variables to cron
# (cron runs in a clean environment, so we persist current env)
printenv | grep -E '^(REDDIT_|TELEGRAM_|OPENAI_|ANTHROPIC_|OLLAMA_|LLM_|LOG_|CACHE_|PYTHONPATH)' \
  > /etc/environment 2>/dev/null || true

# Health checks
echo "🔍 Running health checks..."

# Check Telegram connectivity
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "  ✅ Telegram credentials configured"
else
    echo "  ⚠️  Telegram credentials NOT configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"
fi

# Check Reddit credentials
if [ -n "${REDDIT_CLIENT_ID:-}" ] && [ -n "${REDDIT_CLIENT_SECRET:-}" ]; then
    echo "  ✅ Reddit credentials configured"
else
    echo "  ⚠️  Reddit credentials NOT configured (optional)"
fi

# Check Ollama connectivity
OLLAMA_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"
if curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    echo "  ✅ Ollama reachable at ${OLLAMA_URL}"
else
    echo "  ⚠️  Ollama NOT reachable at ${OLLAMA_URL} (will use fallback summarization)"
fi

echo ""

# Check if this is a one-shot run
if [ "${1:-}" = "run" ] || [ "${1:-}" = "--run-now" ]; then
    echo "🚀 Running pipeline now (one-shot)..."
    exec su -s /bin/bash newsbot -c "cd /app && python -m src.main ${*:2}"
fi

if [ "${1:-}" = "dry-run" ]; then
    echo "🧪 Running pipeline in dry-run mode..."
    exec su -s /bin/bash newsbot -c "cd /app && python -m src.main --dry-run"
fi

# Start cron daemon in foreground
echo "⏰ Starting cron scheduler..."
echo "   Schedule: see /etc/cron.d/semantic-daily-cron"
echo "   Logs: /var/log/semantic-daily.log"
echo ""

# Start cron in foreground (PID 1 is tini, cron is the main process)
exec cron -f
