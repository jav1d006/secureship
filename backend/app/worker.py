"""In-process worker: one thread, one scan at a time (keeps RAM low).
Swap for Redis/RQ later without touching the API."""
import logging
import queue
import shutil
import threading
import time

from prometheus_client import Counter, Gauge, Histogram

from . import config, db
from .safezip import UnsafeArchive, safe_extract
from .scanners import SCANNERS
from .scoring import overall_score

log = logging.getLogger("secureship.worker")

SCANS_TOTAL = Counter("secureship_scans_total", "Finished scans", ["status"])
SCAN_SECONDS = Histogram("secureship_scan_duration_seconds", "Scan duration")
QUEUE_LEN = Gauge("secureship_queue_length", "Scans waiting in queue")

_q: "queue.Queue[str]" = queue.Queue()
_started = False


def enqueue(scan_id: str) -> None:
    _q.put(scan_id)
    QUEUE_LEN.set(_q.qsize())


def _process(scan_id: str) -> None:
    scan_dir = config.WORK_DIR / scan_id
    zip_path = scan_dir / "upload.zip"
    src_dir = scan_dir / "src"
    start = time.monotonic()
    db.set_running(scan_id)
    try:
        safe_extract(
            zip_path, src_dir,
            max_bytes=config.MAX_UNZIPPED_MB * 1024 * 1024,
            max_files=config.MAX_FILES,
        )
        results = {name: run(src_dir) for name, run in SCANNERS.items()}
        score, per_module = overall_score(results)
        db.set_done(scan_id, score, {"modules": per_module, **results})
        SCANS_TOTAL.labels("done").inc()
    except UnsafeArchive as e:
        db.set_failed(scan_id, f"rejected archive: {e}")
        SCANS_TOTAL.labels("failed").inc()
    except Exception as e:  # scanner crash, timeout, ...
        log.exception("scan %s failed", scan_id)
        db.set_failed(scan_id, str(e))
        SCANS_TOTAL.labels("failed").inc()
    finally:
        SCAN_SECONDS.observe(time.monotonic() - start)
        shutil.rmtree(scan_dir, ignore_errors=True)  # never keep user code


def _loop() -> None:
    while True:
        scan_id = _q.get()
        QUEUE_LEN.set(_q.qsize())
        _process(scan_id)


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    for scan_id in db.unfinished_ids():
        if (config.WORK_DIR / scan_id / "upload.zip").exists():
            enqueue(scan_id)
        else:
            db.set_failed(scan_id, "interrupted by restart")
    threading.Thread(target=_loop, name="scan-worker", daemon=True).start()
