"""The single LLM abstraction. Every node and the UI call `get_llm()` — never an
Ollama client directly — so the backend stays swappable behind one seam.

Only the `ollama` backend is wired today. A stub/dummy backend was deferred (see
DECISIONS `drop-dummy-llm`); keeping all call sites on `get_llm()` means it can be
added later as a single branch here, with no surgery across the graph.

The returned object is a LangChain chat model (`BaseChatModel`), so callers use the
standard `.invoke(messages)` / `.stream(messages)` interface and message types.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from src.config import Config, get_config


class UnsupportedBackendError(ValueError):
    """Raised when config requests an LLM backend that isn't wired."""


def _build_ollama(cfg: Config) -> BaseChatModel:
    # Imported lazily so adding other backends never forces the Ollama import.
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=cfg.model,
        base_url=cfg.ollama_url,
        temperature=cfg.temperature,  # 0 by default for determinism
    )


# Registry of wired backends. Add new backends (e.g. a stub) as one entry here.
_BACKENDS = {
    "ollama": _build_ollama,
}


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Return the configured chat model. Cached for the process lifetime."""
    cfg = get_config()
    backend = cfg.llm_backend.lower()
    builder = _BACKENDS.get(backend)
    if builder is None:
        raise UnsupportedBackendError(
            f"LLM_BACKEND={cfg.llm_backend!r} is not wired. "
            f"Available: {sorted(_BACKENDS)}."
        )
    return builder(cfg)
