"""`POST /api/tickets/{ticket_id}/override` (TC23) qua HTTP thật của app, graph trên bản giả (`desk_env`). Phase 4 chặng 4d DỪNG 1,
viết TỪ ĐẶC TẢ trước thân code: phase4 mục 7.1 P1–P4, 7.3 i13/i14/i14b; PLAN-4d mục 2.1 (hợp đồng — bảng thứ tự 1–11), mục 3
(o1–o5), TQ-1, TQ-2, TQ-4.

Người (desk_env, `seed_ad_users`): an.nv = nv001 (employee, người gửi), binh.tt = nv002 (employee), ha.lt = l1_01 (l1), duc.pv = l1_02
(l1 — người ghi đè chuẩn), long.nh = l2_01 (l2, không có `decision:override`). (Manager không dùng: đăng nhập manager cần MFA.)

Cách dựng ticket ĐÃ KẾT THÚC (chọn rõ, PLAN lời giao): plan node giả `{"b12_assess": "deny"}` → graph tự chạy tới `S_ESCALATED` (E5,
`tickets.final_state` có — khuôn `test_tickets_api.test_closed_status_from_final_state`). Dấu vết quyết định (`risk_decided` /
`B10 deflected_info_only`) của ticket đó được ĐẶT LẠI tường minh trên `env.h.audit.rows` (bảng audit giả mà `MemoryApprovals.
decision_trail` đọc) → `original_decision` kỳ vọng là hằng của bảng P3, không phụ thuộc node giả ghi gì. Riêng o2 (i13 unit) chạy luồng
THẬT của bản giả (duyệt → xác nhận → `S_RESOLVED`) và tính `original_decision` kỳ vọng bằng bảng P3 viết lại trong test
(`_spec_original`) trên chính dòng audit node giả đã ghi. Ticket MỞ: plan mặc định → `S_PENDING_APPROVAL`.
"""

import copy
import hashlib
import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest
from app.api.errors import GUARD_UNAVAILABLE
from app.domain.states import S_ESCALATED, S_PENDING_APPROVAL, S_RESOLVED
from app.guard.privacy import NOTICE_SECRET, RedactionResult, RegexPrivacyGuard
from app.settings import Settings
from tests.fakes.desk import MASK, SECRET, DeskEnv, MaskingGuard, desk_env

pytestmark = pytest.mark.asyncio

ROUTE = "/api/tickets/{ticket_id}/override"
PERM = "decision:override"
DENY: dict[str, str | list[str]] = {"b12_assess": "deny"}  # node giả B12 → E5, ticket kết thúc
FORBIDDEN = {"detail": "forbidden"}
NOT_FOUND = {"detail": "not_found"}
REAUTH = {"detail": "reauth_required"}
TICKET_OPEN = {"detail": "ticket_open"}
SAME = {"detail": "same_as_original"}
ALREADY = {"detail": "already_overridden"}
NOTE_FIELD = {"error": "invalid_request", "fields": ["note"]}  # như `parse_body` (vd `test_guard_api.py` e8: ["text"]) — hợp đồng PLAN sửa từ "body.note"
RESPONSE_KEYS = {"ticket_id", "original_decision", "override_decision", "reason_code", "notices"}
ROW_KEYS = frozenset({
    "ticket_id", "created_at", "step", "event", "from_status", "to_status", "original_decision", "override_decision",
    "overrider_id", "note", "detail", "idempotency_key",
})  # fmt: skip
RISK, DEFLECT = ("B13/B14", "risk_decided"), ("B10", "deflected_info_only")
CANARY = "Canary#" + "4d-override"  # ghép lúc chạy (gitleaks)
LIMIT = 64 * 1024


def _key(ticket_id: str, overrider_id: str) -> str:
    return hashlib.sha256(("override:" + ticket_id + ":" + overrider_id).encode()).hexdigest()


def _spec_original(env: DeskEnv, ticket_id: str) -> str:
    """Bảng P3 + TQ-3 viết lại độc lập trong test (dòng `risk_decided` sau cùng = mới nhất theo thứ tự ghi)."""
    rows = [r for r in env.h.audit.rows if r["ticket_id"] == ticket_id]
    risk = [r for r in rows if (r["step"], r["event"]) == RISK]
    if risk:
        last = risk[-1]
        route = (last.get("detail") or {}).get("route")
        if route is not None:
            return {"AUTO": "AUTO", "HITL": "HITL", "ESCALATE_L2": "L2"}.get(route, "L2")
        return {"allow": "AUTO", "approval_required": "HITL"}.get(last.get("policy_decision") or "", "L2")
    return "ANSWER" if any((r["step"], r["event"]) == DEFLECT for r in rows) else "L2"


