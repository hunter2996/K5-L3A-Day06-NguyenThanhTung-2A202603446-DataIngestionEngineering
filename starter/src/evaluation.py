"""Evaluate retrieved top-k evidence, preserve traces, and prepare human audit packets."""
from __future__ import annotations

import re
from typing import Any

# 10 deterministic source positions across Chapters 1-3 fixed prior to retrieval runs
# for cross-strategy Chunk Coherence auditing (score 0 / 1 / 2).
COHERENCE_SAMPLE_POSITIONS: list[dict[str, Any]] = [
    {"pos_id": "coh_01", "page": 17, "label": "Ch.1 Introduction & Objectives opening"},
    {"pos_id": "coh_02", "page": 18, "label": "Sec. 1.1 Descriptive vs. Inferential Statistics"},
    {"pos_id": "coh_03", "page": 22, "label": "Sec. 1.2 Qualitative vs. Quantitative Data"},
    {"pos_id": "coh_04", "page": 31, "label": "Sec. 1.2 Stratified & Cluster Sampling"},
    {"pos_id": "coh_05", "page": 38, "label": "Sec. 1.3 Frequency Tables & Rounding"},
    {"pos_id": "coh_06", "page": 78, "label": "Sec. 2.1 Stem-and-Leaf Graph Example"},
    {"pos_id": "coh_07", "page": 87, "label": "Sec. 2.2 Histogram Definition & Intervals"},
    {"pos_id": "coh_08", "page": 99, "label": "Sec. 2.3 Percentiles & Median Position"},
    {"pos_id": "coh_09", "page": 180, "label": "Sec. 3.1 Sample Space & Event Terminology"},
    {"pos_id": "coh_10", "page": 185, "label": "Sec. 3.2 Independent Events Condition"},
]


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _gold_candidates(question: dict[str, Any]) -> list[dict[str, Any]]:
    primary = {
        "gold_source_id": question["gold_source_id"],
        "gold_page": int(question["gold_page"]),
        "evidence_quote": question.get("evidence_quote", ""),
        "evidence_clauses": list(question.get("evidence_clauses") or []),
    }
    candidates = [primary]
    for alt in question.get("alternative_gold") or []:
        candidates.append(
            {
                "gold_source_id": alt["gold_source_id"],
                "gold_page": int(alt["gold_page"]),
                "evidence_quote": alt.get("evidence_quote", ""),
                "evidence_clauses": list(alt.get("evidence_clauses") or []),
            }
        )
    return candidates


