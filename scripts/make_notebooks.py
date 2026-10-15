"""Generate the ten milestone notebooks (01-09 + master) from source.

Usage:  python scripts/make_notebooks.py          # write notebooks/*.ipynb
Then execute with:  python scripts/run_notebooks.py
"""
from pathlib import Path

import nbformat as nbf

NB_DIR = Path(__file__).resolve().parent.parent / "notebooks"
NB_DIR.mkdir(exist_ok=True)

SETUP = '''import os, sys, json, time, warnings, pathlib
warnings.filterwarnings("ignore")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
ROOT = pathlib.Path.cwd().parent if pathlib.Path.cwd().name == "notebooks" else pathlib.Path.cwd()
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
import pandas as pd
import matplotlib.pyplot as plt
pd.set_option("display.max_colwidth", 120)
from rag import config'''


def nb(title: str, intro: str, cells: list[tuple[str, str]]):
    n = nbf.v4.new_notebook()
    n.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    n.cells.append(nbf.v4.new_markdown_cell(f"# {title}\n\n{intro}"))
    n.cells.append(nbf.v4.new_code_cell(SETUP))
    for kind, src in cells:
        n.cells.append(nbf.v4.new_markdown_cell(src) if kind == "md" else nbf.v4.new_code_cell(src))
    return n


NOTEBOOKS = {}

