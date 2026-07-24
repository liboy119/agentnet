FROM python:3.11-slim

WORKDIR /app

# Install deps
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# AgentPub runs on port 7700
EXPOSE 7700

# Default: API server. Override CMD to run MCP server etc.
CMD ["python", "-m", "agentpub.main", "--host", "0.0.0.0", "--port", "7700"]