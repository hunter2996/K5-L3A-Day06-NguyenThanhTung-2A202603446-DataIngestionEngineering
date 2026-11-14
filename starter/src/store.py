"""Store and search vectors with metadata filtering using PostgreSQL + pgvector."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import Chunk

ALLOWED_FILTER_KEYS = {"document_id", "chapter", "content_type", "section", "page"}
_COLUMN_FILTER_KEYS = {"document_id", "chapter", "content_type", "section", "page"}


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


class PgVectorStore:
    """Persistent PostgreSQL + pgvector store supporting exact cosine search & SQL metadata filters."""

    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url or not database_url.strip():
            raise ValueError("DATABASE_URL must be configured.")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError(f"dimensions must be a positive integer, got {dimensions!r}")

        self.database_url = database_url.strip()
        self.dimensions = dimensions
        self.metric = "cosine"
        self.search_mode = "exact (<=> sequential cosine distance)"

        try:
            with psycopg.connect(self.database_url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                    row = cur.fetchone()
                    if not row:
                        raise RuntimeError("pgvector extension is not enabled in the target database.")
                    self.pgvector_version = str(row[0])
        except psycopg.Error as exc:
            raise RuntimeError(f"Failed to connect to PostgreSQL + pgvector: {exc}") from exc

    def create_schema(self) -> None:
        """Create vector chunks table and metadata indexes with fixed embedding dimensions."""
        ddl_vector = f"""
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS chunks (
            strategy TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            source TEXT NOT NULL,
            page INTEGER NOT NULL,
            chapter TEXT,
            content_type TEXT,
            section TEXT,
            text TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding vector({self.dimensions}) NOT NULL,
            content_hash TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (strategy, chunk_id)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_strategy_doc ON chunks (strategy, document_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_strategy_filters ON chunks (strategy, chapter, content_type);
        """
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(ddl_vector)
                cur.execute(
                    """
                    SELECT format_type(atttypid, atttypmod)
                    FROM pg_attribute
                    WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'
                    """
                )
                row = cur.fetchone()
                expected_type = f"vector({self.dimensions})"
                if row and row[0] != expected_type:
                    raise RuntimeError(
                        f"Existing chunks.embedding column has type {row[0]}, expected {expected_type}."
                    )
            conn.commit()

    def count_chunks(self, strategy: str) -> int:
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM chunks WHERE strategy = %s", (strategy,))
                return int(cur.fetchone()[0])

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> dict[str, int]:
        """Idempotently upsert chunks by stable (strategy, chunk_id) and prune obsolete chunks."""
        if not strategy or not strategy.strip():
            raise ValueError("strategy must be non-empty")
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch")

        for idx, vec in enumerate(vectors):
            if len(vec) != self.dimensions:
                raise ValueError(
                    f"Vector at index {idx} has dimension {len(vec)}, expected {self.dimensions}"
                )

        if not chunks:
            return {"upserted": 0, "deleted_obsolete": 0, "total_in_strategy": self.count_chunks(strategy)}

        doc_ids_to_ids: dict[str, list[str]] = {}
        rows: list[tuple[Any, ...]] = []
        for chunk, vec in zip(chunks, vectors):
            doc_ids_to_ids.setdefault(chunk.document_id, []).append(chunk.chunk_id)
            meta_json = json.dumps(chunk.metadata, sort_keys=True, ensure_ascii=False)
            content_hash = hashlib.sha256((chunk.text + "\n" + meta_json).encode("utf-8")).hexdigest()
            rows.append(
                (
                    strategy,
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.source,
                    int(chunk.page),
                    chunk.metadata.get("chapter"),
                    chunk.metadata.get("content_type"),
                    chunk.metadata.get("section"),
                    chunk.text,
                    meta_json,
                    _vector_literal(vec),
                    content_hash,
                )
            )

        deleted_obsolete = 0
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for doc_id, active_ids in doc_ids_to_ids.items():
                    cur.execute(
                        """
                        DELETE FROM chunks
                        WHERE strategy = %s AND document_id = %s AND NOT (chunk_id = ANY(%s))
                        """,
                        (strategy, doc_id, active_ids),
                    )
                    deleted_obsolete += cur.rowcount

                cur.executemany(
                    """
                    INSERT INTO chunks (
                        strategy, chunk_id, document_id, source, page,
                        chapter, content_type, section, text, metadata,
                        embedding, content_hash, updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s::jsonb,
                        %s::vector, %s, NOW()
                    )
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id,
                        source = EXCLUDED.source,
                        page = EXCLUDED.page,
                        chapter = EXCLUDED.chapter,
                        content_type = EXCLUDED.content_type,
                        section = EXCLUDED.section,
                        text = EXCLUDED.text,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding,
                        content_hash = EXCLUDED.content_hash,
                        updated_at = NOW()
                    """,
                    rows,
                )

                cur.execute("SELECT COUNT(*) FROM chunks WHERE strategy = %s", (strategy,))
                total_in_strategy = int(cur.fetchone()[0])
            conn.commit()

        return {
            "upserted": len(chunks),
            "deleted_obsolete": deleted_obsolete,
            "total_in_strategy": total_in_strategy,
        }

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter permitted metadata in SQL, rank by exact cosine distance, and return top-k hits."""
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query vector dimension {len(query_vector)} does not match store dimension {self.dimensions}"
            )
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        vec_str = _vector_literal(query_vector)
        where_clauses = ["strategy = %s"]
        params: list[Any] = [strategy]

        if filters:
            for key, val in filters.items():
                if key not in ALLOWED_FILTER_KEYS:
                    raise ValueError(f"Filter key {key!r} is not in ALLOWED_FILTER_KEYS: {sorted(ALLOWED_FILTER_KEYS)}")
                if key in _COLUMN_FILTER_KEYS:
                    where_clauses.append(f"{key} = %s")
                    params.append(val)
                else:
                    where_clauses.append("metadata ->> %s = %s")
                    params.extend([key, str(val)])

        where_sql = " AND ".join(where_clauses)
        sql = f"""
            SELECT
                chunk_id,
                document_id,
                source,
                page,
                chapter,
                content_type,
                section,
                text,
                metadata,
                1.0 - (embedding <=> %s::vector) AS score
            FROM chunks
            WHERE {where_sql}
            ORDER BY embedding <=> %s::vector ASC
            LIMIT %s
        """
        query_params = [vec_str, *params, vec_str, top_k]

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, query_params)
                rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            meta = dict(row.get("metadata") or {})
            meta.setdefault("chapter", row.get("chapter"))
            meta.setdefault("content_type", row.get("content_type"))
            meta.setdefault("section", row.get("section"))
            results.append(
                {
                    "chunk_id": row["chunk_id"],
                    "document_id": row["document_id"],
                    "source": row["source"],
                    "page": int(row["page"]),
                    "text": row["text"],
                    "score": round(float(row["score"]), 6),
                    "metadata": meta,
                }
            )
        return results
