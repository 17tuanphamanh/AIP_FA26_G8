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
from app.console_ui import Html, avatar, badge, card, icon, table
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
LOCK_REASON = {"bad_password": "nhập sai mật khẩu nhiều lần", "admin": "quản trị viên khoá", "inactivity": "lâu không đăng nhập"}
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
    return f'<div class="alert ok">✓ {escape(NOTICES[key])}</div>' if key in NOTICES else ""


def _err(text: str) -> str:
    return f'<div class="alert err">{escape(text)}</div>'


def _input(label: str, name: str, value: str = "", *, placeholder: str = "", readonly: bool = False) -> str:
    ro = " readonly" if readonly else ""
    return (
        f'<label class="fld">{escape(label)}<input name="{name}" value="{escape(value)}" placeholder="{escape(placeholder)}"'
        f' maxlength="{TEXT_MAX}"{ro}></label>'
    )


def _select(label: str, name: str, options: list[tuple[str, str]], selected: str, *, disabled: bool = False) -> str:
    opts = "".join(
        f'<option value="{escape(v)}"{" selected" if v == selected else ""}>{escape(t)}</option>' for v, t in options
    )
    dis = " disabled" if disabled else ""
    return f'<label class="fld">{escape(label)}<select name="{name}"{dis}>{opts}</select></label>'


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
    back = "/console/nhan-vien" if user is None else f"/console/nhan-vien/{user.user_id}"
    return (
        f'<form method="post" action="{escape(action)}"><div class="grid2">{"".join(fields)}</div>{hidden_role}'
        f'<div class="actions"><button class="btn pri">{escape(submit)}</button>'
        f'<a class="btn" href="{escape(back)}">Huỷ</a></div></form>'
    )


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
    '<div class="alert info">Đây là phần mềm quản trị AD của công ty (giả lập), không thuộc ServiceDesk AI. Quản trị viên không đặt và '
    "không xem mật khẩu: tài khoản mới dùng mật khẩu demo chung; nhân viên quên mật khẩu thì nhắn ServiceDesk AI để đặt lại. Dữ liệu ở "
    "đây về ban đầu khi chạy lại hệ thống.</div>"
)
ROLE_TONE = {"manager": "warn", "l1": "info", "l2": "info", "employee": ""}
STATUS_TONE = {"active": "ok", "probation": "info", "disabled": "", "terminated": "bad"}
BACK = f'<p style="margin:-8px 0 14px"><a href="/console/nhan-vien">{icon("arrow-left", 14)} Danh sách nhân viên</a></p>'


def _admin_page(state: MockState, title: str, body: str, *, status: int = 200, subtitle: str = "") -> HTMLResponse:
    return _page(state, title, body, admin=True, status=status, active="nhan-vien", subtitle=subtitle)


def _status_badge(user: User) -> Html:
    return badge(STATUS_LABEL.get(user.employment_status, user.employment_status), STATUS_TONE.get(user.employment_status, ""))


def _role_badge(user: User) -> Html:
    return badge(_role_label(user), "" if user.is_service_account else ROLE_TONE[_role(user)])


@router.get("", response_class=HTMLResponse)
async def list_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    rows = []
    users = sorted(state.users.values(), key=lambda u: u.user_id)
    for u in users:
        locks = _locks(u)
        rows.append([
            Html(f'<span class="namecell">{avatar(u.user_id, u.full_name, "sm")}<span><b>{escape(u.full_name)}</b>'
                 f"<small>{escape(u.username)}</small></span></span>"),
            u.user_id,
            Html(f'{escape(u.title)}<br><small class="muted">{escape(u.department)}</small>'),
            _role_badge(u),
            u.manager_id or DASH,
            _status_badge(u),
            badge(", ".join(locks), "bad") if locks else Html('<span class="muted">không</span>'),
            Html(f'<a class="btn sm" href="/console/nhan-vien/{escape(u.user_id)}">Quản lý</a>'),
        ])  # fmt: skip
    toolbar = (
        f'<div class="toolbar"><label class="search">{icon("search", 16)}<input type="search" data-loc="bang-nv" '
        'placeholder="Tìm theo tên, mã, phòng ban, vai trò…" aria-label="Tìm nhân viên"></label>'
        f'<span class="count" id="dem-loc">{len(users)} người</span><span class="grow"></span>'
        f'<a class="btn pri" href="/console/nhan-vien/them">{icon("plus", 16)} Thêm nhân viên</a></div>'
    )
    bang = table(["Nhân viên", "Mã", "Chức danh / phòng ban", "Vai trò", "Quản lý", "Trạng thái", "Đang khoá", ""], rows)
    log = "".join(
        f"<li><time>{escape(_vn(at))}</time><span>{escape(text)}</span></li>" for at, text in reversed(state.admin_log[-50:])
    )
    body = (
        f"{_notice(request)}{NOTE}"
        + card("", f'{toolbar}<div id="bang-nv">{bang}</div>')
        + card("Nhật ký thao tác", f'<ul class="log">{log or "<li class=muted>(chưa có)</li>"}</ul>',
               sub="Mọi lần thêm / sửa / tắt / bật / mở khoá ở trang này, mới nhất trên cùng.")
    )  # fmt: skip
    return _admin_page(state, "Quản trị nhân viên (AD)", body,
                       subtitle="Thêm, sửa, tắt / bật tài khoản và mở khoá — ServiceDesk AI đọc thay đổi ở lần đăng nhập kế tiếp.")  # fmt: skip


