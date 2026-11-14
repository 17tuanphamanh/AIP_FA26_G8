"""Màn xem trạng thái hệ thống giả lập (mock console) — để demo trước/sau khi agent xử lý ticket.

HTML dựng ở server, tự làm mới 5 giây (script thay phần nội dung, không tải lại cả trang; tắt JS thì về `<meta refresh>`), CHỈ
ĐỌC (mọi route là GET, không đổi state). Chỉ phục vụ khi CẢ HAI: `APP_ENV` ∈ {dev, test} VÀ cờ `MOCK_CONSOLE_ENABLED` bật (đúng
`1` hoặc `true`; mặc định TẮT — P5 tuần 8). Thiếu một trong hai (biến thiếu, giá trị khác như prod/staging, `0`, `yes`…) → 404
như thể route không tồn tại, ở `/console` và MỌI trang con (dependency của router). Đọc hai biến mỗi request (không cache) để
test đổi được bằng monkeypatch. Khung giao diện (thanh tab, CSS, script) ở `console_ui.py` (làm lại 14/11 cho dễ nhìn, dễ mở).

Mật khẩu: chỉ trang `/console/phone/{user_id}` (điện thoại của nhân viên) hiện mật khẩu tạm, và chỉ SMS gửi tới đúng số của
user đó. Mọi trang khác dùng `OutboxMessage.view()` (đã che) hoặc không đụng tới nội dung tin; `password_hash` không bao giờ in.
Trang chọn máy `/console/phone` chỉ đếm số tin, không in nội dung.

Giới hạn do state hiện có:
- Email AD và số điện thoại đều hiện dạng đã che (`notify.mask_email`, `mask_phone`); user không có email → "—".
- `CallLog` chỉ giữ bộ đếm theo (method, path) và mã trả về, không có mốc thời gian/thứ tự → trang lời gọi liệt kê theo
  endpoint kèm mã, không có cột "lúc nào". Các lời gọi tới `/console` (màn tự làm mới 5 giây) và `/favicon.ico` (trình
  duyệt tự xin) được ẩn khỏi trang này.
"""

import os
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.ad import mock_state
from app.admin_calls import CallLog
from app.console_ui import Html, avatar, badge, card, icon, shell, table
from app.fileserver import permission_view
from app.notify import OutboxMessage, mask_email, mask_phone
from app.state import Connection, MockState, User
from app.vpn import cert_view

CONSOLE_ENVS = frozenset({"dev", "test"})
CONSOLE_FLAG = "MOCK_CONSOLE_ENABLED"
CONSOLE_FLAG_ON = frozenset({"1", "true"})
REFRESH_SECONDS = 5
VN_TZ = timezone(timedelta(hours=7))
DASH = "—"


def _require_dev_env() -> None:
    if os.environ.get("APP_ENV") not in CONSOLE_ENVS or os.environ.get(CONSOLE_FLAG) not in CONSOLE_FLAG_ON:
        raise HTTPException(404)


router = APIRouter(prefix="/console", dependencies=[Depends(_require_dev_env)])


def _vn(at: datetime | None) -> str:
    return DASH if at is None else at.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")


def _hm(at: datetime) -> str:
    return at.astimezone(VN_TZ).strftime("%H:%M · %d/%m")


def _yes(flag: bool) -> str:
    return "có" if flag else "không"


def _page(
    state: MockState,
    title: str,
    body: str,
    *,
    admin: bool = False,
    status: int = 200,
    active: str = "",
    subtitle: str = "",
) -> HTMLResponse:
    """`admin` (D-97 — trang quản trị nhân viên `console_admin`): KHÔNG tự làm mới (đang gõ form thì không mất chữ)."""
    html = shell(
        title=title, subtitle=subtitle, clock=f"Giờ VN {_vn(state.now())}", body=body, active=active, live=not admin
    )
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


def _temp_password_live(state: MockState, user: User) -> bool:
    expires = user.temp_password_expires_at
    return user.must_change_password and expires is not None and state.now() < expires


def _sms_of(state: MockState, user: User) -> list[OutboxMessage]:
    """SMS tới đúng số của user, cũ → mới."""
    if user.phone is None:
        return []
    return [m for m in state.outbox if m.channel == "sms" and m.to == user.phone]


def _status_badge(user: User) -> Html:
    tone = {"active": "ok", "probation": "info", "disabled": "", "terminated": "bad"}.get(user.employment_status, "")
    ad = "bật" if user.accounts["ad"].enabled else "tắt"
    return badge(f"{user.employment_status} / AD {ad}", tone)


