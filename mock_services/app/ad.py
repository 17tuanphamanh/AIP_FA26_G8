"""Mock Active Directory: đăng nhập (argon2id), thuộc tính người dùng (kèm email), lịch sử khoá, mức đặc quyền,
chuỗi quản lý; ghi: đặt lại mật khẩu, mở khoá, khoá (P5 mục 7).

Khoá tài khoản AD (`accounts.ad.locked`) chặn `/ad/authenticate`: mật khẩu đúng → 403 `account_locked` (mật khẩu sai vẫn
401 — không dò được tài khoản nào đang khoá). Khoá email/ERP không chặn — người bị khoá email/ERP vẫn đăng nhập service
desk để xin mở khoá. Trạng thái làm việc (disabled, terminated…) do backend quyết định sau khi đăng nhập (P6 mục 4 bước
5), mock chỉ trả thuộc tính. Ghi: tài khoản `enabled=false` hoặc người `terminated` → reset/unlock 409 `account_disabled`;
unlock tài khoản không khoá → 409 `not_locked`.

F2: `reset-password` có `channel="sms"` (chỉ tài khoản `ad`) — mật khẩu tạm một lần, hạn `TEMP_PASSWORD_TTL`, gửi SMS tới
`phone` trong seed + email báo chủ tài khoản (`app/notify.py`, chỉ vào hộp thư đi); `/ad/change-password` đổi mật khẩu tạm lấy
mật khẩu mới.

Cổng đăng nhập giả lập `GET /portal` (chỉ `APP_ENV` dev/test, môi trường khác → 404): HTML tối giản, không JS — đăng nhập,
gặp mật khẩu tạm thì form đổi mật khẩu. Dùng chung logic với `/ad/authenticate` và `/ad/change-password`, không cần token
(là màn hình của người dùng cuối, như trang đăng nhập Windows/OWA).
"""

import os
import secrets
from datetime import timedelta
from html import escape
from typing import Any, Literal
from urllib.parse import parse_qs

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app import notify
from app.security import require_read, require_write
from app.state import MockState, User

api = APIRouter(prefix="/ad")

