"""Q5 (ĐP 09/11) — phần mềm bị cấm: từ chối ngay theo quy định, không gửi chờ duyệt. Viết TRƯỚC code (DỪNG 1).

Bằng chứng (demo): "Cài giúp mình uTorrent", "Cài Windows crack lên máy em" → `in_catalog=False` → R13 `approval_required` → gửi L1
chờ duyệt; người duyệt sẽ từ chối, nhưng đúng ra hệ thống phải từ chối ngay.

Hợp đồng kiểm ở đây:
- Danh sách cấm do HỆ THỐNG NGOÀI giữ (mock `seed.json`) — `GET /software/catalog/{tên}` trả thêm `prohibited: bool`. Fact
  `software_prohibited` (bool) CHỈ từ đầu ra tool (`infer_software`), không bao giờ từ slot (G-01; test AST `test_facts_ast.py`).
- Luật R21 `deny` (software / install_software / `action.facts.software_prohibited is_true`) — chặt nhất thắng nên R13 khớp kèm vẫn
  thua: E5 `policy_deny`, KHÔNG qua B15 (0 phiếu duyệt); người dùng nhận câu E5 `policy_deny` của Q3 M5 (nguyên văn).
- B14 (đã đo RQ1) KHÔNG thấy fact này (ĐP 09/11 10:05): đầu vào `b14_risk_estimate`/`b14_risk_vote` giữ như bản đo.
- Phần mềm trong danh mục (7-Zip, Zoom, Adobe Acrobat Pro) → như cũ; tên lạ không cấm (Photoshop) → R13 như cũ; tool lỗi → E2 như
  lỗi tool hiện nay (không coi là "không cấm").
"""

import ast
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from app.domain.facts import FACT_KEYS, FACT_TYPES, FactKeyViolation, check_facts
from app.domain.states import (
    S_ASSESSING,
    S_CLASSIFYING,
    S_DIAGNOSING,
    S_ESCALATED,
    S_EXECUTING,
    S_RETRIEVING,
)
from app.domain.ticket_state import RiskDecision
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b03_classify, b06_diagnose, b11_slots, b12_assess, b20_audit
from app.llm.providers.scripted import Reply
from app.risk.estimator import (
    B14_EXCLUDED_FACTS,
    LlmRiskEstimator,
    PMethod,
    estimator_vars,
)
from app.risk.models import RiskContext
from app.risk.policy_engine import evaluate_rules
from app.settings import action_intents, get_policy
from app.tools.diagnosis import software
from app.tools.models import CatalogEntry
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.unit._t20a import NOW, Env, rc
from tests.unit._t24 import action as t24_action
from tests.unit.test_facts_ast import check_infer
from tests.unit.test_q5_catalog_prohibited import IN_CATALOG, PROHIBITED

REPO = Path(__file__).resolve().parents[3]
DIAG_SOFTWARE = REPO / "backend" / "app" / "tools" / "diagnosis" / "software.py"
FOUR = frozenset({"vpn", "account", "software", "access"})
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}

# Câu E5 `policy_deny` ĐP soạn (Q3 M5, config/escalation_templates.yaml) — chép NGUYÊN VĂN, không đọc từ file mẫu.
POLICY_DENY_TEXT = ("Theo quy định của công ty, việc này không được thực hiện tự động. Mình đã chuyển kỹ thuật viên xem xét; bạn sẽ "
                    "nhận phản hồi tại đây.")  # fmt: skip
R21 = {
    "id": "R21", "type": "deny", "intent": "software", "action": "install_software",
    "conditions": {"all": [{"fact": "action.facts.software_prohibited", "op": "is_true"}]},
    "description": "Phần mềm bị cấm theo quy định của công ty",
}  # fmt: skip


# ---- fact ------------------------------------------------------------------------------------------------------------------


def test_fact_software_prohibited_is_bool_in_closed_list() -> None:
    assert "software_prohibited" in FACT_KEYS and FACT_TYPES["software_prohibited"] is bool
    check_facts({"software_prohibited": True, "in_catalog": False})
    for bad in ("true", 1, None):
        with pytest.raises(FactKeyViolation):
            check_facts({"software_prohibited": bad})


