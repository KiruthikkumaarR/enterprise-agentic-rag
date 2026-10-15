"""Run the full evaluation (same computation as notebook 09) and cache results in artifacts/eval/.

  1. guardrailed pipeline + naive baseline over 200 held-out pairs and 20 unanswerable questions
  2. RAGAS (faithfulness, answer relevancy, LLM context precision / recall) with the Qwen2.5-7B judge

Usage:  python scripts/run_evaluation.py [--skip-ragas]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config, evaluation, generator, store
from rag.corpus import load_jsonl
from rag.pipeline import RAGPipeline

OUT = config.ARTIFACT_DIR / "eval"
ALL_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")   # full RAGAS, LLM judge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ragas", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    store.ensure_qdrant()
    print("llm:", generator.ensure_llm())
    test = load_jsonl(config.EVAL_DIR / "test_qa.jsonl")
    unans = load_jsonl(config.EVAL_DIR / "unanswerable_qa.jsonl")

    if not (OUT / "naive_unanswerable.jsonl").exists():
        pipe = RAGPipeline()
        print("reranker:", pipe.reranker_name)
        t = time.time()
        full = evaluation.run_queries(pipe, test, "full", OUT / "full_test.jsonl")
        naive = evaluation.run_queries(pipe, test, "naive", OUT / "naive_test.jsonl")
        evaluation.run_queries(pipe, unans, "full", OUT / "full_unanswerable.jsonl", log_every=0)
        evaluation.run_queries(pipe, unans, "naive", OUT / "naive_unanswerable.jsonl", log_every=0)
        print(f"generation runs: {(time.time() - t) / 60:.1f} min")
        del pipe
    full = load_jsonl(OUT / "full_test.jsonl")
    naive = load_jsonl(OUT / "naive_test.jsonl")
    for name, recs in (("full", full), ("naive", naive)):
        s = evaluation.score_records(recs)
        print(name, json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}))

    if not args.skip_ragas and not (OUT / "ragas.json").exists():
        t = time.time()
        print("judge:", evaluation.ensure_judge())
        rf, rf_rows = evaluation.ragas_scores(full, ALL_METRICS)
        print("ragas full :", rf)
        rn, rn_rows = evaluation.ragas_scores(naive, ALL_METRICS)
        print("ragas naive:", rn)
        (OUT / "ragas.json").write_text(json.dumps({"full": rf, "naive": rn, "full_rows": rf_rows, "naive_rows": rn_rows},
                                                   indent=2, default=float))
        print(f"RAGAS: {(time.time() - t) / 60:.1f} min")


if __name__ == "__main__":
    main()
