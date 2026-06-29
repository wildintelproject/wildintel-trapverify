# Build context must be the project root (docker-compose uses context: .)
FROM ghcr.io/astral-sh/uv:python3.13-slim

WORKDIR /app

# pyproject.toml and uv.lock now live at the project root
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/src/ ./src/

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