# ---- infer_software: fact từ đầu ra tool ----------------------------------------------------------------------------------


def _diag(entry: object) -> dict[str, Any]:
    return {t: None for t in software.TOOLS} | {"check_catalog_entry": entry}


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        pytest.param(PROHIBITED, {"in_catalog": False, "software_prohibited": True}, id="cam-ngoai-danh-muc"),
        pytest.param(None, {"in_catalog": False, "software_prohibited": False}, id="404-ngoai-danh-muc-khong-cam"),
        pytest.param(IN_CATALOG,
                     {"in_catalog": True, "software_prohibited": False, "license_paid": False, "requires_local_admin": False},
                     id="trong-danh-muc"),
    ],
)  # fmt: skip
def test_infer_software_prohibited_from_tool_output(entry: dict[str, Any] | None, expected: dict[str, bool]) -> None:
    data = None if entry is None else CatalogEntry.model_validate(entry)  # 404 → None (TQ-2)
    _, facts = software.infer_software(_diag(data), requester_id="nv001", slots={"software_name": "x"})
    soft = {k: v for k, v in facts.items() if k in {"in_catalog", "software_prohibited", "license_paid", "requires_local_admin"}}
    assert soft == expected
    check_facts(facts)


def test_infer_software_no_name_no_prohibited_fact() -> None:
    """Chưa có tên → không gọi catalog → không đặt `software_prohibited` (như `in_catalog`, s7)."""
    _, facts = software.infer_software(_diag(None), requester_id="nv001", slots={})
    assert "software_prohibited" not in facts and "in_catalog" not in facts


def test_ast_catches_prohibited_from_slot() -> None:
    """Đột biến "fact lấy từ slot": chèn vào `infer_software` THẬT một phép gán `software_prohibited` từ slot → bộ kiểm AST bắt được."""
    src = DIAG_SOFTWARE.read_text(encoding="utf-8")
    assert check_infer(src, "infer_software") == []
    anchor = "    assert set(facts) <= FACT_KEYS"
    assert src.count(anchor) == 1
    mutated = src.replace(anchor, "    facts['software_prohibited'] = 'crack' in slots['software_name'].lower()\n" + anchor)
    ast.parse(mutated)
    assert check_infer(mutated, "infer_software")


# ---- luật R21 -------------------------------------------------------------------------------------------------------------------


def _raw_rules() -> list[dict[str, Any]]:
    return list(json.loads((REPO / "config" / "policy.json").read_text(encoding="utf-8"))["rules"])


def test_r21_exact_and_last() -> None:
    rules = _raw_rules()
    assert rules[-1] == R21
    assert [r["id"] for r in rules] == [f"R{n:02d}" for n in range(1, 22)]
    assert {r["id"] for r in rules if r["type"] == "deny"} == {"R12", "R21"}


def _verdict(facts: dict[str, Any], *, target_is_other: bool = False) -> Any:
    action = t24_action("install_software", facts=facts)
    ctx = RiskContext(requester=rc("nv001"), facts=dict(action.facts), now=NOW, within_business_hours=True,
                      target_is_other=target_is_other)  # fmt: skip
    return evaluate_rules(get_policy().rules, action, ctx, intents=action_intents())


@pytest.mark.parametrize(
    ("facts", "decision", "rule", "matched"),
    [
        pytest.param({"in_catalog": False, "software_prohibited": True}, "deny", "R21", ["R13", "R21"], id="cam-thang-R13"),
        pytest.param({"in_catalog": False, "software_prohibited": False}, "approval_required", "R13", ["R13"], id="la-khong-cam-R13"),
        pytest.param({"in_catalog": False}, "approval_required", "R13", ["R13"], id="thieu-fact-cam-khong-khop-R21"),
        pytest.param({"in_catalog": True, "software_prohibited": False, "license_paid": False, "requires_local_admin": False},
                     "allow", "R11", ["R11"], id="mien-phi-R11"),
    ],
)  # fmt: skip
def test_r21_deny_beats_approval(facts: dict[str, Any], decision: str, rule: str, matched: list[str]) -> None:
    v = _verdict(facts)
    assert (v.decision, v.rule_id, v.all_matched) == (decision, rule, matched)