def _other_than(decision: str) -> str:
    return "L2" if decision != "L2" else "AUTO"


type Risk = tuple[str | None, str | None]  # (detail.route | None, cột policy_decision | None)


def _set_trail(env: DeskEnv, ticket_id: str, *, risks: Sequence[Risk] = (), deflected: bool = False) -> None:
    """Đặt lại dấu vết quyết định của ticket trên bảng audit giả: bỏ mọi `risk_decided`/`deflected_info_only` cũ, ghi theo thứ tự
    `risks` = [(detail.route | None, cột policy_decision | None), …] (cái sau = mới nhất) rồi (tuỳ chọn) dòng B10."""
    env.h.audit.rows[:] = [r for r in env.h.audit.rows
                           if not (r["ticket_id"] == ticket_id and (r["step"], r["event"]) in (RISK, DEFLECT))]  # fmt: skip
    for route, policy in risks:
        env.h.audit.rows.append({"ticket_id": ticket_id, "step": RISK[0], "event": RISK[1], "policy_decision": policy,
                                 "detail": {} if route is None else {"route": route}})  # fmt: skip
    if deflected:
        env.h.audit.rows.append({"ticket_id": ticket_id, "step": DEFLECT[0], "event": DEFLECT[1], "detail": {}})


async def _finished(
    env: DeskEnv, by: str = "an.nv", *, risks: Sequence[Risk] | None = None, deflected: bool = False
) -> str:
    """Ticket ĐÃ KẾT THÚC (plan DENY) do `by` gửi; dấu vết mặc định: một `risk_decided` route HITL → original HITL."""
    headers = await env.token(by)
    ticket = await env.create(headers)
    await env.drain()
    final = env.h.tickets.final(ticket)
    assert final is not None and final.final_state == S_ESCALATED, "plan deny phải kết thúc ticket"
    _set_trail(env, ticket, risks=[("HITL", "approval_required")] if risks is None else risks, deflected=deflected)
    return ticket


async def _open(env: DeskEnv, by: str = "an.nv") -> str:
    """Ticket MỞ (plan mặc định → chờ duyệt, `final_state` NULL)."""
    headers = await env.token(by)
    ticket = await env.create(headers)
    await env.drain()
    assert env.h.tickets.final(ticket) is None
    assert (await env.ticket(ticket, headers))["status"] == S_PENDING_APPROVAL
    return ticket


def _post(env: DeskEnv, ticket_id: str, headers: dict[str, str] | None, body: Any = None, **fields: Any) -> Any:
    kw: dict[str, Any] = {"content": body} if isinstance(body, str | bytes) else {"json": body if body is not None else fields}
    return env.client.post(f"/api/tickets/{ticket_id}/override", headers=headers or {}, **kw)


def _overrides(env: DeskEnv, ticket_id: str | None = None) -> list[dict[str, Any]]:
    return [r for r in env.h.audit.rows if r["step"] == "OVERRIDE" and (ticket_id is None or r["ticket_id"] == ticket_id)]


def _secret_events(env: DeskEnv) -> int:
    return len(env.sink.of("privacy_secret_redacted"))


def _writes(env: DeskEnv) -> tuple[int, int, int, int]:
    """(dòng OVERRIDE, permission_denied, privacy_secret_redacted, số lần gọi guard)."""
    return len(_overrides(env)), env.denied(), _secret_events(env), env.guard.calls


async def _state_of(env: DeskEnv, ticket_id: str) -> dict[str, Any]:
    """Mọi thứ ghi đè KHÔNG được đụng (P4, S1): dòng `tickets`, lượt, checkpoint, side effect, hạn chờ, phiếu, notifier, executor."""
    snap = await env.h.runner.snapshot(ticket_id)
    return {
        "ticket": copy.deepcopy(env.h.tickets.rows[ticket_id]),
        "turns": copy.deepcopy(env.h.turns.of(ticket_id)),
        "checkpoint": (snap.config, snap.values),
        "effects": {k: dict(v) for k, v in env.h.effects.rows.items() if v["ticket_id"] == ticket_id},
        "waits": [dict(w) for w in env.h.deadlines.waits if w["ticket_id"] == ticket_id],
        "approvals": {k: dict(v) for k, v in env.h.approvals._table.items() if v["ticket_id"] == ticket_id},
        "notified": env.h.notifier.count(ticket_id),
        "executed": env.h.executor.calls[ticket_id],
        "non_override_audit": [dict(r) for r in env.h.audit.rows if r["ticket_id"] == ticket_id and r["step"] != "OVERRIDE"],
    }


