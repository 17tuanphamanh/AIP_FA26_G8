"""Cổng 5 tự động — phần ĐƠN Ý (phase5 mục 7.6, PLAN-T24 S15) trên stack compose THẬT — `make gate5 S=<kịch bản>` sau `make up` +
KB THẬT (`kb/` — 6 bài quy trình `procedure_doc` của account/software/access; `make verify G=…5` tự nạp, Q-T24-1).

Khuôn `gate3.py` / `gate4.py` (tái dùng `Shell`, `Report`, `Ctx`, chốt an toàn, làm nóng rerank, `audit_check` theo ticket). Node THẬT,
`LLM_BACKEND=scripted` với preset `config/scripted/{tc01,tc03,tc07,tc08,tc17,tc18,tc21a,tc21b,hb04}.yaml` (thẻ `[fake:<preset>]` cuối
câu), mock/ml-service/Qdrant thật. Không luật nào của 3 intent mới phụ thuộc giờ → kịch bản không phụ thuộc giờ chạy.

Chốt an toàn (trước mọi HTTP; không qua → exit 2): như gate3 (APP_ENV=dev, URL 127.0.0.1, cấm `down -v`, `LLM_BACKEND=scripted`,
`FAKE_SCENARIO` không đặt) + `ENABLED_INTENTS` hiệu lực của backend VÀ worker đủ 4 intent (TQ-13 — script trong container chỉ in NHÃN
`INTENTS=du|thieu|?`, không in giá trị; compose không truyền biến này → thiếu = image cũ dựng trước T24) + KB đang chạy = KB thật `kb/` (so `collection` của `/api/health` với `kb_<kb_version(kb/)>`).

Lỗi hệ thống giả qua `/_admin/faults` của mock (tiền tố đường dẫn — `admin_faults.py`); mock nạp lại seed trước mỗi kịch bản (xoá lỗi
bơm + bộ đếm). Lời gọi ghi đếm ở NƠI NHẬN (`/_admin/calls`, POST trừ đăng nhập).

Kịch bản (`S=all` theo thứ tự `ALL`): preflight · tc01 R01 AUTO reset → xác nhận · tc03 R11 AUTO cài Zoom (0 assign) · tc07 R03 (+R04)
duyệt → reset svc_backup · tc08 R07 (+R09) TỪ CHỐI → 0 ghi · tc17 catalog 404 → R13 chờ duyệt · tc18 500 ở check_privilege_level → B7
E2 · tc21a cài lỗi 500 → E7 · tc21b có phí: license OK, cài lỗi → E7, 0 hoàn tác · hb04 AutoCAD hết license 409 → E7 · g5-audit
`audit_check` trên đúng ticket của lần chạy + quét log. `S=all` ghi biên bản `bienban-gate5-<YYYYmmdd>.md` (không commit bản đã điền).
"""

import json
import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from app.audit.check import SecretScanner, scan_log
from app.core.clock import SystemClock
from app.domain.states import S_REJECTED
from app.rag.ingest.kbversion import kb_version
from app.rag.ingest.loader import load_kb
from app.settings import Settings
from tests.stack import gate2, gate3, gate4
from tests.stack.gate2 import (
    DEFAULT_URL,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_RESOLVED,
    Line,
    Report,
    Run,
    Shell,
    StackError,
    Unsafe,
    check_url,
    q,
    safety_gate,
    subprocess_run,
)

REPO = Path(__file__).resolve().parents[3]
REAL_KB = REPO / "kb"
CONFIG_DIR = Settings(_env_file=None).config_dir  # type: ignore[call-arg]
AN, BINH, HA = gate3.AN, gate3.BINH, gate3.APPROVER  # nv001, nv002, l1_01 — không MFA
USERS = (HA, AN, BINH)
FOUR = ("vpn", "account", "software", "access")

