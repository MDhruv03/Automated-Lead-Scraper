FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# System deps for lxml + psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt1-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && \
    uv pip install --no-deps en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

COPY . .

EXPOSE 10000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
