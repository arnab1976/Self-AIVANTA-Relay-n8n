"""Document engine: DOCX, PDF and XLSX exports.

Every export carries version, review status, assumptions and source evidence
(Definition of Done item 7).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any


def _meta_lines(doc: dict) -> list[tuple[str, str]]:
    return [
        ("Project", f"{doc.get('project_code', '')} · {doc.get('client', '')}"),
        ("Artifact", f"{doc.get('type', '')} v{doc.get('version', 1)}"),
        ("Review status", str(doc.get("review_status", "draft"))),
        ("Graph version / run", f"{doc.get('graph_version', '-')} / {doc.get('run_id', '-')}"),
        ("Generated", doc.get("generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    ]


def render_docx(doc: dict[str, Any]) -> bytes:
    from docx import Document
    from docx.shared import Pt

    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(10.5)
    d.add_heading(doc.get("title", "Document"), level=0)
    table = d.add_table(rows=0, cols=2)
    table.style = "Light List"
    for k, v in _meta_lines(doc):
        row = table.add_row().cells
        row[0].text, row[1].text = k, v
    for sec in doc.get("sections", []):
        d.add_heading(sec.get("heading", ""), level=1)
        if sec.get("body"):
            d.add_paragraph(sec["body"])
        for b in sec.get("bullets", []):
            d.add_paragraph(str(b), style="List Bullet")
        if sec.get("table"):
            rows = sec["table"]
            t = d.add_table(rows=1, cols=len(rows[0]))
            t.style = "Light Grid"
            for i, h in enumerate(rows[0]):
                t.rows[0].cells[i].text = str(h)
            for r in rows[1:]:
                cells = t.add_row().cells
                for i, v in enumerate(r):
                    cells[i].text = str(v)
    d.add_heading("Assumptions", level=1)
    for a in doc.get("assumptions", []) or ["None recorded"]:
        d.add_paragraph(str(a), style="List Bullet")
    d.add_heading("Source evidence", level=1)
    for s in doc.get("sources", []) or ["None recorded"]:
        d.add_paragraph(s if isinstance(s, str) else f"{s.get('document')} — {s.get('locator')}", style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def render_pdf(doc: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from xml.sax.saxutils import escape

    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(doc.get("title", "Document")), styles["Title"])]
    meta = Table([[k, escape(v)] for k, v in _meta_lines(doc)], colWidths=[45 * mm, 120 * mm])
    meta.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
                              ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
    story += [meta, Spacer(1, 8)]

    def bullets(items):
        return ListFlowable([ListItem(Paragraph(escape(str(i)), styles["BodyText"])) for i in items], bulletType="bullet")

    for sec in doc.get("sections", []):
        story.append(Paragraph(escape(sec.get("heading", "")), styles["Heading2"]))
        if sec.get("body"):
            story.append(Paragraph(escape(sec["body"]), styles["BodyText"]))
        if sec.get("bullets"):
            story.append(bullets(sec["bullets"]))
        if sec.get("table"):
            t = Table([[escape(str(c)) for c in r] for r in sec["table"]], repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                                   ("FONTSIZE", (0, 0), (-1, -1), 8.5)]))
            story.append(t)
    story.append(Paragraph("Assumptions", styles["Heading2"]))
    story.append(bullets(doc.get("assumptions") or ["None recorded"]))
    story.append(Paragraph("Source evidence", styles["Heading2"]))
    story.append(bullets([s if isinstance(s, str) else f"{s.get('document')} — {s.get('locator')}" for s in (doc.get("sources") or ["None recorded"])]))
    SimpleDocTemplate(buf, pagesize=A4, title=doc.get("title", "Document"), leftMargin=18 * mm, rightMargin=18 * mm).build(story)
    return buf.getvalue()


def render_xlsx(doc: dict[str, Any]) -> bytes:
    """Spreadsheet export: metadata sheet plus one sheet per table section."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([doc.get("title", "Document")])
    ws["A1"].font = Font(bold=True, size=14)
    for k, v in _meta_lines(doc):
        ws.append([k, v])
    ws.append([])
    ws.append(["Assumptions"])
    for a in doc.get("assumptions", []):
        ws.append(["", a])
    for i, sec in enumerate([s for s in doc.get("sections", []) if s.get("table")], 1):
        sh = wb.create_sheet(title=(sec.get("heading") or f"Table {i}")[:31])
        for r in sec["table"]:
            sh.append(list(r))
        for c in sh[1]:
            c.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


RENDERERS = {"docx": (render_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
             "pdf": (render_pdf, "application/pdf"),
             "xlsx": (render_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def render(doc: dict[str, Any], fmt: str) -> tuple[bytes, str]:
    if fmt not in RENDERERS:
        raise ValueError(f"Unsupported export format '{fmt}'")
    fn, mime = RENDERERS[fmt]
    return fn(doc), mime
