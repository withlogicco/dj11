import json
from collections.abc import AsyncIterator

from .events import JSONValue, ServerSentEvent, ServerSentEventStream


def _field_lines(prefix: str, value: str | int | None) -> list[str]:
    if value is None:
        return []
    text = str(value)
    if "\r" in text or "\n" in text:
        raise ValueError("SSE field values cannot contain line breaks")
    return [f"{prefix}: {text}"]


def _data_text(data: JSONValue) -> str:
    return data if isinstance(data, str) else json.dumps(data)


def _data_lines(data: JSONValue) -> list[str]:
    text = _data_text(data).replace("\r\n", "\n").replace("\r", "\n")
    return [f"data: {line}" for line in text.split("\n")]


def encode_event(event: ServerSentEvent) -> bytes:
    lines = _field_lines("id", event.id) + _field_lines("event", event.event)
    if event.data is not None:
        lines += _data_lines(event.data)
    lines += _field_lines("", event.comment)
    return ("\n".join(lines) + "\n\n").encode("utf-8")


async def encode_events(events: ServerSentEventStream) -> AsyncIterator[bytes]:
    async for event in events:
        yield encode_event(event)
