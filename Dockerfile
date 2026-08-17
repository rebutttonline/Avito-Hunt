FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --gid 1000 app && adduser --uid 1000 --gid 1000 --disabled-password app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

USER 1000:1000

CMD ["python", "-m", "avito_hunt.bot_service"]

