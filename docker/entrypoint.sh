#!/usr/bin/env bash
# Container entrypoint: prepare (wait for Ollama → pull models → ingest if needed),
# then hand off to Streamlit as PID 1's child via exec (clean signal handling).
set -euo pipefail

# Run as a module from the app root so `import config` / `from src...` resolve
# (running it as a path script would put docker/ on sys.path instead of /app).
python -m docker.prepare

# Bind to all interfaces so the published port reaches the host; headless = no browser
# auto-open, no telemetry prompt inside the container.
exec streamlit run streamlit_app.py \
    --server.address=0.0.0.0 \
    --server.port=8501 \
    --server.headless=true
