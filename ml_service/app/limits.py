"""Giới hạn body 256 KB (P4 mục 5) — 413 TRƯỚC mọi kiểm token và trước handler.

Cùng khuôn `backend/app/api/limits.py` (2b-3 Q5; hai package cùng tên `app` nên không import chéo): đọc
hết body tối đa N byte, đếm byte ĐỌC THẬT — không tin `Content-Length` (request chunked không có header
này). `Content-Length` khai lớn hơn giới hạn → 413 luôn, khỏi đọc.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 256 * 1024
TOO_LARGE_BODY = json.dumps({"error": "payload_too_large"}).encode()


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
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
            return await receive()

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
