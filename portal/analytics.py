"""Grounded analytics: dashboards, charts on request and report data.

Numbers are never produced by the language model. A chart is a *spec* (dataset, dimension, measure, aggregation,
filters, chart type) that is validated against a whitelist catalogue and executed with pandas on the company's
structured datasets. The LLM's only job (``plan``) is to translate a question into such a spec. Every dataset is
backed by a document in the portal, so the same access control applies: a user can only chart data from documents
they are cleared to read.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import access, db
from .company_data import DOC_DIR

# ---------------------------------------------------------------------------- catalogue
CATALOG: dict[str, dict] = {
    "financial_kpis": {"doc": "Financial_KPIs_FY2025.csv", "title": "Quarterly financial KPIs FY2025", "unit": "EUR m",
                       "dims": ["quarter"], "measures": ["revenue", "budget_revenue", "ebitda", "ebitda_margin_pct", "net_income", "order_intake",
                                                          "free_cash_flow", "gross_margin_pct", "cash", "book_to_bill", "ltifr", "on_time_delivery_pct"]},
    "bookings": {"doc": "Order_Bookings_Monthly.csv", "title": "Order bookings by month and region", "unit": "EUR",
                 "dims": ["month", "region", "year"], "measures": ["orders_eur", "quotes_issued", "win_rate_pct"]},
    "pipeline": {"doc": "Sales_Pipeline_2026.csv", "title": "Sales pipeline 2026", "unit": "EUR",
                 "dims": ["stage", "product", "owner", "country", "account", "close_quarter"], "measures": ["value_eur", "weighted_value_eur", "probability_pct"]},
    "customers": {"doc": "Customer_Accounts.csv", "title": "Customer accounts", "unit": "EUR",
                  "dims": ["country", "industry", "segment", "account_manager", "city", "account_name"], "measures": ["annual_revenue_eur", "credit_limit_eur", "payment_terms_days"]},
    "staff": {"doc": "Staff_Directory.csv", "title": "Salaried staff", "unit": "people", "dims": ["department", "site", "job_title", "start_year", "manager"], "measures": []},
    "open_positions": {"doc": "Open_Positions.csv", "title": "Open positions", "unit": "positions", "dims": ["department", "site", "status", "contract", "job_title"], "measures": []},
    "budget": {"doc": "Budget_FY2026_by_Department.csv", "title": "Budget FY2026 by department", "unit": "EUR",
               "dims": ["department", "category", "budget_owner"], "measures": ["budget_fy2026_eur", "actual_fy2025_eur"]},
    "payables": {"doc": "Accounts_Payable_Ledger_2026.csv", "title": "Accounts payable 2026", "unit": "EUR",
                 "dims": ["supplier", "status", "invoice_month"], "measures": ["amount_eur", "days_overdue"]},
    "expenses": {"doc": "Expense_Claims_2026.csv", "title": "Expense claims 2026", "unit": "EUR",
                 "dims": ["department", "category", "status", "employee", "month"], "measures": ["amount_eur"]},
    "purchase_orders": {"doc": "Purchase_Orders_2026.csv", "title": "Purchase orders 2026", "unit": "EUR",
                        "dims": ["supplier", "category", "status", "delivery_site", "buyer", "month"], "measures": ["value_eur"]},
    "inventory": {"doc": "Inventory_Levels.csv", "title": "Inventory levels", "unit": "EUR",
                  "dims": ["site", "preferred_supplier", "below_reorder"], "measures": ["stock_value_eur", "on_hand_qty", "reorder_point", "lead_time_days"]},
    "production": {"doc": "Production_Plan_2026_Q1.csv", "title": "Production plan 2026 Q1", "unit": "units",
                   "dims": ["site", "product", "week", "status", "customer"], "measures": ["quantity"]},
    "safety": {"doc": "Safety_Incident_Log_2025.csv", "title": "Safety incidents 2025", "unit": "incidents",
               "dims": ["site", "type", "severity", "status", "month"], "measures": ["days_lost"]},
    "it_assets": {"doc": "IT_Asset_Inventory.csv", "title": "IT assets", "unit": "assets",
                  "dims": ["type", "model", "department", "status", "refresh_year"], "measures": []},
    "contracts": {"doc": "Contract_Register.csv", "title": "Contracts", "unit": "EUR", "dims": ["type", "auto_renewal", "end_year", "contract_owner"], "measures": ["value_eur"]},
    "campaigns": {"doc": "Marketing_Campaigns_2025.csv", "title": "Marketing campaigns 2025", "unit": "EUR",
                  "dims": ["channel", "product_focus", "region"], "measures": ["spend_eur", "leads", "opportunities"]},
    "change_orders": {"doc": "Engineering_Change_Orders.csv", "title": "Engineering change orders", "unit": "ECOs",
                      "dims": ["product", "status", "impact", "requested_by"], "measures": []},
    "suppliers": {"doc": "supplier_register.csv", "title": "Supplier register", "unit": "suppliers",
                  "dims": ["country", "category", "supplier_name"], "measures": ["lead_time_days", "quality_score"]},
    "performance": {"doc": "Performance_Calibration_2025.csv", "title": "Performance calibration 2025", "unit": "employees",
                    "dims": ["department", "rating", "potential", "flight_risk"], "measures": []},
    "exec_comp": {"doc": "Executive_Compensation_2025.csv", "title": "Executive compensation 2025", "unit": "EUR",
                  "dims": ["name", "title"], "measures": ["base_salary_eur", "bonus_paid_eur", "lti_grant_eur"]},
    "litigation": {"doc": "Litigation_Register.csv", "title": "Litigation register", "unit": "EUR",
                   "dims": ["matter", "jurisdiction", "status", "risk"], "measures": ["exposure_eur"]},
}
AGGS = {"sum", "mean", "count", "max", "min"}
KEYWORDS = {   # a chart is only drawn if the question mentions its subject
    "financial_kpis": ["revenue", "ebitda", "margin", "net income", "profit", "cash", "financial", "quarter", "order intake", "book-to-bill", "ltifr", "on-time"],
    "bookings": ["booking", "order intake", "orders by", "order value", "win rate", "quotes"],
    "pipeline": ["pipeline", "opportunit", "deal", "forecast", "weighted", "stage"],
    "customers": ["customer", "account", "client", "credit limit", "payment terms"],
    "staff": ["headcount", "staff", "employee", "people", "hire", "workforce", "personnel"],
    "open_positions": ["open position", "vacanc", "recruit", "hiring", "requisition", "job opening"],
    "budget": ["budget", "spend plan", "cost center", "cost centre"],
    "payables": ["payable", "invoice", "overdue", "ap "],
    "expenses": ["expense", "claim", "travel cost"],
    "purchase_orders": ["purchase order", "po ", "purchasing", "procurement spend", "buyer", "supplier spend", " po"],
    "inventory": ["inventory", "stock", "sku", "reorder"],
    "production": ["production", "manufactur", "output", "units planned"],
    "safety": ["safety", "incident", "injur", "near miss", "lost time", "accident"],
    "it_assets": ["it asset", "laptop", "device", "hardware", "refresh", "asset"],
    "contracts": ["contract"],
    "campaigns": ["campaign", "marketing", "lead", "channel", "roi"],
    "change_orders": ["change order", "eco", "engineering change"],
    "suppliers": ["supplier", "vendor", "lead time", "quality score"],
    "performance": ["performance", "rating", "calibration", "potential", "flight risk"],
    "exec_comp": ["compensation", "bonus", "salary", "salaries", "pay ", "lti", "executive pay"],
    "litigation": ["litigation", "lawsuit", "legal exposure", "dispute", "court"],
}
TIME_DIMS = {"month", "quarter", "week", "year", "start_year", "close_quarter", "invoice_month", "refresh_year", "end_year"}
CHARTS = {"bar", "hbar", "line", "pie", "doughnut", "table", "kpi"}


@lru_cache(maxsize=64)
def _load(doc: str, mtime: float) -> pd.DataFrame:
    df = pd.read_csv(DOC_DIR / doc)
    # derived fields used by the catalogue
    if doc.startswith("Sales_Pipeline"):
        df["weighted_value_eur"] = df["value_eur"] * df["probability_pct"] / 100
        d = pd.to_datetime(df["expected_close"])
        df["close_quarter"] = d.dt.year.astype(str) + "-Q" + d.dt.quarter.astype(str)
    if doc.startswith("Order_Bookings"):
        df["year"] = df["month"].str[:4]
    if doc.startswith("Staff_Directory"):
        df["start_year"] = df["start_date"].str[:4]
    if doc.startswith("Inventory"):
        df["stock_value_eur"] = (df["on_hand_qty"] * df["unit_cost_eur"]).round(2)
        df["below_reorder"] = (df["on_hand_qty"] < df["reorder_point"]).map({True: "Below reorder point", False: "OK"})
    if doc.startswith("Accounts_Payable"):
        df["invoice_month"] = df["invoice_date"].str[:7]
    if doc.startswith("Expense_Claims"):
        df["month"] = df["date"].str[:7]
    if doc.startswith("Purchase_Orders"):
        df["month"] = df["order_date"].str[:7]
    if doc.startswith("Safety_Incident"):
        df["month"] = df["date"].str[:7]
    if doc.startswith("IT_Asset"):
        df["refresh_year"] = df["refresh_due"].str[:4]
    if doc.startswith("Contract_Register"):
        df["end_year"] = df["end_date"].str[:4]
    return df


def frame(name: str) -> pd.DataFrame:
    path = DOC_DIR / CATALOG[name]["doc"]
    return _load(CATALOG[name]["doc"], path.stat().st_mtime)


def doc_meta(name: str) -> dict | None:
    with db.conn() as c:
        r = c.execute("SELECT * FROM documents WHERE doc=?", (CATALOG[name]["doc"],)).fetchone()
    return db.doc_row(r) if r else None


def allowed(user: dict, name: str) -> bool:
    m = doc_meta(name)
    return bool(m) and access.can_see(user, m)


def catalog_for(user: dict) -> dict:
    return {k: {**v, "level": doc_meta(k)["level"]} for k, v in CATALOG.items() if (DOC_DIR / v["doc"]).exists() and allowed(user, k)}


# ---------------------------------------------------------------------------- spec execution
class SpecError(ValueError):
    pass


def validate(spec: dict) -> dict:
    name = spec.get("dataset")
    if name not in CATALOG:
        raise SpecError(f"unknown dataset '{name}'")
    cat = CATALOG[name]
    metrics = spec.get("metrics") or [spec.get("metric") or "count"]
    metrics = [m for m in metrics if m == "count" or m in cat["measures"]] or ["count"]
    agg = spec.get("agg", "sum" if metrics != ["count"] else "count")
    if agg not in AGGS:
        agg = "sum"
    x = spec.get("x")
    if x is not None and x not in cat["dims"]:
        raise SpecError(f"'{x}' is not a dimension of {name}; use one of {cat['dims']}")
    series = spec.get("series")
    if series is not None and (series not in cat["dims"] or series == x):
        series = None
    chart = spec.get("chart", "bar")
    if chart not in CHARTS:
        chart = "bar"
    if chart == "line" and x not in TIME_DIMS:            # lines only make sense over time
        chart = "bar"
    if x is None and chart != "kpi":
        chart = "kpi"
    filters = []
    for f in spec.get("filters") or []:
        col, op, val = f.get("col"), f.get("op", "eq"), f.get("value")
        if col in cat["dims"] + cat["measures"] and op in ("eq", "ne", "in", "gt", "lt", "contains"):
            filters.append({"col": col, "op": op, "value": val})
    top = spec.get("top")
    top = max(1, min(int(top), 50)) if isinstance(top, (int, float)) or (isinstance(top, str) and top.isdigit()) else None
    sort = spec.get("sort", "desc" if x not in ("month", "quarter", "week", "year", "start_year", "close_quarter", "invoice_month",
                                                "refresh_year", "end_year") else "x")
    return {"dataset": name, "x": x, "series": series, "metrics": metrics, "agg": agg, "chart": chart, "filters": filters,
            "top": top, "sort": sort if sort in ("desc", "asc", "x") else "desc", "title": str(spec.get("title") or "")[:120]}


def _apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    for f in filters:
        col, op, v = f["col"], f["op"], f["value"]
        s = df[col]
        if op == "eq":
            df = df[s.astype(str).str.lower() == str(v).lower()]
        elif op == "ne":
            df = df[s.astype(str).str.lower() != str(v).lower()]
        elif op == "in":
            vals = {str(x).lower() for x in (v if isinstance(v, list) else [v])}
            df = df[s.astype(str).str.lower().isin(vals)]
        elif op == "contains":
            df = df[s.astype(str).str.contains(str(v), case=False, regex=False)]
        elif op in ("gt", "lt"):
            num = pd.to_numeric(s, errors="coerce")
            df = df[num > float(v)] if op == "gt" else df[num < float(v)]
    return df


def run(spec: dict) -> dict:
    """Execute a validated spec. Returns chart-ready data plus provenance."""
    sp = validate(spec)
    cat = CATALOG[sp["dataset"]]
    df = _apply_filters(frame(sp["dataset"]), sp["filters"])
    n_rows = len(df)

    def agg_series(g, m):
        if m == "count":
            return g.size()
        return getattr(g[m], sp["agg"])()

    if sp["x"] is None:      # KPI
        vals = [float(len(df)) if m == "count" else float(getattr(df[m], sp["agg"])()) if len(df) else 0.0 for m in sp["metrics"]]
        out = {"labels": [], "datasets": [{"label": _label(m, sp["agg"]), "data": [round(v, 2)]} for m, v in zip(sp["metrics"], vals)], "value": round(vals[0], 2)}
    elif sp["series"]:
        m = sp["metrics"][0]
        g = df.groupby([sp["x"], sp["series"]])
        tab = agg_series(g, m).unstack(fill_value=0)
        tab = _order(tab, sp, tab.sum(axis=1))
        out = {"labels": [str(i) for i in tab.index], "datasets": [{"label": str(c), "data": [round(float(v), 2) for v in tab[c]]} for c in tab.columns]}
    else:
        g = df.groupby(sp["x"])
        tab = pd.DataFrame({m: agg_series(g, m) for m in sp["metrics"]})
        tab = _order(tab, sp, tab[sp["metrics"][0]])
        out = {"labels": [str(i) for i in tab.index], "datasets": [{"label": _label(m, sp["agg"]), "data": [round(float(v), 2) for v in tab[m]]} for m in sp["metrics"]]}
    unit = "%" if sp["metrics"][0].endswith("_pct") else ("count" if sp["metrics"][0] == "count" else cat["unit"])
    if unit == "EUR" and sp["x"] is not None:      # show large money values in EUR millions
        peak = max((abs(v) for ds in out["datasets"] for v in ds["data"]), default=0)
        if peak >= 1e6:
            for ds in out["datasets"]:
                ds["data"] = [round(v / 1e6, 2) for v in ds["data"]]
            unit = "EUR m"
    title = sp["title"] or default_title(sp)
    if unit == "EUR m" and "EUR m" not in title:
        title += " (EUR m)"
    return {"spec": sp, **out, "unit": unit, "rows_used": n_rows, "source_doc": cat["doc"], "source_title": cat["title"], "title": title}


def _order(tab: pd.DataFrame, sp: dict, key: pd.Series) -> pd.DataFrame:
    if sp["sort"] == "x":
        tab = tab.sort_index()
    else:
        tab = tab.loc[key.sort_values(ascending=sp["sort"] == "asc").index]
    if sp["top"]:
        tab = tab.head(sp["top"])
    return tab


def _label(m: str, agg: str) -> str:
    if m == "count":
        return "Count"
    nice = m.replace("_eur", "").replace("_pct", " %").replace("_", " ").strip().capitalize()
    return nice if agg == "sum" else f"{nice} ({agg})"


def default_title(sp: dict) -> str:
    m = _label(sp["metrics"][0], sp["agg"]) if len(sp["metrics"]) == 1 else " vs ".join(_label(x, sp["agg"]) for x in sp["metrics"])
    t = f"{m} by {sp['x'].replace('_', ' ')}" if sp["x"] else m
    if sp["series"]:
        t += f" and {sp['series'].replace('_', ' ')}"
    if sp["top"]:
        t = f"Top {sp['top']}: " + t
    return t


def rows_for_export(spec: dict, limit: int = 5000) -> pd.DataFrame:
    sp = validate(spec)
    return _apply_filters(frame(sp["dataset"]), sp["filters"]).head(limit)


# ---------------------------------------------------------------------------- dashboards
W = lambda title, chart, **spec: {"title": title, "chart": chart, **spec}   # noqa: E731
WIDGETS = {
    "Executive Office": [
        W("Revenue vs budget by quarter (EUR m)", "bar", dataset="financial_kpis", x="quarter", metrics=["revenue", "budget_revenue"], sort="x"),
        W("Adjusted EBITDA margin by quarter (%)", "line", dataset="financial_kpis", x="quarter", metric="ebitda_margin_pct", sort="x"),
        W("Order bookings by month and region", "line", dataset="bookings", x="month", series="region", metric="orders_eur", sort="x"),
        W("Weighted pipeline by stage", "bar", dataset="pipeline", x="stage", metric="weighted_value_eur"),
        W("Litigation exposure by risk", "doughnut", dataset="litigation", x="risk", metric="exposure_eur"),
        W("Salaried headcount by department", "hbar", dataset="staff", x="department", metric="count"),
    ],
    "Finance": [
        W("FY2026 budget by department", "hbar", dataset="budget", x="department", metrics=["budget_fy2026_eur", "actual_fy2025_eur"]),
        W("Net income by quarter (EUR m)", "bar", dataset="financial_kpis", x="quarter", metric="net_income", sort="x"),
        W("Payables by status", "doughnut", dataset="payables", x="status", metric="amount_eur"),
        W("Expense claims by category", "bar", dataset="expenses", x="category", metric="amount_eur"),
        W("Expense claims per month", "line", dataset="expenses", x="month", metric="amount_eur", sort="x"),
    ],
    "Sales": [
        W("Pipeline value by stage", "bar", dataset="pipeline", x="stage", metric="value_eur"),
        W("Top 10 account managers by weighted pipeline", "hbar", dataset="pipeline", x="owner", metric="weighted_value_eur", top=10),
        W("Pipeline by product", "hbar", dataset="pipeline", x="product", metric="value_eur", top=10),
        W("Customer revenue by industry", "doughnut", dataset="customers", x="industry", metric="annual_revenue_eur"),
        W("Top 10 customers by annual revenue", "hbar", dataset="customers", x="account_name", metric="annual_revenue_eur", top=10),
        W("Order bookings by region and year", "bar", dataset="bookings", x="region", series="year", metric="orders_eur"),
    ],
    "Human Resources": [
        W("Headcount by department", "hbar", dataset="staff", x="department", metric="count"),
        W("Headcount by site", "doughnut", dataset="staff", x="site", metric="count"),
        W("Hires by start year", "line", dataset="staff", x="start_year", metric="count", sort="x"),
        W("Open positions by department", "bar", dataset="open_positions", x="department", metric="count"),
        W("Performance ratings 2025", "bar", dataset="performance", x="rating", metric="count", sort="x"),
    ],
    "Operations": [
        W("Stock value by site", "bar", dataset="inventory", x="site", metric="stock_value_eur"),
        W("SKUs below reorder point", "doughnut", dataset="inventory", x="below_reorder", metric="count"),
        W("Safety incidents by site and severity", "bar", dataset="safety", x="site", series="severity", metric="count"),
        W("Planned production by site (units)", "hbar", dataset="production", x="site", metric="quantity"),
    ],
    "Procurement": [
        W("Purchase order value by category", "bar", dataset="purchase_orders", x="category", metric="value_eur"),
        W("Top 10 suppliers by PO value", "hbar", dataset="purchase_orders", x="supplier", metric="value_eur", top=10),
        W("Average supplier quality score by country", "bar", dataset="suppliers", x="country", metric="quality_score", agg="mean"),
        W("Purchase orders per month", "line", dataset="purchase_orders", x="month", metric="value_eur", sort="x"),
    ],
    "IT": [
        W("IT assets by type and status", "bar", dataset="it_assets", x="type", series="status", metric="count"),
        W("Laptop and device refreshes due by year", "line", dataset="it_assets", x="refresh_year", metric="count", sort="x"),
    ],
    "Marketing": [
        W("Campaign spend by channel", "bar", dataset="campaigns", x="channel", metric="spend_eur"),
        W("Leads by channel", "doughnut", dataset="campaigns", x="channel", metric="leads"),
        W("Opportunities by product focus", "bar", dataset="campaigns", x="product_focus", metric="opportunities"),
    ],
    "Legal & Compliance": [
        W("Contract value by type", "bar", dataset="contracts", x="type", metric="value_eur"),
        W("Contracts ending per year", "line", dataset="contracts", x="end_year", metric="count", sort="x"),
    ],
    "Engineering": [
        W("Change orders by status", "doughnut", dataset="change_orders", x="status", metric="count"),
        W("Change orders by product", "hbar", dataset="change_orders", x="product", metric="count", top=12),
    ],
    "Quality": [
        W("Safety incidents by type", "hbar", dataset="safety", x="type", metric="count"),
        W("Change orders by impact", "doughnut", dataset="change_orders", x="impact", metric="count"),
    ],
}
KPIS = [  # (label, spec, format)
    ("FY2025 revenue", {"dataset": "financial_kpis", "metric": "revenue", "agg": "sum"}, "EUR {:,.1f}m"),
    ("Avg EBITDA margin", {"dataset": "financial_kpis", "metric": "ebitda_margin_pct", "agg": "mean"}, "{:.1f}%"),
    ("FY2025 order intake", {"dataset": "financial_kpis", "metric": "order_intake", "agg": "sum"}, "EUR {:,.1f}m"),
    ("Weighted pipeline", {"dataset": "pipeline", "metric": "weighted_value_eur", "agg": "sum"}, "EURm"),
    ("Customer accounts", {"dataset": "customers", "metric": "count"}, "{:,.0f}"),
    ("Salaried staff", {"dataset": "staff", "metric": "count"}, "{:,.0f}"),
    ("Open positions", {"dataset": "open_positions", "metric": "count"}, "{:,.0f}"),
    ("PO value 2026", {"dataset": "purchase_orders", "metric": "value_eur", "agg": "sum"}, "EURm"),
    ("Stock value", {"dataset": "inventory", "metric": "stock_value_eur", "agg": "sum"}, "EURm"),
    ("Safety incidents 2025", {"dataset": "safety", "metric": "count"}, "{:,.0f}"),
]


def kpis_for(user: dict, limit: int = 6) -> list[dict]:
    out = []
    for label, spec, fmt in KPIS:
        if allowed(user, spec["dataset"]):
            r = run(spec)
            disp = f"EUR {r['value'] / 1e6:,.1f}m" if fmt == "EURm" else fmt.format(r["value"])
            out.append({"label": label, "value": r["value"], "display": disp, "source": r["source_title"]})
    return out[:limit]


def dashboard_tabs(user: dict) -> list[str]:
    tabs = [d for d in WIDGETS if any(allowed(user, w["dataset"]) for w in WIDGETS[d])
            and (d != "Executive Office" or access.max_level(user) >= 3)]
    first = "Executive Office" if access.max_level(user) >= 4 else user["department"]
    return sorted(tabs, key=lambda d: (d != first, d != user["department"], d))


def dashboard(user: dict, tab: str) -> list[dict]:
    out = []
    for w in WIDGETS.get(tab, []):
        if allowed(user, w["dataset"]):
            r = run({**w, "title": w["title"]})
            out.append(r)
    return out


# ---------------------------------------------------------------------------- natural language -> spec
CHART_INTENT = re.compile(r"\b(chart|graph|plot|visuali[sz]e|dashboard|breakdown|break down|distribution|trend|over time|per month|by month|"
                          r"compare|comparison|top \d+|split by|grouped by|pie|bar chart|line chart|how many .* (by|per) )\b", re.I)


def wants_chart(q: str) -> bool:
    return bool(CHART_INTENT.search(q))


def plan(question: str, user: dict) -> dict:
    """Ask the local LLM to translate the question into a chart spec, constrained by a JSON schema."""
    from rag import generator
    cat = catalog_for(user)
    if not cat:
        raise SpecError("you have no access to structured datasets")
    lines = [f"- {k}: {v['title']}. dimensions: {', '.join(v['dims'])}. measures: {', '.join(v['measures'] + ['count'])}" for k, v in cat.items()]
    system = ("You turn business questions into a JSON chart specification over these datasets. Use ONLY the dataset, dimension "
              "and measure names listed. Choose agg 'sum' for money and quantities, 'mean' for scores, rates and percentages, "
              "'count' to count rows. Choose chart: line for time (month, quarter, year), doughnut for shares of a whole with few "
              "categories, hbar for rankings or long labels, bar otherwise. Use 'series' only when the user asks to split by a second "
              "dimension. Use 'top' when the user asks for top N. Use filters only when the user names a specific value.\n\nDATASETS:\n" + "\n".join(lines))
    # one schema branch per dataset: the grammar only allows that dataset's own dimensions and measures
    branches = []
    for k, v in cat.items():
        branches.append({"type": "object", "properties": {
            "dataset": {"const": k}, "x": {"enum": v["dims"]}, "metric": {"enum": v["measures"] + ["count"]},
            "series": {"enum": v["dims"] + [None]}, "agg": {"enum": sorted(AGGS)},
            "chart": {"enum": ["bar", "hbar", "line", "pie", "doughnut", "table"]}, "top": {"type": ["integer", "null"]},
            "title": {"type": "string"},
            "filters": {"type": "array", "items": {"type": "object", "properties": {
                "col": {"enum": v["dims"]}, "op": {"enum": ["eq", "ne", "in", "contains"]}, "value": {"type": "string"}},
                "required": ["col", "op", "value"]}}},
            "required": ["dataset", "x", "metric", "agg", "chart", "title", "series", "top", "filters"]})
    schema = {"anyOf": branches}
    import requests
    from rag import config
    r = requests.post(f"{config.LLM_URL}/v1/chat/completions", timeout=120, json={
        "model": config.LLM_NAME, "temperature": 0, "max_tokens": 300, "seed": config.SEED,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "chart_spec", "schema": schema}}})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    spec = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    if spec.get("dataset") not in cat:
        raise SpecError("the requested data is not in a dataset you can access")
    if not any(k in question.lower() for k in KEYWORDS.get(spec["dataset"], [])):
        raise SpecError("question does not match an accessible dataset")   # avoid charting the wrong data
    return _repair(spec, question)


def _repair(spec: dict, question: str) -> dict:
    """Deterministic fixes for common small-model slips."""
    q = question.lower()
    dims = CATALOG[spec["dataset"]]["dims"]
    if not spec.get("series"):                              # "... by month by region" -> split by the second dimension
        for d in dims:
            if d != spec.get("x") and re.search(rf"\bby {re.escape(d.replace('_', ' '))}\b", q):
                spec["series"] = d
                break
    m = re.search(r"\btop (\d+)\s+([a-z ]+?)\b(by|in|for|with|$)", q)
    if m:
        spec["top"] = spec.get("top") or int(m.group(1))
        entity = {"account manager": ["account_manager", "owner"], "customer": ["account_name", "account"], "account": ["account_name", "account"],
                  "supplier": ["supplier_name", "supplier"], "product": ["product"], "owner": ["owner", "account_manager"],
                  "buyer": ["buyer"], "employee": ["employee", "name"], "site": ["site", "delivery_site"], "countr": ["country"],
                  "region": ["region"], "department": ["department"], "categor": ["category"]}
        for key, cands in entity.items():
            if key in m.group(2):
                hit = next((c for c in cands if c in dims), None)
                if hit:
                    spec["x"] = hit
                    if not re.search(rf"\bby {re.escape(str(spec.get('series') or '').replace('_', ' '))}\b", q):
                        spec["series"] = None           # a top-N ranking is a single series unless a split was asked for
                break
    if spec.get("top") and spec.get("chart") in ("bar", "pie", "doughnut"):
        spec["chart"] = "hbar"                              # rankings read best as horizontal bars
    spec["title"] = ""                                      # titles are computed from the executed spec, never taken from the model
    if spec.get("metric") == "count":
        spec["agg"] = "count"
    if spec.get("x") in TIME_DIMS and spec.get("chart") in ("bar", "hbar") and "bar" not in q and "column" not in q:
        spec["chart"] = "line"
    return spec
