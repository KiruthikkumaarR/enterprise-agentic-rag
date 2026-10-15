"""Development check of the RAGAS judge input (no test data involved).

Generates answers for the 60 development questions with the final system, then scores the SAME answers with the
judge shown (a) page text + response with [Source n] markers ("raw", the earlier setting) and (b) exactly what the
generator saw: per-source document header + text, response without citation markers ("generator").
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config, evaluation, generator, store
from rag.corpus import load_jsonl
from rag.pipeline import RAGPipeline


def dev_rows(n=60):
    train = load_jsonl(config.EVAL_DIR / "train_qa.jsonl")
    facts = sorted({r["fact_id"] for r in train})
    random.Random(config.SEED).shuffle(facts)
    val = set(facts[: len(facts) // 10])
    by_fact = {}
    for r in train:
        if r["fact_id"] in val and r["fact_id"] not in by_fact:
            by_fact[r["fact_id"]] = r
    return random.Random(1).sample(list(by_fact.values()), n)


if __name__ == "__main__":
    store.ensure_qdrant(); generator.ensure_llm()
    recs = evaluation.run_queries(RAGPipeline(audit=False), dev_rows(), "full", log_every=0)
    out = {}
    for view in ("raw", "generator"):
        m, rows = evaluation.ragas_scores(recs, ("faithfulness",), view=view)
        out[view] = {"faithfulness": m["faithfulness"], "below_1": sum(r["faithfulness"] < 1 for r in rows), "n": m["n_scored"]}
        print(view, out[view], flush=True)
    (config.ARTIFACT_DIR / "dev_judge_view.json").write_text(json.dumps(out, indent=2))
