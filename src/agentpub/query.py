"""Query helpers that work on both asyncpg Pool/Connection and aiosqlite Connection.

Unified asyncpg-style API:
  await q.fetchrow(conn, sql, *args) -> dict | None
  await q.fetch(conn, sql, *args)    -> list[dict]
  await q.fetchval(conn, sql, *args) -> Any | None
  await q.execute(conn, sql, *args)  -> None

Postgres-style $1, $2 placeholders work in Postgres; on SQLite they're
translated to ? before execution.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import aiosqlite


_PLACEHOLDER_RE = re.compile(r"\$\d+")


def _is_sqlite(conn) -> bool:
    return isinstance(conn, aiosqlite.Connection)


def _adapt(conn, sql: str) -> str:
    if _is_sqlite(conn):
        return _PLACEHOLDER_RE.sub("?", sql)
    return sql


def _row_to_dict(cur, row) -> dict:
    """Convert a single row (sqlite tuple or asyncpg Record) to a dict."""
    if row is None:
        return None
    if hasattr(row, "keys"):
        # asyncpg Record / sqlite3.Row
        return dict(row)
    # aiosqlite row is a plain tuple — use cursor description
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def fetchrow(conn, sql: str, *args) -> Optional[dict]:
    s = _adapt(conn, sql)
    if _is_sqlite(conn):
        async with conn.execute(s, args) as cur:
            row = await cur.fetchone()
        return _row_to_dict(cur, row)
    return await conn.fetchrow(s, *args)


async def fetch(conn, sql: str, *args) -> list[dict]:
    s = _adapt(conn, sql)
    if _is_sqlite(conn):
        async with conn.execute(s, args) as cur:
            rows = await cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    rows = await conn.fetch(s, *args)
    return [dict(r) for r in rows]


async def fetchval(conn, sql: str, *args) -> Any:
    s = _adapt(conn, sql)
    if _is_sqlite(conn):
        async with conn.execute(s, args) as cur:
            row = await cur.fetchone()
        return row[0] if row else None
    return await conn.fetchval(s, *args)


async def execute(conn, sql: str, *args) -> None:
    s = _adapt(conn, sql)
    if _is_sqlite(conn):
        await conn.execute(s, args)
        await conn.commit()
    else:
        await conn.execute(s, *args)


async def executemany(conn, sql: str, args_seq) -> None:
    s = _adapt(conn, sql)
    if _is_sqlite(conn):
        await conn.executemany(s, args_seq)
        await conn.commit()
    else:
        await conn.executemany(s, args_seq)