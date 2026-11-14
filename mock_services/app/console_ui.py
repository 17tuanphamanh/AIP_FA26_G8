"""Khung giao diện chung của các trang giả lập (`/console/*`) — CSS, biểu tượng, thanh tab, nhãn màu, script làm mới mềm.

Tách khỏi `console.py` (14/11, TA: "nhìn chán, khó mở khó dùng") để trang dữ liệu chỉ lo nội dung. Không tải tài nguyên ngoài
(không font, không CDN): mọi thứ nằm trong trang. Biểu tượng là nét vẽ SVG kiểu Feather (giấy phép MIT).

Quy ước an toàn giữ như cũ: mọi chuỗi từ state đi qua `escape`; `Html` chỉ để đánh dấu đoạn ĐÃ escape (dựng bằng các hàm ở
đây). Script chỉ làm 4 việc: làm mới mềm 5 giây (thay `#noi-dung`, không tải lại cả trang), tạm dừng, lọc bảng tại chỗ, nút
sao chép trên trang điện thoại. Không gửi gì đi ngoài GET lại chính trang đang mở.
"""

import os
from collections.abc import Iterable, Sequence
from html import escape

APP_WEB_URL_ENV = "APP_WEB_URL"
APP_WEB_URL_DEFAULT = "http://localhost:5173"


class Html(str):
    """Đoạn HTML đã escape xong — `table()` chèn nguyên văn. Chỉ dựng bằng các hàm trong module này."""


def badge(text: str, tone: str = "") -> Html:
    """tone: ok | warn | bad | info | "" (xám). Thêm " up" để in hoa."""
    return Html(f'<span class="b {escape(tone)}">{escape(text)}</span>')


def icon(name: str, size: int = 18) -> Html:
    return Html(
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>'
    )


AVATAR_TONES = 6


def avatar(user_id: str, full_name: str, size: str = "") -> Html:
    words = full_name.split()
    letter = words[-1][0].upper() if words else "?"
    tone = sum(ord(ch) for ch in user_id) % AVATAR_TONES
    return Html(f'<span class="av c{tone} {escape(size)}">{escape(letter)}</span>')


def table(headers: Sequence[str], rows: Iterable[Sequence[str]], empty: str = "(trống)") -> Html:
    """Ô thường được escape ở đây; ô kiểu `Html` chèn nguyên văn. `<table>`, `<th>`, `<td>` để trần (test đọc theo chuỗi)."""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c if isinstance(c, Html) else escape(c)}</td>" for c in row) + "</tr>" for row in rows
    )
    if not body:
        body = f'<tr><td colspan="{len(headers)}" class="muted empty-row">{escape(empty)}</td></tr>'
    return Html(f'<div class="tw"><table><tr>{head}</tr>{body}</table></div>')


def card(title: str, inner: str, *, sub: str = "", flush: bool = False, extra: str = "") -> Html:
    """Khối trắng bo góc. `inner` / `extra` là HTML đã escape; `title`, `sub` là chữ thô."""
    head = f"<h2>{escape(title)}</h2>" if title else ""
    note = f'<p class="sub">{escape(sub)}</p>' if sub else ""
    top = f'<div class="card-head"><div>{head}{note}</div>{extra}</div>' if (head or note or extra) else ""
    return Html(f'<section class="card{" flush" if flush else ""}">{top}{inner}</section>')


# ---- thanh tab -----------------------------------------------------------------------------------------------------------

# (khoá, đường dẫn, nhãn, biểu tượng). Khoá dùng để tô tab đang mở.
TABS: list[tuple[str, str, str, str]] = [
    ("tong-quan", "/console", "Tổng quan", "grid"),
    ("nhan-vien", "/console/nhan-vien", "Quản trị nhân viên", "users"),
    ("dien-thoai", "/console/phone", "Điện thoại", "phone"),
    ("ad", "/console/ad", "Tài khoản AD", "key"),
    ("vpn", "/console/vpn", "VPN", "globe"),
    ("fileserver", "/console/fileserver", "File server", "folder"),
    ("software", "/console/software", "Phần mềm", "box"),
    ("outbox", "/console/outbox", "Hộp thư đi", "mail"),
    ("calls", "/console/calls", "Lời gọi API", "activity"),
]