def _create_body(state: MockState, form: dict[str, str], errors: list[str] | None = None) -> str:
    form_html = _person_form(state, "/console/nhan-vien/them", form, user=None, submit="Tạo tài khoản")
    return (
        BACK + "".join(_err(e) for e in errors or []) + NOTE
        + card("Thông tin nhân viên mới", form_html, sub="Mã nhân viên tự cấp. Đăng nhập được ngay bằng mật khẩu demo chung.")
    )  # fmt: skip


@router.get("/them", response_class=HTMLResponse)
async def create_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    return _admin_page(state, "Thêm nhân viên", _create_body(state, {"role": "employee"}))


@router.post("/them", response_class=HTMLResponse)
async def create(request: Request) -> Any:
    _same_origin(request)
    state = mock_state(request)
    form = await _form(request)
    problems = _check(state, form, user_id=None)
    if problems:
        return _admin_page(state, "Thêm nhân viên", _create_body(state, form, problems), status=400)
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
    return _admin_page(state, f"Nhân viên {user.user_id}", _detail(state, user, _values(user), request))


def _detail(state: MockState, user: User, form: dict[str, str], request: Request, errors: list[str] | None = None) -> str:
    uid = escape(user.user_id)
    if user.employment_status in ("active", "probation"):
        ask = escape(f"Tắt tài khoản của {user.full_name}? Người này sẽ không đăng nhập được nữa (bật lại được).")
        toggle = (f'<form method="post" action="/console/nhan-vien/{uid}/tat" data-hoi="{ask}">'
                  '<button class="btn danger">Tắt tài khoản</button></form>')  # fmt: skip
    elif user.employment_status == "disabled":
        toggle = (f'<form method="post" action="/console/nhan-vien/{uid}/bat">'
                  '<button class="btn pri">Bật lại tài khoản</button></form>')  # fmt: skip
    else:
        toggle = '<span class="muted">Đã nghỉ việc — không bật lại ở đây.</span>'
    profile = card(
        "",
        f'<div class="profile">{avatar(user.user_id, user.full_name, "lg")}<div class="who"><b>{escape(user.full_name)}</b>'
        f'<div class="meta"><span class="muted">{uid} · {escape(user.username)}</span>{_role_badge(user)}'
        f'{_status_badge(user)}</div></div><span class="grow"></span>{toggle}</div>',
    )
    manager = state.users.get(user.manager_id) if user.manager_id else None
    manager_text = DASH if user.manager_id is None else (
        f"{user.manager_id} — {manager.full_name}" if manager else user.manager_id
    )  # fmt: skip
    info = card(
        "Thông tin",
        '<dl class="kv">'
        f"<dt>Chức danh</dt><dd>{escape(user.title)}</dd><dt>Phòng ban</dt><dd>{escape(user.department)}</dd>"
        f"<dt>Người quản lý</dt><dd>{escape(manager_text)}</dd>"
        f"<dt>Số điện thoại</dt><dd>{escape(mask_phone(user.phone) if user.phone else DASH)}</dd>"
        f"<dt>Email</dt><dd>{escape(mask_email(user.email) if user.email else DASH)}</dd>"
        f"<dt>Ngày vào làm</dt><dd>{escape(user.hired_at.strftime('%d/%m/%Y'))}</dd></dl>",
        sub="Số điện thoại và email hiện dạng đã che.",
    )
    lock_rows = "".join(
        f'<div class="lockrow"><span>{icon("lock", 15)} <b>{escape(kind)}</b> — khoá do {escape(LOCK_REASON.get(a.lock_reason or "", a.lock_reason or DASH))}</span>'
        f'<form method="post" action="/console/nhan-vien/{uid}/mo-khoa">'
        f'<input type="hidden" name="account_type" value="{escape(kind)}"><button class="btn sm">Mở khoá</button></form></div>'
        for kind, a in user.accounts.items()
        if a.locked
    )
    locks = card(
        "Khoá tài khoản",
        lock_rows or '<p class="muted" style="margin:0">Không có tài khoản nào đang khoá.</p>',
        sub="Bị khoá khi nhập sai nhiều lần. Mở khoá ở đây, hoặc nhân viên nhắn ServiceDesk AI.",
    )
    edit = card("Sửa thông tin", _person_form(state, f"/console/nhan-vien/{user.user_id}/sua", form, user=user, submit="Lưu"))
    return (
        f"{BACK}{_notice(request)}{''.join(_err(e) for e in errors or [])}"
        f'{profile}<div class="cols">{info}{locks}</div>{edit}'
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
        return _admin_page(state, f"Nhân viên {user.user_id}", _detail(state, user, shown, request, problems), status=400)
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
