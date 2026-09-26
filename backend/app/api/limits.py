"""Giới hạn kích thước body request (2b-3 Q5): 413 TRƯỚC mọi kiểm quyền.

Middleware ASGI đọc HẾT body (tối đa N byte) trước khi gọi app, đếm byte ĐỌC THẬT — không tin
`Content-Length` (request `Transfer-Encoding: chunked` không có header này, header cũng có thể nói dối).
Vượt → 413 ngay, app không chạy dòng nào (không auth, không ghi gì). 413 không lộ gì về ticket.
`Content-Length` khai lớn hơn giới hạn → 413 luôn, khỏi đọc.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOO_LARGE_BODY = json.dumps({"detail": "payload_too_large"}).encode()


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _reject(send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_bytes:
                await _reject(send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break
        replayed = False
        whole = b"".join(chunks)

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": whole, "more_body": False}
            return await receive()  # sau body: chờ disconnect như bình thường

        await self.app(scope, replay, send)


def _content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _reject(send: Send) -> None:
    await send({
        "type": "http.response.start", "status": 413,
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(TOO_LARGE_BODY)).encode())],
    })  # fmt: skip
    await send({"type": "http.response.body", "body": TOO_LARGE_BODY})
