"""LoRA fine-tune of Phi-4-mini-instruct on grounded, cited domain QA (proposal stretch goal).

Steps (each resumable):
  prepare  build training examples with the real pipeline: hybrid retrieval -> fine-tuned reranker -> parent
           expansion -> the production prompt. Target = the reference sentence cited to the gold source, or
           INSUFFICIENT_EVIDENCE when the gold page is absent (12% of examples have it removed on purpose).
           Uses only training facts: never test facts, never the development (validation) facts.
  train    LoRA (r=16, alpha=32) on attention + MLP projections, loss on answer tokens only, 1 epoch.
  export   merge LoRA into the base weights -> GGUF (llama.cpp converter at the installed commit) -> Q8_0.

Usage:  python scripts/train_lora.py prepare|train|export
"""
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag import config  # noqa: E402

BASE = "microsoft/Phi-4-mini-instruct"
DATA = config.EVAL_DIR / "lora_train.jsonl"
ADAPTER = config.MODEL_DIR / "phi4-mini-lora-adapter"
MERGED = config.MODEL_DIR / "phi4-mini-lora-merged"
GGUF_F16 = config.MODEL_DIR / "Phi-4-mini-instruct-LoRA-F16.gguf"
GGUF_Q8 = config.MODEL_DIR / "Phi-4-mini-instruct-LoRA-Q8_0.gguf"
CONVERTER = next((ROOT / "third_party").glob("llama.cpp-*/convert_hf_to_gguf.py"), None)
N_EXAMPLES = 900


