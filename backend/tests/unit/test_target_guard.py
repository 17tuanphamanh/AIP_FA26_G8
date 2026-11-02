"""be-target-guard (L-03) — node B3 / B5 / clarify_wait / B11 / B15 + chuỗi tích hợp tái hiện ĐÚNG ca lỗi ticket ac72e226….

Ca lỗi: nv001 (an.nv) gửi "Nhờ IT đặt lại mật khẩu cho tài khoản dịch vụ svc-backup, đội sao lưu cần đăng nhập lại", LLM chỉ trả
`{account_type: ad}` + `reset_password` (KHÔNG `target_user`) → trước bản vá: `requested_for` = nv001, R01 allow → đặt lại mật khẩu CỦA
nv001. Sau bản vá: B3 bật `ctx_flags.target_is_other` → B11 hỏi `target_user` (câu cố định, không LLM) → "svc_backup" → R03 chờ duyệt.

ScriptedLLM, không key, không Postgres. Luồng đầy đủ dùng `tests/unit/_t20b.make_flow` (graph thật, node thật, `CountingExecutor` đếm
lời gọi ghi); test mức node khuôn `test_chain_t20a.chain` (mỗi bước qua `wrap_node` — lỗi lạ → E9 → assert đỏ).
"""

import dataclasses
from typing import Any

import pytest
from app.audit.check import required
from app.domain.action import Action
from app.domain.risk_factors import FactorCode
from app.domain.states import (
    S_ASSESSING,
    S_CLARIFYING,
    S_CLASSIFYING,
    S_CONFIRMING,
    S_DIAGNOSING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_RETRIEVING,
)
from app.domain.target import TARGET_QUESTION
from app.domain.ticket_state import ChunkRef, RiskDecision
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.fakes import fake_risk
from app.graph.nodes import (
    b03_classify,
    b06_diagnose,
    b11_slots,
    b12_assess,
    b15_prepare_approval,
    clarify_wait,
)
from app.llm.providers.scripted import Reply
from app.risk.estimator import RiskEstimate
from app.settings import get_action_metadata
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fakes.risk_estimator import FakeRiskEstimator
from tests.unit._t20a import Env, rc
from tests.unit._t20b import Flow, classify, item, make_flow

BUG = "Nhờ IT đặt lại mật khẩu cho tài khoản dịch vụ svc-backup, đội sao lưu cần đăng nhập lại"
DEMO_SELF = "Mình quên mật khẩu tài khoản AD đăng nhập máy tính, đặt lại giúp mình với."
FOUR = frozenset({"vpn", "account", "software", "access"})
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}
WRITE_STEPS = frozenset({"B13/B14", "B17", "B18"})


async def seeds(f: Flow) -> dict[str, dict[str, Any]]:
    return dict((await f.values(f.parent))["child_seeds"])


def _account(text: str, slots: dict[str, str]) -> dict[str, Any]:
    return item("account", text, action="reset_password", slots=slots)


# ---- mức node --------------------------------------------------------------------------------------------------------------


@dataclasses.dataclass
class Node:
    env: Env
    h: GraphHarness
    audit: MemoryAudit
    gw: Any

    async def run(self, name: str, module: Any, state: dict[str, Any], **deps_over: Any) -> dict[str, Any]:
        deps = dataclasses.replace(self.h.deps(), enabled_intents=FOUR, **deps_over)
        run = RunContext(turn_id="T1", trace_id="0" * 32, audit=self.audit, effects=MemoryEffects(), spans=MemorySpans(),
                         clock=self.env.clock, txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run):
            update = await wrap_node(name, module.make(deps))(dict(state))
        return {**state, **update}

    def row(self, step: str, event: str | None = None) -> dict[str, Any]:
        [r] = [r for r in self.audit.rows if r["step"] == step and (event is None or r["event"] == event)]
        return r


def node(scripts: dict[str, Any] | None = None) -> Node:
    env = Env()
    gw = make_gateway({"b02_injection_judge": lambda _: Reply(NOT_ATTACK), **(scripts or {})}, clock=env.clock)
    h = GraphHarness(clock=env.clock, directory=env.directory(), llm=gw.client, rag=FakeRag())
    return Node(env, h, MemoryAudit(), gw)


