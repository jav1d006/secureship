import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock, _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,           -- queued | running | done | failed
                score INTEGER,
                result TEXT,                    -- JSON
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_scan(filename: str) -> str:
    scan_id = uuid.uuid4().hex
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO scans (id, filename, status, created_at) VALUES (?, ?, 'queued', ?)",
            (scan_id, filename, _now()),
        )
    return scan_id


def set_running(scan_id: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE scans SET status='running' WHERE id=?", (scan_id,))


def set_done(scan_id: str, score: int, result: dict) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE scans SET status='done', score=?, result=?, finished_at=? WHERE id=?",
            (score, json.dumps(result), _now(), scan_id),
        )


def set_failed(scan_id: str, error: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE scans SET status='failed', error=?, finished_at=? WHERE id=?",
            (error[:500], _now(), scan_id),
        )


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    if d.get("result"):
        d["result"] = json.loads(d["result"])
    return d


def get_scan(scan_id: str) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    return _row(r) if r else None


def list_scans(limit: int = 50) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, filename, status, score, created_at, finished_at "
            "FROM scans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def unfinished_ids() -> list[str]:
    """Scans interrupted by a restart; the worker re-queues them on startup."""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id FROM scans WHERE status IN ('queued','running') ORDER BY created_at"
        ).fetchall()
    return [r["id"] for r in rows]
