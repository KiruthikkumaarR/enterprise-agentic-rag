"""Fine-tune bge-reranker-large on the project's own query-passage pairs and compare
pre-trained vs fine-tuned retrieval quality on the 200-pair held-out test set.

Usage:  python scripts/train_reranker.py [--epochs 2]
Writes: models/bge-reranker-large-finetuned/, artifacts/reranker_comparison.json
"""
import argparse
import gc
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from rag import config, metrics, parsing
from rag.corpus import load_jsonl
from rag.reranker import CrossEncoderReranker, build_training_examples, finetune
from rag.retrieval import HybridRetriever
from rag.store import ensure_qdrant


def evaluate_reranker(rr: CrossEncoderReranker, retriever, test_rows, cache):
    per_q = []
    for row in test_rows:
        cands = cache.setdefault(row["qid"], retriever.retrieve(row["question"]))
        top = rr.rerank(row["question"], cands, top_k=config.FINAL_TOP_K, min_score=None)
        per_q.append(metrics.retrieval_scores(top, row))
    return metrics.mean_scores(per_q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=1e-5)
    args = ap.parse_args()

    ensure_qdrant()
    retriever = HybridRetriever()
    chunks = parsing.load_chunks()
    train_rows = load_jsonl(config.EVAL_DIR / "train_qa.jsonl")
    test_rows = load_jsonl(config.EVAL_DIR / "test_qa.jsonl")

    # validation split by *fact* so paraphrases of one fact never straddle train/val
    facts = sorted({r["fact_id"] for r in train_rows})
    random.Random(config.SEED).shuffle(facts)
    val_facts = set(facts[: len(facts) // 10])
    examples = build_training_examples(train_rows, retriever, chunks)
    train_ex = [e for e in examples if e["fact_id"] not in val_facts]
    val_ex = [e for e in examples if e["fact_id"] in val_facts]
    print(f"training examples: {len(train_ex)}  validation: {len(val_ex)}")

    cache = {}
    hybrid_only = metrics.mean_scores([metrics.retrieval_scores(
        cache.setdefault(r["qid"], retriever.retrieve(r["question"]))[: config.FINAL_TOP_K], r) for r in test_rows])
    base = CrossEncoderReranker(config.RERANKER_MODEL)
    before = evaluate_reranker(base, retriever, test_rows, cache)
    print("hybrid only :", hybrid_only)
    print("pre-trained :", before)
    del base; gc.collect(); torch.mps.empty_cache() if torch.backends.mps.is_available() else None

    history = finetune(train_ex, val_ex, epochs=args.epochs, lr=args.lr)
    gc.collect()
    tuned = CrossEncoderReranker(config.FINETUNED_RERANKER_DIR)
    after = evaluate_reranker(tuned, retriever, test_rows, cache)
    print("fine-tuned  :", after)
    out = {"hybrid_rrf_no_rerank": hybrid_only, "pretrained_reranker": before, "finetuned_reranker": after,
           "training": {k: history[k] for k in ("epochs", "lr", "n_train", "n_val", "n_neg", "seconds")}}
    (config.ARTIFACT_DIR / "reranker_comparison.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
