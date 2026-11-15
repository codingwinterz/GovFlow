"""Call an ASGI app in-process (no sockets, no httpx dependency).

The event loop is created once at import, during test collection and before conftest's
network guard starts. On Windows the Proactor loop's internal wake-up pipe is a loopback
socket pair, which the guard would otherwise block. All outward connections stay blocked.
"""

import asyncio
import json
from typing import Any, Optional

_LOOP = asyncio.new_event_loop()


def call(app: Any, method: str, path: str, body: Any = None,
         headers: Optional[dict[str, str]] = None) -> tuple[int, Any]:
    path, _, query = path.partition("?")
    raw = json.dumps(body).encode() if body is not None else b""
    hdrs = [(b"content-type", b"application/json")]
    hdrs += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode(),
             "root_path": "", "headers": hdrs, "client": ("test", 1), "server": ("test", 80)}
    messages: list[dict] = []
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.sleep(3600)   # never disconnect mid-request
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    _LOOP.run_until_complete(app(scope, receive, send))
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    data = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, (json.loads(data) if data else None)
