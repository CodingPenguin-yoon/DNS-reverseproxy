FROM caddy:2 AS caddybin

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=caddybin /usr/bin/caddy /usr/bin/caddy
COPY pyproject.toml README.md ./
COPY edge_controller ./edge_controller
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --no-cache-dir .

CMD ["sh", "-c", "alembic upgrade head && uvicorn edge_controller.main:app --host 0.0.0.0 --port 8000"]
