"""Central configuration — every runtime knob in one place, overridable by env.

Import from here instead of hardcoding model names, URLs, or top-k in the code.
Environment variables win over the defaults, so a reviewer can flip a knob without
editing anything:

    MODEL=llama3.2:3b TOP_K=6 streamlit run streamlit_app.py
"""

import os

# --- LLM ---
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")
MODEL = os.getenv("MODEL", "qwen2.5:3b-instruct")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0"))  # 0 = deterministic

# --- Retrieval / RAG (used from Phase 2 onward) ---
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
TOP_K = int(os.getenv("TOP_K", "4"))
REWRITE_MAX_RETRIES = int(os.getenv("REWRITE_MAX_RETRIES", "1"))  # bounded corrective-RAG loop
CHROMA_DIR = os.getenv("CHROMA_DIR", "data/chroma")
CORPUS_DIR = os.getenv("CORPUS_DIR", "data/corpus")