class BreakableGuard(MaskingGuard):
    """`MaskingGuard` của desk + công tắc `broken` → ném lỗi có CHỨA văn bản (response/log không được lộ nó)."""

    def __init__(self) -> None:
        super().__init__()
        self.broken = False

    async def redact(self, text: str) -> RedactionResult:
        if self.broken:
            self.calls += 1
            raise RuntimeError(f"guard nổ trên {text!r}")
        return await super().redact(text)


class CountingRealGuard:
    """Guard regex THẬT (L0 + `config/privacy_patterns.json`) có đếm lời gọi — cho `notices` thật và note rỗng sau che."""

    def __init__(self) -> None:
        self.real = RegexPrivacyGuard.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
        self.calls = 0

    async def redact(self, text: str) -> RedactionResult:
        self.calls += 1
        return await self.real.redact(text)


def _clean_422(r: Any) -> list[str]:
    """422 `invalid_request` chung — không `input`/`ctx`, không giá trị người gửi."""
    assert r.status_code == 422, r.text
    body = r.json()
    assert set(body) == {"error", "fields"} and body["error"] == "invalid_request", body
    assert CANARY not in r.text and "input" not in r.text and "ctx" not in r.text
    return list(body["fields"])


# ---- o1 dòng 1: 413 trước mọi thứ ----------------------------------------------------------------------------------------------


async def test_o1_row1_body_over_64kb_413_before_auth() -> None:
    """2.1 dòng 1: body > 64 KB → 413 TRƯỚC cả 401 (không token); không ghi gì, không gọi guard."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        before = _writes(env)
        head, tail = b'{"note": "', b'"}'
        body = head + b"a" * (LIMIT + 1 - len(head) - len(tail)) + tail
        r = await env.client.post(f"/api/tickets/{ticket}/override", content=body,
                                  headers={"content-type": "application/json"})  # fmt: skip
        assert r.status_code == 413
        assert _writes(env) == before


# ---- o1 dòng 2: không có decision:override ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["long.nh", "an.nv", "binh.tt"], ids=["l2", "employee-nguoi-gui", "employee-khac"])
async def test_o1_row2_without_decision_override_403(who: str) -> None:
    """2.1 dòng 2: l2 / nhân viên (kể cả chính người gửi) → 403 `forbidden` + `permission_denied {perm}`; 0 dòng, 0 guard."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        headers = await env.token(who)
        rows, denied, secrets, calls = _writes(env)
        r = await _post(env, ticket, headers, override_decision="L2", reason_code="other", note=f"x {SECRET}")
        assert (r.status_code, r.json()) == (403, FORBIDDEN)
        assert _writes(env) == (rows, denied + 1, secrets, calls)
        ev = env.sink.of("permission_denied")[-1]
        assert (ev.route, ev.detail) == (ROUTE, {"perm": PERM})


async def test_o1_row2_before_row4_missing_ticket_still_403() -> None:
    """Thứ tự: quyền (dòng 2) trước 404 (dòng 4) — l2 gọi ticket không có → 403, không 404."""
    async with desk_env() as env:
        l2 = await env.token("long.nh")
        r = await _post(env, "khong-co", l2, override_decision="L2", reason_code="policy_gap")
        assert (r.status_code, r.json()) == (403, FORBIDDEN)


# ---- o1 dòng 3 / o4: đăng nhập > 10 phút (i14b unit) ----------------------------------------------------------------------------


