"""Async execution over Django's own SQL compilers.

Django still builds every statement. These classes only add awaitable
execution through the connection's `AsyncDatabase` methods. A backend whose
driver takes Django's `%s` placeholders can name this module as its
`compiler_module`; one that needs another style overrides `async_sql`.
"""

from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from django.core.exceptions import EmptyResultSet
from django.db.models.sql import compiler
from django.db.models.sql import constants as sql_constants

from dj11.aorm.rows import AsyncRows, EmptyCursor, convert, fetch_all

type Statement = tuple[str, Any]


class AsyncSQL:
    """The hook a backend overrides to match its driver's placeholders."""

    def async_sql(self, sql: str) -> str:
        return sql


class AsyncSelect(AsyncSQL):
    async def aexecute_sql(
        self,
        result_type=sql_constants.MULTI,
        chunked_fetch=False,
        chunk_size=100,
    ) -> Any:
        result_type = result_type or sql_constants.NO_RESULTS
        try:
            sql, params = self.as_sql()
        except EmptyResultSet:
            if result_type == sql_constants.MULTI:
                return AsyncRows(EmptyCursor(), chunk_size)
            return None
        open_cursor = getattr(self.connection, "aread_cursor", self.connection.acursor)
        cursor = await open_cursor()
        try:
            await cursor.execute(self.async_sql(sql), params)
        except BaseException:
            await cursor.close()
            raise
        return await _result(cursor, result_type, chunk_size)

    async def aresults_iter(self, chunk_size: int = 100) -> AsyncIterator[list[Any]]:
        rows = await self.aexecute_sql(sql_constants.MULTI, chunk_size=chunk_size)
        fields = [item[0] for item in self.select[: self.col_count]]
        converters = self.get_converters(fields)
        async for chunk in rows:
            yield convert(chunk, converters, self.connection)


class AsyncInsert(AsyncSQL):
    def insert_statements(self, returning_fields: list | None) -> list[Statement]:
        """The statements one insert runs; a backend may reuse cached SQL."""
        self.returning_fields = returning_fields
        return self.as_sql()

    async def aexecute_sql(self, returning_fields=None) -> list[Any]:
        statements = self.insert_statements(returning_fields)
        _, returned = await awrite(
            self.connection, statements, self.async_sql, bool(returning_fields)
        )
        return returned


class AsyncWrite(AsyncSQL):
    async def aexecute_sql(self, result_type=sql_constants.ROW_COUNT) -> int:
        statements = self.as_sql()
        if isinstance(statements, tuple):
            statements = [statements]
        count, _ = await awrite(self.connection, statements, self.async_sql)
        return count if result_type == sql_constants.ROW_COUNT else 0


async def awrite(
    connection: Any,
    statements: Iterable[Statement],
    adapt: Callable[[str], str],
    returning: bool = False,
) -> tuple[int, list[Any]]:
    """Run writes on one cursor and commit unless a transaction owns them."""
    cursor = await connection.acursor()
    try:
        for sql, params in statements:
            await cursor.execute(adapt(sql), params)
        returned = await fetch_all(cursor) if returning else []
        if not getattr(connection, "in_async_transaction", False):
            await connection.acommit()
        return cursor.rowcount, returned
    finally:
        await cursor.close()


async def _result(cursor: Any, result_type: str, chunk_size: int) -> Any:
    match result_type:
        case sql_constants.ROW_COUNT:
            count = cursor.rowcount
            await cursor.close()
            return count
        case sql_constants.CURSOR:
            return cursor
        case sql_constants.SINGLE:
            row = await cursor.fetchone()
            await cursor.close()
            return row
        case sql_constants.MULTI:
            return AsyncRows(cursor, chunk_size)
        case _:
            await cursor.close()
            return []


class SQLCompiler(AsyncSelect, compiler.SQLCompiler):
    """Django's SELECT compiler with awaitable execution."""


class SQLInsertCompiler(AsyncInsert, compiler.SQLInsertCompiler):
    """Django's INSERT compiler with awaitable execution."""


class SQLUpdateCompiler(AsyncWrite, compiler.SQLUpdateCompiler):
    """Django's UPDATE compiler with awaitable execution."""


class SQLDeleteCompiler(AsyncWrite, compiler.SQLDeleteCompiler):
    """Django's DELETE compiler with awaitable execution."""


class SQLAggregateCompiler(AsyncSelect, compiler.SQLAggregateCompiler):
    """Django's aggregate-over-subquery compiler with awaitable execution."""


__all__ = [
    "AsyncInsert",
    "AsyncSQL",
    "AsyncSelect",
    "AsyncWrite",
    "SQLAggregateCompiler",
    "SQLCompiler",
    "SQLDeleteCompiler",
    "SQLInsertCompiler",
    "SQLUpdateCompiler",
    "awrite",
]
