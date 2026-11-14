"""Trang quản trị nhân viên của AD giả lập (D-97, TA chốt 14/11 — "cách 1").

Đóng vai phần mềm quản trị AD của công ty (ngoài đời: công cụ quản trị Active Directory / Entra), KHÔNG nằm trong ServiceDesk AI:
app chỉ có nút mở sang. Nhờ vậy luật "chỉ B17 ghi ra hệ thống ngoài" của agent giữ nguyên — đây là IT thao tác tay trên AD.

Chức năng: xem danh sách, thêm, sửa thông tin, tắt / bật tài khoản (KHÔNG xoá), mở khoá tài khoản đang bị khoá.
- Quản trị viên KHÔNG đặt và KHÔNG xem mật khẩu. Tài khoản mới dùng mật khẩu demo công khai (`mock_services/README.md`), không bắt
  đổi lần đầu (app chưa có màn đổi mật khẩu). Mật khẩu chỉ lưu dạng argon2id như seed.
- "Tắt" = `employment_status = disabled` (+ AD `enabled = false`): ServiceDesk AI từ chối đăng nhập; phiên đang mở bị cắt ở lần làm
  mới phiên kế tiếp. "Bật" = trở lại `active`. Người đã nghỉ việc (`terminated`) không bật lại ở đây.
- Mọi thao tác ghi vào `MockState.admin_log` (hiện ở cuối trang danh sách). Dữ liệu trang này về ban đầu khi nạp lại seed
  (`make seed`, `/_admin/reset`, hoặc bấm chạy lại gói nộp).

Cổng như mọi trang console: chỉ khi APP_ENV ∈ {dev, test} VÀ MOCK_CONSOLE_ENABLED bật (mock chỉ nghe 127.0.0.1). Thêm: mọi POST phải
từ CHÍNH trang này (`Origin`/`Referer` cùng host) — trang khác mở trên cùng máy không gửi form hộ được (403).
"""

import re
from html import escape
from typing import Any
from urllib.parse import parse_qs, urlsplit

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ad import get_user, mock_state
from app.console import DASH, _page, _require_dev_env, _vn
from app.notify import mask_email, mask_phone
from app.state import Account, MockState, User

router = APIRouter(prefix="/console/nhan-vien", dependencies=[Depends(_require_dev_env)])

DEFAULT_PASSWORD = "Demo@2026!"  # mật khẩu demo CÔNG KHAI của môi trường giả lập (mock_services/README.md) — không phải bí mật
_hasher = PasswordHasher()

