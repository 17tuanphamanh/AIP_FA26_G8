"""T20a — node B6 / B11 THẬT cho account, software, access (phase5 5.1.1 P3, P4; 5.1.5; 5.1.6 n1–n5, p2–p4; PLAN-T20a TQ-2,
TQ-11, TQ-12, TQ-17). Viết TỪ ĐẶC TẢ, trước code — hiện thực ở DỪNG 2.

Mức node như `test_b06_diagnose.py` (RunContext + `bind_run` + `wrap_node` — lỗi chưa lường trước → E9 → assert đỏ, không lọt
exception lạ). Registry THẬT trên `tests/unit/_t20a.Env` (AD giả đọc seed + `SeedVpn` + `SeedTools`) truyền `GraphHarness(directory=…)`;
`enabled_intents` tiêm bằng `dataclasses.replace` (KHÔNG sửa `graph/fakes.py`). n3 dựng state tay ở B11 (TQ-11: `clarify_wait` chỉ
nhận slot đang thiếu — A12). n6 = test VPN cũ (`test_b06_diagnose.py`, `test_b11_slots.py`) — không viết mới, không sửa.
"""

import dataclasses
import json
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import pytest
from app.domain.facts import FACT_KEYS
from app.domain.states import (
    S_ASSESSING,
    S_CLARIFYING,
    S_DIAGNOSING,
    S_ESCALATED,
    S_RETRIEVING,
)
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b06_diagnose, b11_slots
from app.llm.providers.scripted import Reply
from app.settings import get_slots
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.unit._t20a import Env, rc

FOUR = frozenset({"vpn", "account", "software", "access"})
POINT2_KEYS = {"phase", "slots_inferred", "tools_called", "facts", "rediagnose"}  # điểm log 2 (như VPN — TQ-17)
QUESTION = "Bạn cần quyền này trong bao nhiêu ngày?"



class Nodes:
    """Node thật gọi trực tiếp trên harness; mỗi `run` = một "process" (`h.deps()` dựng mới), `enabled_intents` = 4 intent."""

    def __init__(self, env: Env | None = None, *, rag: FakeRag | None = None) -> None:
        self.env = env or Env()
        self.gw: Gateway = make_gateway({"b11_clarify_question": lambda _: Reply({"text": QUESTION})}, clock=self.env.clock)
        self.h = GraphHarness(clock=self.env.clock, directory=self.env.directory(), llm=self.gw.client,
                              rag=rag or FakeRag())  # fmt: skip
        self.audit = MemoryAudit()

    async def run(self, name: str, module: ModuleType, state: Mapping[str, Any], **over: Any) -> dict[str, Any]:
        deps = dataclasses.replace(self.h.deps(), enabled_intents=FOUR, **over)
        run = RunContext(turn_id="T1", trace_id="0" * 32, audit=self.audit, effects=MemoryEffects(), spans=MemorySpans(),
                         clock=self.env.clock, txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run):
            return dict(await wrap_node(name, module.make(deps))(dict(state)))

    async def b6(self, state: Mapping[str, Any], **over: Any) -> dict[str, Any]:
        return await self.run("b06_diagnose", b06_diagnose, state, **over)

    async def b11(self, state: Mapping[str, Any]) -> dict[str, Any]:
        return await self.run("b11_slots", b11_slots, state)


def b6_state(user: str, intent: str, slots: dict[str, str]) -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_DIAGNOSING, "intent": intent, "slots": dict(slots), "facts": {},
            "requester_context": rc(user), "reasoning_loops": 1}  # fmt: skip


def b11_state(user: str, intent: str, slots: dict[str, str], facts: dict[str, Any] | None = None,
              **over: Any) -> dict[str, Any]:  # fmt: skip
    base: dict[str, Any] = {"ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "intent": intent, "slots": dict(slots),
                            "facts": dict(facts or {}), "requester_context": rc(user), "redacted_request": "yêu cầu",
                            "clarification_turns": 0}  # fmt: skip
    base.update(over)
    return base


# Kỳ vọng fact — chép từ bảng 5.1.6 i1, s1/s4, c1 + seed.
I1 = {"target_account_privilege": "standard_user", "target_is_service_account": False, "target_user_status": "active",
      "target_account_locked": False}  # fmt: skip