def app_web_url() -> str:
    return os.environ.get(APP_WEB_URL_ENV) or APP_WEB_URL_DEFAULT


def shell(*, title: str, subtitle: str, clock: str, body: str, active: str, live: bool) -> str:
    """Cả trang. `live` = trang chỉ đọc tự làm mới (trang quản trị thì không — đang gõ form không mất chữ)."""
    tabs = "".join(
        f'<a href="{escape(href)}"{" class=on" if key == active else ""}>{icon(ic, 16)}{escape(label)}</a>'
        for key, href, label, ic in TABS
    )
    refresh = '<noscript><meta http-equiv="refresh" content="5"></noscript>' if live else ""
    if live:
        status = (
            '<span class="live" id="den"></span><span>Tự cập nhật 5 giây</span>'
            '<button class="btn sm" type="button" id="tam-dung">Tạm dừng</button>'
        )
    else:
        status = '<span class="live off"></span><span>Trang quản trị · không tự làm mới</span>'
    sub = f'<p class="sub">{escape(subtitle)}</p>' if subtitle else ""
    return (
        f'<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">{refresh}'
        f"<title>{escape(title)} · Hệ thống giả lập</title><style>{CSS}</style></head>"
        f'<body data-lam-moi="{"1" if live else "0"}">'
        '<header class="top"><div class="bar">'
        f'<a class="brand" href="/console"><span class="logo">{icon("server", 18)}</span>'
        "<span>Hệ thống giả lập<small>Các hệ thống ngoài của Demo Corp mà ServiceDesk AI gọi tới</small></span></a>"
        '<span class="mock">MÔI TRƯỜNG GIẢ LẬP</span><span class="grow"></span>'
        f'<a class="btn" href="/portal" target="_blank" rel="noopener">{icon("login", 16)}Cổng đăng nhập ↗</a>'
        f'<a class="btn pri" href="{escape(app_web_url())}" target="_blank" rel="noopener">Mở ServiceDesk AI ↗</a>'
        f'</div><nav class="tabs" aria-label="Trang giả lập">{tabs}</nav></header>'
        f'<main><div class="head"><div><h1>{escape(title)}</h1>{sub}</div>'
        f'<div class="clock">{status}<span class="sep"></span><span id="dong-ho">{escape(clock)}</span></div></div>'
        f'<div id="noi-dung">{body}</div></main><script>{SCRIPT}</script></body></html>'
    )


# ---- biểu tượng (Feather, MIT) -------------------------------------------------------------------------------------------

_ICONS = {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>'
    '<rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
    '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "phone": '<rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>',
    "key": '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 '
    '7l-3-3m-3.5 3.5L19 4"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 '
    '15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "box": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 '
    '2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
    "mail": '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>'
    '<polyline points="22,6 12,13 2,6"/>',
    "activity": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "login": '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/>'
    '<line x1="15" y1="12" x2="3" y2="12"/>',
    "server": '<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>'
    '<line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "send": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
}


# ---- CSS (bảng màu theo app: chữ #1d1d1f, nền #f5f5f7, xanh FPT #0055a4, cam #f37021) ------------------------------------