async def test_o4_i14b_login_older_than_10_minutes_403_reauth() -> None:
    """o4 (P1, M-4d-2): `duc.pv` đăng nhập rồi FakeClock +11 phút (access token 15 phút còn hạn) → 403 `reauth_required`, 1
    `permission_denied {perm, reason: reauth_required}`, 0 dòng OVERRIDE, guard không chạy."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        env.clock.advance(timedelta(minutes=11))
        rows, denied, secrets, calls = _writes(env)
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="policy_gap")
        assert (r.status_code, r.json()) == (403, REAUTH)
        assert _writes(env) == (rows, denied + 1, secrets, calls)
        ev = env.sink.of("permission_denied")[-1]
        assert (ev.user_id, ev.route, ev.detail) == ("l1_02", ROUTE, {"perm": PERM, "reason": "reauth_required"})
        assert _overrides(env, ticket) == []


async def test_o4_i14b_relogin_then_201() -> None:
    """o4: sau 403 `reauth_required`, đăng nhập lại → 201, đúng 1 dòng OVERRIDE."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        env.clock.advance(timedelta(minutes=11))
        assert (await _post(env, ticket, duc, override_decision="L2", reason_code="policy_gap")).status_code == 403
        duc = await env.token("duc.pv")
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="policy_gap")
        assert r.status_code == 201, r.text
        assert len(_overrides(env, ticket)) == 1


async def test_o1_row3_before_row4_missing_ticket_still_reauth() -> None:
    """Thứ tự: reauth (dòng 3) trước 404 (dòng 4)."""
    async with desk_env() as env:
        duc = await env.token("duc.pv")
        env.clock.advance(timedelta(minutes=11))
        r = await _post(env, "khong-co", duc, override_decision="L2", reason_code="policy_gap")
        assert (r.status_code, r.json()) == (403, REAUTH)


async def test_o4_login_9_minutes_ago_is_fresh_enough() -> None:
    """Đối chứng: đăng nhập 9 phút trước (≤ 10) → không bị đòi đăng nhập lại → 201."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        env.clock.advance(timedelta(minutes=9))
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="policy_gap")
        assert r.status_code == 201, r.text


# ---- o1 dòng 4: ticket không có ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {"override_decision": "L2", "reason_code": "policy_gap"},
    {"override_decision": "L2", "reason_code": "other"},  # body sai — 404 vẫn đứng trước 422
])  # fmt: skip
async def test_o1_row4_missing_ticket_404_writes_nothing(body: dict[str, Any]) -> None:
    async with desk_env(plan=DENY) as env:
        await _finished(env)
        duc = await env.token("duc.pv")
        before, audit = _writes(env), len(env.h.audit.rows)
        r = await _post(env, "khong-co", duc, body)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert _writes(env) == before and len(env.h.audit.rows) == audit


# ---- o1 dòng 5 / o3: người gửi tự ghi đè ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {"override_decision": "L2", "reason_code": "policy_gap"},
    {"override_decision": "HITL", "reason_code": "other"},  # cũng là same_as_original + body sai — 403 đứng trước
])  # fmt: skip
async def test_o3_i14_requester_self_override_403_permission_denied(body: dict[str, Any]) -> None:
    """o3 / 2.1 dòng 5 (`can_override`, M-4d-12): ha.lt (l1, CÓ `decision:override`) tự gửi ticket rồi tự ghi đè → 403 `forbidden`,
    `permission_denied {perm, ticket_id, reason: self_override}`; 0 dòng OVERRIDE, guard không chạy."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env, by="ha.lt")
        ha = await env.token("ha.lt")
        rows, denied, secrets, calls = _writes(env)
        r = await _post(env, ticket, ha, body)
        assert (r.status_code, r.json()) == (403, FORBIDDEN)
        assert _writes(env) == (rows, denied + 1, secrets, calls)
        ev = env.sink.of("permission_denied")[-1]
        assert (ev.user_id, ev.route) == ("l1_01", ROUTE)
        assert ev.detail == {"perm": PERM, "ticket_id": ticket, "reason": "self_override"}


async def test_o1_row5_before_row6_self_override_on_open_ticket_403() -> None:
    """Thứ tự: `can_override` (dòng 5) trước `ticket_open` (dòng 6)."""
    async with desk_env() as env:
        ticket = await _open(env, by="ha.lt")
        ha = await env.token("ha.lt")
        r = await _post(env, ticket, ha, override_decision="L2", reason_code="policy_gap")
        assert (r.status_code, r.json()) == (403, FORBIDDEN)
        assert env.sink.of("permission_denied")[-1].detail["reason"] == "self_override"


