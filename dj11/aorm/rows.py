"""Chunked row streams and Django field conversion."""

from collections.abc import AsyncIterator
from typing import Any


class AsyncRows:
    """Fetch rows in chunks without materializing the result set."""

    def __init__(self, cursor: Any, chunk_size: int) -> None:
        self.cursor = cursor
        self.chunk_size = chunk_size

    def __aiter__(self) -> AsyncIterator[list[Any]]:
        return self._rows()

    async def _rows(self) -> AsyncIterator[list[Any]]:
        while True:
            rows = await self.cursor.fetchmany(self.chunk_size)
            if not rows:
                return
            yield rows


class EmptyCursor:
    """Stand in for a cursor when Django proves a query returns no rows."""

    async def fetchmany(self, size: int) -> list[Any]:
        return []

    async def close(self) -> None:
        return None


async def fetch_all(cursor: Any) -> list[Any]:
    rows = []
    while chunk := await cursor.fetchmany(2000):
        rows.extend(chunk)
    return rows


async def close_rows(rows: Any) -> None:
    if (cursor := getattr(rows, "cursor", None)) is not None:
        await cursor.close()


def convert(rows: list[Any], converters: dict, connection: Any) -> list[Any]:
    converted = []
    for row in rows:
        values = list(row)
        for pos, (funcs, expression) in converters.items():
            for converter in funcs:
                values[pos] = converter(values[pos], expression, connection)
        converted.append(values)
    return converted


__all__ = ["AsyncRows", "EmptyCursor", "close_rows", "convert", "fetch_all"]