# (preset, người gửi, câu) — preset `config/scripted/<preset>.yaml`, thẻ `[fake:<preset>]` cuối câu (bảng 7.6)
# Q-T24-10 = A: câu có "mật khẩu" kết thúc bằng dấu chấm — luật bí mật `password` (privacy_patterns.json) hiểu "mật khẩu … [fake:" + ":"
# là "mật khẩu: <giá trị>" và che mất tên preset (→ preset default → E1). Dấu chấm cắt chuỗi từ đệm của luật.
TC01 = ("tc01", AN, "đặt lại mật khẩu tài khoản AD.")
TC03 = ("tc03", AN, "cài Zoom")
TC07 = ("tc07", AN, "đặt lại mật khẩu AD cho svc_backup.")
TC08 = ("tc08", BINH, "xin quyền đọc finance/Q3 30 ngày")
TC17 = ("tc17", AN, "cài utorrent")
TC18 = ("tc18", AN, "đặt lại mật khẩu tài khoản AD.")
TC21A = ("tc21a", AN, "cài Zoom")
TC21B = ("tc21b", AN, "cài Adobe Acrobat Pro")
HB04 = ("hb04", AN, "cài AutoCAD")
TICKET_PRESETS = (TC01, TC03, TC07, TC08, TC17, TC18, TC21A, TC21B, HB04)

# Đường mock (lời gọi ghi đếm ở nơi nhận)
RESET_NV001 = "/ad/users/nv001/reset-password"
RESET_SVC = "/ad/users/svc_backup/reset-password"
INSTALL = "/software/installed/LAP-0342/install"
UNINSTALL = "/software/installed/LAP-0342/uninstall"
LICENSES = "/software/licenses/"
ASSIGN_ACROBAT = "/software/licenses/adobe-acrobat-pro/assign"
ASSIGN_AUTOCAD = "/software/licenses/autocad/assign"
PRIVILEGE_NV001 = "/ad/users/nv001/privilege"  # check_privilege_level — KHÔNG bơm lỗi ở /ad/users/nv001 (B1 dùng chung → E2 ở B1)
REJECT_NOTE = "Thư mục tài chính quý 3 chỉ cấp cho phòng Tài chính"
TC08_HEAD = "Yêu cầu cấp quyền truy cập cho thư mục finance/Q3 chưa được duyệt. Lý do: "


@dataclass(frozen=True)
class Risk:
    rule: str  # matched_rule_id (chặt nhất; cùng mức → luật đứng trước trong policy.json)
    route: str  # AUTO | HITL
    all_matched: frozenset[str]


# Điểm log 4 mong đợi (bảng 7.6 + bảng luật 4.4; seed `mock_services/seed.json`) — không phụ thuộc giờ
EXPECTED: Mapping[str, Risk] = {
    "tc01": Risk("R01", "AUTO", frozenset({"R01"})),
    "tc03": Risk("R11", "AUTO", frozenset({"R11"})),
    "tc07": Risk("R03", "HITL", frozenset({"R03", "R04"})),
    "tc08": Risk("R07", "HITL", frozenset({"R07", "R09"})),
    "tc17": Risk("R13", "HITL", frozenset({"R13"})),
    "tc21a": Risk("R11", "AUTO", frozenset({"R11"})),
    "tc21b": Risk("R14", "HITL", frozenset({"R14"})),
    "hb04": Risk("R14", "HITL", frozenset({"R14", "R15"})),
}

# TQ-13: ENABLED_INTENTS hiệu lực TRONG container — chỉ in nhãn. Không đọc `.env` (Settings đọc biến môi trường của container).
INTENTS_PROBE = (
    "import sys\n"
    "try:\n"
    "    from app.settings import Settings\n"
    "    got = set(Settings().enabled_intents)\n"
    "except Exception:\n"
    "    print('INTENTS=?'); sys.exit(0)\n"
    f"print('INTENTS=du' if {set(FOUR)!r} <= got else 'INTENTS=thieu')\n"
)
INTENTS_LABELS = frozenset({"du", "thieu", "?"})
FAULT_PY = (
    "import json, sys, httpx; r = httpx.post('http://127.0.0.1:8100/_admin/faults', json=json.loads(sys.argv[1]), timeout=5); "
    "r.raise_for_status(); print(r.json()['fault_id'])"
)
CALLS_PY = (
    "import sys, httpx; r = httpx.get('http://127.0.0.1:8100/_admin/calls', params={'path_prefix': sys.argv[1], 'method': sys.argv[2]}, "
    "timeout=5); r.raise_for_status(); print(r.json()['count'])"
)


def parse_intents(out: str) -> str:
    """`INTENTS=du|thieu|?` → nhãn; lạ/thiếu → `?` (không in lại đầu ra)."""
    for line in out.splitlines():
        name, _, value = line.strip().partition("=")
        if name == "INTENTS" and value in INTENTS_LABELS:
            return value
    return "?"