S1 = {"in_catalog": True, "license_paid": False, "requires_local_admin": False, "device_registered": True,
      "device_owner_is_requester": True}  # fmt: skip
S4 = {**S1, "device_count": 1, "has_registered_device": True}
C1 = {"resource_sensitivity": "low", "same_department": True, "has_permission_record": True,
      "existing_permission_level": "read", "target_user_status": "active"}  # fmt: skip
Q3_NV001 = {"resource_sensitivity": "high", "same_department": True, "has_permission_record": True,
            "existing_permission_level": "read", "target_user_status": "active"}  # fmt: skip
EXTEND_PR = {"action": "extend_permission", "resource_path": "finance/public-reports", "duration": "30"}


# ---- n1: B6 ---------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "intent", "slots", "tools", "facts", "slots_after", "inferred"),
    [
        pytest.param("nv001", "account", {"account_type": "ad", "action": "reset_password"},
                     ["check_account_status", "check_lockout_history", "check_privilege_level"], I1,
                     {"account_type": "ad", "action": "reset_password"}, [], id="n1-account-i1"),
        pytest.param("nv001", "software", {"software_name": "Zoom", "action": "install_software"},
                     ["check_catalog_entry", "check_license_available", "check_device_registered"], S4,
                     {"software_name": "Zoom", "action": "install_software", "device_id": "LAP-0342"}, ["device_id"],
                     id="n1-software-s4-suy-may"),
        pytest.param("nv001", "access", EXTEND_PR,
                     ["check_current_permissions", "check_resource_sensitivity", "check_manager_chain",
                      "check_account_status"], C1, EXTEND_PR, [], id="n1-access-c1"),
    ],
)  # fmt: skip
async def test_n1_b6_three_intents_seed(
    user: str, intent: str, slots: dict[str, str], tools: list[str], facts: dict[str, Any], slots_after: dict[str, str],
    inferred: list[str],
) -> None:  # fmt: skip
    """n1: B6 qua `DIAGNOSERS` — đúng bộ tool theo slot đã có (đếm ở NƠI NHẬN), `facts` như i/s/c, slot suy ra bổ sung (không đè),
    `S_RETRIEVING` → b08; điểm log 2 giữ khoá, `phase="lookup"` khi chưa có `device_id`; `ctx_flags.target_is_other=False`."""
    n = Nodes()
    update = await n.b6(b6_state(user, intent, slots))
    assert (update.get("status"), update.get("next")) == (S_RETRIEVING, "b08_retrieve"), n.audit.rows
    assert update["facts"] == facts and set(update["facts"]) <= FACT_KEYS
    assert update["slots"] == slots_after
    assert update["ctx_flags"] == {"target_is_other": False}
    received = {**dict(n.env.tools.calls), **{k: v for k, v in n.env.vpn.calls.items() if v}}
    assert received == dict.fromkeys(tools, 1)
    json.dumps(update["diagnostics"])  # JSON thuần trong state (không model Pydantic)
    [row] = n.audit.rows
    d = row["detail"]
    assert (row["step"], row["event"]) == ("B6", "diagnosed") and POINT2_KEYS <= set(d)
    assert (d["phase"], d["tools_called"], d["slots_inferred"], d["facts"]) == ("lookup", tools, inferred, facts)


@pytest.mark.asyncio
async def test_n1_b6_software_named_device_phase_device() -> None:
    """n1 + TQ-17: software có `device_id` → đủ 4 tool, fact như s1, `phase="device"`."""
    n = Nodes()
    slots = {"software_name": "Zoom", "device_id": "LAP-0342", "action": "install_software"}
    update = await n.b6(b6_state("nv001", "software", slots))
    assert update["status"] == S_RETRIEVING and update["facts"] == S1 and update["slots"] == slots
    [row] = n.audit.rows
    assert row["detail"]["phase"] == "device"
    assert row["detail"]["tools_called"] == ["check_catalog_entry", "check_license_available", "check_installed_list",
                                             "check_device_registered"]  # fmt: skip


