"""Halvorsen Intelligence Portal - local-only FastAPI application.

Run (binds to loopback only):
    .venv/bin/uvicorn portal.app:app --host 127.0.0.1 --port 8100
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag import generator, parsing, store
from rag.pipeline import RAGPipeline

from . import access, analytics, db, indexer, reports
from .company_data import ACCOUNTS, DEPARTMENTS, LEVELS, UPLOAD_DIR

STATIC = Path(__file__).parent / "static"
COOKIE = "his_session"
DEMO_MODE = os.environ.get("PORTAL_DEMO", "1") == "1"
MAX_UPLOAD = 25 * 1024 * 1024
state: dict = {}
model_lock = threading.Lock()      # the GPU models are shared; serialise inference and indexing


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    store.ensure_qdrant()
    generator.ensure_llm()
    qc = store.client()
    indexer.ensure_collection(qc)
    state["qc"] = qc
    state["pipeline"] = RAGPipeline(audit=False, collection=indexer.COLLECTION)
    yield


app = FastAPI(title="Halvorsen Intelligence Portal", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # simple CSRF defence: state-changing API calls must carry a custom header (browsers cannot add it cross-site)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/") \
            and request.headers.get("x-his-request") != "1":
        return JSONResponse({"detail": "missing request header"}, status_code=403)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
    return resp


# --------------------------------------------------------------------------- auth helpers
def current_user(request: Request) -> dict:
    u = db.session_user(request.cookies.get(COOKIE))
    if not u:
        raise HTTPException(401, "not signed in")
    return u


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not access.can_manage_users(user):
        raise HTTPException(403, "administrator or executive rights required")
    return user


def visible_docs(user: dict) -> list[dict]:
    with db.conn() as c:
        docs = [db.doc_row(r) for r in c.execute("SELECT * FROM documents ORDER BY created DESC")]
    return [d for d in docs if access.can_see(user, d)]


def get_doc(user: dict, name: str) -> dict:
    with db.conn() as c:
        r = c.execute("SELECT * FROM documents WHERE doc=?", (name,)).fetchone()
    if not r:
        raise HTTPException(404, "document not found")
    d = db.doc_row(r)
    if not access.can_see(user, d):
        db.log_activity(user["username"], "access_denied", name)
        raise HTTPException(404, "document not found")      # do not reveal that it exists
    return d


def public_user(u: dict) -> dict:
    shown = max(2, access.max_level(u))      # employees also read their own department's level-2 documents
    return {k: u[k] for k in ("username", "full_name", "title", "department", "role")} | {
        "clearance": shown, "clearance_label": LEVELS[shown],
        "can_manage_users": access.can_manage_users(u), "upload_levels": access.allowed_upload_levels(u)}


# --------------------------------------------------------------------------- authentication
class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@app.post("/api/login")
def login(body: Login, response: Response):
    uname = body.username.strip().lower()
    if db.recent_failures(uname) >= 5:
        raise HTTPException(429, "too many failed attempts - wait 5 minutes")
    with db.conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=? AND active=1", (uname,)).fetchone()
    ok = bool(r) and db.verify_password(body.password, r["pw_salt"], r["pw_hash"])
    db.log_attempt(uname, ok)
    if not ok:
        time.sleep(0.4)
        raise HTTPException(401, "invalid username or password")
    token = db.create_session(uname)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=db.SESSION_TTL, path="/")
    db.log_activity(uname, "login")
    return public_user(dict(r))


@app.post("/api/logout")
def logout(request: Request, response: Response):
    u = db.session_user(request.cookies.get(COOKIE))
    db.drop_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    if u:
        db.log_activity(u["username"], "logout")
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


@app.get("/api/demo-accounts")
def demo_accounts():
    """Demo convenience for this local, synthetic-data portal. Disable with PORTAL_DEMO=0."""
    if not DEMO_MODE:
        raise HTTPException(404)
    import csv
    with open(ACCOUNTS) as f:
        return [{k: r[k] for k in ("username", "password", "full_name", "title", "department", "role")} for r in csv.DictReader(f)]


# --------------------------------------------------------------------------- assistant
class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=600)


@app.post("/api/ask")
def ask(body: Ask, user: dict = Depends(current_user)):
    if analytics.wants_chart(body.question):          # visual question -> grounded analytics, not free text
        t0 = time.time()
        try:
            spec = analytics.plan(body.question, user)
            res = analytics.run(spec)
            if not res["labels"] and spec.get("filters"):     # an over-specific filter emptied the chart: drop it
                res = analytics.run({**spec, "filters": []})
            if not analytics.allowed(user, res["spec"]["dataset"]):
                raise analytics.SpecError("no access")
            if not res["labels"] or not res["rows_used"]:
                raise analytics.SpecError("no matching records")
            lat = time.time() - t0
            with db.conn() as c:
                c.execute("INSERT INTO queries (ts,username,question,status,answer,citations,retrieved,latency) VALUES (?,?,?,?,?,?,?,?)",
                          (time.time(), user["username"], body.question, "chart", res["title"], json.dumps([res["source_doc"]]), "[]", lat))
            return {"question": body.question, "kind": "chart", "status": "chart", "chart": res,
                    "insight": reports.insight(res), "level": analytics.doc_meta(res["spec"]["dataset"])["level"],
                    "timings": {"total": lat}}
        except Exception:                               # could not map to a dataset -> answer from documents instead
            pass
    with model_lock:
        r = state["pipeline"].answer(body.question, "full", query_filter=access.qdrant_filter(user))
    # defence in depth: never return a source the user may not see, even if the index were mis-tagged
    with db.conn() as c:
        meta = {d["doc"]: d for d in (db.doc_row(x) for x in c.execute("SELECT * FROM documents"))}
    leaked = [s for s in r["sources"] if s["doc"] in meta and not access.can_see(user, meta[s["doc"]])]
    if leaked:
        db.log_activity(user["username"], "blocked_source", ",".join(s["doc"] for s in leaked))
        r["answer"], r["answer_raw"], r["status"], r["sources"], r["citations"] = (
            "I cannot verify an answer to this question from the documents you have access to.",) * 2 + ("abstained", [], [])
    sources = []
    for s in r["sources"]:
        m = meta.get(s["doc"], {})
        sources.append({"doc": s["doc"], "title": m.get("title", s["doc"]), "page": s["page"], "doc_type": s["doc_type"],
                        "section": s["section"], "text": s["text"][:6000], "score": s.get("score"),
                        "level": m.get("level"), "level_label": LEVELS.get(m.get("level"), ""), "departments": m.get("departments", [])})
    out = {"question": body.question, "status": r["status"], "answer": r["answer"], "answer_raw": r["answer_raw"],
           "sources": sources, "timings": r["timings_s"], "regenerations": r["regenerations"],
           "claims": (r["attempts"][-1].get("verdict") or {}).get("claims", []) if r["attempts"] else []}
    with db.conn() as c:
        c.execute("INSERT INTO queries (ts,username,question,status,answer,citations,retrieved,latency) VALUES (?,?,?,?,?,?,?,?)",
                  (time.time(), user["username"], body.question, r["status"], r["answer"], json.dumps(r["citations"]),
                   json.dumps([x["chunk_id"] for x in r["retrieved"]]), r["timings_s"]["total"]))
    return out


@app.get("/api/history")
def history(user: dict = Depends(current_user)):
    with db.conn() as c:
        rows = c.execute("SELECT ts,question,status,latency FROM queries WHERE username=? ORDER BY id DESC LIMIT 30", (user["username"],)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/suggestions")
def suggestions(user: dict = Depends(current_user)):
    common = ["How much is the annual wellbeing allowance?", "What is the hotel cap per night outside capital cities?",
              "Who is the Head of Engineering?", "Which training covers GDPR and how long is it?"]
    by_dept = {
        "Finance": ["What is the single approval limit for a department head?", "What was net income in Q3 FY2025?"],
        "Sales": ["What is the list price of the HX-320?", "Who is the account manager for Bilbao Packaging S.L.?"],
        "Engineering": ["What was the noise result in the HX-450 type test?", "When is the CU-5 controller planned for release?"],
        "Operations": ["How many lost-time incidents occurred at Porto Foundry?", "What is the reorder point for SKU-40012?"],
        "Human Resources": ["What is the midpoint salary for grade P2?", "How many open positions are in Engineering?"],
        "IT": ["What caused the VPN gateway outage?", "When is the laptop of asset IT-100005 due for refresh?"],
        "Legal & Compliance": ["When must personal data breaches be reported to the DPO?", "Which contracts with Bluecrest Seals are active?"],
        "Procurement": ["What is the lead time for Polaris Polymers?", "What is the value of purchase order PO-450010?"],
        "Quality": ["What is the calibration tolerance for torque wrenches?", "Within how many days must an NCR be closed?"],
        "Marketing": ["Which campaign had the highest ROI?", "What is the positioning of Wilmar Fluid?"],
    }
    execs = ["What did the board approve in Q3 2025?", "What is the indicative enterprise value of Project Nordlys?",
             "What are the revenue targets in the 2026-2028 strategic plan?", "What bonus was paid to the CFO in 2025?"]
    mgmt = ["What was the voluntary attrition rate in 2025?", "What is the FY2026 IT & Software budget for Engineering?"]
    s = by_dept.get(user["department"], [])
    if access.max_level(user) >= 4:
        s = execs + s
    elif access.max_level(user) >= 3:
        s = mgmt + s
    return (s + common)[:8]


# --------------------------------------------------------------------------- documents
@app.get("/api/documents")
def documents(user: dict = Depends(current_user)):
    docs = visible_docs(user)
    for d in docs:
        d["level_label"] = LEVELS[d["level"]]
        d["type"] = Path(d["doc"]).suffix[1:].upper()
        d["can_delete"] = access.can_delete(user, d)
    return docs


@app.get("/api/documents/{name}/download")
def download(name: str, user: dict = Depends(current_user)):
    d = get_doc(user, name)
    db.log_activity(user["username"], "download", name)
    return FileResponse(indexer.path_for(d), filename=d["doc"])


@app.get("/api/documents/{name}/page/{page}.png")
def page_png(name: str, page: int, user: dict = Depends(current_user)):
    d = get_doc(user, name)
    path = indexer.path_for(d)
    if path.suffix.lower() != ".pdf":
        raise HTTPException(404)
    import pymupdf
    pdf = pymupdf.open(path)
    if not 1 <= page <= len(pdf):
        raise HTTPException(404)
    return Response(pdf[page - 1].get_pixmap(dpi=110).tobytes("png"), media_type="image/png")


@app.get("/api/documents/{name}/preview")
def preview(name: str, user: dict = Depends(current_user)):
    d = get_doc(user, name)
    path = indexer.path_for(d)
    suf = path.suffix.lower()
    if suf == ".csv":
        lines = path.read_text(errors="replace").splitlines()
        return {"kind": "table", "rows": [l.split(",") for l in lines[:26]], "total_rows": len(lines) - 1}
    if suf == ".md":
        return {"kind": "text", "text": path.read_text(errors="replace")[:8000]}
    chunks = parsing.PARSERS[suf](path)
    seen, parts = set(), []
    for c in chunks:
        if c.parent_id not in seen:
            seen.add(c.parent_id)
            parts.append(c.parent_text)
    return {"kind": "text", "text": "\n\n".join(parts)[:8000], "pages": len(seen)}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), title: str = Form(..., max_length=160), level: int = Form(...),
                 departments: str = Form(...), category: str = Form("Uploaded", max_length=60),
                 description: str = Form("", max_length=400), user: dict = Depends(current_user)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in indexer.SUPPORTED:
        raise HTTPException(400, f"unsupported file type; allowed: {', '.join(sorted(indexer.SUPPORTED))}")
    if level not in access.allowed_upload_levels(user):
        raise HTTPException(403, "you cannot upload at this classification level")
    depts = [d for d in json.loads(departments) if d in DEPARTMENTS] or [user["department"]]
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file larger than 25 MB")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename).stem)[:60] or "document"
    name = f"{stem}_{int(time.time())}{suffix}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_bytes(data)
    doc = {"doc": name, "title": title.strip(), "departments": depts, "level": level, "owner": user["full_name"],
           "created": date.today().isoformat(), "description": description.strip(), "category": category.strip() or "Uploaded",
           "source": "upload", "uploaded_by": user["username"]}
    with db.conn() as c:
        db.upsert_document(c, doc)
    try:
        with model_lock:
            n = indexer.index_document(state["qc"], doc)
    except Exception as e:  # unreadable file: roll back
        (UPLOAD_DIR / name).unlink(missing_ok=True)
        with db.conn() as c:
            c.execute("DELETE FROM documents WHERE doc=?", (name,))
        raise HTTPException(400, f"could not read the document: {e}")
    db.log_activity(user["username"], "upload", f"{name} ({LEVELS[level]}, {', '.join(depts)}, {n} chunks)")
    return {**doc, "chunks": n, "level_label": LEVELS[level]}


@app.delete("/api/documents/{name}")
def delete_doc(name: str, user: dict = Depends(current_user)):
    d = get_doc(user, name)
    if not access.can_delete(user, d):
        raise HTTPException(403, "you cannot delete this document")
    with model_lock:
        indexer.delete_document(state["qc"], name)
    with db.conn() as c:
        c.execute("DELETE FROM documents WHERE doc=?", (name,))
    if d["source"] == "upload":
        (UPLOAD_DIR / name).unlink(missing_ok=True)
    db.log_activity(user["username"], "delete", name)
    return {"ok": True}


# --------------------------------------------------------------------------- dashboards, charts & reports
class ChartReq(BaseModel):
    spec: dict


def _checked(user: dict, spec: dict) -> dict:
    try:
        sp = analytics.validate(spec)
    except analytics.SpecError as e:
        raise HTTPException(400, str(e))
    if not analytics.allowed(user, sp["dataset"]):
        raise HTTPException(404, "dataset not found")
    return sp


def _file(data: bytes, name: str, kind: str) -> Response:
    media = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[kind]
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/dashboard/tabs")
def dashboard_tabs(user: dict = Depends(current_user)):
    return {"tabs": ["My charts"] + analytics.dashboard_tabs(user), "kpis": analytics.kpis_for(user)}


@app.get("/api/dashboard")
def dashboard(tab: str, user: dict = Depends(current_user)):
    if tab == "My charts":
        with db.conn() as c:
            rows = c.execute("SELECT id, spec FROM user_widgets WHERE username=? ORDER BY id", (user["username"],)).fetchall()
        out = []
        for r in rows:
            spec = json.loads(r["spec"])
            if analytics.allowed(user, spec["dataset"]):
                out.append({**analytics.run(spec), "widget_id": r["id"]})
        return out
    return analytics.dashboard(user, tab)


@app.get("/api/catalog")
def catalog(user: dict = Depends(current_user)):
    return analytics.catalog_for(user)


@app.post("/api/chart")
def chart(body: ChartReq, user: dict = Depends(current_user)):
    _checked(user, body.spec)
    return analytics.run(body.spec)


@app.post("/api/widgets")
def save_widget(body: ChartReq, user: dict = Depends(current_user)):
    sp = _checked(user, body.spec)
    with db.conn() as c:
        if c.execute("SELECT COUNT(*) FROM user_widgets WHERE username=?", (user["username"],)).fetchone()[0] >= 24:
            raise HTTPException(400, "you can pin up to 24 charts")
        c.execute("INSERT INTO user_widgets (username, spec, created) VALUES (?,?,?)", (user["username"], json.dumps(sp), time.time()))
    db.log_activity(user["username"], "pin_chart", sp["title"] or analytics.default_title(sp))
    return {"ok": True}


@app.delete("/api/widgets/{wid}")
def delete_widget(wid: int, user: dict = Depends(current_user)):
    with db.conn() as c:
        c.execute("DELETE FROM user_widgets WHERE id=? AND username=?", (wid, user["username"]))
    return {"ok": True}


@app.post("/api/export/chart.{kind}")
def export_chart(kind: str, body: ChartReq, user: dict = Depends(current_user)):
    sp = _checked(user, body.spec)
    if kind == "pptx":
        data, name = reports.chart_pptx(user, sp)
    elif kind == "xlsx":
        data, name = reports.xlsx(user, [sp], re.sub(r"[^A-Za-z0-9]+", "_", sp["title"] or analytics.default_title(sp))[:50])
    else:
        raise HTTPException(404)
    db.log_activity(user["username"], f"export_chart_{kind}", sp["title"] or analytics.default_title(sp))
    return _file(data, name, kind)


@app.get("/api/reports")
def report_list(user: dict = Depends(current_user)):
    return reports.available(user)


@app.get("/api/reports/{key}.{kind}")
def report_file(key: str, kind: str, user: dict = Depends(current_user)):
    if key not in {r["id"] for r in reports.available(user)}:
        raise HTTPException(404, "report not available")
    if kind == "pptx":
        data, name = reports.build_pptx(user, key)
    elif kind == "xlsx":
        data, name = reports.xlsx(user, reports.widgets_for(user, key), reports.TEMPLATES[key]["title"].replace(" ", "_").replace("&", "and"))
    else:
        raise HTTPException(404)
    db.log_activity(user["username"], f"report_{kind}", reports.TEMPLATES[key]["title"])
    return _file(data, name, kind)


# --------------------------------------------------------------------------- insights
@app.get("/api/stats")
def stats(user: dict = Depends(current_user)):
    docs = visible_docs(user)
    by_dept: dict[str, int] = {}
    for d in docs:
        for dep in d["departments"]:
            by_dept[dep] = by_dept.get(dep, 0) + 1
    with db.conn() as c:
        total_docs = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        mine = c.execute("SELECT COUNT(*), AVG(latency) FROM queries WHERE username=?", (user["username"],)).fetchone()
        org = c.execute("SELECT COUNT(*), SUM(status='verified'), AVG(latency) FROM queries").fetchone()
        users = c.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
        recent = [dict(r) for r in c.execute("SELECT title, created, owner, level, departments FROM documents ORDER BY rowid DESC LIMIT 200")]
    recent = [r for r in recent if access.can_see(user, {**r, "departments": json.loads(r["departments"])})][:6]
    out = {"visible_documents": len(docs), "total_documents": total_docs, "visible_chunks": sum(d["chunks"] for d in docs),
           "by_department": dict(sorted(by_dept.items(), key=lambda x: -x[1])),
           "by_level": {LEVELS[l]: sum(d["level"] == l for d in docs) for l in LEVELS},
           "my_questions": mine[0], "my_avg_latency": round(mine[1] or 0, 2), "recent": recent}
    if access.can_manage_users(user) or access.max_level(user) >= 3:
        out.update(org_questions=org[0], org_verified_rate=round((org[1] or 0) / org[0], 3) if org[0] else None,
                   org_avg_latency=round(org[2] or 0, 2), active_users=users)
    return out


# --------------------------------------------------------------------------- administration
class NewUser(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9._-]{3,32}$")
    full_name: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=80)
    department: str
    role: str = Field(pattern="^(employee|manager|executive|admin)$")
    password: str = Field(min_length=8, max_length=128)


class UserPatch(BaseModel):
    active: bool | None = None
    role: str | None = Field(None, pattern="^(employee|manager|executive|admin)$")
    password: str | None = Field(None, min_length=8, max_length=128)


@app.get("/api/admin/users")
def list_users(admin: dict = Depends(require_admin)):
    with db.conn() as c:
        rows = c.execute("SELECT username,full_name,title,department,role,active,last_login FROM users ORDER BY CASE role WHEN 'executive' THEN 0 WHEN 'manager' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, department, full_name").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/users")
def create_user(body: NewUser, admin: dict = Depends(require_admin)):
    if body.department not in DEPARTMENTS:
        raise HTTPException(400, "unknown department")
    if body.role == "executive" and admin["role"] != "executive":
        raise HTTPException(403, "only executives can create executive accounts")
    salt, h = db.hash_password(body.password)
    with db.conn() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?", (body.username,)).fetchone():
            raise HTTPException(409, "username already exists")
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,1,?,NULL)",
                  (body.username, body.full_name, body.title, body.department, body.role, salt, h, time.time()))
    db.log_activity(admin["username"], "create_user", f"{body.username} ({body.role}, {body.department})")
    return {"ok": True}


@app.patch("/api/admin/users/{username}")
def update_user(username: str, body: UserPatch, admin: dict = Depends(require_admin)):
    with db.conn() as c:
        target = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not target:
            raise HTTPException(404)
        if (target["role"] == "executive" or body.role == "executive") and admin["role"] != "executive":
            raise HTTPException(403, "only executives can modify executive accounts")
        if username == admin["username"] and body.active is False:
            raise HTTPException(400, "you cannot deactivate your own account")
        if body.active is not None:
            c.execute("UPDATE users SET active=? WHERE username=?", (int(body.active), username))
            if not body.active:
                c.execute("DELETE FROM sessions WHERE username=?", (username,))
        if body.role:
            c.execute("UPDATE users SET role=? WHERE username=?", (body.role, username))
        if body.password:
            salt, h = db.hash_password(body.password)
            c.execute("UPDATE users SET pw_salt=?, pw_hash=? WHERE username=?", (salt, h, username))
    db.log_activity(admin["username"], "update_user", f"{username}: " + ", ".join(k for k, v in body.model_dump().items() if v is not None))
    return {"ok": True}


@app.get("/api/admin/activity")
def activity(admin: dict = Depends(require_admin)):
    with db.conn() as c:
        acts = [dict(r) for r in c.execute("SELECT ts,username,action,detail FROM activity ORDER BY id DESC LIMIT 150")]
        qs = [dict(r) for r in c.execute("SELECT ts,username,question,status,latency FROM queries ORDER BY id DESC LIMIT 150")]
    return {"activity": acts, "queries": qs}


@app.get("/api/meta")
def meta(user: dict = Depends(current_user)):
    return {"departments": DEPARTMENTS, "levels": LEVELS}


# --------------------------------------------------------------------------- static site
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
