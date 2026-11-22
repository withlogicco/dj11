"""An awaitable driver over the standard library's sqlite3, for tests.

Each call runs on the caller's thread and then yields to the event loop
once, so the ORM meets a real suspension point. The connection refuses any
thread but the one that opened it, so work handed to another thread fails.
"""

import asyncio
import sqlite3
import threading
from collections.abc import Iterable
from typing import Any

from dj11.aorm.driver import Capabilities, Params


class FakeCursor:
    def __init__(self, connection: FakeConnection, cursor: Any) -> None:
        self._connection = connection
        self._cursor = cursor

    @property
    def description(self) -> Any:
        return self._cursor.description

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    async def execute(self, sql: str, params: Params = ()) -> FakeCursor:
        self._connection.check_thread()
        self._cursor.execute(sql, params)
        await asyncio.sleep(0)
        return self

    async def executemany(self, sql: str, params: Iterable[Params]) -> FakeCursor:
        self._connection.check_thread()
        self._cursor.executemany(sql, params)
        await asyncio.sleep(0)
        return self

    async def fetchone(self) -> Any:
        self._connection.check_thread()
        row = self._cursor.fetchone()
        await asyncio.sleep(0)
        return row

    async def fetchmany(self, size: int) -> list[Any]:
        self._connection.check_thread()
        rows = self._cursor.fetchmany(size)
        await asyncio.sleep(0)
        return rows

    async def close(self) -> None:
        self._cursor.close()


class FakeConnection:
    capabilities = Capabilities(
        caller_driven_async=True, uses_python_worker=False, supports_cancellation=False
    )

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db
        self.thread = threading.get_ident()

    def check_thread(self) -> None:
        if threading.get_ident() != self.thread:
            raise RuntimeError("the fake connection belongs to one thread")

    def cursor(self) -> FakeCursor:
        self.check_thread()
        return FakeCursor(self, self._db.cursor())

    async def commit(self) -> None:
        self.check_thread()
        self._db.commit()

    async def rollback(self) -> None:
        self.check_thread()
        self._db.rollback()

    async def close(self) -> None:
        self._db.close()


async def connect(name: str) -> FakeConnection:
    # Autocommit mode: `atransaction` issues BEGIN itself, as a native
    # driver's caller would.
    db = sqlite3.connect(name, isolation_level=None, check_same_thread=False)
    return FakeConnection(db)


__all__ = ["FakeConnection", "FakeCursor", "connect"]
