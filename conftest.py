"""Chạy trước mọi test (conftest ở rootdir nạp trước mọi module test): test không chạm `.env` thật.

Hai đường chạm, chặn cả hai:
  1. pytest tự duyệt thư mục gốc (Dir.collect) và gọi `is_dir()` lên TỪNG mục, kể cả `.env` —
     tức là stat file bí mật. `collect_ignore_glob` được xét TRƯỚC `is_dir()` nên chặn được;
     `norecursedirs` thì không (xét sau).
  2. `app.settings.Settings` đọc file env theo `APP_ENV_FILE` — đặt rỗng để tắt hẳn, test chỉ
     thấy biến môi trường do chính test đặt.

Kèm: `APP_ENV=test` (2b-Q2): thiếu APP_ENV thì app từ chối nạp thành phần giả (guard không che,
   người duyệt giả). Test nào kiểm luật fail-closed tự truyền `app_env` khác.
Kèm: `ML_SERVICE_TOKEN` ngẫu nhiên mỗi phiên (3-Q21, Q-3a-5): backend/worker từ chối khởi động khi thiếu;
   test kiểm luật đó tự xoá biến (monkeypatch). Không phải token thật nào — không có ml-service nào nhận nó.
Kèm: `LLM_BACKEND=scripted` (3-Q26, PLAN-3d Q-3d-13): bắt buộc mọi env; test không bao giờ gọi LLM thật.
   Test kiểm luật fail-closed tự xoá/đổi biến.
Kèm: chặn mạng của SDK `openai` (PLAN-3d, chốt DỪNG 1). SDK 3.x đi qua `httpx2`, respx không chặn được: provider
   thật dựng thiếu transport giả sẽ gọi thẳng ra Internet (CI không có sandbox). Transport thật của `httpx2` bị thay
   bằng hàm ném `NetworkBlocked` — lỗi này không phải `httpx2.RequestError` nên SDK không bọc thành lỗi kết nối,
   gateway cũng không coi là lỗi provider: test đỏ rõ ràng, không request nào ra mạng. `MockTransport` không bị ảnh
   hưởng. `httpx` (respx, testcontainers) giữ nguyên.
"""

import os
import secrets

import pytest

os.environ["APP_ENV_FILE"] = ""
os.environ["APP_ENV"] = "test"
os.environ["ML_SERVICE_TOKEN"] = secrets.token_urlsafe(32)
os.environ["LLM_BACKEND"] = "scripted"

collect_ignore_glob = [".env*"]


class NetworkBlocked(RuntimeError):
    """Test chạm transport mạng thật của `httpx2` (SDK openai)."""


@pytest.fixture(autouse=True)
def _block_llm_network(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import httpx2
    except ImportError:  # môi trường không có SDK openai
        return

    def blocked(_: object, request: "httpx2.Request") -> "httpx2.Response":
        raise NetworkBlocked(f"test không được ra mạng: {request.method} tới {request.url.host}")

    async def blocked_async(_: object, request: "httpx2.Request") -> "httpx2.Response":
        raise NetworkBlocked(f"test không được ra mạng: {request.method} tới {request.url.host}")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", blocked_async)
