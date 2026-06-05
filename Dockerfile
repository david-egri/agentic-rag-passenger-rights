# syntax=docker/dockerfile:1
# Multi-stage build. Stage 1 resolves + installs the pinned deps into an isolated venv;
# stage 2 is a clean slim runtime that just copies that venv + the app code. Keeps the
# final image small (no pip cache, no build tooling) — important on a tight disk.
#
# Base is pinned to python:3.14-slim to match the local .python-version (3.14) so wheel
# resolution is identical to dev (Phase 2 confirmed cp314 wheels for langgraph/chromadb —
# no source builds, so the builder needs no compiler). If a future dep ships only an sdist,
# add `build-essential` to the builder stage *only* (it never reaches the runtime image).

# ---- Stage 1: builder ----------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Isolated venv we can copy wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install deps first (own layer) so they cache across source-only changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- Stage 2: runtime ----------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root user (image hygiene — never run the app as root).
RUN useradd --create-home --uid 1000 app

# Bring in the prebuilt venv from the builder.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# App code + the frozen corpus (committed). The derived vector store is NOT copied —
# .dockerignore excludes data/chroma/; the entrypoint rebuilds it at runtime into a volume.
COPY --chown=app:app . /app

# Pre-create the Chroma mount point owned by `app`. A fresh named volume mounted here
# inherits this ownership, so the non-root user can write the vector store. Also make the
# entrypoint executable.
RUN mkdir -p /app/data/chroma \
    && chmod +x /app/docker/entrypoint.sh \
    && chown -R app:app /app

USER app

EXPOSE 8501

# Streamlit's own healthcheck endpoint (compose can probe it if desired).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3).status==200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