AccountType = Literal["ad", "email", "erp"]
_hasher = PasswordHasher()
TEMP_PASSWORD_TTL = timedelta(minutes=15)
_TTL_MINUTES = int(TEMP_PASSWORD_TTL.total_seconds() // 60)


def new_temp_password() -> str:
    """Mật khẩu tạm ngẫu nhiên (16 ký tự). Test monkeypatch hàm này để biết mật khẩu mà không đọc nội dung tin."""
    return secrets.token_urlsafe(12)


def _verify(stored: str, password: str) -> bool:
    try:
        _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False
    return True


def _temp_valid(state: MockState, user: User) -> bool:
    expires = user.temp_password_expires_at
    return user.must_change_password and expires is not None and state.now() < expires


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
        "email": user.email,
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


def check_login(state: MockState, dummy: str, username: str, password: str) -> User:
    """Logic chung của `/ad/authenticate` và cổng `/portal`. Sai mật khẩu / user lạ / mật khẩu tạm hết hạn → 401; mật khẩu
    đúng nhưng AD khoá → 403 `account_locked`; mật khẩu tạm còn hạn → 403 `password_change_required`."""
    user = next((u for u in state.users.values() if u.username == username), None)
    # Không có user vẫn verify một hash giả: thời gian phản hồi tương đương, không dò được
    # username nào tồn tại (P6 mục 4 "Thông báo lỗi").
    stored = user.password_hash if user is not None else dummy
    if not _verify(stored, password) or user is None:  # user None: chỉ khi đoán trúng mật khẩu ngẫu nhiên của hash giả
        raise HTTPException(401, "invalid_credentials")
    # F2: hash đang là của mật khẩu tạm — hết hạn thì như sai mật khẩu
    if user.must_change_password and not _temp_valid(state, user):
        raise HTTPException(401, "invalid_credentials")
    if user.accounts["ad"].locked:  # kiểm SAU mật khẩu: mật khẩu sai không cho biết tài khoản có đang khoá
        raise HTTPException(403, "account_locked")
    if user.must_change_password:
        raise HTTPException(403, "password_change_required")
    return user


@api.post("/authenticate", dependencies=[Depends(require_read)])
async def authenticate(body: Credentials, request: Request) -> dict[str, Any]:
    user = check_login(mock_state(request), request.app.state.dummy_hash, body.username, body.password)
    return user_view(user)


@api.get("/users/{user_id}", dependencies=[Depends(require_read)])
async def read_user(user_id: str, request: Request, account_type: AccountType = "ad") -> dict[str, Any]:
    return user_view(get_user(mock_state(request), user_id), account_type)


@api.get("/users/{user_id}/lockouts", dependencies=[Depends(require_read)])
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


@api.get("/users/{user_id}/privilege", dependencies=[Depends(require_read)])
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


@api.get("/users/{user_id}/manager-chain", dependencies=[Depends(require_read)])
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


def _require_enabled(user: User, account: Any) -> None:
    if not account.enabled or user.employment_status == "terminated":
        raise HTTPException(409, "account_disabled")


class ResetPasswordBody(BaseModel):
    # F2: chỉ body này cấm trường lạ — không nhận số điện thoại từ lời gọi (số lấy từ seed của chính chủ).
    model_config = ConfigDict(extra="forbid")
    account_type: AccountType = "ad"
    channel: Literal["email", "sms"] = "email"


@api.post("/users/{user_id}/reset-password", dependencies=[Depends(require_write)])
async def reset_password(user_id: str, body: ResetPasswordBody, request: Request) -> dict[str, Any]:
    user, account = _account(request, user_id, body.account_type)
    _require_enabled(user, account)
    state = mock_state(request)
    if body.channel == "email":
        account.password_last_set = state.now()
        # Mật khẩu tạm gửi thẳng tới email người dùng — KHÔNG bao giờ nằm trong phản hồi API.
        return {
            "user_id": user_id,
            "account_type": body.account_type,
            "delivered_via": "email",
            "must_change_at_next_login": True,
        }
    if body.account_type != "ad":  # mock chỉ có một password_hash (của AD) để kiểm mật khẩu tạm
        raise HTTPException(409, "sms_reset_ad_only")
    if user.phone is None:
        raise HTTPException(409, "no_phone_on_file")
    now = state.now()
    temp = new_temp_password()
    user.password_hash = _hasher.hash(temp)  # mật khẩu cũ hỏng ngay; chỉ lưu hash của mật khẩu tạm
    user.must_change_password = True
    user.temp_password_expires_at = now + TEMP_PASSWORD_TTL
    account.password_last_set = now
    notify.send_temp_password_sms(state.outbox, user.phone, temp, now, _TTL_MINUTES)
    if user.email is not None:  # seed bắt buộc email — nhánh này chỉ để kiểu chặt
        notify.send_sms_reset_notice(state.outbox, user.email, user.phone, now, _TTL_MINUTES)
    # Mật khẩu tạm chỉ đi qua SMS — KHÔNG bao giờ nằm trong phản hồi API. `sent_to` là số ĐÃ CHE.
    return {
        "user_id": user_id,
        "account_type": body.account_type,
        "delivered_via": "sms",
        "must_change_at_next_login": True,
        "expires_in_minutes": _TTL_MINUTES,
        "sent_to": notify.mask_phone(user.phone),
    }


class ChangePasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    temp_password: str
    new_password: str = Field(min_length=12)

    @model_validator(mode="after")
    def _differs(self) -> "ChangePasswordBody":
        if self.new_password == self.temp_password:
            raise ValueError("new_password phải khác temp_password")
        return self


def apply_change(state: MockState, dummy: str, body: ChangePasswordBody) -> User:
    """Logic chung của `/ad/change-password` và cổng `/portal`. Sai / hết hạn / đã dùng / user lạ → cùng một 401; mật khẩu
    tạm đúng nhưng AD đang khoá → 403 `account_locked` (không đổi gì)."""
    user = next((u for u in state.users.values() if u.username == body.username), None)
    stored = user.password_hash if user is not None else dummy  # luôn verify một hash như authenticate
    if not _verify(stored, body.temp_password) or user is None or not _temp_valid(state, user):
        raise HTTPException(401, "invalid_credentials")
    if user.accounts["ad"].locked:
        raise HTTPException(403, "account_locked")
    user.password_hash = _hasher.hash(body.new_password)
    user.must_change_password, user.temp_password_expires_at = False, None
    user.accounts["ad"].password_last_set = state.now()
    return user


@api.post("/change-password", dependencies=[Depends(require_write)])
async def change_password(body: ChangePasswordBody, request: Request) -> dict[str, Any]:
    """F2: đổi mật khẩu tạm (còn hạn, chưa dùng) lấy mật khẩu mới."""
    user = apply_change(mock_state(request), request.app.state.dummy_hash, body)
    return {"user_id": user.user_id, "username": user.username, "password_changed": True}


@api.post("/users/{user_id}/unlock", dependencies=[Depends(require_write)])
async def unlock(user_id: str, body: AccountBody, request: Request) -> dict[str, Any]:
    user, account = _account(request, user_id, body.account_type)
    _require_enabled(user, account)
    if not account.locked:
        raise HTTPException(409, "not_locked")
    was_locked = account.locked
    account.locked, account.lock_reason = False, None
    return {"user_id": user_id, "account_type": body.account_type, "locked": False,
            "was_locked": was_locked}  # fmt: skip


@api.post("/users/{user_id}/lock", dependencies=[Depends(require_write)])
async def lock(user_id: str, body: LockBody, request: Request) -> dict[str, Any]:
    _, account = _account(request, user_id, body.account_type)
    account.locked, account.lock_reason = True, body.reason
    return {"user_id": user_id, "account_type": body.account_type, "locked": True}


def dummy_hash() -> str:
    """Hash của một chuỗi ngẫu nhiên — chỉ để `authenticate` tốn cùng thời gian khi user không có."""
    return _hasher.hash(secrets.token_urlsafe(32))


# ---- Cổng đăng nhập giả lập (chỉ APP_ENV dev/test) ------------------------------------------------

PORTAL_ENVS = frozenset({"dev", "test"})
_PORTAL_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_PORTAL_ERRORS = {
    "invalid_credentials": "Tên đăng nhập hoặc mật khẩu không đúng.",
    "account_locked": "Tài khoản đang bị khoá. Liên hệ IT Service Desk để mở khoá.",
    "account_disabled": "Tài khoản đã bị vô hiệu hoá. Liên hệ IT Service Desk.",
}


def _require_portal() -> None:
    # Đọc env lúc nhận request (không phải lúc import): test bật/tắt bằng monkeypatch; thiếu APP_ENV → tắt (fail-closed).
    if os.environ.get("APP_ENV", "") not in PORTAL_ENVS:
        raise HTTPException(404, "Not Found")


portal = APIRouter(prefix="/portal", dependencies=[Depends(_require_portal)], include_in_schema=False)


_PORTAL_CSS = (
    "*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;"
    "font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#1d1d1f;"
    "background:linear-gradient(160deg,#eaf1fa 0%,#f5f5f7 55%,#fdf1e8 100%)}"
    ".box{width:100%;max-width:420px;background:#fff;border:1px solid #e5e5ea;border-radius:22px;padding:30px 30px 22px;"
    "box-shadow:0 20px 50px rgba(0,40,90,.10)}"
    ".brand{display:flex;align-items:center;gap:12px;margin-bottom:22px}.brand b{display:block;font-size:15px}"
    ".brand small{color:#6e6e73;font-size:12.5px}.logo{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;"
    "background:linear-gradient(135deg,#0055a4,#3b86d6);color:#fff;font-weight:800;letter-spacing:.02em}"
    ".mock{margin-left:auto;background:#fff1e6;color:#b54708;border:1px solid #f8c9a0;border-radius:999px;padding:2px 9px;"
    "font-size:10.5px;font-weight:700;letter-spacing:.05em}"
    "h1{font-size:24px;margin:0 0 6px;letter-spacing:-.01em}p{margin:0 0 14px;color:#3a3a3c}"
    "label{display:block;margin:14px 0 0;font-weight:600;font-size:13.5px}input{display:block;width:100%;height:44px;margin-top:6px;"
    "padding:0 13px;border:1px solid #d2d2d7;border-radius:11px;font:inherit}"
    "input:focus{outline:none;border-color:#0055a4;box-shadow:0 0 0 3px rgba(0,85,164,.15)}"
    "button{width:100%;height:46px;margin-top:22px;border:0;border-radius:12px;background:#0055a4;color:#fff;font:inherit;"
    "font-weight:600;cursor:pointer}button:hover{background:#00498d}"
    ".err,.ok{padding:11px 14px;border-radius:12px;font-weight:500}.err{background:#fdecea;color:#b42318;border:1px solid #f5c2bc}"
    ".ok{background:#e7f5ec;color:#1a7f37;border:1px solid #bfe5cb}"
    ".foot{margin:22px 0 0;padding-top:14px;border-top:1px solid #efeff2;color:#8e8e93;font-size:12.5px;text-align:center}"
)


def _page(body: str, status: int = 200) -> HTMLResponse:
    html = (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Cổng đăng nhập (giả lập)</title>'
        f"<style>{_PORTAL_CSS}</style></head><body><main class=\"box\">"
        '<div class="brand"><span class="logo">DC</span><div><b>Demo Corp</b><small>Cổng đăng nhập công ty</small></div>'
        '<span class="mock">GIẢ LẬP</span></div>'
        f"<h1>Đăng nhập</h1>{body}"
        '<p class="foot">Tài khoản AD dùng chung với ServiceDesk AI · môi trường giả lập</p></main></body></html>'
    )
    return HTMLResponse(html, status_code=status, headers=_PORTAL_HEADERS)


def _note(text: str | None, cls: str = "err") -> str:
    return f'<p class="{cls}">{escape(text)}</p>' if text else ""


def _login_form(error: str | None = None, status: int = 200) -> HTMLResponse:
    return _page(
        f'{_note(error)}<form method="post" action="/portal/login">'
        '<label>Tên đăng nhập <input name="username" autocomplete="username" required></label>'
        '<label>Mật khẩu <input name="password" type="password" autocomplete="current-password" required></label>'
        "<button>Đăng nhập</button></form>",
        status,
    )


def _change_form(username: str, error: str | None = None, status: int = 200) -> HTMLResponse:
    # Không bao giờ điền sẵn mật khẩu (tạm hay mới) vào trang — chỉ username.
    return _page(
        f"{_note(error)}<p>Bạn đang dùng mật khẩu tạm. Hãy đặt mật khẩu mới (từ 12 ký tự, khác mật khẩu tạm).</p>"
        '<form method="post" action="/portal/change-password">'
        f'<input type="hidden" name="username" value="{escape(username)}">'
        '<label>Mật khẩu tạm <input name="temp_password" type="password" autocomplete="current-password" required></label>'
        '<label>Mật khẩu mới <input name="new_password" type="password" autocomplete="new-password" required></label>'
        '<label>Nhập lại mật khẩu mới <input name="confirm_password" type="password" autocomplete="new-password" required>'
        "</label><button>Đổi mật khẩu</button></form>",
        status,
    )


def _success(user: User) -> HTMLResponse:
    return _page(_note(f"Đăng nhập thành công. Xin chào {user.full_name}.", "ok"))


async def _form(request: Request) -> dict[str, str]:
    """Đọc form urlencoded (không cần python-multipart). Trường lặp → lấy giá trị đầu."""
    raw = (await request.body()).decode("utf-8", errors="replace")
    return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}


