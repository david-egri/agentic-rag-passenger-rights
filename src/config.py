"""Configuration loading: `config.yaml` as the base, environment variables override.

One typed `Config` object is the single source of truth for runtime knobs, so no
module hardcodes a model name, URL, or top-k. Later phases read the retrieval
fields that already exist here as placeholders.

Usage:
    from src.config import get_config
    cfg = get_config()
    cfg.model        # -> "qwen2.5:3b-instruct"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path

import yaml

# Repo root = parent of this file's parent (src/ -> repo).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"

# Maps env var name -> (config field, caster). Env always wins over the file so a
# reviewer can flip a knob without editing tracked config.
_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "LLM_BACKEND": ("llm_backend", str),
    "MODEL": ("model", str),
    "OLLAMA_URL": ("ollama_url", str),
    "TEMPERATURE": ("temperature", float),
    "EMBEDDING_MODEL": ("embedding_model", str),
    "TOP_K": ("top_k", int),
    "REWRITE_MAX_RETRIES": ("rewrite_max_retries", int),
    "CHROMA_DIR": ("chroma_dir", str),
    "CORPUS_DIR": ("corpus_dir", str),
}


@dataclass(frozen=True)
class Config:
    """Typed view over config.yaml + env overrides."""

    # LLM (Phase 1)
    llm_backend: str
    model: str
    ollama_url: str
    temperature: float
    # Retrieval / RAG (Phase 2 placeholders)
    embedding_model: str
    top_k: int
    rewrite_max_retries: int
    chroma_dir: str
    corpus_dir: str


def _load_yaml() -> dict:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.yaml not found at {_CONFIG_PATH}")
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _apply_env_overrides(values: dict) -> dict:
    for env_name, (field_name, caster) in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is not None and raw != "":
            values[field_name] = caster(raw)
    return values


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the singleton Config (file + env). Cached for the process lifetime."""
    values = _apply_env_overrides(_load_yaml())
    known = {f.name for f in fields(Config)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown config keys in config.yaml: {sorted(unknown)}")
    missing = known - set(values)
    if missing:
        raise ValueError(f"Missing required config keys: {sorted(missing)}")
    return Config(**values)
