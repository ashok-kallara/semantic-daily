# ---- Build stage ----
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project

# Copy source code
COPY src/ src/
COPY config/ config/
COPY scripts/ scripts/

# Install the project itself
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime

# Install tini for proper PID 1 handling and cron
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini cron && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r newsbot && \
    useradd -r -g newsbot -d /app -s /sbin/nologin newsbot

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/config /app/config
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Ensure scripts are executable
RUN chmod +x /app/scripts/entrypoint.sh

# Create writable directories
RUN mkdir -p /app/data /var/log/semantic-daily && \
    chown -R newsbot:newsbot /app/data /var/log/semantic-daily

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

ENTRYPOINT ["tini", "--"]
CMD ["/app/scripts/entrypoint.sh"]