def intents_gate(shell: Shell) -> dict[str, str]:
    """ENABLED_INTENTS của backend VÀ worker phải đủ 4 intent (T24 P1 — máy đặt tường minh trong `.env` phải tự xoá dòng đó)."""
    found = {name: parse_intents(shell.compose("exec", "-T", name, "python", "-c", INTENTS_PROBE)) for name in ("backend", "worker")}
    wrong = {name: v for name, v in found.items() if v != "du"}
    if wrong:
        raise Unsafe(f"ENABLED_INTENTS {wrong} — gate5 cần đủ {list(FOUR)} ở backend và worker (compose không truyền biến này: "
                     "image dựng trước T24? — make up để dựng lại image từ cây hiện tại)")  # fmt: skip
    return found


def real_kb_collection() -> str:
    """Collection mà `make ingest` (KB_DIR=kb) tạo: `kb_<sha256 danh sách doc_id:version enabled>`."""
    docs, _ = load_kb(REAL_KB, SystemClock())
    return f"kb_{kb_version(docs)}"


def kb_gate(http: httpx.Client) -> None:
    """KB đang chạy phải là KB thật (`kb/`) — KB fixture chỉ có bài VPN → B11 S0-P10 ra E3 `no_procedure` cho mọi ca (Q-T24-1)."""
    try:
        running = (http.get("/api/health").json().get("kb") or {}).get("collection")
    except (httpx.HTTPError, ValueError) as exc:
        raise Unsafe(f"không đọc được /api/health ({type(exc).__name__})") from exc
    if running != real_kb_collection():
        raise Unsafe("KB đang chạy không phải KB thật kb/ — chạy qua `make verify G=…5` (tự nạp) hoặc `make ingest` (KB_DIR=kb)")


# ---- Ngữ cảnh -------------------------------------------------------------------------------------------------------------


@dataclass
class Ctx(gate3.Ctx):
    start: datetime = field(default_factory=lambda: datetime.now(UTC))

    def login_users(self) -> None:
        for username in USERS:
            self.login(username)

    def ticket(self, spec: tuple[str, str, str]) -> tuple[str, dict[str, Any]]:
        preset, who, sentence = spec
        t = self.open(who, preset, sentence)
        return t, self.settle(t, 0)

    def fault(self, prefix: str, *, method: str, status: int = 500) -> None:
        body = json.dumps({"path_prefix": prefix, "method": method, "mode": "error", "status": status})
        self.shell.compose("exec", "-T", "mock", "python", "-c", FAULT_PY, body)

    def calls(self, prefix: str, method: str = "POST") -> int:
        return int(self.shell.compose("exec", "-T", "mock", "python", "-c", CALLS_PY, prefix, method).strip())

    def handoff_why(self, ticket: str) -> list[str]:
        """`escalations.handoff_note.why_escalated` — B20 chép ghi chú bàn giao của executor (`escalation_note`) vào đây."""
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(handoff_note->>'why_escalated' ORDER BY escalation_id), '[]') FROM escalations "
            f"WHERE ticket_id = {q(ticket)}"
        ))  # fmt: skip

    def decide(self, ticket: str, body: Mapping[str, Any]) -> tuple[httpx.Response, dict[str, Any]]:
        """`l1_01` quyết phiếu duy nhất của ticket → (phản hồi, view sau lượt nền)."""
        approvals = self.approvals(ticket)
        if len(approvals) != 1:
            raise StackError(f"ticket {ticket}: cần đúng 1 phiếu, thấy {len(approvals)}")
        before = self.turn_count(ticket)
        r = self.post(f"/api/approvals/{approvals[0]['approval_id']}/decision", body, self.tokens[HA])
        return r, self.settle(ticket, before)


# ---- Bước chung -------------------------------------------------------------------------------------------------------------


def _begin(ctx: Ctx) -> None:
    ctx.mock_reset()
    ctx.login_users()


def _risk(ctx: Ctx, t: str, tc: str) -> None:
    want = EXPECTED[tc]
    got = [(r.get("matched_rule_id"), r.get("route"), frozenset(r.get("all_matched") or ())) for r in ctx.risk(t)]
    ctx.report.eq(t, "B12 điểm log 4 (luật, route, mọi luật khớp)", [(want.rule, want.route, want.all_matched)], got)


