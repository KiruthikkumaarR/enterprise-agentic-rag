"""A/B check of the faithfulness changes on a DEVELOPMENT set (never the test set).

Dev questions: one question per validation fact, i.e. facts held out of reranker training and disjoint from the
200 test facts. Variant A = original prompt with Markdown tables; variant B = full-sentence examples + linearised
tables. Scores: label-based correctness and RAGAS faithfulness with the Qwen2.5-7B judge.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config, evaluation, generator, store
from rag.corpus import load_jsonl
from rag.pipeline import RAGPipeline

OLD_PROMPT = generator.SYSTEM_PROMPT.split("4. Always answer")[0] + (
    '4. Answer in 1-3 short, complete sentences that name the subject of the question (e.g. "The maximum head of the '
    'HX-200 is 50 m [S1]."). Do not add background, advice or caveats.\n5. If the SOURCES do not contain the answer, '
    f"reply with exactly: {generator.REFUSAL_TOKEN}")
NEW_PROMPT, NEW_FORMAT = generator.SYSTEM_PROMPT, generator.format_sources


def old_format(sources):
    return "\n\n".join(f"[S{i}] (document: {s['doc']}, {generator.loc_label(s['doc_type'], s['page'])})\n{s['text']}"
                       for i, s in enumerate(sources, 1))


def main(n=60):
    train = load_jsonl(config.EVAL_DIR / "train_qa.jsonl")
    facts = sorted({r["fact_id"] for r in train})
    random.Random(config.SEED).shuffle(facts)
    val = facts[: len(facts) // 10]
    by_fact = {}
    for r in train:
        if r["fact_id"] in val and r["fact_id"] not in by_fact:
            by_fact[r["fact_id"]] = r
    dev = random.Random(1).sample(list(by_fact.values()), n)
    store.ensure_qdrant(); generator.ensure_llm()
    pipe = RAGPipeline(audit=False)
    out = {}
    for name, prompt, fmt in (("A_original", OLD_PROMPT, old_format), ("B_new", NEW_PROMPT, NEW_FORMAT)):
        generator.SYSTEM_PROMPT, generator.format_sources = prompt, fmt
        evaluation.CONTEXT_FN = (lambda t: t) if name == "A_original" else generator.linearize_tables   # judge sees what the generator saw
        recs = evaluation.run_queries(pipe, dev, "full", log_every=0)
        s = evaluation.score_records(recs)
        rg, _ = evaluation.ragas_scores(recs, metrics_names=("faithfulness",))
        terse = sum(len(r["answer_raw"].split()) <= 5 for r in recs if r["status"] == "verified")
        out[name] = {"correct": s["correct"], "answered": s["answered"], "ragas_faithfulness": rg["faithfulness"],
                     "terse_answers": terse, "n": len(recs)}
        print(name, out[name], flush=True)
    generator.SYSTEM_PROMPT, generator.format_sources = NEW_PROMPT, NEW_FORMAT
    evaluation.CONTEXT_FN = generator.linearize_tables
    (config.ARTIFACT_DIR / "dev_faithfulness_ab.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
