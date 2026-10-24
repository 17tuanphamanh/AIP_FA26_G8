"""Màn xem trạng thái hệ thống giả lập (mock console) — để demo trước/sau khi agent xử lý ticket.

HTML dựng ở server, tối giản, tự làm mới 5 giây, CHỈ ĐỌC (mọi route là GET, không đổi state). Chỉ phục vụ khi `APP_ENV` ∈
{dev, test} — biến thiếu hoặc giá trị khác (prod, staging…) → 404 như thể route không tồn tại. Đọc `APP_ENV` mỗi request
(không cache) để test đổi được bằng monkeypatch.

Mật khẩu: chỉ trang `/console/phone/{user_id}` (điện thoại của nhân viên) hiện mật khẩu tạm, và chỉ SMS gửi tới đúng số của
user đó. Mọi trang khác dùng `OutboxMessage.view()` (đã che) hoặc không đụng tới nội dung tin; `password_hash` không bao giờ in.

Giới hạn do state hiện có:
- `User` chưa có địa chỉ email → cột email hiện "—"; số điện thoại được che.
- `CallLog` chỉ giữ bộ đếm theo (method, path) và mã trả về, không có mốc thời gian/thứ tự → trang lời gọi liệt kê theo
  endpoint kèm mã, không có cột "lúc nào". Các lời gọi tới `/console` được ẩn khỏi trang này (màn tự làm mới 5 giây).
"""

import os
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.ad import mock_state
from app.admin_calls import CallLog
from app.fileserver import permission_view
from app.notify import mask_phone
from app.state import Connection, MockState, User
from app.vpn import cert_view

CONSOLE_ENVS = frozenset({"dev", "test"})
REFRESH_SECONDS = 5
VN_TZ = timezone(timedelta(hours=7))
DASH = "—"


def _require_dev_env() -> None:
    if os.environ.get("APP_ENV") not in CONSOLE_ENVS:
        raise HTTPException(404)


router = APIRouter(prefix="/console", dependencies=[Depends(_require_dev_env)])

_CSS = """
body{font:14px/1.45 system-ui,sans-serif;margin:0;color:#1c2330;background:#f6f7f9}
.banner{background:#b42318;color:#fff;font-weight:700;text-align:center;padding:6px;letter-spacing:.06em}
main{padding:16px 20px}
nav a{margin-right:12px}
table{border-collapse:collapse;margin:8px 0 20px;background:#fff}
th,td{border:1px solid #d0d5dd;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#eaecf0}
.muted{color:#667085}
pre{margin:0;white-space:pre-wrap;font:inherit}
"""


def _vn(at: datetime | None) -> str:
    return DASH if at is None else at.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")


def _yes(flag: bool) -> str:
    return "có" if flag else "không"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]], empty: str = "(trống)") -> str:
    """Mọi ô được escape ở đây — caller đưa chuỗi thô."""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows)
    if not body:
        body = f'<tr><td colspan="{len(headers)}" class="muted">{escape(empty)}</td></tr>'
    return f"<table><tr>{head}</tr>{body}</table>"


def _page(state: MockState, title: str, body: str) -> HTMLResponse:
    html = (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
        f"<title>{escape(title)} — mock console</title><style>{_CSS}</style></head><body>"
        '<div class="banner">MÔI TRƯỜNG GIẢ LẬP</div><main>'
        '<nav><a href="/console">Mục lục</a></nav>'
        f"<h1>{escape(title)}</h1>"
        f'<p class="muted">Giờ VN: {escape(_vn(state.now()))} (UTC+7) · tự làm mới mỗi {REFRESH_SECONDS} giây · chỉ đọc</p>'
        f"{body}</main></body></html>"
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _temp_password_live(state: MockState, user: User) -> bool:
    expires = user.temp_password_expires_at
    return user.must_change_password and expires is not None and state.now() < expires


# ---- C1 ------------------------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    state = mock_state(request)
    pages = [
        ("/console/ad", "Tài khoản AD"),
        ("/console/vpn", "VPN: chứng chỉ, kết nối"),
        ("/console/fileserver", "File server: quyền"),
        ("/console/software", "Phần mềm: máy, license"),
        ("/console/outbox", "Hộp thư đi (SMS/email, mật khẩu đã che)"),
        ("/console/calls", "Lời gọi tới mock theo endpoint"),
    ]
    links = "<ul>" + "".join(f'<li><a href="{escape(u)}">{escape(t)}</a></li>' for u, t in pages) + "</ul>"
    phones = "<ul>" + "".join(
        f'<li><a href="/console/phone/{escape(u.user_id)}">{escape(u.user_id)} — {escape(u.full_name)}</a></li>'
        for u in sorted(state.users.values(), key=lambda u: u.user_id)
    ) + "</ul>"
    body = (
        f"{links}<h2>Điện thoại của nhân viên</h2>"
        '<p class="muted">Trang này hiện mật khẩu tạm trong SMS của đúng nhân viên đó.</p>'
        f"{phones}"
    )
    return _page(state, "Mock console", body)


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
            DASH,  # state chưa có email
            DASH if u.phone is None else mask_phone(u.phone),
            f"{u.employment_status} / AD {'bật' if ad.enabled else 'tắt'}",
            ", ".join(locked) if locked else "không",
            _vn(ad.password_last_set),
            _yes(u.must_change_password),
            _yes(_temp_password_live(state, u)),
        ])  # fmt: skip
    table = _table(
        ["user_id", "Tên", "Email (che)", "SĐT (che)", "Trạng thái", "Khoá", "password_last_set",
         "Phải đổi mật khẩu", "Có mật khẩu tạm còn hạn"],
        rows,
    )  # fmt: skip
    return _page(state, "Active Directory", table)