CSS = """
:root{--ink:#1d1d1f;--ink2:#6e6e73;--ink3:#aeaeb2;--line:#e5e5ea;--bg:#f5f5f7;--blue:#0055a4;--blue2:#e6eef7;--orange:#f37021;
--ok:#1a7f37;--okb:#e7f5ec;--warn:#8a5a00;--warnb:#fff3d1;--bad:#b42318;--badb:#fdecea;--mut:#5f6368;--mutb:#efeff2}
*{box-sizing:border-box}
html{scroll-padding-top:120px}
body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
color:var(--ink);background:var(--bg);-webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.94);backdrop-filter:saturate(180%) blur(12px);
border-bottom:1px solid var(--line)}
.bar,.tabs,main{max-width:1240px;margin:0 auto;padding-left:24px;padding-right:24px}
.bar{display:flex;align-items:center;gap:14px;min-height:60px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);font-weight:700;font-size:15px;line-height:1.25}
.brand:hover{text-decoration:none}.brand small{display:block;font-weight:400;color:var(--ink2);font-size:12px}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#0055a4,#3b86d6);color:#fff;
display:grid;place-items:center;flex:none}
.mock{background:#fff1e6;color:#b54708;border:1px solid #f8c9a0;border-radius:999px;padding:3px 10px;font-size:11px;
font-weight:700;letter-spacing:.06em;white-space:nowrap}
.grow{flex:1}
.tabs{display:flex;gap:2px;overflow-x:auto;scrollbar-width:thin}
.tabs a{display:flex;align-items:center;gap:7px;padding:10px 12px 11px;color:var(--ink2);font-weight:500;
border-bottom:2px solid transparent;white-space:nowrap}
.tabs a:hover{color:var(--ink);text-decoration:none}.tabs a.on{color:var(--blue);border-bottom-color:var(--blue);font-weight:600}
main{padding-top:26px;padding-bottom:64px}
.head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px}
h1{font-size:26px;line-height:1.2;margin:0;letter-spacing:-.015em}
.sub{margin:6px 0 0;color:var(--ink2)}
.clock{display:flex;align-items:center;gap:9px;color:var(--ink2);font-size:13px;flex-wrap:wrap}
.clock .sep{width:1px;height:16px;background:var(--line)}
.live{width:9px;height:9px;border-radius:50%;background:#34c759;box-shadow:0 0 0 3px rgba(52,199,89,.2);flex:none}
.live.off{background:var(--ink3);box-shadow:none}.live.err{background:var(--bad);box-shadow:0 0 0 3px rgba(180,35,24,.18)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;height:36px;padding:0 14px;border-radius:10px;
border:1px solid #d2d2d7;background:#fff;color:var(--ink);font:inherit;font-weight:600;cursor:pointer;white-space:nowrap}
.btn:hover{background:#f7f7f9;text-decoration:none}
.btn.pri{background:var(--blue);border-color:var(--blue);color:#fff}.btn.pri:hover{background:#00498d}
.btn.danger{color:var(--bad);border-color:#f0b4ad}.btn.danger:hover{background:var(--badb)}
.btn.sm{height:28px;padding:0 10px;font-size:12.5px;border-radius:8px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin-bottom:18px}
.card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.card h2{font-size:16px;margin:0;letter-spacing:-.005em}.card .sub{margin:3px 0 0;font-size:13px}
.card.flush{padding:0;overflow:hidden}.card.flush .card-head{padding:16px 20px 4px;margin:0}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%}
th{background:#fafafb;color:var(--ink2);font-size:12px;font-weight:600;text-align:left;padding:10px 16px;
border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:11px 16px;border-bottom:1px solid #efeff2;vertical-align:middle}
tr:last-child td{border-bottom:0}tr:hover td{background:#fafbfd}
.card:not(.flush) .tw{border:1px solid var(--line);border-radius:12px}
.empty-row{text-align:center;padding:28px 16px}
.b{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;
white-space:nowrap;background:var(--mutb);color:var(--mut);line-height:1.6}
.b.ok{background:var(--okb);color:var(--ok)}.b.warn{background:var(--warnb);color:var(--warn)}
.b.bad{background:var(--badb);color:var(--bad)}.b.info{background:var(--blue2);color:var(--blue)}
.b.up{text-transform:uppercase;letter-spacing:.04em;font-size:11px}
.muted{color:var(--ink2)}
.mono,code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
pre{margin:0;white-space:pre-wrap;font:inherit}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:1px 8px;font-size:12.5px;white-space:nowrap}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-bottom:22px}
.stat{background:#fff;border:1px solid var(--line);border-radius:16px;padding:14px 18px}
.stat .k{color:var(--ink2);font-size:13px}.stat .v{font-size:28px;font-weight:700;line-height:1.2;margin-top:4px;
letter-spacing:-.02em}.stat .s{color:var(--ink2);font-size:12.5px}
.stat.bad .v{color:var(--bad)}.stat.warn .v{color:#b54708}
h3{font-size:13px;font-weight:600;color:var(--ink2);text-transform:uppercase;letter-spacing:.05em;margin:6px 0 10px}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:26px}
.tile{display:flex;gap:12px;align-items:flex-start;background:#fff;border:1px solid var(--line);border-radius:16px;
padding:15px 16px;color:var(--ink);transition:border-color .15s,box-shadow .15s,transform .15s}
.tile:hover{text-decoration:none;border-color:#b6cbe3;box-shadow:0 6px 18px rgba(0,40,90,.08);transform:translateY(-1px)}
.tile .ic{flex:none;width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:var(--blue2);
color:var(--blue)}
.tile .ic.or{background:#fff1e6;color:#c4570f}.tile .ic.gr{background:var(--okb);color:var(--ok)}
.tile b{display:block;font-size:14.5px}.tile span.d{display:block;color:var(--ink2);font-size:13px;margin-top:1px}
.people{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.person{display:flex;align-items:center;gap:11px;background:#fff;border:1px solid var(--line);border-radius:14px;
padding:10px 12px;color:var(--ink)}
.person:hover{border-color:#b6cbe3;text-decoration:none;box-shadow:0 4px 12px rgba(0,40,90,.06)}
.person.new{border-color:#f8c9a0;background:#fffaf5}
.who{flex:1;min-width:0}.who b{display:block;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.who small{color:var(--ink2);font-size:12px}
.av{flex:none;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;color:#fff;font-weight:700;font-size:15px}
.av.lg{width:56px;height:56px;font-size:22px}.av.sm{width:30px;height:30px;font-size:13px}
.c0{background:#0055a4}.c1{background:#e8630a}.c2{background:#1a7f37}.c3{background:#7a3db8}.c4{background:#c2185b}
.c5{background:#00838f}
.namecell{display:flex;align-items:center;gap:10px}.namecell b{display:block;font-weight:600}
.namecell small{color:var(--ink2)}
.alert{padding:11px 14px;border-radius:12px;margin-bottom:16px;font-weight:500;border:1px solid transparent}
.alert.ok{background:var(--okb);color:var(--ok);border-color:#bfe5cb}
.alert.err{background:var(--badb);color:var(--bad);border-color:#f5c2bc}
.alert.info{background:var(--blue2);color:#0b3d73;font-weight:400;border-color:#c9daee}
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.search{position:relative;flex:1;max-width:420px}.search svg{position:absolute;left:11px;top:10px;color:var(--ink3)}
.search input{width:100%;height:38px;padding:0 12px 0 36px;border:1px solid #d2d2d7;border-radius:10px;font:inherit;
background:#fff}
.search input:focus,.fld input:focus,.fld select:focus{outline:none;border-color:var(--blue);
box-shadow:0 0 0 3px rgba(0,85,164,.15)}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 20px}
.fld{display:flex;flex-direction:column;gap:6px;font-weight:600;font-size:13px}
.fld input,.fld select{height:40px;padding:0 12px;border:1px solid #d2d2d7;border-radius:10px;font:inherit;font-weight:400;
background:#fff;color:var(--ink);width:100%}
.fld input[readonly],.fld select[disabled]{background:var(--bg);color:var(--ink2)}
.actions{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap}
.cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.cols>.card{margin-bottom:0}
.cols+.card,.cols+.cols{margin-top:18px}
dl.kv{display:grid;grid-template-columns:140px minmax(0,1fr);gap:10px 14px;margin:0}
dl.kv dt{color:var(--ink2)}dl.kv dd{margin:0;font-weight:500}
.profile{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.profile .who b{font-size:20px}.profile .meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;align-items:center}
.lockrow{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border:1px solid #f5c2bc;
background:#fffafa;border-radius:12px;margin-bottom:8px}
.log{list-style:none;margin:0;padding:0}.log li{display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #efeff2}
.log li:last-child{border-bottom:0}.log time{color:var(--ink2);white-space:nowrap;font-variant-numeric:tabular-nums}
.count{color:var(--ink2);font-size:13px}
.phone-wrap{display:grid;grid-template-columns:360px minmax(0,1fr);gap:28px;align-items:start}
.phone{width:340px;height:660px;border-radius:48px;background:#1c1c1e;padding:11px;
box-shadow:0 24px 60px rgba(0,0,0,.18),inset 0 0 0 2px #3a3a3c}
.phone .in{height:100%;border-radius:38px;background:#fff;overflow:hidden;display:flex;flex-direction:column}
.phone .st{display:flex;justify-content:space-between;align-items:center;padding:14px 26px 6px;font-size:12.5px;font-weight:600}
.phone .island{width:96px;height:26px;border-radius:14px;background:#1c1c1e}
.phone .hd{display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px 16px 12px;border-bottom:1px solid var(--line);
background:#fafafa}
.phone .hd small{color:var(--ink2);font-size:11.5px}
.screen{flex:1;overflow-y:auto;padding:16px 12px;display:flex;flex-direction:column;gap:12px}
.msg{align-self:flex-start;max-width:88%;background:#e9e9eb;border-radius:18px 18px 18px 6px;padding:9px 13px;font-size:13.5px;
overflow-wrap:anywhere}
.msg time{display:block;font-size:11px;color:var(--ink2);margin-top:5px}
.otp{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#fff;border:1px dashed var(--orange);
border-radius:6px;padding:0 5px;font-weight:700;color:#b54708}
.copy{margin-top:8px}
.screen .none{margin:auto;text-align:center;color:var(--ink2);font-size:13px}
.steps{margin:0;padding-left:20px}.steps li{margin:6px 0}
select.pick{height:38px;border:1px solid #d2d2d7;border-radius:10px;padding:0 10px;font:inherit;background:#fff;max-width:100%}
@media(max-width:900px){.phone-wrap,.cols,.grid2,.tiles{grid-template-columns:1fr}.phone{margin:0 auto}}
@media(max-width:640px){.bar,.tabs,main{padding-left:14px;padding-right:14px}.brand small{display:none}}
"""

