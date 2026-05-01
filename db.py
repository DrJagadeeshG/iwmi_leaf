"""
Postgres connection pool and helpers for LEAF DSS.

Uses DATABASE_URL from the environment (loaded by python-dotenv at app start).
A small ThreadedConnectionPool is sized for typical Render dyno concurrency.
"""

import os
from contextlib import contextmanager
from threading import Lock

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

_pool: ThreadedConnectionPool | None = None
_pool_lock = Lock()


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL is not set; cannot use Postgres backend")
            _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=url)
    return _pool


@contextmanager
def get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit: bool = False, dict_rows: bool = True):
    """Acquire a cursor from a pooled connection. Set `commit=True` for writes."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor) if dict_rows else conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def is_configured() -> bool:
    return bool(os.environ.get("DATABASE_URL"))
