"""Hybrid retrieval: BGE-M3 sparse + dense search in Qdrant fused with Reciprocal Rank Fusion."""
from __future__ import annotations

from . import config, store
from .embedder import get_embedder


def rrf_fuse(ranked_lists: dict[str, list], k: int = config.RRF_K) -> list[dict]:
    """Cormack et al. (2009): score(d) = sum_i 1 / (k + rank_i(d))."""
    fused: dict[str, dict] = {}
    for name, hits in ranked_lists.items():
        for rank, h in enumerate(hits, start=1):
            cid = h.payload["chunk_id"]
            e = fused.setdefault(cid, {**h.payload, "rrf_score": 0.0})
            e["rrf_score"] += 1.0 / (k + rank)
            e[f"{name}_rank"] = rank
            e[f"{name}_score"] = float(h.score)
    return sorted(fused.values(), key=lambda e: e["rrf_score"], reverse=True)


class HybridRetriever:
    def __init__(self, qc=None, collection: str = config.COLLECTION):
        self.qc = qc or store.client()
        self.collection = collection
        self.emb = get_embedder()

    def encode_query(self, query: str):
        dense, sparse = self.emb.encode([query])
        return dense[0], sparse[0]

    def retrieve(self, query: str, k: int = config.HYBRID_CANDIDATES, query_filter=None) -> list[dict]:
        """query_filter: optional Qdrant filter applied inside both searches (used for access control)."""
        dense, sparse = self.encode_query(query)
        lists = {"dense": store.search_dense(self.qc, dense, k, self.collection, query_filter),
                 "sparse": store.search_sparse(self.qc, sparse, k, self.collection, query_filter)}
        return rrf_fuse(lists)[:k]

    def retrieve_dense_only(self, query: str, k: int = config.FINAL_TOP_K, query_filter=None) -> list[dict]:
        """Naive-RAG baseline: single dense search, no fusion, no reranking."""
        dense, _ = self.encode_query(query)
        return [{**h.payload, "dense_score": float(h.score), "dense_rank": r}
                for r, h in enumerate(store.search_dense(self.qc, dense, k, self.collection, query_filter), start=1)]

    def retrieve_single(self, query: str, mode: str, k: int) -> list[dict]:
        dense, sparse = self.encode_query(query)
        hits = (store.search_dense(self.qc, dense, k, self.collection) if mode == "dense"
                else store.search_sparse(self.qc, sparse, k, self.collection))
        return [{**h.payload, f"{mode}_score": float(h.score)} for h in hits]
