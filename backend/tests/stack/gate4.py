"""Cổng 4 trên stack compose THẬT (phase4 mục 7.1 P6, 7.4; PLAN-4d mục 11.5) — `make gate4 S=<kịch bản>` sau `make up`. Người KHÔNG làm
chính chạy `make gate4 S=all` (ngoài giờ, cắm sạc, mở nắp — `README.md` cạnh file này) rồi điền biên bản.

Khuôn `gate3.py` (tái dùng `Shell`, `Report`, `Ctx`, chốt an toàn, làm nóng rerank). Khác gate3: B15–B16 THẬT với hạn duyệt rút ngắn
`APPROVAL_SLA_MINUTES_DEV=2` (worker thật quét 15 s: nhắc ~60 s / ~96 s, hết hạn 120 s) — kịch bản không phụ thuộc giờ chạy (R19 vì
chau.hm đang thử việc; R17 vì PC-0124/LAP-0700/LAP-0900 chưa đăng ký — `mock_services/seed.json`).

Chốt an toàn (trước mọi HTTP; không qua → exit 2): như gate3 (APP_ENV=dev, URL 127.0.0.1, cấm `down -v`, `LLM_BACKEND=scripted`,
`FAKE_SCENARIO` không đặt) + `APPROVAL_SLA_MINUTES_DEV` của backend VÀ worker phải là 2 — script trong container chỉ in `SLA=2`,
`SLA=khac` hoặc `SLA=0` (không đặt), KHÔNG BAO GIỜ in giá trị.

Kịch bản (`S=all` theo thứ tự `ALL`): preflight · g4-01 duyệt → thực thi → xác nhận · g4-11 ghi đè + lần 2 409 (ticket g4-01) · g4-02 từ
chối thiếu note 422 rồi có note · g4-06 TC19 PC-0124 → it_mgr01 (self), người gửi quyết 403 · g4-07 LAP-0700 → it_mgr01 (boss) · g4-09
L2 quyết/xem 403, L1 khác xem 404 · g4-10 xem phiếu ghi `first_viewed_at` · g4-04 dự phòng quyết sau nhắc 2 · g4-03 hết hạn: nhắc 1,
nhắc 2, E6 · g4-05 bấm muộn 409 (TQ-16) · g4-12 `audit_check` trên ĐÚNG các ticket lần chạy này đã tạo + quét log `--since` 0 lỗi.

**KHÔNG có g4-08** (quan.tm = Trưởng BP gửi LAP-0900 → E5 `no_valid_approver`) — Q-4d-9 = B: manager BẮT BUỘC MFA, script cổng không
đăng nhập manager và không tự ghi danh MFA trên stack (không cầm secret MFA, không để lại ghi danh trên DB của người chạy). Ca x4 phủ ở
e2e `test_i5_x4_…` (ghi danh trong tiến trình test, OTP theo FakeClock) + unit `test_x_table_3_2_real_node[x4-…]`. Mọi người gửi/người
xem trong gate4 là l1/l2/nhân viên (không MFA) có trong `mock_services/seed.json`.
`S=all` ghi biên bản `bienban-gate4-<YYYYmmdd>.md` cạnh file này (TQ-17: người chạy, máy, chữ ký để trống; agent không commit).
"""

import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from app.audit.check import SecretScanner, scan_log
from app.domain.states import S_REJECTED
from app.settings import Settings
from tests.stack import gate2, gate3
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
    wait_for,
)