def _pending(ctx: Ctx, t: str, v: Mapping[str, Any]) -> None:
    rep = ctx.report
    rep.eq(t, "chờ duyệt", S_PENDING_APPROVAL, v["status"])
    rep.eq(t, "0 lời gọi ghi trước khi duyệt (mock)", 0, ctx.mock_writes())
    approvals = ctx.approvals(t)
    rep.eq(t, "1 phiếu pending → l1_01 / l1_02, không xung đột", [("pending", "l1_01", "l1_02", False)],
           [(a["status"], a["approver_id"], a["backup_approver_id"], a["conflict_detected"]) for a in approvals])  # fmt: skip


def _approve(ctx: Ctx, t: str) -> dict[str, Any]:
    r, v = ctx.decide(t, {"decision": "approved"})
    ctx.report.eq(t, f"{HA} duyệt → 202", 202, r.status_code)
    return v


def _result(ctx: Ctx, t: str, v: Mapping[str, Any], head: str) -> None:
    results = gate3.msgs(v, "result")
    ctx.report.check(t, f"1 tin result bắt đầu {head!r}, needs=confirm",
                     len(results) == 1 and results[0]["text"].startswith(head) and results[0].get("needs") == "confirm",
                     head, [m.get("text") for m in results])  # fmt: skip


def _point7(ctx: Ctx, t: str, event: str, step: str, writes: int) -> None:
    rows = [r["detail"].get("write_calls") for r in ctx.audit(t) if (r["step"], r["event"]) == (step, event)]
    ctx.report.eq(t, f"điểm log 7: {step} {event} write_calls", [writes], rows)


def _confirm(ctx: Ctx, t: str, writes: int) -> None:
    rep = ctx.report
    before = ctx.turn_count(t)
    r = ctx.post(f"/api/tickets/{t}/confirm", {"confirmed": True}, ctx.tokens[ctx.owner[t]])
    rep.eq(t, "xác nhận → 202", 202, r.status_code)
    v = ctx.settle(t, before)
    rep.eq(t, "đóng", (S_RESOLVED, "resolved_user_confirmed"), (v["final_state"], v["close_reason"]))
    rep.eq(t, "xác nhận không gọi ghi thêm (mock)", writes, ctx.mock_writes())


def _exec_failed(ctx: Ctx, t: str, v: Mapping[str, Any], sentences: Sequence[str]) -> None:
    rep = ctx.report
    rep.eq(t, "→ E7", (S_ESCALATED, "E7"), (v["final_state"], v["exit_code"]))
    rep.eq(t, "escalations", [["E7", "exec_failed"]], ctx.escalation(t))
    rep.eq(t, "tin mẫu E7", [gate3.user_message("E7")], [m["text"] for m in gate3.msgs(v, "escalation")])
    why = ctx.handoff_why(t)
    note = why[0] if len(why) == 1 and isinstance(why[0], str) else ""
    for part in ("Đã làm:", "Lỗi ở bước:", "Hoàn tác:", "L2 cần làm tay:"):
        rep.check(t, f"ghi chú bàn giao có {part!r}", part in note, part, note[:160])
    for sentence in sentences:
        rep.check(t, f"ghi chú bàn giao có {sentence[:60]!r}", sentence in note, sentence, note[:240])


# ---- Kịch bản ---------------------------------------------------------------------------------------------------------------


def preflight(ctx: Ctx) -> None:
    rep = ctx.report
    body = ctx.http.get("/api/health").json()
    rep.eq("-", "health status", "ok", body.get("status"))
    rep.eq("-", "health runtime", "up", body.get("runtime"))
    rep.eq("-", "health kb", "ready", (body.get("kb") or {}).get("status"))
    rep.eq("-", "KB thật kb/", real_kb_collection(), (body.get("kb") or {}).get("collection"))
    rep.eq("-", "worker healthy", "healthy", ctx.worker_health())
    ctx.login_users()
    rep.check("-", f"đăng nhập {', '.join(USERS)}", True, "200", "200")


