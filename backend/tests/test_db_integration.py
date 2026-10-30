"""Needs a real PostgreSQL: set TEST_DATABASE_URL (CI provides a service container)."""
import os

import pytest

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def db(monkeypatch):
    from app import config, db as dbmod
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