def test_r21_deny_even_for_other_target() -> None:
    v = _verdict({"in_catalog": False, "software_prohibited": True}, target_is_other=True)
    assert (v.decision, v.rule_id) == ("deny", "R21")


# ---- chuỗi node B3 → B6 → B11 → B12 (→ B20) trên seed.json ------------------------------------------------------------------


async def _chain(user: str, text: str, slots: dict[str, str], *, env: Env | None = None,
                 until_b20: bool = False) -> tuple[dict[str, Any], MemoryAudit, GraphHarness]:  # fmt: skip
    """Như `test_chain_t20a.chain` (intent software, hint install_software); dừng ở bước đầu tiên ra `S_ESCALATED`."""
    env = env or Env()
    item = {"type": "software", "confidence": 0.93, "span": text, "action_hint": "install_software", "slots": dict(slots)}
    gw = make_gateway({"b02_injection_judge": lambda _: Reply(NOT_ATTACK),
                       "b03_classify": lambda _: Reply({"intents": [item], "is_multi": False})}, clock=env.clock)  # fmt: skip
    h = GraphHarness(clock=env.clock, directory=env.directory(), llm=gw.client, rag=FakeRag())
    h.tickets.register("t1", env.clock.now(), requester_id=user)  # B20 đọc dòng ticket (như runner đã tạo)
    audit = MemoryAudit()
    state: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_CLASSIFYING, "redacted_request": text, "reasoning_loops": 0,
        "conversation": [], "requester_context": rc(user), "clarification_turns": 0,
    }  # fmt: skip
    steps: list[tuple[str, Any, str | None]] = [
        ("b03_classify", b03_classify, S_DIAGNOSING), ("b06_diagnose", b06_diagnose, S_RETRIEVING),
        ("b11_slots", b11_slots, S_ASSESSING), ("b12_assess", b12_assess, None),
    ]  # fmt: skip
    for name, module, expect in steps:
        deps = dataclasses.replace(h.deps(), enabled_intents=FOUR)
        run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                         clock=env.clock, txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run):
            update = await wrap_node(name, module.make(deps))(dict(state))
        state = {**state, **update}
        if state.get("status") == S_ESCALATED:
            break
        if expect is not None:
            assert state["status"] == expect, (name, state.get("exit_code"), state.get("escalation_reason_detail"))
    if until_b20:
        assert state.get("next") == "b20_audit", state.get("next")
        deps = dataclasses.replace(h.deps(), enabled_intents=FOUR)
        run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                         clock=env.clock, txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run):
            update = await wrap_node("b20_audit", b20_audit.make(deps))(dict(state))
        state = {**state, **update}
    return state, audit, h


def _risk(state: dict[str, Any]) -> RiskDecision:
    assert state.get("risk") is not None, (state.get("exit_code"), state.get("escalation_reason_detail"))
    return RiskDecision.model_validate(state["risk"])


def _all_matched(audit: MemoryAudit) -> list[str]:
    rows = [r for r in audit.rows if r["step"] == "B13/B14"]
    assert len(rows) == 1, [(r["step"], r["event"]) for r in audit.rows]
    return list(rows[0]["detail"]["all_matched"])


DENY_CASES = [
    pytest.param("Cài giúp mình uTorrent", "uTorrent", id="uTorrent-danh-sach"),
    pytest.param("Cài Windows crack lên máy em", "Windows crack", id="Windows-crack-tu-khoa"),
    pytest.param("Cài keygen office giúp em", "keygen office", id="keygen-office-tu-khoa"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "name"), DENY_CASES)
