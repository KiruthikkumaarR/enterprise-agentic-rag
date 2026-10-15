"""BGE-M3 encoder producing dense (1024-d) and sparse lexical vectors in one pass.

Re-implements BGE-M3's two heads directly on top of Hugging Face ``transformers``:
  dense  = L2-normalised [CLS] hidden state
  sparse = ReLU(sparse_linear(hidden_state)) per token, max-pooled per token id,
           special tokens removed (Chen et al., 2024)
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import torch
from huggingface_hub import hf_hub_download
from transformers import AutoModel, AutoTokenizer

from . import config


class BGEM3:
    def __init__(self, name: str = config.EMBED_MODEL, device: str | None = None, max_length: int = 1024):
        self.device = device or config.device()
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModel.from_pretrained(name).to(self.device).eval()
        self.sparse = torch.nn.Linear(1024, 1)
        self.sparse.load_state_dict(torch.load(hf_hub_download(name, "sparse_linear.pt"), map_location="cpu"))
        self.sparse.to(self.device).eval()
        self.max_length = max_length
        self.special = {self.tok.cls_token_id, self.tok.eos_token_id, self.tok.pad_token_id, self.tok.unk_token_id}

    @torch.no_grad()
    def encode(self, texts: list[str], batch_size: int = 16) -> tuple[np.ndarray, list[dict[int, float]]]:
        dense_out, sparse_out = [], []
        for i in range(0, len(texts), batch_size):
            batch = self.tok(texts[i:i + batch_size], padding=True, truncation=True,
                             max_length=self.max_length, return_tensors="pt").to(self.device)
            hidden = self.model(**batch).last_hidden_state
            dense = torch.nn.functional.normalize(hidden[:, 0], dim=-1)
            weights = torch.relu(self.sparse(hidden)).squeeze(-1)
            dense_out.append(dense.float().cpu().numpy())
            ids = batch["input_ids"].cpu().numpy()
            w = weights.float().cpu().numpy()
            for row_ids, row_w in zip(ids, w):
                sp: dict[int, float] = {}
                for t, v in zip(row_ids, row_w):
                    t = int(t)
                    if t in self.special or v <= 0:
                        continue
                    if v > sp.get(t, 0.0):
                        sp[t] = float(v)
                sparse_out.append(sp)
        return np.concatenate(dense_out), sparse_out


@lru_cache(maxsize=1)
def get_embedder() -> BGEM3:
    return BGEM3()