def b3_state(text: str, user: str = "nv001") -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_CLASSIFYING, "redacted_request": text, "reasoning_loops": 0,
            "conversation": [], "requester_context": rc(user), "clarification_turns": 0}  # fmt: skip


async def _b3(text: str, slots: dict[str, str]) -> tuple[dict[str, Any], Node]:
    n = node({"b03_classify": lambda _: Reply({"intents": [_account(text, slots)], "is_multi": False})})
    out = await n.run("b03_classify", b03_classify, b3_state(text))
    assert out["status"] == S_DIAGNOSING, (out.get("exit_code"), out.get("escalation_reason_detail"))
    return out, n


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "slots", "reason"),
    [
        pytest.param(BUG, {"account_type": "ad"}, "identifier", id="i-khong-target"),
        pytest.param("Nhờ IT đặt lại mật khẩu AD, đội sao lưu cần đăng nhập lại", {"account_type": "ad", "account_name": "svc-backup"},
                     "unknown_key", id="ii-account_name-unknown_key"),
        pytest.param(BUG, {"account_type": "ad", "target_user": "svc-backup"}, "dropped", id="iii-target_user-bad_value"),
    ],
)  # fmt: skip
async def test_b3_sets_flag_when_other_target(text: str, slots: dict[str, str], reason: str) -> None:
    out, n = await _b3(text, slots)
    assert out["ctx_flags"] == {"target_is_other": True}
    assert "target_user" not in out["slots"]
    detail = n.row("B3")["detail"]
    assert detail["other_target_reason"] == reason
    assert isinstance(detail["other_target_mention"], bool)
    assert "svc" not in repr(detail)  # không câu/token trong audit


@pytest.mark.asyncio
async def test_b3_self_demo_sentence_no_flag() -> None:
    out, n = await _b3(DEMO_SELF, {"account_type": "ad"})
    assert "ctx_flags" not in out or out["ctx_flags"] in (None, {})
    detail = n.row("B3")["detail"]
    assert (detail["other_target_mention"], detail["other_target_reason"]) == (False, None)


@pytest.mark.asyncio
async def test_b3_valid_target_user_no_extra_flag() -> None:
    """Đích hợp lệ có trong câu → không bật cờ (requested_for đã là đích, build_ctx tự tính người khác)."""
    text = "Đặt lại mật khẩu AD cho svc_backup"
    out, n = await _b3(text, {"account_type": "ad", "target_user": "svc_backup"})
    assert out["slots"]["target_user"] == "svc_backup"
    assert not (out.get("ctx_flags") or {}).get("target_is_other")
    assert n.row("B3")["detail"]["other_target_reason"] is None


@pytest.mark.asyncio
async def test_b5_child_without_target_flags_by_whole_sentence() -> None:
    """(iv) tách 2 ý: con account KHÔNG có đích, span không nêu ai — dò TOÀN CÂU GỐC thấy "svc-backup" → con 1 bật cờ; con
    software không bật (ngoài account/access). Dòng tách B5: `children_other_target_reason` theo con."""
    reset, zoom = "đặt lại mật khẩu AD", "cài Zoom giúp svc-backup"
    f = make_flow(classify(_account(reset, {"account_type": "ad"}),
                           item("software", zoom, action="install_software", slots={"software_name": "Zoom"})))  # fmt: skip
    await f.submit(f"{reset}, tiện {zoom}")
    s = await seeds(f)
    assert s["T1-1"]["ctx_flags"] == {"target_is_other": True}
    assert s["T1-2"].get("ctx_flags") in (None, {})
    [split] = [r for r in f.h.audit.rows if r["ticket_id"] == "T1" and r["event"] == "split_into_2_children"]
    assert split["detail"]["children_other_target_reason"] == ["identifier", None]
    assert split["detail"]["other_target_mention"] is True


