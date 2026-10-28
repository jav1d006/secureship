import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import config


def _conn() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


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


def create_scan(filename: str, upload: bytes, scanners: list[str]) -> str:
    scan_id = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO scans (id, filename, status, upload, scanners, created_at) VALUES (%s,%s,'queued',%s,%s,%s)",
            (scan_id, filename, upload, ",".join(scanners), _now()),
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
        c.execute("UPDATE scans SET status='running' WHERE id=%s", (scan_id,))


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


def get_scan(scan_id: str) -> dict | None:
    with _conn() as c:
        return c.execute(
            "SELECT id, filename, status, score, result, error, scanners, created_at, finished_at "
            "FROM scans WHERE id=%s", (scan_id,)
        ).fetchone()


def list_scans(limit: int = 50) -> list[dict]:
    with _conn() as c:
        return c.execute(
            "SELECT id, filename, status, score, created_at, finished_at "
            "FROM scans ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()


def unfinished_ids() -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM scans WHERE status IN ('queued','running') ORDER BY created_at"
        ).fetchall()
    return [r["id"] for r in rows]


def count_by_status() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT status, COUNT(*) AS n FROM scans GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def get_scanners(scan_id: str) -> list[str]:
    with _conn() as c:
        r = c.execute("SELECT scanners FROM scans WHERE id=%s", (scan_id,)).fetchone()
    return [s for s in ((r or {}).get("scanners") or "secrets").split(",") if s]
