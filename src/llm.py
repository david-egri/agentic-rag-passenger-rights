"""The single LLM accessor. Every node and the UI call `get_llm()` — never an Ollama
client directly — so the backend stays swappable behind one seam (CLAUDE.md non-neg #1).

Only Ollama is wired today. If a stub backend is ever needed (e.g. to isolate LLM
latency in the load test — see DECISIONS `drop-dummy-llm`), add a branch here; callers
don't change. The returned object is a LangChain chat model, so callers use the
standard `.invoke(messages)` / `.stream(messages)` interface.
"""

from functools import lru_cache

import config


@lru_cache(maxsize=1)
def get_llm():
    """Return the configured chat model (cached for the process lifetime)."""
    if config.LLM_BACKEND != "ollama":
        raise ValueError(f"Unsupported LLM_BACKEND={config.LLM_BACKEND!r} (only 'ollama' is wired).")
    from langchain_ollama import ChatOllama

    return ChatOllama(model=config.MODEL, base_url=config.OLLAMA_URL, temperature=config.TEMPERATURE)
