"""Record real outputs from the running portal (http://127.0.0.1:8100) for the portfolio's interactive replay.

Signs in as three roles, asks curated questions (answers, charts, refusals), and saves every response the
frontend needs - plus cited PDF page images, document previews, original files and generated PowerPoint/Excel
reports - into kiruthikportfolio.com/demo/data/.

Usage:  python scripts/record_portfolio_demo.py
"""
import csv
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8100"
H = {"X-HIS-Request": "1"}
OUT = ROOT / "kiruthikportfolio.com" / "demo" / "data"
ROLES = ["ceo", "head.finance", "sales"]
SHARED_QUESTIONS = [            # same question, different clearance -> different outcome
    "What is the indicative enterprise value of Project Nordlys?",
    "What bonus was paid to the CFO in 2025?",
    "How much is the annual wellbeing allowance?",
    "What is the hotel cap per night outside capital cities?",
    "What was net income in Q3 FY2025?",
    "Who is the account manager for Bilbao Packaging S.L.?",
    "What is the maximum head of the HX-320 pump?",
    "What caused the VPN gateway outage?",
    "What is the CEO's home address?",
    "Show me the top 10 customers by annual revenue as a chart",
    "Show pipeline value by stage as a chart",
    "Chart revenue vs budget by quarter",
    "Show a breakdown of headcount by site",
    "Chart of order bookings per month by region",
    "Visualize purchase order value by category",
]


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def main():
    acc = {r["username"]: r for r in csv.DictReader(open(ROOT / "data/portal/demo_accounts.csv"))}
    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("pages", "files", "reports", "previews"):
        (OUT / d).mkdir(parents=True)
    accounts = []
    previews_done = set()
    for u in ROLES:
        s = requests.Session()
        me = s.post(f"{BASE}/api/login", json={"username": u, "password": acc[u]["password"]}, headers=H).json()
        accounts.append({k: acc[u][k] for k in ("username", "password", "full_name", "title", "department", "role")})
        g = lambda p: s.get(f"{BASE}{p}").json()                                                    # noqa: E731
        rec = {"me": me, "suggestions": g("/api/suggestions"), "documents": g("/api/documents"), "stats": g("/api/stats"),
               "meta": g("/api/meta"), "reports": g("/api/reports"), "dashboard_tabs": g("/api/dashboard/tabs"), "dashboards": {}, "answers": []}
        for tab in rec["dashboard_tabs"]["tabs"]:
            rec["dashboards"][tab] = g(f"/api/dashboard?tab={quote(tab)}")
        if me["can_manage_users"]:
            rec["users"] = g("/api/admin/users")
            act = g("/api/admin/activity")
            rec["activity"] = {"activity": act["activity"][:60], "queries": act["queries"][:60]}
        for q in dict.fromkeys(rec["suggestions"] + SHARED_QUESTIONS):
            r = s.post(f"{BASE}/api/ask", json={"question": q}, headers=H).json()
            rec["answers"].append(r)
            for src in r.get("sources", []):
                if src["doc_type"] == "pdf":
                    f = OUT / "pages" / f"{slug(src['doc'])}__{src['page']}.png"
                    if not f.exists():
                        f.write_bytes(s.get(f"{BASE}/api/documents/{quote(src['doc'])}/page/{src['page']}.png").content)
            print(f"  {u:13s} {r.get('status', '?'):18s} {q[:70]}")
        for d in rec["documents"]:
            if d["doc"] not in previews_done:
                (OUT / "previews" / f"{slug(d['doc'])}.json").write_text(json.dumps(g(f"/api/documents/{quote(d['doc'])}/preview")))
                previews_done.add(d["doc"])
        for rep in rec["reports"][:3]:
            for kind in ("pptx", "xlsx"):
                f = OUT / "reports" / f"{u}__{rep['id']}.{kind}"
                f.write_bytes(s.get(f"{BASE}/api/reports/{rep['id']}.{kind}").content)
        (OUT / f"{u}.json").write_text(json.dumps(rec))
        print(f"{u}: {len(rec['answers'])} answers, {len(rec['documents'])} documents, {len(rec['dashboards'])} dashboards")
    for f in (ROOT / "data/portal/documents").iterdir():          # original (synthetic) documents for "Download original"
        shutil.copy(f, OUT / "files" / f.name)
    (OUT / "accounts.json").write_text(json.dumps(accounts, indent=1))
    print("recorded ->", OUT, sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) // 1024, "KB")


if __name__ == "__main__":
    sys.exit(main())