CHAU, HA, DUC, KHOA, LONG = "chau.hm", "ha.lt", "duc.pv", "khoa.dv", "long.nh"  # nv003, l1_01, l1_02, l1_lead, l2_01 — không MFA
USERS = (CHAU, HA, DUC, KHOA, LONG)  # Q-4d-9 = B: không manager (MFA)
L1_01, L1_02, HEAD = "l1_01", "l1_02", "it_mgr01"
SLA_S = 120  # APPROVAL_SLA_MINUTES_DEV=2
RENEW = "/vpn/certs/nv003/renew"
REJECT_NOTE = "Máy không thuộc diện gia hạn trong đợt này"
# (preset, người gửi, câu) — preset `config/scripted/<preset>.yaml`, thẻ `[fake:<preset>]` cuối câu
HITL = ("g4_0501", CHAU, "gia hạn VPN cho máy LAP-0501")
SELF = ("g4_0124", HA, "gia hạn VPN cho máy PC-0124")
BOSS = ("g4_0700", KHOA, "gia hạn VPN cho máy LAP-0700")
TICKET_PRESETS = (HITL, SELF, BOSS)
MISSING_APPROVAL = "999999999999"  # id phiếu không tồn tại (BIGINT hợp lệ) — đối chứng 404 của g4-09
CONFIG_DIR = Settings(_env_file=None).config_dir  # type: ignore[call-arg]

# g4-12 (Q-4d-10 = A): `audit_check` trên ĐÚNG danh sách ticket của lần chạy (không `--since` — trên stack dev dùng chung, `--since` kéo cả
# ticket node giả của gate2 / ticket cũ có dòng mới do worker). Bọc `sh -c … 2>&1; echo exit` để lấy NGUYÊN bảng kèm mã thoát (Shell.run
# chỉ giữ 2000 ký tự cuối khi lệnh lỗi). Bảng của audit_check không bao giờ có giá trị (chỉ ticket/điểm/tên trường) — in được.
AUDIT_SH = 'python -m app.audit.check "$@" 2>&1; echo "audit_check_exit=$?"'
AUDIT_LINES = ("| ", "bí mật:", "KẾT LUẬN")


def audit_result(out: str) -> tuple[int | None, list[str]]:
    """(mã thoát của audit_check | None nếu không thấy, các dòng bảng/bí mật/KẾT LUẬN) — dòng khác (nhãn role, rác) bỏ."""
    code: int | None = None
    lines: list[str] = []
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("audit_check_exit="):
            value = line.partition("=")[2]
            code = int(value) if value.isdigit() else None
        elif line.startswith(AUDIT_LINES):
            lines.append(line)
    return code, lines


# Chốt SLA: in nhãn, không in giá trị (khác 2 → "khac").
SLA_PROBE = 'case "$(printenv APPROVAL_SLA_MINUTES_DEV)" in 2) echo SLA=2;; "") echo SLA=0;; *) echo SLA=khac;; esac'
SLA_LABELS = {"2": "=2", "0": "=0", "khac": "=khac"}


def parse_sla(out: str) -> str:
    """`SLA=2|0|khac` → nhãn; lạ/thiếu → `?` (không in lại đầu ra)."""
    for line in out.splitlines():
        name, _, value = line.strip().partition("=")
        if name == "SLA" and value in SLA_LABELS:
            return value
    return "?"


def sla_gate(shell: Shell) -> dict[str, str]:
    """`APPROVAL_SLA_MINUTES_DEV` của backend VÀ worker phải là 2 (B15 ở API đặt hạn; worker phục hồi lượt dở cũng chạy B15)."""
    found = {name: parse_sla(shell.compose("exec", "-T", name, "sh", "-c", SLA_PROBE)) for name in ("backend", "worker")}
    wrong = {name: SLA_LABELS.get(v, "=?") for name, v in found.items() if v != "2"}
    if wrong:
        raise Unsafe(f"APPROVAL_SLA_MINUTES_DEV {wrong} — gate4 cần =2 ở cả backend lẫn worker (thêm vào .env rồi make up lại)")
    return found


def reminder_in_window(at: datetime | None, mark: datetime, deadline: datetime, slack: timedelta = timedelta(seconds=1)) -> bool:
    """Nhắc KHÔNG BAO GIỜ sớm hơn mốc (50% / 80% thời hạn — trừ `slack` cho lệch đồng hồ giữa app và DB) và không sau hạn."""
    return at is not None and mark - slack <= at < deadline


def _ts(value: Any) -> datetime:
    return datetime.fromisoformat(str(value))


# ---- Ngữ cảnh -------------------------------------------------------------------------------------------------------------


