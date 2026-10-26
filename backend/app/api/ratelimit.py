"""429 theo tài khoản (Phase 5 gói 2b, D-54 a; đặc tả `claude/dac-ta-bat-2-model.md` 4.8) — bước gọi ở DÒNG ĐẦU handler của
`POST /api/tickets` (bộ A) và `/messages`, `/reply`, `/confirm` (bộ B, chung một bộ).

Thứ tự chốt: 413 (middleware) → 401/403 (`require`) → **429** → 404/403/409 của ticket (`_owned_leaf`) → 422 (thân đọc TRONG handler,
sau dòng này) → xử lý. Đếm theo `p.user_id` của token — không theo IP, không theo trường trong thân; request chưa xác thực dừng ở 401 nên
không làm hao lượt của ai. Không là dependency riêng: bọc `require(...)` trong dependency thứ hai sẽ chạy `require` hai lần (FastAPI cache
theo đối tượng hàm, mà `require` sinh closure mới mỗi lần gọi) → `permission_denied` ghi hai lần.

Vượt → 429 `{"detail": "rate_limited"}` + `Retry-After`; không tạo ticket, không `spawn`, không gọi guard, không lưu nội dung. Lỗi DB ở
cổng đếm lan ra như mọi truy vấn DB khác của route (không fail-open).
"""

from fastapi import HTTPException, Request

from app.api.desk import Desk, RateGate, route_of
from app.auth.models import Principal

__all__ = ["RateGate", "limit_messages", "limit_tickets"]
RATE_LIMITED = "rate_limited"


async def limit_tickets(request: Request, p: Principal, desk: Desk) -> None:
    _raise(await desk.rate.tickets(p.user_id, desk.clock.now(), route_of(request)))


async def limit_messages(request: Request, p: Principal, desk: Desk) -> None:
    _raise(await desk.rate.messages(p.user_id, desk.clock.now(), route_of(request)))


def _raise(wait: int | None) -> None:
    if wait is not None:
        raise HTTPException(429, RATE_LIMITED, headers={"Retry-After": str(wait)})
