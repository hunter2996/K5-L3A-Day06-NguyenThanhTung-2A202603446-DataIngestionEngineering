"""Real local SentenceTransformers embedding adapter (no silent mock fallback)."""
from __future__ import annotations

import time
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """Local SentenceTransformers embedder using normalized cosine embeddings."""

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        if not model_name or not model_name.strip():
            raise ValueError("EMBEDDING_MODEL must be set to a real embedding model name.")
        self.model_name = model_name.strip()
        self.provider = "sentence-transformers (local)"
        self.batch_size = batch_size
        self.total_doc_texts = 0
        self.total_doc_chars = 0
        self.total_query_calls = 0
        self.total_embed_seconds = 0.0

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device="cpu")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize embedding model '{self.model_name}'. "
                "Do not fall back to mock vectors."
            ) from exc

        dim = self._model.get_sentence_embedding_dimension()
        if not isinstance(dim, int) or dim <= 0:
            raise RuntimeError(f"Invalid embedding dimension {dim!r} for model '{self.model_name}'.")
        self.dimensions = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        t0 = time.perf_counter()
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        elapsed = time.perf_counter() - t0
        self.total_doc_texts += len(texts)
        self.total_doc_chars += sum(len(t) for t in texts)
        self.total_embed_seconds += elapsed
        return [vec.tolist() for vec in vectors]

    def embed_query(self, question: str) -> list[float]:
        if not question or not question.strip():
            raise ValueError("Query question must be non-empty.")
        t0 = time.perf_counter()
        vector = self._model.encode(
            [question.strip()],
            batch_size=1,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        self.total_query_calls += 1
        self.total_embed_seconds += time.perf_counter() - t0
        return vector.tolist()