def _people_grid(state: MockState) -> Html:
    """Ô chọn "điện thoại của nhân viên": người vừa có SMS lên đầu. Chỉ đếm tin — KHÔNG in nội dung hay số điện thoại."""
    cards = []
    users = sorted(state.users.values(), key=lambda u: u.user_id)
    latest = {u.user_id: (sms[-1].at if (sms := _sms_of(state, u)) else None) for u in users}
    users.sort(key=lambda u: -t.timestamp() if (t := latest[u.user_id]) else float("inf"))  # sort ổn định: còn lại theo mã
    for u in users:
        n = len(_sms_of(state, u))
        if u.phone is None:
            tag = badge("không có số")
        elif n:
            tag = badge(f"{n} SMS", "warn")
        else:
            tag = Html("")
        cards.append(
            f'<a class="person{" new" if n else ""}" href="/console/phone/{escape(u.user_id)}">'
            f"{avatar(u.user_id, u.full_name)}<span class=\"who\"><b>{escape(u.full_name)}</b>"
            f"<small>{escape(u.user_id)} · {escape(u.username)}</small></span>{tag}</a>"
        )
    return Html(f'<div class="people">{"".join(cards)}</div>')


# ---- C1 ------------------------------------------------------------------------------------------


_TILES = [
    ("/console/nhan-vien", "users", "", "Quản trị nhân viên", "Thêm, sửa, tắt / bật, mở khoá tài khoản"),
    ("/console/phone", "phone", "or", "Điện thoại nhân viên", "SMS mật khẩu tạm trên máy từng người"),
    ("/portal", "login", "gr", "Cổng đăng nhập công ty", "Nhân viên đổi mật khẩu tạm ở đây"),
    ("/console/ad", "key", "", "Tài khoản AD", "Trạng thái, khoá, cờ mật khẩu tạm"),
    ("/console/vpn", "globe", "", "VPN", "Chứng chỉ và lần kết nối gần nhất"),
    ("/console/fileserver", "folder", "", "File server", "Quyền thư mục, hạn quyền"),
    ("/console/software", "box", "", "Phần mềm", "Máy đã cài gì, license còn bao nhiêu"),
    ("/console/outbox", "mail", "", "Hộp thư đi", "SMS / email đã gửi (mật khẩu đã che)"),
    ("/console/calls", "activity", "", "Lời gọi API", "ServiceDesk AI đã gọi gì, mã trả về"),
]


@router.get("", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    state = mock_state(request)
    people = [u for u in state.users.values() if not u.is_service_account]
    working = sum(u.employment_status in ("active", "probation") for u in people)
    locked = sum(any(a.locked for a in u.accounts.values()) for u in state.users.values())
    cert_status = [cert_view(state, c)["status"] for c in state.certs]
    bad_certs = sum(s != "valid" for s in cert_status)
    sms = sum(m.channel == "sms" for m in state.outbox)
    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="k">Nhân viên</div><div class="v">{len(people)}</div>'
        f'<div class="s">{working} đang làm việc</div></div>'
        f'<div class="stat{" bad" if locked else ""}"><div class="k">Tài khoản đang khoá</div><div class="v">{locked}</div>'
        '<div class="s">mở ở trang Quản trị nhân viên</div></div>'
        f'<div class="stat{" warn" if bad_certs else ""}"><div class="k">Chứng chỉ VPN hết hạn / thu hồi</div>'
        f'<div class="v">{bad_certs}</div><div class="s">trên {len(cert_status)} chứng chỉ</div></div>'
        f'<div class="stat"><div class="k">Tin đã gửi</div><div class="v">{len(state.outbox)}</div>'
        f'<div class="s">{sms} SMS · {len(state.outbox) - sms} email</div></div></div>'
    )
    tiles = "".join(
        f'<a class="tile" href="{escape(href)}"{" target=_blank rel=noopener" if href == "/portal" else ""}>'
        f'<span class="ic {tone}">{icon(ic, 20)}</span><span><b>{escape(name)}</b><span class="d">{escape(desc)}</span></span></a>'
        for href, ic, tone, name, desc in _TILES
    )
    body = (
        f'{stats}<h3>Các trang</h3><div class="tiles">{tiles}</div>'
        + card(
            "Điện thoại của nhân viên",
            _people_grid(state),
            sub="Bấm vào một người để xem SMS trên máy của họ — mật khẩu tạm chỉ hiện ở trang điện thoại của đúng người đó.",
        )
    )
    return _page(state, "Tổng quan", body, active="tong-quan",
                 subtitle="Trạng thái các hệ thống ngoài — mở song song với ServiceDesk AI để xem trước / sau khi agent xử lý.")  # fmt: skip


