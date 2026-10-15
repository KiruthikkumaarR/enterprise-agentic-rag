"""Evaluation harness.

* run_queries        - run the pipeline (full or naive) over a QA set, keep every output
* score_records      - label-based metrics: RAGAS context precision / recall (page labels),
                       answer correctness, citation accuracy, guardrail faithfulness, latency
* guardrail_stress   - does the verifier accept correct claims and catch corrupted ones?
* ragas_scores       - the RAGAS framework itself (faithfulness, answer relevancy, LLM context
                       precision / recall) with an independent local judge LLM served by llama.cpp
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from . import config, guardrail, metrics
from .parsing import linearize_tables, norm

CONTEXT_FN = linearize_tables      # how source text is shown to the generator (and therefore to the judge)
JUDGE_GGUF = config.MODEL_DIR / "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
JUDGE_URL = "http://127.0.0.1:18091"


# ---------------------------------------------------------------------------
def run_queries(pipeline, rows: list[dict], mode: str = "full", out: Path | None = None, log_every: int = 25) -> list[dict]:
    records = []
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        r = pipeline.answer(row["question"], mode)
        rec = {"qid": row["qid"], "question": row["question"], "gold_answer": row.get("answer"),
               "ground_truth": row.get("ground_truth"), "gold_doc": row.get("doc"), "gold_page": row.get("page"),
               "doc_type": row.get("doc_type"), **{k: r[k] for k in ("mode", "status", "answer", "answer_raw", "citations",
                                                                     "retrieved", "regenerations", "timings_s")},
               "contexts": [CONTEXT_FN(s["text"]) for s in r["sources"]],   # exactly what the generator saw
               "source_locs": [(s["doc"], s["page"]) for s in r["sources"]],
               "source_types": [s["doc_type"] for s in r["sources"]],
               "verdict": r["attempts"][-1].get("verdict") if r["attempts"] else None,
               "first_verdict": r["attempts"][0].get("verdict") if r["attempts"] else None}
        records.append(rec)
        if log_every and i % log_every == 0:
            print(f"  [{mode}] {i}/{len(rows)}  ({time.time() - t0:.0f}s)")
    if out:
        with open(out, "w") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
    return records


def _answered(rec) -> bool:
    return rec["status"] in ("verified", "partially_verified", "unverified_baseline")


_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                        "september", "october", "november", "december"], 1)}


def _canon(text: str) -> str:
    """Lower-case, drop thousands separators and citations, rewrite 'January 20, 2028' / '20 January 2028' as ISO dates."""
    t = re.sub(r"\[S\d+\]", " ", text.lower()).replace(",", "")
    t = re.sub(r"\b(\d{1,2}) (%s) (\d{4})\b" % "|".join(_MONTHS),
               lambda m: f"{m.group(3)}-{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}", t)
    t = re.sub(r"\b(%s) (\d{1,2}) (\d{4})\b" % "|".join(_MONTHS),
               lambda m: f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}", t)
    return re.sub(r"\s+", " ", t)


def answer_correct_strict(rec) -> float:
    """Exact (normalised) substring match of the gold value."""
    return float(_answered(rec) and rec["gold_answer"] is not None and norm(rec["gold_answer"]).replace(",", "")
                 in norm(rec["answer_raw"]).replace(",", ""))


def answer_correct(rec) -> float:
    """Semantic match: every number/date of the gold value must appear, and >= 80% of its word stems
    (4-char prefixes, so 'repairs'~'repairing'); unit spellings such as 'L/min' vs 'litres per minute' are not
    required when the number matches."""
    if not _answered(rec) or rec["gold_answer"] is None:
        return 0.0
    if answer_correct_strict(rec):
        return 1.0
    gold, ans = _canon(rec["gold_answer"]), _canon(rec["answer_raw"])
    nums = re.findall(r"\d+(?:[.-]\d+)*", gold)
    if nums and not all(re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", ans) for n in nums):
        return 0.0
    words = [w for w in re.findall(r"[a-z][a-z-]+", gold) if w not in {"the", "a", "an", "of", "and", "per", "l", "min"}]
    if nums:
        words = [w for w in words if w not in {"kg", "mm", "kw", "ms", "mwh", "kwp", "tonnes", "days", "minutes", "degc"}]
    if not words:
        return 1.0
    stems = {w[:4] for w in re.findall(r"[a-z][a-z-]+", ans)}
    return float(sum(w[:4] in stems for w in words) / len(words) >= 0.8)


def score_records(records: list[dict]) -> dict:
    per = []
    for rec in records:
        row = {"doc": rec["gold_doc"], "page": rec["gold_page"], "answer": rec["gold_answer"]}
        retrieved = [{"doc": c["chunk_id"].split("::")[0], "page": int(c["chunk_id"].split("::")[1]), "text": ""}
                     for c in rec["retrieved"]]
        rs = metrics.retrieval_scores(retrieved, row) if retrieved else {
            "context_precision": 0.0, "context_recall": 0.0, "mrr": 0.0, "hit@1": 0.0, "answer_chunk@1": 0.0}
        cites = [(c["doc"], c["page"]) for c in rec["citations"]]
        gold = (rec["gold_doc"], rec["gold_page"])
        v = rec["verdict"]
        per.append({
            "context_precision": rs["context_precision"], "context_recall": rs["context_recall"],
            "answered": float(_answered(rec)), "correct": answer_correct(rec), "correct_strict": answer_correct_strict(rec),
            "citation_accuracy": float(gold in cites) if _answered(rec) else np.nan,
            "citation_precision": (sum(c == gold for c in cites) / len(cites)) if (_answered(rec) and cites) else np.nan,
            "nli_faithfulness": v["faithfulness"] if (v and v.get("faithfulness") is not None and _answered(rec)) else np.nan,
            "latency": rec["timings_s"]["total"], "regenerated": float(rec["regenerations"] > 0),
            "wrong_answer": float(_answered(rec) and not answer_correct(rec)),
        })
    m = {k: float(np.nanmean([p[k] for p in per])) for k in per[0] if k != "latency"}
    lat = np.array([p["latency"] for p in per])
    m.update(latency_mean=float(lat.mean()), latency_p50=float(np.percentile(lat, 50)),
             latency_p95=float(np.percentile(lat, 95)), within_3_5s=float((lat < 3.5).mean()), n=len(per))
    statuses: dict[str, int] = {}
    for rec in records:
        statuses[rec["status"]] = statuses.get(rec["status"], 0) + 1
    m["status_counts"] = statuses
    return m


def score_unanswerable(records: list[dict]) -> dict:
    refused = [r["status"] in ("abstained", "no_evidence", "unverified_fallback") for r in records]
    return {"n": len(records), "correct_refusal_rate": float(np.mean(refused)),
            "hallucinated_answers": [r["question"] + " -> " + r["answer"] for r, x in zip(records, refused) if not x]}


# ---------------------------------------------------------------------------
def guardrail_stress(test_rows: list[dict], facts: list[dict], chunks, n: int = 120, seed: int = config.SEED) -> dict:
    """For each sampled test fact build three answers citing the gold page:
       correct   - the reference sentence                          (should PASS)
       corrupted - reference with the value swapped for another
                   value of the same kind from the same document   (should FAIL)
       foreign   - a true sentence about a *different* fact that
                   is not on the cited page                        (should FAIL)"""
    rng = random.Random(seed)
    parents = {(c.doc, c.page): {"doc": c.doc, "doc_type": c.doc_type, "page": c.page, "section": c.section,
                                 "text": c.parent_text} for c in chunks}
    by_doc: dict[str, list[dict]] = {}
    for f in facts:
        by_doc.setdefault(f["doc"], []).append(f)
    out = {"correct": [], "corrupted": [], "foreign": []}
    examples = []
    for row in rng.sample(test_rows, min(n, len(test_rows))):
        src = [parents[(row["doc"], row["page"])]]
        gold = row["ground_truth"]
        alts = [f["answer"] for f in by_doc[row["doc"]] if f["answer"] != row["answer"]
                and f["gold_answer"].replace(f["answer"], "") != gold.replace(row["answer"], "")
                and norm(f["answer"]) not in norm(src[0]["text"])]
        same_shape = [a for a in alts if any(ch.isdigit() for ch in a) == any(ch.isdigit() for ch in row["answer"])]
        corrupted_val = rng.choice(same_shape or alts)
        corrupted = gold.replace(row["answer"], corrupted_val)
        foreign = rng.choice([f for f in facts if (f["doc"], f["page"]) != (row["doc"], row["page"])])["gold_answer"]
        for kind, sent in (("correct", gold), ("corrupted", corrupted), ("foreign", foreign)):
            v = guardrail.verify(sent.rstrip(".") + " [S1].", src, question=row["question"])
            out[kind].append(v["status"] == "verified")
            examples.append({"kind": kind, "question": row["question"], "claim": sent, "passed": v["status"] == "verified",
                             "entailment": v["claims"][0]["entailment"], "reason": v["claims"][0]["reason"]})
    return {"n": len(out["correct"]),
            "correct_accepted": float(np.mean(out["correct"])),
            "corrupted_caught": 1 - float(np.mean(out["corrupted"])),
            "foreign_caught": 1 - float(np.mean(out["foreign"])),
            "examples": examples}


# ---------------------------------------------------------------------------
# RAGAS with an independent local judge (Qwen2.5-7B-Instruct via llama.cpp)
# ---------------------------------------------------------------------------
def ensure_judge(timeout: float = 240) -> str:
    import requests

    def alive():
        try:   # must be *our* judge, not some other server on the port
            return requests.get(f"{JUDGE_URL}/health", timeout=1).ok and "judge" in [
                m["id"] for m in requests.get(f"{JUDGE_URL}/v1/models", timeout=2).json().get("data", [])]
        except (requests.RequestException, ValueError):
            return False

    if alive():
        return "already running"
    log = open(config.ARTIFACT_DIR / "judge_server.log", "a")
    subprocess.Popen([config.LLM_SERVER_BIN, "-m", str(JUDGE_GGUF), "--port", JUDGE_URL.rsplit(":", 1)[-1],
                      "--host", "127.0.0.1", "-c", "32768", "-np", "4", "-ngl", "99", "--jinja", "--alias", "judge"],
                     stdout=log, stderr=log, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if alive():
            return "started"
        time.sleep(1)
    raise RuntimeError("judge server failed to start; see artifacts/judge_server.log")


class _BGEEmbeddings:
    """LangChain-style embeddings adapter over our BGE-M3 dense head (for answer relevancy)."""

    def __init__(self):
        from .embedder import get_embedder
        self.emb = get_embedder()

    def embed_documents(self, texts):
        return self.emb.encode(list(texts))[0].tolist()

    def embed_query(self, text):
        return self.embed_documents([text])[0]

    async def aembed_documents(self, texts):
        return self.embed_documents(texts)

    async def aembed_query(self, text):
        return self.embed_query(text)


def judge_view(rec: dict, view: str = "generator") -> tuple[str, list[str]]:
    """What the RAGAS judge is shown.

    generator : exactly what the generator saw - each context carries the same "(document: ..., p. N)" header the
                prompt uses, and the response is shown without its [S#] citation markers (citations are links, not
                claims). Entities named only in a document title (e.g. "CU-4") are then visible to the judge.
    raw       : page text only and the response with "[Source n]" markers (the earlier evaluation setting).
    """
    if view == "raw":
        return rec["answer_raw"].replace("[S", "[Source ").strip(), rec["contexts"] or [""]
    from .parsing import loc_label
    types = rec.get("source_types") or [{"csv": "csv", "md": "md"}.get(d.rsplit(".", 1)[-1], "pdf") for d, _ in rec["source_locs"]]
    ctx = [f"(document: {d}, {loc_label(t, p)})\n{c}" for (d, p), t, c in zip(rec["source_locs"], types, rec["contexts"])]
    resp = re.sub(r"\s*\[S\d+\]", "", rec["answer_raw"]).strip()
    return resp, ctx or [""]


def ragas_scores(records: list[dict], metrics_names=("faithfulness", "answer_relevancy"),
                 max_workers: int = 4, view: str = "generator") -> tuple[dict, list[dict]]:
    """Run the RAGAS framework on answered records. Returns (mean scores, per-sample rows)."""
    from langchain_core.embeddings import Embeddings
    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, RunConfig, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy

    ensure_judge()
    llm = LangchainLLMWrapper(ChatOpenAI(base_url=f"{JUDGE_URL}/v1", api_key="local", model="judge",
                                         temperature=0.0, max_tokens=1024, timeout=180))
    emb_impl = _BGEEmbeddings()

    class LCEmb(Embeddings):
        def embed_documents(self, texts):
            return emb_impl.embed_documents(texts)

        def embed_query(self, text):
            return emb_impl.embed_query(text)

    emb = LangchainEmbeddingsWrapper(LCEmb())
    available = {"faithfulness": Faithfulness(), "answer_relevancy": ResponseRelevancy(strictness=1),
                 "context_precision": LLMContextPrecisionWithReference(), "context_recall": LLMContextRecall()}
    mets = [available[m] for m in metrics_names]
    answered = [r for r in records if _answered(r)]
    samples = []
    for r in answered:
        resp, ctx = judge_view(r, view)
        samples.append(SingleTurnSample(user_input=r["question"], response=resp, retrieved_contexts=ctx, reference=r["ground_truth"]))
    result = evaluate(EvaluationDataset(samples=samples), metrics=mets, llm=llm, embeddings=emb,
                      run_config=RunConfig(max_workers=max_workers, timeout=600, max_retries=3), show_progress=False,
                      raise_exceptions=False)
    df = result.to_pandas()
    df["qid"] = [r["qid"] for r in answered]
    cols = [c for c in df.columns if c not in ("user_input", "response", "retrieved_contexts", "reference", "qid")]
    means = {c: float(df[c].mean()) for c in cols}
    means["nan_rate"] = {c: float(df[c].isna().mean()) for c in cols}
    means["n_scored"] = len(df)
    return means, df[["qid"] + cols].to_dict(orient="records")
