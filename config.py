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
# Embeddings reuse the local Ollama (no torch / sentence-transformers) — see
# DECISIONS `embeddings-ollama`. nomic-embed-text wants task prefixes:
# documents are embedded as "search_document: …", queries as "search_query: …"
# (src/store.py applies these). Using the wrong prefix degrades retrieval.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
TOP_K = int(os.getenv("TOP_K", "4"))
REWRITE_MAX_RETRIES = int(os.getenv("REWRITE_MAX_RETRIES", "1"))  # bounded corrective-RAG loop
# Cosine-distance safety floor for the RAG grader: a hit at/below this counts as relevant
# even if the small LLM grader says "no" (guards against 3B false negatives). Tune in eval.
GRADE_DISTANCE_FLOOR = float(os.getenv("GRADE_DISTANCE_FLOOR", "0.25"))
CHROMA_DIR = os.getenv("CHROMA_DIR", "data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "passenger_rights_261")
CORPUS_DIR = os.getenv("CORPUS_DIR", "data/corpus")

# --- Calculator (Phase 3) ---
# OpenFlights airport table (IATA → lat/lon) for great-circle distance. ODbL — attributed in
# data/SOURCES.md. Path only; the Art. 7 band amounts/thresholds are statutory and live as
# constants in src/calculator.py (not env knobs — see DECISIONS).
AIRPORTS_DAT = os.getenv("AIRPORTS_DAT", "data/airports.dat")
