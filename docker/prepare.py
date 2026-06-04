"""Container start-up prep — run once by the entrypoint before Streamlit launches.

Three jobs, all idempotent so repeated `docker compose up` is cheap:

  1. Wait for the Ollama service to answer (compose gates on its healthcheck, but we
     re-check so a host-Ollama override or a slow first boot still works).
  2. Auto-pull the chat + embedding models if the Ollama server doesn't have them yet
     (DECISIONS `commit-corpus`/Phase-7 D1 — true one-command `up`). ~2.2 GB, first run only;
     persisted in the ollama named volume thereafter.
  3. Build the Chroma vector store *only if it's empty* — the named volume keeps it across
     restarts, and re-embedding the whole corpus every boot would be wasteful (it also hits
     Ollama). `src.ingest` itself rebuilds-from-corpus; this guard makes start-up a no-op
     once the volume is warm.

Everything Docker needs flows through config.py via env (OLLAMA_URL, CHROMA_DIR, …), so
this script reads the same knobs the app does — no hardcoding.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

import config

OLLAMA = config.OLLAMA_URL.rstrip("/")
# Chat model + embedding model both served by the same Ollama (one OLLAMA_URL).
REQUIRED_MODELS = [config.MODEL, config.EMBEDDING_MODEL]


def _log(msg: str) -> None:
    print(f"[prepare] {msg}", flush=True)


def wait_for_ollama(timeout_s: int = 180, interval_s: float = 2.0) -> None:
    """Block until Ollama answers /api/version, or give up after timeout_s."""
    _log(f"waiting for Ollama at {OLLAMA} …")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{OLLAMA}/api/version", timeout=3) as r:
                if r.status == 200:
                    _log("Ollama is up.")
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(interval_s)
    _log(f"ERROR: Ollama not reachable at {OLLAMA} after {timeout_s}s.")
    sys.exit(1)


def _installed_models() -> set[str]:
    with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=10) as r:
        data = json.load(r)
    return {m["name"] for m in data.get("models", [])}


def _have(model: str, installed: set[str]) -> bool:
    # Ollama stores an untagged name as "<name>:latest"; treat both as present.
    if model in installed:
        return True
    return ":" not in model and f"{model}:latest" in installed


def pull_model(model: str) -> None:
    """Stream a model pull, logging coarse status transitions (not every byte)."""
    _log(f"pulling '{model}' (first run only; this can take a few minutes) …")
    req = urllib.request.Request(
        f"{OLLAMA}/api/pull",
        data=json.dumps({"name": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    last_status = None
    with urllib.request.urlopen(req, timeout=None) as r:  # no timeout: large download
        for raw in r:
            line = raw.decode().strip()
            if not line:
                continue
            evt = json.loads(line)
            if err := evt.get("error"):
                _log(f"ERROR pulling '{model}': {err}")
                sys.exit(1)
            status = evt.get("status")
            if status and status != last_status:
                _log(f"  {model}: {status}")
                last_status = status
    _log(f"pulled '{model}'.")


def ensure_models() -> None:
    installed = _installed_models()
    for model in REQUIRED_MODELS:
        if _have(model, installed):
            _log(f"model '{model}' already present.")
        else:
            pull_model(model)


def ensure_corpus_ingested() -> None:
    """Run ingestion only if the Chroma collection is empty/missing (volume may be warm)."""
    try:
        from src.store import get_collection

        count = get_collection().count()
    except Exception as e:  # collection/dir not there yet
        _log(f"no existing vector store ({type(e).__name__}); will ingest.")
        count = 0
    if count > 0:
        _log(f"vector store already populated ({count} chunks) — skipping ingest.")
        return
    _log("building vector store from corpus (one-time) …")
    from src.ingest import ingest

    n = ingest()
    _log(f"ingested {n} chunks.")


def main() -> None:
    wait_for_ollama()
    ensure_models()
    ensure_corpus_ingested()
    _log("ready — launching Streamlit.")


if __name__ == "__main__":
    main()