# ---- C2 ------------------------------------------------------------------------------------------


@router.get("/ad", response_class=HTMLResponse)
async def ad_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    rows = []
    for u in sorted(state.users.values(), key=lambda u: u.user_id):
        ad = u.accounts["ad"]
        locked = [f"{kind} ({a.lock_reason or DASH})" for kind, a in u.accounts.items() if a.locked]
        rows.append([
            u.user_id,
            u.full_name,
            DASH if u.email is None else mask_email(u.email),  # có thể là địa chỉ thật (seed.local.json)
            DASH if u.phone is None else mask_phone(u.phone),
            _status_badge(u),
            badge(", ".join(locked), "bad") if locked else "không",
            _vn(ad.password_last_set),
            _yes(u.must_change_password),
            _yes(_temp_password_live(state, u)),
        ])  # fmt: skip
    bang = table(
        ["user_id", "Tên", "Email (che)", "SĐT (che)", "Trạng thái", "Khoá", "password_last_set",
         "Phải đổi mật khẩu", "Có mật khẩu tạm còn hạn"],
        rows,
    )  # fmt: skip
    return _page(state, "Tài khoản AD", card("", bang, flush=True), active="ad",
                 subtitle="Email và số điện thoại đã che. Mật khẩu không bao giờ hiện ở đây — chỉ có cờ mật khẩu tạm.")  # fmt: skip


# ---- C3 ------------------------------------------------------------------------------------------


_CERT_TONE = {"valid": "ok", "expired": "bad", "revoked": "bad"}


@router.get("/vpn", response_class=HTMLResponse)
async def vpn_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    certs = []
    for c in sorted(state.certs, key=lambda c: c.serial):
        v = cert_view(state, c)
        certs.append([c.serial, c.user_id, c.device_id, _vn(c.issued_at), _vn(c.expires_at),
                      badge(v["status"], _CERT_TONE.get(v["status"], "")), str(v["days_to_expiry"])])  # fmt: skip
    latest: dict[tuple[str, str], Connection] = {}
    for conn in sorted(state.connections, key=lambda x: x.at):
        latest[(conn.user_id, conn.device_id)] = conn  # sắp tăng dần → ghi đè = bản mới nhất
    conns = [
        [c.user_id, c.device_id, _vn(c.at), badge(c.result, "ok" if c.result == "success" else "bad"),
         Html(f'<span class="mono">{escape(c.error_code)}</span>') if c.error_code else DASH]
        for c in sorted(latest.values(), key=lambda x: x.at, reverse=True)
    ]  # fmt: skip
    body = card(
        "Chứng chỉ", table(["Serial", "user_id", "Máy", "Cấp lúc", "Hết hạn", "Trạng thái", "Số ngày tới hạn"], certs),
        flush=True,
    ) + card("Kết nối gần nhất (mỗi người / máy)", table(["user_id", "Máy", "Lúc", "Kết quả", "Mã lỗi"], conns), flush=True)
    return _page(state, "VPN", body, active="vpn", subtitle="Gia hạn chứng chỉ qua ServiceDesk AI rồi xem trạng thái đổi ở đây.")


_SENS_TONE = {"high": "bad", "medium": "warn", "low": ""}


@router.get("/fileserver", response_class=HTMLResponse)
async def fileserver_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    rows = []
    for p in sorted(state.permissions, key=lambda p: (p.user_id, p.path)):
        res = state.resources.get(p.path)
        v = permission_view(state, p)
        rows.append([p.user_id, Html(f'<span class="mono">{escape(p.path)}</span>'), p.level,
                     DASH if res is None else badge(res.sensitivity, _SENS_TONE.get(res.sensitivity, "")),
                     _vn(p.granted_at), "không hết hạn" if p.expires_at is None else _vn(p.expires_at),
                     badge(v["status"], "ok" if v["status"] == "active" else "bad")])  # fmt: skip
    bang = table(["user_id", "Thư mục", "Mức quyền", "Độ nhạy", "Cấp lúc", "Hết hạn", "Trạng thái"], rows)
    return _page(state, "File server", card("Quyền truy cập thư mục", bang, flush=True), active="fileserver",
                 subtitle="Quyền theo người dùng; thư mục độ nhạy cao cần duyệt trước khi cấp.")  # fmt: skip


