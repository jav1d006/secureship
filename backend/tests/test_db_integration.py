"""Needs a real PostgreSQL: set TEST_DATABASE_URL (CI provides a service container)."""
import os

import pytest

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def db(monkeypatch):
    from app import config
    from app import db as dbmod
    monkeypatch.setattr(config, "DATABASE_URL", URL)
    monkeypatch.setattr(dbmod, "_pool", None)
    dbmod.init_db()
    with dbmod._conn() as c:
        c.execute("DELETE FROM scans")
    yield dbmod
    dbmod._pool.close()


def age(db, sid, **cols):
    with db._conn() as c:
        for k, v in cols.items():
            c.execute(f"UPDATE scans SET {k}=%s WHERE id=%s", (v, sid))


def test_ownership_roundtrip(db):
    sid = db.create_scan("a.zip", b"PK", ["secrets"], "alice")
    assert db.get_scan_owned(sid, "alice")["filename"] == "a.zip"
    assert db.get_scan_owned(sid, "bob") is None
    assert db.list_scans_owned("bob", 10, 0) == []
    assert db.delete_scan(sid, "bob") is False and db.delete_scan(sid, "alice") is True


def test_set_running_counts_attempts(db):
    sid = db.create_scan("a.zip", b"PK", ["secrets"], "o")
    db.set_running(sid); db.set_running(sid)
    with db._conn() as c:
        assert c.execute("SELECT attempts, started_at FROM scans WHERE id=%s", (sid,)).fetchone()["attempts"] == 2


def test_stuck_scan_is_revived_then_given_up(db):
    sid = db.create_scan("a.zip", b"PK", ["secrets"], "o")
    db.set_running(sid)
    old = "2000-01-01T00:00:00+00:00"
    age(db, sid, started_at=old)
    assert db.fail_exhausted(3, 900) == 0 and db.reset_stuck(900) == 1       # attempt 1 died -> back to queue
    for _ in range(2):
        db.set_running(sid)
    age(db, sid, started_at=old)
    assert db.fail_exhausted(3, 900) == 1                                     # 3 attempts used -> failed
    s = db.get_scan_owned(sid, "o")
    assert s["status"] == "failed" and "repeated" in s["error"]
    assert db.get_upload(sid) is None


def test_running_last_attempt_is_not_killed(db):
    sid = db.create_scan("a.zip", b"PK", ["secrets"], "o")
    for _ in range(3):
        db.set_running(sid)
    assert db.fail_exhausted(3, 900) == 0 and db.get_scan_owned(sid, "o")["status"] == "running"


def test_unfinished_ids_respects_min_age(db):
    sid = db.create_scan("a.zip", b"PK", ["secrets"], "o")
    assert sid not in db.unfinished_ids(60) and sid in db.unfinished_ids(0)


def test_purge_old_only_removes_finished_expired(db):
    done = db.create_scan("d.zip", b"PK", ["secrets"], "o"); db.set_done(done, 90, {})
    queued = db.create_scan("q.zip", b"PK", ["secrets"], "o")
    fresh = db.create_scan("f.zip", b"PK", ["secrets"], "o"); db.set_done(fresh, 90, {})
    old = "2000-01-01T00:00:00+00:00"
    age(db, done, created_at=old); age(db, queued, created_at=old)
    assert db.purge_old(30) == 1
    assert db.get_scan_owned(done, "o") is None and db.get_scan_owned(queued, "o") and db.get_scan_owned(fresh, "o")


def test_stats_aggregates(db):
    empty = db.stats()
    assert empty["oldest_queued"] == 0 and empty["done_1h"] == 0 and empty["avg_duration"] == 0
    q = db.create_scan("q.zip", b"PK", ["secrets"], "o")
    age(db, q, created_at="2000-01-01T00:00:00+00:00")
    d = db.create_scan("d.zip", b"PK", ["secrets"], "o"); db.set_running(d); db.set_done(d, 90, {})
    f = db.create_scan("f.zip", b"PK", ["secrets"], "o"); db.set_failed(f, "x")
    st = db.stats()
    assert st["oldest_queued"] > 86400 * 365
    assert (st["done_1h"], st["failed_1h"]) == (1, 1) and 0 <= st["avg_duration"] < 5


def test_share_token_roundtrip(db):
    sid = db.create_scan("a.zip", b"PK", ["secrets"], "alice")
    assert db.share_scan(sid, "bob", "T" * 22) is None                      # not the owner
    assert db.share_scan(sid, "alice", "A" * 22) == "A" * 22
    assert db.share_scan(sid, "alice", "B" * 22) == "A" * 22                # idempotent
    assert db.get_shared("A" * 22)["status"] == "queued" and db.get_shared("X" * 22) is None
    assert db.unshare_scan(sid, "bob") is False and db.unshare_scan(sid, "alice") is True
    assert db.get_shared("A" * 22) is None


def test_api_key_lifecycle(db):
    with db._conn() as c:
        c.execute("DELETE FROM api_keys")
    assert db.resolve_key("unknown") is None                      # legacy / stand-alone key
    kid = db.create_key("alice", "h1", "ci", "ss_abcde", 2)
    assert db.resolve_key("h1") == {"owner": "alice", "revoked": False}
    assert db.create_key("alice", "h2", "x", "ss_x", 2)
    assert db.create_key("alice", "h3", "y", "ss_y", 2) is None   # limit of active keys
    assert [k["id"] for k in db.list_keys("bob")] == []
    assert not db.revoke_key(kid, "bob")
    assert db.revoke_key(kid, "alice")
    assert db.resolve_key("h1")["revoked"] is True
    assert db.create_key("alice", "h3", "y", "ss_y", 2)           # revoked key frees a slot


def test_migrations_idempotent_and_concurrent(db):
    """Several processes (API + worker) start at once: the advisory lock serialises them."""
    import subprocess
    import sys
    env = {**os.environ, "DATABASE_URL": URL}
    ps = [subprocess.Popen([sys.executable, "-c", "from app import db; db.init_db()"], env=env,
                           stderr=subprocess.PIPE, text=True) for _ in range(4)]
    assert [p.wait(timeout=60) for p in ps] == [0, 0, 0, 0], [p.stderr.read() for p in ps]
    with db._conn() as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()["version_num"] == "0002"
        assert c.execute("SELECT to_regclass('api_keys') IS NOT NULL AS ok").fetchone()["ok"]