# ---- o1 dòng 6 / o3: ticket còn mở ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {"override_decision": "L2", "reason_code": "policy_gap"},
    {"override_decision": "L2", "reason_code": "other"},  # body sai — 409 vẫn đứng trước 422 (dòng 6 trước 7)
    {"override_decision": "L2", "reason_code": "policy_gap", "note": f"x {SECRET}"},  # guard không chạy
])  # fmt: skip
async def test_o3_i14_open_ticket_409_ticket_open(body: dict[str, Any]) -> None:
    """o3 / 2.1 dòng 6 (M-4d-4): `tickets.final_state` NULL → 409 `ticket_open`; 0 dòng, guard không chạy, không sự kiện."""
    async with desk_env() as env:
        ticket = await _open(env)
        duc = await env.token("duc.pv")
        before = _writes(env)
        state = await _state_of(env, ticket)
        r = await _post(env, ticket, duc, body)
        assert (r.status_code, r.json()) == (409, TICKET_OPEN)
        assert _writes(env) == before
        assert await _state_of(env, ticket) == state


# ---- o1 dòng 7 / o5: body sai ---------------------------------------------------------------------------------------------------


OTHER_NOTE_BAD: list[dict[str, Any]] = [
    {"override_decision": "L2", "reason_code": "other"},
    {"override_decision": "L2", "reason_code": "other", "note": None},
    {"override_decision": "L2", "reason_code": "other", "note": ""},
    {"override_decision": "L2", "reason_code": "other", "note": "   \t  "},
]


@pytest.mark.parametrize("body", OTHER_NOTE_BAD, ids=["thieu-note", "note-null", "note-rong", "note-khoang-trang"])
async def test_o5_other_without_note_422_body_note(body: dict[str, Any]) -> None:
    """o5 / 2.1 dòng 7 + TQ-1: `reason_code="other"` mà thiếu note / note toàn khoảng trắng → 422 `invalid_request`,
    `fields == ["note"]` — kiểm ở bước BODY (trước guard: guard không chạy)."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        before = _writes(env)
        r = await _post(env, ticket, duc, body)
        assert (r.status_code, r.json()) == (422, NOTE_FIELD)
        assert _writes(env) == before


BAD_BODIES: list[tuple[str, Any, str | None]] = [
    ("json-hong", '{"override_decision": "L2", "reason_code": "other", "note": "' + CANARY, None),
    ("khoa-la", {"override_decision": "L2", "reason_code": "policy_gap", CANARY: 1}, "<extra>"),
    ("khoa-la-overrider", {"override_decision": "L2", "reason_code": "policy_gap", "overrider_id": "it_mgr01"}, "<extra>"),
    ("khoa-la-original", {"override_decision": "L2", "reason_code": "policy_gap", "original_decision": "AUTO"}, "<extra>"),
    ("enum-decision", {"override_decision": CANARY, "reason_code": "policy_gap"}, "override_decision"),
    ("enum-decision-chu-thuong", {"override_decision": "l2", "reason_code": "policy_gap"}, "override_decision"),
    ("enum-reason", {"override_decision": "L2", "reason_code": CANARY}, "reason_code"),
    ("thieu-decision", {"reason_code": "policy_gap"}, "override_decision"),
    ("thieu-reason", {"override_decision": "L2"}, "reason_code"),
    ("note-1001", {"override_decision": "L2", "reason_code": "policy_gap", "note": CANARY + "x" * (1001 - len(CANARY))}, "note"),
    ("note-khong-phai-chuoi", {"override_decision": "L2", "reason_code": "policy_gap", "note": 12}, "note"),
    ("body-khong-phai-object", [CANARY], None),
]


@pytest.mark.parametrize(("body", "field_suffix"), [(b, f) for _, b, f in BAD_BODIES], ids=[i for i, _, _ in BAD_BODIES])
async def test_o5_bad_body_422_invalid_request_without_input(body: Any, field_suffix: str | None) -> None:
    """o5 / 2.1 dòng 7 (S4): JSON hỏng, khoá lạ (kể cả `overrider_id`/`original_decision` — server tự tính), enum lạ, note > 1000
    → 422 `{"error":"invalid_request","fields":[…]}`; thân KHÔNG chứa giá trị gửi; 0 dòng, guard không chạy."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        before = _writes(env)
        fields = _clean_422(await _post(env, ticket, duc, body))
        if field_suffix is not None:
            assert any(f.endswith(field_suffix) for f in fields), fields
        assert _writes(env) == before and _overrides(env, ticket) == []