# ---- n2: B6 lỗi hệ thống ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "slots", "tool"),
    [
        pytest.param("access", EXTEND_PR, "check_resource_sensitivity", id="n2-access-sensitivity-500"),
        pytest.param("account", {"account_type": "ad"}, "check_privilege_level", id="n2-account-privilege-500"),
        pytest.param("software", {"software_name": "Zoom"}, "check_catalog_entry", id="n2-software-catalog-500"),
    ],
)
async def test_n2_b6_tool_500_e2(intent: str, slots: dict[str, str], tool: str) -> None:
    """n2 (5.1.2 "Lỗi hệ thống"): một tool 500 (sau retry) → E2 `tool_system_error` (B7); `tool_errors` không URL / user_id; không
    kết luận fact từ dữ liệu thiếu."""
    env = Env()
    env.tools.fail(tool, 500)
    n = Nodes(env)
    update = await n.b6(b6_state("nv001", intent, slots))
    assert (update.get("status"), update.get("exit_code"), update.get("escalation_reason_detail")) == (
        S_ESCALATED, "E2", "tool_system_error")
    assert update["tool_errors"] == [f"{tool}: HTTPStatusError"]
    assert update["tool_retry_count"] == 2 and env.tools.calls[tool] == 3
    assert "facts" not in update
    [row] = n.audit.rows
    assert (row["step"], row["event"]) == ("B7", "tool_system_error")
    assert "nv001" not in repr(row["detail"]) and "/files/" not in repr(row["detail"]) and "/ad/" not in repr(row["detail"])


# ---- n3: B11 tính lại TOÀN BỘ fact theo slot cuối ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n3_b11_access_recomputes_all_facts_for_final_path() -> None:
    """n3 (TQ-11, M-T20a-12): B6 chạy với `finance/public-reports` (facts C1), slot cuối là `finance/Q3` → B11 gọi lại tool theo
    `finance/Q3` và THAY toàn bộ fact (không giữ `resource_sensitivity=low` của B6)."""
    n = Nodes()
    state = b11_state("nv001", "access", {"action": "extend_permission", "resource_path": "finance/Q3", "duration": "30"},
                      facts=C1)  # fmt: skip
    out = await n.b11(state)
    assert (out.get("status"), out.get("next")) == (S_ASSESSING, "b12_assess"), n.audit.rows
    action = out["intended_action"]
    assert (action.type, action.target, action.requested_for) == ("extend_permission", "folder:finance/Q3", "nv001")
    assert action.params == {"resource_path": "finance/Q3", "duration_days": 30}
    assert action.facts == out["facts"] == Q3_NV001
    assert {a["resource_path"] for t, a in n.env.tools.seen if t == "check_resource_sensitivity"} == {"finance/Q3"}
    assert out.get("slots", state["slots"]) == state["slots"]  # slot suy ra ở B11 bị bỏ — slot người dùng không đổi


@pytest.mark.asyncio
async def test_n3_b11_drops_stale_folder_facts_on_unknown_path() -> None:
    """n3 (biến thể): slot cuối là thư mục lạ (404) → fact theo thư mục của B6 KHÔNG còn (thay toàn bộ, không gộp)."""
    n = Nodes()
    state = b11_state("nv001", "access", {"action": "extend_permission", "resource_path": "finance/khong-co",
                                          "duration": "30"}, facts=C1)  # fmt: skip
    out = await n.b11(state)
    assert out["status"] == S_ASSESSING, n.audit.rows
    assert out["facts"] == {"has_permission_record": False, "target_user_status": "active"}
    assert out["intended_action"].facts == out["facts"]


# ---- n4: B6 suy máy → B11 dựng đích máy ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n4_b6_infers_device_b11_builds_device_target() -> None:
    """n4: software, nv001 không nêu máy → B6 suy `device_id=LAP-0342` → B11 dựng `target="device:LAP-0342"`; fact B11 tính lại
    theo máy (không còn `device_count`)."""
    n = Nodes()
    st = b6_state("nv001", "software", {"software_name": "Zoom", "action": "install_software"})
    u6 = await n.b6(st)
    assert u6["status"] == S_RETRIEVING and u6["slots"]["device_id"] == "LAP-0342", n.audit.rows
    st = {**st, **u6, "redacted_request": "cài Zoom giúp em", "clarification_turns": 0}
    out = await n.b11(st)
    assert out["status"] == S_ASSESSING, n.audit.rows
    action = out["intended_action"]
    assert (action.type, action.target, action.requested_for) == ("install_software", "device:LAP-0342", "nv001")
    assert action.params == {"device_id": "LAP-0342", "software_name": "zoom"}
    assert action.facts == S1