# ---------------------------------------------------------------------------
NOTEBOOKS["01_environment_diagnostics.ipynb"] = nb(
    "Milestone 1 - System setup & Qdrant / llama.cpp diagnostics",
    "Verifies the local, fully on-premise environment before any modelling: Python/PyTorch and the Apple-Silicon "
    "GPU (MPS) backend, the model weights on disk, the **Qdrant** vector database and the **llama.cpp** "
    "`llama-server` hosting **Phi-4-mini-instruct (3.8B, Q8_0 GGUF)**. Nothing here calls an external API.",
    [("code", '''import platform, subprocess, torch, transformers, qdrant_client, fastapi
info = {
    "python": platform.python_version(), "platform": platform.platform(),
    "cpu": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip(),
    "ram_gb": round(int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30, 1),
    "torch": torch.__version__, "transformers": transformers.__version__,
    "qdrant_client": qdrant_client.__version__ if hasattr(qdrant_client, "__version__") else "n/a",
    "fastapi": fastapi.__version__, "device": config.device(),
}
pd.Series(info).to_frame("value")'''),
     ("md", "### Model weights present locally"),
     ("code", '''from huggingface_hub import scan_cache_dir
cache = {r.repo_id: r for r in scan_cache_dir().repos}
rows = []
for name, role in [(config.EMBED_MODEL, "embedder"), (config.RERANKER_MODEL, "reranker"), (config.NLI_MODEL, "guardrail NLI")]:
    rows.append({"model": name, "role": role, "size_gb": round(cache[name].size_on_disk / 1e9, 2) if name in cache else None})
rows.append({"model": config.LLM_GGUF.name, "role": "generator (llama.cpp)", "size_gb": round(config.LLM_GGUF.stat().st_size / 1e9, 2)})
ft = config.FINETUNED_RERANKER_DIR
rows.append({"model": ft.name, "role": "fine-tuned reranker", "size_gb": round(sum(f.stat().st_size for f in ft.rglob('*') if f.is_file()) / 1e9, 2) if ft.exists() else None})
pd.DataFrame(rows)'''),
     ("md", "### Qdrant vector database"),
     ("code", '''from rag import store
print("Qdrant:", store.ensure_qdrant())
import requests
print(requests.get(f"{config.QDRANT_URL}/").json())
print("collections:", [c.name for c in store.client().get_collections().collections])'''),
     ("md", "### llama.cpp server with Phi-4-mini"),
     ("code", '''from rag import generator
print("llama-server:", generator.ensure_llm())
print(subprocess.run([config.LLM_SERVER_BIN, "--version"], capture_output=True, text=True).stderr.strip().splitlines()[0])
print(requests.get(f"{config.LLM_URL}/v1/models").json()["data"][0]["id"])
r = generator.chat([{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=5)
print("response:", r["text"], "| latency %.2fs" % r["latency_s"])'''),
     ("code", '''t = time.time(); x = torch.randn(4096, 4096, device=config.device()); y = (x @ x).sum().item()
print(f"GPU matmul smoke test on {config.device()}: {time.time() - t:.3f}s")
print("Environment verified: all components local, no external API keys configured.")'''),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["02_document_parsing.ipynb"] = nb(
    "Milestone 2 - Document parsing & parent-child chunking",
    "Builds the synthetic, de-identified enterprise corpus (PDF, DOCX, CSV, Markdown) together with the labelled "
    "QA sets, then parses every document **layout-aware**: tables are detected and converted to Markdown, headings "
    "define the section hierarchy, and documents are split into *parent* units (page / section / row - the unit we "
    "cite) and *child* chunks (paragraph groups or whole tables - the unit we embed). PII (e-mail addresses and "
    "phone numbers) is redacted before anything is indexed.",
    [("code", '''from rag import corpus, parsing
summary = corpus.build_corpus()          # deterministic (seeded) - rebuilds identical files
summary'''),
     ("code", '''docs = pd.DataFrame([{"document": p.name, "format": p.suffix[1:], "kb": round(p.stat().st_size / 1024, 1)}
                     for p in sorted(config.CORPUS_DIR.iterdir())])
docs'''),
     ("code", '''chunks = parsing.parse_corpus()
parsing.save_chunks(chunks)
df = pd.DataFrame([{**c.__dict__, "words": len(c.text.split())} for c in chunks])
print(f"{len(chunks)} child chunks from {df.parent_id.nunique()} parent units")
df.groupby(["doc_type", "kind"]).agg(chunks=("chunk_id", "count"), mean_words=("words", "mean")).round(1)'''),
     ("md", "### Table structure survives parsing\nA table from a PDF page (detected geometrically by PyMuPDF) and one from a Word document:"),
     ("code", '''print(next(c.text for c in chunks if c.doc_type == "pdf" and c.kind == "table"))
print()
print(next(c.text for c in chunks if c.doc_type == "docx" and c.kind == "table"))'''),
     ("md", "### Parent-child structure\nOne PDF page = one parent; its children are the paragraph groups and the table on that page."),
     ("code", '''pid = next(c.parent_id for c in chunks if c.doc.startswith("HIS_Annual") and c.page == 3)
for c in chunks:
    if c.parent_id == pid:
        print(f"--- child {c.chunk_id} ({c.kind})\\n{c.text}\\n")'''),
     ("md", "### CSV rows and Markdown sections"),
     ("code", '''print(next(c.text for c in chunks if c.doc_type == "csv"))
print()
print(next(c.text for c in chunks if c.doc_type == "md" and c.page == 1))'''),
     ("md", "### PII redaction"),
     ("code", '''raw = (config.CORPUS_DIR / "engineering_meeting_notes.md").read_text().split("## ")[1].splitlines()[2]
print("raw     :", raw)
print("indexed :", parsing.redact_pii(raw))
assert not any("@" in c.text for c in chunks), "e-mail address leaked into index"'''),
     ("md", "### Ground-truth validation\nEvery one of the labelled facts must literally appear on the page it is labelled with."),
     ("code", '''facts = corpus.load_jsonl(config.EVAL_DIR / "facts.jsonl")
v = parsing.validate_ground_truth(chunks, facts)
print(f"checked {v['checked']} facts - missing on labelled page: {v['missing']}")
test = pd.DataFrame(corpus.load_jsonl(config.EVAL_DIR / "test_qa.jsonl"))
print(f"held-out test set: {len(test)} QA pairs;  reranker training questions: {len(corpus.load_jsonl(config.EVAL_DIR / 'train_qa.jsonl'))}")
test.groupby("doc").size().rename("test pairs").to_frame()'''),
     ("code", '''test.sample(8, random_state=1)[["question", "answer", "doc", "page"]]'''),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["03_vector_indexing.ipynb"] = nb(
    "Milestone 3 - Hybrid vector store (BGE-M3 + Qdrant)",
    "**BGE-M3** (XLM-RoBERTa-large encoder) produces, in a single forward pass, a 1024-d dense vector "
    "(normalised [CLS]) and a sparse lexical vector (ReLU of a learned per-token weight, max-pooled per token id). "
    "Both are stored in one **Qdrant** collection with an HNSW index and **int8 scalar quantisation**.",
    [("code", '''from rag import parsing, store
from rag.embedder import get_embedder
chunks = parsing.load_chunks()
emb = get_embedder()
t = time.time()
dense, sparse = emb.encode([c.text for c in chunks])
print(f"encoded {len(chunks)} chunks in {time.time() - t:.1f}s on {emb.device}; dense shape {dense.shape}")'''),
     ("md", "### What the sparse head learns\nTop-weighted tokens for one chunk - the model up-weights rare, discriminative terms (model codes, numbers)."),
     ("code", '''i = next(k for k, c in enumerate(chunks) if c.kind == "table" and c.doc_type == "docx")
top = sorted(sparse[i].items(), key=lambda kv: -kv[1])[:12]
print(chunks[i].text[:200], "...\\n")
pd.DataFrame([(emb.tok.convert_ids_to_tokens(t), round(w, 3)) for t, w in top], columns=["token", "weight"])'''),
     ("code", '''import numpy as np
print("mean non-zero sparse terms per chunk:", round(np.mean([len(s) for s in sparse]), 1))
print("dense L2 norms (should be 1):", np.linalg.norm(dense, axis=1)[:5].round(4))'''),
     ("md", "### Create the collection and index"),
     ("code", '''print(store.ensure_qdrant())
qc = store.client()
store.create_collection(qc)
n = store.index_chunks(qc, chunks, dense, sparse)
info = qc.get_collection(config.COLLECTION)
print("indexed points:", n, "| status:", info.status)
cfg = info.config
print("dense:", cfg.params.vectors["dense"].size, cfg.params.vectors["dense"].distance, "| HNSW m =", cfg.hnsw_config.m, "ef_construct =", cfg.hnsw_config.ef_construct)
print("quantisation:", cfg.quantization_config)
print("sparse vectors:", list(cfg.params.sparse_vectors.keys()))'''),
     ("md", "### Memory effect of int8 quantisation (dense vectors)"),
     ("code", '''f32 = len(chunks) * config.DENSE_DIM * 4
i8 = len(chunks) * config.DENSE_DIM * 1
print(f"float32: {f32/1024:.0f} KiB   int8: {i8/1024:.0f} KiB   (4x smaller; originals kept on disk for rescoring)")
for n_docs in (1e5, 1e6, 1e7):
    print(f"  at {int(n_docs):>10,} chunks: float32 {n_docs*4096/2**30:6.1f} GiB  ->  int8 {n_docs*1024/2**30:5.1f} GiB")'''),
     ("md", "### Quantised search agrees with exact search"),
     ("code", '''from qdrant_client import models
q = "maximum head of the HX-320 pump"
qd, qs = emb.encode([q])
approx = [p.payload["chunk_id"] for p in store.search_dense(qc, qd[0], 5)]
exact = [p.payload["chunk_id"] for p in qc.query_points(config.COLLECTION, query=qd[0].tolist(), using="dense", limit=5,
         search_params=models.SearchParams(exact=True, quantization=models.QuantizationSearchParams(ignore=True))).points]
print("HNSW+int8:", approx); print("exact    :", exact); print("overlap@5:", len(set(approx) & set(exact)) / 5)'''),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["04_hybrid_retrieval.ipynb"] = nb(
    "Milestone 4 - Hybrid retrieval & Reciprocal Rank Fusion",
    "Sparse (lexical, BM25-like) and dense (semantic) searches run against Qdrant and their ranked lists are merged "
    "with **Reciprocal Rank Fusion**: `score(d) = sum_i 1/(k + rank_i(d))`, k = 60 (Cormack et al., 2009). "
    "Evaluated on the 200-pair held-out test set with page-level relevance labels.",
    [("code", '''from rag import metrics, store
from rag.corpus import load_jsonl
from rag.retrieval import HybridRetriever, rrf_fuse
store.ensure_qdrant()
r = HybridRetriever()
test = load_jsonl(config.EVAL_DIR / "test_qa.jsonl")'''),
     ("md", "### Anatomy of one query"),
     ("code", '''q = "What is the most liquid the HX-360 can move per minute?"
dense_q, sparse_q = r.encode_query(q)
lists = {"dense": store.search_dense(r.qc, dense_q, 10), "sparse": store.search_sparse(r.qc, sparse_q, 10)}
fused = rrf_fuse(lists)
pd.DataFrame([{k: f.get(k) for k in ("chunk_id", "dense_rank", "sparse_rank", "rrf_score")} for f in fused[:8]])'''),
     ("md", "### Dense vs sparse vs hybrid on the test set (top-5)"),
     ("code", '''rows = {"dense only": [], "sparse only": [], "hybrid (RRF)": []}
lat = []
for row in test:
    rows["dense only"].append(metrics.retrieval_scores(r.retrieve_single(row["question"], "dense", 5), row))
    rows["sparse only"].append(metrics.retrieval_scores(r.retrieve_single(row["question"], "sparse", 5), row))
    t = time.perf_counter(); cands = r.retrieve(row["question"], 30); lat.append(time.perf_counter() - t)
    rows["hybrid (RRF)"].append(metrics.retrieval_scores(cands[:5], row))
    row["_recall30"] = metrics.context_recall(metrics.relevance(cands, row["doc"], row["page"]))
res = pd.DataFrame({k: metrics.mean_scores(v) for k, v in rows.items()}).T.round(3)
res'''),
     ("code", '''print(f"hybrid candidate recall@30 (what the reranker gets to see): {sum(r_['_recall30'] for r_ in test)/len(test):.3f}")
print(f"hybrid retrieval latency: mean {1000*sum(lat)/len(lat):.0f} ms, max {1000*max(lat):.0f} ms")
ax = res[["context_precision", "context_recall", "mrr", "hit@1"]].T.plot.bar(figsize=(8, 3.5), rot=0)
ax.set_ylim(0.5, 1.02); ax.set_title("Retrieval quality on 200 held-out queries (top-5)"); plt.tight_layout()
plt.savefig(config.ARTIFACT_DIR / "retrieval_comparison.png", dpi=120); plt.show()'''),
     ("md", "Dense search alone misses exact identifiers (asset IDs, work-order numbers); sparse search alone misses paraphrases. "
            "Fusion keeps recall@30 essentially perfect, but top-1 precision is still limited - which is what the cross-encoder in Milestone 5 fixes."),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["05_reranker_integration.ipynb"] = nb(
    "Milestones 5-6 - Cross-encoder reranker + fine-tuning",
    "`BAAI/bge-reranker-large` jointly encodes (query, passage) and outputs a relevance logit. It narrows the 30 hybrid "
    "candidates to the top 5. We fine-tune it in PyTorch on the project's own labelled pairs with a **pairwise "
    "(RankNet) loss** `log(1 + exp(-(s_pos - s_neg)))`, using hard negatives mined from the hybrid retriever. "
    "Training facts and test facts are disjoint. Training is run by `scripts/train_reranker.py` "
    "(about 45 min on an M4 Max); this notebook re-runs it only if no fine-tuned checkpoint exists.",
    [("code", '''import subprocess
if not (config.FINETUNED_RERANKER_DIR / "model.safetensors").exists():
    subprocess.run([sys.executable, "scripts/train_reranker.py"], check=True)
hist = json.loads((config.FINETUNED_RERANKER_DIR / "training_history.json").read_text())
comp = json.loads((config.ARTIFACT_DIR / "reranker_comparison.json").read_text())
print({k: hist[k] for k in ("base", "epochs", "lr", "n_train", "n_val", "n_neg")}, f"training time {hist['seconds']/60:.1f} min")'''),
     ("md", "### Training curve"),
     ("code", '''h = pd.DataFrame({k: hist[k] for k in ("step", "train_loss", "val_loss", "val_acc")})
fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
h.plot(x="step", y=["train_loss", "val_loss"], ax=ax[0], marker="o"); ax[0].set_title("pairwise loss")
h.plot(x="step", y="val_acc", ax=ax[1], marker="o", color="C2", legend=False); ax[1].set_title("validation top-1 (pos vs 7 hard negs)")
plt.tight_layout(); plt.savefig(config.ARTIFACT_DIR / "reranker_training_curve.png", dpi=120); plt.show()
h'''),
     ("md", "### Before vs after fine-tuning (200 held-out queries, top-5 after reranking)"),
     ("code", '''cmp = pd.DataFrame({"hybrid RRF (no reranker)": comp["hybrid_rrf_no_rerank"],
                    "pre-trained bge-reranker-large": comp["pretrained_reranker"],
                    "fine-tuned bge-reranker-large": comp["finetuned_reranker"]}).T.round(4)
cmp["hit@1 errors"] = ((1 - cmp["hit@1"]) * 200).round().astype(int)
cmp'''),
     ("md", "### Which queries changed?"),
     ("code", '''from rag.corpus import load_jsonl
from rag.retrieval import HybridRetriever
from rag.reranker import CrossEncoderReranker
from rag import metrics, store
store.ensure_qdrant()
r = HybridRetriever(); test = load_jsonl(config.EVAL_DIR / "test_qa.jsonl")
base = CrossEncoderReranker(config.RERANKER_MODEL); tuned = CrossEncoderReranker(config.FINETUNED_RERANKER_DIR)
diff, pos_scores, neg_scores = [], {"pre-trained": [], "fine-tuned": []}, {"pre-trained": [], "fine-tuned": []}
for row in test:
    c = r.retrieve(row["question"])
    out = {}
    for name, m in (("pre-trained", base), ("fine-tuned", tuned)):
        top = m.rerank(row["question"], c, 30, None)
        rel = metrics.relevance(top, row["doc"], row["page"])
        out[name] = (top[0]["doc"], top[0]["page"], rel[0])
        pos_scores[name] += [t["rerank_score"] for t, x in zip(top, rel) if x]
        neg_scores[name] += [t["rerank_score"] for t, x in zip(top, rel) if not x]
    if out["pre-trained"][2] != out["fine-tuned"][2]:
        diff.append({"question": row["question"], "gold": f'{row["doc"]} p{row["page"]}',
                     "pre-trained top-1": f'{out["pre-trained"][0]} p{out["pre-trained"][1]}',
                     "fine-tuned top-1": f'{out["fine-tuned"][0]} p{out["fine-tuned"][1]}'})
pd.DataFrame(diff)'''),
     ("md", "### Score separation and the strict cutoff\nFine-tuning widens the margin between relevant and irrelevant passages, "
            "which is what lets a fixed cutoff drop clutter from the context window without losing evidence."),
     ("code", '''import numpy as np
fig, ax = plt.subplots(1, 2, figsize=(11, 3.2), sharey=True)
for a, name in zip(ax, ("pre-trained", "fine-tuned")):
    a.hist(neg_scores[name], bins=40, alpha=.6, label="irrelevant", density=True)
    a.hist(pos_scores[name], bins=40, alpha=.6, label="relevant (gold page)", density=True)
    cut = config.RERANK_MIN_SCORE if name == "pre-trained" else config.RERANK_MIN_SCORE_FINETUNED
    a.axvline(cut, color="k", ls="--", lw=1); a.set_title(f"{name} (cutoff {cut})"); a.legend()
plt.tight_layout(); plt.savefig(config.ARTIFACT_DIR / "reranker_score_separation.png", dpi=120); plt.show()
for name in ("pre-trained", "fine-tuned"):
    p, n = np.array(pos_scores[name]), np.array(neg_scores[name])
    cut = config.RERANK_MIN_SCORE if name == "pre-trained" else config.RERANK_MIN_SCORE_FINETUNED
    print(f"{name:12s} cutoff {cut}: relevant kept {np.mean(p >= cut):.3f}   irrelevant removed: {np.mean(n < cut):.3f}"
          f"   median margin: {np.median(p) - np.median(n):.2f}")'''),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["06_rag_synthesis.ipynb"] = nb(
    "Milestone 7 - RAG master prompt & grounded generation",
    "The top-5 reranked child chunks are expanded to their parent page / section / row, numbered `[S1]..[Sn]` with "
    "document name and page, and inserted into a grounded system prompt. **Phi-4-mini-instruct** (llama.cpp, "
    "temperature 0.0, fixed seed) must answer only from those sources and cite every sentence.",
    [("code", '''from rag import generator, store
from rag.pipeline import RAGPipeline
store.ensure_qdrant(); generator.ensure_llm()
pipe = RAGPipeline(audit=False)
print("reranker:", pipe.reranker_name)
print(generator.SYSTEM_PROMPT.format(company="Halvorsen Industrial Systems"))'''),
     ("md", "### The exact prompt for one question"),
     ("code", '''q = "How heavy is the HX-250 when empty?"
cands = pipe.retriever.retrieve(q)
top = pipe.reranker.rerank(q, cands)
from rag.pipeline import expand_to_parents
sources = expand_to_parents(top)
print(generator.build_messages(q, sources)[1]["content"][:2500])'''),
     ("code", '''out = generator.chat(generator.build_messages(q, sources))
print("raw model output:", out["text"]); print("tokens:", out["usage"], "| %.2fs" % out["latency_s"])'''),
     ("md", "### End-to-end answers with rendered citations"),
     ("code", '''questions = ["What is the maximum head of the HX-320 pump?", "How long must CCTV footage be kept?",
             "Who leads the Bilbao Plant site?", "When was CU-4 firmware 4.6 released?",
             "What caused the VPN gateway outage?", "How many days lead time does supplier Polaris Polymers have?"]
rows = []
for q in questions:
    res = pipe.answer(q)
    rows.append({"question": q, "status": res["status"], "answer": res["answer"], "seconds": round(res["timings_s"]["total"], 2)})
pd.DataFrame(rows)'''),
     ("md", "### Out-of-scope questions are refused, not invented"),
     ("code", '''for q in ["What is the CEO's annual salary?", "What is the maximum flow rate of the HX-990 pump?", "What was group revenue in FY2019?"]:
    res = pipe.answer(q)
    print(f"{q}\\n  -> [{res['status']}] {res['answer']}\\n")'''),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["07_guardrail_verifier.ipynb"] = nb(
    "Milestone 8 - Faithfulness & citation guardrail",
    "An **independent** verifier checks every sentence of a candidate answer before it reaches the user: "
    "(1) it must cite an existing source, (2) every number in it must appear in the cited source, and "
    "(3) an NLI cross-encoder (DeBERTa-v3-large trained on MNLI/FEVER/ANLI/LingNLI/WANLI) must judge it "
    "*entailed* by the cited source (max over sentence/table-row premises, p >= 0.5). Failures trigger one "
    "bounded regeneration with feedback, then removal of unverifiable sentences or an explicit "
    "\"cannot be verified\" fallback.",
    [("code", '''from rag import guardrail, parsing
from rag.corpus import load_jsonl
from rag import evaluation
chunks = parsing.load_chunks()
src = [next({"doc": c.doc, "doc_type": c.doc_type, "page": c.page, "section": c.section, "text": c.parent_text}
            for c in chunks if c.doc.startswith("HX_Pump_Series") and c.page == 6)]
print(src[0]["text"])'''),
     ("md", "### How the source is turned into NLI premises"),
     ("code", '''for w in guardrail.premise_windows(src[0]): print("-", w)'''),
     ("md", "### Verifying a mixed answer"),
     ("code", '''import re
model = re.search(r"HX-\\d+", src[0]["section"]).group()
true_head = re.search(r"Maximum head \\| (\\d+ m)", src[0]["text"]).group(1)
answer = (f"The maximum head of the {model} is {true_head} [S1]. "
          f"The {model} has a dry weight of 12 kg [S1]. "
          f"The {model} is certified for use on offshore platforms [S1]. "
          f"It is the most popular pump in the range.")
v = guardrail.verify(answer, src, question=f"Tell me about the {model}")
print("status:", v["status"], "| faithfulness:", v["faithfulness"])
pd.DataFrame(v["claims"])[["claim", "citations", "numbers_ok", "entailment", "supported", "reason"]]'''),
     ("md", "### Stress test on 120 held-out facts\nFor each fact: the correct reference sentence (should pass), the same sentence with the value "
            "swapped for another value from the same document (should be caught), and a true sentence about a different fact "
            "cited to the wrong page (should be caught)."),
     ("code", '''test = load_jsonl(config.EVAL_DIR / "test_qa.jsonl"); facts = load_jsonl(config.EVAL_DIR / "facts.jsonl")
t = time.time()
st = evaluation.guardrail_stress(test, facts, chunks, n=120)
print(f"{st['n']} facts x 3 variants in {time.time() - t:.0f}s")
summary = pd.Series({k: st[k] for k in ("correct_accepted", "corrupted_caught", "foreign_caught")}).round(3)
(config.ARTIFACT_DIR / "guardrail_stress.json").write_text(json.dumps({k: v for k, v in st.items() if k != "examples"}, indent=2))
summary.to_frame("rate")'''),
     ("code", '''ex = pd.DataFrame(st["examples"])
print("Misclassified examples:")
ex[((ex.kind == "correct") & ~ex.passed) | ((ex.kind != "correct") & ex.passed)][["kind", "claim", "entailment", "reason"]].head(12)'''),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["08_api_ui_server.ipynb"] = nb(
    "Milestone 9 - FastAPI server & web interface",
    "`api/server.py` exposes the pipeline as a REST API (`POST /api/query`, `GET /api/health`, rendered PDF pages for "
    "the citation drawer) and serves the single-page UI in `api/static/index.html`. This notebook starts the server, "
    "exercises every endpoint and shuts it down again. To use the UI interactively run "
    "`.venv/bin/uvicorn api.server:app --port 8000` and open http://127.0.0.1:8000.",
    [("code", '''import subprocess, requests
PORT = 8765
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.server:app", "--port", str(PORT), "--log-level", "warning"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{PORT}"
for _ in range(240):
    try:
        if requests.get(base + "/api/health", timeout=1).ok: break
    except requests.RequestException: pass
    time.sleep(1)
requests.get(base + "/api/health").json()'''),
     ("code", '''t = time.time()
resp = requests.post(base + "/api/query", json={"question": "What is the hotel cap per night outside capital cities?"}).json()
print(f"HTTP round trip {time.time() - t:.2f}s")
{k: resp[k] for k in ("status", "answer", "citations", "regenerations", "timings_s")}'''),
     ("code", '''naive = requests.post(base + "/api/query", json={"question": "What is the hotel cap per night outside capital cities?", "mode": "naive"}).json()
{k: naive[k] for k in ("status", "answer", "citations")}'''),
     ("md", "### Citation drawer support: page rendering"),
     ("code", '''from IPython.display import Image, display
c = resp["citations"][0]
img = requests.get(f"{base}/api/documents/{c['doc']}/page/{c['page']}.png")
print(img.status_code, img.headers["content-type"], len(img.content), "bytes")
display(Image(img.content, width=420))'''),
     ("code", '''print("UI page:", requests.get(base + "/").status_code, "| documents:", requests.get(base + "/api/documents").json()[:4], "...")
print("input validation:", requests.post(base + "/api/query", json={"question": ""}).status_code)
print("path traversal blocked:", requests.get(base + "/api/documents/..%2F..%2Frag%2Fconfig.py/raw").status_code)
shot = config.ARTIFACT_DIR / "ui_screenshot.jpg"
if shot.exists(): display(Image(str(shot), width=900))'''),
     ("code", '''srv.terminate(); srv.wait(10); print("server stopped")'''),
     ])

# ---------------------------------------------------------------------------
NOTEBOOKS["09_evaluation_scorecard.ipynb"] = nb(
    "Milestone 10 - Evaluation scorecard (RAGAS)",
    "Runs the **guardrailed pipeline** and the **naive-RAG baseline** (dense top-5, no reranking, no verification, same "
    "generator and prompt) over the 200 held-out QA pairs plus 20 deliberately unanswerable questions, then scores "
    "them with (a) label-based metrics - RAGAS context precision / recall against the gold page, answer correctness, "
    "citation accuracy, latency - and (b) the **RAGAS framework** itself (faithfulness, answer relevancy, LLM context "
    "precision / recall) using an independent local judge, Qwen2.5-7B-Instruct served by llama.cpp. "
    "Full audit logs are written for every query.",
    [("code", '''from rag import evaluation, generator, store
from rag.corpus import load_jsonl
from rag.pipeline import RAGPipeline
store.ensure_qdrant(); generator.ensure_llm()
test = load_jsonl(config.EVAL_DIR / "test_qa.jsonl"); unans = load_jsonl(config.EVAL_DIR / "unanswerable_qa.jsonl")
OUT = config.ARTIFACT_DIR / "eval"; OUT.mkdir(exist_ok=True)
RECOMPUTE = not (OUT / "full_test.jsonl").exists()
print("recompute:", RECOMPUTE)'''),
     ("code", '''if RECOMPUTE:
    pipe = RAGPipeline()
    print("reranker:", pipe.reranker_name)
    t = time.time()
    full = evaluation.run_queries(pipe, test, "full", OUT / "full_test.jsonl")
    naive = evaluation.run_queries(pipe, test, "naive", OUT / "naive_test.jsonl")
    full_u = evaluation.run_queries(pipe, unans, "full", OUT / "full_unanswerable.jsonl", log_every=0)
    naive_u = evaluation.run_queries(pipe, unans, "naive", OUT / "naive_unanswerable.jsonl", log_every=0)
    print(f"generation runs finished in {(time.time() - t)/60:.1f} min")
else:
    full, naive, full_u, naive_u = (load_jsonl(OUT / f) for f in ("full_test.jsonl", "naive_test.jsonl", "full_unanswerable.jsonl", "naive_unanswerable.jsonl"))'''),
     ("md", "### Label-based scorecard"),
     ("code", '''sf, sn = evaluation.score_records(full), evaluation.score_records(naive)
uf, un = evaluation.score_unanswerable(full_u), evaluation.score_unanswerable(naive_u)
keys = ["context_precision", "context_recall", "answered", "correct", "correct_strict", "wrong_answer", "citation_accuracy", "citation_precision",
        "nli_faithfulness", "regenerated", "latency_mean", "latency_p50", "latency_p95", "within_3_5s"]
tbl = pd.DataFrame({"naive RAG baseline": {k: sn[k] for k in keys}, "guardrailed pipeline": {k: sf[k] for k in keys}})
tbl.loc["unanswerable: correct refusal"] = [un["correct_refusal_rate"], uf["correct_refusal_rate"]]
tbl.round(3)'''),
     ("code", '''print("status counts  full :", sf["status_counts"]); print("status counts  naive:", sn["status_counts"])
print("\\nnaive baseline hallucinated on unanswerable questions:"); [print("  ", h) for h in un["hallucinated_answers"]]
print("\\nguardrailed pipeline hallucinated on unanswerable questions:"); [print("  ", h) for h in uf["hallucinated_answers"]]'''),
     ("md", "### RAGAS framework scores (independent judge: Qwen2.5-7B-Instruct)\n"
            "All four RAGAS metrics - faithfulness, answer relevancy, LLM context precision (with reference) and LLM context "
            "recall - scored by the judge model."),
     ("code", '''RAGAS_FILE = OUT / "ragas.json"
if RECOMPUTE or not RAGAS_FILE.exists():
    t = time.time()
    ALL = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    rf, rf_rows = evaluation.ragas_scores(full, ALL)
    rn, rn_rows = evaluation.ragas_scores(naive, ALL)
    RAGAS_FILE.write_text(json.dumps({"full": rf, "naive": rn, "full_rows": rf_rows, "naive_rows": rn_rows}, indent=2, default=float))
    print(f"RAGAS finished in {(time.time() - t)/60:.1f} min")
rg = json.loads(RAGAS_FILE.read_text())
gv = json.loads((OUT / "ragas_generator_view.json").read_text())
ragas_tbl = pd.DataFrame({"naive RAG baseline": {k: v for k, v in rg["naive"].items() if isinstance(v, float)},
                          "guardrailed pipeline": {k: v for k, v in rg["full"].items() if isinstance(v, float)}})
ragas_tbl.loc["faithfulness (judge sees generator input)"] = [gv["naive"]["means"]["faithfulness"], gv["full"]["means"]["faithfulness"]]
print("judge failures (NaN rate):", rg["full"]["nan_rate"], "| scored answers:", rg["full"]["n_scored"], "/", rg["naive"]["n_scored"])
ragas_tbl.round(3)'''),
     ("md", "### What the faithfulness judge is shown\n"
            "The generator receives each source with a header such as `(document: CU4_Controller_Firmware_Release_Notes.docx, p. 3)`. "
            "In the first RAGAS runs the judge received only the page text and the answer with `[Source n]` markers, so a correct "
            "answer mentioning an entity that appears only in the document name (e.g. *CU-4*) was marked unsupported, and citation "
            "markers were treated as claims. The corrected judge view shows the judge exactly the generator's input (header + text) "
            "and the answer without citation markers. The change was validated on 60 **development** questions (facts disjoint "
            "from the test set) before being applied to the test set; both views are reported."),
     ("code", '''dev = json.loads((config.ARTIFACT_DIR / "dev_judge_view.json").read_text())
display(pd.DataFrame(dev).T.rename(index={"raw": "page text + [Source n] (old)", "generator": "exactly the generator input (new)"}))
views = pd.DataFrame({"page text + [Source n] (old)": {"naive": rg["naive"]["faithfulness"], "pipeline": rg["full"]["faithfulness"]},
                      "generator input (new)": {"naive": gv["naive"]["means"]["faithfulness"], "pipeline": gv["full"]["means"]["faithfulness"],
                                                "pipeline + LoRA": gv["lora"]["means"]["faithfulness"]}})
views.round(3)'''),
     ("code", '''by = {r["qid"]: r for r in full}
low = [x for x in gv["full"]["rows"] if x["faithfulness"] < 1]
print(len(low), "pipeline answers still scored below 1.0 by the judge (generator view):")
pd.DataFrame([{"faithfulness": x["faithfulness"], "answer": by[x["qid"]]["answer_raw"][:110], "gold": by[x["qid"]]["gold_answer"],
               "correct": evaluation.answer_correct(by[x["qid"]])} for x in low])'''),
     ("md", "### Stretch goal: LoRA fine-tune of Phi-4-mini\n"
            "LoRA (r = 16, alpha = 32, attention + MLP projections, 23 M trainable parameters = 0.6%) trained for one epoch on 806 "
            "grounded, cited examples built with the production retrieval pipeline from training facts only (no test or development "
            "facts), including 20 abstention examples; merged, converted to GGUF and quantised to Q8_0 exactly like the base model, "
            "then evaluated on the same 200 test questions with the same retrieval, reranker, prompt and guardrail."),
     ("code", '''lora_dir = config.ARTIFACT_DIR / "eval_lora"
lora, lora_u = load_jsonl(lora_dir / "full_test.jsonl"), load_jsonl(lora_dir / "full_unanswerable.jsonl")
sl, ul = evaluation.score_records(lora), evaluation.score_unanswerable(lora_u)
cmp_keys = ["answered", "correct", "correct_strict", "wrong_answer", "citation_accuracy", "citation_precision", "nli_faithfulness", "regenerated", "latency_p50", "latency_p95"]
lt = pd.DataFrame({"base Phi-4-mini": {k: sf[k] for k in cmp_keys}, "LoRA Phi-4-mini": {k: sl[k] for k in cmp_keys}})
lt.loc["unanswerable: correct refusal"] = [uf["correct_refusal_rate"], ul["correct_refusal_rate"]]
lt.loc["RAGAS faithfulness (generator view)"] = [gv["full"]["means"]["faithfulness"], gv["lora"]["means"]["faithfulness"]]
lt.loc["RAGAS answer relevancy"] = [rg["full"]["answer_relevancy"], gv["lora"]["means"]["answer_relevancy"]]
lh = json.loads((config.MODEL_DIR / "phi4-mini-lora-adapter" / "training_history.json").read_text())
fig, ax = plt.subplots(figsize=(6, 3)); pd.DataFrame({k: lh[k] for k in ("step", "train_loss", "val_loss")}).plot(x="step", ax=ax, marker="o")
ax.set_title("LoRA training (loss on answer tokens)"); plt.tight_layout(); plt.savefig(config.ARTIFACT_DIR / "lora_training_curve.png", dpi=120); plt.show()
lt.round(3)'''),
     ("md", "### Scorecard against the proposal's targets"),
     ("md", "The **final system** uses the LoRA-tuned generator. Retrieval and reranking are identical for both generators, so "
            "context metrics are shared; generator-dependent metrics are measured separately."),
     ("code", '''rel = lambda run, fallback: gv[run]["means"].get("answer_relevancy", fallback)
rows = [
    ("Context precision (RAGAS def., gold-page labels)", ">= 0.90", sn["context_precision"], sf["context_precision"], sl["context_precision"]),
    ("Context precision (RAGAS, LLM judge)", ">= 0.90", rg["naive"]["llm_context_precision_with_reference"], rg["full"]["llm_context_precision_with_reference"], rg["full"]["llm_context_precision_with_reference"]),
    ("Context recall (RAGAS, LLM judge)", "-", rg["naive"]["context_recall"], rg["full"]["context_recall"], rg["full"]["context_recall"]),
    ("Faithfulness (RAGAS, judge sees generator input)", ">= 0.95", gv["naive"]["means"]["faithfulness"], gv["full"]["means"]["faithfulness"], gv["lora"]["means"]["faithfulness"]),
    ("Faithfulness (RAGAS, page-text-only judge view)", "(info)", rg["naive"]["faithfulness"], rg["full"]["faithfulness"], None),
    ("Answer relevancy (RAGAS)", "-", rg["naive"]["answer_relevancy"], rel("full", rg["full"]["answer_relevancy"]), rel("lora", None)),
    ("Citation accuracy (gold page cited)", ">= 0.95", sn["citation_accuracy"], sf["citation_accuracy"], sl["citation_accuracy"]),
    ("End-to-end latency p95 (s)", "< 3.5", sn["latency_p95"], sf["latency_p95"], sl["latency_p95"]),
    ("Answer correctness (semantic match)", "-", sn["correct"], sf["correct"], sl["correct"]),
    ("Answer correctness (strict exact match)", "-", sn["correct_strict"], sf["correct_strict"], sl["correct_strict"]),
    ("Wrong answers delivered", "-", sn["wrong_answer"], sf["wrong_answer"], sl["wrong_answer"]),
    ("Refusal on unanswerable questions", "-", un["correct_refusal_rate"], uf["correct_refusal_rate"], ul["correct_refusal_rate"]),
]
score = pd.DataFrame(rows, columns=["metric", "target", "naive", "pipeline (base)", "final system (LoRA)"])
def passed(r):
    v = r["final system (LoRA)"]
    if r["target"].startswith(">="): return v >= float(r["target"][3:])
    if r["target"].startswith("<"): return v < float(r["target"][2:])
    return None
score["target met (final)"] = score.apply(passed, axis=1)
score = score.round(3)
(config.ARTIFACT_DIR / "scorecard.json").write_text(score.to_json(orient="records", indent=2))
score'''),
     ("code", '''fig, ax = plt.subplots(figsize=(10, 4))
plot = score[score.metric.str.contains("precision|recall|Faithfulness \\(RAGAS, judge|relevancy|Citation|correctness \\(semantic")].set_index("metric")[["naive", "pipeline (base)", "final system (LoRA)"]]
plot.plot.barh(ax=ax); ax.set_xlim(0.5, 1.0); ax.set_title("Naive RAG vs guardrailed pipeline vs final system (200 held-out queries)")
plt.tight_layout(); plt.savefig(config.ARTIFACT_DIR / "scorecard.png", dpi=120); plt.show()'''),
     ("md", "### Effect of the two post-analysis bug fixes\nAfter the first evaluation run, error analysis found two generic bugs: "
            "(1) the reranker cutoff could empty the context entirely, and (2) NLI premises lacked the document title, so "
            "entities named only in the title (e.g. *CU-4*) could not be entailed. Both were fixed (best passage always kept; "
            "premises prefixed with `title | section`). Because the fixes came from test-set errors, the pre-fix run is kept in "
            "`artifacts/eval_v1_before_fixes/` and reported here for transparency."),
     ("code", '''pre = config.ARTIFACT_DIR / "eval_v1_before_fixes" / "full_test.jsonl"
if pre.exists():
    s0 = evaluation.score_records(load_jsonl(pre))
    display(pd.DataFrame({"before fixes": {k: s0[k] for k in keys}, "after fixes": {k: sf[k] for k in keys}}).round(3))'''),
     ("md", "### Breakdown by document type and latency profile"),
     ("code", '''df = pd.DataFrame([{**{k: r[k] for k in ("doc_type", "status")}, "correct": evaluation.answer_correct(r),
                    **{f"t_{k}": v for k, v in r["timings_s"].items()}} for r in full])
display(df.groupby("doc_type").agg(n=("correct", "size"), correct=("correct", "mean"), mean_latency=("t_total", "mean")).round(3))
df[[c for c in df.columns if c.startswith("t_")]].describe(percentiles=[.5, .95]).round(3)'''),
     ("md", "### Audit log sample\nEvery query writes retrieved chunk IDs, dense / sparse / RRF / rerank scores and per-claim verifier verdicts."),
     ("code", '''log = sorted(config.AUDIT_DIR.glob("audit_*.jsonl"))[-1]
lines = log.read_text().splitlines()
print(log.name, "-", len(lines), "audit records")
rec = json.loads(next(l for l in reversed(lines) if '"mode": "full"' in l))
print(json.dumps(rec, indent=1)[:2500])'''),
     ("md", "### Remaining errors of the guardrailed pipeline"),
     ("code", '''errs = [{"question": r["question"], "gold": r["gold_answer"], "status": r["status"], "answer": r["answer"][:160]}
        for r in full if not evaluation.answer_correct(r)]
print(len(errs), "queries not answered correctly")
pd.DataFrame(errs)'''),
     ])

# ---------------------------------------------------------------------------
master = nbf.v4.new_notebook()
master.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
master.cells = [
    nbf.v4.new_markdown_cell(
        "# Enterprise Agentic RAG Engine - master execution notebook\n\n"
        "Runs the complete project end to end by executing the nine milestone notebooks in order "
        "(environment -> parsing -> indexing -> hybrid retrieval -> reranker -> generation -> guardrail -> API -> "
        "evaluation) and then presents the final scorecard. Each milestone notebook is saved with its outputs.\n\n"
        "Heavy steps are cached: reranker fine-tuning (`scripts/train_reranker.py`) and the evaluation runs are "
        "re-used if their artifacts exist. Delete `models/bge-reranker-large-finetuned/` or `artifacts/eval/` to "
        "force a full re-run."),
    nbf.v4.new_code_cell(SETUP),
    nbf.v4.new_code_cell('''import nbformat
from nbclient import NotebookClient
STEPS = ["01_environment_diagnostics", "02_document_parsing", "03_vector_indexing", "04_hybrid_retrieval",
         "05_reranker_integration", "06_rag_synthesis", "07_guardrail_verifier", "08_api_ui_server", "09_evaluation_scorecard"]
timings = []
for name in STEPS:
    path = ROOT / "notebooks" / f"{name}.ipynb"
    nb = nbformat.read(path, as_version=4)
    t = time.time()
    NotebookClient(nb, timeout=None, kernel_name="python3", resources={"metadata": {"path": str(path.parent)}}).execute()
    nbformat.write(nb, path)
    timings.append({"milestone": name, "seconds": round(time.time() - t, 1), "status": "ok"})
    print(f"{name:32s} done in {timings[-1]['seconds']:7.1f}s")
pd.DataFrame(timings)'''),
    nbf.v4.new_markdown_cell("## Final results"),
    nbf.v4.new_code_cell('''comp = json.loads((config.ARTIFACT_DIR / "reranker_comparison.json").read_text())
print("Reranker fine-tuning (200 held-out queries):")
display(pd.DataFrame({k: comp[k] for k in ("hybrid_rrf_no_rerank", "pretrained_reranker", "finetuned_reranker")}).T.round(4))
print("Guardrail stress test:", json.loads((config.ARTIFACT_DIR / "guardrail_stress.json").read_text()))
pd.read_json(config.ARTIFACT_DIR / "scorecard.json")'''),
    nbf.v4.new_code_cell('''from IPython.display import Image, display
for f in ("scorecard.png", "retrieval_comparison.png", "reranker_training_curve.png", "reranker_score_separation.png"):
    p = config.ARTIFACT_DIR / f
    if p.exists(): display(Image(str(p), width=760))'''),
]
NOTEBOOKS["master_execution_notebook.ipynb"] = master

if __name__ == "__main__":
    for name, n in NOTEBOOKS.items():
        nbf.write(n, NB_DIR / name)
        print("wrote", NB_DIR / name)