async def test_o5_note_exactly_1000_chars_accepted() -> None:
    """Biên P2: note đúng 1000 ký tự → qua (201)."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="other", note="n" * 1000)
        assert r.status_code == 201, r.text
        [row] = _overrides(env, ticket)
        assert row["note"] == "n" * 1000


async def test_o1_row7_before_row8_bad_body_wins_over_same_as_original() -> None:
    """Thứ tự: body sai (dòng 7) trước `same_as_original` (dòng 8) — `other` thiếu note + quyết định trùng gốc → 422 body."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)  # original HITL
        duc = await env.token("duc.pv")
        r = await _post(env, ticket, duc, override_decision="HITL", reason_code="other")
        assert (r.status_code, r.json()) == (422, NOTE_FIELD)


# ---- o1 dòng 8 / o3: same_as_original ----------------------------------------------------------------------------------------------


TRAILS: list[tuple[str, list[Risk], bool, str]] = [
    ("route-AUTO", [("AUTO", "allow")], False, "AUTO"),
    ("route-HITL", [("HITL", "approval_required")], False, "HITL"),
    ("route-ESCALATE_L2", [("ESCALATE_L2", "deny")], False, "L2"),
    ("route-la", [("KHAC", "allow")], False, "L2"),
    ("khong-route-allow", [(None, "allow")], False, "AUTO"),
    ("khong-route-approval_required", [(None, "approval_required")], False, "HITL"),
    ("khong-route-deny", [(None, "deny")], False, "L2"),
    ("nhieu-risk-moi-nhat", [("AUTO", "allow"), ("HITL", "approval_required")], False, "HITL"),
    ("chi-B10", [], True, "ANSWER"),
    ("risk-va-B10", [("AUTO", "allow")], True, "AUTO"),
    ("khong-gi", [], False, "L2"),
]


@pytest.mark.parametrize(("risks", "deflected", "expected"), [(r, d, e) for _, r, d, e in TRAILS], ids=[i for i, *_ in TRAILS])
async def test_o3_i14_same_as_original_422_guard_not_called(risks: list[Risk], deflected: bool, expected: str) -> None:
    """o3 / 2.1 dòng 8 (P3, M-4d-11): `override_decision == original_decision` (server suy theo bảng P3 từ audit) → 422
    `same_as_original`; guard KHÔNG chạy (note có bí mật vẫn không có `privacy_secret_redacted`), 0 dòng."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env, risks=risks, deflected=deflected)
        duc = await env.token("duc.pv")
        before = _writes(env)
        r = await _post(env, ticket, duc, override_decision=expected, reason_code="other", note=f"lý do {SECRET}")
        assert (r.status_code, r.json()) == (422, SAME)
        assert _writes(env) == before


@pytest.mark.parametrize(("risks", "deflected", "expected"), [(r, d, e) for _, r, d, e in TRAILS], ids=[i for i, *_ in TRAILS])
async def test_o6_route_original_decision_from_audit_trail(risks: list[Risk], deflected: bool, expected: str) -> None:
    """o6 qua route (P3, TQ-3, M-4d-14): 201 mang `original_decision` server suy; dòng OVERRIDE ghi cùng giá trị."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env, risks=risks, deflected=deflected)
        duc = await env.token("duc.pv")
        override = _other_than(expected)
        r = await _post(env, ticket, duc, override_decision=override, reason_code="policy_gap")
        assert r.status_code == 201, r.text
        assert (r.json()["original_decision"], r.json()["override_decision"]) == (expected, override)
        [row] = _overrides(env, ticket)
        assert (row["original_decision"], row["override_decision"]) == (expected, override)


# ---- o1 dòng 9: guard lỗi ---------------------------------------------------------------------------------------------------------


async def test_o1_row9_guard_error_503_nothing_written(caplog: pytest.LogCaptureFixture) -> None:
    """2.1 dòng 9: guard lỗi → 503 `privacy_guard_unavailable`; 0 dòng OVERRIDE, 0 `privacy_secret_redacted`, log không có note."""
    caplog.set_level(logging.DEBUG)
    guard = BreakableGuard()
    async with desk_env(plan=DENY, guard=guard) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        rows, denied, secrets, calls = _writes(env)
        guard.broken = True
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="other", note=f"lý do {CANARY}")
        assert (r.status_code, r.json()) == (503, GUARD_UNAVAILABLE)
        assert _writes(env) == (rows, denied, secrets, calls + 1)
        assert CANARY not in r.text
    assert CANARY not in caplog.text


