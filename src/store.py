"""Retrieval substrate shared by ingestion (`src/ingest.py`) and the retrieval tool
(`src/tools.py`): the persisted Chroma collection plus the embedding seam.

Two consumers (write side + read side) is why this is its own module rather than
living inside ingest — keeping a single definition of *how* text becomes vectors and
*where* they're stored means the two sides can't drift apart.

Embeddings reuse the local Ollama model (`config.EMBEDDING_MODEL`, default
`nomic-embed-text`) via `OllamaEmbeddings` — no torch / sentence-transformers
(DECISIONS `embeddings-ollama`). nomic-embed-text is trained with task prefixes, so we
embed corpus chunks as `search_document: …` and queries as `search_query: …`. These are
applied here, in one place, so the asymmetry is correct by construction:
`embed_documents()` is the only way text enters the index and `embed_query()` the only
way a query is vectorised. Chroma never auto-embeds — we always pass vectors explicitly,
so its default (onnx) embedding function is never invoked.
"""

from functools import lru_cache

import config

_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


@lru_cache(maxsize=1)
def get_embedder():
    """Cached LangChain embeddings client pointed at the local Ollama."""
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=config.EMBEDDING_MODEL, base_url=config.OLLAMA_URL)


def embed_documents(texts):
    """Embed corpus chunks (applies the `search_document:` prefix)."""
    return get_embedder().embed_documents([_DOC_PREFIX + t for t in texts])


def embed_query(text):
    """Embed a search query (applies the `search_query:` prefix)."""
    return get_embedder().embed_query(_QUERY_PREFIX + text)


@lru_cache(maxsize=1)
def get_client():
    """Cached Chroma client persisted at `config.CHROMA_DIR`."""
    import chromadb

    return chromadb.PersistentClient(path=config.CHROMA_DIR)


def get_collection():
    """The passenger-rights collection (created on first use). Cosine space matches the
    normalised embeddings; we always supply vectors, so no embedding_function is set."""
    return get_client().get_or_create_collection(
        name=config.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
