"""Grounded generation with Phi-4-mini served locally by llama.cpp (``llama-server``)."""
from __future__ import annotations

import subprocess
import time

import requests

from . import config
from .parsing import linearize_tables, loc_label

REFUSAL_TOKEN = "INSUFFICIENT_EVIDENCE"

SYSTEM_PROMPT = f"""You are the {{company}} document assistant. You answer questions strictly from the numbered SOURCES supplied with each question.

Rules:
1. Use ONLY facts explicitly stated in the SOURCES. Never use outside knowledge, never guess, never infer values that are not written.
2. End every sentence with the citation of the source(s) that support it, written as [S1] or [S1][S2].
3. Copy numbers, units, dates, codes and names exactly as they appear in the sources.
4. Always answer with 1-3 complete sentences that restate the subject of the question. Never answer with only a number, date or name. Do not add background, advice or caveats.
5. If the SOURCES do not contain the answer, reply with exactly: {REFUSAL_TOKEN}

Examples of the required style (fictional values):
QUESTION: What is the dry weight of the HX-999?
ANSWER: The dry weight of the HX-999 is 812 kg [S1].
QUESTION: Who is the account manager for Example Water Oy?
ANSWER: The account manager for Example Water Oy is Jane Doe [S2].
QUESTION: When was asset AST-0000 last serviced?
ANSWER: Asset AST-0000 was last serviced on 2026-01-31 [S1]."""

REGEN_SUFFIX = """

Your previous answer contained statements that are NOT supported by the cited sources:
{failed}
Write a corrected answer. Every sentence must be directly supported by the source it cites. If the sources do not contain the answer, reply with exactly: """ + REFUSAL_TOKEN


def format_sources(sources: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sources, start=1):
        blocks.append(f"[S{i}] (document: {s['doc']}, {loc_label(s['doc_type'], s['page'])})\n{linearize_tables(s['text'])}")
    return "\n\n".join(blocks)


def build_messages(question: str, sources: list[dict], company: str = "Halvorsen Industrial Systems",
                   failed_claims: list[str] | None = None) -> list[dict]:
    user = f"SOURCES:\n\n{format_sources(sources)}\n\nQUESTION: {question}"
    if failed_claims:
        user += REGEN_SUFFIX.format(failed="\n".join(f"- {c}" for c in failed_claims))
    return [{"role": "system", "content": SYSTEM_PROMPT.format(company=company)},
            {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
def llm_alive(url: str = config.LLM_URL) -> bool:
    """True only if *our* model is being served on that port (another llama-server may be running)."""
    try:
        if not requests.get(f"{url}/health", timeout=1).ok:
            return False
        ids = [m["id"] for m in requests.get(f"{url}/v1/models", timeout=2).json().get("data", [])]
        return config.LLM_NAME in ids
    except (requests.RequestException, ValueError):
        return False


def ensure_llm(timeout: float = 180) -> str:
    """Start llama-server with the Phi-4-mini GGUF if it is not running."""
    if llm_alive():
        return "already running"
    if not config.LLM_GGUF.exists():
        raise FileNotFoundError(f"GGUF model not found: {config.LLM_GGUF}")
    port = config.LLM_URL.rsplit(":", 1)[-1]
    log = open(config.ARTIFACT_DIR / "llama_server.log", "a")
    subprocess.Popen([config.LLM_SERVER_BIN, "-m", str(config.LLM_GGUF), "--port", port, "--host", "127.0.0.1",
                      "-c", str(config.LLM_CTX), "-ngl", "99", "-np", "2", "--jinja", "--alias", config.LLM_NAME,
                      "--seed", str(config.SEED)],
                     stdout=log, stderr=log, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if llm_alive():
            return "started"
        time.sleep(1)
    raise RuntimeError("llama-server did not become healthy; see artifacts/llama_server.log")


def chat(messages: list[dict], max_tokens: int = config.MAX_NEW_TOKENS, temperature: float = config.TEMPERATURE) -> dict:
    t0 = time.time()
    r = requests.post(f"{config.LLM_URL}/v1/chat/completions", timeout=300, json={
        "model": config.LLM_NAME, "messages": messages, "temperature": temperature, "top_p": 1.0,
        "max_tokens": max_tokens, "seed": config.SEED, "cache_prompt": True})
    r.raise_for_status()
    data = r.json()
    return {"text": data["choices"][0]["message"]["content"].strip(), "usage": data.get("usage", {}),
            "latency_s": time.time() - t0}