@router.get("/software", response_class=HTMLResponse)
async def software_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    by_device: dict[str, list[str]] = {d: [] for d in sorted(state.devices)}
    for i in sorted(state.installed, key=lambda i: i.name):
        by_device.setdefault(i.device_id, []).append(f"{i.name} {i.version}")
    machines = []
    for device_id, items in by_device.items():
        d = state.devices.get(device_id)
        chips = Html('<div class="chips">' + "".join(f'<span class="chip">{escape(x)}</span>' for x in items) + "</div>")
        machines.append([Html(f"<b>{escape(device_id)}</b>"), DASH if d is None else d.owner_id, chips if items else DASH])
    licenses = []
    for pool in sorted(state.licenses.values(), key=lambda p: p.name):
        holders = ", ".join(a.get("user_id", DASH) for a in pool.assignments)
        left = pool.total - pool.used
        licenses.append([pool.name, str(pool.total), str(pool.used), badge(str(left), "ok" if left > 0 else "bad"),
                         holders or DASH])  # fmt: skip
    body = card("Máy → phần mềm đã cài", table(["Máy", "Chủ máy", "Đã cài"], machines), flush=True) + card(
        "License trả phí", table(["Phần mềm", "Tổng", "Đã dùng", "Còn lại", "Người giữ (nếu có ghi nhận)"], licenses),
        flush=True,
    )
    return _page(state, "Phần mềm", body, active="software",
                 subtitle="Cài phần mềm qua ServiceDesk AI rồi xem máy và license đổi ở đây.")  # fmt: skip


# ---- C4 ------------------------------------------------------------------------------------------


@router.get("/outbox", response_class=HTMLResponse)
async def outbox_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    rows = []
    for m in reversed(state.outbox):
        v = m.view()  # đã che mật khẩu tạm — không dùng m.body ở trang này
        tone = "info up" if v["channel"] == "sms" else "up"
        rows.append([_vn(m.at), badge(v["channel"], tone), v["to"], Html(f"<pre>{escape(v['body'])}</pre>")])
    bang = table(["Lúc", "Kênh", "Tới", "Nội dung (mật khẩu đã che)"], rows, empty="(chưa có tin nào)")
    return _page(state, "Hộp thư đi", card("", bang, flush=True), active="outbox",
                 subtitle="Mọi SMS / email hệ thống đã gửi, mới nhất trên cùng. Muốn thấy mật khẩu tạm: xem trang Điện thoại.")  # fmt: skip


# ---- C5 ------------------------------------------------------------------------------------------


@router.get("/phone", response_class=HTMLResponse)
async def phone_pick_page(request: Request) -> HTMLResponse:
    """Chọn máy của một nhân viên. Chỉ đếm số SMS — không in nội dung, không in số điện thoại."""
    state = mock_state(request)
    return _page(state, "Điện thoại của nhân viên", _people_grid(state), active="dien-thoai",
                 subtitle="Người vừa nhận SMS hiện ở đầu (viền cam). Bấm vào để mở máy của người đó.")  # fmt: skip


def _bubble(m: OutboxMessage) -> str:
    text = escape(m.body)
    copy = ""
    if m.secret:
        text = text.replace(escape(m.secret), f'<span class="otp">{escape(m.secret)}</span>')
        copy = (f'<button class="btn sm copy" type="button" data-copy="{escape(m.secret)}">Sao chép mật khẩu tạm</button>')  # fmt: skip
    return f'<div class="msg">{text}<time>{escape(_hm(m.at))}</time>{copy}</div>'


