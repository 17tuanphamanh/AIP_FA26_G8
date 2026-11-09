"""Q3 M3 (ĐP 09/11): không hỏi điều hệ thống đã biết — B6 suy slot `account_type = "ad"` khi AD của CHÍNH người gửi đang khoá.

Điều kiện (đủ cả): intent `account`; `action` là `unlock_account` hoặc chưa có; `account_type` THIẾU; đích = người gửi (không `target_user`,
cờ `ctx_flags.target_is_other` không bật); fact B6 (tra mặc định `ad` — TQ-8) `target_account_locked is True`. Như VPN suy máy duy nhất ở B6:
slot suy ra chỉ bổ sung, audit `slots_inferred`. Ca khác → không suy → B11 hỏi câu cố định (M1). Policy/M5 không đổi (slot không phải fact).

Seed: `hr_head` AD đang khoá (inactivity); `nv007` AD KHÔNG khoá (email khoá); `nv001` không khoá gì.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from app.domain.states import S_ASSESSING, S_CLARIFYING, S_RETRIEVING
from app.settings import get_slots
from app.tools.diagnosis import account
from app.tools.models import AccountStatus
from tests.unit.test_nodes_t20a import Nodes, b6_state, b11_state

PID = "b11_clarify_question"
ACCOUNT_TYPE_Q = get_slots().intents["account"].fixed_questions["account_type"]
ACTION_Q = get_slots().intents["account"].fixed_questions["action"]


async def _b6(n: Nodes, user: str, slots: dict[str, str], **over: Any) -> dict[str, Any]:
    state = b6_state(user, "account", slots)
    state.update(over)
    out = await n.b6(state)
    assert out.get("status") == S_RETRIEVING, n.audit.rows
    return out


def _inferred(n: Nodes) -> list[str]:
    [row] = [r for r in n.audit.rows if r["event"] == "diagnosed"]
    return list(row["detail"]["slots_inferred"])


# ---- B6 ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("slots", [{"action": "unlock_account"}, {}], ids=["unlock", "chua-co-action"])
async def test_own_ad_locked_infers_ad(slots: dict[str, str]) -> None:
    n = Nodes()
    out = await _b6(n, "hr_head", slots)
    assert out["slots"] == {**slots, "account_type": "ad"}
    assert out["facts"]["target_account_locked"] is True
    assert _inferred(n) == ["account_type"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "slots", "over"),
    [
        pytest.param("nv001", {"action": "unlock_account", "target_user": "hr_head"}, {}, id="co-target_user-AD-nguoi-khac-khoa"),
        pytest.param("hr_head", {"action": "unlock_account"}, {"ctx_flags": {"target_is_other": True}}, id="co-target_is_other"),
        pytest.param("hr_head", {"action": "reset_password"}, {}, id="dat-lai-mat-khau"),
        pytest.param("nv007", {"action": "unlock_account"}, {}, id="AD-khong-khoa"),
        pytest.param("hr_head", {"action": "unlock_account", "account_type": "email"}, {}, id="da-co-account_type"),
    ],
)  # fmt: skip
async def test_no_inference(user: str, slots: dict[str, str], over: dict[str, Any]) -> None:
    n = Nodes()
    out = await _b6(n, user, slots, **over)
    assert out["slots"] == slots
    assert _inferred(n) == []


def _status(locked: bool) -> AccountStatus:
    """Chỉ các trường `infer_account` đọc (model_construct — không cần đủ hồ sơ AD)."""
    acc = SimpleNamespace(locked=locked, lock_reason="bad_password" if locked else None)
    return AccountStatus.model_construct(employment_status="active", is_service_account=False, disable_reason=None, account=acc)


def _diag(locked: bool) -> dict[str, Any]:
    return {"check_account_status": _status(locked), "check_lockout_history": None, "check_privilege_level": None}


@pytest.mark.parametrize(
    ("slots", "allow", "locked", "expected"),
    [
        ({}, True, True, {"account_type": "ad"}),
        ({"action": "unlock_account"}, True, True, {"account_type": "ad"}),
        ({"action": "unlock_account"}, False, True, {}),
        ({"action": "unlock_account"}, True, False, {}),
        ({"action": "reset_password"}, True, True, {}),
        ({"action": "unlock_account", "target_user": "x01"}, True, True, {}),
        ({"action": "unlock_account", "account_type": "erp"}, True, True, {}),
    ],
)  # fmt: skip
def test_infer_account_pure(slots: dict[str, str], allow: bool, locked: bool, expected: dict[str, str]) -> None:
    inferred, facts = account.infer_account(_diag(locked), requester_id="x01", slots=slots, allow_infer=allow)
    assert inferred == expected
    assert facts["target_account_locked"] is locked  # fact không đổi vì có/không suy


def test_infer_account_unknown_status_no_inference() -> None:
    """404 (không có dòng trạng thái) → không fact khoá → không suy."""
    diag = {"check_account_status": None, "check_lockout_history": None, "check_privilege_level": None}
    assert account.infer_account(diag, requester_id="x01", slots={}) == ({}, {})


# ---- B6 → B11: 0 câu hỏi ------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locked_ad_then_b11_builds_unlock_without_question() -> None:
    n = Nodes()
    b6 = await _b6(n, "hr_head", {"action": "unlock_account"})
    out = await n.b11(b11_state("hr_head", "account", b6["slots"], facts=b6["facts"]))
    assert out.get("status") == S_ASSESSING, n.audit.rows
    action = out["intended_action"]
    assert (action.type, action.target, action.params["account_type"]) == ("unlock_account", "user:hr_head", "ad")
    assert action.facts["target_account_locked"] is True
    assert n.h.notifier.sent == [] and n.gw.llm.calls_for(PID) == []


@pytest.mark.asyncio
async def test_locked_ad_no_action_asks_only_action() -> None:
    n = Nodes()
    b6 = await _b6(n, "hr_head", {})
    out = await n.b11(b11_state("hr_head", "account", b6["slots"], facts=b6["facts"]))
    assert (out.get("status"), out.get("missing_slots")) == (S_CLARIFYING, ["action"])
    assert n.h.notifier.sent == [("t1", ACTION_Q, "answer")]


@pytest.mark.asyncio
async def test_target_user_then_b11_still_asks_account_type() -> None:
    """Có `target_user` (AD người đó đang khoá) → không suy → B11 hỏi câu cố định `account_type`."""
    n = Nodes()
    b6 = await _b6(n, "nv001", {"action": "unlock_account", "target_user": "hr_head"})
    out = await n.b11(b11_state("nv001", "account", b6["slots"], facts=b6["facts"]))
    assert (out.get("status"), out.get("missing_slots")) == (S_CLARIFYING, ["account_type"])
    assert n.h.notifier.sent == [("t1", ACCOUNT_TYPE_Q, "answer")]
