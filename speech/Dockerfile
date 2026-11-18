FROM ghcr.io/astral-sh/uv:0.8.15 AS uv
FROM python:3.11.14-slim-bookworm AS base
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    PYANNOTE_METRICS_ENABLED=0 OMP_NUM_THREADS=4
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
COPY src ./src
COPY configs ./configs
COPY migrations ./migrations
COPY alembic.ini ACCEPTANCE.yaml SPEC.md SOURCES.md ./
COPY tests ./tests
COPY scripts ./scripts
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen && mkdir -p /audio /artifacts /models /reports /data/input /data/curated /data/manifests \
    && chown -R app:app /audio /artifacts /models /reports /data /app
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "north55_speech.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS gpu
USER root
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra gpu
ENV LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib
USER 10001:10001