def dev_facts() -> set:
    train = [json.loads(l) for l in open(config.EVAL_DIR / "train_qa.jsonl")]
    facts = sorted({r["fact_id"] for r in train})
    random.Random(config.SEED).shuffle(facts)
    return set(facts[: len(facts) // 10]), train


def prepare():
    from rag import generator, store
    from rag.pipeline import RAGPipeline, expand_to_parents

    store.ensure_qdrant()
    held_out, train = dev_facts()
    rows = [r for r in train if r["fact_id"] not in held_out]
    rng = random.Random(config.SEED)
    rng.shuffle(rows)
    pipe = RAGPipeline(audit=False)
    out, t0 = [], time.time()
    for i, r in enumerate(rows[:N_EXAMPLES]):
        cands = pipe.retriever.retrieve(r["question"], config.HYBRID_CANDIDATES)
        sources = expand_to_parents(pipe.reranker.rerank(r["question"], cands, config.FINAL_TOP_K, pipe.min_score))
        gold = (r["doc"], r["page"])
        if rng.random() < 0.12:                       # teach abstention: remove the evidence
            sources = [s for s in sources if (s["doc"], s["page"]) != gold] or sources[:0]
        idx = next((k for k, s in enumerate(sources, 1) if (s["doc"], s["page"]) == gold), None)
        target = f"{r['ground_truth'].rstrip('.')} [S{idx}]." if idx else generator.REFUSAL_TOKEN
        if not sources:
            continue
        out.append({"messages": generator.build_messages(r["question"], sources), "target": target, "fact_id": r["fact_id"]})
        if (i + 1) % 100 == 0:
            print(f"prepared {i + 1}/{N_EXAMPLES} ({time.time() - t0:.0f}s)", flush=True)
    with open(DATA, "w") as f:
        for o in out:
            f.write(json.dumps(o) + "\n")
    print(f"{len(out)} examples, {sum(o['target'] == generator.REFUSAL_TOKEN for o in out)} abstentions -> {DATA}")


def train(epochs: int = 1, lr: float = 1e-4, accum: int = 8, max_len: int = 2048):
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup

    torch.manual_seed(config.SEED)
    dev = config.device()
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16).to(dev)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["qkv_proj", "o_proj", "gate_up_proj", "down_proj"]))
    for n, p in model.named_parameters():
        if p.requires_grad:
            p.data = p.data.float()                   # keep adapter weights in fp32 for stable optimisation
    model.print_trainable_parameters()

    data = [json.loads(l) for l in open(DATA)]
    examples = []
    for d in data:
        prompt = tok.apply_chat_template(d["messages"], tokenize=False, add_generation_prompt=True)
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(d["target"] + tok.eos_token, add_special_tokens=False)["input_ids"]
        ids = (p_ids + a_ids)[-max_len:]
        labels = ([-100] * len(p_ids) + a_ids)[-max_len:]
        examples.append((ids, labels))
    random.Random(config.SEED).shuffle(examples)
    n_val = 40
    val, tr = examples[:n_val], examples[n_val:]
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    steps = math.ceil(len(tr) * epochs / accum)
    sched = get_cosine_schedule_with_warmup(opt, max(1, int(.06 * steps)), steps)
    hist = {"step": [], "train_loss": [], "val_loss": []}

    def loss_of(ids, labels):
        x = torch.tensor([ids], device=dev)
        y = torch.tensor([labels], device=dev)
        return model(input_ids=x, labels=y).loss

    def evaluate():
        model.eval()
        with torch.no_grad():
            v = sum(loss_of(i, l).item() for i, l in val) / len(val)
        model.train()
        return v

    v0 = evaluate()
    hist["step"].append(0); hist["train_loss"].append(None); hist["val_loss"].append(v0)
    print(f"step 0 val_loss={v0:.4f}", flush=True)
    model.train()
    step, running, t0 = 0, [], time.time()
    for ep in range(epochs):
        for k, (ids, labels) in enumerate(tr, 1):
            loss = loss_of(ids, labels) / accum
            loss.backward()
            running.append(loss.item() * accum)
            if k % accum == 0 or k == len(tr):
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step(); sched.step(); opt.zero_grad()
                step += 1
                if step % 20 == 0 or step == steps:
                    vl = evaluate()
                    tl = sum(running) / len(running); running = []
                    hist["step"].append(step); hist["train_loss"].append(tl); hist["val_loss"].append(vl)
                    print(f"step {step}/{steps} train_loss={tl:.4f} val_loss={vl:.4f} ({time.time() - t0:.0f}s)", flush=True)
                    if dev == "mps":
                        torch.mps.empty_cache()
    model.save_pretrained(ADAPTER)
    hist.update(examples=len(tr), val_examples=n_val, epochs=epochs, lr=lr, accum=accum, seconds=time.time() - t0,
                r=16, alpha=32, targets=["qkv_proj", "o_proj", "gate_up_proj", "down_proj"])
    (ADAPTER / "training_history.json").write_text(json.dumps(hist, indent=2))
    print("saved adapter ->", ADAPTER)


def export(skip_merge: bool = False):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not skip_merge:
        base = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16)
        merged = PeftModel.from_pretrained(base, ADAPTER).merge_and_unload()
        merged.save_pretrained(MERGED, safe_serialization=True)
        del base, merged
    # use Microsoft's original tokenizer files: the llama.cpp converter keys on tokenizer_class == "GPT2Tokenizer"
    from huggingface_hub import hf_hub_download
    import shutil
    for f in ("tokenizer_config.json", "tokenizer.json", "vocab.json", "merges.txt", "added_tokens.json", "special_tokens_map.json"):
        shutil.copy(hf_hub_download(BASE, f, local_files_only=True), MERGED / f)
    env = {"PYTHONPATH": str(CONVERTER.parent / "gguf-py")}
    import os
    subprocess.run([sys.executable, str(CONVERTER), str(MERGED), "--outfile", str(GGUF_F16), "--outtype", "f16"],
                   check=True, env={**os.environ, **env})
    subprocess.run(["llama-quantize", str(GGUF_F16), str(GGUF_Q8), "Q8_0"], check=True)
    GGUF_F16.unlink()
    print("exported ->", GGUF_Q8)


if __name__ == "__main__":
    if sys.argv[1] == "convert":            # re-run conversion only, reusing an existing merged model
        export(skip_merge=True)
    else:
        {"prepare": prepare, "train": train, "export": export}[sys.argv[1]]()
