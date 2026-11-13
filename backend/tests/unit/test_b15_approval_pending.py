"""Q3 M4 (ĐP 09/11): B15 báo người dùng khi yêu cầu chờ duyệt.

Bằng chứng (demo): 8 ca gửi duyệt (gia hạn VPN, uTorrent…) → người dùng KHÔNG nhận tin nào — B15 chỉ `notify_approver`. Nay: sau khi tạo
phiếu + `notify_approver`, B15 gửi MỘT tin CỐ ĐỊNH qua `effects.once("notify_user", sub="approval_pending")` + output guard:
"Yêu cầu {nhãn hành động} cho {đích} cần được duyệt theo quy định của công ty. Mình đã gửi phiếu duyệt; có kết quả mình báo bạn tại đây."
(`ACTION_LABELS` + `target_phrase`; KHÔNG nêu người duyệt). Chạy lại node / nhánh phiếu cũ (TC33) không gửi lần 2. Ticket CON: tin thành
notice của con (needs=none) như mọi `notify_user` khác của con. `kind` tin = `approval_pending`, needs `none` (FE: tin thường, không nút).
"""

import dataclasses
from typing import Any, cast

import pytest
from app.db.models import NOTICE_KINDS
from app.domain.messages import (
    ACTION_LABELS,
    APPROVAL_PENDING_KIND,
    MSG_KINDS,
    approval_pending_msg,
    approval_pending_text,
)
from app.domain.states import S_PENDING_APPROVAL
from app.graph.nodes import b15_prepare_approval
from app.notify.child import NOTICE_KIND_BY_STEP
from tests.fakes.ad_seed import seed_ad_records
from tests.fakes.graph import Crash
from tests.unit.test_b15_prepare_approval import NOW, Env, _crash_once, _x1

TAIL = "cần được duyệt theo quy định của công ty. Mình đã gửi phiếu duyệt; có kết quả mình báo bạn tại đây."
X1_TEXT = f"Yêu cầu gia hạn chứng chỉ VPN cho máy LAP-0501 {TAIL}"


class Block:
    def violation(self, text: str) -> str:
        return "canary"


def _user_msgs(env: Env, ticket: str = "t1") -> list[tuple[str, str, str]]:
    return [m for m in env.h.notifier.sent if m[0] == ticket]


# ---- mẫu (hàm thuần) ---------------------------------------------------------------------------------------------------------------


def test_text_template() -> None:
    assert approval_pending_text("renew_vpn_cert", "máy LAP-0501") == X1_TEXT
    assert approval_pending_text("reset_password", "tài khoản của bạn") == f"Yêu cầu đặt lại mật khẩu cho tài khoản của bạn {TAIL}"
    # không nhãn / không đích → câu chung, không bịa
    assert approval_pending_text("khong_co", "máy LAP-0501") == f"Yêu cầu của bạn {TAIL}"
    assert approval_pending_text("renew_vpn_cert", "") == f"Yêu cầu của bạn {TAIL}"


def test_every_action_has_label() -> None:
    for action in ACTION_LABELS:
        assert ACTION_LABELS[action] in approval_pending_text(action, "máy LAP-0501")


def test_msg_shape_needs_none() -> None:
    assert approval_pending_msg("x", "m1") == {"role": "assistant", "kind": APPROVAL_PENDING_KIND, "text": "x", "ref": "m1",
                                               "needs": "none"}  # fmt: skip
    assert APPROVAL_PENDING_KIND == "approval_pending"


def test_kind_declared_in_msg_kinds_not_notice_kinds() -> None:
    """ĐP 09/11 01:50: `approval_pending` là loại tin hội thoại khai báo; notice con vẫn `result` (CHECK `child_notices` — chờ migration)."""
    assert APPROVAL_PENDING_KIND in MSG_KINDS
    assert APPROVAL_PENDING_KIND not in NOTICE_KINDS and NOTICE_KIND_BY_STEP["B15"] == "result"


# ---- node ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio


async def test_queued_sends_one_user_message() -> None:
    env = Env()
    _, state = _x1()
    out = await env.run(state)
    assert out["status"] == S_PENDING_APPROVAL
    assert _user_msgs(env) == [("t1", X1_TEXT, "none")]
    assert env.h.effects.count("t1", "notify_user") == 1 and env.h.effects.count("t1", "notify_approver") == 1
    [msg] = out["conversation"]
    assert (msg["kind"], msg["text"], msg["needs"], msg["ref"]) == (APPROVAL_PENDING_KIND, X1_TEXT, "none", "m1")


@pytest.mark.asyncio


async def test_message_never_names_approver() -> None:
    env = Env()
    _, state = _x1()
    out = await env.run(state)
    a = await env.h.approvals.get(str(out["approval_id"]))
    assert a is not None
    [rec] = seed_ad_records(NOW, [a.approver_id])
    [(_, text, _)] = _user_msgs(env)
    for word in (a.approver_id, rec["username"], rec["full_name"]):
        assert word not in text


@pytest.mark.asyncio


async def test_rerun_same_turn_sends_nothing_more() -> None:
    """Chạy lại node CÙNG lượt (nhánh `peek`) → vẫn đúng 1 tin."""
    env = Env()
    _, state = _x1()
    await env.run(state)
    await env.run(state)
    assert _user_msgs(env) == [("t1", X1_TEXT, "none")]
    assert env.h.effects.count("t1", "notify_user") == 1


@pytest.mark.asyncio


async def test_tc33_crash_after_create_then_rerun_one_message() -> None:
    """TC33: chết sau `approval_create` (chưa báo ai) → chạy lại = nhánh phiếu cũ → đúng 1 tin người dùng."""
    env = Env()
    _, state = _x1()
    env.h.scenario.on("t1", "after_approval_create", _crash_once())
    with pytest.raises(Crash):
        await env.run(state)
    assert _user_msgs(env) == []
    out = await env.run(state)
    assert out["status"] == S_PENDING_APPROVAL
    assert _user_msgs(env) == [("t1", X1_TEXT, "none")]
    assert env.h.effects.count("t1", "notify_user") == 1


@pytest.mark.asyncio


async def test_output_guard_blocks_zero_messages_still_queued() -> None:
    """Guard chặn mẫu → 0 tin (như các nhánh cũ), phiếu vẫn chờ duyệt (đã tạo + đã báo người duyệt); audit ghi lý do chặn."""
    env = Env()
    _, state = _x1()
    fn = b15_prepare_approval.make(dataclasses.replace(env.h.deps(), output_guard=cast(Any, Block())))
    with env.bound(state):
        out: dict[str, Any] = await fn(state)
    assert out["status"] == S_PENDING_APPROVAL
    assert _user_msgs(env) == [] and env.h.effects.count("t1", "notify_user") == 0
    assert "conversation" not in out
    assert env.h.approvals.count("t1") == 1 and len(env.h.approvals.notified) == 1
    assert env.row("queued")["detail"]["user_notice_guard"] == "canary"


@pytest.mark.asyncio


async def test_child_ticket_message_becomes_notice() -> None:
    """Ticket CON: không nhắn thẳng người dùng — 1 notice (needs=none, source_step B15) của con cho cha gom; chạy lại không nhân đôi."""
    env = Env()
    env.h.tickets.register("P", NOW, is_parent=True)
    env.h.tickets.register("t1", NOW, parent_ticket_id="P")
    _, state = _x1()
    out = await env.run(state)
    await env.run(state)
    assert out["status"] == S_PENDING_APPROVAL
    assert _user_msgs(env) == []
    [n] = env.h.tickets.notices_of("t1")
    assert (n["parent_ticket_id"], n["source_step"], n["kind"], n["needs"], n["body"]) == (
        "P", "B15", NOTICE_KIND_BY_STEP["B15"], "none", X1_TEXT)
    assert out["conversation"][0]["ref"].startswith("notice:")
