"""Alembic environment: online migrations only, serialised by an advisory lock so that the
API and the worker can both start (and call init_db) at the same time."""
from alembic import context
from sqlalchemy import create_engine, text

LOCK_ID = 727274


def run() -> None:
    url = context.config.attributes["url"].replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, poolclass=None)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            conn.execute(text(f"SELECT pg_advisory_xact_lock({LOCK_ID})"))
            context.run_migrations()
    engine.dispose()


run()