@dataclass
class Ctx(gate3.Ctx):
    start: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved: str | None = None  # ticket g4-01 (đã đóng) — g4-11 ghi đè trên đó

    def login_users(self) -> None:
        for username in USERS:
            self.login(username)

    def ticket(self, spec: tuple[str, str, str]) -> tuple[str, dict[str, Any]]:
        preset, who, sentence = spec
        t = self.open(who, preset, sentence)
        return t, self.settle(t, 0)

    def approval(self, ticket: str) -> list[dict[str, Any]]:
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(json_build_object('approval_id', approval_id, 'status', status, 'approver_id', approver_id, "
            "'backup_approver_id', backup_approver_id, 'conflict_detected', conflict_detected, 'conflict_type', conflict_type, "
            "'decided_by', decided_by, 'created_at', created_at, 'deadline', deadline, 'reminder_1_at', reminder_1_at, "
            "'reminder_2_at', reminder_2_at, 'first_viewed_at', first_viewed_at, "
            "'sla_s', extract(epoch FROM deadline - created_at), 'past_deadline', now() >= deadline)), '[]') "
            f"FROM approvals WHERE ticket_id = {q(ticket)}"
        ))  # fmt: skip

    def b16(self, ticket: str) -> list[dict[str, Any]]:
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(json_build_object('event', event, 'approval_result', approval_result, 'detail', detail) "
            f"ORDER BY log_id), '[]') FROM audit_logs WHERE ticket_id = {q(ticket)} AND step = 'B16'"
        ))  # fmt: skip

    def late_events(self, ticket: str) -> list[dict[str, Any]]:
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(detail ORDER BY log_id), '[]') FROM audit_logs "
            f"WHERE ticket_id = {q(ticket)} AND event = 'late_event'"
        ))  # fmt: skip

    def overrides(self, ticket: str) -> list[list[Any]]:
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(json_build_array(overrider_id, original_decision, override_decision) ORDER BY log_id), '[]') "
            f"FROM audit_logs WHERE ticket_id = {q(ticket)} AND step = 'OVERRIDE'"
        ))  # fmt: skip

    def ticket_row(self, ticket: str) -> Any:
        return self.shell.sql(f"SELECT row_to_json(t) FROM tickets t WHERE ticket_id = {q(ticket)}")

    def decide(self, aid: Any, who: str, body: Mapping[str, Any] | None = None) -> httpx.Response:
        return self.post(f"/api/approvals/{aid}/decision", body or {"decision": "approved"}, self.tokens[who])

    def look(self, aid: Any, who: str) -> httpx.Response:
        return self.http.get(f"/api/approvals/{aid}", headers=self.tokens[who])


# ---- Bước chung -------------------------------------------------------------------------------------------------------------


def _begin(ctx: Ctx) -> None:
    ctx.mock_reset()
    ctx.login_users()


def _one_approval(ctx: Ctx, t: str) -> dict[str, Any]:
    rows = ctx.approval(t)
    if len(rows) != 1:
        raise StackError(f"ticket {t}: cần đúng 1 phiếu, thấy {len(rows)}")
    return rows[0]


def _pending(ctx: Ctx, spec: tuple[str, str, str] = HITL) -> tuple[str, dict[str, Any]]:
    t, v = ctx.ticket(spec)
    ctx.report.eq(t, "chờ duyệt", S_PENDING_APPROVAL, v["status"])
    return t, _one_approval(ctx, t)


def _roster(ctx: Ctx, t: str, a: Mapping[str, Any], want: tuple[Any, ...]) -> None:
    ctx.report.eq(t, "phiếu: (người duyệt, dự phòng, xung đột, loại xung đột)", want,
                  (a["approver_id"], a["backup_approver_id"], a["conflict_detected"], a["conflict_type"]))  # fmt: skip


