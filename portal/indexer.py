"""Index portal documents (generated or uploaded) into their own Qdrant collection with access metadata."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from pathlib import Path

from qdrant_client import models

from rag import parsing, store
from rag.embedder import get_embedder

from . import db
from .company_data import DOC_DIR, UPLOAD_DIR

COLLECTION = "company_portal"
SUPPORTED = set(parsing.PARSERS)


def ensure_collection(qc, recreate: bool = False):
    if recreate or not qc.collection_exists(COLLECTION):
        store.create_collection(qc, COLLECTION)
        for field, schema in (("level", models.PayloadSchemaType.INTEGER), ("departments", models.PayloadSchemaType.KEYWORD),
                              ("doc", models.PayloadSchemaType.KEYWORD)):
            qc.create_payload_index(COLLECTION, field, schema)


def path_for(doc: dict) -> Path:
    return (UPLOAD_DIR if doc.get("source") == "upload" else DOC_DIR) / doc["doc"]


def index_document(qc, doc: dict, batch: int = 128) -> int:
    """Parse, embed and upsert one document. Point ids are derived from chunk ids, so re-indexing replaces."""
    path = path_for(doc)
    chunks = parsing.PARSERS[path.suffix.lower()](path)
    if not chunks:
        return 0
    emb = get_embedder()
    dense, sparse = emb.encode([c.text for c in chunks])
    meta = {"level": int(doc["level"]), "departments": doc["departments"], "title": doc["title"], "category": doc.get("category", "")}
    points = [models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, c.chunk_id)),
                                 vector={store.DENSE: d.tolist(), store.SPARSE: models.SparseVector(indices=list(s.keys()), values=list(s.values()))},
                                 payload={**asdict(c), **meta})
              for c, d, s in zip(chunks, dense, sparse)]
    for i in range(0, len(points), batch):
        qc.upsert(COLLECTION, points[i:i + batch], wait=True)
    with db.conn() as c:
        c.execute("UPDATE documents SET chunks=?, size_bytes=? WHERE doc=?", (len(chunks), path.stat().st_size, doc["doc"]))
    return len(chunks)


def delete_document(qc, name: str):
    qc.delete(COLLECTION, points_selector=models.FilterSelector(filter=models.Filter(
        must=[models.FieldCondition(key="doc", match=models.MatchValue(value=name))])), wait=True)


def build_all(log=print) -> dict:
    store.ensure_qdrant()
    qc = store.client()
    ensure_collection(qc, recreate=True)
    with db.conn() as c:
        docs = [db.doc_row(r) for r in c.execute("SELECT * FROM documents")]
    t0, total = time.time(), 0
    for i, d in enumerate(docs, 1):
        n = index_document(qc, d)
        total += n
        log(f"[{i}/{len(docs)}] {d['doc']}: {n} chunks")
    return {"documents": len(docs), "chunks": total, "seconds": round(time.time() - t0, 1)}