def tc01(ctx: Ctx) -> None:
    """R01 AUTO → POST reset-password nv001 đúng 1 lần → tin result → xác nhận → `S_RESOLVED`."""
    rep = ctx.report
    _begin(ctx)
    t, v = ctx.ticket(TC01)
    _risk(ctx, t, "tc01")
    rep.eq(t, "thực thi xong → chờ xác nhận", S_CONFIRMING, v["status"])
    rep.eq(t, f"POST {RESET_NV001} đúng 1 lần", 1, ctx.calls(RESET_NV001))
    rep.eq(t, "tổng lời gọi ghi = 1", 1, ctx.mock_writes())
    rep.eq(t, "transaction_log", [["reset_password", "begun"]], ctx.txlog(t))
    _point7(ctx, t, "executed_ok", "B18", 1)
    _result(ctx, t, v, "Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của bạn.")
    _confirm(ctx, t, 1)


def tc03(ctx: Ctx) -> None:
    """R11 AUTO (Zoom miễn phí, máy LAP-0342 do B6 suy) → 1 lời gọi install, 0 assign → xác nhận → `S_RESOLVED`."""
    rep = ctx.report
    _begin(ctx)
    t, v = ctx.ticket(TC03)
    _risk(ctx, t, "tc03")
    rep.eq(t, "thực thi xong → chờ xác nhận", S_CONFIRMING, v["status"])
    rep.eq(t, f"POST {INSTALL} đúng 1 lần", 1, ctx.calls(INSTALL))
    rep.eq(t, f"0 POST {LICENSES}* (không cấp license cho phần mềm miễn phí)", 0, ctx.calls(LICENSES))
    rep.eq(t, "tổng lời gọi ghi = 1", 1, ctx.mock_writes())
    rep.eq(t, "transaction_log", [["install_software", "begun"]], ctx.txlog(t))
    rep.eq(t, "B6 tự suy máy: 0 tin question", [], gate3.msgs(v, "question"))
    _result(ctx, t, v, "Đã cài zoom")
    rep.check(t, "tin result nêu LAP-0342", any("LAP-0342" in m["text"] for m in gate3.msgs(v, "result")), "có", "không")
    _confirm(ctx, t, 1)


def tc07(ctx: Ctx) -> None:
    """R03 (+R04) → phiếu l1_01 → duyệt → B17 tra lại AD người gửi + svc_backup → reset svc_backup đúng 1 lần (không reset nv001)."""
    rep = ctx.report
    _begin(ctx)
    t, v = ctx.ticket(TC07)
    _risk(ctx, t, "tc07")
    _pending(ctx, t, v)
    svc_get, an_get = ctx.calls("/ad/users/svc_backup", "GET"), ctx.calls("/ad/users/nv001", "GET")
    v = _approve(ctx, t)
    rep.eq(t, "thực thi xong → chờ xác nhận", S_CONFIRMING, v["status"])
    rep.check(t, "B17 tra lại AD svc_backup (GET tăng)", ctx.calls("/ad/users/svc_backup", "GET") > svc_get, "> trước", "không tăng")
    rep.check(t, "B17 tra lại AD người gửi nv001 (GET tăng)", ctx.calls("/ad/users/nv001", "GET") > an_get, "> trước", "không tăng")
    rep.eq(t, f"POST {RESET_SVC} đúng 1 lần", 1, ctx.calls(RESET_SVC))
    rep.eq(t, f"0 POST {RESET_NV001}", 0, ctx.calls(RESET_NV001))
    rep.eq(t, "tổng lời gọi ghi = 1", 1, ctx.mock_writes())
    _point7(ctx, t, "executed_ok", "B18", 1)
    _result(ctx, t, v, "Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của svc_backup.")
    _confirm(ctx, t, 1)


def tc08(ctx: Ctx) -> None:
    """binh.tt xin quyền đọc finance/Q3 → R07 (+R09) → l1_01 TỪ CHỐI có lý do → `S_REJECTED`, tin từ chối theo đích, 0 ghi."""
    rep = ctx.report
    _begin(ctx)
    t, v = ctx.ticket(TC08)
    _risk(ctx, t, "tc08")
    _pending(ctx, t, v)
    r, v = ctx.decide(t, {"decision": "rejected", "reason_code": "policy_violation", "note": REJECT_NOTE})
    rep.eq(t, f"{HA} từ chối → 202", 202, r.status_code)
    rep.eq(t, "đóng: từ chối", (S_REJECTED, "rejected_by_approver"), (v["final_state"], v["close_reason"]))
    texts = [m["text"] for m in gate3.msgs(v, "rejection")]
    rep.check(t, "1 tin rejection theo đích thư mục", len(texts) == 1 and texts[0].startswith(TC08_HEAD), TC08_HEAD, texts)
    rep.eq(t, "0 lời gọi ghi", 0, ctx.mock_writes())