@pytest.mark.asyncio
async def test_a2_multi_intent_self_account_flagged_by_other_span() -> None:
    """A2 (chấp nhận có chủ ý — an toàn): "đặt lại mật khẩu cho em và cài Zoom cho chị Hoa" — ý account là của CHÍNH người gửi nhưng
    câu gốc có "cho chị Hoa" → con account BẬT cờ (B11 sẽ hỏi đích)."""
    reset, zoom = "đặt lại mật khẩu cho em", "cài Zoom cho chị Hoa"
    f = make_flow(classify(_account(reset, {"account_type": "ad"}),
                           item("software", zoom, action="install_software", slots={"software_name": "Zoom"})))  # fmt: skip
    await f.submit(f"{reset} và {zoom}")
    s = await seeds(f)
    assert s["T1-1"]["ctx_flags"] == {"target_is_other": True}
    [split] = [r for r in f.h.audit.rows if r["ticket_id"] == "T1" and r["event"] == "split_into_2_children"]
    assert split["detail"]["children_other_target_reason"] == ["phrase", None]


def clarify_state(missing: list[str], slots: dict[str, str], **over: Any) -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_CLARIFYING, "intent": "account", "reasoning_loops": 1,
            "requester_context": rc("nv001"), "slots": slots, "missing_slots": missing, "conversation": [],
            "clarification_turns": 1, "off_topic_streak": 0, **over}  # fmt: skip


@pytest.mark.asyncio
async def test_clarify_reply_names_other_sets_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """(v) lượt trả lời "email của bạn nv005 ạ" (LLM chỉ lấy `account_type`) → cờ bật `identifier`; không câu/token trong audit."""
    n = node({"b11_extract_slots": lambda _: Reply({"slots": {"account_type": "email"}, "off_topic": False})})
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": "email của bạn nv005 ạ"})
    out = await n.run("clarify_wait", clarify_wait, clarify_state(["account_type"], {"action": "reset_password"}))
    assert out["status"] == S_CLARIFYING and out["ctx_flags"] == {"target_is_other": True}
    detail = n.row("B11", "user_replied")["detail"]
    assert (detail["other_target_mention"], detail["other_target_reason"]) == (True, "identifier")
    assert "nv005" not in repr(detail)


@pytest.mark.asyncio
async def test_clarify_declared_key_not_asked_is_not_unknown_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q1 (BE duyệt): LLM nhắc lại `action` (khoá ĐÃ khai báo, không đang hỏi → `unknown_key`) → KHÔNG bật cờ."""
    n = node({"b11_extract_slots": lambda _: Reply({"slots": {"account_type": "ad", "action": "reset_password"},
                                                    "off_topic": False})})  # fmt: skip
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": "AD, đặt lại mật khẩu"})
    out = await n.run("clarify_wait", clarify_wait, clarify_state(["account_type"], {"action": "reset_password"}))
    detail = n.row("B11", "user_replied")["detail"]
    assert detail["dropped_slot_reasons"] == {"action": "unknown_key"}
    assert "ctx_flags" not in out and detail["other_target_reason"] is None


@pytest.mark.asyncio
async def test_clarify_never_lowers_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cờ đã bật + người dùng trả lời mã của CHÍNH mình → cờ giữ (node không ghi False)."""
    n = node({"b11_extract_slots": lambda _: Reply({"slots": {"target_user": "nv001"}, "off_topic": False})})
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": "nv001"})
    st = clarify_state(["target_user"], {"action": "reset_password", "account_type": "ad"}, ctx_flags={"target_is_other": True})
    out = await n.run("clarify_wait", clarify_wait, st)
    assert out["slots"]["target_user"] == "nv001" and out["ctx_flags"] == {"target_is_other": True}


def b11_state(slots: dict[str, str], *, flag: bool, turns: int = 0) -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "intent": "account", "reasoning_loops": 1,
            "requester_context": rc("nv001"), "slots": slots, "facts": {}, "conversation": [], "clarification_turns": turns,
            "ctx_flags": {"target_is_other": flag}}  # fmt: skip