def _approve_and_confirm(ctx: Ctx, t: str, aid: Any, who: str) -> None:
    rep = ctx.report
    before = ctx.turn_count(t)
    r = ctx.decide(aid, who)
    rep.eq(t, f"{who} duyệt → 202", 202, r.status_code)
    v = ctx.settle(t, before)
    rep.eq(t, "thực thi xong → chờ xác nhận", S_CONFIRMING, v["status"])
    rep.eq(t, f"POST {RENEW} đúng 1 lần (mock)", 1, ctx.mock_calls(RENEW))
    rep.eq(t, "tổng lời gọi ghi = 1 (mock)", 1, ctx.mock_writes())
    before = ctx.turn_count(t)
    r = ctx.post(f"/api/tickets/{t}/confirm", {"confirmed": True}, ctx.tokens[CHAU])
    rep.eq(t, "xác nhận → 202", 202, r.status_code)
    v = ctx.settle(t, before)
    rep.eq(t, "đóng", (S_RESOLVED, "resolved_user_confirmed"), (v["final_state"], v["close_reason"]))


# ---- Kịch bản ---------------------------------------------------------------------------------------------------------------


def preflight(ctx: Ctx) -> None:
    rep = ctx.report
    body = ctx.http.get("/api/health").json()
    rep.eq("-", "health status", "ok", body.get("status"))
    rep.eq("-", "health runtime", "up", body.get("runtime"))
    rep.eq("-", "health kb", "ready", (body.get("kb") or {}).get("status"))
    rep.eq("-", "worker healthy", "healthy", ctx.worker_health())
    ctx.login_users()
    rep.check("-", f"đăng nhập {', '.join(USERS)}", True, "200", "200")


def g4_01(ctx: Ctx) -> None:
    """i1: duyệt → thực thi đúng 1 lần → xác nhận → đóng. Hạn phiếu = 120 s (chứng minh SLA=2 có hiệu lực)."""
    rep = ctx.report
    _begin(ctx)
    t, a = _pending(ctx)
    _roster(ctx, t, a, (L1_01, L1_02, False, None))
    rep.check(t, "hạn duyệt = SLA 2 phút (deadline − created_at)", abs(float(a["sla_s"]) - SLA_S) <= 3, "120 ± 3 s", a["sla_s"])
    rep.eq(t, "0 lời gọi ghi trước khi duyệt (mock)", 0, ctx.mock_writes())
    _approve_and_confirm(ctx, t, a["approval_id"], HA)
    rep.eq(t, "transaction_log", [["renew_vpn_cert", "begun"]], ctx.txlog(t))
    ctx.resolved = t


def g4_11(ctx: Ctx) -> None:
    """i13: duc.pv ghi đè ticket g4-01 (HITL → L2) → 201; lần 2 → 409 `already_overridden`; đúng 1 dòng; `tickets` không đổi."""
    rep = ctx.report
    t = ctx.resolved
    if t is None:  # chạy lẻ S=g4-11 → tự dựng ticket đã đóng
        g4_01(ctx)
        t = ctx.resolved
    assert t is not None
    ctx.login(DUC)  # đăng nhập ≤ 10 phút (P1 reauth)
    before = ctx.ticket_row(t)
    r = ctx.post(f"/api/tickets/{t}/override", {"override_decision": "L2", "reason_code": "too_risky_for_auto"}, ctx.tokens[DUC])
    rep.eq(t, "ghi đè → 201, quyết định gốc HITL", (201, "HITL"), (r.status_code, r.json().get("original_decision")))
    r = ctx.post(f"/api/tickets/{t}/override", {"override_decision": "AUTO", "reason_code": "other", "note": "đổi ý"},
                 ctx.tokens[DUC])  # fmt: skip
    rep.eq(t, "ghi đè lần 2 → 409 already_overridden", (409, {"detail": "already_overridden"}), (r.status_code, r.json()))
    rep.eq(t, "đúng 1 dòng OVERRIDE", [[L1_02, "HITL", "L2"]], ctx.overrides(t))
    rep.eq(t, "dòng tickets trước = sau", before, ctx.ticket_row(t))


