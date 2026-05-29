"""ChromaDB-backed vector retrieval for larger / more complex corpora.

This module is the second retrieval strategy in the project. Small corpora are
handled by the local BM25 retriever in ``retrieval.py``; once a corpus crosses a
complexity threshold (see ``retrieval.choose_retrieval_engine``) the system
embeds the chunks with the Google GenAI embeddings API and stores them in a
persistent ChromaDB collection so that questions are answered with semantic
vector search.

The candidates returned here use the exact same dict shape as the BM25
retriever, so the routes, templates, and generators do not need to change.
"""

import hashlib
import logging
import os
from typing import Any

from .llm import GeminiError, gemini_embed_texts
from .retrieval import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    chunk_with_offsets,
    tokenize,
)

logger = logging.getLogger(__name__)

CHROMA_PATH = os.environ.get("CORPUS_FORGE_CHROMA", "data/chroma")
COLLECTION_NAME = "corpus_forge_chunks"


class VectorStoreError(RuntimeError):
    """Raised when the ChromaDB vector path cannot be used."""


_client = None


def chroma_is_available() -> bool:
    """Return True when the chromadb package can be imported."""
    try:
        import chromadb  # noqa: F401
    except Exception:  # pragma: no cover - depends on environment
        return False
    return True


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        import chromadb
    except Exception as error:  # pragma: no cover - depends on environment
        raise VectorStoreError(f"chromadb is not installed: {error}") from error

    os.makedirs(CHROMA_PATH, exist_ok=True)
    try:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    except Exception as error:
        raise VectorStoreError(f"Could not open ChromaDB store: {error}") from error
    return _client


def _get_collection():
    client = _get_client()
    # Cosine space matches normalized text embeddings well.
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _corpus_signature(documents: list[dict[str, Any]]) -> str:
    """Stable hash describing the active document set and its content."""
    hasher = hashlib.sha256()
    for document in sorted(documents, key=lambda d: str(d.get("filename", ""))):
        hasher.update(str(document.get("filename", "")).encode("utf-8", "ignore"))
        hasher.update(b"\x00")
        hasher.update(str(document.get("text", "")).encode("utf-8", "ignore"))
        hasher.update(b"\x01")
    return hasher.hexdigest()[:16]


def _build_chunks(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for document in documents:
        filename = document.get("filename", "document")
        for index, chunk in enumerate(
            chunk_with_offsets(document.get("text", ""), size=DEFAULT_CHUNK_SIZE, overlap=DEFAULT_OVERLAP),
            start=1,
        ):
            if not tokenize(chunk["text"]):
                continue
            chunks.append(
                {
                    "document": filename,
                    "chunk": chunk["text"],
                    "chunk_index": index,
                    "start_word": chunk["start_word"],
                    "end_word": chunk["end_word"],
                }
            )
    return chunks


def _index_corpus(collection, signature: str, documents: list[dict[str, Any]], api_key: str | None) -> int:
    """Embed and upsert chunks for this corpus signature if not already present."""
    existing = collection.get(where={"signature": signature}, include=[])
    if existing and existing.get("ids"):
        return len(existing["ids"])

    chunks = _build_chunks(documents)
    if not chunks:
        return 0

    embeddings = gemini_embed_texts([chunk["chunk"] for chunk in chunks], api_key=api_key)

    ids = [f"{signature}:{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "signature": signature,
            "document": chunk["document"],
            "chunk_index": chunk["chunk_index"],
            "start_word": chunk["start_word"],
            "end_word": chunk["end_word"],
        }
        for chunk in chunks
    ]
    documents_text = [chunk["chunk"] for chunk in chunks]

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents_text,
    )
    logger.info("Indexed %d chunks into ChromaDB for signature %s", len(chunks), signature)
    return len(chunks)


def _confidence_from_distance(distance: float) -> str:
    # Cosine distance: 0 == identical, 2 == opposite. Map to similarity.
    similarity = 1.0 - float(distance)
    if similarity >= 0.72:
        return "high"
    if similarity >= 0.5:
        return "medium"
    if similarity > 0:
        return "low"
    return "none"


def chroma_retrieval(
    documents: list[dict[str, Any]],
    query: str,
    limit: int = 5,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve chunks from the ChromaDB vector store.

    Embeds the active corpus (once per content signature), embeds the query, and
    runs a nearest-neighbour search. Returns candidates in the same dict shape as
    the BM25 retriever so callers do not need special handling. Raises
    ``VectorStoreError`` or ``GeminiError`` when the path cannot run, letting the
    caller fall back to local retrieval.
    """
    if not documents or not query.strip():
        return []

    collection = _get_collection()
    signature = _corpus_signature(documents)
    indexed = _index_corpus(collection, signature, documents, api_key)
    if not indexed:
        return []

    query_embedding = gemini_embed_texts([query], api_key=api_key)[0]
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=max(1, limit),
        where={"signature": signature},
        include=["documents", "metadatas", "distances"],
    )

    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    query_terms = set(tokenize(query))
    candidates: list[dict[str, Any]] = []
    for chunk_text, meta, distance in zip(docs, metas, dists):
        similarity = round(1.0 - float(distance), 3)
        chunk_terms = set(tokenize(chunk_text))
        matched = tuple(sorted(query_terms & chunk_terms))
        candidates.append(
            {
                "document": meta.get("document", "document"),
                "chunk": chunk_text,
                "score": similarity,
                "strategy": "chromadb vector",
                "chunk_index": int(meta.get("chunk_index", 1)),
                "start_word": int(meta.get("start_word", 1)),
                "end_word": int(meta.get("end_word", 1)),
                "matched_terms": list(matched),
                "confidence": _confidence_from_distance(distance),
            }
        )
    return candidates
