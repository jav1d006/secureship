"""Redis/RQ queue. API calls enqueue(); the `rq worker scans` process runs process()."""
import logging
import shutil

from redis import Redis
from rq import Queue
from rq.job import Job

from . import config, db
from .safezip import UnsafeArchive, safe_extract
from .scanners import SCANNERS
from .scoring import overall_score

log = logging.getLogger("secureship.worker")


def _redis() -> Redis:
    return Redis.from_url(config.REDIS_URL)


def _queue() -> Queue:
    return Queue("scans", connection=_redis())


def enqueue(scan_id: str) -> None:
    _queue().enqueue(process, scan_id, job_id=scan_id, job_timeout=600,
                     result_ttl=0, failure_ttl=0)


def queue_len() -> int:
    return len(_queue())


def requeue_unfinished() -> None:
    """Redis keeps no data on restart; re-queue scans that are still unfinished in Postgres."""
    try:
        r = _redis()
        for sid in db.unfinished_ids():
            if not Job.exists(sid, connection=r):
                enqueue(sid)
    except Exception:
        log.exception("requeue failed")


def process(scan_id: str) -> None:
    scan_dir = config.WORK_DIR / scan_id
    try:
        data = db.get_upload(scan_id)
        if data is None:
            db.set_failed(scan_id, "upload missing")
            return
        db.set_running(scan_id)
        scan_dir.mkdir(parents=True, exist_ok=True)
        zip_path = scan_dir / "upload.zip"
        zip_path.write_bytes(data)
        safe_extract(zip_path, scan_dir / "src",
                     max_bytes=config.MAX_UNZIPPED_MB * 1024 * 1024,
                     max_files=config.MAX_FILES)
        results, errors = {}, {}
        for name in db.get_scanners(scan_id):
            fn = SCANNERS.get(name)
            if not fn:
                continue
            try:
                results[name] = fn(scan_dir / "src")
            except Exception as e:  # one scanner failing must not kill the others
                log.warning("scanner %s failed: %s", name, e)
                errors[name] = str(e)[:200]
        if not results:
            raise RuntimeError("; ".join(errors.values()) or "no scanners selected")
        score, per_module = overall_score(results)
        db.set_done(scan_id, score, {"modules": per_module, "errors": errors, **results})
        db.clear_upload(scan_id)
    except UnsafeArchive as e:
        db.set_failed(scan_id, f"rejected archive: {e}")
        db.clear_upload(scan_id)
    except Exception as e:
        log.exception("scan %s failed", scan_id)
        db.set_failed(scan_id, str(e))
        db.clear_upload(scan_id)
    finally:
        shutil.rmtree(scan_dir, ignore_errors=True)  # never keep user code
