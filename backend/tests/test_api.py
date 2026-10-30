"""API tests: ownership (IDOR), validation and rate limits, with Redis/Postgres/queue faked."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import main, security


class FakeRedis:
    def __init__(self):
        self.d = {}

    def incr(self, k):
        self.d[k] = self.d.get(k, 0) + 1
        return self.d[k]

    def expire(self, k, s):
        pass

    def ttl(self, k):
        return 42


class FakeDB:
    def __init__(self):
        self.rows = {}

    def create_scan(self, name, data, scanners, owner):
        sid = f"{len(self.rows):032x}"
        self.rows[sid] = {"id": sid, "filename": name, "status": "queued", "owner": owner}
        return sid

    def get_scan_owned(self, sid, owner):
        r = self.rows.get(sid)
        return r if r and r["owner"] == owner else None

    def list_scans_owned(self, owner, limit, offset):
        return [r for r in self.rows.values() if r["owner"] == owner]

    def count_by_status(self):
        return {"queued": 2}

    def stats(self):
        return {"oldest_queued": 42.0, "done_1h": 5, "failed_1h": 1, "avg_duration": 7.5}

    def delete_scan(self, sid, owner):
        return self.rows.pop(sid, None) is not None if self.get_scan_owned(sid, owner) else False


@pytest.fixture
def client(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(security, "_redis", FakeRedis())
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main.worker, "queue_len", lambda: 0)
    monkeypatch.setattr(main.worker, "enqueue", lambda sid: None)
    return TestClient(main.app)


def zip_bytes():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("a.txt", "x")
    return b.getvalue()


def upload(c, key, name="p.zip", data=None, scanners="secrets"):
    return c.post("/api/v1/scans", headers={"X-API-Key": key},
                  files={"file": (name, data if data is not None else zip_bytes())},
                  data={"scanners": scanners})


def test_owner_cannot_read_or_delete_foreign_scan(client):
    a, b = security.new_token(), security.new_token()
    sid = upload(client, a).json()["id"]
    assert client.get(f"/api/v1/scans/{sid}", headers={"X-API-Key": a}).status_code == 200
    assert client.get(f"/api/v1/scans/{sid}", headers={"X-API-Key": b}).status_code == 404
    assert client.delete(f"/api/v1/scans/{sid}", headers={"X-API-Key": b}).status_code == 404
    assert client.get("/api/v1/scans", headers={"X-API-Key": b}).json() == []
    assert client.delete(f"/api/v1/scans/{sid}", headers={"X-API-Key": a}).status_code == 204


def test_invalid_api_key_rejected(client):
    assert client.get("/api/v1/scans", headers={"X-API-Key": "nope"}).status_code == 401


def test_upload_validation(client):
    k = security.new_token()
    assert upload(client, k, name="p.txt").status_code == 400
    assert upload(client, k, data=b"not a zip").status_code == 400
    assert upload(client, k, scanners="nope").status_code == 400
    assert upload(client, k, scanners=",").status_code == 400


def test_oversize_upload_rejected(client, monkeypatch):
    monkeypatch.setattr(main.config, "MAX_UPLOAD_MB", 0)
    assert upload(client, security.new_token()).status_code in (413,)


def test_scan_rate_limit(client, monkeypatch):
    monkeypatch.setattr(security.config, "RATE_SCANS_PER_HOUR", 2)
    k = security.new_token()
    codes = [upload(client, k).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_security_headers_and_malformed_id(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/v1/scans/../etc", headers={"X-API-Key": security.new_token()}).status_code == 404


def test_metrics_exposes_monitoring_series(client):
    client.get("/health")
    body = client.get("/metrics").text
    for line in ('secureship_oldest_queued_seconds 42.0',
                 'secureship_scans_finished_last_hour{status="failed"} 1.0',
                 'secureship_scan_duration_seconds_avg 7.5',
                 'secureship_dependency_up{dependency="postgres"} 1.0',
                 'secureship_dependency_up{dependency="redis"} 1.0',
                 'secureship_scans{status="queued"} 2.0'):
        assert line in body
    assert 'secureship_http_requests_total{method="GET",route="/health",status="200"}' in body
    assert "/metrics" not in body.split("secureship_http_requests_total")[1].split("# HELP")[0]


def test_metrics_survives_dependency_failure(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(main.worker, "queue_len", boom)
    monkeypatch.setattr(main.db, "stats", boom)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert 'secureship_dependency_up{dependency="redis"} 0.0' in r.text
    assert 'secureship_dependency_up{dependency="postgres"} 0.0' in r.text
