"""`POST /api/escalations/{id}/close` (P4 tuần 8; B20 mục 4.3, 5.1; P6 §5.3) — bản giả `MemoryEscalations` + `MemoryAudit` của harness.

- Quyền `escalation:handle`: L1 VÀ L2 đóng được ca cấp 2; nhân viên → 403 TRƯỚC 422 thân; D-99: manager (Trưởng IT — chỉ ca cấp 3) qua
  cổng vai trò, thân hợp lệ trên ca cấp 2 → 403 (+ `permission_denied`). Luật cấp 3 + nhận ca: `test_d99_luong_l2.py`.
- Thứ tự: 401 → 403 → 422 thân (`fields` không tiền tố) → 404 `not_found` → 409 `already_closed` → 422 `fields: ["close_result"]`
  (`completed` cho ca deny / E5 / E6) → guard (503 khi lỗi; bản che chỉ khoảng trắng / > 1000 → 422 `["note"]`, KHÔNG cắt).
- 200: thân đúng 9 khoá (D-99 thêm `user_message`); `close_note` = bản ĐÃ che; `new_ticket_id` null trừ `reopened_as_new` (D-99 (A):
  tạo ticket THẬT cùng người gửi + cùng nội dung đã che);
  `tickets.close_reason` theo B20:297–301 khi ticket `S_ESCALATED` còn NULL, khác thì giữ nguyên + log.info.
- Audit: MỘT dòng `B20`/`escalation_closed`, `detail` ĐÚNG {escalation_id, close_result, closed_by, note_length}; không chuỗi bí mật.
  `audit/check.required` không báo thiếu sai vì dòng này, và dòng này KHÔNG thay được ("B20","closed") của điểm 8.
- Hai lần đóng đồng thời → một 200, một 409; một dòng audit.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
import pytest
from app.audit.check import required
from app.db.escalations import CLOSE_EVENT, CLOSE_STEP
from app.domain.final import FinalSummary
from app.domain.states import S_ESCALATED, S_RESOLVED
from tests.fakes.auth import EPOCH
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env
from tests.fakes.graph import MemoryEscalations
from tests.unit.test_approvals_view import _login

pytestmark = pytest.mark.asyncio

URL = "/api/escalations/{}/close"
OUT_KEYS = {
    "escalation_id", "ticket_id", "close_result", "close_reason", "closed_at", "closed_by", "close_note", "new_ticket_id", "user_message",
}  # fmt: skip
NOTE = "Đã kiểm tra lại với người dùng."


def _final(code: str, *, close_reason: str | None = None, state: str = S_ESCALATED) -> FinalSummary:
    return FinalSummary(
        final_state=state, exit_code=code, block_reason=None, close_reason=close_reason, resolution_path="escalated",
        aggregate_status=None, auto_closed=False, intent=None, slots=None, total_turns=1, total_duration_seconds=1, closed_at=EPOCH,
    )  # fmt: skip


@asynccontextmanager
async def env_with(*cases: tuple[str, bool], **kw: Any) -> AsyncIterator[tuple[DeskEnv, MemoryEscalations]]:
    """Mỗi `(mã E, is_deny_case)` → một ticket `S_ESCALATED` + một ca mở (escalation_id = 1, 2, …)."""
    async with desk_env(**kw) as env:
        esc = MemoryEscalations(env.h.tickets, env.h.audit)
        for i, (code, deny) in enumerate(cases, 1):
            tid = f"esc-{i}"
            env.h.tickets.register(tid, EPOCH)
            env.h.tickets.rows[tid]["final"] = _final(code)
            await esc.create(ticket_id=tid, exit_code=code, reason_detail=None, handoff_note={"request": "x"},
                             is_deny_case=deny, created_at=EPOCH)  # fmt: skip
        env.app.state.escalations = esc
        yield env, esc


async def _close(env: DeskEnv, eid: Any, headers: dict[str, str] | None, body: Any = None, **kw: Any) -> httpx.Response:
    payload = {"close_result": "completed", "note": NOTE} if body is None else body
    return await env.client.post(URL.format(eid), json=payload, headers=headers or {}, **kw)


def _audit(env: DeskEnv, ticket: str) -> list[dict[str, Any]]:
    return [r for r in env.h.audit.rows if r["ticket_id"] == ticket and (r["step"], r["event"]) == (CLOSE_STEP, CLOSE_EVENT)]


def _invalid(r: httpx.Response, *fields: str) -> None:
    assert r.status_code == 422, r.text
    assert r.json() == {"error": "invalid_request", "fields": list(fields)}


# ---- quyền + thân 200 ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("user", "role_id"), [("ha.lt", "l1_01"), ("long.nh", "l2_01")])
async def test_l1_and_l2_can_close(user: str, role_id: str) -> None:
    async with env_with(("E1", False)) as (env, esc):
        r = await _close(env, 1, await _login(env, user))
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == OUT_KEYS
        assert (body["escalation_id"], body["ticket_id"], body["close_result"], body["closed_by"]) == (1, "esc-1", "completed", role_id)
        assert (body["close_reason"], body["close_note"], body["new_ticket_id"]) == ("resolved_after_escalation", NOTE, None)
        assert esc.rows[0]["closed_by"] == role_id and esc.rows[0]["close_note"] == NOTE
        final = env.h.tickets.final("esc-1")
        assert final is not None and final.close_reason == "resolved_after_escalation"


@pytest.mark.parametrize(
    ("user", "body"),
    [
        ("an.nv", {"x": 1}),  # nhân viên: 403 TRƯỚC 422 thân
        ("quan.tm", {"close_result": "completed", "note": NOTE}),  # D-99: manager chỉ ca cấp 3 — ca cấp 2 → 403
    ],
)
async def test_employee_and_manager_forbidden(user: str, body: dict[str, Any]) -> None:
    async with env_with(("E1", False)) as (env, esc):
        denied = env.denied()
        r = await _close(env, 1, await _login(env, user), body=body)
        assert r.status_code == 403 and r.json() == {"detail": "forbidden"}
        assert env.denied() == denied + 1 and esc.rows[0]["closed_at"] is None


async def test_no_token_401() -> None:
    async with env_with(("E1", False)) as (env, _):
        assert (await _close(env, 1, None)).status_code == 401


# ---- 404 / 409 / 422 -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("eid", ["999", "abc", "1x", "²", "9" * 19])
async def test_unknown_id_404(eid: str) -> None:
    async with env_with(("E1", False)) as (env, _):
        r = await _close(env, eid, await _login(env, "long.nh"))
        assert r.status_code == 404 and r.json() == {"detail": "not_found"}


async def test_second_close_409_keeps_first_note() -> None:
    async with env_with(("E1", False)) as (env, esc):
        l2 = await _login(env, "long.nh")
        assert (await _close(env, 1, l2)).status_code == 200
        r = await _close(env, 1, l2, body={"close_result": "confirmed_denial", "note": "lần hai"})
        assert r.status_code == 409 and r.json() == {"detail": "already_closed"}
        assert (esc.rows[0]["close_result"], esc.rows[0]["close_note"]) == ("completed", NOTE)
        assert len(_audit(env, "esc-1")) == 1


@pytest.mark.parametrize(("code", "deny"), [("E5", True), ("E5", False), ("E6", False), ("E1", True)])
async def test_completed_on_e5_e6_or_deny_case_422(code: str, deny: bool) -> None:
    async with env_with((code, deny)) as (env, esc):
        _invalid(await _close(env, 1, await _login(env, "long.nh")), "close_result")
        assert esc.rows[0]["closed_at"] is None and _audit(env, "esc-1") == []
        assert env.guard.calls == 0  # luật chặn TRƯỚC khi che ghi chú


@pytest.mark.parametrize(
    ("code", "deny", "result", "reason"),
    [
        ("E5", True, "confirmed_denial", "resolved_after_deny_review"),
        ("E5", True, "reopened_as_new", "resolved_after_deny_review"),
        ("E6", False, "confirmed_denial", "resolved_after_escalation"),
        ("E6", False, "reopened_as_new", "resolved_after_escalation"),
        ("E2", False, "completed", "resolved_after_escalation"),
    ],
)
async def test_close_reason_mapping_and_new_ticket_only_for_reopen(code: str, deny: bool, result: str, reason: str) -> None:
    async with env_with((code, deny)) as (env, esc):
        await _login(env, "an.nv")  # D-100: người gửi có phiên CÒN SỐNG — ticket mới mang phiên đó để qua B1
        live = next(sid for sid, rec in env.store.sessions.items() if rec.user_id == "nv001")
        env.h.tickets.rows["esc-1"].update(requester_id="nv001", session_id=live)
        tickets = set(env.h.tickets.rows)
        r = await _close(env, 1, await _login(env, "long.nh"), body={"close_result": result, "note": NOTE})
        assert r.status_code == 200, r.text
        assert r.json()["close_reason"] == reason
        new = set(env.h.tickets.rows) - tickets
        if result == "reopened_as_new":  # D-99 (A): ticket THẬT, cùng người gửi + cùng nội dung đã che, ghi vào ca
            [new_id] = new
            assert r.json()["new_ticket_id"] == new_id == esc.rows[0]["new_ticket_id"]
            old, fresh = env.h.tickets.rows["esc-1"], env.h.tickets.rows[new_id]
            assert (fresh["requester_id"], fresh["redacted_request"], fresh["session_id"]) == (
                old["requester_id"], old["redacted_request"], live)  # fmt: skip
        else:
            assert r.json()["new_ticket_id"] is None and not new


@pytest.mark.parametrize("session", ["không-có-phiên", None])
async def test_reopen_without_live_requester_session_creates_nothing(session: str | None) -> None:
    """D-100 (máy demo 17/11): phiên của người gửi đã hết / đăng xuất → ticket mới sẽ bị B1 chặn `session_invalid` mà không ai được báo
    → KHÔNG tạo; ca vẫn đóng, `new_ticket_id` null (thông báo quay về câu "đề nghị bạn gửi một yêu cầu mới")."""
    async with env_with(("E6", False)) as (env, esc):
        env.h.tickets.rows["esc-1"].update(session_id=session)
        tickets = set(env.h.tickets.rows)
        r = await _close(env, 1, await _login(env, "long.nh"), body={"close_result": "reopened_as_new", "note": NOTE})
        assert r.status_code == 200, r.text
        assert r.json()["new_ticket_id"] is None and set(env.h.tickets.rows) == tickets
        assert esc.rows[0]["close_result"] == "reopened_as_new" and esc.rows[0].get("new_ticket_id") is None


BAD_BODIES: list[tuple[Any, list[str]]] = [
    ({"close_result": "completed"}, ["note"]),
    ({"note": NOTE}, ["close_result"]),
    ({"close_result": "done", "note": NOTE}, ["close_result"]),
    ({"close_result": "completed", "note": ""}, ["note"]),
    ({"close_result": "completed", "note": " \n\t "}, ["note"]),
    ({"close_result": "completed", "note": "x" * 1001}, ["note"]),
    ({"close_result": "completed", "note": NOTE, "mat_khau": "x"}, ["<extra>"]),
    ({"close_result": "completed", "note": 5}, ["note"]),
]


@pytest.mark.parametrize(("body", "fields"), BAD_BODIES)
async def test_bad_body_422_before_lookup(body: Any, fields: list[str]) -> None:
    async with env_with(("E1", False)) as (env, esc):
        _invalid(await _close(env, 999, await _login(env, "long.nh"), body=body), *fields)  # id không có: thân kiểm TRƯỚC 404
        assert esc.rows[0]["closed_at"] is None


async def test_invalid_json_422() -> None:
    async with env_with(("E1", False)) as (env, _):
        l2 = await _login(env, "long.nh")
        r = await env.client.post(URL.format(1), content=b"{khong-phai-json", headers={**l2, "Content-Type": "application/json"})
        assert r.status_code == 422 and r.json()["error"] == "invalid_request"


# ---- ghi chú qua privacy guard ------------------------------------------------------------------------------------------------


async def test_note_is_redacted_everywhere() -> None:
    async with env_with(("E1", False)) as (env, esc):
        raw = f"mật khẩu: {SECRET} — đã đặt lại cho người dùng"
        r = await _close(env, 1, await _login(env, "long.nh"), body={"close_result": "completed", "note": raw})
        assert r.status_code == 200, r.text
        masked = raw.replace(SECRET, MASK)
        assert r.json()["close_note"] == masked and SECRET not in r.text
        assert esc.rows[0]["close_note"] == masked
        queue = await env.client.get("/api/escalations/queue?status=closed", headers=await _login(env, "ha.lt"))
        assert queue.json()["items"][0]["close_note"] == masked and SECRET not in queue.text
        [row] = _audit(env, "esc-1")
        assert row["detail"] == {"escalation_id": 1, "close_result": "completed", "closed_by": "l2_01", "note_length": len(masked)}
        assert SECRET not in repr(env.h.audit.rows) and MASK not in repr(row)  # không nguyên văn ghi chú (gốc lẫn đã che)
        assert [e.detail for e in env.sink.of("privacy_secret_redacted")] == [{"count": 1}]


async def test_redacted_note_over_1000_is_422_not_truncated() -> None:
    raw = "a" * (1000 - len(SECRET)) + SECRET  # 1000 ký tự; mặt nạ dài hơn chuỗi bí mật → bản che 1001
    assert len(raw) == 1000 and len(raw.replace(SECRET, MASK)) > 1000
    async with env_with(("E1", False)) as (env, esc):
        _invalid(await _close(env, 1, await _login(env, "long.nh"), body={"close_result": "completed", "note": raw}), "note")
        assert esc.rows[0]["closed_at"] is None and _audit(env, "esc-1") == []


class BrokenGuard:
    calls = 0

    async def redact(self, text: str) -> Any:
        raise RuntimeError("guard hỏng")


async def test_guard_down_503_nothing_closed() -> None:
    async with env_with(("E1", False), guard=BrokenGuard()) as (env, esc):
        r = await _close(env, 1, await _login(env, "long.nh"))
        assert r.status_code == 503 and r.json() == {"error": "privacy_guard_unavailable"}
        assert esc.rows[0]["closed_at"] is None and _audit(env, "esc-1") == []


# ---- tickets.close_reason chỉ ghi một lần ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("final", [_final("E1", close_reason="resolved_user_confirmed"), _final("E1", state=S_RESOLVED), None])
async def test_close_reason_not_overwritten(final: FinalSummary | None) -> None:
    """Ticket đã có `close_reason` / không ở `S_ESCALATED` / chưa finalize → giữ nguyên, ca VẪN đóng (log.info kiểm ở test PG)."""
    async with env_with(("E1", False)) as (env, esc):
        env.h.tickets.rows["esc-1"]["final"] = final
        r = await _close(env, 1, await _login(env, "long.nh"))
        assert r.status_code == 200 and esc.rows[0]["closed_at"] is not None
        assert env.h.tickets.rows["esc-1"]["final"] == final
        assert r.json()["close_reason"] == (final.close_reason if final else None)


# ---- đồng thời ------------------------------------------------------------------------------------------------------------------


async def test_concurrent_close_one_wins() -> None:
    async with env_with(("E1", False)) as (env, esc):
        l1, l2 = await _login(env, "ha.lt"), await _login(env, "long.nh")
        a, b = await asyncio.gather(_close(env, 1, l1), _close(env, 1, l2, body={"close_result": "confirmed_denial", "note": "khác"}))
        assert sorted([a.status_code, b.status_code]) == [200, 409]
        winner = a if a.status_code == 200 else b
        assert (esc.rows[0]["close_result"], esc.rows[0]["close_note"]) == (winner.json()["close_result"], winner.json()["close_note"])
        assert len(_audit(env, "esc-1")) == 1


# ---- audit/check ---------------------------------------------------------------------------------------------------------------


async def test_audit_check_not_confused_by_close_row() -> None:
    async with env_with(("E1", False)) as (env, _):
        assert (await _close(env, 1, await _login(env, "long.nh"))).status_code == 200
        [close_row] = _audit(env, "esc-1")
        point8 = {"step": "B20", "event": "closed", "final_state": S_ESCALATED, "exit_code": "E1", "log_id": 1}
        assert required("esc-1", [point8], final_state=S_ESCALATED) == []
        assert required("esc-1", [point8, close_row], final_state=S_ESCALATED) == []  # dòng mới không bị báo thiếu
        missing = required("esc-1", [close_row], final_state=S_ESCALATED)  # nhưng KHÔNG thay được điểm 8
        assert [(m.point, m.fields) for m in missing] == [(8, ("B20/closed",))]


async def test_closed_at_uses_app_clock() -> None:
    async with env_with(("E1", False)) as (env, esc):
        env.clock.advance(timedelta(minutes=7))
        r = await _close(env, 1, await _login(env, "long.nh"))
        assert esc.rows[0]["closed_at"] == env.clock.now() and r.json()["closed_at"].startswith(env.clock.now().strftime("%Y-%m-%dT%H:%M"))



# ---- Q5a (soát 12/11, agent 13 F4): không tự đóng ca escalation của chính ticket mình gửi -------------------------------------


@pytest.mark.parametrize(("user", "uid"), [("long.nh", "l2_01"), ("ha.lt", "l1_01")])
async def test_q5a_khong_tu_dong_ca_cua_ticket_minh_gui(user: str, uid: str) -> None:
    async with env_with(("E9", False), ("E1", False)) as (env, esc):
        env.h.tickets.rows["esc-1"]["requester_id"] = uid
        env.h.tickets.rows["esc-2"]["requester_id"] = uid
        headers = await _login(env, user)
        denied = env.denied()
        for eid in (1, 2):  # E9 lỗi hệ thống; E1 nghi tấn công — đều không được tự đóng `completed`
            r = await _close(env, eid, headers)
            assert r.status_code == 403 and r.json() == {"detail": "forbidden"}, r.text
        assert env.denied() == denied + 2
        assert all(row["closed_at"] is None for row in esc.rows)
        assert _audit(env, "esc-1") == [] and env.h.tickets.final("esc-1").close_reason is None  # type: ignore[union-attr]


async def test_q5a_nguoi_khac_van_dong_duoc() -> None:
    async with env_with(("E9", False)) as (env, esc):
        env.h.tickets.rows["esc-1"]["requester_id"] = "l2_01"  # long.nh gửi, ha.lt đóng
        r = await _close(env, 1, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        assert esc.rows[0]["closed_by"] == "l1_01"