@pytest.mark.asyncio
async def test_b11_flag_without_target_asks_fixed_question_no_llm() -> None:
    """B: cờ + chưa có `target_user` → `S_CLARIFYING`, `missing[0] == "target_user"`, KHÔNG `intended_action`, câu cố định (không gọi
    `b11_clarify_question` — không có script: gọi là ScriptExhausted → E9), qua notify + hạn; audit `target_required`, `prompt` None."""
    n = node()
    out = await n.run("b11_slots", b11_slots, b11_state({"action": "reset_password", "account_type": "ad"}, flag=True))
    assert (out["status"], out["next"]) == (S_CLARIFYING, "clarify_wait"), (out.get("exit_code"), out.get("escalation_reason_detail"))
    assert out["missing_slots"][0] == "target_user"
    assert out.get("intended_action") is None
    assert out["conversation"][-1]["text"] == TARGET_QUESTION
    assert n.gw.llm.calls_for("b11_clarify_question") == []
    assert [d["kind"] for d in n.h.deadlines.waits] == ["clarify"]
    detail = n.row("B11", "asked")["detail"]
    assert (detail["target_required"], detail["prompt"], detail["guard"]) == (True, None, None)


@pytest.mark.asyncio
async def test_b11_fixed_question_still_goes_through_output_guard() -> None:
    n = node()

    class Block:
        def violation(self, _text: str) -> str:
            return "blocked"

    out = await n.run("b11_slots", b11_slots, b11_state({"action": "reset_password", "account_type": "ad"}, flag=True),
                      output_guard=Block())  # fmt: skip
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "output_guard_block")
    assert out.get("conversation") in (None, [])


@pytest.mark.asyncio
async def test_b11_flag_target_first_then_other_missing() -> None:
    """Cờ + thiếu cả `account_type` → `target_user` đứng ĐẦU, slot thiếu khác theo sau."""
    n = node()
    out = await n.run("b11_slots", b11_slots, b11_state({"action": "reset_password"}, flag=True))
    assert out["missing_slots"] == ["target_user", "account_type"]


@pytest.mark.asyncio
async def test_b11_flag_with_valid_target_builds_action_for_target() -> None:
    n = node()
    out = await n.run("b11_slots", b11_slots,
                      b11_state({"action": "reset_password", "account_type": "ad", "target_user": "svc_backup"}, flag=True))  # fmt: skip
    assert out["status"] == S_ASSESSING, (out.get("exit_code"), out.get("escalation_reason_detail"))
    action = Action.model_validate(out["intended_action"])
    assert (action.requested_for, action.target) == ("svc_backup", "user:svc_backup")
    assert n.row("B11", "action_built")["detail"]["target_required"] is False


@pytest.mark.asyncio
async def test_b11_flag_last_turn_e4_clarification_exhausted() -> None:
    n = node()
    max_turns = n.h.deps().constants.MAX_CLARIFICATION_TURNS
    out = await n.run("b11_slots", b11_slots,
                      b11_state({"action": "reset_password", "account_type": "ad"}, flag=True, turns=max_turns))  # fmt: skip
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E4", "clarification_exhausted")
    assert out["missing_slots"][0] == "target_user" and out.get("intended_action") is None


@pytest.mark.asyncio
async def test_b11_no_flag_unchanged() -> None:
    """Đối chứng: không cờ → dựng Action trên người gửi như cũ (R01 hợp lệ cho câu tự xưng)."""
    n = node()
    out = await n.run("b11_slots", b11_slots, b11_state({"action": "reset_password", "account_type": "ad"}, flag=False))
    assert Action.model_validate(out["intended_action"]).requested_for == "nv001"
    assert n.row("B11", "action_built")["detail"]["target_required"] is False


def _reset_action(requested_for: str) -> Action:
    m = get_action_metadata().of("account")["reset_password"]
    return Action(
        type="reset_password", target=f"user:{requested_for}", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"account_type": "ad"},
        facts={"target_account_privilege": "standard_user", "target_is_service_account": False, "target_user_status": "active"},
    )  # fmt: skip


def b15_state(requested_for: str, *, flag: bool, intent: str = "account") -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_ASSESSING, "intent": intent, "reasoning_loops": 1,
            "requester_context": rc("nv005"), "intended_action": _reset_action(requested_for),
            "ctx_flags": {"target_is_other": flag}, "slots": {"action": "reset_password", "account_type": "ad"},
            "risk": fake_risk("HITL"), "redacted_request": "x"}  # fmt: skip


