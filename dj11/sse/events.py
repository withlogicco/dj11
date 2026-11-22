from collections.abc import AsyncIterable
from dataclasses import dataclass

type JSONValue = (
    None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
)


@dataclass(frozen=True, slots=True)
class ServerSentEvent:
    data: JSONValue = None
    event: str | None = None
    id: str | int | None = None
    comment: str | None = None


ServerSentEventStream = AsyncIterable[ServerSentEvent]
