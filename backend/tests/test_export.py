import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app import export, main, security
from tests.test_api import FakeDB, FakeRedis

RESULT = {"modules": {"code": 85}, "errors": {}, "skipped": {}, "timings": {},
          "code": {"findings": [{"rule": "B602", "description": "shell=True", "file": "a.py", "line": 7, "severity": "high"},
                                {"rule": "B101", "description": "=cmd|' /C calc'!A0", "file": "b.py", "line": 0, "severity": "low"}]},
          "secrets": {"findings": []}}


def test_sarif_structure():
    s = export.to_sarif({"result": RESULT})
    run = s["runs"][0]
    assert s["version"] == "2.1.0" and run["tool"]["driver"]["name"] == "SecureShip"
    r0, r1 = run["results"]
    assert r0["ruleId"] == "code/B602" and r0["level"] == "error"
    assert r0["locations"][0]["physicalLocation"]["region"]["startLine"] == 7
    assert r1["level"] == "note" and r1["locations"][0]["physicalLocation"]["region"]["startLine"] == 1   # line 0 -> 1
    assert {r["id"] for r in run["tool"]["driver"]["rules"]} == {"code/B602", "code/B101"}


def test_csv_neutralises_formulas_and_keeps_empty_cells():
    rows = list(csv.reader(io.StringIO(export.to_csv({"result": RESULT}))))
    assert rows[0][0] == "module" and rows[1][:3] == ["code", "high", "B602"]
    assert rows[2][5].startswith("'=")
    assert export.to_csv({"result": {"code": {"findings": [{"description": "", "severity": "low"}]}}}).splitlines()[1].endswith(",")


def test_findings_ignore_meta_keys():
    assert {f["module"] for f in export.findings({"result": RESULT})} == {"code"}
    assert export.findings({"result": None}) == []


@pytest.mark.parametrize("status,score,text,color", [("done", 90, "90/100", "#4c1"), ("done", 65, "65/100", "#97ca00"),
                                                      ("done", 45, "45/100", "#dfb317"), ("done", 10, "10/100", "#e05d44"),
                                                      ("queued", None, "pending", "#9f9f9f"), ("failed", None, "failed", "#9f9f9f")])
def test_badge(status, score, text, color):
    svg = export.badge_svg(status, score)
    assert text in svg and color in svg and svg.startswith("<svg")


class ExportDB(FakeDB):
    def __init__(self):
        super().__init__()
        self.tokens = {}

    def get_scan_owned(self, sid, owner):
        r = self.rows.get(sid)
        return r if r and r["owner"] == owner else None

    def share_scan(self, sid, owner, token):
        if not self.get_scan_owned(sid, owner):
            return None
        return self.tokens.setdefault(sid, token)

    def unshare_scan(self, sid, owner):
        return bool(self.get_scan_owned(sid, owner)) and self.tokens.pop(sid, None) is not None

    def get_shared(self, token):
        sid = next((k for k, v in self.tokens.items() if v == token), None)
        return {"status": self.rows[sid]["status"], "score": self.rows[sid].get("score")} if sid else None


@pytest.fixture
def api(monkeypatch):
    db = ExportDB()
    monkeypatch.setattr(security, "_redis", FakeRedis())
    monkeypatch.setattr(main, "db", db)
    c = TestClient(main.app)
    a, b = security.new_token(), security.new_token()
    sid = db.create_scan("p.zip", b"PK", ["code"], security.hashlib.sha256(a.encode()).hexdigest())
    db.rows[sid].update(status="done", score=85, result=RESULT)
    return c, db, sid, {"X-API-Key": a}, {"X-API-Key": b}


def test_export_formats_and_ownership(api):
    c, db, sid, mine, other = api
    r = c.get(f"/api/v1/scans/{sid}/export?format=sarif", headers=mine)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/sarif+json")
    assert json.loads(r.text)["runs"][0]["results"]
    assert "module,severity" in c.get(f"/api/v1/scans/{sid}/export?format=csv", headers=mine).text
    assert c.get(f"/api/v1/scans/{sid}/export?format=json", headers=mine).json()["score"] == 85
    assert c.get(f"/api/v1/scans/{sid}/export?format=xml", headers=mine).status_code == 422
    assert c.get(f"/api/v1/scans/{sid}/export", headers=other).status_code == 404


def test_export_requires_finished_scan(api):
    c, db, sid, mine, _ = api
    db.rows[sid]["status"] = "running"
    assert c.get(f"/api/v1/scans/{sid}/export", headers=mine).status_code == 409


def test_badge_is_public_but_share_is_owner_only(api):
    c, db, sid, mine, other = api
    assert c.post(f"/api/v1/scans/{sid}/share", headers=other).status_code == 404
    url = c.post(f"/api/v1/scans/{sid}/share", headers=mine).json()["badge_url"]
    assert c.post(f"/api/v1/scans/{sid}/share", headers=mine).json()["badge_url"] == url      # idempotent
    r = c.get(url)                                        # no API key: public
    assert r.status_code == 200 and "85/100" in r.text and r.headers["content-type"] == "image/svg+xml"
    assert r.headers["cache-control"] == "public, max-age=300" and "p.zip" not in r.text
    assert c.delete(f"/api/v1/scans/{sid}/share", headers=mine).status_code == 204
    assert c.get(url).status_code == 404
    assert c.get("/api/v1/badge/not-a-token.svg").status_code == 404