async def test_prohibited_denied_e5_no_approval(text: str, name: str) -> None:
    """Cấm → R21 deny (R13 khớp kèm nhưng thua) → E5 `policy_deny` → B20; KHÔNG qua B15 (0 phiếu duyệt); 1 tin = câu E5 policy_deny."""
    state, audit, h = await _chain("nv001", text, {"software_name": name}, until_b20=True)
    facts = state["intended_action"].facts
    assert (facts["in_catalog"], facts["software_prohibited"]) == (False, True)
    risk = _risk(state)
    assert (risk.policy_decision, risk.matched_rule_id) == ("deny", "R21")
    assert _all_matched(audit) == ["R13", "R21"]
    assert (state["exit_code"], state["escalation_reason_detail"]) == ("E5", "policy_deny")
    assert not any(r["step"].startswith("B15") for r in audit.rows), [(r["step"], r["event"]) for r in audit.rows]
    assert h.approvals.count("t1") == 0
    assert h.notifier.sent == [("t1", POLICY_DENY_TEXT, "none")]


@pytest.mark.asyncio
async def test_b20_control_r12_deny_sends_policy_deny_text() -> None:
    """Đối chứng cho bộ chạy chuỗi `_chain(until_b20)`: luật deny CŨ (R12, g8 của T20a) ra đúng câu E5 policy_deny — xanh trước khi
    có R21, để chắc ca cấm đỏ vì thiếu R21 chứ không vì bộ chạy."""
    env = Env()
    gw_item = {"type": "access", "confidence": 0.93, "span": "", "action_hint": "grant_permission",
               "slots": {"resource_path": "engineering/specs", "permission_level": "read", "duration": "30",
                         "target_user": "nv004"}}  # fmt: skip
    text = "Cấp quyền đọc thư mục engineering/specs trong 30 ngày cho nv004"
    gw = make_gateway({"b02_injection_judge": lambda _: Reply(NOT_ATTACK),
                       "b03_classify": lambda _: Reply({"intents": [{**gw_item, "span": text}], "is_multi": False})},
                      clock=env.clock)  # fmt: skip
    h = GraphHarness(clock=env.clock, directory=env.directory(), llm=gw.client, rag=FakeRag())
    h.tickets.register("t1", env.clock.now(), requester_id="nv001")
    audit = MemoryAudit()
    state: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_CLASSIFYING, "redacted_request": text, "reasoning_loops": 0,
        "conversation": [], "requester_context": rc("nv001"), "clarification_turns": 0,
    }  # fmt: skip
    for name, module in (("b03_classify", b03_classify), ("b06_diagnose", b06_diagnose), ("b11_slots", b11_slots),
                         ("b12_assess", b12_assess), ("b20_audit", b20_audit)):  # fmt: skip
        deps = dataclasses.replace(h.deps(), enabled_intents=FOUR)
        run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                         clock=env.clock, txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run):
            state = {**state, **await wrap_node(name, module.make(deps))(dict(state))}
    assert (state["exit_code"], state["escalation_reason_detail"]) == ("E5", "policy_deny")
    assert h.notifier.sent == [("t1", POLICY_DENY_TEXT, "none")]


ASIS_CASES = [
    pytest.param("Cài 7-Zip giúp em", "7-Zip", "allow", "R11", ["R11"], True, id="7-Zip-R11"),
    pytest.param("Cài Zoom giúp em với", "Zoom", "allow", "R11", ["R11"], True, id="Zoom-R11"),
    pytest.param("Cài Adobe Acrobat Pro cho em", "Adobe Acrobat Pro", "approval_required", "R14", ["R14"], True,
                 id="Acrobat-Pro-paid-R14"),
    pytest.param("Cài Photoshop cho em", "Photoshop", "approval_required", "R13", ["R13"], False, id="ten-la-khong-cam-R13"),
]  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "name", "decision", "rule", "matched", "in_catalog"), ASIS_CASES)
async def test_not_prohibited_unchanged(
    text: str, name: str, decision: str, rule: str, matched: list[str], in_catalog: bool
) -> None:  # fmt: skip
    """Không cấm → quyết định như trước Q5 (fact `software_prohibited=False` không làm khớp luật nào mới)."""
    state, audit, _ = await _chain("nv001", text, {"software_name": name})
    facts = state["intended_action"].facts
    assert (facts["in_catalog"], facts["software_prohibited"]) == (in_catalog, False)
    risk = _risk(state)
    assert (risk.policy_decision, risk.matched_rule_id) == (decision, rule)
    assert _all_matched(audit) == matched
    if decision == "allow":
        assert (state.get("status"), state.get("next")) == (S_EXECUTING, "b17_execute")
    else:
        assert (state.get("status"), state.get("next")) == (S_ASSESSING, "b15_prepare_approval")