# ---- n5: B11 lỗi tool / thiếu quy trình -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n5_b11_tool_error_e2_target_check_error() -> None:
    """n5: lỗi hệ thống ở tool của B11 → E2 `target_check_error`, không dựng Action."""
    env = Env()
    env.tools.fail("check_current_permissions", 500)
    n = Nodes(env)
    out = await n.b11(b11_state("nv001", "access", EXTEND_PR, facts=C1))
    assert (out.get("status"), out.get("exit_code"), out.get("escalation_reason_detail")) == (
        S_ESCALATED, "E2", "target_check_error")
    assert out["tool_errors"] == ["check_current_permissions: HTTPStatusError"]
    assert "intended_action" not in out


@pytest.mark.asyncio
async def test_n5_b11_missing_procedure_doc_e3_no_procedure() -> None:
    """n5 (S0-P10 như cũ): KB giả không có `KB-ACC-001` (procedure_doc của reset_password, bảng 4.2) → E3 `no_procedure`, kèm
    `intended_action` (L2 thấy hành động dự kiến)."""
    n = Nodes(rag=FakeRag(procedures={"KB-VPN-004", "KB-VPN-001"}))
    out = await n.b11(b11_state("nv001", "account", {"account_type": "ad", "action": "reset_password"}, facts=I1))
    assert (out.get("status"), out.get("exit_code"), out.get("escalation_reason_detail")) == (
        S_ESCALATED, "E3", "no_procedure")
    assert out["intended_action"].type == "reset_password"
    [row] = [r for r in n.audit.rows if r["event"] == "no_procedure"]
    assert (row["step"], row["detail"]["procedure_doc"]) == ("B11", "KB-ACC-001")


# ---- p2–p4: slot theo hành động (P4) ------------------------------------------------------------------------------------------


def _access_by_action_config() -> None:
    """Tiền đề P4 (DỪNG 1): access `required: [action]` + `required_by_action` — nếu chưa có thì "missing" của B11 cũ trùng hợp
    đúng nhờ `required` cũ, không chứng minh được P4."""
    acc = get_slots().intents["access"]
    assert acc.required == ("action",) and "grant_permission" in acc.required_by_action


@pytest.mark.asyncio
async def test_p2_b11_grant_missing_duration_asks_duration() -> None:
    """p2 (P4, M-T20a-11): access `action=grant_permission`, thiếu `duration` → hỏi `duration`."""
    _access_by_action_config()
    n = Nodes()
    out = await n.b11(b11_state("nv001", "access", {"action": "grant_permission", "resource_path": "finance/public-reports",
                                                    "permission_level": "read"}))  # fmt: skip
    assert (out.get("status"), out.get("missing_slots")) == (S_CLARIFYING, ["duration"]), n.audit.rows
    [call] = n.gw.llm.calls_for("b11_clarify_question")
    assert call.variables["missing"] == ["duration"]


@pytest.mark.asyncio
async def test_p2_b11_grant_missing_duration_last_turn_e4() -> None:
    """p2: đã hỏi đủ `MAX_CLARIFICATION_TURNS` lượt mà vẫn thiếu `duration` → E4 `clarification_exhausted`."""
    _access_by_action_config()
    n = Nodes()
    turns = n.h.deps().constants.MAX_CLARIFICATION_TURNS
    out = await n.b11(b11_state("nv001", "access", {"action": "grant_permission", "resource_path": "finance/public-reports",
                                                    "permission_level": "read"}, clarification_turns=turns))  # fmt: skip
    assert (out.get("status"), out.get("exit_code"), out.get("escalation_reason_detail")) == (
        S_ESCALATED, "E4", "clarification_exhausted")
    assert out.get("missing_slots") == ["duration"]


@pytest.mark.asyncio
async def test_p2_b11_grant_only_action_asks_in_declared_order() -> None:
    """P4: `missing` = required thiếu + `required_by_action[action]` thiếu, THEO THỨ TỰ KHAI BÁO."""
    _access_by_action_config()
    n = Nodes()
    out = await n.b11(b11_state("nv001", "access", {"action": "grant_permission"}))
    assert out.get("missing_slots") == ["resource_path", "permission_level", "duration"], n.audit.rows


