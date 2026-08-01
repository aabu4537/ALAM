FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

# Dependency layer, cached independently of source changes. `--group local`
# is explicit because it isn't a default uv group (see pyproject.toml) — this
# is the local-dev image (docker-compose.yml), not the Vercel production
# path, so it keeps installing the local ($0) providers same as before they
# were split out of the base dependency list.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev --group local 2>/dev/null || uv sync --no-install-project --no-dev --group local

COPY . .
RUN uv sync --no-editable --no-dev --group local 2>/dev/null || true

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "alam.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
