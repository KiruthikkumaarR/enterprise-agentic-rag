"""Final RAGAS faithfulness with the judge shown exactly what the generator saw (see evaluation.judge_view).

Scores the saved test-set answers of: guardrailed pipeline (base Phi-4-mini), naive baseline, guardrailed
pipeline with the LoRA-tuned Phi-4-mini. Answer relevancy is also computed for the LoRA run (the other two
already have it from scripts/run_evaluation.py). Writes artifacts/eval/ragas_generator_view.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config, evaluation
from rag.corpus import load_jsonl

RUNS = {"full": ("eval/full_test.jsonl", ("faithfulness", "answer_relevancy")),
        "naive": ("eval/naive_test.jsonl", ("faithfulness",)),
        "lora": ("eval_lora/full_test.jsonl", ("faithfulness", "answer_relevancy"))}

if __name__ == "__main__":
    out_path = config.ARTIFACT_DIR / "eval" / "ragas_generator_view.json"
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    for name, (path, metrics) in RUNS.items():
        if name in out:
            continue
        m, rows = evaluation.ragas_scores(load_jsonl(config.ARTIFACT_DIR / path), metrics, view="generator")
        out[name] = {"means": m, "rows": rows}
        print(name, m, flush=True)
        out_path.write_text(json.dumps(out, indent=2, default=float))     # resumable
