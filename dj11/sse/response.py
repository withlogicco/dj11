from django.http import StreamingHttpResponse

from .encode import encode_events
from .events import ServerSentEventStream


class ServerSentEventsResponse(StreamingHttpResponse):
    def __init__(self, events: ServerSentEventStream) -> None:
        self._events = events
        super().__init__(encode_events(events), content_type="text/event-stream")
        self["Cache-Control"] = "no-cache"
        self["X-Accel-Buffering"] = "no"

    def close(self) -> None:
        if close := getattr(self._events, "close", None):
            close()
        super().close()
