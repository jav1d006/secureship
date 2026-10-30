import asyncio
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from . import config, db, export, worker
from .scanners import META, SCANNERS
from .security import client_ip, hit, limit_reads, limit_scans, new_token

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("secureship.api")

SCAN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHARE_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
QUEUE_LEN = Gauge("secureship_queue_length", "Scans waiting in queue")
SCANS = Gauge("secureship_scans", "Scans by status", ["status"])
DEP_UP = Gauge("secureship_dependency_up", "1 if the dependency answered", ["dependency"])
OLDEST_QUEUED = Gauge("secureship_oldest_queued_seconds", "Age of the oldest queued scan")
FINISHED_1H = Gauge("secureship_scans_finished_last_hour", "Scans finished in the last hour", ["status"])
SCAN_SECONDS = Gauge("secureship_scan_duration_seconds_avg", "Average duration of scans finished in the last hour")
SCANNER_SECONDS = Gauge("secureship_scanner_duration_seconds_avg", "Average seconds per scanner, last hour", ["scanner"])
HTTP_REQS = Counter("secureship_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LAT = Histogram("secureship_http_request_seconds", "HTTP request latency", ["route"])
MAX_BODY = config.MAX_UPLOAD_MB * 1024 * 1024 + 1024 * 1024


async def _maintenance_loop() -> None:
    while True:
        await asyncio.sleep(config.MAINTENANCE_INTERVAL_SEC)
        try:
            await asyncio.to_thread(worker.maintain)
        except Exception:
            log.exception("maintenance failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    worker.requeue_unfinished()
    task = asyncio.create_task(_maintenance_loop())
    yield
    task.cancel()


app = FastAPI(title="SecureShip API", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def harden(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY:
        return JSONResponse({"detail": "request too large"}, status_code=413)
    started = time.perf_counter()
    resp = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "unmatched")
    if route != "/metrics":
        HTTP_REQS.labels(request.method, route, str(resp.status_code)).inc()
        HTTP_LAT.labels(route).observe(time.perf_counter() - started)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith("/api/docs"):
        resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/v1/badge/"):
        resp.headers["Cache-Control"] = "public, max-age=300"
    elif request.url.path.startswith("/api/v1"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    try:
        db.count_by_status()
        worker.queue_len()
    except Exception:
        raise HTTPException(503, "not ready")
    return {"status": "ready"}


@app.get("/metrics")
def metrics():
    """Never fails: a broken dependency shows up as secureship_dependency_up 0, not as a 500."""
    try:
        QUEUE_LEN.set(worker.queue_len())
        DEP_UP.labels("redis").set(1)
    except Exception:
        DEP_UP.labels("redis").set(0)
    try:
        counts = {k: 0 for k in ("queued", "running", "done", "failed")} | db.count_by_status()
        for k, n in counts.items():
            SCANS.labels(k).set(n)
        st = db.stats()
        OLDEST_QUEUED.set(st["oldest_queued"])
        FINISHED_1H.labels("done").set(st["done_1h"])
        FINISHED_1H.labels("failed").set(st["failed_1h"])
        SCAN_SECONDS.set(st["avg_duration"])
        SCANNER_SECONDS.clear()
        for r in db.scanner_durations():
            SCANNER_SECONDS.labels(r["scanner"]).set(r["avg"])
        DEP_UP.labels("postgres").set(1)
    except Exception:
        DEP_UP.labels("postgres").set(0)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


v1 = APIRouter(prefix="/api/v1")


@v1.get("/scanners")
def scanners_catalog(_: str = Depends(limit_reads)):
    return META


@v1.post("/keys", status_code=201)
def create_key(request: Request):
    hit(f"rl:k:{client_ip(request)}", 5, 3600)
    return {"api_key": new_token(),
            "usage": "Send it as the X-API-Key header. Store it safely; it is not shown again."}


@v1.post("/scans", status_code=202)
async def create_scan(file: UploadFile = File(...), scanners: str = Form("secrets"),
                      who: str = Depends(limit_scans)):
    name = re.sub(r"[^\w.\- ]", "_", (file.filename or "upload.zip"))[:200]
    if not name.lower().endswith(".zip"):
        raise HTTPException(400, "only .zip uploads are supported")
    selected = [s for s in dict.fromkeys(x.strip() for x in scanners.split(",")) if s]
    if not selected or any(s not in SCANNERS for s in selected):
        raise HTTPException(400, "unknown or no scanner selected")
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"file exceeds {config.MAX_UPLOAD_MB} MB")
    if not data.startswith(b"PK\x03\x04"):
        raise HTTPException(400, "file is not a valid zip archive")
    try:
        if worker.queue_len() >= config.MAX_QUEUE:
            raise HTTPException(503, "scan queue is full, try again shortly")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "service temporarily unavailable")
    scan_id = db.create_scan(name, data, selected, who)
    worker.enqueue(scan_id)
    return {"id": scan_id, "status": "queued"}


@v1.get("/scans")
def list_scans(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
               who: str = Depends(limit_reads)):
    return db.list_scans_owned(who, limit, offset)


@v1.get("/scans/{scan_id}")
def get_scan(scan_id: str, who: str = Depends(limit_reads)):
    scan = db.get_scan_owned(scan_id, who) if SCAN_ID_RE.match(scan_id) else None
    if not scan:
        raise HTTPException(404, "scan not found")
    return scan


@v1.delete("/scans/{scan_id}", status_code=204)
def delete_scan(scan_id: str, who: str = Depends(limit_reads)):
    if not SCAN_ID_RE.match(scan_id) or not db.delete_scan(scan_id, who):
        raise HTTPException(404, "scan not found")
    return Response(status_code=204)


def _owned(scan_id: str, who: str) -> dict:
    scan = db.get_scan_owned(scan_id, who) if SCAN_ID_RE.match(scan_id) else None
    if not scan:
        raise HTTPException(404, "scan not found")
    return scan


@v1.get("/scans/{scan_id}/export")
def export_scan(scan_id: str, format: str = Query("sarif", pattern="^(sarif|json|csv)$"),
                who: str = Depends(limit_reads)):
    scan = _owned(scan_id, who)
    if scan["status"] != "done":
        raise HTTPException(409, "scan is not finished")
    if format == "sarif":
        return JSONResponse(export.to_sarif(scan), media_type="application/sarif+json",
                            headers={"Content-Disposition": f'attachment; filename="secureship-{scan_id[:8]}.sarif"'})
    if format == "csv":
        return PlainTextResponse(export.to_csv(scan), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="secureship-{scan_id[:8]}.csv"'})
    return scan


@v1.post("/scans/{scan_id}/share")
def share_scan(scan_id: str, who: str = Depends(limit_reads)):
    """Public score badge for a scan (shows only the score). Revoke with DELETE."""
    _owned(scan_id, who)
    token = db.share_scan(scan_id, who, secrets.token_urlsafe(16))
    return {"badge_url": f"/api/v1/badge/{token}.svg",
            "markdown": f"![security](/api/v1/badge/{token}.svg)"}


@v1.delete("/scans/{scan_id}/share", status_code=204)
def unshare_scan(scan_id: str, who: str = Depends(limit_reads)):
    if not SCAN_ID_RE.match(scan_id) or not db.unshare_scan(scan_id, who):
        raise HTTPException(404, "scan not found")
    return Response(status_code=204)


@app.get("/api/v1/badge/{token}.svg")
def badge(token: str, request: Request):
    hit(f"rl:b:{client_ip(request)}", 120, 60)
    row = db.get_shared(token) if SHARE_RE.match(token) else None
    if not row:
        raise HTTPException(404, "badge not found")
    return Response(export.badge_svg(row["status"], row["score"]), media_type="image/svg+xml")


app.include_router(v1)
