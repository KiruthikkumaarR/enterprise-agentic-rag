"""Generate test-set answers with the LoRA-tuned Phi-4-mini (same retrieval, reranker, prompt and guardrail).

The LoRA GGUF is served by its own llama-server on port 18092, so the base model's results are untouched.
Outputs artifacts/eval_lora/{full_test,full_unanswerable}.jsonl.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["RAG_LLM_GGUF"] = str(ROOT / "models" / "Phi-4-mini-instruct-LoRA-Q8_0.gguf")
os.environ["RAG_LLM_NAME"] = "phi-4-mini-lora"
os.environ["RAG_LLM_URL"] = "http://127.0.0.1:18092"
sys.path.insert(0, str(ROOT))

from rag import config, evaluation, generator, store  # noqa: E402
from rag.corpus import load_jsonl  # noqa: E402
from rag.pipeline import RAGPipeline  # noqa: E402

OUT = config.ARTIFACT_DIR / "eval_lora"

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    store.ensure_qdrant()
    print("llm:", generator.ensure_llm(), config.LLM_NAME, config.LLM_URL)
    pipe = RAGPipeline(audit=False)
    full = evaluation.run_queries(pipe, load_jsonl(config.EVAL_DIR / "test_qa.jsonl"), "full", OUT / "full_test.jsonl")
    evaluation.run_queries(pipe, load_jsonl(config.EVAL_DIR / "unanswerable_qa.jsonl"), "full", OUT / "full_unanswerable.jsonl", log_every=0)
    s = evaluation.score_records(full)
    print("lora", json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}))
