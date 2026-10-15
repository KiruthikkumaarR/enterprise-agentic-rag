# Enterprise Agentic RAG Engine

**Kiruthikkumaar Radhakrishnan** · [Portfolio & interactive demo](https://kiruthikportfolio.com/demo/) ·
[LinkedIn](https://www.linkedin.com/in/kiruthikkumaar-r/)

A zero-hallucination retrieval-augmented generation system for enterprise document intelligence,
implementing project proposal 5.2 (Master of AI & ML, Adelaide University, 6 Sep 2026). Everything runs **on-premise on one Apple-Silicon
Mac**: no chunk, embedding or query leaves the machine, and the Hugging Face Hub is forced offline at runtime.

```
question
   │
   ├─► BGE-M3 ──► dense 1024-d ─┐                       Qdrant 1.19 (HNSW + int8 scalar quantisation)
   │          └─► sparse lexical ┴─► hybrid search ──► Reciprocal Rank Fusion (k=60) ──► top-30
   │
   ├─► bge-reranker-large (fine-tuned, pairwise RankNet loss) ──► top-5, calibrated cutoff
   ├─► parent expansion (child chunk ──► full page / section / row) ──► numbered sources [S1..S5]
   ├─► Phi-4-mini-instruct 3.8B + LoRA fine-tune (llama.cpp, Q8_0, temperature 0) ──► answer with per-sentence citations
   └─► faithfulness guardrail: citation check + exact-number check + DeBERTa-v3-large NLI entailment
          ├─ pass ──────────────► verified answer  ──► FastAPI ──► web UI with citation drawer
          ├─ fail ──► 1 bounded regeneration with feedback
          └─ still fail ──► unverifiable sentences removed, or "cannot be verified" fallback
```

## Results (200 held-out QA pairs + 20 unanswerable questions)

Final system = guardrailed pipeline with the **LoRA-tuned Phi-4-mini** generator (proposal stretch goal). All
targets from the proposal are met.

| Metric | Target | Naive RAG | Pipeline (base Phi-4-mini) | **Final system (LoRA)** |
|---|---|---|---|---|
| Context precision (RAGAS definition, gold-page labels) | ≥ 0.90 | 0.793 | 0.991 | **0.991** ✅ |
| Context precision (RAGAS, LLM judge) | ≥ 0.90 | 0.832 | 0.990 | **0.990** ✅ |
| Context recall (RAGAS, LLM judge) | – | 0.995 | 1.000 | **1.000** |
| Faithfulness (RAGAS, judge sees the generator's input) | ≥ 0.95 | 0.971 | 0.997 | **0.997** ✅ |
| Faithfulness (RAGAS, judge sees page text only) | (info) | 0.854 | 0.891 | – |
| Answer relevancy (RAGAS) | – | 0.933 | **0.950** | 0.871 |
| Citation accuracy (gold page among citations) | ≥ 0.95 | 0.968 | 0.995 | **1.000** ✅ |
| End-to-end latency p95 | < 3.5 s | 1.16 s | 2.32 s | **1.98 s** ✅ |
| Answer correctness (semantic match) | – | 0.920 | 0.980 | **0.995** |
| Answer correctness (strict exact match) | – | 0.905 | 0.955 | **0.980** |
| Wrong answers delivered | – | 2.5 % | 1.0 % | **0 %** |
| Correct refusal on 20 unanswerable questions | – | 100 % | 100 % | **100 %** |

RAGAS 0.4.3 with an independent judge (Qwen2.5-7B-Instruct, Q4_K_M, llama.cpp - a different model family from the
generator); all four metrics computed by the judge, 0 judge failures (NaN rate 0 %). Latency was measured while
other jobs shared the GPU; on an idle machine the pipeline's p95 was 1.0-1.3 s.

**What the faithfulness judge is shown.** The generator receives each source with a header such as
`(document: CU4_Controller_Firmware_Release_Notes.docx, p. 3)`. In the first RAGAS runs the judge received only the
page text, plus the answer with `[Source n]` markers, so correct answers mentioning an entity named only in the
document name (e.g. "CU-4") were scored unsupported and citation markers were treated as claims (raw score 0.891;
27 of 29 low-scored answers were correct with the value verbatim in the evidence). The corrected judge view shows
the judge exactly the generator's input and the answer without citation markers. It was validated on 60
**development** questions (facts disjoint from the test set; 0.966 → 1.000 on identical answers) before being
applied to the test set, and both views are reported above and in notebook 09.

**LoRA trade-off.** The LoRA model gives the best correctness (0 wrong answers, 100 % citation accuracy, 100 %
refusals) but more compact answers, which RAGAS answer relevancy rewards less (0.871 vs 0.950).

### Reranker fine-tuning (milestones 5–6) — top-5 after reranking, same 200 held-out queries

| | hit@1 | MRR | context precision | context recall |
|---|---|---|---|---|
| Hybrid RRF, no reranker | 0.760 | 0.866 | 0.858 | 0.995 |
| bge-reranker-large, pre-trained | 0.975 | 0.986 | **0.974** | **1.000** |
| bge-reranker-large, **fine-tuned** | **0.995** | **0.995** | 0.972 | 0.995 |

Fine-tuning: 1 epoch, 1,852 training queries (2 per step, 1 positive + 7 hard negatives mined from the
hybrid top-30), AdamW lr 1e-5 with linear warm-up, pairwise loss `log(1+exp(-(s⁺−s⁻)))`, 31 min on an M4 Max.
Training facts and test facts are disjoint. Fine-tuning cut top-1 errors from 5 to 1; context precision and
recall were flat (one query lost its gold page from the top 5). Its main practical gain is **score separation**:
on 211 validation questions whose facts were never trained on, a cutoff of −2.0 keeps 100 % of gold passages
while removing 99.3 % of irrelevant ones (pre-trained at its cutoff: 98.3 % / 88.7 %), which keeps the
generator's context window clean.

### Guardrail stress test (notebook 07)

For each held-out fact: the correct sentence, the same sentence with its value swapped for another value from
the same document, and a true sentence about a different fact cited to the wrong page. See
`artifacts/guardrail_stress.json` Result on 120 held-out facts: **100 % of correct claims accepted, 100 % of value-swapped claims
caught, 100 % of misattributed claims caught.**

## Honest notes and limitations

* **Synthetic data.** The corpus is a generated, de-identified document estate for a fictional company
  (14 documents, 1,064 facts). Labels are exact by construction and every answer is verified to sit on its
  labelled page, but real enterprise documents are messier (scans, multi-column layouts, OCR noise).
* **A first version of the benchmark was too easy** (the pre-trained reranker already scored hit@1 = 1.0), so
  "hard-negative" documents were added that mention the same entities in other contexts (energy *savings* vs
  *consumption*, audit *scores* vs register *quality scores*, typical duty point vs maximum flow, work-order
  dates vs scheduled service dates), plus paraphrased questions that avoid the document's wording.
* **Two bug fixes came from test-set error analysis**: (1) the reranker cutoff could empty the context — the
  best passage is now always kept; (2) NLI premises lacked the document title, so entities named only in the
  title (e.g. "CU-4") could not be entailed. They are generic bugs, not tuned parameters, but because they were
  found on the test set the pre-fix run is preserved in `artifacts/eval_v1_before_fixes/` and compared in
  notebook 09 (before: correct 0.94 semantic, 4 empty-context failures, 5 false guardrail rejections).
* **Answer correctness** is reported two ways: strict substring match of the gold value, and a semantic matcher
  (numbers and dates must match exactly after normalisation, ≥ 80 % of word stems must appear) that accepts
  "January 20, 2028" for "2028-01-20" and "450 liters per minute" for "450 L/min".
* The guardrail is strict by design: it trades a few over-cautious refusals for very few unsupported claims.
  Remaining errors include one genuinely ambiguous question ("last service date" of an asset whose most recent
  *work order* is a few days earlier than its scheduled service date).
* **LoRA stretch goal (done).** r = 16, alpha = 32 on attention + MLP projections (23 M trainable parameters, 0.6 %),
  one epoch on 806 grounded, cited examples built with the production retrieval pipeline from training facts only
  (only 20 abstention examples - with the strict reranker most questions have a single source, so removing it left
  nothing to train on); validation loss 1.23 → 0.055; merged, converted with the llama.cpp converter at the installed
  commit and quantised to Q8_0 exactly like the base model (`scripts/train_lora.py`, `models/phi4-mini-lora-adapter/`).
* **Guardrail refinement after the first final run**: table rows now carry their caption (so units stated once,
  e.g. "(EUR million)", apply to every row) and each table also yields one combined premise (so sentences
  summarising several rows can be entailed). Found on portal questions, not the test set; the stress test is still
  100 % / 100 % / 100 %, and the pre-change runs are kept in `artifacts/eval_v3_before_caption_fix/`.
* The proposal named Ollama; the implementation uses **llama.cpp `llama-server`** instead, with the same model
  (Phi-4-mini-instruct, 3.8B).

## Project layout

```
rag/                    core package
  config.py             all settings (env-overridable, RAG_*); forces HF offline mode
  corpus.py             synthetic corpus + ground-truth QA generator (PDF/DOCX/CSV/MD)
  parsing.py            layout-aware parsing, parent-child chunking, PII redaction, label validation
  embedder.py           BGE-M3 dense + sparse heads on transformers
  store.py              Qdrant collection (HNSW, int8 quantisation, sparse vectors), local server control
  retrieval.py          hybrid search + Reciprocal Rank Fusion
  reranker.py           cross-encoder reranking + resumable PyTorch fine-tuning (pairwise loss)
  generator.py          grounded prompt, llama.cpp server control, chat client
  guardrail.py          claim splitting, citation/number checks, NLI entailment verifier
  pipeline.py           end-to-end agentic pipeline, bounded regeneration, audit logging
  metrics.py, evaluation.py   retrieval metrics, scorecard, guardrail stress test, RAGAS integration
api/server.py           FastAPI REST API;  api/static/index.html  web UI with source-citation drawer
notebooks/              01–09 milestone notebooks + master_execution_notebook.ipynb (executed, with outputs)
scripts/                setup.sh, build_index.py, train_reranker.py, run_evaluation.py, make_notebooks.py, run_notebooks.py
data/corpus/            the 14 source documents;  data/eval/  facts, test, train and unanswerable QA sets
artifacts/              scorecard, comparison JSONs, plots, evaluation outputs, audit_logs/
models/                 GGUF models + fine-tuned reranker (not included in source control)
```

## Running it

> **Not included in this repository** (too large, or generated): model weights (`models/`: Phi-4-mini GGUF, the
> Qwen2.5 judge, the fine-tuned reranker and the LoRA adapter), the Qdrant index, the portal database and the
> generated portal documents. `scripts/setup.sh` downloads the base models; `scripts/train_reranker.py` and
> `scripts/train_lora.py` reproduce the two fine-tunes; `scripts/build_index.py` and `scripts/build_portal.py`
> rebuild the index, the portal documents and the demo accounts. All evaluation outputs are included under
> `artifacts/`, so every number in this README can be checked without re-running anything.

```bash
bash scripts/setup.sh                       # one-time: venv, llama.cpp, Qdrant binary, model downloads
.venv/bin/python scripts/build_index.py     # corpus -> chunks -> BGE-M3 -> Qdrant
.venv/bin/python scripts/train_reranker.py  # ~30 min on M4 Max; resumable
.venv/bin/python scripts/train_lora.py prepare && .venv/bin/python scripts/train_lora.py train && .venv/bin/python scripts/train_lora.py export   # ~45 min
.venv/bin/python scripts/run_evaluation.py  # pipeline vs baseline + RAGAS (all four metrics)
.venv/bin/python scripts/eval_lora.py && .venv/bin/python scripts/final_ragas.py   # LoRA run + final faithfulness
.venv/bin/uvicorn api.server:app --port 8000   # then open http://127.0.0.1:8000
```

Qdrant (port 6333), Phi-4-mini (port 18090) and the RAGAS judge (port 18091) are started automatically when
needed. `POST /api/query {"question": "...", "mode": "full" | "naive"}` returns the answer, citations, sources,
retrieval scores, per-claim verifier verdicts and stage timings. Every query is appended to
`artifacts/audit_logs/audit_YYYYMMDD.jsonl` (retrieved chunk IDs, dense/sparse/RRF/rerank scores, verifier verdicts).

The notebooks reproduce each milestone; `notebooks/master_execution_notebook.ipynb` runs all nine in order.

---

# Halvorsen Intelligence Portal (company demo)

A local, login-protected web portal built on the same RAG engine, with a realistic **synthetic** company
document estate and role-based access control. It is separate from the coursework evaluation above (its own
Qdrant collection `company_portal`), so the reported results are unaffected.

```bash
bash scripts/start_portal.sh        # then open http://127.0.0.1:8100
```

**Data** (`data/portal/documents/`, generated by `portal/company_data.py`, fixed seed): 67 documents (PDF, DOCX,
CSV, Markdown) across 11 departments, including board minutes, strategy, an acquisition memo, quarterly
financial statements, budgets, a 650-person staff directory, salary bands, 320 customer accounts, a 540-deal sales
pipeline, 900 purchase orders, quarterly financial KPIs, monthly bookings, IT assets, contracts, test reports and
policies (6,570 indexed passages). Quarterly financials add up to the reported FY2025 revenue (EUR 412.6m) and are
the same in the board minutes, financial statements and KPI dataset. People,
customers, suppliers and figures are fictional and consistent across documents.

**Accounts**: 30 demo accounts (8 executives, 11 department heads, 10 employees, 1 IT admin), listed with their
test passwords in `data/portal/demo_accounts.csv` and in the "Demo accounts" panel on the sign-in page
(disable the panel with `PORTAL_DEMO=0`). Passwords are stored as scrypt hashes in `data/portal/portal.db`.

| Classification | Who can read it |
|---|---|
| All staff | everyone |
| Department | members of the document's departments, managers, executives |
| Management | managers and executives |
| Executive | executives only |

Access is enforced **inside the vector search** (a Qdrant payload filter per user), so restricted passages are
never retrieved for an unauthorised user, and again on every download, preview and returned source.

**Features**: AI assistant with verified, cited answers and a source drawer (PDF page rendering); document library
with search, filters, preview and download; 3D "Knowledge Galaxy"; drag-and-drop upload (indexed within seconds,
classification limited by role); insights dashboard; user administration; audit log of questions and actions.

**Dashboards, charts and reports** (`portal/analytics.py`, `portal/reports.py`):

* **Role-based dashboards** - KPI tiles and department tabs built from 21 structured datasets (finance KPIs, bookings,
  pipeline, customers, staff, budget, payables, expenses, purchase orders, inventory, safety, IT assets, contracts,
  campaigns, ...). A chart appears only if the user is cleared to read its source document.
* **Charts on request** - ask the assistant e.g. "top 10 customers by annual revenue as a chart". Phi-4-mini only
  *chooses* a chart specification, constrained by a per-dataset JSON schema; the numbers are computed with pandas from
  the source records, and titles are derived from what was computed, so a chart cannot contain invented figures.
  Questions the user's data cannot answer fall back to the document assistant.
* **Chart builder & "My charts"** - build any chart from accessible data and pin it to a personal dashboard.
* **One-click reports** - 10 templates (Executive Summary, Finance, Sales, People, Operations, Procurement, IT,
  Marketing, Legal, Engineering) export as **PowerPoint** (native, editable charts, KPI slide, data tables, sources
  slide, classification label) or **Excel**. Every chart also exports to PPT or Excel individually.

**Security**: binds to 127.0.0.1 only, trusted-host check, HttpOnly SameSite=Strict session cookies (8 h), CSRF
header on state-changing requests, login rate limiting (5 failures / 5 min), strict Content-Security-Policy, all
JavaScript served locally (Three.js vendored, no CDNs). `scripts/test_portal_security.py` runs 25 end-to-end checks
(all pass), including access control for dashboards, charts and reports. This is a demo: before real use, replace the demo accounts, disable demo mode and put it behind HTTPS.