# ---- C3 ------------------------------------------------------------------------------------------


@router.get("/vpn", response_class=HTMLResponse)
async def vpn_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    certs = []
    for c in sorted(state.certs, key=lambda c: c.serial):
        v = cert_view(state, c)
        certs.append([c.serial, c.user_id, c.device_id, _vn(c.issued_at), _vn(c.expires_at), v["status"],
                      str(v["days_to_expiry"])])  # fmt: skip
    latest: dict[tuple[str, str], Connection] = {}
    for conn in sorted(state.connections, key=lambda x: x.at):
        latest[(conn.user_id, conn.device_id)] = conn  # sắp tăng dần → ghi đè = bản mới nhất
    conns = [
        [c.user_id, c.device_id, _vn(c.at), c.result, c.error_code or DASH]
        for c in sorted(latest.values(), key=lambda x: x.at, reverse=True)
    ]
    body = (
        "<h2>Chứng chỉ</h2>"
        + _table(["Serial", "user_id", "Máy", "Cấp lúc", "Hết hạn", "Trạng thái", "Số ngày tới hạn"], certs)
        + "<h2>Kết nối gần nhất (mỗi người/máy)</h2>"
        + _table(["user_id", "Máy", "Lúc", "Kết quả", "Mã lỗi"], conns)
    )
    return _page(state, "VPN", body)


@router.get("/fileserver", response_class=HTMLResponse)
async def fileserver_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    rows = []
    for p in sorted(state.permissions, key=lambda p: (p.user_id, p.path)):
        res = state.resources.get(p.path)
        v = permission_view(state, p)
        rows.append([p.user_id, p.path, p.level, DASH if res is None else res.sensitivity,
                     _vn(p.granted_at), "không hết hạn" if p.expires_at is None else _vn(p.expires_at),
                     v["status"]])  # fmt: skip
    table = _table(["user_id", "Thư mục", "Mức quyền", "Độ nhạy", "Cấp lúc", "Hết hạn", "Trạng thái"], rows)
    return _page(state, "File server", table)


@router.get("/software", response_class=HTMLResponse)
async def software_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    by_device: dict[str, list[str]] = {d: [] for d in sorted(state.devices)}
    for i in sorted(state.installed, key=lambda i: i.name):
        by_device.setdefault(i.device_id, []).append(f"{i.name} {i.version}")
    machines = []
    for device_id, items in by_device.items():
        d = state.devices.get(device_id)
        machines.append([device_id, DASH if d is None else d.owner_id, ", ".join(items) if items else DASH])
    licenses = []
    for pool in sorted(state.licenses.values(), key=lambda p: p.name):
        holders = ", ".join(a.get("user_id", DASH) for a in pool.assignments)
        licenses.append([pool.name, str(pool.total), str(pool.used), str(pool.total - pool.used), holders or DASH])
    body = (
        "<h2>Máy → phần mềm đã cài</h2>"
        + _table(["Máy", "Chủ máy", "Đã cài"], machines)
        + "<h2>License trả phí</h2>"
        + _table(["Phần mềm", "Tổng", "Đã dùng", "Còn lại", "Người giữ (nếu có ghi nhận)"], licenses)
    )
    return _page(state, "Phần mềm", body)


# ---- C4 ------------------------------------------------------------------------------------------


@router.get("/outbox", response_class=HTMLResponse)
async def outbox_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    rows = []
    for m in reversed(state.outbox):
        v = m.view()  # đã che mật khẩu tạm — không dùng m.body ở trang này
        rows.append([_vn(m.at), v["channel"], v["to"], v["body"]])
    table = _table(["Lúc", "Kênh", "Tới", "Nội dung (mật khẩu đã che)"], rows, empty="(chưa có tin nào)")
    return _page(state, "Hộp thư đi", table)


# ---- C5 ------------------------------------------------------------------------------------------


@router.get("/phone/{user_id}", response_class=HTMLResponse)
async def phone_page(user_id: str, request: Request) -> HTMLResponse:
    """"Điện thoại của nhân viên": SMS gửi tới số của đúng user này, mật khẩu tạm HIỆN RÕ (như người nhận thấy trên máy)."""
    state = mock_state(request)
    user = state.users.get(user_id)
    if user is None:
        raise HTTPException(404)
    if user.phone is None:
        return _page(state, f"Điện thoại của {user.full_name}", "<p>Không có số điện thoại trong hồ sơ.</p>")
    rows = [
        [_vn(m.at), m.body]
        for m in reversed(state.outbox)
        if m.channel == "sms" and m.to == user.phone
    ]
    head = f"<p>{escape(user.full_name)} ({escape(user.user_id)}) · số {escape(user.phone)}</p>"
    table = _table(["Lúc", "Tin nhắn SMS"], rows, empty="(chưa có SMS nào)")
    return _page(state, f"Điện thoại của {user.full_name}", head + table)


# ---- C6 ------------------------------------------------------------------------------------------


@router.get("/calls", response_class=HTMLResponse)
async def calls_page(request: Request) -> HTMLResponse:
    state = mock_state(request)
    calls: CallLog = request.app.state.calls
    rows = []
    for r in calls.view("/", None)["calls"]:
        if r["path"].startswith("/console"):
            continue
        codes = ", ".join(f"{code} ×{n}" for code, n in r["statuses"].items())
        rows.append([r["method"], r["path"], str(r["count"]), codes or DASH])
    table = _table(["Method", "Endpoint", "Số lần tới", "Mã trả về (số lần)"], rows, empty="(chưa có lời gọi nào)")
    note = '<p class="muted">Bộ đếm không lưu thời điểm — hiện theo endpoint. Xoá bằng POST /_admin/calls/reset.</p>'
    return _page(state, "Lời gọi tới mock", note + table)