def g4_02(ctx: Ctx) -> None:
    """i2 + i3: từ chối không note → 422, phiếu vẫn pending; từ chối có note → `S_REJECTED`, 1 tin `rejection`, 0 ghi."""
    rep = ctx.report
    _begin(ctx)
    t, a = _pending(ctx)
    r = ctx.decide(a["approval_id"], HA, {"decision": "rejected"})
    rep.eq(t, "từ chối không note → 422", (422, {"detail": "rejected_requires_note"}), (r.status_code, r.json()))
    rep.eq(t, "phiếu vẫn pending", "pending", _one_approval(ctx, t)["status"])
    before = ctx.turn_count(t)
    r = ctx.decide(a["approval_id"], HA, {"decision": "rejected", "note": REJECT_NOTE})
    rep.eq(t, "từ chối có note → 202", 202, r.status_code)
    v = ctx.settle(t, before)
    rep.eq(t, "đóng: từ chối", (S_REJECTED, "rejected_by_approver"), (v["final_state"], v["close_reason"]))
    texts = [m["text"] for m in gate3.msgs(v, "rejection")]
    rep.check(t, "1 tin rejection nêu LAP-0501 + ghi chú", len(texts) == 1 and "LAP-0501" in texts[0] and REJECT_NOTE in texts[0],
              "1 tin", texts)  # fmt: skip
    rep.eq(t, "0 lời gọi ghi (mock)", 0, ctx.mock_writes())


def g4_06(ctx: Ctx) -> None:
    """TC19 (x2): ha.lt gửi cho máy của mình → xung đột self → Trưởng BP; ha.lt (người gửi) quyết → 403."""
    rep = ctx.report
    _begin(ctx)
    t, a = _pending(ctx, SELF)
    _roster(ctx, t, a, (HEAD, None, True, "self"))
    r = ctx.decide(a["approval_id"], HA)
    rep.eq(t, "ha.lt (người gửi, không được giao) quyết → 403", 403, r.status_code)
    rep.eq(t, "0 lời gọi ghi (mock)", 0, ctx.mock_writes())


def g4_07(ctx: Ctx) -> None:
    """x3: khoa.dv (sếp trực tiếp của l1_01) → Trưởng BP, `boss_of_approver`."""
    _begin(ctx)
    t, a = _pending(ctx, BOSS)
    _roster(ctx, t, a, (HEAD, None, True, "boss_of_approver"))
    ctx.report.eq(t, "0 lời gọi ghi (mock)", 0, ctx.mock_writes())


def g4_09(ctx: Ctx) -> None:
    """i11 + 4c c7: long.nh (L2) quyết/xem → 403; khoa.dv (L1 không được giao) xem → 404 CÙNG thân với id không tồn tại."""
    rep = ctx.report
    _begin(ctx)
    t, a = _pending(ctx)
    aid = a["approval_id"]
    rep.eq(t, "L2 quyết → 403", 403, ctx.decide(aid, LONG).status_code)
    rep.eq(t, "L2 xem phiếu → 403", 403, ctx.look(aid, LONG).status_code)
    other, missing = ctx.look(aid, KHOA), ctx.look(MISSING_APPROVAL, KHOA)
    rep.eq(t, "L1 khác xem → 404 như id không có", (404, missing.content), (other.status_code, other.content))
    rep.eq(t, "first_viewed_at vẫn NULL", None, _one_approval(ctx, t)["first_viewed_at"])


def g4_10(ctx: Ctx) -> None:
    """c7/c8: người được giao xem → 200 `role_as=primary`, ghi `first_viewed_at`; xem lần 2 giữ lần đầu; duyệt → B16
    `decided_without_view=false`."""
    rep = ctx.report
    _begin(ctx)
    t, a = _pending(ctx)
    r = ctx.look(a["approval_id"], HA)
    rep.eq(t, "ha.lt xem → 200 primary", (200, "primary"), (r.status_code, r.json().get("role_as")))
    first = _one_approval(ctx, t)["first_viewed_at"]
    rep.check(t, "first_viewed_at được ghi", first is not None, "có", first)
    rep.eq(t, "xem lần 2 → 200", 200, ctx.look(a["approval_id"], HA).status_code)
    rep.eq(t, "first_viewed_at giữ lần đầu", first, _one_approval(ctx, t)["first_viewed_at"])
    _approve_and_confirm(ctx, t, a["approval_id"], HA)
    rep.eq(t, "B16 decided_without_view=false", [False], [r["detail"].get("decided_without_view") for r in ctx.b16(t)
                                                         if r["event"] == "approved"])  # fmt: skip