@pytest.mark.asyncio
async def test_b15_flag_and_requested_for_is_requester_e5_no_approval() -> None:
    """C: cờ + `requested_for == người gửi` → E5 `approval_target_unverified`, `stage="target_flag_guard"`, 0 phiếu, 0 lời tra AD."""
    n = node()
    ad_before = n.h.ad.calls
    out = await n.run("b15_prepare_approval", b15_prepare_approval, b15_state("nv005", flag=True))
    got = (out["status"], out["next"], out["exit_code"], out["escalation_reason_detail"])
    assert got == (S_ESCALATED, "b20_audit", "E5", "approval_target_unverified")
    assert n.h.approvals.count("t1") == 0 and n.h.approvals.notified == []
    assert n.row("B15")["detail"]["stage"] == "target_flag_guard"
    assert n.h.ad.calls == ad_before


@pytest.mark.asyncio
@pytest.mark.parametrize(("requested_for", "flag"), [("nv005", False), ("l1_02", True)], ids=["khong-co", "co-dich-khac"])
async def test_b15_guard_not_triggered_controls(requested_for: str, flag: bool) -> None:
    n = node()
    out = await n.run("b15_prepare_approval", b15_prepare_approval, b15_state(requested_for, flag=flag))
    assert out["status"] == S_PENDING_APPROVAL, (out.get("exit_code"), out.get("escalation_reason_detail"), n.audit.rows[-1])


# ---- chuỗi tích hợp: graph đầy đủ, ca lỗi nguyên văn -------------------------------------------------------------------------


def _extract(variables: Any) -> dict[str, str]:
    """`b11_extract_slots` "ngoan": câu trả lời là đúng chuỗi người dùng gõ → `target_user` (B11 đang hỏi)."""
    return {"target_user": str(variables["text"]).strip()}


def _never_action_on(values: dict[str, Any], user: str) -> None:
    raw = values.get("intended_action")
    assert raw is None or Action.model_validate(raw).requested_for != user


@pytest.mark.asyncio
async def test_chain_bug_case_asks_target_then_r03_for_svc_backup() -> None:
    f = make_flow(classify(_account(BUG, {"account_type": "ad"})), extract=_extract)
    r = await f.submit(BUG)
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events("T1")
    v = await f.values("T1")
    assert v["missing_slots"][0] == "target_user" and v.get("intended_action") is None
    assert v["ctx_flags"] == {"target_is_other": True}
    assert (await f.assistant_msgs())[-1]["text"] == TARGET_QUESTION
    assert not {s for s, _ in f.h.audit.events("T1")} & WRITE_STEPS  # không B13/B14, không B17
    assert f.h.executor.calls["T1"] == 0
    r = await f.deliver("T1", S_CLARIFYING, {"kind": "user_reply", "text": "svc_backup"})
    assert (r.status, r.waiting_at) == (S_PENDING_APPROVAL, "approval_wait"), f.h.audit.events("T1")
    v = await f.values("T1")
    action = Action.model_validate(v["intended_action"])
    assert (action.requested_for, action.target) == ("svc_backup", "user:svc_backup")
    risk = RiskDecision.model_validate(v["risk"])
    assert (risk.policy_decision, risk.matched_rule_id) == ("approval_required", "R03")
    assert f.h.executor.calls["T1"] == 0
    assert required("T1", [r for r in f.h.audit.rows if r["ticket_id"] == "T1"], final_state=None) == []