async def test_o1_row8_before_row9_same_as_original_does_not_call_broken_guard() -> None:
    """Thứ tự: `same_as_original` (dòng 8) trước guard (dòng 9) — guard hỏng vẫn ra 422, không 503."""
    guard = BreakableGuard()
    async with desk_env(plan=DENY, guard=guard) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        calls = guard.calls
        guard.broken = True
        r = await _post(env, ticket, duc, override_decision="HITL", reason_code="policy_gap", note="trùng")
        assert (r.status_code, r.json()) == (422, SAME)
        assert guard.calls == calls and _overrides(env, ticket) == []


# ---- o1 dòng 10 / o5: other + note rỗng SAU khi che ---------------------------------------------------------------------------------


ZWSP, SHY = chr(0x200B), chr(0x00AD)  # ký tự vô hình — L0 của guard xoá (khuôn S4b của 4c)


@pytest.mark.parametrize("note", [ZWSP, SHY, f" {ZWSP} {SHY} "], ids=["zwsp", "soft-hyphen", "tron"])
async def test_o5_other_note_empty_after_redaction_422(note: str) -> None:
    """2.1 dòng 10 + TQ-1 (khuôn S4b của 4c): guard THẬT (L0 xoá ký tự vô hình) → note `other` rỗng sau che → 422
    `invalid_request` `["note"]`; guard đã chạy đúng 1 lần, 0 dòng."""
    guard = CountingRealGuard()
    async with desk_env(plan=DENY, guard=guard) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        rows, denied, secrets, calls = _writes(env)
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="other", note=note)
        assert (r.status_code, r.json()) == (422, NOTE_FIELD)
        assert _writes(env) == (rows, denied, secrets, calls + 1)


async def test_tq4_non_other_note_empty_after_redaction_stored_null() -> None:
    """TQ-4 / 2.1: note KHÔNG phải `other` mà che xong rỗng → 201, `note` lưu None."""
    guard = CountingRealGuard()
    async with desk_env(plan=DENY, guard=guard) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="policy_gap", note=ZWSP)
        assert r.status_code == 201, r.text
        [row] = _overrides(env, ticket)
        assert row["note"] is None


# ---- o2: i13 unit — đạt, đúng 1 dòng, không đổi ticket, idempotent, 2 người → 2 dòng --------------------------------------------------


async def test_o2_i13_override_finished_ticket_one_row_nothing_else_changes() -> None:
    """o2 (P4, S1, M-4d-1, M-4d-5): ticket đi HẾT luồng giả (chờ duyệt → ha.lt duyệt → an.nv xác nhận → `S_RESOLVED`); duc.pv ghi
    đè → 201 đúng thân; đúng 1 dòng OVERRIDE đủ 12 khoá; `tickets`, lượt, checkpoint, side effect, hạn chờ, phiếu, notifier,
    executor trước = sau; lần 2 cùng người → 409 `already_overridden`, vẫn 1 dòng; người khác (ha.lt) → dòng thứ 2."""
    async with desk_env() as env:
        an, ha = await env.token("an.nv"), await env.token("ha.lt")
        ticket = await env.create(an)
        await env.drain()
        r = await env.client.post(f"/api/approvals/{env.approval_of(ticket)}/decision", json={"decision": "approved"},
                                  headers=ha)  # fmt: skip
        assert r.status_code == 202, r.text
        await env.drain()
        r = await env.client.post(f"/api/tickets/{ticket}/confirm", json={"confirmed": True}, headers=an)
        assert r.status_code == 202, r.text
        await env.drain()
        final = env.h.tickets.final(ticket)
        assert final is not None and final.final_state == S_RESOLVED
        env.clock.advance(timedelta(minutes=3))
        duc = await env.token("duc.pv")
        expected = _spec_original(env, ticket)
        override = _other_than(expected)
        before = await _state_of(env, ticket)
        at = env.clock.now()

        r = await _post(env, ticket, duc, override_decision=override, reason_code="too_risky_for_auto")
        assert r.status_code == 201, r.text
        assert set(r.json()) == RESPONSE_KEYS
        assert r.json() == {"ticket_id": ticket, "original_decision": expected, "override_decision": override,
                            "reason_code": "too_risky_for_auto", "notices": []}  # fmt: skip
        [row] = _overrides(env, ticket)
        assert set(row) == ROW_KEYS, sorted(set(row) ^ ROW_KEYS)
        assert row == {
            "ticket_id": ticket, "created_at": at, "step": "OVERRIDE", "event": "override_recorded", "from_status": None,
            "to_status": None, "original_decision": expected, "override_decision": override, "overrider_id": "l1_02",
            "note": None, "detail": {"reason_code": "too_risky_for_auto"}, "idempotency_key": _key(ticket, "l1_02"),
        }  # fmt: skip
        assert await _state_of(env, ticket) == before

        env.clock.advance(timedelta(seconds=30))
        again = await _post(env, ticket, duc, override_decision="ANSWER" if override != "ANSWER" else "AUTO",
                            reason_code="wrong_answer")  # fmt: skip
        assert (again.status_code, again.json()) == (409, ALREADY)
        assert len(_overrides(env, ticket)) == 1
        assert await _state_of(env, ticket) == before

        ha = await env.token("ha.lt")  # người duyệt — không phải người gửi → được ghi đè
        second = await _post(env, ticket, ha, override_decision=override, reason_code="policy_gap")
        assert second.status_code == 201, second.text
        rows = _overrides(env, ticket)
        assert [r["overrider_id"] for r in rows] == ["l1_02", "l1_01"]
        assert [r["idempotency_key"] for r in rows] == [_key(ticket, u) for u in ("l1_02", "l1_01")]
        assert await _state_of(env, ticket) == before