def g4_04(ctx: Ctx) -> None:
    """c5: dự phòng duc.pv quyết TRƯỚC nhắc 2 → 403; chờ nhắc 2 → duyệt 202 `decided_as=backup` → thực thi → đóng."""
    rep = ctx.report
    _begin(ctx)
    t, a = _pending(ctx)
    aid = a["approval_id"]
    rep.eq(t, "dự phòng quyết trước nhắc 2 → 403", 403, ctx.decide(aid, DUC).status_code)

    def reminded() -> dict[str, Any] | None:
        row = _one_approval(ctx, t)
        return row if row["reminder_2_at"] else None

    a = wait_for("nhắc 2 (reminder_2_at)", reminded, SLA_S + 15, interval=1)
    if a["past_deadline"]:
        rep.fail(t, "dự phòng quyết sau nhắc 2", "nhắc 2 tới khi đã quá hạn — không còn cửa sổ để bấm (máy chậm/worker trễ)")
        return
    before = ctx.turn_count(t)
    r = ctx.decide(aid, DUC)
    rep.eq(t, "dự phòng quyết sau nhắc 2 → 202 backup", (202, "backup"), (r.status_code, r.json().get("decided_as")))
    v = ctx.settle(t, before)
    rep.eq(t, "thực thi xong → chờ xác nhận", S_CONFIRMING, v["status"])
    rep.eq(t, "tổng lời gọi ghi = 1 (mock)", 1, ctx.mock_writes())
    rep.eq(t, "phiếu decided_by l1_02", L1_02, _one_approval(ctx, t)["decided_by"])
    rep.eq(t, "B16 decided_as=backup", ["backup"], [r["detail"].get("decided_as") for r in ctx.b16(t) if r["event"] == "approved"])


def g4_03(ctx: Ctx) -> None:
    """c3 + i6: không ai quyết — nhắc 1 (≥ 50%), nhắc 2 (≥ 80%), cả hai trước hạn; worker → E6, phiếu `timeout`, 0 ghi."""
    rep = ctx.report
    _begin(ctx)
    t, _ = _pending(ctx)
    v = ctx.closed(t, timeout=SLA_S + 60)
    a = _one_approval(ctx, t)
    created, deadline = _ts(a["created_at"]), _ts(a["deadline"])
    for n, frac, col in ((1, 0.5, "reminder_1_at"), (2, 0.8, "reminder_2_at")):
        mark = created + (deadline - created) * frac
        at = _ts(a[col]) if a[col] else None
        rep.check(t, f"nhắc {n}: không sớm hơn {int(frac * 100)}% hạn, trước hạn", reminder_in_window(at, mark, deadline),
                  f"[{mark.isoformat()}, {deadline.isoformat()})", a[col])  # fmt: skip
    rep.eq(t, "→ E6", (S_ESCALATED, "E6"), (v["final_state"], v["exit_code"]))
    rep.eq(t, "phiếu timeout", "timeout", a["status"])
    rep.eq(t, "B16 approval_timeout", [("approval_timeout", "timeout")], [(r["event"], r["approval_result"]) for r in ctx.b16(t)])
    rep.eq(t, "0 lời gọi ghi (mock)", 0, ctx.mock_writes())


def g4_05(ctx: Ctx) -> None:
    """i7 trên stack (TQ-16): bấm sau hạn → 409 + đúng 1 `late_event` (`expired`, hoặc `already_decided` nếu worker thật quét trước) →
    E6, phiếu `timeout`, 0 ghi. Ca "phiếu vẫn pending sau bấm muộn" ghim ở e2e i7 (FakeClock)."""
    rep = ctx.report
    _begin(ctx)
    t, a = _pending(ctx)
    wait_for("quá hạn phiếu (giờ DB)", lambda: True if _one_approval(ctx, t)["past_deadline"] else None, SLA_S + 15, interval=1)
    r = ctx.decide(a["approval_id"], HA)
    rep.eq(t, "bấm sau hạn → 409", 409, r.status_code)
    late = ctx.late_events(t)
    rep.check(t, "đúng 1 late_event (expired | already_decided)",
              len(late) == 1 and late[0].get("reason") in ("expired", "already_decided"), "1 dòng", late)  # fmt: skip
    v = ctx.closed(t, timeout=60)
    rep.eq(t, "→ E6", (S_ESCALATED, "E6"), (v["final_state"], v["exit_code"]))
    rep.eq(t, "phiếu timeout", "timeout", _one_approval(ctx, t)["status"])
    rep.eq(t, "0 lời gọi ghi (mock)", 0, ctx.mock_writes())