@pytest.mark.asyncio
async def test_p3_b11_view_permissions_no_question_builds_action() -> None:
    """p3: access `view_permissions` không slot khác → không hỏi — dựng `Action` (`target=user:nv001`, `params={}`)."""
    _access_by_action_config()
    n = Nodes()
    out = await n.b11(b11_state("nv001", "access", {"action": "view_permissions"}))
    assert out["status"] == S_ASSESSING, n.audit.rows
    assert n.gw.llm.calls_for("b11_clarify_question") == []
    action = out["intended_action"]
    assert (action.type, action.target, action.params) == ("view_permissions", "user:nv001", {})
    assert action.facts == {"target_user_status": "active"}


@pytest.mark.asyncio
async def test_p4_b11_access_without_action_asks_action() -> None:
    """p4: access chưa có `action` → hỏi `action` (chưa xét `required_by_action`)."""
    _access_by_action_config()
    n = Nodes()
    out = await n.b11(b11_state("nv001", "access", {"resource_path": "finance/Q3"}))
    assert (out.get("status"), out.get("missing_slots")) == (S_CLARIFYING, ["action"]), n.audit.rows


# ---- Thêm khi duyệt DỪNG 1 (agent chính viết — lệnh duyệt 13/10, không qua test-writer) ----------------------------------------------


@pytest.mark.asyncio
async def test_n3_account_b6_ad_lookup_b11_recomputes_for_email() -> None:
    """NGHI d (security-reviewer DỪNG 1): B6 tra theo `ad` khi chưa có `account_type` (TQ-8) → fact AD của nv007 (không khoá);
    người dùng trả lời `account_type=email` → B11 tra lại theo `email` và THAY toàn bộ fact (khoá `bad_password`) — không để fact AD
    áp cho thao tác email."""
    n = Nodes()
    st = b6_state("nv007", "account", {"action": "unlock_account"})
    u6 = await n.b6(st)
    assert u6["status"] == S_RETRIEVING, n.audit.rows
    assert u6["facts"]["target_account_locked"] is False  # gợi ý của B6 theo ad
    st = {**st, **u6, "slots": {**u6["slots"], "account_type": "email"}, "redacted_request": "mở khoá email",
          "clarification_turns": 1}  # fmt: skip
    out = await n.b11(st)
    assert out["status"] == S_ASSESSING, n.audit.rows
    assert out["facts"] == {"target_user_status": "active", "target_is_service_account": False,
                            "target_account_locked": True, "target_lock_reason": "bad_password",
                            "target_account_privilege": "standard_user"}  # fmt: skip
    assert out["intended_action"].facts == out["facts"]
    assert out["intended_action"].params == {"account_type": "email"}
    b11_lookups = [a.get("account_type") for t, a in n.env.tools.seen if t == "check_account_status"]
    assert b11_lookups == ["ad", "email"]  # B6 theo ad, B11 theo email


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "slots", "over"),
    [
        pytest.param("vpn", {"device_id": "LAP-0342"}, {}, id="n7-vpn"),
        pytest.param("account", {"account_type": "ad", "action": "reset_password"}, {}, id="n7-account"),
        pytest.param("access", EXTEND_PR, {}, id="n7-access"),
        pytest.param("software", {"software_name": "Zoom"}, {}, id="n7-software"),
        pytest.param("account", {"account_type": "ad"}, {"enable_proactive_diagnosis": False}, id="n7-ablation"),
    ],
)
async def test_n7_b6_keeps_target_is_other_from_b3(intent: str, slots: dict[str, str], over: dict[str, Any]) -> None:
    """n7 (Q-T20a-4 điểm 2, M-T20a-15): B3 đã đặt `ctx_flags.target_is_other=True` → B6 GIỮ True ở nhánh VPN, nhánh `DIAGNOSERS` và
    nhánh ablation; không có cờ → False như cũ (n1)."""
    n = Nodes()
    st = {**b6_state("nv001", intent, slots), "ctx_flags": {"target_is_other": True}}
    update = await n.b6(st, **over)
    assert update.get("status") == S_RETRIEVING, n.audit.rows
    assert update["ctx_flags"] == {"target_is_other": True}
    plain = await Nodes().b6(b6_state("nv001", intent, slots), **over)
    assert plain["ctx_flags"] == {"target_is_other": False}
