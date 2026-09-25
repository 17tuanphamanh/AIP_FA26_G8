"""Client httpx gắn token dịch vụ ở header `X-Service-Token` (P6 mục 3). Mỗi lời gọi truyền timeout
của tool; lỗi HTTP để `raise_for_status` ném — ToolRegistry phân loại (P5 mục 5, 6.1)."""

from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr


def seg(value: str) -> str:
    """Một đoạn path an toàn: `nv001` giữ nguyên, `a/b` thành `a%2Fb` — không để id chui sang route khác."""
    return quote(value, safe="")


def path(value: str) -> str:
    """Đường dẫn thư mục (`finance/Q3`) — giữ `/` vì route mock dùng `{path:path}`."""
    return quote(value.strip("/"), safe="/")


class ServiceHttp:
    def __init__(
        self,
        base_url: str,
        token: SecretStr,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Service-Token": token.get_secret_value()},
            transport=transport,
        )

    async def get(self, url: str, *, timeout: float, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        resp = await self._client.get(url, params=clean, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    async def post(self, url: str, *, timeout: float, json: dict[str, Any]) -> Any:
        resp = await self._client.post(url, json=json, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