@pytest.mark.asyncio
async def test_chain_bug_case_bad_target_twice_e4_off_topic() -> None:
    """Q2 (BE duyệt, LỆCH đặc tả "×3"): "svc-backup" sai mẫu → `bad_value` → không slot sạch → `off_topic_streak` +1; lần trả lời THỨ 2
    → E4 `off_topic_twice` (luật đã chốt). Không lúc nào có Action trên nv001, 0 lời gọi ghi."""
    f = make_flow(classify(_account(BUG, {"account_type": "ad"})), extract=_extract)
    r = await f.submit(BUG)
    assert r.status == S_CLARIFYING
    r = await f.deliver("T1", S_CLARIFYING, {"kind": "user_reply", "text": "svc-backup"})
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events("T1")
    _never_action_on(await f.values("T1"), "nv001")
    r = await f.deliver("T1", S_CLARIFYING, {"kind": "user_reply", "text": "svc-backup"})
    v = await f.values("T1")
    assert (r.status, v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E4", "off_topic_twice")
    _never_action_on(v, "nv001")
    assert f.h.executor.calls["T1"] == 0
    assert not {s for s, _ in f.h.audit.events("T1")} & WRITE_STEPS


@pytest.mark.asyncio
async def test_chain_control_self_demo_sentence_r01_allow_no_question() -> None:
    """Đối chứng: câu demo tự quên mật khẩu → R01 allow, không hỏi, B17 chạy đúng 1 lần."""
    f = make_flow(classify(_account(DEMO_SELF, {"account_type": "ad"})))
    r = await f.submit(DEMO_SELF)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait"), f.h.audit.events("T1")
    v = await f.values("T1")
    assert RiskDecision.model_validate(v["risk"]).matched_rule_id == "R01"
    assert Action.model_validate(v["intended_action"]).requested_for == "nv001"
    assert "asked" not in {e for _, e in f.h.audit.events("T1")}
    assert f.h.executor.calls["T1"] == 1


@pytest.mark.asyncio
async def test_q4_self_id_reply_no_allow_rule_never_auto_then_b15_e5(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q4 (BE): cờ True + người dùng trả lời mã CỦA CHÍNH MÌNH → `requested_for` = nv001, R01 không khớp (cờ) → lớp LLM với ước lượng
    rất thấp (0,01), có bằng chứng (không kb_gap), calibrator None → KHÔNG AUTO (strategy.py:113-117) → HITL → B15 chốt C → E5."""
    n = node({"b03_classify": lambda _: Reply({"intents": [_account(BUG, {"account_type": "ad"})], "is_multi": False}),
              "b11_extract_slots": lambda _: Reply({"slots": {"target_user": "nv001"}, "off_topic": False})})  # fmt: skip
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": "nv001"})
    state = b3_state(BUG)
    for name, module, expect in (("b03_classify", b03_classify, S_DIAGNOSING), ("b06_diagnose", b06_diagnose, S_RETRIEVING),
                                 ("b11_slots", b11_slots, S_CLARIFYING), ("clarify_wait", clarify_wait, S_CLARIFYING),
                                 ("b11_slots", b11_slots, S_ASSESSING)):  # fmt: skip
        state = await n.run(name, module, state)
        assert state["status"] == expect, (name, state.get("exit_code"), state.get("escalation_reason_detail"))
    assert Action.model_validate(state["intended_action"]).requested_for == "nv001"
    assert state["ctx_flags"] == {"target_is_other": True}
    chunk = ChunkRef(chunk_id="KB-ACC-001#0", doc_id="KB-ACC-001", version=1, seq=0, title="T", heading_path="H", score=0.95,
                     excerpt="x")  # fmt: skip
    state = {**state, "retrieved": [chunk], "retrieval_score": 0.95, "kb_version": "a" * 64}
    est = FakeRiskEstimator(RiskEstimate(raw_prob=0.01, p_method="self_report", factors=(FactorCode.ROUTINE_LOW_RISK,),
                                         prompt_id="b14_risk_estimate", prompt_version="1", model="gia", evidence_trimmed=0))  # fmt: skip
    state = await n.run("b12_assess", b12_assess, state, estimator=est, calibrator=None)
    risk = RiskDecision.model_validate(state["risk"])
    assert est.calls and est.calls[0][1].target_is_other is True
    assert (risk.decided_by, risk.matched_rule_id, risk.route) == ("llm", None, "HITL"), risk
    assert (state["status"], state["next"]) == (S_ASSESSING, "b15_prepare_approval")
    state = await n.run("b15_prepare_approval", b15_prepare_approval, state)
    assert (state["exit_code"], state["escalation_reason_detail"]) == ("E5", "approval_target_unverified")
    assert n.h.approvals.count("t1") == 0


def test_audit_check_new_fields_no_false_missing() -> None:
    """`audit/check.required` không báo thiếu với dòng điểm log 1 có trường mới (không đổi check.py)."""
    row = {"step": "B3", "event": "intent_classified", "intent": "account",
           "detail": {"layer": "llm", "intent": "account", "confidence": 0.9, "dropped_slot_keys": [],
                      "other_target_mention": True, "other_target_reason": "identifier"}}  # fmt: skip
    b11 = {"step": "B11", "event": "asked", "detail": {"target_required": True, "missing": ["target_user"]}}
    assert required("t1", [row, b11], final_state=None) == []

