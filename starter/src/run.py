"""End-to-end Day 06 Data Ingestion & Retrieval Benchmark pipeline."""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import COHERENCE_SAMPLE_POSITIONS, evaluate_query, summarize
from .ingestion import load_pdf
from .models import Chunk
from .store import PgVectorStore


def _compute_chunk_stats(chunks: list[Chunk]) -> dict[str, Any]:
    if not chunks:
        return {"count": 0, "total_chars": 0, "min": 0, "median": 0, "mean": 0.0, "p95": 0, "max": 0}
    lengths = sorted(len(c.text) for c in chunks)
    p95_idx = min(len(lengths) - 1, int(0.95 * (len(lengths) - 1)))
    return {
        "count": len(lengths),
        "total_chars": sum(lengths),
        "min": lengths[0],
        "median": int(statistics.median(lengths)),
        "mean": round(statistics.mean(lengths), 1),
        "p95": lengths[p95_idx],
        "max": lengths[-1],
    }


def _serialize_chunk(c: Chunk) -> dict[str, Any]:
    return {
        "chunk_id": c.chunk_id,
        "document_id": c.document_id,
        "source": c.source,
        "page": c.page,
        "char_len": len(c.text),
        "metadata": c.metadata,
        "text": c.text,
    }


def _build_audit_samples(
    chunks_by_strategy: dict[str, list[Chunk]],
    traces_by_strategy: dict[str, list[dict[str, Any]]],
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    coherence_samples: list[dict[str, Any]] = []
    for pos in COHERENCE_SAMPLE_POSITIONS:
        target_page = int(pos["page"])
        chunks_a = [_serialize_chunk(c) for c in chunks_by_strategy["A"] if c.page == target_page]
        chunks_bc = [_serialize_chunk(c) for c in chunks_by_strategy["B"] if c.page == target_page]
        coherence_samples.append(
            {
                "pos_id": pos["pos_id"],
                "page": target_page,
                "label": pos["label"],
                "strategy_A_chunks_on_page": chunks_a,
                "strategy_B_C_chunks_on_page": chunks_bc,
                "manual_scores": {"A": None, "B": None, "C": None},
                "manual_notes": {"A": "", "B": "", "C": ""},
            }
        )

    trace_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for strat, strat_traces in traces_by_strategy.items():
        for t in strat_traces:
            trace_lookup[(strat, t["question_id"])] = t

    test_audit: list[dict[str, Any]] = []
    for q in questions:
        if q.get("split") != "test":
            continue
        qid = q["id"]
        per_strategy: dict[str, Any] = {}
        for strat in ("A", "B", "C"):
            t = trace_lookup[(strat, qid)]
            per_strategy[strat] = {
                "applied_filter": t["applied_filter"],
                "filter_compliant": t["filter_compliant"],
                "hit_at_1": t["hit_at_1"],
                "evidence_hit_at_3": t["evidence_hit_at_3"],
                "hits": t["hits"],
                "manual_grounding_score": None,
                "manual_grounding_note": "",
                "manual_metadata_helpful_hits": None,
                "manual_metadata_note": "",
            }
        test_audit.append(
            {
                "question_id": qid,
                "type": q.get("type", ""),
                "section": q.get("section", ""),
                "question": q["question"],
                "expected_answer": q.get("expected_answer", ""),
                "gold_source_id": q["gold_source_id"],
                "gold_page": int(q["gold_page"]),
                "evidence_quote": q.get("evidence_quote", ""),
                "question_filter": q.get("filter"),
                "strategies": per_strategy,
            }
        )

    return {
        "coherence_positions": coherence_samples,
        "test_questions_top3": test_audit,
    }


def main() -> None:
    starter_dir = Path(__file__).resolve().parent.parent
    repo_root = starter_dir.parent
    load_dotenv(starter_dir / ".env")

    database_url = os.getenv("DATABASE_URL", "").strip()
    embedding_model = os.getenv("EMBEDDING_MODEL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured in starter/.env")
    if not embedding_model:
        raise RuntimeError("EMBEDDING_MODEL is not configured in starter/.env")

    manifest_path = repo_root / "data" / "manifest.json"
    benchmark_path = repo_root / "benchmark" / "questions.json"
    results_dir = repo_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    questions: list[dict[str, Any]] = benchmark["questions"]

    # 1. Validate corpus size and benchmark split invariants
    pdf_path = repo_root / manifest["local_file"]
    included_pages: list[int] = [int(p) for p in manifest["included_page_ids"]]
    ingestion_errors: list[dict[str, Any]] = []

    t_ingest0 = time.perf_counter()
    pages = load_pdf(
        path=pdf_path,
        document_id=manifest["source_id"],
        source=manifest["local_file"],
        page_numbers=included_pages,
        error_log=ingestion_errors,
    )
    ingest_seconds = round(time.perf_counter() - t_ingest0, 3)

    if len(pages) < 30:
        raise RuntimeError(f"Corpus must contain at least 30 valid content pages, got {len(pages)}")

    dev_qs = [q for q in questions if q.get("split") == "dev"]
    test_qs = [q for q in questions if q.get("split") == "test"]
    filter_qs = [q for q in questions if q.get("filter")]
    test_filter_qs = [q for q in test_qs if q.get("filter")]
    if len(dev_qs) < 15 or len(test_qs) < 5 or len(filter_qs) < 3 or len(test_filter_qs) < 1:
        raise RuntimeError(
            f"Benchmark invariant failed: dev={len(dev_qs)}, test={len(test_qs)}, "
            f"filter={len(filter_qs)}, test_filter={len(test_filter_qs)}"
        )

    # 2. Build chunks for A (fixed_size), B (by_paragraph), and C (identical chunks to B)
    chunks_a: list[Chunk] = []
    chunks_b: list[Chunk] = []
    for page in pages:
        chunks_a.extend(fixed_size(page, size=500, overlap=50))
        chunks_b.extend(by_paragraph(page, max_size=1000))
    chunks_c: list[Chunk] = list(chunks_b)

    chunks_by_strategy = {"A": chunks_a, "B": chunks_b, "C": chunks_c}
    chunk_stats = {s: _compute_chunk_stats(cs) for s, cs in chunks_by_strategy.items()}

    # 3. Real embedding model + persistent pgvector store
    embedder = MyEmbedder(model_name=embedding_model, batch_size=32)
    store = PgVectorStore(database_url=database_url, dimensions=embedder.dimensions)
    store.create_schema()

    t_emb_a0 = time.perf_counter()
    vectors_a = embedder.embed_documents([c.text for c in chunks_a])
    emb_a_seconds = round(time.perf_counter() - t_emb_a0, 3)

    t_emb_b0 = time.perf_counter()
    vectors_b = embedder.embed_documents([c.text for c in chunks_b])
    emb_b_seconds = round(time.perf_counter() - t_emb_b0, 3)

    t_up_a0 = time.perf_counter()
    upsert_a = store.upsert("A", chunks_a, vectors_a)
    up_a_seconds = round(time.perf_counter() - t_up_a0, 3)

    t_up_b0 = time.perf_counter()
    upsert_b = store.upsert("B", chunks_b, vectors_b)
    up_b_seconds = round(time.perf_counter() - t_up_b0, 3)

    t_up_c0 = time.perf_counter()
    upsert_c = store.upsert("C", chunks_c, vectors_b)
    up_c_seconds = round(time.perf_counter() - t_up_c0, 3)

    # Idempotency check: re-ingesting identical chunks for strategy B must not duplicate chunks
    count_b_before = store.count_chunks("B")
    reingest_b = store.upsert("B", chunks_b, vectors_b)
    count_b_after = store.count_chunks("B")
    idempotency_ok = (
        count_b_before == count_b_after == len(chunks_b) and reingest_b["deleted_obsolete"] == 0
    )

    # 4. Embed queries once and run controlled retrieval across A, B, and C
    t_qemb0 = time.perf_counter()
    query_vectors = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    query_embed_seconds = round(time.perf_counter() - t_qemb0, 3)

    all_traces: list[dict[str, Any]] = []
    traces_by_strategy: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    search_seconds_by_strategy: dict[str, float] = {}

    for strat in ("A", "B", "C"):
        t_s0 = time.perf_counter()
        for q in questions:
            applied_filter = q.get("filter") if strat == "C" else None
            hits = store.search(
                strategy=strat,
                query_vector=query_vectors[q["id"]],
                top_k=3,
                filters=applied_filter,
            )
            trace = evaluate_query(q, hits, strategy=strat, applied_filter=applied_filter)
            traces_by_strategy[strat].append(trace)
            all_traces.append(trace)
        search_seconds_by_strategy[strat] = round(time.perf_counter() - t_s0, 3)

    metrics_summary = summarize(all_traces)

    # 5. Save traces, summary, error log, and audit packet
    for strat in ("A", "B", "C"):
        (results_dir / f"traces_{strat}.json").write_text(
            json.dumps(traces_by_strategy[strat], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    summary_payload: dict[str, Any] = {
        "corpus": {
            "source_id": manifest["source_id"],
            "local_file": manifest["local_file"],
            "requested_pages": len(included_pages),
            "loaded_pages": len(pages),
            "normalized_total_chars": sum(len(p.text) for p in pages),
            "pdf_extract_seconds": ingest_seconds,
            "ingestion_diagnostics_count": len(ingestion_errors),
        },
        "embedding": {
            "provider": embedder.provider,
            "model": embedder.model_name,
            "dimensions": embedder.dimensions,
            "normalized_l2": True,
            "total_doc_texts_embedded": embedder.total_doc_texts,
            "total_doc_chars_embedded": embedder.total_doc_chars,
            "total_query_calls": embedder.total_query_calls,
            "total_embed_seconds": round(embedder.total_embed_seconds, 3),
            "strategy_A_doc_embed_seconds": emb_a_seconds,
            "strategy_B_doc_embed_seconds": emb_b_seconds,
            "strategy_C_note": "Reuses Strategy B chunk vectors identically.",
            "query_embed_seconds_20q": query_embed_seconds,
        },
        "vector_store": {
            "engine": "PostgreSQL + pgvector",
            "pgvector_version": store.pgvector_version,
            "metric": store.metric,
            "search_mode": store.search_mode,
            "upsert_counts": {
                "A": {**upsert_a, "upsert_seconds": up_a_seconds},
                "B": {**upsert_b, "upsert_seconds": up_b_seconds},
                "C": {**upsert_c, "upsert_seconds": up_c_seconds},
            },
            "idempotency_check_B": {
                "count_before": count_b_before,
                "count_after": count_b_after,
                "reingest_result": reingest_b,
                "passed": idempotency_ok,
            },
            "search_seconds_20q": search_seconds_by_strategy,
        },
        "chunk_stats": chunk_stats,
        "benchmark": {
            "total_questions": len(questions),
            "dev_count": len(dev_qs),
            "test_count": len(test_qs),
            "filter_questions_total": len(filter_qs),
            "filter_questions_dev": len([q for q in dev_qs if q.get("filter")]),
            "filter_questions_test": len(test_filter_qs),
        },
        "retrieval_metrics": metrics_summary,
    }

    (results_dir / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (results_dir / "ingestion_errors.json").write_text(
        json.dumps(ingestion_errors, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    audit_packet = _build_audit_samples(chunks_by_strategy, traces_by_strategy, questions)
    (results_dir / "audit_samples.json").write_text(
        json.dumps(audit_packet, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Loaded {len(pages)} pages | Diagnostics: {len(ingestion_errors)}")
    print(f"Chunks: A={chunk_stats['A']['count']}, B={chunk_stats['B']['count']}, C={chunk_stats['C']['count']}")
    print(f"Idempotency B: passed={idempotency_ok} (before={count_b_before}, after={count_b_after})")
    for strat in ("A", "B", "C"):
        d = metrics_summary[strat]["dev"]
        t = metrics_summary[strat]["test"]
        print(
            f"Strategy {strat} | "
            f"dev Hit@1={d['hit1_count']}/{d['total']} ({d['hit1_rate']:.1%}), "
            f"EvHit@3={d['evidence_hit3_count']}/{d['total']} ({d['evidence_hit3_rate']:.1%}) | "
            f"test Hit@1={t['hit1_count']}/{t['total']} ({t['hit1_rate']:.1%}), "
            f"EvHit@3={t['evidence_hit3_count']}/{t['total']} ({t['evidence_hit3_rate']:.1%})"
        )


if __name__ == "__main__":
    main()
