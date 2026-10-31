"""Entrypoint of the scan worker: python -m app.run_worker"""
import logging

from redis import Redis
from rq import Queue, Worker

from . import config


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:        # copy the Trivy DB out of the image now, not during the first user's scan
        from .scanners import trivy
        trivy._ensure_cache()
    except Exception as e:
        logging.getLogger("secureship.worker").warning("trivy cache warm-up skipped: %s", e)
    if config.SANDBOX_MODE == "job":
        from . import jobs
        jobs.sweep()
    conn = Redis.from_url(config.REDIS_URL)
    Worker([Queue("scans", connection=conn)], connection=conn).work()


if __name__ == "__main__":
    main()
