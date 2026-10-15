"""End-to-end agentic RAG pipeline with audit logging.

full  : hybrid (dense+sparse, RRF) -> cross-encoder top-5 -> parent expansion -> Phi-4-mini
        -> faithfulness guardrail -> bounded regeneration -> verified answer / explicit fallback
naive : dense top-5 -> Phi-4-mini (same prompt), no reranking, no verification
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone

from . import config, generator, guardrail
from .parsing import loc_label
from .reranker import CrossEncoderReranker
from .retrieval import HybridRetriever

FALLBACK = "I cannot verify an answer to this question from the available documents."


def expand_to_parents(children: list[dict]) -> list[dict]:
    """Deduplicate top children by parent (page/section/row), keep rerank order."""
    seen, sources = {}, []
    for c in children:
        pid = c["parent_id"]
        if pid in seen:
            seen[pid]["child_ids"].append(c["chunk_id"])
            continue
        src = {"parent_id": pid, "doc": c["doc"], "doc_type": c["doc_type"], "page": c["page"],
               "section": c["section"], "title": c["text"].split("\n", 1)[0].strip("[]").split(" | ")[0],
               "text": c["parent_text"], "child_ids": [c["chunk_id"]],
               "score": c.get("rerank_score", c.get("dense_score"))}
        seen[pid] = src
        sources.append(src)
    return sources


def render_citations(answer: str, sources: list[dict]) -> str:
    def sub(m):
        i = int(m.group(1))
        if 1 <= i <= len(sources):
            s = sources[i - 1]
            return f"[{s['doc']}, {loc_label(s['doc_type'], s['page'])}]"
        return m.group(0)
    return re.sub(r"\[S(\d+)\]", sub, answer)


class RAGPipeline:
    def __init__(self, reranker_path=None, audit: bool = True, collection: str = config.COLLECTION):
        path = reranker_path or (config.FINETUNED_RERANKER_DIR if config.FINETUNED_RERANKER_DIR.exists()
                                 else config.RERANKER_MODEL)
        self.retriever = HybridRetriever(collection=collection)
        self.reranker = CrossEncoderReranker(path)
        self.reranker_name = str(path)
        self.min_score = (config.RERANK_MIN_SCORE_FINETUNED if str(path) == str(config.FINETUNED_RERANKER_DIR)
                          else config.RERANK_MIN_SCORE)
        self.audit = audit
        guardrail.get_verifier()
        self._warmup()

    def _warmup(self):
        """One throw-away pass so MPS kernels are compiled before the first real query."""
        cands = self.retriever.retrieve("warm-up query", 5)
        self.reranker.rerank("warm-up query", cands, 5, None)
        guardrail.get_verifier().entailment(["warm-up premise."], "warm-up hypothesis.")

    # ------------------------------------------------------------------
    def answer(self, question: str, mode: str = "full", query_filter=None) -> dict:
        """query_filter restricts retrieval (e.g. to documents the user is cleared to see)."""
        t = {"start": time.perf_counter()}
        qid = uuid.uuid4().hex[:12]
        if mode == "naive":
            children = self.retriever.retrieve_dense_only(question, config.FINAL_TOP_K, query_filter)
            t["retrieval"] = time.perf_counter()
            candidates = children
            t["rerank"] = t["retrieval"]
        else:
            candidates = self.retriever.retrieve(question, config.HYBRID_CANDIDATES, query_filter)
            t["retrieval"] = time.perf_counter()
            children = self.reranker.rerank(question, candidates, config.FINAL_TOP_K, self.min_score)
            t["rerank"] = time.perf_counter()
        sources = expand_to_parents(children)

        attempts, failed, verdict, gen = [], None, None, None
        if not sources:
            final, status = FALLBACK, "no_evidence"
            t["generation"] = t["verify"] = time.perf_counter()
        else:
            n_tries = 1 if mode == "naive" else 1 + config.MAX_REGENERATIONS
            gen_time = ver_time = 0.0
            for attempt in range(n_tries):
                g0 = time.perf_counter()
                gen = generator.chat(generator.build_messages(question, sources, failed_claims=failed))
                gen_time += time.perf_counter() - g0
                if mode == "naive":
                    attempts.append({"attempt": attempt, "raw": gen["text"]})
                    break
                v0 = time.perf_counter()
                verdict = guardrail.verify(gen["text"], sources, question=question)
                ver_time += time.perf_counter() - v0
                attempts.append({"attempt": attempt, "raw": gen["text"], "verdict": verdict})
                if verdict["status"] in ("verified", "abstained"):
                    break
                failed = [c["claim"] for c in verdict["claims"] if not c["supported"]]
            t["generation"] = t["rerank"] + gen_time
            t["verify"] = t["generation"] + ver_time
            raw = attempts[-1]["raw"]
            if mode == "naive":
                status = "abstained" if generator.REFUSAL_TOKEN in raw else "unverified_baseline"
                final = FALLBACK if status == "abstained" else raw
            elif verdict["status"] == "abstained":
                final, status = FALLBACK, "abstained"
            elif verdict["status"] == "verified":
                final, status = raw, "verified"
            elif verdict["supported"]:
                kept = " ".join(c["raw"] for c in verdict["claims"] if c["supported"])
                dropped = verdict["total"] - verdict["supported"]
                final, status = kept + f" ({dropped} unverifiable statement(s) removed.)", "partially_verified"
            else:
                final, status = FALLBACK, "unverified_fallback"
        t["end"] = time.perf_counter()

        cited = sorted({int(n) for n in re.findall(r"\[S(\d+)\]", final)})
        result = {
            "query_id": qid, "question": question, "mode": mode, "status": status,
            "answer": render_citations(final, sources), "answer_raw": final,
            "citations": [{"source": i, "doc": sources[i - 1]["doc"], "page": sources[i - 1]["page"],
                           "loc": loc_label(sources[i - 1]["doc_type"], sources[i - 1]["page"])}
                          for i in cited if 1 <= i <= len(sources)],
            "sources": sources,
            "retrieved": [{k: c.get(k) for k in ("chunk_id", "doc", "page", "dense_rank", "sparse_rank", "dense_score",
                                                  "sparse_score", "rrf_score", "rerank_score")} for c in children],
            "candidates": [{k: c.get(k) for k in ("chunk_id", "rrf_score", "dense_rank", "sparse_rank")} for c in candidates],
            "attempts": attempts, "regenerations": max(0, len(attempts) - 1),
            "timings_s": {"retrieval": t["retrieval"] - t["start"], "rerank": t["rerank"] - t["retrieval"],
                          "generation": t["generation"] - t["rerank"], "verification": t["verify"] - t["generation"],
                          "total": t["end"] - t["start"]},
            "models": {"llm": config.LLM_NAME, "reranker": self.reranker_name, "nli": config.NLI_MODEL},
        }
        if self.audit:
            self._log(result)
        return result

    def _log(self, r: dict):
        rec = {"ts": datetime.now(timezone.utc).isoformat(), **{k: r[k] for k in (
            "query_id", "question", "mode", "status", "answer", "citations", "retrieved", "regenerations", "timings_s")},
            "verifier": [{"attempt": a["attempt"], "status": a.get("verdict", {}).get("status"),
                          "claims": [{k: c[k] for k in ("claim", "citations", "entailment", "numbers_ok", "supported", "reason")}
                                     for c in a.get("verdict", {}).get("claims", [])]} for a in r["attempts"]]}
        with open(config.AUDIT_DIR / f"audit_{datetime.now():%Y%m%d}.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
