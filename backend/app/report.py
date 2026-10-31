"""PDF security report. All text is untrusted (file names, rule descriptions), so it is escaped
before it reaches reportlab's mini-markup parser."""
import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import export

SEV_COLOR = {"critical": "#a4161a", "high": "#d9480f", "medium": "#a8670a", "low": "#2b6cb0"}
SEV_ORDER = ["critical", "high", "medium", "low"]
MAX_ROWS = 300
LABELS = {"secrets": "Secrets", "dependencies": "Dependencies", "code": "Source code", "iac": "Infrastructure",
          "docker": "Dockerfile", "semgrep": "Multi-language SAST", "checkov": "IaC policies", "shell": "Shell scripts"}


def _t(text, limit: int = 300) -> str:
    return escape(str(text if text is not None else "")[:limit])


def to_pdf(scan: dict) -> bytes:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#586964"))
    h1 = ParagraphStyle("h1", parent=ss["Title"], alignment=0, fontSize=22, leading=26)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, spaceBefore=14)
    result = scan.get("result") or {}
    items = sorted(export.findings(scan), key=lambda f: SEV_ORDER.index(f.get("severity")) if f.get("severity") in SEV_ORDER else 9)
    score = scan.get("score") or 0
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    story = [Paragraph("SecureShip security report", h1),
             Paragraph(f"Project: <b>{_t(scan.get('filename'), 120)}</b> &nbsp;·&nbsp; Generated {when}", body),
             Paragraph(f"Scan ID: {_t(scan.get('id'), 40)}", small), Spacer(1, 8 * mm)]

    col = "#15803d" if score >= 80 else "#4d7c0f" if score >= 60 else "#a8670a" if score >= 40 else "#a4161a"
    story.append(Paragraph(f'<font size="34" color="{col}"><b>{int(score)}</b></font> <font size="11">/ 100</font>', body))

    mods = result.get("modules") or {}
    if mods:
        story.append(Paragraph("Modules", h2))
        rows = [["Module", "Score", "Findings"]] + [
            [LABELS.get(m, m), str(s), str(len((result.get(m) or {}).get("findings") or []))] for m, s in mods.items()]
        t = Table(rows, colWidths=[90 * mm, 30 * mm, 30 * mm])
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5ebe7")),
                               ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#cdd6d1")), ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
        story.append(t)

    for k, msg in (result.get("skipped") or {}).items():
        story.append(Paragraph(f"{_t(LABELS.get(k, k))} skipped: {_t(msg, 160)}", small))
    for k, msg in (result.get("errors") or {}).items():
        story.append(Paragraph(f"{_t(LABELS.get(k, k))} could not run: {_t(msg, 160)}", small))

    story.append(Paragraph(f"Findings ({len(items)})", h2))
    if not items:
        story.append(Paragraph("No issues were found by the selected scanners.", body))
    else:
        rows = [["Severity", "Rule", "Location", "Description"]]
        for f in items[:MAX_ROWS]:
            loc = f"{f.get('file') or ''}{':' + str(f['line']) if f.get('line') else ''}"
            rows.append([Paragraph(f'<font color="{SEV_COLOR.get(f.get("severity"), "#000")}"><b>{_t(f.get("severity"), 10)}</b></font>', body),
                         Paragraph(_t(f.get("rule"), 80), body), Paragraph(_t(loc, 120), body), Paragraph(_t(f.get("description"), 240), body)])
        t = Table(rows, colWidths=[18 * mm, 38 * mm, 48 * mm, 66 * mm], repeatRows=1)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, 0), 9),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5ebe7")),
                               ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#cdd6d1"))]))
        story.append(t)
        if len(items) > MAX_ROWS:
            story.append(Paragraph(f"{len(items) - MAX_ROWS} more findings are in the SARIF/CSV export.", small))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                      title="SecureShip security report", author="SecureShip").build(story)
    return buf.getvalue()
