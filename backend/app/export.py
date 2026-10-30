"""Scan result exporters (SARIF 2.1.0 for GitHub Code Scanning / IDEs, CSV) and the public score badge."""
import csv
import io
from xml.sax.saxutils import escape

META_KEYS = {"modules", "errors", "skipped", "timings"}
LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}
SECURITY_SEVERITY = {"critical": "9.5", "high": "8.0", "medium": "5.5", "low": "2.0"}


def findings(scan: dict) -> list[dict]:
    """Flat list of findings, each tagged with its module."""
    result = scan.get("result") or {}
    return [{**f, "module": m} for m, v in result.items()
            if m not in META_KEYS and isinstance(v, dict) for f in v.get("findings") or []]


def to_sarif(scan: dict) -> dict:
    rules, results = {}, []
    for f in findings(scan):
        rid = f"{f['module']}/{f.get('rule') or 'finding'}"
        sev = f.get("severity", "low")
        rules.setdefault(rid, {"id": rid, "name": rid, "shortDescription": {"text": (f.get("description") or rid)[:200]},
                               "properties": {"security-severity": SECURITY_SEVERITY.get(sev, "2.0"),
                                              "tags": ["security", f["module"]]}})
        results.append({
            "ruleId": rid, "level": LEVEL.get(sev, "note"),
            "message": {"text": f.get("description") or rid},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": f.get("file") or "unknown"},
                                                "region": {"startLine": max(int(f.get("line") or 1), 1)}}}],
        })
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "SecureShip", "informationUri": "https://github.com/jav1d006/secureship",
                                          "rules": list(rules.values())}}, "results": results}]}


def to_csv(scan: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["module", "severity", "rule", "file", "line", "description"])
    for f in findings(scan):
        # prefix formula-looking cells so a spreadsheet never evaluates scanned content
        cells = [f["module"], f.get("severity"), f.get("rule"), f.get("file"), f.get("line"), f.get("description")]
        w.writerow([("'" + c) if isinstance(c, str) and c and c[0] in "=+-@\t\r" else c for c in cells])
    return out.getvalue()


def badge_svg(status: str | None, score: int | None) -> str:
    if status == "done" and score is not None:
        value = f"{score}/100"
        color = "#4c1" if score >= 80 else "#97ca00" if score >= 60 else "#dfb317" if score >= 40 else "#e05d44"
    else:
        value, color = ("failed", "#9f9f9f") if status == "failed" else ("pending", "#9f9f9f")
    label = "security"
    lw, vw = 6 * len(label) + 12, 6 * len(value) + 12
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw + vw}" height="20" role="img" aria-label="{label}: {escape(value)}">'
            f'<rect width="{lw}" height="20" fill="#555"/><rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
            f'<text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" y="14">{escape(value)}</text></g></svg>')
