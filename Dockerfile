# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN groupadd --gid 10001 shein \
    && useradd --uid 10001 --gid shein --create-home --shell /usr/sbin/nologin shein

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir ".[server]" \
    && python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        fonts-noto-color-emoji \
        fonts-noto-core \
        fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/runtime/data /app/runtime/exports /app/runtime/outputs \
    && chown -R shein:shein /app /ms-playwright

USER shein

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "shein_extractor.presentation.api.bootstrap:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
