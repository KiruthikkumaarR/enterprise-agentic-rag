"""FastAPI backend: REST API over the RAG pipeline + static web UI with a source-citation drawer.

Run:  .venv/bin/uvicorn api.server:app --port 8000
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from rag import config, generator, store
from rag.pipeline import RAGPipeline

STATIC = Path(__file__).parent / "static"
state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.ensure_qdrant()
    generator.ensure_llm()
    state["pipeline"] = RAGPipeline()
    yield


app = FastAPI(title="Enterprise Agentic RAG Engine", version="1.0", lifespan=lifespan)


class Query(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    mode: str = Field("full", pattern="^(full|naive)$")


@app.get("/api/health")
def health():
    return {"qdrant": store.qdrant_alive(), "llm": generator.llm_alive(), "pipeline": "pipeline" in state,
            "llm_model": config.LLM_NAME, "reranker": state["pipeline"].reranker_name if "pipeline" in state else None}


@app.post("/api/query")
def query(q: Query):
    r = state["pipeline"].answer(q.question, q.mode)
    return {k: r[k] for k in ("query_id", "question", "mode", "status", "answer", "answer_raw", "citations",
                              "sources", "retrieved", "regenerations", "timings_s", "attempts")}


@app.get("/api/documents")
def documents():
    return sorted(p.name for p in config.CORPUS_DIR.iterdir() if p.is_file())


@app.get("/api/documents/{name}/page/{page}.png")
def page_image(name: str, page: int):
    """Render a PDF page so the user can inspect exactly where a claim came from."""
    path = (config.CORPUS_DIR / name).resolve()
    if path.parent != config.CORPUS_DIR.resolve() or not path.exists() or path.suffix != ".pdf":
        raise HTTPException(404)
    import pymupdf

    doc = pymupdf.open(path)
    if not 1 <= page <= len(doc):
        raise HTTPException(404)
    return Response(doc[page - 1].get_pixmap(dpi=110).tobytes("png"), media_type="image/png")


@app.get("/api/documents/{name}/raw")
def raw_document(name: str):
    path = (config.CORPUS_DIR / name).resolve()
    if path.parent != config.CORPUS_DIR.resolve() or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, filename=name)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
