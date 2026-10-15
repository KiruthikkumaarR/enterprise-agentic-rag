"""Faithfulness & citation guardrail.

Every sentence ("claim") of a generated answer must
  1. carry at least one citation [S#] pointing at a source that exists,
  2. have all of its numbers present verbatim in the cited source(s), and
  3. be *entailed* by the cited source(s) according to an independent NLI
     cross-encoder (DeBERTa-v3-large NLI cross-encoder), max over premise windows.
Claims failing any check are reported back so the pipeline can regenerate or
fall back to an explicit "cannot be verified" answer.
"""
from __future__ import annotations

import re
from functools import lru_cache

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from . import config
from .generator import REFUSAL_TOKEN

_CITE = re.compile(r"\[S(\d+)\]")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


class NLIVerifier:
    def __init__(self, name: str = config.NLI_MODEL, device: str | None = None):
        self.device = device or config.device()
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForSequenceClassification.from_pretrained(name).to(self.device).eval()
        labels = {v.lower(): k for k, v in self.model.config.id2label.items()}
        self.ent, self.con = labels["entailment"], labels["contradiction"]

    @torch.no_grad()
    def entailment(self, premises: list[str], hypothesis: str) -> list[float]:
        enc = self.tok(premises, [hypothesis] * len(premises), padding=True, truncation="only_first",
                       max_length=512, return_tensors="pt").to(self.device)
        probs = self.model(**enc).logits.softmax(-1).float().cpu()
        return probs[:, self.ent].tolist()


@lru_cache(maxsize=1)
def get_verifier() -> NLIVerifier:
    return NLIVerifier()


# ---------------------------------------------------------------------------
def split_claims(answer: str) -> list[str]:
    """Sentence split that keeps trailing citations with their sentence and ignores decimals."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\[])|\n+", answer.strip())
    claims: list[str] = []
    for p in (x.strip() for x in parts):
        if not p:
            continue
        if claims and _CITE.sub("", p).strip(" .") == "":   # citation-only fragment
            claims[-1] += " " + p
        else:
            claims.append(p)
    return claims


def strip_citations(text: str) -> str:
    return re.sub(r"\s+", " ", _CITE.sub("", text)).strip().rstrip(" .") + "."


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(text)}


def premise_windows(source: dict) -> list[str]:
    """Linearise a source into short NLI premises.

    * every premise is prefixed with "document title | section", so entities named only in the title (e.g. "CU-4")
      are visible to the NLI model;
    * each table row becomes one sentence and carries the table's caption (the prose line just before it), so units
      stated once in a caption such as "(EUR million)" still apply to every row;
    * each table also yields one combined premise, so a sentence that summarises several rows can be entailed.
    """
    section = " | ".join(x for x in (source.get("title", ""), source.get("section", "")) if x)
    out, header, rows, caption = [], None, [], ""
    prose = []

    def flush():
        if len(rows) > 1:
            out.append(f"{section}: {caption} " + " ".join(rows))
        rows.clear()

    for line in source["text"].splitlines():
        line = line.strip()
        if line.startswith("|") and not set(line) <= set("|-: "):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if header is None:
                header = cells
                continue
            if len(cells) == 2:
                col = header[1] if len(header) > 1 and header[1].lower() not in ("value", "values", "") else ""
                row = f"The {cells[0]}{' in ' + col if col else ''} is {cells[1]}."
            else:
                row = ", ".join(f"{h} is {c}" for h, c in zip(header, cells)) + "."
            rows.append(row)
            out.append(f"{section}: {caption} {row}".replace("  ", " "))
        elif line.startswith("|"):
            continue
        else:
            if header is not None:
                flush()
            header = None
            if line:
                prose.append(line.lstrip("# "))
                caption = line.lstrip("# ")
    flush()
    text = " ".join(prose)
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    for i in range(0, len(sents), 2):
        out.append(f"{section}: " + " ".join(sents[i:i + 3]))
    if source.get("doc_type") == "csv":
        out.append(source["text"])
    return out or [source["text"]]


def hypothesis(claim: str, question: str | None) -> str:
    """Short, subject-less claims ("87.3%.") are weak hypotheses; anchor them to the question."""
    if question and len(claim.split()) <= 4:
        return f'The answer to the question "{question.strip()}" is {claim.rstrip(".")}.'
    return claim


def verify(answer: str, sources: list[dict], threshold: float = config.ENTAILMENT_THRESHOLD,
           question: str | None = None) -> dict:
    if REFUSAL_TOKEN in answer:
        return {"status": "abstained", "claims": [], "supported": 0, "total": 0, "faithfulness": None}
    nli = get_verifier()
    windows = [premise_windows(s) for s in sources]
    claims = []
    for raw in split_claims(answer):
        cites = sorted({int(n) for n in _CITE.findall(raw)})
        valid = [c for c in cites if 1 <= c <= len(sources)]
        hyp = strip_citations(raw)
        rec = {"claim": hyp, "raw": raw, "citations": cites, "entailment": 0.0, "numbers_ok": False,
               "supported": False, "reason": ""}
        if not cites:
            rec["reason"] = "no citation"
        elif len(valid) != len(cites):
            rec["reason"] = "citation to non-existent source"
        else:
            cited_text = " ".join(sources[c - 1]["text"] for c in valid).replace(",", "")
            rec["numbers_ok"] = all(n in cited_text for n in _numbers(hyp))
            prem = [w for c in valid for w in windows[c - 1]]
            rec["entailment"] = max(nli.entailment(prem, hypothesis(hyp, question)))
            if not rec["numbers_ok"]:
                rec["reason"] = "number not found in cited source"
            elif rec["entailment"] < threshold:
                rec["reason"] = f"not entailed (p={rec['entailment']:.2f})"
            else:
                rec["supported"] = True
        claims.append(rec)
    n_ok = sum(c["supported"] for c in claims)
    status = "verified" if claims and n_ok == len(claims) else ("partially_verified" if n_ok else "unverified")
    return {"status": status, "claims": claims, "supported": n_ok, "total": len(claims),
            "faithfulness": n_ok / len(claims) if claims else 0.0}