ROLES: dict[str, tuple[str, list[str]]] = {
    "employee": ("Nhân viên", ["IT-Users"]),
    "l1": ("IT Helpdesk L1", ["IT-Users", "IT-L1"]),
    "l2": ("Kỹ thuật viên L2", ["IT-Users", "IT-L2"]),
}
STATUS_LABEL = {"active": "Đang làm", "probation": "Thử việc", "disabled": "Đã tắt", "terminated": "Đã nghỉ việc"}
NOTICES = {
    "tao": "Đã tạo tài khoản. Mật khẩu ban đầu là mật khẩu demo chung.",
    "sua": "Đã lưu thông tin.",
    "tat": "Đã tắt tài khoản: không đăng nhập được nữa.",
    "bat": "Đã bật lại tài khoản.",
    "mo-khoa": "Đã mở khoá.",
}
USERNAME = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")
PHONE = re.compile(r"^0\d{9,10}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TEXT_MAX = 80


# ---- tiện ích ------------------------------------------------------------------------------------------------------------


def _same_origin(request: Request) -> None:
    """Form chỉ được gửi từ chính trang console (chống trang khác trên cùng máy gửi form hộ — CSRF)."""
    own = f"{request.url.scheme}://{request.url.netloc}"
    origin = request.headers.get("origin")
    if origin is not None:
        if origin != own:
            raise HTTPException(403, "cross_origin")
        return
    referer = request.headers.get("referer")
    if referer is None or f"{urlsplit(referer).scheme}://{urlsplit(referer).netloc}" != own:
        raise HTTPException(403, "cross_origin")


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8", errors="replace")
    return {k: v[0].strip() for k, v in parse_qs(raw, keep_blank_values=True).items()}


def _role(user: User) -> str:
    if "IT-Manager" in user.groups:
        return "manager"
    if "IT-L1" in user.groups:
        return "l1"
    if "IT-L2" in user.groups:
        return "l2"
    return "employee"


def _role_label(user: User) -> str:
    role = _role(user)
    if user.is_service_account:
        return "Tài khoản dịch vụ"
    return "Trưởng bộ phận IT" if role == "manager" else ROLES[role][0]


def _log(state: MockState, text: str) -> None:
    state.admin_log.append((state.now(), text))


def _locks(user: User) -> list[str]:
    return [kind for kind, a in user.accounts.items() if a.locked]


def _redirect(path: str, notice: str) -> RedirectResponse:
    return RedirectResponse(f"{path}?tb={notice}", status_code=303)


def _notice(request: Request) -> str:
    key = request.query_params.get("tb")
    return f'<p class="ok">{escape(NOTICES[key])}</p>' if key in NOTICES else ""


def _err(text: str) -> str:
    return f'<p class="err">{escape(text)}</p>'


def _input(label: str, name: str, value: str = "", *, placeholder: str = "", readonly: bool = False) -> str:
    ro = " readonly" if readonly else ""
    return (
        f'<label>{escape(label)}<input name="{name}" value="{escape(value)}" placeholder="{escape(placeholder)}"'
        f' maxlength="{TEXT_MAX}"{ro}></label>'
    )


def _select(label: str, name: str, options: list[tuple[str, str]], selected: str, *, disabled: bool = False) -> str:
    opts = "".join(
        f'<option value="{escape(v)}"{" selected" if v == selected else ""}>{escape(t)}</option>' for v, t in options
    )
    dis = " disabled" if disabled else ""
    return f'<label>{escape(label)}<select name="{name}"{dis}>{opts}</select></label>'


def _manager_options(state: MockState, exclude: str | None = None) -> list[tuple[str, str]]:
    people = sorted((u for u in state.users.values() if u.user_id != exclude and not u.is_service_account),
                    key=lambda u: u.user_id)  # fmt: skip
    return [("", "(không có)"), *((u.user_id, f"{u.user_id} — {u.full_name}") for u in people)]


def _check(state: MockState, form: dict[str, str], *, user_id: str | None) -> list[str]:
    """Lỗi nhập liệu (câu tiếng Việt). `user_id` None = đang tạo mới."""
    problems: list[str] = []
    if user_id is None:
        username = form.get("username", "")
        if not USERNAME.match(username):
            problems.append("Tên đăng nhập: 3–32 ký tự, chữ thường không dấu, số, dấu chấm, gạch; bắt đầu bằng chữ (vd: minh.nt).")
        elif any(u.username.lower() == username for u in state.users.values()):
            problems.append("Tên đăng nhập đã có người dùng.")
    full_name = form.get("full_name", "")
    if not 2 <= len(full_name) <= TEXT_MAX:
        problems.append("Họ tên: 2–80 ký tự.")
    for key, label in (("title", "Chức danh"), ("department", "Phòng ban")):
        if not 1 <= len(form.get(key, "")) <= TEXT_MAX:
            problems.append(f"{label}: 1–80 ký tự.")
    if form.get("role", "") not in ROLES:
        problems.append("Vai trò không hợp lệ.")
    manager = form.get("manager_id", "")
    if manager and (manager not in state.users or manager == user_id):
        problems.append("Người quản lý không hợp lệ.")
    phone = form.get("phone", "")
    if phone:
        if not PHONE.match(phone):
            problems.append("Số điện thoại: 10–11 chữ số, bắt đầu bằng 0.")
        elif any(u.phone == phone and u.user_id != user_id for u in state.users.values()):
            problems.append("Số điện thoại đã thuộc người khác (SMS đặt lại mật khẩu sẽ gửi nhầm người).")
    email = form.get("email", "")
    if email and (len(email) > TEXT_MAX or not EMAIL.match(email)):
        problems.append("Email không hợp lệ.")
    return problems


def _next_id(state: MockState) -> str:
    numbers = [int(m.group(1)) for uid in state.users if (m := re.fullmatch(r"nv(\d{3,})", uid))]
    return f"nv{(max(numbers, default=0) + 1):03d}"


def _person_form(state: MockState, action: str, form: dict[str, str], *, user: User | None, submit: str) -> str:
    editing_role_locked = user is not None and (_role(user) == "manager" or user.is_service_account)
    role_options = [(k, v[0]) for k, v in ROLES.items()]
    if editing_role_locked and user is not None:
        role_options = [(form.get("role", ""), _role_label(user))]
    fields = [
        _input("Mã nhân viên", "user_id", user.user_id if user else "(tự cấp khi tạo)", readonly=True),
        _input("Tên đăng nhập", "username", form.get("username", ""), placeholder="vd: minh.nt", readonly=user is not None),
        _input("Họ tên", "full_name", form.get("full_name", "")),
        _input("Chức danh", "title", form.get("title", "")),
        _input("Phòng ban", "department", form.get("department", ""), placeholder="vd: Finance, Sales, HR, IT"),
        _select("Vai trò", "role", role_options, form.get("role", "employee"), disabled=editing_role_locked),
        _select("Người quản lý", "manager_id", _manager_options(state, user.user_id if user else None), form.get("manager_id", "")),
        _input("Số điện thoại", "phone", form.get("phone", ""), placeholder="nhận SMS đặt lại mật khẩu"),
        _input("Email", "email", form.get("email", "")),
    ]
    hidden_role = (
        f'<input type="hidden" name="role" value="{escape(form.get("role", ""))}">' if editing_role_locked else ""
    )
    return f'<form class="f" method="post" action="{escape(action)}">{"".join(fields)}{hidden_role}<button>{escape(submit)}</button></form>'


def _values(user: User) -> dict[str, str]:
    return {
        "username": user.username, "full_name": user.full_name, "title": user.title, "department": user.department,
        "role": _role(user), "manager_id": user.manager_id or "", "phone": user.phone or "", "email": user.email or "",
    }  # fmt: skip


def _groups_for(user: User, role: str) -> list[str]:
    """Đổi vai trò chỉ thay nhóm IT-L1 / IT-L2; giữ các nhóm khác (ServiceDesk AI tự nhận vai trò mới ở lần đăng nhập / làm mới sau)."""
    keep = [g for g in user.groups if g not in ("IT-L1", "IT-L2")]
    extra = [g for g in ROLES[role][1] if g not in keep]
    return keep + extra


# ---- trang ---------------------------------------------------------------------------------------------------------------


NOTE = (
    '<p class="muted">Đây là phần mềm quản trị AD của công ty (giả lập), không thuộc ServiceDesk AI. Quản trị viên không đặt và không '
    "xem mật khẩu: tài khoản mới dùng mật khẩu demo chung; nhân viên quên mật khẩu thì nhắn ServiceDesk AI để đặt lại. Dữ liệu ở đây về "
    "ban đầu khi chạy lại hệ thống.</p>"
)


@router.get("", response_class=HTMLResponse)
async def list_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    rows = []
    for u in sorted(state.users.values(), key=lambda u: u.user_id):
        locks = ", ".join(_locks(u)) or "không"
        cells = [
            u.user_id, u.username, u.full_name, u.title, u.department, _role_label(u), u.manager_id or DASH,
            STATUS_LABEL.get(u.employment_status, u.employment_status), locks,
        ]  # fmt: skip
        tds = "".join(f"<td>{escape(c)}</td>" for c in cells)
        link = f'<td><a href="/console/nhan-vien/{escape(u.user_id)}">Quản lý</a></td>'
        rows.append(f"<tr>{tds}{link}</tr>")
    head = "".join(
        f"<th>{escape(h)}</th>"
        for h in ["Mã", "Tên đăng nhập", "Họ tên", "Chức danh", "Phòng ban", "Vai trò", "Quản lý", "Trạng thái", "Đang khoá", ""]
    )
    log = "".join(f"<li>{escape(_vn(at))} — {escape(text)}</li>" for at, text in reversed(state.admin_log[-50:]))
    body = (
        f"{_notice(request)}{NOTE}"
        '<p><a href="/console/nhan-vien/them"><button type="button">+ Thêm nhân viên</button></a></p>'
        f"<table><tr>{head}</tr>{''.join(rows)}</table>"
        f"<h2>Nhật ký thao tác</h2><ul>{log or '<li class=muted>(chưa có)</li>'}</ul>"
    )
    return _page(state, "Quản trị nhân viên (AD)", body, admin=True)


@router.get("/them", response_class=HTMLResponse)
async def create_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    return _page(state, "Thêm nhân viên", NOTE + _person_form(state, "/console/nhan-vien/them", {"role": "employee"},
                                                             user=None, submit="Tạo tài khoản"), admin=True)  # fmt: skip


@router.post("/them", response_class=HTMLResponse)
async def create(request: Request) -> Any:
    _same_origin(request)
    state = mock_state(request)
    form = await _form(request)
    problems = _check(state, form, user_id=None)
    if problems:
        body = "".join(_err(p) for p in problems) + _person_form(state, "/console/nhan-vien/them", form, user=None,
                                                                 submit="Tạo tài khoản")  # fmt: skip
        return _page(state, "Thêm nhân viên", body, admin=True, status=400)
    now = state.now()
    user_id = _next_id(state)
    accounts = {kind: Account(enabled=True, locked=False, lock_reason=None, password_last_set=now, privilege="standard_user")
                for kind in ("ad", "email")}  # fmt: skip
    state.users[user_id] = User(
        user_id=user_id, username=form["username"], full_name=form["full_name"], title=form["title"],
        department=form["department"], groups=list(ROLES[form["role"]][1]), manager_id=form.get("manager_id") or None,
        employment_status="active", hired_at=now.date(), is_privileged_account=False,
        is_service_account=False, disable_reason=None, password_hash=_hasher.hash(DEFAULT_PASSWORD), accounts=accounts,
        lockouts=[], phone=form.get("phone") or None, email=form.get("email") or None,
    )  # fmt: skip
    _log(state, f"Tạo {user_id} ({form['username']}, {ROLES[form['role']][0]})")
    return _redirect(f"/console/nhan-vien/{user_id}", "tao")


@router.get("/{user_id}", response_class=HTMLResponse)
async def detail_page(user_id: str, request: Request) -> HTMLResponse:
    state = mock_state(request)
    user = get_user(state, user_id)
    return _page(state, f"Nhân viên {user.user_id} — {user.full_name}", _detail(state, user, _values(user), request),
                 admin=True)  # fmt: skip


def _detail(state: MockState, user: User, form: dict[str, str], request: Request, errors: list[str] | None = None) -> str:
    status = STATUS_LABEL.get(user.employment_status, user.employment_status)
    if user.employment_status in ("active", "probation"):
        toggle = (f'<form method="post" action="/console/nhan-vien/{escape(user.user_id)}/tat">'
                  "<button>Tắt tài khoản</button></form>")  # fmt: skip
    elif user.employment_status == "disabled":
        toggle = (f'<form method="post" action="/console/nhan-vien/{escape(user.user_id)}/bat">'
                  "<button>Bật lại tài khoản</button></form>")  # fmt: skip
    else:
        toggle = '<p class="muted">Đã nghỉ việc — không bật lại ở đây.</p>'
    lock_rows = "".join(
        f"<li>{escape(kind)} — khoá do {escape(a.lock_reason or DASH)} "
        f'<form style="display:inline" method="post" action="/console/nhan-vien/{escape(user.user_id)}/mo-khoa">'
        f'<input type="hidden" name="account_type" value="{escape(kind)}"><button>Mở khoá</button></form></li>'
        for kind, a in user.accounts.items()
        if a.locked
    )
    contact = f"SĐT {mask_phone(user.phone) if user.phone else DASH} · email {mask_email(user.email) if user.email else DASH}"
    return (
        f"{_notice(request)}{''.join(_err(e) for e in errors or [])}"
        f"<p><b>Trạng thái:</b> {escape(status)} · <b>Vai trò:</b> {escape(_role_label(user))} · {escape(contact)}</p>"
        f"{toggle}<h2>Khoá tài khoản</h2><ul>{lock_rows or '<li class=muted>Không có tài khoản nào đang khoá.</li>'}</ul>"
        f"<h2>Sửa thông tin</h2>"
        + _person_form(state, f"/console/nhan-vien/{user.user_id}/sua", form, user=user, submit="Lưu")
        + '<p><a href="/console/nhan-vien">← Danh sách nhân viên</a></p>'
    )


@router.post("/{user_id}/sua", response_class=HTMLResponse)
async def update(user_id: str, request: Request) -> Any:
    _same_origin(request)
    state = mock_state(request)
    user = get_user(state, user_id)
    form = await _form(request)
    locked_role = _role(user) == "manager" or user.is_service_account
    if locked_role:
        form["role"] = "employee"  # chỉ để qua kiểm; KHÔNG đổi nhóm của manager / tài khoản dịch vụ ở đây
    problems = _check(state, form, user_id=user_id)
    if problems:
        shown = {**form, "username": user.username, "role": _role(user) if locked_role else form.get("role", "")}
        return _page(state, f"Nhân viên {user.user_id} — {user.full_name}", _detail(state, user, shown, request, problems),
                     admin=True, status=400)  # fmt: skip
    user.full_name, user.title, user.department = form["full_name"], form["title"], form["department"]
    user.manager_id = form.get("manager_id") or None
    user.phone, user.email = form.get("phone") or None, form.get("email") or None
    if not locked_role:
        user.groups = _groups_for(user, form["role"])
    _log(state, f"Sửa thông tin {user_id}")
    return _redirect(f"/console/nhan-vien/{user_id}", "sua")


@router.post("/{user_id}/tat")
async def disable(user_id: str, request: Request) -> RedirectResponse:
    _same_origin(request)
    state = mock_state(request)
    user = get_user(state, user_id)
    if user.employment_status not in ("active", "probation"):
        raise HTTPException(409, "not_active")
    user.employment_status, user.disable_reason = "disabled", "other"
    user.accounts["ad"].enabled = False
    _log(state, f"Tắt tài khoản {user_id}")
    return _redirect(f"/console/nhan-vien/{user_id}", "tat")


@router.post("/{user_id}/bat")
async def enable(user_id: str, request: Request) -> RedirectResponse:
    _same_origin(request)
    state = mock_state(request)
    user = get_user(state, user_id)
    if user.employment_status != "disabled":
        raise HTTPException(409, "not_disabled")
    user.employment_status, user.disable_reason = "active", None
    user.accounts["ad"].enabled = True
    _log(state, f"Bật lại tài khoản {user_id}")
    return _redirect(f"/console/nhan-vien/{user_id}", "bat")


@router.post("/{user_id}/mo-khoa")
async def unlock(user_id: str, request: Request) -> RedirectResponse:
    _same_origin(request)
    state = mock_state(request)
    user = get_user(state, user_id)
    kind = (await _form(request)).get("account_type", "")
    account = user.accounts.get(kind)
    if account is None or not account.locked:
        raise HTTPException(409, "not_locked")
    account.locked, account.lock_reason = False, None
    _log(state, f"Mở khoá {kind} của {user_id}")
    return _redirect(f"/console/nhan-vien/{user_id}", "mo-khoa")