def g4_12(ctx: Ctx) -> None:
    """P5 (Q-4d-10 = A): `audit_check <các ticket lần chạy này đã tạo>` TRONG container (chỉ đọc) → mã 0, `0 thiếu, 0 bí mật`; mã khác →
    in NGUYÊN bảng (không có giá trị). Danh sách rỗng (vd chạy lẻ `S=g4-12`) → FAIL rõ lý do, không xanh giả. Log backend+worker từ giờ
    bắt đầu chạy → 0 trúng luật bí mật (`scan_log` trên máy — không in giá trị)."""
    rep = ctx.report
    name = "audit_check trên ticket của lần chạy: mã 0, 0 thiếu, 0 bí mật"
    tickets = [q(t).strip("'") for t in ctx.owner]  # q(): kiểm dạng id trước khi đưa vào lệnh
    if not tickets:
        rep.fail("-", name, "lần chạy chưa tạo ticket nào (chạy lẻ S=g4-12?) — chạy cùng các kịch bản khác: make gate4 S=all")
    else:
        compose = shlex.join([*ctx.shell.compose_base, "exec", "-T", "backend"])
        out = ctx.shell.run([*ctx.shell.compose_base, "exec", "-T", "backend", "sh", "-c", AUDIT_SH, "sh", *tickets],
                            shown=f"{compose} python -m app.audit.check <{len(tickets)} ticket của lần chạy>")  # fmt: skip
        code, lines = audit_result(out)
        ok = code == 0 and any(line.startswith("KẾT LUẬN: 0 thiếu, 0 bí mật") for line in lines)
        rep.check("-", name, ok, f"mã 0, KẾT LUẬN: 0 thiếu, 0 bí mật ({len(tickets)} ticket)",
                  f"mã {code}, {lines[-1] if lines else 'không có dòng KẾT LUẬN'}")  # fmt: skip
        if not ok:
            for line in lines:  # bảng audit_check: ticket | điểm | tên trường — không giá trị (S6)
                rep.echo(f"    {line}")
    since = ctx.start.strftime("%Y-%m-%dT%H:%M:%SZ")  # RFC 3339 — `compose logs --since`
    try:
        logs = ctx.shell.compose("logs", "--no-color", "--since", since, "backend", "worker")
    except StackError as exc:  # lỗi mang đuôi đầu ra = chính log cần quét → chỉ in dòng đầu (soát 4d DỪNG 2)
        rep.fail("-", "log backend+worker: 0 trúng luật bí mật", str(exc).splitlines()[0])
        return
    hits = scan_log(logs.splitlines(), SecretScanner.from_config(CONFIG_DIR))
    rep.eq("-", "log backend+worker: 0 trúng luật bí mật", [], [(h.ref, h.rule) for h in hits])


SCENARIOS: dict[str, Callable[[Ctx], None]] = {
    "preflight": preflight, "g4-01": g4_01, "g4-11": g4_11, "g4-02": g4_02, "g4-06": g4_06, "g4-07": g4_07,
    "g4-09": g4_09, "g4-10": g4_10, "g4-04": g4_04, "g4-03": g4_03, "g4-05": g4_05, "g4-12": g4_12,
}  # fmt: skip
ALL = list(SCENARIOS)  # g4-12 cuối: quét mọi ticket của lần chạy


# ---- Biên bản (TQ-17) -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    name: str
    passed: int
    failed: int
    first_fail: str


