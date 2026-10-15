"""End-to-end security checks against a running portal (default http://127.0.0.1:8100).

Verifies authentication, rate limiting, CSRF header, role-based document visibility, that restricted
documents never surface through the assistant, upload classification limits and admin rights.
Uses the demo accounts in data/portal/demo_accounts.csv.
"""
import csv
import sys
from pathlib import Path

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8100"
ACC = {r["username"]: r for r in csv.DictReader(open(Path(__file__).resolve().parent.parent / "data/portal/demo_accounts.csv"))}
H = {"X-HIS-Request": "1"}
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def session(user):
    s = requests.Session()
    r = s.post(f"{BASE}/api/login", json={"username": user, "password": ACC[user]["password"]}, headers=H)
    assert r.ok, r.text
    return s


anon = requests.Session()
check("unauthenticated /api/documents is rejected", anon.get(f"{BASE}/api/documents").status_code == 401)
check("wrong password is rejected", anon.post(f"{BASE}/api/login", json={"username": "ceo", "password": "wrong"}, headers=H).status_code == 401)
check("POST without CSRF header is rejected", anon.post(f"{BASE}/api/login", json={"username": "ceo", "password": ACC["ceo"]["password"]}).status_code == 403)
check("foreign Host header is rejected", requests.get(f"{BASE}/", headers={"Host": "evil.example"}).status_code == 400)

ceo, emp, mgr, adm = session("ceo"), session("sales"), session("head.finance"), session("admin")
docs = {u: {d["doc"]: d for d in s.get(f"{BASE}/api/documents").json()} for u, s in (("ceo", ceo), ("sales", emp), ("head.finance", mgr), ("admin", adm))}
check("CEO sees every document", len(docs["ceo"]) >= 65, f"{len(docs['ceo'])}")
check("employee sees no Management/Executive docs", all(d["level"] <= 2 for d in docs["sales"].values()))
check("employee sees only own-department level-2 docs",
      all(d["level"] == 1 or "Sales" in d["departments"] for d in docs["sales"].values()))
check("manager sees no Executive docs", all(d["level"] <= 3 for d in docs["head.finance"].values()))
check("employee cannot download board minutes (404, existence hidden)",
      emp.get(f"{BASE}/api/documents/Board_Minutes_2025_Q3.pdf/download").status_code == 404)
check("CEO can download board minutes", ceo.get(f"{BASE}/api/documents/Board_Minutes_2025_Q3.pdf/download").status_code == 200)

q = "What is the indicative enterprise value of Project Nordlys?"
a_ceo, a_emp = ceo.post(f"{BASE}/api/ask", json={"question": q}, headers=H).json(), emp.post(f"{BASE}/api/ask", json={"question": q}, headers=H).json()
check("CEO gets a verified answer about Project Nordlys", a_ceo["status"] == "verified", a_ceo["answer"][:100])
check("employee gets no Project Nordlys answer", a_emp["status"] != "verified" and "Nordlys" not in "".join(s["doc"] for s in a_emp["sources"]), a_emp["answer"][:100])
q2 = "What bonus was paid to the CFO in 2025?"
a_mgr = mgr.post(f"{BASE}/api/ask", json={"question": q2}, headers=H).json()
check("manager cannot retrieve executive compensation", all(s["level"] <= 3 for s in a_mgr["sources"]), a_mgr["answer"][:100])
a_emp2 = emp.post(f"{BASE}/api/ask", json={"question": "How much is the annual wellbeing allowance?"}, headers=H).json()
check("employee gets an all-staff answer", a_emp2["status"] == "verified" and "400" in a_emp2["answer"], a_emp2["answer"][:100])

r = emp.post(f"{BASE}/api/upload", headers=H, files={"file": ("note.md", b"# Test\n\nSecret plan.")},
             data={"title": "Test", "level": "4", "departments": '["Sales"]'})
check("employee cannot upload at Executive level", r.status_code == 403)
check("employee cannot list users", emp.get(f"{BASE}/api/admin/users").status_code == 403)
check("admin can list users", adm.get(f"{BASE}/api/admin/users").status_code == 200)
r = adm.post(f"{BASE}/api/admin/users", headers=H, json={"username": "x.exec", "full_name": "Test Exec", "title": "Test Title", "department": "IT", "role": "executive", "password": "Password123"})
check("admin cannot create executive accounts", r.status_code == 403)
# analytics / reports access control
check("employee cannot chart executive compensation", emp.post(f"{BASE}/api/chart", json={"spec": {"dataset": "exec_comp", "x": "name", "metric": "bonus_paid_eur"}}, headers=H).status_code == 404)
check("employee cannot download the executive report", emp.get(f"{BASE}/api/reports/executive_summary.pptx").status_code == 404)
check("CEO can download the executive report", ceo.get(f"{BASE}/api/reports/executive_summary.pptx").status_code == 200)
check("chart spec injection is rejected", ceo.post(f"{BASE}/api/chart", json={"spec": {"dataset": "pipeline", "x": "__import__('os')", "metric": "value_eur"}}, headers=H).status_code == 400)
r = emp.post(f"{BASE}/api/ask", json={"question": "Plot executive bonus by name"}, headers=H).json()
check("employee asking for an executive chart gets no chart", r.get("kind") != "chart", str(r)[:120])
check("employee dashboard has no executive tab", "Executive Office" not in emp.get(f"{BASE}/api/dashboard/tabs").json()["tabs"])
for _ in range(6):
    anon.post(f"{BASE}/api/login", json={"username": "cto", "password": "nope"}, headers=H)
check("login rate limit after 5 failures", anon.post(f"{BASE}/api/login", json={"username": "cto", "password": "nope"}, headers=H).status_code == 429)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
