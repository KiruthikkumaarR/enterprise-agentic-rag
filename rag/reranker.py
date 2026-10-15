"""Cross-encoder reranking (bge-reranker-large) and PyTorch fine-tuning with a pairwise ranking loss."""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from . import config
from .parsing import norm


class CrossEncoderReranker:
    def __init__(self, name_or_path: str | Path = config.RERANKER_MODEL, device: str | None = None, max_length: int = 384):
        self.device = device or config.device()
        self.name = str(name_or_path)
        self.tok = AutoTokenizer.from_pretrained(self.name)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.name).to(self.device).eval()
        self.max_length = max_length

    def _batch(self, query: str, passages: list[str]):
        return self.tok([query] * len(passages), passages, padding=True, truncation="only_second",
                        max_length=self.max_length, return_tensors="pt").to(self.device)

    @torch.no_grad()
    def score(self, query: str, passages: list[str], batch_size: int = 32) -> list[float]:
        out = []
        for i in range(0, len(passages), batch_size):
            out += self.model(**self._batch(query, passages[i:i + batch_size])).logits.view(-1).float().cpu().tolist()
        return out

    def rerank(self, query: str, candidates: list[dict], top_k: int = config.FINAL_TOP_K,
               min_score: float | None = config.RERANK_MIN_SCORE) -> list[dict]:
        if not candidates:
            return []
        scores = self.score(query, [c["text"] for c in candidates])
        ranked = sorted(({**c, "rerank_score": s} for c, s in zip(candidates, scores)),
                        key=lambda c: c["rerank_score"], reverse=True)
        if min_score is not None:
            # the cutoff prunes clutter but never empties the context: the best passage always
            # reaches the generator, which can still abstain (and the guardrail still verifies)
            ranked = ranked[:1] + [c for c in ranked[1:] if c["rerank_score"] >= min_score]
        return ranked[:top_k]


# ---------------------------------------------------------------------------
# Fine-tuning
# ---------------------------------------------------------------------------
def build_training_examples(train_rows: list[dict], retriever, chunks, n_neg: int = 7, seed: int = config.SEED):
    """(query, positive chunk, hard negatives mined from the hybrid retriever's top-30)."""
    rng = random.Random(seed)
    by_page: dict[tuple, list] = {}
    for c in chunks:
        by_page.setdefault((c.doc, c.page), []).append(c)
    examples = []
    for row in train_rows:
        gold = (row["doc"], row["page"])
        pos = [c.text for c in by_page.get(gold, []) if norm(row["answer"]) in norm(c.text)]
        if not pos:
            continue
        cands = retriever.retrieve(row["question"])
        negs = [c["text"] for c in cands if (c["doc"], c["page"]) != gold]
        if not negs:
            continue
        examples.append({"query": row["question"], "pos": pos[0], "negs": negs[:n_neg],
                         "fact_id": row["fact_id"]})
    rng.shuffle(examples)
    return examples


def pairwise_loss(scores: torch.Tensor) -> torch.Tensor:
    """scores[:, 0] = positive, scores[:, 1:] = negatives.  RankNet / pairwise logistic loss:
    mean over pairs of log(1 + exp(-(s_pos - s_neg)))."""
    return torch.nn.functional.softplus(-(scores[:, :1] - scores[:, 1:])).mean()


def finetune(examples: list[dict], val_examples: list[dict], out_dir: Path = config.FINETUNED_RERANKER_DIR,
             base: str = config.RERANKER_MODEL, epochs: int = 1, lr: float = 1e-5, queries_per_step: int = 2,
             max_length: int = 256, seed: int = config.SEED, log=print, ckpt_every: int = 100) -> dict:
    torch.manual_seed(seed)
    random.seed(seed)
    rr = CrossEncoderReranker(base, max_length=max_length)
    model, tok, dev = rr.model, rr.tok, rr.device
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * math.ceil(len(examples) / queries_per_step)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    history = {"step": [], "train_loss": [], "val_loss": [], "val_acc": []}

    def forward(batch):
        q, p = [], []
        for ex in batch:
            docs = [ex["pos"]] + ex["negs"]
            q += [ex["query"]] * len(docs)
            p += docs
        enc = tok(q, p, padding=True, truncation="only_second", max_length=max_length, return_tensors="pt").to(dev)
        n = 1 + len(batch[0]["negs"])
        return model(**enc).logits.view(len(batch), n)

    def evaluate():
        model.eval()
        losses, correct = [], 0
        with torch.no_grad():
            for ex in val_examples:
                s = forward([ex])
                losses.append(pairwise_loss(s).item())
                correct += int(s[0].argmax().item() == 0)
        model.train()
        return sum(losses) / max(1, len(losses)), correct / max(1, len(val_examples))

    # equal negatives per example so they stack into one tensor
    n_neg = min(len(e["negs"]) for e in examples + val_examples)
    for e in examples + val_examples:
        e["negs"] = e["negs"][:n_neg]

    # Resumable: a checkpoint (weights + optimiser + scheduler) is written every `ckpt_every`
    # steps; the example order is seeded, so a restart skips exactly the steps already done.
    ckpt = out_dir.parent / f"{out_dir.name}-checkpoint.pt"
    step_done, elapsed, running = 0, 0.0, []
    if ckpt.exists():
        state = torch.load(ckpt, map_location="cpu", weights_only=False)
        model.load_state_dict(state["model"]); opt.load_state_dict(state["opt"]); sched.load_state_dict(state["sched"])
        step_done, elapsed, history = state["step"], state["elapsed"], state["history"]
        log(f"resumed from checkpoint at step {step_done}/{steps}")
    else:
        vl, va = evaluate()
        history["step"].append(0); history["train_loss"].append(None); history["val_loss"].append(vl); history["val_acc"].append(va)
        log(f"step 0  val_loss={vl:.4f}  val_top1={va:.3f}")
    model.train()
    step, t0 = 0, time.time() - elapsed
    for ep in range(epochs):
        random.shuffle(examples)
        for i in range(0, len(examples), queries_per_step):
            if step < step_done:
                step += 1
                continue
            loss = pairwise_loss(forward(examples[i:i + queries_per_step]))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            running.append(loss.item())
            step += 1
            if step % 100 == 0 or step == steps:
                vl, va = evaluate()
                tl = sum(running) / len(running)
                running = []
                history["step"].append(step); history["train_loss"].append(tl)
                history["val_loss"].append(vl); history["val_acc"].append(va)
                log(f"epoch {ep + 1} step {step}/{steps}  train_loss={tl:.4f}  val_loss={vl:.4f}  "
                    f"val_top1={va:.3f}  ({time.time() - t0:.0f}s)")
            if step % ckpt_every == 0 and step < steps:
                torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                            "step": step, "elapsed": time.time() - t0, "history": history}, ckpt)
                log(f"checkpoint saved at step {step}")
    model.eval()
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    history.update(epochs=epochs, lr=lr, n_train=len(examples), n_val=len(val_examples), n_neg=n_neg,
                   seconds=time.time() - t0, base=base)
    (out_dir / "training_history.json").write_text(json.dumps(history, indent=2))
    ckpt.unlink(missing_ok=True)
    return history
