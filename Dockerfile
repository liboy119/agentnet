FROM python:3.11-slim

WORKDIR /app

# Install deps
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# Default port — Render injects $PORT automatically
EXPOSE 7700

# Default: API server. Override CMD to run MCP server etc.
# Honor $PORT (Render, Railway, fly.io) with fallback to 7700.
CMD ["sh", "-c", "python -m agentpub.main --host 0.0.0.0 --port ${PORT:-7700}"]