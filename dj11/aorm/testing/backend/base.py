"""A Django backend that runs the async ORM over the fake driver.

Django's sqlite3 backend builds the SQL and, on its sync connection, the
schema; the fake driver runs the async side. It exists so the contract suite
runs with no real async database installed.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Self

from django.db import connections
from django.db.backends.sqlite3.base import DatabaseWrapper as SQLiteWrapper
from django.db.backends.sqlite3.operations import DatabaseOperations as SQLiteOperations

from dj11.aorm.testing.driver import FakeConnection, FakeCursor, connect


class DatabaseOperations(SQLiteOperations):
    compiler_module = "dj11.aorm.testing.backend.compiler"


class DatabaseWrapper(SQLiteWrapper):
    ops_class = DatabaseOperations

    def __init__(self, settings_dict: dict[str, Any], alias: str = "default") -> None:
        super().__init__(settings_dict, alias)
        self._async_connection: FakeConnection | None = None
        self._async_tx_depth = 0

    @property
    def in_async_transaction(self) -> bool:
        return self._async_tx_depth > 0

    async def aensure_connection(self) -> FakeConnection:
        if self._async_connection is None:
            self._async_connection = await connect(str(self.settings_dict["NAME"]))
        return self._async_connection

    async def acursor(self) -> FakeCursor:
        return (await self.aensure_connection()).cursor()

    async def acommit(self) -> None:
        if not self._async_tx_depth:
            await (await self.aensure_connection()).commit()

    async def arollback(self) -> None:
        self._async_tx_depth = 0
        await (await self.aensure_connection()).rollback()

    @asynccontextmanager
    async def atransaction(self) -> AsyncIterator[Self]:
        outer = self._async_tx_depth == 0
        if outer:
            await self._aexecute("BEGIN")
        self._async_tx_depth += 1
        try:
            yield self
        except BaseException:
            self._async_tx_depth -= 1
            if outer:
                await self._aexecute("ROLLBACK")
            raise
        self._async_tx_depth -= 1
        if outer:
            await self._aexecute("COMMIT")

    async def _aexecute(self, sql: str) -> None:
        cursor = await self.acursor()
        try:
            await cursor.execute(sql)
        finally:
            await cursor.close()

    async def aclose(self) -> None:
        if self._async_connection is not None:
            await self._async_connection.close()
            self._async_connection = None
            self._async_tx_depth = 0


def settings_for(name: str) -> dict[str, Any]:
    """A complete settings dict for one fake database file."""
    engine = {"ENGINE": "dj11.aorm.testing.backend", "NAME": name}
    return connections.configure_settings({"default": engine})["default"]


__all__ = ["DatabaseOperations", "DatabaseWrapper", "settings_for"]
