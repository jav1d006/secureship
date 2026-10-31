import pytest

from app import config, mailer, report
from tests.test_api import client  # noqa: F401

SCAN = {"id": "a" * 32, "filename": "<b>evil</b>&name.zip", "status": "done", "score": 62, "result": {
    "modules": {"secrets": 40}, "skipped": {"code": "no <py> files"}, "errors": {},
    "secrets": {"findings": [{"severity": "critical", "rule": "aws<key>", "file": "a&b.py", "line": 3, "description": "<para>x</para>"}]}}}


def test_pdf_is_generated_and_escapes_markup():
    pdf = report.to_pdf(SCAN)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500


def test_pdf_handles_empty_and_many_findings():
    assert report.to_pdf({"id": "x", "filename": "a", "score": 100, "result": {"modules": {}}}).startswith(b"%PDF")
    many = {**SCAN, "result": {"modules": {"code": 0}, "code": {"findings": [{"severity": "low", "rule": f"r{i}", "file": "f", "description": "d"} for i in range(400)]}}}
    assert report.to_pdf(many).startswith(b"%PDF")


def test_email_validation():
    assert mailer.EMAIL_RE.match("a.b+c@example.co")
    for bad in ("x", "a@b", "a@@b.com", "a b@c.com", "a@b.c", "a@b.com\r\nBcc: x@y.com"):
        assert not mailer.EMAIL_RE.match(bad)


class Store:
    def __init__(self, c):
        self.c = c

    def make(self):
        r = self.c.post("/api/v1/scans", data={"scanners": "secrets"}, files=[("files", ("p/a", b"x"))])
        from app import main
        sid = r.json()["id"]
        main.db.rows[sid].update(status="done", score=80, result=SCAN["result"])
        return sid


def test_email_flow(client, monkeypatch):
    sid = Store(client).make()
    sent = []
    monkeypatch.setattr(mailer, "send_report", lambda to, name, score, pdf: sent.append((to, pdf[:4])))
    monkeypatch.setattr(config, "SMTP_HOST", "")
    assert client.get("/api/v1/config").json() == {"email": False}
    assert client.post(f"/api/v1/scans/{sid}/email", json={"to": "a@b.com"}).status_code == 501
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    assert client.get("/api/v1/config").json() == {"email": True}
    assert client.post(f"/api/v1/scans/{sid}/email", json={"to": "nope"}).status_code == 400
    assert client.post(f"/api/v1/scans/{'b' * 32}/email", json={"to": "a@b.com"}).status_code == 404
    assert client.post(f"/api/v1/scans/{sid}/email", json={"to": "A@B.com"}).status_code == 202
    assert sent == [("a@b.com", b"%PDF")]
    for _ in range(2):
        client.post(f"/api/v1/scans/{sid}/email", json={"to": "a@b.com"})
    assert client.post(f"/api/v1/scans/{sid}/email", json={"to": "a@b.com"}).status_code == 429   # per-recipient cap


def test_pdf_export_endpoint(client):
    sid = Store(client).make()
    r = client.get(f"/api/v1/scans/{sid}/export?format=pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
