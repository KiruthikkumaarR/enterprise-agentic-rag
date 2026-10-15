"""Layout-aware document parsing and parent-child chunking.

* PDF  - PyMuPDF: tables are detected geometrically and converted to Markdown,
         headings are detected from font size, running headers/footers dropped.
* DOCX - python-docx: body order preserved, explicit page breaks tracked,
         Word tables converted to Markdown.
* CSV  - one child chunk per data row, rendered as ``column: value`` pairs.
* MD   - split on ``##`` sections.

Each *parent* is a full page / section / row (the unit we cite), each *child* is
a paragraph group or a whole table inside it (the unit we embed and rerank).
Tables are never split, so their structure survives chunking.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

CHILD_WORDS = 110

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+\d{1,3}(?:[ -]?\d{2,4}){2,4}")


def redact_pii(text: str) -> str:
    """Remove direct contact identifiers before anything is indexed."""
    return _PHONE.sub("[PHONE]", _EMAIL.sub("[EMAIL]", text))


@dataclass
class Chunk:
    chunk_id: str
    parent_id: str
    doc: str
    doc_type: str
    page: int
    section: str
    kind: str          # text | table | row
    text: str          # child text (what is embedded)
    parent_text: str   # full page / section text (expanded context)

    @property
    def loc(self) -> str:
        return loc_label(self.doc_type, self.page)


def loc_label(doc_type: str, page: int) -> str:
    return {"csv": f"row {page}", "md": f"section {page}"}.get(doc_type, f"p. {page}")


def _md_table(rows: list[list]) -> str:
    rows = [[("" if c is None else str(c)).replace("\n", " ").strip() for c in r] for r in rows if r]
    if not rows:
        return ""
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _group_paragraphs(paras: list[str], limit: int = CHILD_WORDS) -> list[str]:
    groups, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > limit:
            groups.append(" ".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        groups.append(" ".join(cur))
    return groups


def _emit(chunks, doc, doc_type, page, section, blocks, title):
    """blocks: list of (kind, text) in reading order for one parent unit."""
    parent_id = f"{doc}::{page}"
    parent_text = redact_pii("\n\n".join(t for _, t in blocks))
    paras, children = [], []
    for kind, text in blocks:
        if kind == "table":
            children += [("text", g) for g in _group_paragraphs(paras)]
            paras = []
            children.append(("table", text))
        else:
            paras.append(text)
    children += [("text", g) for g in _group_paragraphs(paras)]
    for i, (kind, text) in enumerate(children):
        header = f"[{title} | {section}]"
        chunks.append(Chunk(f"{parent_id}::{i}", parent_id, doc, doc_type, page, section, kind,
                            redact_pii(f"{header}\n{text}"), parent_text))


# --------------------------------------------------------------------------- PDF
def parse_pdf(path: Path) -> list[Chunk]:
    import pymupdf as fitz

    chunks: list[Chunk] = []
    pdf = fitz.open(path)
    title = pdf.metadata.get("title") or path.stem
    section = title
    for pno, page in enumerate(pdf, start=1):
        h = page.rect.height
        tables = page.find_tables().tables
        tboxes = [fitz.Rect(t.bbox) for t in tables]
        items = []  # (y, kind, text)
        for t, box in zip(tables, tboxes):
            items.append((box.y0, "table", _md_table(t.extract())))
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            r = fitz.Rect(b["bbox"])
            if r.y0 > h - 60 or any(r.intersects(tb) for tb in tboxes):   # footer / inside table
                continue
            spans = [s for line in b["lines"] for s in line["spans"]]
            text = " ".join(s["text"] for s in spans).strip()
            text = re.sub(r"\s+", " ", text)
            if not text:
                continue
            size = max(s["size"] for s in spans)
            kind = "heading" if size >= 13 else "text"
            items.append((r.y0, kind, text))
        items.sort(key=lambda x: x[0])
        blocks = []
        for _, kind, text in items:
            if kind == "heading":
                if text != title:
                    section = text
                blocks.append(("text", f"## {text}"))
            else:
                blocks.append((kind, text))
        _emit(chunks, path.name, "pdf", pno, section, blocks, title)
    return chunks


# --------------------------------------------------------------------------- DOCX
def parse_docx(path: Path) -> list[Chunk]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Document(path)
    title = path.stem.replace("_", " ")
    chunks: list[Chunk] = []
    page, section, blocks = 1, title, []
    pages: list[tuple[int, str, list]] = []
    for el in d.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(el, d)
            if p.style.name == "Title":
                title = p.text.strip()
            if el.xpath(".//w:br[@w:type='page']"):
                pages.append((page, section, blocks))
                page, blocks = page + 1, []
            text = p.text.strip()
            if not text:
                continue
            if p.style.name.startswith("Heading") or p.style.name == "Title":
                if p.style.name != "Title":
                    section = text
                blocks.append(("text", f"## {text}"))
            else:
                blocks.append(("text", text))
        elif tag == "tbl":
            t = Table(el, d)
            blocks.append(("table", _md_table([[c.text for c in r.cells] for r in t.rows])))
    pages.append((page, section, blocks))
    for pno, sec, blk in pages:
        if blk:
            _emit(chunks, path.name, "docx", pno, sec, blk, title)
    return chunks


# --------------------------------------------------------------------------- CSV
def parse_csv(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    title = path.stem.replace("_", " ").title()
    with open(path, newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            body = "; ".join(f"{k}: {v}" for k, v in row.items())
            _emit(chunks, path.name, "csv", i, f"{title} row {i}", [("text", body)], title)
    return chunks


# --------------------------------------------------------------------------- Markdown
def parse_md(path: Path) -> list[Chunk]:
    text = path.read_text()
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), path.stem)
    chunks: list[Chunk] = []
    parts = re.split(r"(?m)^## ", text)
    for sec_no, part in enumerate(parts):
        lines = part.strip().splitlines()
        if not lines:
            continue
        heading = title if sec_no == 0 else lines[0].strip()
        body = lines if sec_no == 0 else lines[1:]
        paras = [p.strip() for p in "\n".join(body).split("\n\n") if p.strip() and not p.startswith("# ")]
        blocks = [("text", f"## {heading}")] + [("text", p.replace("**", "")) for p in paras]
        _emit(chunks, path.name, "md", sec_no, heading, blocks, title)
    return chunks


PARSERS = {".pdf": parse_pdf, ".docx": parse_docx, ".csv": parse_csv, ".md": parse_md}


def parse_corpus(corpus_dir: Path = config.CORPUS_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in sorted(corpus_dir.iterdir()):
        if p.suffix.lower() in PARSERS:
            chunks += PARSERS[p.suffix.lower()](p)
    return chunks


def save_chunks(chunks: list[Chunk], path: Path = config.PROCESSED_DIR / "chunks.jsonl"):
    with open(path, "w") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c)) + "\n")
    return path


def load_chunks(path: Path = config.PROCESSED_DIR / "chunks.jsonl") -> list[Chunk]:
    with open(path) as f:
        return [Chunk(**json.loads(l)) for l in f if l.strip()]


def linearize_tables(text: str) -> str:
    """Rewrite Markdown tables as one plain sentence per row ("Maximum head: 74 m." or
    "Supplier: X; Audit score: 81."). Small LLMs (generator and judge) read rows far more reliably than pipes."""
    out, header = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and set(s) <= set("|-: "):
            continue                                   # separator row
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if header is None:
                header = cells
                continue
            if len(cells) == 2:
                col = header[1] if header[1].lower() not in ("value", "values", "") else ""
                out.append(f"{cells[0]}{f' ({col})' if col else ''}: {cells[1]}.")
            else:
                out.append("; ".join(f"{h}: {c}" for h, c in zip(header, cells)) + ".")
        else:
            header = None
            out.append(line)
    return "\n".join(out)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def validate_ground_truth(chunks: list[Chunk], facts: list[dict]) -> dict:
    """Check that each fact's answer text appears on its labelled page."""
    parents = {}
    for c in chunks:
        parents[(c.doc, c.page)] = norm(c.parent_text)
    bad = [f for f in facts if norm(f["answer"]) not in parents.get((f["doc"], f["page"]), "")]
    return {"checked": len(facts), "missing": len(bad), "examples": bad[:5]}
