from tests.test_api import client  # noqa: F401


def H(k):
    return {"X-API-Key": k}


def test_key_lifecycle_shares_history_with_session(client):
    r = client.post("/api/v1/keys", json={"name": "ci"})
    assert r.status_code == 201 and r.json()["name"] == "ci"
    key, kid = r.json()["api_key"], r.json()["id"]
    # the key acts as the session that created it: scans from either side are visible to both
    client.post("/api/v1/scans", headers=H(key), data={"scanners": "secrets"}, files=[("files", ("p/a", b"x"))])
    assert len(client.get("/api/v1/scans").json()) == 1
    assert [k["id"] for k in client.get("/api/v1/keys").json()] == [kid]
    assert "api_key" not in client.get("/api/v1/keys").json()[0]
    assert client.delete(f"/api/v1/keys/{kid}").status_code == 204
    assert client.get("/api/v1/scans", headers=H(key)).status_code == 401
    assert client.delete(f"/api/v1/keys/{kid}").status_code == 404


def test_key_cannot_manage_keys_and_limit(client, monkeypatch):
    from app import config
    key = client.post("/api/v1/keys").json()["api_key"]
    assert client.post("/api/v1/keys", headers=H(key)).status_code == 403
    assert client.get("/api/v1/keys", headers=H(key)).status_code == 403
    monkeypatch.setattr(config, "MAX_API_KEYS", 2)
    assert client.post("/api/v1/keys").status_code == 201
    assert client.post("/api/v1/keys").status_code == 409


def test_keys_are_private_to_creator(client):
    from fastapi.testclient import TestClient
    kid = client.post("/api/v1/keys").json()["id"]
    other = TestClient(client.app)
    assert other.get("/api/v1/keys").json() == []
    assert other.delete(f"/api/v1/keys/{kid}").status_code == 404
