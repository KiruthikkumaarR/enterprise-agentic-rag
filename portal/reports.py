"""One-click reports: PowerPoint decks with native (editable) charts and Excel workbooks.

Every chart and figure in a report is computed by ``analytics.run`` from a dataset the requesting user is cleared
to read; widgets the user may not see are left out, and the deck is labelled with the highest classification of
the data it contains.
"""
from __future__ import annotations

import io
import math
import re
from datetime import date

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from . import analytics
from .company_data import COMPANY, LEVELS

NAVY, INK, MUTED, TEAL, BLUE = RGBColor(0x0A, 0x10, 0x20), RGBColor(0x1B, 0x22, 0x33), RGBColor(0x6B, 0x76, 0x8F), RGBColor(0x1F, 0xB5, 0xA3), RGBColor(0x3D, 0x6F, 0xE0)
PALETTE = ["1FB5A3", "3D6FE0", "F2A93B", "E0566A", "8E6CE0", "5BBF7A", "4FB3D9", "D98E4F", "A0A8B8", "C6D24A"]
LEVEL_COLORS = {1: "2E9E6A", 2: "3D6FE0", 3: "C98A1B", 4: "D23C50"}

T = lambda title, *widgets, **kw: {"title": title, "widgets": list(widgets), **kw}   # noqa: E731
TEMPLATES = {
    "executive_summary": T("Executive Summary", "Executive Office", "Sales", "Human Resources", "Operations",
                           description="Board-level view: financial performance, bookings, pipeline, people, operations and legal exposure.", min_level=4),
    "finance_overview": T("Finance Overview", "Finance", description="Quarterly results, budget versus actuals, payables and expense spend.", dept="Finance"),
    "sales_review": T("Sales Review", "Sales", description="Pipeline by stage, product and owner; customer mix; bookings by region.", dept="Sales"),
    "people_report": T("People Report", "Human Resources", description="Headcount by department and site, hiring trend, open positions and ratings.", dept="Human Resources"),
    "operations_review": T("Operations Review", "Operations", "Quality", description="Stock value, reorder risk, safety incidents and production plan.", dept="Operations"),
    "procurement_review": T("Procurement Review", "Procurement", description="Purchase order spend by category and supplier, supplier quality.", dept="Procurement"),
    "it_review": T("IT Review", "IT", description="IT asset estate by type and status and the refresh schedule.", dept="IT"),
    "marketing_review": T("Marketing Review", "Marketing", description="Campaign spend, leads and opportunities by channel and product.", dept="Marketing"),
    "legal_review": T("Legal & Contracts Review", "Legal & Compliance", description="Contract portfolio value and renewal profile.", dept="Legal & Compliance"),
    "engineering_review": T("Engineering Review", "Engineering", description="Engineering change orders by status, product and impact.", dept="Engineering"),
}


def widgets_for(user: dict, key: str) -> list[dict]:
    t = TEMPLATES[key]
    seen, out = set(), []
    for d in t["widgets"]:
        for w in analytics.WIDGETS.get(d, []):
            if w["title"] not in seen and analytics.allowed(user, w["dataset"]):
                seen.add(w["title"])
                out.append(w)
    return out


def available(user: dict) -> list[dict]:
    from . import access
    res = []
    for k, t in TEMPLATES.items():
        if t.get("min_level") and access.max_level(user) < t["min_level"]:
            continue
        ws = widgets_for(user, k)
        if not ws:
            continue
        lvl = max(analytics.doc_meta(w["dataset"])["level"] for w in ws)
        res.append({"id": k, "title": t["title"], "description": t["description"], "charts": len(ws), "level": lvl, "level_label": LEVELS[lvl],
                    "recommended": t.get("dept") == user["department"] or (k == "executive_summary")})
    return sorted(res, key=lambda r: (not r["recommended"], r["title"]))


