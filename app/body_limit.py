"""Refuse request bodies over a size limit before the app reads them (413), so one request cannot fill memory.

Checks Content-Length up front; also counts bytes as they arrive, for requests without that header.
"""

import json
from typing import Any, Awaitable, Callable

MAX_BODY_BYTES = 14 * 1024 * 1024   # a 10 MB upload is about 13.4 MB as base64 in JSON


class BodyLimit:
    def __init__(self, app: Any, max_bytes: int = MAX_BODY_BYTES):
        self.app, self.max_bytes = app, max_bytes

    async def _refuse(self, send: Callable[[dict], Awaitable[None]]) -> None:
        body = json.dumps({"detail": f"Request too large (max {self.max_bytes // (1024 * 1024)} MB)"}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            return await self._refuse(send)
        received, started, too_large = 0, False, False

        async def counted() -> dict:
            # Past the limit, the app is told the client went away, so it stops reading; its own answer to that
            # (FastAPI turns body errors into 400) is dropped below and the client gets the 413 instead.
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def tracked(message: dict) -> None:
            nonlocal started
            if too_large:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counted, tracked)
        except Exception:
            if not too_large:
                raise
        if too_large and not started:
            await self._refuse(send)
