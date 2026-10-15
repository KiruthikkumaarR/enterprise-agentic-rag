"""Central configuration for the Enterprise Agentic RAG Engine.

Every value can be overridden with an environment variable of the same name
prefixed with ``RAG_`` (e.g. ``RAG_LLM_URL``).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# On-premise guarantee: once weights are cached, never contact the Hugging Face Hub
# (no telemetry, no version checks). Set RAG_ALLOW_DOWNLOADS=1 for first-time setup.
if os.environ.get("RAG_ALLOW_DOWNLOADS") != "1":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _env(name: str, default):
    raw = os.environ.get(f"RAG_{name}")
    if raw is None:
        return default
    return type(default)(raw) if not isinstance(default, Path) else Path(raw)


# --- paths -----------------------------------------------------------------
DATA_DIR = _env("DATA_DIR", ROOT / "data")
CORPUS_DIR = DATA_DIR / "corpus"            # raw heterogeneous documents
PROCESSED_DIR = DATA_DIR / "processed"      # parsed chunks (jsonl)
EVAL_DIR = DATA_DIR / "eval"                # ground-truth QA sets
ARTIFACT_DIR = _env("ARTIFACT_DIR", ROOT / "artifacts")
AUDIT_DIR = ARTIFACT_DIR / "audit_logs"
MODEL_DIR = _env("MODEL_DIR", ROOT / "models")
FINETUNED_RERANKER_DIR = MODEL_DIR / "bge-reranker-large-finetuned"

# --- models ----------------------------------------------------------------
EMBED_MODEL = _env("EMBED_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = _env("RERANKER_MODEL", "BAAI/bge-reranker-large")
NLI_MODEL = _env("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli")
# Default generator: Phi-4-mini-instruct with the project's LoRA fine-tune (merged, GGUF Q8_0). It scored best on the
# held-out test set (99.5% correct, 0 wrong answers, 100% citation accuracy). The base model is still available:
#   RAG_LLM_GGUF=models/Phi-4-mini-instruct-Q8_0.gguf RAG_LLM_NAME=phi-4-mini-instruct
_LORA = MODEL_DIR / "Phi-4-mini-instruct-LoRA-Q8_0.gguf"
LLM_GGUF = _env("LLM_GGUF", _LORA if _LORA.exists() else MODEL_DIR / "Phi-4-mini-instruct-Q8_0.gguf")
LLM_NAME = _env("LLM_NAME", "phi-4-mini-lora" if _LORA.exists() else "phi-4-mini-instruct")

# --- services --------------------------------------------------------------
QDRANT_URL = _env("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_BIN = _env("QDRANT_BIN", ROOT / "bin" / "qdrant")
QDRANT_STORAGE = _env("QDRANT_STORAGE", ROOT / "qdrant_storage")
COLLECTION = _env("COLLECTION", "enterprise_docs")
LLM_URL = _env("LLM_URL", "http://127.0.0.1:18090")   # llama.cpp llama-server
LLM_SERVER_BIN = _env("LLM_SERVER_BIN", "llama-server")
LLM_CTX = _env("LLM_CTX", 8192)

# --- retrieval / generation knobs (values from the proposal) ---------------
DENSE_DIM = 1024
HYBRID_CANDIDATES = _env("HYBRID_CANDIDATES", 30)   # top-30 into the reranker
FINAL_TOP_K = _env("FINAL_TOP_K", 5)                # top-5 into the prompt
RRF_K = _env("RRF_K", 60)
RERANK_MIN_SCORE = _env("RERANK_MIN_SCORE", -4.0)   # strict cutoff (logit), pre-trained reranker
# Fine-tuned reranker: calibrated on 211 validation questions whose facts were held out of training
# (lowest gold score +1.68; -2.0 keeps 100% of gold passages and removes 99.3% of irrelevant ones).
RERANK_MIN_SCORE_FINETUNED = _env("RERANK_MIN_SCORE_FINETUNED", -2.0)
TEMPERATURE = 0.0
MAX_NEW_TOKENS = _env("MAX_NEW_TOKENS", 256)
MAX_REGENERATIONS = _env("MAX_REGENERATIONS", 1)
ENTAILMENT_THRESHOLD = _env("ENTAILMENT_THRESHOLD", 0.5)
SEED = 7

for _d in (CORPUS_DIR, PROCESSED_DIR, EVAL_DIR, ARTIFACT_DIR, AUDIT_DIR, MODEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