def tc17(ctx: Ctx) -> None:
    """utorrent: catalog 404 là DỮ LIỆU (không E2) → `in_catalog=False` → R13 → chờ duyệt, 0 ghi."""
    rep = ctx.report
    _begin(ctx)
    t, v = ctx.ticket(TC17)
    _risk(ctx, t, "tc17")
    _pending(ctx, t, v)
    rep.eq(t, "không escalations (404 không phải lỗi hệ thống)", [], ctx.escalation(t))


def tc18(ctx: Ctx) -> None:
    """500 ở `check_privilege_level` (sau retry) → B7 E2 `tool_system_error`, tin mẫu E2, 0 ghi."""
    _begin(ctx)
    ctx.fault(PRIVILEGE_NV001, method="GET")
    gate3._escalated(ctx, "tc18", TC18[2], "E2", "tool_system_error")


def tc21a(ctx: Ctx) -> None:
    """R11 AUTO, cài lỗi 500 → E7 `exec_failed`, 1 lời gọi ghi, ghi chú 4 phần có "có thể đã được áp dụng"."""
    rep = ctx.report
    _begin(ctx)
    ctx.fault(INSTALL, method="POST")
    t, v = ctx.ticket(TC21A)
    _risk(ctx, t, "tc21a")
    rep.eq(t, f"POST {INSTALL} đúng 1 lần (không retry)", 1, ctx.calls(INSTALL))
    rep.eq(t, "tổng lời gọi ghi = 1", 1, ctx.mock_writes())
    rep.eq(t, "transaction_log", [["install_software", "begun"]], ctx.txlog(t))
    _exec_failed(ctx, t, v, ["có thể đã được áp dụng"])
    _point7(ctx, t, "exec_failed", "B17", 1)


def tc21b(ctx: Ctx) -> None:
    """Cổng 5 "phần mềm có phí lỗi khi cài → không gọi hoàn tác": R14 → duyệt → assign OK → cài lỗi 500 → E7, 0 uninstall, license đã
    cấp KHÔNG thu hồi; ghi chú bàn giao nói rõ."""
    rep = ctx.report
    _begin(ctx)
    ctx.fault(INSTALL, method="POST")
    t, v = ctx.ticket(TC21B)
    _risk(ctx, t, "tc21b")
    _pending(ctx, t, v)
    v = _approve(ctx, t)
    rep.eq(t, f"POST {ASSIGN_ACROBAT} đúng 1 lần", 1, ctx.calls(ASSIGN_ACROBAT))
    rep.eq(t, f"POST {INSTALL} đúng 1 lần", 1, ctx.calls(INSTALL))
    rep.eq(t, f"0 POST {UNINSTALL} (không hoàn tác)", 0, ctx.calls(UNINSTALL))
    rep.eq(t, "tổng lời gọi ghi = 2 (0 lời gọi hoàn tác)", 2, ctx.mock_writes())
    rep.eq(t, "transaction_log", [["assign_paid_license", "begun"], ["install_software", "begun"]], ctx.txlog(t))
    _exec_failed(ctx, t, v, [
        "license adobe-acrobat-pro ĐÃ cấp cho nv001 và KHÔNG được thu hồi tự động", "assign_paid_license: not_reversible",
    ])  # fmt: skip
    _point7(ctx, t, "exec_failed", "B17", 2)


def hb04(ctx: Ctx) -> None:
    """AutoCAD (3/3 license đã dùng) → R14 (+R15) → duyệt → assign 409 `no_license_available` → E7, 1 lời gọi ghi, "hết license"."""
    rep = ctx.report
    _begin(ctx)
    t, v = ctx.ticket(HB04)
    _risk(ctx, t, "hb04")
    _pending(ctx, t, v)
    v = _approve(ctx, t)
    rep.eq(t, f"POST {ASSIGN_AUTOCAD} đúng 1 lần", 1, ctx.calls(ASSIGN_AUTOCAD))
    rep.eq(t, f"0 POST {INSTALL}", 0, ctx.calls(INSTALL))
    rep.eq(t, "tổng lời gọi ghi = 1", 1, ctx.mock_writes())
    rep.eq(t, "transaction_log", [["assign_paid_license", "begun"]], ctx.txlog(t))
    _exec_failed(ctx, t, v, ["hết license autocad"])
    _point7(ctx, t, "exec_failed", "B17", 1)


