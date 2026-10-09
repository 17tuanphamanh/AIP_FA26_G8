"""Mock Active Directory: đăng nhập (argon2id), thuộc tính người dùng, lịch sử khoá, mức đặc quyền,
chuỗi quản lý; ghi: đặt lại mật khẩu, mở khoá, khoá (P5 mục 7).

Mock đơn giản hoá: khoá tài khoản (`accounts.*.locked`) không chặn `/ad/authenticate` — người bị
khoá email/ERP vẫn đăng nhập service desk để xin mở khoá. Trạng thái làm việc (disabled,
terminated…) do backend quyết định sau khi đăng nhập (P6 mục 4 bước 5), mock chỉ trả thuộc tính.
"""

import secrets
from typing import Any, Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.security import require_read, require_write
from app.state import MockState, User

router = APIRouter(prefix="/ad")

AccountType = Literal["ad", "email", "erp"]
_hasher = PasswordHasher()


def mock_state(request: Request) -> MockState:
    state: MockState = request.app.state.mock
    return state


def get_user(state: MockState, user_id: str) -> User:
    user = state.users.get(user_id)
    if user is None:
        raise HTTPException(404, "not_found")
    return user


def user_view(user: User, account_type: str = "ad") -> dict[str, Any]:
    account = user.accounts.get(account_type)
    if account is None:
        raise HTTPException(404, "not_found")
    return {
        "user_id": user.user_id,
        "username": user.username,
        "full_name": user.full_name,
        "title": user.title,
        "department": user.department,
        "groups": user.groups,
        "manager_id": user.manager_id,
        "employment_status": user.employment_status,
        "hired_at": user.hired_at,
        "is_privileged_account": user.is_privileged_account,
        "is_service_account": user.is_service_account,  # Phase 5 T22a P7
        "disable_reason": user.disable_reason,  # Phase 5 T22a P7
        "account": {
            "account_type": account_type,
            "enabled": account.enabled,
            "locked": account.locked,
            "lock_reason": account.lock_reason,
            "password_last_set": account.password_last_set,
        },
    }


class Credentials(BaseModel):
    username: str
    password: str


@router.post("/authenticate", dependencies=[Depends(require_read)])
async def authenticate(body: Credentials, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    user = next((u for u in state.users.values() if u.username == body.username), None)
    # Không có user vẫn verify một hash giả: thời gian phản hồi tương đương, không dò được
    # username nào tồn tại (P6 mục 4 "Thông báo lỗi").
    stored = user.password_hash if user is not None else request.app.state.dummy_hash
    try:
        _hasher.verify(stored, body.password)
    except (VerificationError, InvalidHashError):
        raise HTTPException(401, "invalid_credentials") from None
    if user is None:  # không thể xảy ra trừ khi ai đó đoán trúng mật khẩu ngẫu nhiên của hash giả
        raise HTTPException(401, "invalid_credentials")
    return user_view(user)


@router.get("/users/{user_id}", dependencies=[Depends(require_read)])
async def read_user(user_id: str, request: Request, account_type: AccountType = "ad") -> dict[str, Any]:
    return user_view(get_user(mock_state(request), user_id), account_type)


@router.get("/users/{user_id}/lockouts", dependencies=[Depends(require_read)])
async def lockouts(
    user_id: str, request: Request, account_type: AccountType | None = None
) -> list[dict[str, Any]]:
    user = get_user(mock_state(request), user_id)
    rows = [x for x in user.lockouts if account_type is None or x.account_type == account_type]
    rows.sort(key=lambda x: x.at, reverse=True)
    return [
        {"account_type": x.account_type, "at": x.at, "reason": x.reason, "source": x.source}
        for x in rows
    ]


@router.get("/users/{user_id}/privilege", dependencies=[Depends(require_read)])
async def privilege(user_id: str, request: Request, account_type: AccountType = "ad") -> dict[str, Any]:
    user = get_user(mock_state(request), user_id)
    account = user.accounts.get(account_type)
    if account is None:
        raise HTTPException(404, "not_found")
    return {
        "user_id": user.user_id,
        "account_type": account_type,
        "level": account.privilege,
        "is_privileged_account": user.is_privileged_account,
    }


@router.get("/users/{user_id}/manager-chain", dependencies=[Depends(require_read)])
async def manager_chain(user_id: str, request: Request) -> list[dict[str, Any]]:
    state = mock_state(request)
    user = get_user(state, user_id)
    chain: list[dict[str, Any]] = []
    seen = {user.user_id}
    current = user.manager_id
    while current is not None and current not in seen and current in state.users:
        seen.add(current)
        boss = state.users[current]
        chain.append(
            {
                "user_id": boss.user_id,
                "full_name": boss.full_name,
                "title": boss.title,
                "department": boss.department,
                "employment_status": boss.employment_status,
            }
        )
        current = boss.manager_id
    return chain


# ---- Ghi (chỉ svc_executor) -------------------------------------------------------------------


class AccountBody(BaseModel):
    account_type: AccountType = "ad"


class LockBody(AccountBody):
    reason: Literal["bad_password", "admin", "inactivity"] = "admin"


def _account(request: Request, user_id: str, account_type: str) -> tuple[User, Any]:
    user = get_user(mock_state(request), user_id)
    account = user.accounts.get(account_type)
    if account is None:
        raise HTTPException(404, "not_found")
    return user, account


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(require_write)])
async def reset_password(user_id: str, body: AccountBody, request: Request) -> dict[str, Any]:
    _, account = _account(request, user_id, body.account_type)
    account.password_last_set = mock_state(request).now()
    # Mật khẩu tạm gửi thẳng tới email người dùng — KHÔNG bao giờ nằm trong phản hồi API.
    return {
        "user_id": user_id,
        "account_type": body.account_type,
        "delivered_via": "email",
        "must_change_at_next_login": True,
    }


@router.post("/users/{user_id}/unlock", dependencies=[Depends(require_write)])
async def unlock(user_id: str, body: AccountBody, request: Request) -> dict[str, Any]:
    _, account = _account(request, user_id, body.account_type)
    was_locked = account.locked
    account.locked, account.lock_reason = False, None
    return {"user_id": user_id, "account_type": body.account_type, "locked": False,
            "was_locked": was_locked}  # fmt: skip


@router.post("/users/{user_id}/lock", dependencies=[Depends(require_write)])
async def lock(user_id: str, body: LockBody, request: Request) -> dict[str, Any]:
    _, account = _account(request, user_id, body.account_type)
    account.locked, account.lock_reason = True, body.reason
    return {"user_id": user_id, "account_type": body.account_type, "locked": True}


def dummy_hash() -> str:
    """Hash của một chuỗi ngẫu nhiên — chỉ để `authenticate` tốn cùng thời gian khi user không có."""
    return _hasher.hash(secrets.token_urlsafe(32))