# ---------------------------------------------------------------------------- pptx helpers
def _text(slide, x, y, w, h, text, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text, p.alignment = text, align
    p.font.size, p.font.bold, p.font.color.rgb, p.font.name = Pt(size), bold, color, "Calibri"
    return tb


def _rect(slide, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = fill
    if line:
        s.line.color.rgb = line
    else:
        s.line.fill.background()
    s.adjustments[0] = 0.08
    s.shadow.inherit = False
    return s


def _header(slide, title, subtitle, level):
    _rect(slide, 0, 0, 13.333, 0.12, TEAL)
    _text(slide, 0.6, 0.35, 10.5, 0.6, title, 26, True)
    if subtitle:
        _text(slide, 0.6, 0.95, 10.5, 0.4, subtitle, 12, color=MUTED)
    tag = _rect(slide, 10.9, 0.42, 1.85, 0.36, RGBColor.from_string(LEVEL_COLORS[level]))
    tag.text_frame.text = LEVELS[level].upper()
    p = tag.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    p.font.size, p.font.bold, p.font.color.rgb = Pt(10), True, RGBColor(0xFF, 0xFF, 0xFF)


def _footer(slide, source, n):
    _text(slide, 0.6, 7.0, 9.5, 0.3, f"Source: {source}", 9, color=MUTED)
    _text(slide, 11.6, 7.0, 1.2, 0.3, str(n), 9, color=MUTED, align=PP_ALIGN.RIGHT)


CHART_TYPES = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "hbar": XL_CHART_TYPE.BAR_CLUSTERED, "line": XL_CHART_TYPE.LINE_MARKERS,
               "pie": XL_CHART_TYPE.PIE, "doughnut": XL_CHART_TYPE.DOUGHNUT, "table": XL_CHART_TYPE.COLUMN_CLUSTERED}


def add_chart(slide, r: dict, x=0.6, y=1.5, w=12.1, h=5.3):
    cd = CategoryChartData()
    labels = r["labels"]
    if r["spec"]["chart"] == "hbar":           # bars read top-down like the web view
        labels = labels[::-1]
    cd.categories = labels
    for ds in r["datasets"]:
        data = ds["data"][::-1] if r["spec"]["chart"] == "hbar" else ds["data"]
        cd.add_series(ds["label"], data)
    kind = r["spec"]["chart"]
    gf = slide.shapes.add_chart(CHART_TYPES[kind], Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    ch.font.size, ch.font.name = Pt(11), "Calibri"
    ch.has_legend = len(r["datasets"]) > 1 or kind in ("pie", "doughnut")
    if ch.has_legend:
        ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
    plot = ch.plots[0]
    if kind in ("pie", "doughnut"):
        for i, pt in enumerate(plot.series[0].points):
            pt.format.fill.solid(); pt.format.fill.fore_color.rgb = RGBColor.from_string(PALETTE[i % len(PALETTE)])
        plot.has_data_labels = True
        plot.data_labels.number_format, plot.data_labels.number_format_is_linked = "0%", False
        plot.data_labels.show_percentage, plot.data_labels.show_value = True, False
    else:
        for i, s in enumerate(plot.series):
            col = RGBColor.from_string(PALETTE[i % len(PALETTE)])
            if kind == "line":
                s.format.line.color.rgb, s.format.line.width, s.smooth = col, Pt(2.25), False
                s.marker.style, s.marker.size = XL_MARKER_STYLE.CIRCLE, 5
                s.marker.format.fill.solid(); s.marker.format.fill.fore_color.rgb = col
                s.marker.format.line.color.rgb = col
            else:
                s.format.fill.solid(); s.format.fill.fore_color.rgb = col
        if kind in ("bar", "hbar"):
            plot.gap_width = 60
            if len(r["datasets"]) == 1 and len(labels) <= 14:
                plot.has_data_labels = True
                dl = plot.data_labels
                dl.number_format, dl.number_format_is_linked, dl.font.size = '#,##0.0' if max(r["datasets"][0]["data"] or [0]) < 1000 else '#,##0', False, Pt(9)
                dl.position = XL_LABEL_POSITION.OUTSIDE_END
        va = ch.value_axis
        peak = max((v for ds in r["datasets"] for v in ds["data"]), default=0)
        if peak > 0:                                     # a "nice" axis maximum just above the data
            mag = 10 ** math.floor(math.log10(peak))
            va.maximum_scale = math.ceil(peak * 1.12 / (mag / 2)) * (mag / 2)
            va.major_unit = va.maximum_scale / 5
            va.minimum_scale = 0 if min((v for ds in r["datasets"] for v in ds["data"]), default=0) >= 0 else None
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = RGBColor(0xE3, 0xE7, 0xEE)
        va.tick_labels.number_format, va.tick_labels.number_format_is_linked = '#,##0.#' if peak < 100 else '#,##0', False
        va.format.line.fill.background()
    return ch


def _kpi_slide(prs, user, kpis, n, level):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _header(s, "Key figures", f"As of {date.today():%d %B %Y}", level)
    for i, k in enumerate(kpis[:6]):
        col, row = i % 3, i // 3
        x, y = 0.6 + col * 4.1, 1.7 + row * 2.55
        _rect(s, x, y, 3.85, 2.25, RGBColor(0xF4, 0xF7, 0xFB), RGBColor(0xE3, 0xE7, 0xEE))
        _text(s, x + 0.3, y + 0.3, 3.3, 0.4, k["label"].upper(), 11, True, MUTED)
        _text(s, x + 0.3, y + 0.75, 3.3, 0.8, k["display"], 30, True, NAVY)
        _text(s, x + 0.3, y + 1.6, 3.3, 0.4, k["source"], 10, color=MUTED)
    _footer(s, "Financial KPIs, pipeline, customer, HR, procurement, inventory and safety datasets", n)


def _table_slide(prs, r, n, level):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _header(s, r["title"] + " - data", r["source_title"], level)
    rows = min(len(r["labels"]), 14)
    cols = 1 + len(r["datasets"])
    tbl = s.shapes.add_table(rows + 1, cols, Inches(0.6), Inches(1.5), Inches(12.1), Inches(0.36 * (rows + 1))).table
    tbl.cell(0, 0).text = r["spec"]["x"].replace("_", " ").capitalize()
    for j, ds in enumerate(r["datasets"], 1):
        tbl.cell(0, j).text = ds["label"]
    for i in range(rows):
        tbl.cell(i + 1, 0).text = str(r["labels"][i])
        for j, ds in enumerate(r["datasets"], 1):
            v = ds["data"][i]
            tbl.cell(i + 1, j).text = f"{v:,.1f}" if abs(v) < 1000 else f"{v:,.0f}"
    for row in tbl.rows:
        for c in row.cells:
            for p in c.text_frame.paragraphs:
                p.font.size = Pt(11)
    _footer(s, f"{r['source_doc']} ({r['rows_used']:,} records)", n)


def build_pptx(user: dict, key: str) -> tuple[bytes, str]:
    t = TEMPLATES[key]
    ws = widgets_for(user, key)
    results = [analytics.run(w) for w in ws]
    level = max(analytics.doc_meta(w["dataset"])["level"] for w in ws)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    # title slide
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
    _rect(s, 0.8, 2.3, 0.12, 2.2, TEAL)
    _text(s, 1.15, 2.1, 11, 0.5, COMPANY.upper(), 14, True, TEAL)
    _text(s, 1.15, 2.6, 11, 1.2, t["title"], 44, True, RGBColor(0xFF, 0xFF, 0xFF))
    _text(s, 1.15, 3.7, 11, 0.6, t["description"], 16, color=RGBColor(0xB8, 0xC3, 0xDA))
    _text(s, 1.15, 5.6, 11, 0.4, f"Prepared for {user['full_name']}, {user['title']}  ·  {date.today():%d %B %Y}", 13, color=RGBColor(0xB8, 0xC3, 0xDA))
    _text(s, 1.15, 6.05, 11, 0.4, f"Classification: {LEVELS[level]}  ·  Generated by Halvorsen Intelligence Portal from source records", 11,
          color=RGBColor(0x8A, 0x96, 0xB0))
    n = 2
    kpis = analytics.kpis_for(user, 6)
    if kpis:
        _kpi_slide(prs, user, kpis, n, level); n += 1
    for r, w in zip(results, ws):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        lvl = analytics.doc_meta(w["dataset"])["level"]
        _header(s, r["title"], f"{r['source_title']} · {r['rows_used']:,} records · {insight(r)}", lvl)
        add_chart(s, r)
        _footer(s, r["source_doc"], n); n += 1
        if r["spec"]["chart"] in ("hbar",) and r["spec"].get("top"):
            _table_slide(prs, r, n, lvl); n += 1
    # sources slide
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _header(s, "Sources and method", "Every figure is computed directly from the records below - no figure is written by AI.", level)
    srcs = sorted({(r["source_doc"], r["source_title"], analytics.doc_meta(w["dataset"])["level"]) for r, w in zip(results, ws)})
    for i, (doc, title, lvl) in enumerate(srcs):
        _text(s, 0.8, 1.6 + i * 0.42, 8.5, 0.4, f"•  {title}  -  {doc}", 13)
        _text(s, 9.6, 1.6 + i * 0.42, 3, 0.4, LEVELS[lvl], 12, True, RGBColor.from_string(LEVEL_COLORS[lvl]))
    _footer(s, "Halvorsen Intelligence Portal", n)
    buf = io.BytesIO(); prs.save(buf)
    return buf.getvalue(), f"{t['title'].replace(' ', '_').replace('&', 'and')}_{date.today():%Y%m%d}.pptx"


def insight(r: dict) -> str:
    """One deterministic sentence describing the chart (computed, not generated)."""
    if not r["labels"] or not r["datasets"]:
        return ""
    multi = len(r["datasets"]) > 1 and r["spec"].get("series")
    d = [sum(ds["data"][i] for ds in r["datasets"]) for i in range(len(r["labels"]))] if multi else r["datasets"][0]["data"]
    total = sum(d)
    if r["spec"]["chart"] == "line" and len(d) > 1 and d[0]:
        return f"{r['labels'][-1]}{' total' if multi else ''}: {d[-1]:,.1f} ({(d[-1] - d[0]) / abs(d[0]) * 100:+.0f}% vs {r['labels'][0]})"
    i = max(range(len(d)), key=lambda k: d[k])
    share = f" ({d[i] / total * 100:.0f}% of total)" if total and r["spec"]["agg"] in ("sum", "count") and not r["spec"].get("top") else ""
    return f"Largest: {r['labels'][i]} at {d[i]:,.1f}{share}"


def chart_pptx(user: dict, spec: dict) -> tuple[bytes, str]:
    r = analytics.run(spec)
    lvl = analytics.doc_meta(r["spec"]["dataset"])["level"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _header(s, r["title"], f"{r['source_title']} · {r['rows_used']:,} records · {insight(r)}", lvl)
    add_chart(s, r)
    _footer(s, f"{r['source_doc']} · prepared for {user['full_name']} · {date.today():%d %B %Y}", 1)
    buf = io.BytesIO(); prs.save(buf)
    return buf.getvalue(), re.sub(r"[^A-Za-z0-9]+", "_", r["title"])[:60] + ".pptx"


def xlsx(user: dict, specs: list[dict], name: str) -> tuple[bytes, str]:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summary = []
        for i, spec in enumerate(specs, 1):
            r = analytics.run(spec)
            df = pd.DataFrame({r["spec"]["x"] or "value": r["labels"] or [r["title"]], **{ds["label"]: ds["data"] for ds in r["datasets"]}})
            sheet = f"{i:02d} " + re.sub(r"[\[\]:*?/\\]", "", r["title"])[:26]
            df.to_excel(xw, sheet_name=sheet, index=False)
            summary.append({"sheet": sheet, "chart": r["title"], "source": r["source_doc"], "records": r["rows_used"],
                            "classification": LEVELS[analytics.doc_meta(r["spec"]["dataset"])["level"]]})
        pd.DataFrame(summary).to_excel(xw, sheet_name="Contents", index=False)
        if len(specs) == 1:
            analytics.rows_for_export(specs[0]).to_excel(xw, sheet_name="Source records", index=False)
        for ws in xw.book.worksheets:                     # readable column widths
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(48, max(10, max(len(str(c.value or "")) for c in col) + 2))
        xw.book.move_sheet("Contents", offset=-len(xw.book.sheetnames) + 1)
    return buf.getvalue(), f"{name}_{date.today():%Y%m%d}.xlsx"

