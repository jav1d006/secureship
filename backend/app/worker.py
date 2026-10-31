"""Redis/RQ queue. API calls enqueue(); the `rq worker scans` process runs process()."""
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from redis import Redis
from rq import Queue
from rq.job import Job

from . import config, db, jobs, logs
from .safezip import UnsafeArchive, safe_extract
from .scanners import GROUPS, SCANNERS, TAKES_INVENTORY, detect, trivy_config
from .scoring import overall_score

logs.setup()
log = logging.getLogger("secureship.worker")

_GATES = {"trivy": threading.Semaphore(1), "heavy": threading.Semaphore(max(1, config.HEAVY_CONCURRENCY))}
_ORDER = {"heavy": 0, "trivy": 1}      # start the slow groups first


def run_scanners(names: list[str], src) -> tuple[dict, dict, dict, dict]:
    """Run the selected scanners in parallel (they are separate processes, so threads are enough).
    Scanners with nothing to analyse in this project are skipped (Semgrep/Checkov cost seconds just to start);
    scanners of one resource group are serialised by a gate. One failing scanner never stops the others.
    Returns (results, errors, skipped, seconds per scanner)."""
    inv = detect.inventory(src)
    skipped, todo = {}, []
    for n in dict.fromkeys(names):
        if n not in SCANNERS:
            continue
        reason = detect.skip_reason(n, inv)
        if reason:
            skipped[n] = reason
        else:
            todo.append(n)

    def one(name):
        gate = _GATES.get(GROUPS.get(name))
        if gate:
            gate.acquire()
        started = time.perf_counter()        # waiting for the gate is not scanner time
        try:
            fn = SCANNERS[name]
            out = fn(src, inv) if name in TAKES_INVENTORY else fn(src)
            return name, out, None, time.perf_counter() - started
        except Exception as e:               # one scanner failing must not kill the others
            log.warning("scanner %s failed: %s", name, e)
            return name, None, str(e)[:200], time.perf_counter() - started
        finally:
            if gate:
                gate.release()

    ordered = sorted(todo, key=lambda n: _ORDER.get(GROUPS.get(n), 2))
    with ThreadPoolExecutor(max_workers=max(1, len(ordered))) as ex:
        done = list(ex.map(one, ordered))
    by_name = {n: (res, err, secs) for n, res, err, secs in done}
    results = {n: by_name[n][0] for n in todo if by_name[n][1] is None}
    errors = {n: by_name[n][1] for n in todo if by_name[n][1] is not None}
    timings = {n: round(by_name[n][2], 2) for n in todo}
    return results, errors, skipped, timings


def _redis() -> Redis:
    return Redis.from_url(config.REDIS_URL)


def _queue() -> Queue:
    return Queue("scans", connection=_redis())


def enqueue(scan_id: str) -> None:
    _queue().enqueue(process, scan_id, job_id=scan_id, job_timeout=600,
                     result_ttl=0, failure_ttl=0)


def queue_len() -> int:
    return len(_queue())


def maintain() -> dict:
    """Periodic housekeeping (run by the API): give up on poison scans, revive dead ones,
    re-queue scans Redis forgot, delete expired results."""
    failed = db.fail_exhausted(config.MAX_ATTEMPTS, config.STUCK_AFTER_SEC)
    revived = db.reset_stuck(config.STUCK_AFTER_SEC)
    requeue_unfinished()
    purged = db.purge_old(config.RETENTION_DAYS)
    if failed or revived or purged:
        log.info("maintenance: failed=%s revived=%s purged=%s", failed, revived, purged)
    return {"failed": failed, "revived": revived, "purged": purged}


def requeue_unfinished() -> None:
    """Redis keeps no data on restart; re-queue scans that are still unfinished in Postgres."""
    try:
        r = _redis()
        for sid in db.unfinished_ids():
            if not Job.exists(sid, connection=r):
                enqueue(sid)
    except Exception:
        log.exception("requeue failed")


def harden_tree(root) -> None:
    """Defence in depth: no symlinks, no exec/setuid bits, owner-only permissions."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                os.unlink(p)
        os.chmod(dirpath, 0o700)
        for name in filenames:
            p = os.path.join(dirpath, name)
            if os.path.isfile(p) and not os.path.islink(p):
                os.chmod(p, 0o600)


def process(scan_id: str) -> None:
    os.umask(0o077)
    use_job = config.SANDBOX_MODE == "job"
    scan_dir = (config.SANDBOX_WORK_DIR if use_job else config.WORK_DIR) / scan_id
    try:
        data = db.get_upload(scan_id)
        if data is None:
            db.set_failed(scan_id, "upload missing")
            return
        db.set_running(scan_id)
        scan_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        zip_path = scan_dir / "upload.zip"
        zip_path.write_bytes(data)
        safe_extract(zip_path, scan_dir / "src",
                     max_bytes=config.MAX_UNZIPPED_MB * 1024 * 1024,
                     max_files=config.MAX_FILES)
        harden_tree(scan_dir / "src")
        names = db.get_scanners(scan_id)
        if use_job:
            results, errors, skipped, timings = jobs.run_in_job(scan_id, names, scan_dir)
        else:
            results, errors, skipped, timings = run_scanners(names, scan_dir / "src")
        if not results:
            why = "; ".join(errors.values()) or "; ".join(f"{k}: {v}" for k, v in skipped.items())
            raise RuntimeError(f"nothing was analysed ({why or 'no scanners selected'})")
        # Skipped scanners (nothing to analyse) do not count towards the score.
        score, per_module = overall_score(results)
        log.info("scan %s done in %.1fs: %s skipped=%s", scan_id, sum(timings.values()), timings, list(skipped))
        db.set_done(scan_id, score, {"modules": per_module, "errors": errors, "skipped": skipped,
                                     "timings": timings, **results})
        db.clear_upload(scan_id)
    except UnsafeArchive as e:
        db.set_failed(scan_id, f"rejected archive: {e}")
        db.clear_upload(scan_id)
    except Exception as e:
        log.exception("scan %s failed", scan_id)
        db.set_failed(scan_id, str(e))
        db.clear_upload(scan_id)
    finally:
        trivy_config.forget(scan_dir / "src")
        shutil.rmtree(scan_dir, ignore_errors=True)  # never keep user code
