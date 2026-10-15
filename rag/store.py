"""Qdrant hybrid collection: dense (HNSW + int8 scalar quantisation) + sparse vectors."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict

import requests
from qdrant_client import QdrantClient, models

from . import config
from .parsing import Chunk

DENSE, SPARSE = "dense", "sparse"


def qdrant_alive(url: str = config.QDRANT_URL) -> bool:
    try:
        return requests.get(f"{url}/readyz", timeout=1).ok
    except requests.RequestException:
        return False


def ensure_qdrant(timeout: float = 30) -> str:
    """Start the local Qdrant binary if nothing is listening yet."""
    if qdrant_alive():
        return "already running"
    config.QDRANT_STORAGE.mkdir(parents=True, exist_ok=True)
    log = open(config.ARTIFACT_DIR / "qdrant.log", "a")
    subprocess.Popen([str(config.QDRANT_BIN)], cwd=config.QDRANT_STORAGE.parent, stdout=log, stderr=log,
                     env={**os.environ, "QDRANT__STORAGE__STORAGE_PATH": str(config.QDRANT_STORAGE),
                          "QDRANT__SERVICE__HTTP_PORT": "6333", "QDRANT__SERVICE__GRPC_PORT": "6334",
                          "QDRANT__TELEMETRY_DISABLED": "true"},
                     start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if qdrant_alive():
            return "started"
        time.sleep(0.5)
    raise RuntimeError("Qdrant did not start; see artifacts/qdrant.log")


def client() -> QdrantClient:
    return QdrantClient(url=config.QDRANT_URL, timeout=60)


def create_collection(qc: QdrantClient, name: str = config.COLLECTION):
    if qc.collection_exists(name):
        qc.delete_collection(name)
    qc.create_collection(
        name,
        vectors_config={DENSE: models.VectorParams(size=config.DENSE_DIM, distance=models.Distance.COSINE,
                                                   hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128))},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))},
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, quantile=0.99, always_ram=True)),
        optimizers_config=models.OptimizersConfigDiff(indexing_threshold=0),  # build HNSW immediately
    )


def index_chunks(qc: QdrantClient, chunks: list[Chunk], dense, sparse, name: str = config.COLLECTION, batch: int = 64):
    points = [models.PointStruct(id=i, vector={DENSE: d.tolist(),
                                               SPARSE: models.SparseVector(indices=list(s.keys()), values=list(s.values()))},
                                 payload=asdict(c))
              for i, (c, d, s) in enumerate(zip(chunks, dense, sparse))]
    for i in range(0, len(points), batch):
        qc.upsert(name, points[i:i + batch], wait=True)
    return len(points)


def search_dense(qc: QdrantClient, vec, limit: int, name: str = config.COLLECTION, query_filter=None):
    return qc.query_points(name, query=list(map(float, vec)), using=DENSE, limit=limit, with_payload=True, query_filter=query_filter,
                           search_params=models.SearchParams(hnsw_ef=128, quantization=models.QuantizationSearchParams(
                               rescore=True, oversampling=2.0))).points


def search_sparse(qc: QdrantClient, sp: dict[int, float], limit: int, name: str = config.COLLECTION, query_filter=None):
    return qc.query_points(name, query=models.SparseVector(indices=list(sp.keys()), values=list(sp.values())),
                           using=SPARSE, limit=limit, with_payload=True, query_filter=query_filter).points
