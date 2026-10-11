"""Cần gạt test Phase 3 chặng 3h (phase3 mục 3.7, 11.5): đếm lời gọi theo endpoint và đổi trạng thái làm việc của người dùng.

- `count_middleware` là middleware NGOÀI CÙNG (đăng ký SAU `fault_middleware`): đếm mọi request tới API giả lập — kể cả
  request bị `/_admin/faults` bơm lỗi và request bị từ chối token — ngay lúc NHẬN, trước khi xử lý (quy ước 3.9: test "gọi
  ghi đúng 1 lần" đếm ở nơi nhận). Không đếm `/_admin/*` và `/health` (cần gạt + healthcheck, không phải API hệ thống ngoài).
- `GET /_admin/calls?path_prefix=…&method=…` → `{"count": n, "calls": [{"method", "path", "count", "statuses"}]}`;
  `statuses` = mã phản hồi đã trả (request chưa xong thì chưa có mã — `count` vẫn tính).
- `POST /_admin/calls/reset` xoá bộ đếm; `POST /_admin/reset` (nạp lại seed) cũng xoá.
- `POST /_admin/users/{user_id}/status` body `{"employment_status": …}` — người bị khoá trong lúc ticket chờ (h17).

Như `/_admin/faults`: không đòi token — mock chỉ nghe trong mạng Docker nội bộ, đây là cần gạt của người chạy test.
"""

from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from app.ad import get_user, mock_state
from app.admin_faults import UNFAULTABLE
from app.seed_model import DisableReason, EmploymentStatus

router = APIRouter(prefix="/_admin")


class CallLog:
    def __init__(self) -> None:
        self._arrived: Counter[tuple[str, str]] = Counter()
        self._statuses: Counter[tuple[str, str, int]] = Counter()

    def arrive(self, method: str, path: str) -> None:
        self._arrived[(method, path)] += 1

    def answered(self, method: str, path: str, status: int) -> None:
        self._statuses[(method, path, status)] += 1

    def clear(self) -> None:
        self._arrived.clear()
        self._statuses.clear()

    def view(self, path_prefix: str, method: str | None) -> dict[str, Any]:
        rows = [
            {
                "method": m, "path": p, "count": n,
                "statuses": {str(s): k for (m2, p2, s), k in sorted(self._statuses.items()) if (m2, p2) == (m, p)},
            }
            for (m, p), n in sorted(self._arrived.items())
            if p.startswith(path_prefix) and method in (None, m)
        ]  # fmt: skip
        return {"count": sum(r["count"] for r in rows), "calls": rows}


async def count_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    path = request.url.path
    if path.startswith(UNFAULTABLE):
        return await call_next(request)
    calls: CallLog = request.app.state.calls
    calls.arrive(request.method, path)  # đếm TRƯỚC khi xử lý: lỗi bơm/timeout/401 vẫn là một lời gọi đã tới
    response = await call_next(request)
    calls.answered(request.method, path, response.status_code)
    return response


@router.get("/calls")
async def list_calls(
    request: Request,
    path_prefix: str = Query(default="/", pattern=r"^/"),
    method: Literal["GET", "POST"] | None = None,
) -> dict[str, Any]:
    calls: CallLog = request.app.state.calls
    return calls.view(path_prefix, method)


@router.post("/calls/reset")
async def reset_calls(request: Request) -> dict[str, str]:
    calls: CallLog = request.app.state.calls
    calls.clear()
    return {"status": "cleared"}


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employment_status: EmploymentStatus
    disable_reason: DisableReason | None = None  # Phase 5 T22a P7 (TQ-8) — chỉ có nghĩa khi chuyển sang disabled


@router.post("/users/{user_id}/status")
async def set_status(user_id: str, body: StatusIn, request: Request) -> dict[str, str]:
    """Phase 5 T22a P7: `disable_reason` theo trạng thái ĐÍCH — sang `disabled` lấy lý do gửi kèm (không kèm → null: R12 và R10
    đều không khớp); trạng thái khác → LUÔN null (bỏ lý do gửi kèm). Hình dạng phản hồi giữ nguyên."""
    user = get_user(mock_state(request), user_id)  # không có → 404
    user.employment_status = body.employment_status
    user.disable_reason = body.disable_reason if body.employment_status == "disabled" else None
    return {"user_id": user.user_id, "employment_status": user.employment_status}