@pytest.mark.asyncio
async def test_catalog_tool_error_is_e2_not_not_prohibited() -> None:
    """Tool danh mục lỗi hệ thống (500 sau retry) → B7 E2 `tool_system_error` như lỗi tool hiện nay — không đi tiếp như "không cấm"."""
    env = Env()
    env.tools.fail("check_catalog_entry", 500)
    state, audit, h = await _chain("nv001", "Cài giúp mình uTorrent", {"software_name": "uTorrent"}, env=env)
    assert (state["status"], state["exit_code"], state["escalation_reason_detail"]) == (S_ESCALATED, "E2", "tool_system_error")
    assert state.get("risk") is None
    assert not any(r["step"] == "B13/B14" for r in audit.rows)
    assert h.approvals.count("t1") == 0


# ---- B14 không thấy `software_prohibited` (ĐP 09/11 10:05: giữ đầu vào prompt B14 như bản đo RQ1) ------------------------------

B14_FACTS = {"in_catalog": True, "license_paid": False, "requires_local_admin": False, "software_prohibited": False,
             "device_registered": True, "device_owner_is_requester": True}  # fmt: skip


def _b14_ctx() -> RiskContext:
    return RiskContext(requester=rc("nv001"), facts=dict(B14_FACTS), now=NOW, within_business_hours=True,
                       target_is_other=True)  # fmt: skip  # cài cho người khác: không luật nào → tới lớp LLM


def test_b14_vars_exclude_software_prohibited() -> None:
    assert B14_EXCLUDED_FACTS == {"software_prohibited"}
    action = t24_action("install_software", facts=B14_FACTS)
    facts = estimator_vars(action, _b14_ctx(), [])["intended_action"]["facts"]
    assert facts == {k: v for k, v in B14_FACTS.items() if k != "software_prohibited"}
    assert action.facts["software_prohibited"] is False  # Action (M5, audit) vẫn giữ fact — chỉ biến B14 bỏ


@pytest.mark.asyncio
@pytest.mark.parametrize("p_method", ["self_report", "sampling_k5"])
async def test_b14_render_has_no_software_prohibited(p_method: PMethod) -> None:
    """Bản render THẬT qua gateway (ScriptedLLM) của `b14_risk_estimate` / cả 5 `b14_risk_vote`: có facts phần mềm (`in_catalog`) nhưng
    không có khoá `software_prohibited`."""
    gw = make_gateway({
        "b14_risk_estimate": lambda _v: Reply({"prob_needs_human": 0.4, "factors": ["routine_low_risk"], "rationale": "x"}),
        "b14_risk_vote": lambda _v: Reply({"needs_human": True, "factors": ["routine_low_risk"]}),
    })  # fmt: skip
    action = t24_action("install_software", facts=B14_FACTS)
    await LlmRiskEstimator(gw.client, p_method=p_method, eval_mode=False).estimate(action, _b14_ctx(), [])
    renders = [c for c in gw.llm.calls if c.prompt_id.startswith("b14")]
    assert len(renders) == (1 if p_method == "self_report" else 5)
    for call in renders:
        text = "\n".join(m["content"] for m in call.rendered_messages)
        assert "in_catalog" in text and "software_prohibited" not in text