# ---- script -------------------------------------------------------------------------------------------------------------

SCRIPT = r"""
(function(){
var live=document.body.getAttribute('data-lam-moi')==='1',paused=false;
var btn=document.getElementById('tam-dung'),den=document.getElementById('den');
function bottom(){var s=document.querySelector('.screen');if(s)s.scrollTop=s.scrollHeight;}
function busy(){var a=document.activeElement;if(a&&/^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName))return true;
var sel=window.getSelection&&window.getSelection();return !!(sel&&String(sel).length);}
if(btn)btn.addEventListener('click',function(){paused=!paused;btn.textContent=paused?'Tiếp tục':'Tạm dừng';
den.className=paused?'live off':'live';});
if(live)setInterval(function(){
if(paused||document.hidden||busy())return;
fetch(location.href,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(r.status);return r.text();})
.then(function(t){var d=new DOMParser().parseFromString(t,'text/html');
var n=d.getElementById('noi-dung'),o=document.getElementById('noi-dung');
if(n&&o&&n.innerHTML!==o.innerHTML){o.innerHTML=n.innerHTML;bottom();filter();}
var c=d.getElementById('dong-ho');if(c)document.getElementById('dong-ho').textContent=c.textContent;
if(den&&!paused)den.className='live';})
.catch(function(){if(den)den.className='live err';});
},5000);
function norm(s){return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/đ/g,'d');}
function filter(){var box=document.querySelector('[data-loc]');if(!box)return;var q=norm(box.value.trim()),shown=0;
var rows=document.querySelectorAll('#'+box.getAttribute('data-loc')+' tr');
rows.forEach(function(tr){if(tr.querySelector('th'))return;var ok=!q||norm(tr.textContent).indexOf(q)>=0;
tr.style.display=ok?'':'none';if(ok)shown++;});
var out=document.getElementById('dem-loc');if(out)out.textContent=shown+' người';}
document.addEventListener('input',function(e){if(e.target.matches('[data-loc]'))filter();});
document.addEventListener('change',function(e){if(e.target.matches('[data-di-toi]')&&e.target.value)location.href=e.target.value;});
document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(!b)return;
var v=b.getAttribute('data-copy'),old=b.textContent;
function done(){b.textContent='Đã chép';setTimeout(function(){b.textContent=old;},1500);}
if(navigator.clipboard)navigator.clipboard.writeText(v).then(done,function(){});});
document.addEventListener('submit',function(e){var m=e.target.getAttribute('data-hoi');if(m&&!confirm(m))e.preventDefault();});
bottom();filter();
})();
"""