# ---- o3: note có bí mật ----------------------------------------------------------------------------------------------------------------


async def test_o3_i14_note_with_secret_stored_redacted_and_event() -> None:
    """o3 (P4, M-4d-3): note chứa bí mật → dòng OVERRIDE lưu bản ĐÃ CHE; `privacy_secret_redacted {count}` (như /confirm) gắn
    ticket + route; giá trị gốc không ở audit/sự kiện."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        secrets = _secret_events(env)
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="other", note=f"lý do: {SECRET}")
        assert r.status_code == 201, r.text
        [row] = _overrides(env, ticket)
        assert row["note"] == f"lý do: {MASK}"
        assert _secret_events(env) == secrets + 1
        ev = env.sink.of("privacy_secret_redacted")[-1]
        assert (ev.user_id, ev.ticket_id, ev.route, ev.detail) == ("l1_02", ticket, ROUTE, {"count": 1})
        assert SECRET not in repr(env.h.audit.rows) and SECRET not in repr([e.detail for e in env.sink.events])


async def test_o3_i14_note_with_password_real_guard_notices() -> None:
    """o3 với guard THẬT: mật khẩu trong note → 201 kèm `notices == [NOTICE_SECRET]`, note đã che, canary không ở audit."""
    async with desk_env(plan=DENY, guard=CountingRealGuard()) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        r = await _post(env, ticket, duc, override_decision="L2", reason_code="other",
                        note=f"người dùng gửi mật khẩu của tôi là {CANARY}, cần chặn")  # fmt: skip
        assert r.status_code == 201, r.text
        assert r.json()["notices"] == [NOTICE_SECRET]
        [row] = _overrides(env, ticket)
        assert CANARY not in str(row["note"]) and "[BÍ_MẬT_ĐÃ_ẨN]" in str(row["note"])
        assert CANARY not in repr(env.h.audit.rows) and CANARY not in r.text


# ---- o1 dòng 11: đã ghi đè ---------------------------------------------------------------------------------------------------------------


async def test_o1_row11_second_override_same_person_409_secret_event_still_recorded() -> None:
    """2.1 dòng 11 + TQ-2: lần 2 cùng người → 409 `already_overridden`, vẫn 1 dòng; lần 2 có bí mật VẪN ghi
    `privacy_secret_redacted` (guard chạy trước khi biết trùng — người dùng đã gửi bí mật thật)."""
    async with desk_env(plan=DENY) as env:
        ticket = await _finished(env)
        duc = await env.token("duc.pv")
        assert (await _post(env, ticket, duc, override_decision="L2", reason_code="policy_gap")).status_code == 201
        secrets = _secret_events(env)
        r = await _post(env, ticket, duc, override_decision="AUTO", reason_code="other", note=f"đổi ý {SECRET}")
        assert (r.status_code, r.json()) == (409, ALREADY)
        [row] = _overrides(env, ticket)
        assert (row["override_decision"], row["note"]) == ("L2", None)
        assert _secret_events(env) == secrets + 1
