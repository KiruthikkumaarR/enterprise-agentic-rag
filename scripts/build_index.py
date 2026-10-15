"""Generate corpus -> parse/chunk -> embed with BGE-M3 -> index into Qdrant.

Usage:  python scripts/build_index.py [--regenerate]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config, corpus, parsing, store
from rag.embedder import get_embedder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regenerate", action="store_true", help="rebuild the synthetic corpus and QA sets first")
    args = ap.parse_args()
    if args.regenerate or not any(config.CORPUS_DIR.iterdir()):
        print(corpus.build_corpus())
    chunks = parsing.parse_corpus()
    parsing.save_chunks(chunks)
    print(parsing.validate_ground_truth(chunks, corpus.load_jsonl(config.EVAL_DIR / "facts.jsonl"))["missing"], "labels missing")
    print(store.ensure_qdrant())
    t = time.time()
    dense, sparse = get_embedder().encode([c.text for c in chunks])
    print(f"embedded {len(chunks)} chunks in {time.time() - t:.1f}s")
    qc = store.client()
    store.create_collection(qc)
    store.index_chunks(qc, chunks, dense, sparse)
    print(qc.get_collection(config.COLLECTION).model_dump(include={"status", "points_count"}))


if __name__ == "__main__":
    main()
