"""Sửa sau soát bảo mật S11 của 4c (security-reviewer, PLAN-4c bước S11) — các NGHI có kịch bản cụ thể:

- S1c: id phiếu `"²"` (`str.isdigit()` True, `int()` ném) hoặc > 18 chữ số (tràn BIGINT) → coi như KHÔNG CÓ (None/False), không 500.
- S4b: ghi chú từ chối chỉ gồm ký tự vô hình (U+200B, U+00AD) — `strip()` để lọt, privacy guard (L0) xoá hết → rỗng. Route trả 422 sau
  khi che (không tạo sự kiện); B16 nhận `""` (sự kiện cũ) vẫn giữ `""` (không biến thành None → vi phạm CHECK → E9).
- R3: hộp thư gặp `intended_action` hỏng ở dòng audit B15 → log cảnh báo (chỉ id phiếu), không nuốt im lặng.
"""

import logging
from typing import Any, cast

import pytest
from app.approval.store import SqlApprovals
from app.domain.states import S_PENDING_APPROVAL, S_REJECTED
from app.graph.late_event import deliver_event
from app.guard.privacy import guard_from_settings
from app.settings import get_settings
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.fakes.desk import desk_env
from tests.fakes.graph import GraphHarness

pytestmark = pytest.mark.asyncio

INVISIBLE = ["\u200b", "\u00ad", " \u200b \u00ad "]


# ---- S1c ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["²", "１２", "9" * 19, "-1", "1 ", ""], ids=["mu-2", "so-toan-goc", "19-chu-so", "am", "khoang", "rong"])
async def test_s1c_non_ascii_or_overflow_id_is_missing_not_500(bad: str) -> None:
    store = SqlApprovals(cast(AsyncEngine, None))  # id hỏng phải trả TRƯỚC khi chạm DB
    assert await store.get(bad) is None
    assert await store.mark_viewed(bad, None) is False  # type: ignore[arg-type]
    async with store.lock_row(bad) as row:
        assert row is None


# ---- S4b ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("note", INVISIBLE, ids=["zwsp", "soft-hyphen", "tron"])
async def test_s4b_reject_with_invisible_note_422_after_redaction(note: str) -> None:
    """Guard THẬT (L0 xoá ký tự định dạng): ghi chú rỗng sau khi che → 422 `rejected_requires_note`, phiếu vẫn `pending`, không resume."""
    async with desk_env(guard=guard_from_settings(get_settings())) as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        ticket = await env.create(an)
        await env.drain()
        aid = env.approval_of(ticket)
        r = await env.client.post(f"/api/approvals/{aid}/decision", headers=l1, json={"decision": "rejected", "note": note})
        assert r.status_code == 422
        await env.drain()
        assert env.h.approvals.status(aid) == "pending"
        assert (await env.ticket(ticket, an))["status"] == S_PENDING_APPROVAL
        assert not any(t["event_type"] == "resume" for t in env.h.turns.of(ticket))


async def test_s4b_b16_keeps_empty_note_not_e9() -> None:
    """Sự kiện cũ mang `note=""` (trước sửa route) → B16 giữ `""` (CHECK `rejected_needs_note` qua), ticket `S_REJECTED`, không E9;
    tin không có câu ghi chú, `note_suppressed=false`."""
    h = GraphHarness()
    await h.submit("t1")
    ev: dict[str, Any] = {"kind": "rejected", "note": "", "approver_id": "l1-fake", "at": h.clock.now().isoformat(),
                          "reason_code": None, "view_duration": None, "decided_as": "primary"}  # fmt: skip
    await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, ev)
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values.get("exit_code")) == (S_REJECTED, None)
    assert h.approvals._table["1"]["note"] == ""
    [msg] = [m for m in snap.values["conversation"] if m.get("kind") == "rejection"]
    assert "Ghi chú" not in msg["text"]
    [row] = [r for r in h.audit.rows if r["ticket_id"] == "t1" and r["step"] == "B16"]
    assert row["detail"]["note_suppressed"] is False


# ---- R3 ----------------------------------------------------------------------------------------------------------------------


async def test_r3_inbox_broken_audit_action_logged_by_id_only(caplog: pytest.LogCaptureFixture) -> None:
    async with desk_env() as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        ticket = await env.create(an)
        await env.drain()
        aid = env.approval_of(ticket)
        plan_hash = env.h.approvals._table[aid]["action_plan_hash"]
        broken = {"type": "renew_vpn_cert", "target": "device:LAP-0501", "secret_like": "SHOULD-NOT-BE-LOGGED"}
        env.h.audit.rows.append({"ticket_id": ticket, "step": "B15", "event": "queued", "action_plan_hash": plan_hash,
                                 "intended_action": broken})  # fmt: skip
        with caplog.at_level(logging.WARNING, logger="app.api.approvals"):
            r = await env.client.get("/api/approvals?mine=1", headers=l1)
        assert r.status_code == 200
        [item] = r.json()["items"]
        assert (str(item["approval_id"]), item["action_type"], item["device_id"]) == (aid, "renew_vpn_cert", "LAP-0501")
        [rec] = [x for x in caplog.records if "intended_action" in x.getMessage()]
        assert aid in rec.getMessage() and "SHOULD-NOT-BE-LOGGED" not in rec.getMessage()