def _portal_login_result(user: User) -> HTMLResponse:
    account = user.accounts["ad"]
    if not account.enabled or user.employment_status == "terminated":
        return _login_form(_PORTAL_ERRORS["account_disabled"], 403)
    return _success(user)


@portal.get("")
async def portal_home() -> HTMLResponse:
    return _login_form()


@portal.post("/login")
async def portal_login(request: Request) -> HTMLResponse:
    form = await _form(request)
    username, password = form.get("username", ""), form.get("password", "")
    if not username or not password:
        return _login_form("Nhập tên đăng nhập và mật khẩu.", 400)
    state = mock_state(request)
    try:
        user = check_login(state, request.app.state.dummy_hash, username, password)
    except HTTPException as e:
        if e.detail == "password_change_required":
            return _change_form(username)
        return _login_form(_PORTAL_ERRORS.get(str(e.detail), _PORTAL_ERRORS["invalid_credentials"]), e.status_code)
    return _portal_login_result(user)


@portal.post("/change-password")
async def portal_change_password(request: Request) -> HTMLResponse:
    form = await _form(request)
    username = form.get("username", "")
    if not username:
        return _login_form("Phiên đổi mật khẩu không hợp lệ — đăng nhập lại.", 400)
    if form.get("new_password", "") != form.get("confirm_password", ""):
        return _change_form(username, "Hai lần nhập mật khẩu mới không khớp.", 422)
    try:
        body = ChangePasswordBody(
            username=username, temp_password=form.get("temp_password", ""), new_password=form.get("new_password", "")
        )
    except ValidationError:
        return _change_form(username, "Mật khẩu mới phải từ 12 ký tự và khác mật khẩu tạm.", 422)
    state = mock_state(request)
    dummy = request.app.state.dummy_hash
    try:
        apply_change(state, dummy, body)
        user = check_login(state, dummy, username, body.new_password)  # đăng nhập lại bằng mật khẩu mới như người dùng thật
    except HTTPException as e:
        if e.detail == "invalid_credentials":
            return _change_form(username, "Mật khẩu tạm sai hoặc đã hết hạn.", 401)
        return _login_form(_PORTAL_ERRORS.get(str(e.detail), _PORTAL_ERRORS["invalid_credentials"]), e.status_code)
    return _portal_login_result(user)


# `main.py` gắn `ad.router`: API /ad/* + cổng /portal. Đặt CUỐI file — include_router chép route đã khai báo lúc gọi.
router = APIRouter()
router.include_router(api)
router.include_router(portal)
