"""Awaitable DB-API shapes a backend must supply to the async ORM.

`AsyncConnection` and `AsyncCursor` describe the driver. `AsyncDatabase`
describes the Django `DatabaseWrapper` methods the async compiler calls.
Storage actions a driver adds, such as compaction, belong to that backend's
own protocol, not to this contract.
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

type Params = Sequence[Any] | Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Capabilities:
    """How a driver runs I/O, independent of the database it talks to."""

    caller_driven_async: bool
    uses_python_worker: bool
    supports_cancellation: bool


class AsyncCursor(Protocol):
    description: tuple[tuple[Any, ...], ...] | None
    rowcount: int
    lastrowid: int | None

    async def execute(self, sql: str, params: Params = ()) -> Any: ...

    async def executemany(self, sql: str, params: Iterable[Params]) -> Any: ...

    async def fetchone(self) -> Any: ...

    async def fetchmany(self, size: int) -> list[Any]: ...

    async def close(self) -> Any: ...


class AsyncConnection(Protocol):
    capabilities: Capabilities

    def cursor(self) -> AsyncCursor: ...

    async def commit(self) -> Any: ...

    async def rollback(self) -> Any: ...

    async def close(self) -> Any: ...


class AsyncDatabase(Protocol):
    """The async half of a Django `DatabaseWrapper`.

    `acommit` must do nothing while `in_async_transaction` is true; the
    compiler still calls it after each write outside a transaction.
    """

    @property
    def in_async_transaction(self) -> bool: ...

    async def acursor(self) -> AsyncCursor: ...

    async def aread_cursor(self) -> AsyncCursor: ...

    async def acommit(self) -> None: ...

    async def arollback(self) -> None: ...

    def atransaction(self) -> AbstractAsyncContextManager[Any]: ...

    async def aclose(self) -> None: ...


type Connect = Callable[..., Awaitable[AsyncConnection]]


__all__ = [
    "AsyncConnection",
    "AsyncCursor",
    "AsyncDatabase",
    "Capabilities",
    "Connect",
    "Params",
]
