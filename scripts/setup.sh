#!/usr/bin/env bash
# One-time setup on Apple Silicon macOS (all downloads happen here; runtime is fully offline).
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-/opt/homebrew/bin/python3.13}
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

command -v llama-server >/dev/null || brew install llama.cpp

mkdir -p bin models
if [ ! -x bin/qdrant ]; then
  curl -sSL https://github.com/qdrant/qdrant/releases/download/v1.19.1/qdrant-aarch64-apple-darwin.tar.gz | tar -xz -C bin
fi

fetch() { [ -s "models/$2" ] || curl -L -C - --retry 5 -o "models/$2" "$1"; }
fetch https://huggingface.co/bartowski/microsoft_Phi-4-mini-instruct-GGUF/resolve/main/microsoft_Phi-4-mini-instruct-Q8_0.gguf \
      Phi-4-mini-instruct-Q8_0.gguf
fetch https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf \
      Qwen2.5-7B-Instruct-Q4_K_M.gguf   # RAGAS judge only

RAG_ALLOW_DOWNLOADS=1 .venv/bin/python - <<'EOF'
from huggingface_hub import snapshot_download
snapshot_download("BAAI/bge-m3", allow_patterns=["*.json", "pytorch_model.bin", "sparse_linear.pt", "sentencepiece.bpe.model"])
snapshot_download("BAAI/bge-reranker-large", allow_patterns=["*.json", "model.safetensors", "sentencepiece.bpe.model"])
snapshot_download("MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli", allow_patterns=["*.json", "model.safetensors", "spm.model"])
EOF
echo "setup complete"
