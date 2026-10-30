import os
import uuid
from datetime import datetime, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None
_pool_pid: int | None = None


def _conn():
    """Pooled connection (context manager; commits on success). One pool per process,
    so a forked RQ work horse never reuses its parent's sockets."""
    global _pool, _pool_pid
    if _pool is None or _pool_pid != os.getpid():
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=config.DB_POOL_MAX,
                               kwargs={"row_factory": dict_row}, timeout=10, open=True)
        _pool_pid = os.getpid()
    return _pool.connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                score INTEGER,
                result JSONB,
                error TEXT,
                upload BYTEA,
                created_at TEXT NOT NULL,
                finished_at TEXT)"""
        )
        c.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS scanners TEXT")
        c.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS owner TEXT")
        c.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS started_at TEXT")
        c.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0")
        c.execute("CREATE INDEX IF NOT EXISTS scans_owner_created ON scans (owner, created_at DESC)")


def create_scan(filename: str, upload: bytes, scanners: list[str], owner: str) -> str:
    scan_id = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO scans (id, filename, status, upload, scanners, owner, created_at) VALUES (%s,%s,'queued',%s,%s,%s,%s)",
            (scan_id, filename, upload, ",".join(scanners), owner, _now()),
        )
    return scan_id


def get_upload(scan_id: str) -> bytes | None:
    with _conn() as c:
        r = c.execute("SELECT upload FROM scans WHERE id=%s", (scan_id,)).fetchone()
    return bytes(r["upload"]) if r and r["upload"] else None


def clear_upload(scan_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE scans SET upload=NULL WHERE id=%s", (scan_id,))


def set_running(scan_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE scans SET status='running', started_at=%s, attempts=attempts+1 WHERE id=%s",
                  (_now(), scan_id))


def set_done(scan_id: str, score: int, result: dict) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE scans SET status='done', score=%s, result=%s, finished_at=%s WHERE id=%s",
            (score, Jsonb(result), _now(), scan_id),
        )


def set_failed(scan_id: str, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE scans SET status='failed', error=%s, finished_at=%s WHERE id=%s",
            (error[:500], _now(), scan_id),
        )


def unfinished_ids(min_age_sec: int = 60) -> list[str]:
    """Queued/running scans older than min_age_sec (avoids racing a request that is still enqueuing)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM scans WHERE status IN ('queued','running') "
            "AND created_at::timestamptz < now() - make_interval(secs => %s) ORDER BY created_at",
            (min_age_sec,),
        ).fetchall()
    return [r["id"] for r in rows]


def fail_exhausted(max_attempts: int, stuck_after_sec: int) -> int:
    """Stop retrying poison scans (e.g. an archive that keeps killing the worker).
    Only scans that are waiting, or dead (running too long), are failed; a scan in its
    last attempt that is still running is left alone."""
    with _conn() as c:
        return c.execute(
            "UPDATE scans SET status='failed', upload=NULL, finished_at=%s, "
            "error='gave up after repeated failures' WHERE attempts >= %s AND ("
            "status='queued' OR (status='running' "
            "AND started_at::timestamptz < now() - make_interval(secs => %s)))",
            (_now(), max_attempts, stuck_after_sec),
        ).rowcount


def reset_stuck(stuck_after_sec: int) -> int:
    """'running' for too long means the worker died: put the scan back to 'queued'."""
    with _conn() as c:
        return c.execute(
            "UPDATE scans SET status='queued' WHERE status='running' "
            "AND started_at::timestamptz < now() - make_interval(secs => %s)",
            (stuck_after_sec,),
        ).rowcount


def purge_old(days: int) -> int:
    with _conn() as c:
        return c.execute(
            "DELETE FROM scans WHERE status IN ('done','failed') "
            "AND created_at::timestamptz < now() - make_interval(days => %s)",
            (days,),
        ).rowcount


def count_by_status() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT status, COUNT(*) AS n FROM scans GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def get_scanners(scan_id: str) -> list[str]:
    with _conn() as c:
        r = c.execute("SELECT scanners FROM scans WHERE id=%s", (scan_id,)).fetchone()
    return [s for s in ((r or {}).get("scanners") or "secrets").split(",") if s]


def get_scan_owned(scan_id: str, owner: str) -> dict | None:
    with _conn() as c:
        return c.execute(
            "SELECT id, filename, status, score, result, error, scanners, created_at, finished_at "
            "FROM scans WHERE id=%s AND owner=%s", (scan_id, owner)
        ).fetchone()


def list_scans_owned(owner: str, limit: int, offset: int) -> list[dict]:
    with _conn() as c:
        return c.execute(
            "SELECT id, filename, status, score, scanners, created_at, finished_at "
            "FROM scans WHERE owner=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (owner, limit, offset),
        ).fetchall()


def delete_scan(scan_id: str, owner: str) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM scans WHERE id=%s AND owner=%s RETURNING id",
                         (scan_id, owner)).fetchone() is not None