def _check_hit_against_gold(hit_text_norm: str, hit: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    same_page = (
        hit.get("document_id") == gold["gold_source_id"]
        and int(hit.get("page", -1)) == int(gold["gold_page"])
    )
    if not same_page:
        return {
            "same_page": False,
            "full_evidence": False,
            "matched_clauses": [],
            "missing_clauses": list(gold.get("evidence_clauses") or []),
        }

    clauses = [_normalize_ws(c) for c in (gold.get("evidence_clauses") or []) if _normalize_ws(c)]
    quote_norm = _normalize_ws(gold.get("evidence_quote", ""))

    if clauses:
        matched = [c for c in clauses if c in hit_text_norm]
        missing = [c for c in clauses if c not in hit_text_norm]
        full_evidence = (len(missing) == 0) or (bool(quote_norm) and quote_norm in hit_text_norm)
    else:
        full_evidence = bool(quote_norm) and quote_norm in hit_text_norm
        matched = [quote_norm] if full_evidence else []
        missing = [] if full_evidence else ([quote_norm] if quote_norm else [])

    return {
        "same_page": True,
        "full_evidence": full_evidence,
        "matched_clauses": matched,
        "missing_clauses": missing,
    }


def hit_matches_filter(hit: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    """Verify whether a returned hit satisfies every key-value predicate in `filters`."""
    if not filters:
        return True
    meta = hit.get("metadata") or {}
    for key, expected in filters.items():
        if key == "document_id":
            if hit.get("document_id") != expected:
                return False
        elif key == "page":
            if int(hit.get("page", -1)) != int(expected):
                return False
        elif meta.get(key) != expected:
            return False
    return True


def evaluate_query(
    question: dict[str, Any],
    hits: list[dict[str, Any]],
    strategy: str = "",
    applied_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate top-3 retrieval hits strictly against source/page & single-chunk gold evidence.

    Never infer manual Chunk Coherence or Grounding Quality scores from string matching.
    """
    gold_list = _gold_candidates(question)
    top3 = hits[:3]

    hit_traces: list[dict[str, Any]] = []
    for rank_idx, hit in enumerate(top3, start=1):
        norm_text = _normalize_ws(hit.get("text", ""))
        best_eval: dict[str, Any] | None = None
        for gold in gold_list:
            cand_eval = _check_hit_against_gold(norm_text, hit, gold)
            if best_eval is None:
                best_eval = cand_eval
            elif cand_eval["full_evidence"] and not best_eval["full_evidence"]:
                best_eval = cand_eval
            elif cand_eval["same_page"] and not best_eval["same_page"]:
                best_eval = cand_eval
            elif (
                cand_eval["same_page"] == best_eval["same_page"]
                and len(cand_eval["matched_clauses"]) > len(best_eval["matched_clauses"])
            ):
                best_eval = cand_eval

        assert best_eval is not None
        matches_intended_filter = (
            hit_matches_filter(hit, question.get("filter"))
            if question.get("filter")
            else None
        )
        hit_traces.append(
            {
                "rank": rank_idx,
                "chunk_id": hit.get("chunk_id"),
                "document_id": hit.get("document_id"),
                "source": hit.get("source"),
                "page": int(hit.get("page", -1)),
                "score": float(hit.get("score", 0.0)),
                "metadata": hit.get("metadata") or {},
                "text": hit.get("text", ""),
                "matches_gold_page": best_eval["same_page"],
                "contains_full_evidence": best_eval["full_evidence"],
                "matched_clauses_count": len(best_eval["matched_clauses"]),
                "missing_clauses_count": len(best_eval["missing_clauses"]),
                "missing_clauses": best_eval["missing_clauses"],
                "matches_question_filter": matches_intended_filter,
            }
        )

    hit_at_1 = bool(hit_traces and hit_traces[0]["contains_full_evidence"])
    evidence_hit_at_3 = any(ht["contains_full_evidence"] for ht in hit_traces)
    source_page_hit_at_1 = bool(hit_traces and hit_traces[0]["matches_gold_page"])
    source_page_hit_at_3 = any(ht["matches_gold_page"] for ht in hit_traces)

    # Detect multi-chunk split cases separately without counting them as single-chunk Hit@3.
    split_evidence_union_top3 = False
    if not evidence_hit_at_3 and source_page_hit_at_3:
        for gold in gold_list:
            page_texts = [
                _normalize_ws(h.get("text", ""))
                for h in top3
                if h.get("document_id") == gold["gold_source_id"]
                and int(h.get("page", -1)) == int(gold["gold_page"])
            ]
            if not page_texts:
                continue
            combined = " ".join(page_texts)
            clauses = [_normalize_ws(c) for c in (gold.get("evidence_clauses") or []) if _normalize_ws(c)]
            if clauses and all(c in combined for c in clauses):
                split_evidence_union_top3 = True
                break

    if applied_filter:
        hits_matching_applied = sum(1 for h in top3 if hit_matches_filter(h, applied_filter))
        filter_compliant: bool | None = len(top3) > 0 and hits_matching_applied == len(top3)
    else:
        hits_matching_applied = None
        filter_compliant = None

    return {
        "strategy": strategy,
        "question_id": question["id"],
        "split": question["split"],
        "type": question.get("type", ""),
        "section": question.get("section", ""),
        "question": question["question"],
        "expected_answer": question.get("expected_answer", ""),
        "gold_source_id": question["gold_source_id"],
        "gold_page": int(question["gold_page"]),
        "alternative_gold_pages": [int(a["gold_page"]) for a in (question.get("alternative_gold") or [])],
        "question_filter": question.get("filter"),
        "applied_filter": applied_filter,
        "hit_at_1": hit_at_1,
        "evidence_hit_at_3": evidence_hit_at_3,
        "source_page_hit_at_1": source_page_hit_at_1,
        "source_page_hit_at_3": source_page_hit_at_3,
        "split_evidence_union_top3": split_evidence_union_top3,
        "filter_compliant": filter_compliant,
        "hits_matching_applied_filter": hits_matching_applied,
        "top_k_count": len(hit_traces),
        "hits": hit_traces,
    }


def _aggregate_group(traces: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(traces)
    if n == 0:
        return {
            "total": 0,
            "hit1_count": 0,
            "hit1_rate": 0.0,
            "evidence_hit3_count": 0,
            "evidence_hit3_rate": 0.0,
            "source_page_hit1_count": 0,
            "source_page_hit1_rate": 0.0,
            "source_page_hit3_count": 0,
            "source_page_hit3_rate": 0.0,
            "split_evidence_union_top3_ids": [],
            "missed_question_ids": [],
        }

    hit1 = sum(1 for t in traces if t["hit_at_1"])
    hit3 = sum(1 for t in traces if t["evidence_hit_at_3"])
    sp1 = sum(1 for t in traces if t["source_page_hit_at_1"])
    sp3 = sum(1 for t in traces if t["source_page_hit_at_3"])
    split_ids = [t["question_id"] for t in traces if t["split_evidence_union_top3"]]
    missed_ids = [t["question_id"] for t in traces if not t["evidence_hit_at_3"]]

    filtered_traces = [t for t in traces if t["applied_filter"]]
    scoped_traces = [t for t in traces if t["question_filter"]]

    scoped_hits_total = sum(len(t["hits"]) for t in scoped_traces)
    scoped_hits_matching = sum(
        sum(1 for h in t["hits"] if h.get("matches_question_filter") is True)
        for t in scoped_traces
    )

    out: dict[str, Any] = {
        "total": n,
        "hit1_count": hit1,
        "hit1_rate": round(hit1 / n, 4),
        "evidence_hit3_count": hit3,
        "evidence_hit3_rate": round(hit3 / n, 4),
        "source_page_hit1_count": sp1,
        "source_page_hit1_rate": round(sp1 / n, 4),
        "source_page_hit3_count": sp3,
        "source_page_hit3_rate": round(sp3 / n, 4),
        "split_evidence_union_top3_count": len(split_ids),
        "split_evidence_union_top3_ids": split_ids,
        "missed_question_ids": missed_ids,
        "scoped_questions_count": len(scoped_traces),
        "scoped_hits_total": scoped_hits_total,
        "scoped_hits_matching_target_filter": scoped_hits_matching,
    }

    if filtered_traces:
        f_total_hits = sum(t["top_k_count"] for t in filtered_traces)
        f_comp_hits = sum(t["hits_matching_applied_filter"] or 0 for t in filtered_traces)
        f_comp_queries = sum(1 for t in filtered_traces if t["filter_compliant"] is True)
        out["applied_filter_queries"] = len(filtered_traces)
        out["filter_compliant_queries"] = f_comp_queries
        out["applied_filter_hits_total"] = f_total_hits
        out["applied_filter_hits_compliant"] = f_comp_hits
    else:
        out["applied_filter_queries"] = 0
        out["filter_compliant_queries"] = None
        out["applied_filter_hits_total"] = 0
        out["applied_filter_hits_compliant"] = None

    return out


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and dev/test split."""
    strategies = sorted({str(t.get("strategy", "")) for t in traces})
    summary: dict[str, Any] = {}
    for strat in strategies:
        strat_traces = [t for t in traces if str(t.get("strategy", "")) == strat]
        summary[strat] = {
            "dev": _aggregate_group([t for t in strat_traces if t.get("split") == "dev"]),
            "test": _aggregate_group([t for t in strat_traces if t.get("split") == "test"]),
            "overall": _aggregate_group(strat_traces),
        }
    return summary
