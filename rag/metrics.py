"""Retrieval metrics following the RAGAS definitions, using page-level ground-truth labels.

A retrieved chunk is *relevant* when it comes from the gold (document, page).
  context_precision@K = sum_k (precision@k * rel_k) / (# relevant in top K)      (RAGAS)
  context_recall      = 1 if the gold evidence is present in the top K else 0
                        (each reference answer here is a single attributable claim)
"""
from __future__ import annotations

from .parsing import norm


def relevance(retrieved: list[dict], gold_doc: str, gold_page: int) -> list[int]:
    return [int(c["doc"] == gold_doc and c["page"] == gold_page) for c in retrieved]


def context_precision(rel: list[int]) -> float:
    hits, total = 0, 0.0
    for k, r in enumerate(rel, start=1):
        if r:
            hits += 1
            total += hits / k
    return total / hits if hits else 0.0


def context_recall(rel: list[int]) -> float:
    return float(any(rel))


def reciprocal_rank(rel: list[int]) -> float:
    return next((1.0 / k for k, r in enumerate(rel, start=1) if r), 0.0)


def answer_chunk_hit(retrieved: list[dict], answer: str, k: int = 1) -> float:
    return float(any(norm(answer) in norm(c["text"]) for c in retrieved[:k]))


def retrieval_scores(retrieved: list[dict], row: dict) -> dict:
    rel = relevance(retrieved, row["doc"], row["page"])
    return {"context_precision": context_precision(rel), "context_recall": context_recall(rel),
            "mrr": reciprocal_rank(rel), "hit@1": float(bool(rel and rel[0])),
            "answer_chunk@1": answer_chunk_hit(retrieved, row["answer"], 1)}


def mean_scores(rows: list[dict]) -> dict:
    keys = rows[0].keys()
    return {k: sum(r[k] for r in rows) / len(rows) for k in keys}
