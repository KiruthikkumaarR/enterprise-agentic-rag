"""Regenerate the guardrailed pipeline's test answers (base Phi-4-mini) with the current code."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import config, evaluation, generator, store
from rag.corpus import load_jsonl
from rag.pipeline import RAGPipeline

if __name__ == "__main__":
    store.ensure_qdrant(); print("llm:", generator.ensure_llm(), config.LLM_NAME)
    OUT = config.ARTIFACT_DIR / "eval"
    pipe = RAGPipeline(audit=False)
    full = evaluation.run_queries(pipe, load_jsonl(config.EVAL_DIR / "test_qa.jsonl"), "full", OUT / "full_test.jsonl")
    evaluation.run_queries(pipe, load_jsonl(config.EVAL_DIR / "unanswerable_qa.jsonl"), "full", OUT / "full_unanswerable.jsonl", log_every=0)
    s = evaluation.score_records(full)
    print("full", json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}))