def g5_audit(ctx: Ctx) -> None:
    """Khuôn g4-12 (Q-4d-10 = A): `audit_check <ticket của lần chạy>` trong container → mã 0, `0 thiếu, 0 bí mật` (đủ điểm log áp
    dụng 1, 2, 4, 7, 8 — 5/6 khi duyệt; không câu người dùng); log backend+worker từ lúc bắt đầu → 0 trúng luật bí mật."""
    rep = ctx.report
    name = "audit_check trên ticket của lần chạy: mã 0, 0 thiếu, 0 bí mật"
    tickets = [q(t).strip("'") for t in ctx.owner]
    if not tickets:
        rep.fail("-", name, "lần chạy chưa tạo ticket nào (chạy lẻ S=g5-audit?) — chạy cùng các kịch bản khác: make gate5 S=all")
    else:
        compose = shlex.join([*ctx.shell.compose_base, "exec", "-T", "backend"])
        out = ctx.shell.run([*ctx.shell.compose_base, "exec", "-T", "backend", "sh", "-c", gate4.AUDIT_SH, "sh", *tickets],
                            shown=f"{compose} python -m app.audit.check <{len(tickets)} ticket của lần chạy>")  # fmt: skip
        code, lines = gate4.audit_result(out)
        ok = code == 0 and any(line.startswith("KẾT LUẬN: 0 thiếu, 0 bí mật") for line in lines)
        rep.check("-", name, ok, f"mã 0, KẾT LUẬN: 0 thiếu, 0 bí mật ({len(tickets)} ticket)",
                  f"mã {code}, {lines[-1] if lines else 'không có dòng KẾT LUẬN'}")  # fmt: skip
        if not ok:
            for line in lines:
                rep.echo(f"    {line}")
    since = ctx.start.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        logs = ctx.shell.compose("logs", "--no-color", "--since", since, "backend", "worker")
    except StackError as exc:
        rep.fail("-", "log backend+worker: 0 trúng luật bí mật", str(exc).splitlines()[0])
        return
    hits = scan_log(logs.splitlines(), SecretScanner.from_config(CONFIG_DIR))
    rep.eq("-", "log backend+worker: 0 trúng luật bí mật", [], [(h.ref, h.rule) for h in hits])


SCENARIOS: dict[str, Callable[[Ctx], None]] = {
    "preflight": preflight, "tc01": tc01, "tc03": tc03, "tc07": tc07, "tc08": tc08, "tc17": tc17, "tc18": tc18,
    "tc21a": tc21a, "tc21b": tc21b, "hb04": hb04, "g5-audit": g5_audit,
}  # fmt: skip
ALL = list(SCENARIOS)  # g5-audit cuối: quét mọi ticket của lần chạy


# ---- Biên bản ---------------------------------------------------------------------------------------------------------------


def render_bienban(rows: Sequence[gate4.Outcome], *, run_id: str, started: datetime, ended: datetime, commit: str, dirty: int) -> str:
    total_fail = sum(r.failed for r in rows)
    table = "\n".join(f"| {r.name} | {r.passed} | {r.failed} | {r.first_fail.replace('|', '/')[:160]} |" for r in rows)
    verdict = "ĐẠT (0 FAIL)" if total_fail == 0 and rows else f"KHÔNG ĐẠT ({total_fail} FAIL)"
    return (
        f"# Biên bản chạy cổng 5 tự động — phần đơn ý (`make gate5 S=all`)\n\n"
        f"- Lần chạy: `{run_id}` — bắt đầu {started:%d/%m/%Y %H:%M:%S %Z}, kết thúc {ended:%H:%M:%S %Z}\n"
        f"- Commit: `{commit}` (tệp đã theo dõi đang sửa: {dirty})\n"
        f"- Người chạy: ______________________\n"
        f"- Máy (hãng, CPU, RAM, hệ điều hành): ______________________\n\n"
        f"| Kịch bản | PASS | FAIL | Dòng FAIL đầu tiên |\n|---|---|---|---|\n{table}\n\n"
        f"**Kết luận:** {verdict}\n\n"
        f"Chữ ký người chạy: ______________________   Ngày: ____/____/________\n"
    )


