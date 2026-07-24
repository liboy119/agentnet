"""Database connection + schema bootstrap for AgentPub.

Supports two backends:
- Postgres (default; recommended for production)
- SQLite (zero-setup, good for dev / single-host)

Detection: SQLite if DATABASE_URL starts with "sqlite://".
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Optional

_pool = None
_sqlite_conn = None

# Convert asyncpg-style $1, $2 placeholders to SQLite ? for the same SQL.
_PLACEHOLDER_RE = re.compile(r"\$\d+")


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite://")


def _default_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "sqlite:///./agentpub.db",
    )


def adapt_sql(sql: str) -> str:
    """Translate Postgres-style $N placeholders to SQLite ? placeholders."""
    if not is_sqlite():
        return sql
    return _PLACEHOLDER_RE.sub("?", sql)


async def init_pool(database_url: Optional[str] = None):
    """Initialize the global async connection. For SQLite, the file is created if needed.
    Call apply_schema() once after this.
    """
    global _pool, _sqlite_conn
    url = database_url or _default_database_url()
    if _pool is not None or _sqlite_conn is not None:
        return _pool or _sqlite_conn

    if _is_sqlite(url):
        # Make sure parent dir exists. Path is everything after "sqlite://".
        path = url[len("sqlite://"):]
        if path.startswith("/") and not path.startswith("/./"):
            path = path.lstrip("/")
        elif path.startswith("/./"):
            path = "." + path[2:]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Initialize schema via sync sqlite3 BEFORE opening async pool
        # (avoid "database is locked" from aiosqlite + sync sqlite3 racing)
        await _init_sqlite_schema(path)
        import aiosqlite
        _sqlite_conn = await aiosqlite.connect(path)
        await _sqlite_conn.execute("PRAGMA foreign_keys = ON")
        await _sqlite_conn.execute("PRAGMA journal_mode = WAL")
        return _sqlite_conn
    else:
        import asyncpg
        _pool = await asyncpg.create_pool(url, min_size=2, max_size=10, command_timeout=30)
        return _pool


async def _init_sqlite_schema(path: str) -> None:
    """Sync sqlite3 schema bootstrap (one-time, runs before async pool)."""
    repo_root = Path(__file__).parent.parent.parent
    schema_file = repo_root / "sql" / "schema.sqlite.sql"
    sql = schema_file.read_text(encoding="utf-8")
    import sqlite3
    sync_conn = sqlite3.connect(path)
    try:
        sync_conn.executescript(sql)
        sync_conn.commit()
    finally:
        sync_conn.close()


def get_pool():
    if _pool is None and _sqlite_conn is None:
        raise RuntimeError("Database not initialized - call init_pool() first")
    return _pool or _sqlite_conn


def is_sqlite() -> bool:
    return _sqlite_conn is not None


@contextlib.asynccontextmanager
async def acquire():
    """Acquire a connection from the pool (Postgres) or yield the single
    connection (SQLite). Use this in route handlers instead of pool.acquire().
    """
    if is_sqlite():
        yield _sqlite_conn
    else:
        async with _pool.acquire() as conn:
            yield conn


async def close_pool() -> None:
    global _pool, _sqlite_conn
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _sqlite_conn is not None:
        await _sqlite_conn.close()
        _sqlite_conn = None


async def apply_schema() -> None:
    """Run SQL migrations.

    SQLite: schema is auto-applied during init_pool() - this is a no-op.
    Postgres: runs all files in sql/migrations/*.sql in order.
    """
    if is_sqlite():
        return  # already done in init_pool

    repo_root = Path(__file__).parent.parent.parent
    migrations_dir = repo_root / "sql" / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    pool = get_pool()
    async with pool.acquire() as c:
        for f in files:
            sql = f.read_text(encoding="utf-8")
            await c.execute(sql)