@router.get("/phone/{user_id}", response_class=HTMLResponse)
async def phone_page(user_id: str, request: Request) -> HTMLResponse:
    """"Điện thoại của nhân viên": SMS gửi tới số của đúng user này, mật khẩu tạm HIỆN RÕ (như người nhận thấy trên máy)."""
    state = mock_state(request)
    user = state.users.get(user_id)
    if user is None:
        raise HTTPException(404)
    title = f"Điện thoại của {user.full_name}"
    options = "".join(
        f'<option value="/console/phone/{escape(u.user_id)}"{" selected" if u.user_id == user.user_id else ""}>'
        f"{escape(u.full_name)} ({escape(u.user_id)})</option>"
        for u in sorted(state.users.values(), key=lambda u: u.user_id)
    )
    picker = f'<select class="pick" data-di-toi aria-label="Xem máy của người khác">{options}</select>'
    if user.phone is None:
        body: str = card("", f'<p>Không có số điện thoại trong hồ sơ — người này không nhận được SMS.</p>{picker}')
        return _page(state, title, body, active="dien-thoai")
    sms = _sms_of(state, user)
    screen = "".join(_bubble(m) for m in sms) or '<div class="none">(chưa có SMS nào)</div>'
    now = state.now().astimezone(VN_TZ).strftime("%H:%M")
    phone = (
        '<div class="phone"><div class="in">'
        f'<div class="st"><span>{escape(now)}</span><span class="island"></span><span>4G ▮▮▮</span></div>'
        f'<div class="hd">{avatar("svc", "Service Desk", "sm")}<b>Service Desk</b><small>Tin nhắn SMS</small></div>'
        f'<div class="screen">{screen}</div></div></div>'
    )
    expires = user.temp_password_expires_at
    if _temp_password_live(state, user) and expires is not None:
        temp = badge(f"còn hạn đến {expires.astimezone(VN_TZ).strftime('%H:%M')}", "warn")
    elif user.must_change_password:
        temp = badge("đã hết hạn", "bad")
    else:
        temp = badge("không có")
    info = card(
        "",
        f'<div class="profile">{avatar(user.user_id, user.full_name, "lg")}<div class="who"><b>{escape(user.full_name)}</b>'
        f'<div class="meta"><span class="muted">{escape(user.user_id)} · {escape(user.username)}</span></div></div></div>'
        f'<dl class="kv" style="margin-top:16px"><dt>Số máy</dt><dd class="mono">{escape(user.phone)}</dd>'
        f"<dt>SMS đã nhận</dt><dd>{len(sms)}</dd><dt>Mật khẩu tạm</dt><dd>{temp}</dd></dl>",
    )
    guide = card(
        "Demo đặt lại mật khẩu qua SMS",
        '<ol class="steps"><li>Đăng nhập ServiceDesk AI bằng tài khoản người này, nhắn yêu cầu đặt lại mật khẩu và chọn nhận qua SMS.</li>'
        "<li>Tin có mật khẩu tạm hiện trên máy bên trái (trang tự cập nhật).</li>"
        "<li>Mở Cổng đăng nhập công ty, đăng nhập bằng mật khẩu tạm rồi đặt mật khẩu mới.</li></ol>"
        '<div class="actions"><a class="btn pri" href="/portal" target="_blank" rel="noopener">Mở Cổng đăng nhập ↗</a></div>',
    )
    switch = card("Xem máy của người khác", picker)
    body = f'<div class="phone-wrap">{phone}<div>{info}{guide}{switch}</div></div>'
    return _page(state, title, body, active="dien-thoai", subtitle="Như màn hình điện thoại thật của người nhận.")


# ---- C6 ------------------------------------------------------------------------------------------


def _code_tone(code: str) -> str:
    return "ok" if code.startswith("2") else ("warn" if code.startswith("4") else "bad")


@router.get("/calls", response_class=HTMLResponse)
async def calls_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    calls: CallLog = request.app.state.calls
    rows = []
    for r in calls.view("/", None)["calls"]:
        if r["path"].startswith("/console") or r["path"] == "/favicon.ico":  # màn này tự làm mới; favicon là trình duyệt tự xin
            continue
        codes = Html(" ".join(str(badge(f"{code} ×{n}", _code_tone(str(code)))) for code, n in r["statuses"].items()))
        method = badge(r["method"], "info" if r["method"] == "GET" else "warn")
        rows.append([method, Html(f'<span class="mono">{escape(r["path"])}</span>'), str(r["count"]), codes or DASH])
    note = '<p class="sub" style="margin:0;padding:14px 20px 12px">Bộ đếm không lưu thời điểm — hiện theo endpoint. Xoá bằng POST /_admin/calls/reset.</p>'
    bang = table(["Method", "Endpoint", "Số lần tới", "Mã trả về (số lần)"], rows, empty="(chưa có lời gọi nào)")
    return _page(state, "Lời gọi API tới hệ thống giả lập", card("", note + bang, flush=True), active="calls",
                 subtitle="Mỗi lần ServiceDesk AI đọc / ghi hệ thống ngoài đều được đếm ở đây.")  # fmt: skip