def write_bienban(path: Path, rows: Sequence[gate4.Outcome], *, run_id: str, started: datetime, run: Run) -> Path:
    commit = gate4._git(run, "rev-parse", "--short=7", "HEAD")
    dirty = len([line for line in gate4._git(run, "status", "--porcelain", "--untracked-files=no").splitlines() if line.strip()])
    path.write_text(render_bienban(rows, run_id=run_id, started=started, ended=datetime.now(UTC), commit=commit, dirty=dirty),
                    encoding="utf-8")  # fmt: skip
    return path


# ---- Chạy -------------------------------------------------------------------------------------------------------------------


def run_scenarios(ctx: Ctx, names: Sequence[str]) -> tuple[int | None, list[tuple[str, Sequence[Line]]]]:
    per: list[tuple[str, Sequence[Line]]] = []
    for n in names:
        ctx.report.echo(f"\n==== {n} ====")
        first = len(ctx.report.lines)
        try:
            SCENARIOS[n](ctx)
        except Unsafe as exc:
            ctx.report.echo(f"DỪNG (chốt an toàn): {exc}")
            return 2, per
        except (StackError, httpx.HTTPError, KeyError, ValueError, IndexError, TypeError) as exc:
            ctx.report.fail("-", f"{n} dừng giữa chừng", f"{type(exc).__name__}: {exc}")
        per.append((n, ctx.report.lines[first:]))
    return None, per


def open_ctx(argv: Sequence[str], *, run: Run, env: Mapping[str, str], echo: Callable[[str], None]
             ) -> tuple[list[str], Shell, str, dict[str, str]] | int:  # fmt: skip
    names = [n for arg in argv for n in (ALL if arg == "all" else [arg])] or ["preflight"]
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        echo(f"kịch bản lạ: {unknown}; chọn trong {sorted(SCENARIOS)} hoặc all")
        return 2
    try:
        url = check_url(env.get("GATE5_URL", DEFAULT_URL))
        shell = Shell(shlex.split(env.get("COMPOSE", "docker compose")), run=run, echo=echo)
        safety_gate(shell)
        flags = gate3.env_gate(shell)
        intents = intents_gate(shell)
    except (Unsafe, StackError) as exc:
        echo(f"DỪNG (chốt an toàn): {exc}")
        return 2
    echo(f"ENABLED_INTENTS: backend={intents['backend']}, worker={intents['worker']} (đủ 4 intent)")
    return names, shell, url, flags


def main(argv: Sequence[str], *, run: Run = subprocess_run, env: Mapping[str, str] = os.environ,
         echo: Callable[[str], None] = print, out_dir: Path | None = None) -> int:  # fmt: skip
    opened = open_ctx(argv, run=run, env=env, echo=echo)
    if isinstance(opened, int):
        return opened
    names, shell, url, flags = opened
    report = Report(echo=echo)
    with httpx.Client(base_url=url, timeout=15) as http:
        try:
            kb_gate(http)
        except Unsafe as exc:
            echo(f"DỪNG (chốt an toàn): {exc}")
            return 2
        ctx = Ctx(shell=shell, http=http, report=report, password=env.get("GATE5_PASSWORD") or gate2.password_from(env))
        echo(f"gate5 run {ctx.run_id}: {names} (bắt đầu {ctx.start.isoformat()})")
        if flags.get("SVC_EXECUTOR_TOKEN") != "1":
            echo("CẢNH BÁO: container backend không có SVC_EXECUTOR_TOKEN — B17 dùng RefusingExecutor → mọi ca thực thi ra E7")
        gate3.warm_rerank(ctx)  # một lần, trước kịch bản đầu (khuôn gate3/gate4)
        stopped, per = run_scenarios(ctx, names)
        if stopped is not None:
            return stopped
    code = report.summary()
    if list(names) == ALL:
        stamp = ctx.start.astimezone(ZoneInfo(ctx.hours.tz))
        path = write_bienban((out_dir or Path(__file__).parent) / f"bienban-gate5-{stamp:%Y%m%d}.md", gate4.outcomes(per),
                             run_id=ctx.run_id, started=stamp, run=run)  # fmt: skip
        echo(f"Biên bản: {path} — điền người chạy, máy, ký; KHÔNG commit bản đã điền")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
