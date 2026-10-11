"""Provider tương thích API OpenAI (cloud, Ollama, vLLM — P2 mục 3, D-12) qua SDK `openai`.

- `max_retries=0`: retry DUY NHẤT ở gateway (Retry-After, jitter, deadline — P2 mục 9).
- Lỗi SDK → `ProviderError` dựng lại, `from None`: không kéo theo thông điệp/thân phản hồi của provider vào chuỗi
  exception (traceback span E9 không được chứa gì ngoài loại lỗi).
- SDK 3.x dùng `httpx2` → test tiêm `http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(...))` và đếm
  request ở handler (respx không chặn được httpx2).
- `json_mode: json_object` (LLM-JSON, provider chỉ nhận `{"type": "json_object"}`, vd. DeepSeek): response_format không
  mang schema → thêm vào CUỐI system message (không có thì chèn một system message ở đầu) yêu cầu trả đúng một đối tượng
  json theo JSON Schema của lời gọi. Dựng list mới, không sửa `req.messages`. `json_schema`: messages gửi y nguyên.
- Logger `httpx2` ghi NGUYÊN URL ở mức INFO (`HTTP Request: POST http://user:pass@host/v1?api-key=…`) → nâng lên
  WARNING (S9). `httpx2` chỉ SDK openai dùng (test AST ở test_llm_security.py); log `openai` ở DEBUG không có thân
  request (đã dò 29/09/2026 với openai 3.19.2).
"""

import json
import logging
from typing import Any, cast
from urllib.parse import urlsplit

import httpx2
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from pydantic import SecretStr

from app.llm.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    parse_retry_after,
)

logging.getLogger("httpx2").setLevel(logging.WARNING)  # base_url có thể mang khoá — xem docstring

JSON_OBJECT_NOTE = (
    "Trả lời bằng đúng MỘT đối tượng json hợp lệ theo JSON Schema dưới đây, không thêm trường nào khác, "
    "không viết gì ngoài đối tượng json đó.\nJSON Schema:\n"
)


class OpenAICompatProvider:
    def __init__(
        self,
        name: str,
        *,
        base_url: str,
        api_key: SecretStr,
        json_mode: str = "json_schema",
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._json_mode = json_mode
        self._host = urlsplit(base_url).hostname  # chỉ tên máy vào nhãn lỗi — không log base_url (có thể chứa khoá)
        self._client = AsyncOpenAI(
            base_url=base_url, api_key=api_key.get_secret_value(), max_retries=0, http_client=http_client
        )

    async def aclose(self) -> None:
        await self._client.close()

    def _response_format(self, req: ProviderRequest) -> dict[str, Any]:
        if self._json_mode == "json_object":
            return {"type": "json_object"}
        return {"type": "json_schema", "json_schema": {"name": req.schema_name, "schema": req.json_schema,
                                                        "strict": False}}  # fmt: skip

    def _messages(self, req: ProviderRequest) -> list[dict[str, str]]:
        if self._json_mode != "json_object":
            return req.messages
        note = JSON_OBJECT_NOTE + json.dumps(req.json_schema, ensure_ascii=False)
        first = next((i for i, m in enumerate(req.messages) if m.get("role") == "system"), None)
        if first is None:
            return [{"role": "system", "content": note}, *req.messages]
        system = req.messages[first]
        return [*req.messages[:first], {**system, "content": f"{system['content']}\n\n{note}"},
                *req.messages[first + 1 :]]  # fmt: skip

    async def chat(self, req: ProviderRequest) -> ProviderResponse:
        try:
            r = await self._client.chat.completions.create(
                model=req.model,
                messages=cast(Any, self._messages(req)),
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                response_format=cast(Any, self._response_format(req)),
                timeout=req.timeout_s,
            )
        except APITimeoutError:
            raise ProviderError("timeout", host=self._host) from None
        except APIConnectionError:
            raise ProviderError("connect", host=self._host) from None
        except APIStatusError as e:
            retry_after = parse_retry_after(e.response.headers.get("retry-after"))
            raise ProviderError("http", status=e.status_code, retry_after=retry_after, host=self._host) from None
        except APIError:  # phản hồi sai định dạng…: lỗi phía provider, không retry
            raise ProviderError("api", host=self._host) from None
        content = r.choices[0].message.content if r.choices else None
        usage = r.usage
        return ProviderResponse(
            content=content or "",
            tokens_in=usage.prompt_tokens if usage else None,
            tokens_out=usage.completion_tokens if usage else None,
            model_version=r.model or None,
        )
