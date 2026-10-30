"""Entrypoint of the scan worker: python -m app.run_worker"""
from redis import Redis
from rq import Queue, Worker

from . import config


def main() -> None:
    conn = Redis.from_url(config.REDIS_URL)
    Worker([Queue("scans", connection=conn)], connection=conn).work()


if __name__ == "__main__":
    main()