def outcomes(per: Sequence[tuple[str, Sequence[Line]]]) -> list[Outcome]:
    return [Outcome(name, sum(line.ok for line in lines), sum(not line.ok for line in lines),
                    next((line.render() for line in lines if not line.ok), "")) for name, lines in per]  # fmt: skip


def render_bienban(rows: Sequence[Outcome], *, run_id: str, started: datetime, ended: datetime, commit: str, dirty: int) -> str:
    total_fail = sum(r.failed for r in rows)
    table = "\n".join(f"| {r.name} | {r.passed} | {r.failed} | {r.first_fail.replace('|', '/')[:160]} |" for r in rows)
    verdict = "ĐẠT (0 FAIL)" if total_fail == 0 and rows else f"KHÔNG ĐẠT ({total_fail} FAIL)"
    return (
        f"# Biên bản chạy cổng 4 (`make gate4 S=all`)\n\n"
        f"- Lần chạy: `{run_id}` — bắt đầu {started:%d/%m/%Y %H:%M:%S %Z}, kết thúc {ended:%H:%M:%S %Z}\n"
        f"- Commit: `{commit}` (tệp đã theo dõi đang sửa: {dirty})\n"
        f"- Người chạy (không làm chính): ______________________\n"
        f"- Máy (hãng, CPU, RAM, hệ điều hành): ______________________\n\n"
        f"| Kịch bản | PASS | FAIL | Dòng FAIL đầu tiên |\n|---|---|---|---|\n{table}\n\n"
        f"**Kết luận:** {verdict}\n\n"
        f"Chữ ký người chạy: ______________________   Ngày: ____/____/________\n"
    )


def _git(run: Run, *args: str) -> str:
    code, out = run(["git", *args], None)
    return out.strip() if code == 0 else "?"


def write_bienban(path: Path, rows: Sequence[Outcome], *, run_id: str, started: datetime, run: Run) -> Path:
    commit = _git(run, "rev-parse", "--short=7", "HEAD")
    dirty = len([line for line in _git(run, "status", "--porcelain", "--untracked-files=no").splitlines() if line.strip()])
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
        url = check_url(env.get("GATE4_URL", DEFAULT_URL))
        shell = Shell(shlex.split(env.get("COMPOSE", "docker compose")), run=run, echo=echo)
        safety_gate(shell)
        flags = gate3.env_gate(shell)
        sla = sla_gate(shell)
    except (Unsafe, StackError) as exc:
        echo(f"DỪNG (chốt an toàn): {exc}")
        return 2
    echo(f"APPROVAL_SLA_MINUTES_DEV: backend{SLA_LABELS[sla['backend']]}, worker{SLA_LABELS[sla['worker']]}")
    return names, shell, url, flags


def main(argv: Sequence[str], *, run: Run = subprocess_run, env: Mapping[str, str] = os.environ,
         echo: Callable[[str], None] = print, out_dir: Path | None = None) -> int:  # fmt: skip
    opened = open_ctx(argv, run=run, env=env, echo=echo)
    if isinstance(opened, int):
        return opened
    names, shell, url, flags = opened
    report = Report(echo=echo)
    with httpx.Client(base_url=url, timeout=15) as http:
        ctx = Ctx(shell=shell, http=http, report=report, password=env.get("GATE4_PASSWORD") or gate2.password_from(env))
        echo(f"gate4 run {ctx.run_id}: {names} (bắt đầu {ctx.start.isoformat()})")
        gate3.warnings(ctx, flags)
        gate3.warm_rerank(ctx)  # TQ-15: trước kịch bản đầu, một lần
        stopped, per = run_scenarios(ctx, names)
        if stopped is not None:
            return stopped
    code = report.summary()
    if list(names) == ALL:  # TQ-17: chỉ lần chạy đủ mới có biên bản
        stamp = ctx.start.astimezone(ZoneInfo(ctx.hours.tz))
        path = write_bienban((out_dir or Path(__file__).parent) / f"bienban-gate4-{stamp:%Y%m%d}.md", outcomes(per),
                             run_id=ctx.run_id, started=stamp, run=run)  # fmt: skip
        echo(f"Biên bản: {path} — điền người chạy, máy, ký; KHÔNG commit bản đã điền")
    return code



if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
