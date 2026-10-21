FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
# Immutable package snapshot pins OCR, rendering, fonts and their dependencies.
RUN rm -f /etc/apt/sources.list.d/* && printf '%s\n' 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261018T000000Z bookworm main' 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261018T000000Z bookworm-security main' > /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends ffmpeg poppler-utils tesseract-ocr tesseract-ocr-eng libreoffice-writer fonts-dejavu-core libseccomp2 \
    && dpkg-query -W > /usr/share/videomind-packages.txt \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.22
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
ENV UV_HTTP_TIMEOUT=180 UV_CONCURRENT_DOWNLOADS=2
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra transcription --no-dev --no-install-project
COPY backend/src ./src
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra transcription --no-dev && useradd --uid 10001 --create-home app
ENV PATH="/app/backend/.venv/bin:$PATH"
USER 10001
CMD ["uvicorn", "videomind.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--log-level", "info"]

FROM app AS verify
USER root
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra transcription --group dev
COPY backend/tests ./tests
USER 10001
CMD ["python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]

FROM app AS embedding
COPY evaluation/manifests/embedding-files.json /usr/share/videomind-embedding-files.json
USER root
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra feasibility --extra transcription --no-dev
USER 10001
ENV HF_HUB_OFFLINE=1 HF_HOME=/tmp/huggingface TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 MALLOC_ARENA_MAX=2
CMD ["uvicorn", "videomind.embeddings.server:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log", "--log-level", "warning"]
