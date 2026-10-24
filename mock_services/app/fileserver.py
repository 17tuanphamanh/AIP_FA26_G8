"""Mock file server: quyền hiện có, độ nhạy thư mục; ghi: cấp, thu hồi, gia hạn, khôi phục hạn
(P5 mục 7). Đường dẫn dạng `finance/Q3` — route dùng `{path:path}` để nhận dấu `/`."""

from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.ad import get_user, mock_state
from app.security import require_read, require_write
from app.state import MockState, Permission

router = APIRouter(prefix="/files")

# Tài khoản còn dùng được để NHẬN quyền: `active` và `probation` (tài khoản AD vẫn bật, cùng tập với
# `target_user_status` của config/policy.json); `disabled`/`terminated` thì file server từ chối.
ACTIVE_STATUSES = frozenset({"active", "probation"})
LEVEL_RANK = {"read": 1, "write": 2, "full": 3}


def normalize_path(path: str) -> str:
    return path.strip().strip("/")


def permission_view(state: MockState, p: Permission) -> dict[str, Any]:
    expired = p.expires_at is not None and p.expires_at <= state.now()
    return {
        "path": p.path,
        "level": p.level,
        "granted_at": p.granted_at,
        "expires_at": p.expires_at,
        "status": "expired" if expired else "active",
    }


@router.get("/permissions/{user_id}", dependencies=[Depends(require_read)])
async def permissions(
    user_id: str, request: Request, resource_path: str | None = None
) -> list[dict[str, Any]]:
    state = mock_state(request)
    get_user(state, user_id)
    wanted = None if resource_path is None else normalize_path(resource_path)
    rows = sorted((p for p in state.permissions if p.user_id == user_id
                   and (wanted is None or p.path == wanted)), key=lambda p: p.path)  # fmt: skip
    return [permission_view(state, p) for p in rows]


@router.get("/resources/{path:path}", dependencies=[Depends(require_read)])
async def resource(path: str, request: Request) -> dict[str, Any]:
    r = mock_state(request).resources.get(normalize_path(path))
    if r is None:
        raise HTTPException(404, "not_found")
    return {
        "path": r.path,
        "sensitivity": r.sensitivity,
        "owner_department": r.owner_department,
        "owner_id": r.owner_id,
    }


# ---- Ghi (chỉ svc_executor) -------------------------------------------------------------------


class GrantBody(BaseModel):
    resource_path: str = Field(min_length=1)
    level: Literal["read", "write", "full"]
    duration_days: int | None = Field(default=None, gt=0)  # None = không hết hạn


class PathBody(BaseModel):
    resource_path: str = Field(min_length=1)


class ExtendBody(PathBody):
    duration_days: int = Field(gt=0)


class RestoreBody(PathBody):
    expires_at: datetime | None


def _find(state: MockState, user_id: str, path: str) -> Permission:
    p = next((x for x in state.permissions if x.user_id == user_id and x.path == path), None)
    if p is None:
        raise HTTPException(404, "not_found")
    return p


def _require_active(state: MockState, user_id: str) -> None:
    if get_user(state, user_id).employment_status not in ACTIVE_STATUSES:
        raise HTTPException(409, "user_not_active")


def _resource_path(state: MockState, raw: str) -> str:
    path = normalize_path(raw)
    if path not in state.resources:
        raise HTTPException(404, "not_found")
    return path


@router.post("/permissions/{user_id}/grant", dependencies=[Depends(require_write)])
async def grant(user_id: str, body: GrantBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    get_user(state, user_id)
    path = _resource_path(state, body.resource_path)
    _require_active(state, user_id)
    now = state.now()
    current = next((p for p in state.permissions if p.user_id == user_id and p.path == path), None)
    previous_level = None if current is None else current.level
    if (current is not None and permission_view(state, current)["status"] == "active"
            and LEVEL_RANK[current.level] > LEVEL_RANK[body.level]):  # fmt: skip
        # Không hạ quyền đang có: giữ nguyên mức và hạn, báo mức đã có để người gọi biết yêu cầu không đổi gì.
        return {**permission_view(state, current), "previous_level": previous_level, "kept_higher_level": True}
    expires = None if body.duration_days is None else now + timedelta(days=body.duration_days)
    state.permissions = [p for p in state.permissions if p is not current]
    perm = Permission(user_id, path, body.level, now, expires)
    state.permissions.append(perm)
    return {**permission_view(state, perm), "previous_level": previous_level, "kept_higher_level": False}


@router.post("/permissions/{user_id}/revoke", dependencies=[Depends(require_write)])
async def revoke(user_id: str, body: PathBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    get_user(state, user_id)
    path = normalize_path(body.resource_path)
    before = len(state.permissions)
    state.permissions = [p for p in state.permissions if not (p.user_id == user_id and p.path == path)]
    return {"path": path, "revoked": before != len(state.permissions)}


@router.post("/permissions/{user_id}/extend", dependencies=[Depends(require_write)])
async def extend(user_id: str, body: ExtendBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    get_user(state, user_id)
    perm = _find(state, user_id, normalize_path(body.resource_path))
    _require_active(state, user_id)
    previous = perm.expires_at
    base = max(previous, state.now()) if previous is not None else state.now()
    perm.expires_at = base + timedelta(days=body.duration_days)
    # previous_expires_at: tham số cho tool hoàn tác restore_permission_expiry (B17).
    return {**permission_view(state, perm), "previous_expires_at": previous}


@router.post("/permissions/{user_id}/restore-expiry", dependencies=[Depends(require_write)])
async def restore_expiry(user_id: str, body: RestoreBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    get_user(state, user_id)
    perm = _find(state, user_id, normalize_path(body.resource_path))
    perm.expires_at = body.expires_at
    return permission_view(state, perm)
