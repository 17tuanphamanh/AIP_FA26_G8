"""be-target-guard-2 (L-03 Phần 2 D, ĐP duyệt 02/11 13:35) — software/vpn: câu nhắm MÁY người khác không được tự suy máy duy nhất của
người gửi (V1: "cài Zoom lên máy của chị Hoa"; V2: "lap-0610" sai mẫu / LLM bỏ khoá mã máy).

Hàm thuần `target_check` (vpn/software) → node B6 (`allow_infer`) → B11 (`devices = []` khi cờ bật, ĐP Q1 = a) → chuỗi đủ: hỏi mã máy →
máy người khác → E5, 0 phiếu, 0 lần thực hiện. Đối chứng R11/R20 trên máy của chính người gửi KHÔNG đổi. ScriptedLLM, không key, không
Postgres; seed: nv001 có đúng 1 máy LAP-0342, LAP-0610 của nv005.
"""

from typing import Any

import pytest
from app.domain.action import Action
from app.domain.risk_factors import FactorCode
from app.domain.slots import sanitize_slots
from app.domain.states import (
    S_ASSESSING,
    S_CLARIFYING,
    S_CONFIRMING,
    S_DIAGNOSING,
    S_ESCALATED,
    S_RETRIEVING,
)
from app.domain.target import target_check
from app.domain.ticket_state import ChunkRef, RiskDecision
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
from app.settings import get_slots
from tests.fakes.risk_estimator import FakeRiskEstimator
from tests.unit._t20a import rc
from tests.unit._t20b import classify, item, make_flow
from tests.unit.test_target_guard import WRITE_STEPS, b3_state, node

SLOTS = get_slots()
SOFT, VPN = SLOTS.intents["software"].keys, SLOTS.intents["vpn"].keys
V1 = "Cài Zoom lên máy của chị Hoa giúp em"
V2 = "Cấp lại chứng chỉ VPN cho máy lap-0610"
# 2 câu Duy Anh chạy lượt 1 (demo e974563, LLM thật) — ĐP 02/11 13:55
DA_A = "Chị Hoa bên Sales lỗi VPN, nhờ IT cấp lại chứng chỉ cho máy chị ấy"
DA_B = "Cài Zoom lên máy lap-0610 của chị Hoa"


# ---- hàm thuần ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent", "text", "slots", "dropped", "reason"),
    [
        ("software", "cài Zoom lên máy của nv005", {"software_name": "Zoom"}, {}, "identifier"),
        ("software", "cài Zoom lên máy của NV005 giúp em", {"software_name": "Zoom"}, {}, "identifier"),
        ("software", V1, {"software_name": "Zoom"}, {}, "phrase"),
        ("software", "cài Zoom cho máy chị ấy", {"software_name": "Zoom"}, {}, "phrase"),
        ("software", "cài Zoom cho máy anh Nam với", {"software_name": "Zoom"}, {}, "phrase"),
        ("software", "cài Zoom lên máy của sếp", {"software_name": "Zoom"}, {}, "phrase"),
        ("software", "cai Zoom len may cua chi Hoa", {"software_name": "Zoom"}, {}, "phrase"),
        ("software", "cài Teams cho đồng nghiệp mới vào", {"software_name": "Teams"}, {}, "phrase"),
        ("vpn", "cấp lại chứng chỉ cho máy chị ấy", {"action": "renew_vpn_cert"}, {}, "phrase"),
        ("vpn", "VPN máy LAP 0610 lỗi chứng chỉ", {}, {}, "device_text"),
        ("vpn", V2, {"action": "renew_vpn_cert"}, {}, "device_text"),  # LLM bỏ khoá device_id
        ("vpn", V2, {"action": "renew_vpn_cert"}, {"device_id": "bad_value"}, "dropped"),
        ("vpn", "VPN máy LAP 0610 lỗi chứng chỉ", {}, {"device_id": "slot_not_in_text"}, "dropped"),
        ("software", "cài Zoom lên PC0977", {"software_name": "Zoom"}, {}, "device_text"),
        ("vpn", DA_A, {"action": "renew_vpn_cert"}, {}, "phrase"),
        ("software", DA_B, {"software_name": "Zoom", "device_id": "LAP-0610"}, {}, "phrase"),
        ("software", "Cài Zoom lên máy lap-0610", {"software_name": "Zoom"}, {}, "device_text"),  # LLM bỏ khoá máy
        ("vpn", "VPN máy lap-0610 lỗi chứng chỉ", {}, {}, "device_text"),
        ("software", "Cài Zoom lên máy lap-0610 của chị Hoa", {"software_name": "Zoom"}, {}, "phrase"),
    ],
)  # fmt: skip
def test_flag_on(intent: str, text: str, slots: dict[str, str], dropped: dict[str, str], reason: str) -> None:
    keys = SOFT if intent == "software" else VPN
    mention, got = target_check(intent, slots, dropped, keys, text, "nv001")
    assert got == reason
    assert mention is (reason in ("identifier", "phrase"))


@pytest.mark.parametrize(
    ("intent", "text", "slots"),
    [
        ("software", "cài 7-zip giúp em", {"software_name": "7-zip"}),
        ("software", "cài 7-zip giúp em", {}),
        ("software", "cài python3.11 giúp em", {"software_name": "python3.11"}),
        ("software", "cài python3.11 giúp em", {}),
        ("software", "cập nhật win11 giúp em", {}),
        ("software", "cài Zoom cho máy em", {"software_name": "Zoom"}),
        ("software", "cài Zoom lên máy của em", {"software_name": "Zoom"}),
        ("software", "cài Zoom cho máy mình với", {"software_name": "Zoom"}),
        ("software", "cài Office 2021 cho em", {"software_name": "Office 2021"}),
        ("software", "cài Notepad++ 8.6 cho em", {"software_name": "Notepad++"}),
        ("software", "cài Zoom lên máy LAP-0342", {"software_name": "Zoom", "device_id": "LAP-0342"}),
        ("software", "cài Zoom lên máy lap-0342", {"software_name": "Zoom", "device_id": "LAP-0342"}),
        ("software", "cài Zoom lên máy của nv001", {"software_name": "Zoom"}),  # mã của CHÍNH người gửi
        ("vpn", "VPN không vào được, báo lỗi 809", {}),
        ("vpn", "VPN lỗi 0x80070005 từ sáng", {}),
        ("vpn", "VPN báo lỗi ở cổng 443", {}),  # ĐP 14:10: chữ có dấu trước số không thành mã máy (trước: "ng 443" → NG-443)
        ("vpn", "Máy em ở phòng 302 không vào được VPN", {}),
        ("vpn", "Cấp lại chứng chỉ VPN cho máy LAP-0342", {"device_id": "LAP-0342", "action": "renew_vpn_cert"}),
    ],
)  # fmt: skip
def test_flag_off(intent: str, text: str, slots: dict[str, str]) -> None:
    keys = SOFT if intent == "software" else VPN
    assert target_check(intent, slots, {}, keys, text, "nv001") == (False, None)


@pytest.mark.parametrize("raw", ["lap-0610", "Lap-0610", "LAP-0610"])
def test_sanitize_device_id_case_insensitive(raw: str) -> None:
    """ĐP 13:55: "lap-0610" khớp "LAP-0610" (chuẩn hoá chữ hoa trước mẫu; slots.yaml không đổi)."""
    clean, dropped = sanitize_slots(SLOTS.intents["software"], {"software_name": "Zoom", "device_id": raw}, text=DA_B)
    assert clean["device_id"] == "LAP-0610" and dropped == {}
    clean, dropped = sanitize_slots(SLOTS.intents["vpn"], {"device_id": "lap-9999"}, text=DA_B)
    assert dropped == {"device_id": "slot_not_in_text"}  # vẫn phải có thật trong câu


def test_account_access_unchanged_by_device_rules() -> None:
    """Cụm máy và `device_text` chỉ áp vpn/software — account/access giữ đúng bản be-target-guard."""
    acc = SLOTS.intents["account"].keys
    assert target_check("account", {"account_type": "ad"}, {}, acc, "đặt lại mật khẩu AD, máy LAP 0610", "nv001") == (False, None)
    assert target_check("account", {"account_type": "ad"}, {}, acc, "đặt lại mật khẩu máy tính của chị", "nv001") == (False, None)
    # V5 (D-91): "của sếp" là VAI TRÒ người khác — bật cờ ở account qua lưới account (không phải luật máy)
    assert target_check("account", {"account_type": "ad"}, {}, acc, "đặt lại mật khẩu máy của sếp", "nv001") == (True, "phrase")


# ---- node B3 → B6, B11 -------------------------------------------------------------------------------------------------------


async def _b3_b6(intent: str, text: str, slots: dict[str, str], action: str) -> dict[str, Any]:
    n = node({"b03_classify": lambda _: Reply({"intents": [item(intent, text, action=action, slots=slots)], "is_multi": False})})
    st = await n.run("b03_classify", b03_classify, b3_state(text))
    assert st["status"] == S_DIAGNOSING, (st.get("exit_code"), st.get("escalation_reason_detail"))
    st = await n.run("b06_diagnose", b06_diagnose, st)
    assert st["status"] == S_RETRIEVING, (st.get("exit_code"), st.get("escalation_reason_detail"))
    return st


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "text", "slots", "action"),
    [("software", V1, {"software_name": "Zoom"}, "install_software"),
     ("vpn", V2, {"device_id": "lap-06100"}, "renew_vpn_cert"),  # mã không có trong câu → slot_not_in_text → dropped
     ("vpn", DA_A, {}, "renew_vpn_cert")],
)  # fmt: skip
async def test_b6_flag_no_inferred_device(intent: str, text: str, slots: dict[str, str], action: str) -> None:
    st = await _b3_b6(intent, text, slots, action)
    assert st["ctx_flags"] == {"target_is_other": True}
    assert "device_id" not in st["slots"]  # KHÔNG suy LAP-0342 của nv001
    assert "device_owner_is_requester" not in st["facts"] and "cert_status" not in st["facts"]
    assert st["facts"]["device_count"] == 1  # fact theo người vẫn có


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "text", "slots", "action"),
    [("software", "cài Zoom cho máy em", {"software_name": "Zoom"}, "install_software"),
     ("vpn", "VPN không vào được, báo lỗi chứng chỉ", {}, "renew_vpn_cert")],
)  # fmt: skip
async def test_b6_control_self_still_infers_own_device(intent: str, text: str, slots: dict[str, str], action: str) -> None:
    st = await _b3_b6(intent, text, slots, action)
    assert not (st.get("ctx_flags") or {}).get("target_is_other")
    assert st["slots"]["device_id"] == "LAP-0342"
    assert st["facts"]["device_owner_is_requester"] is True


def test_b11_summary_hides_requester_devices_when_flag() -> None:
    """ĐP Q1 = a: cờ bật → `devices = []` (câu hỏi không gợi ý máy của người gửi); không cờ → như cũ."""
    diag = {"check_device_registered": [{"device_id": "LAP-0342", "owner_id": "nv001", "registered": True}]}
    base = {"requester_context": rc("nv001"), "diagnostics": diag}
    assert b11_slots.diagnostics_summary({**base, "ctx_flags": {"target_is_other": True}}, {"device_count": 1})["devices"] == []
    assert b11_slots.diagnostics_summary({**base, "ctx_flags": {"target_is_other": False}}, {})["devices"] == ["LAP-0342"]
    assert b11_slots.diagnostics_summary(base, {})["devices"] == ["LAP-0342"]


# ---- chuỗi đủ: đúng 2 câu Duy Anh chạy ------------------------------------------------------------------------------------------


def _device_reply(variables: Any) -> dict[str, str]:
    """`b11_extract_slots` "ngoan": người dùng gõ đúng mã máy → `device_id`."""
    return {"device_id": str(variables["text"]).strip()}


def _no_action_on_requester_device(values: dict[str, Any]) -> None:
    raw = values.get("intended_action")
    assert raw is None or Action.model_validate(raw).target != "device:LAP-0342"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "it"),
    [pytest.param(V1, item("software", V1, action="install_software", slots={"software_name": "Zoom"}), id="V1-zoom-chi-Hoa"),
     pytest.param(DA_A, item("vpn", DA_A, action="renew_vpn_cert"), id="DA-a-may-chi-ay"),
     pytest.param(DA_B, item("software", DA_B, action="install_software", slots={"software_name": "Zoom"}),
                  id="DA-b-LLM-bo-khoa-may"),
     pytest.param(V2, item("vpn", V2, action="renew_vpn_cert"), id="V2-LLM-bo-khoa-may")],
)  # fmt: skip
async def test_chain_other_device_asks_then_e5_no_approval_no_exec(text: str, it: dict[str, Any]) -> None:
    f = make_flow(classify(it), extract=_device_reply)
    r = await f.submit(text)
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events("T1")
    v = await f.values("T1")
    assert v["ctx_flags"] == {"target_is_other": True}
    assert "device_id" in v["missing_slots"] and v.get("intended_action") is None
    assert not {s for s, _ in f.h.audit.events("T1")} & WRITE_STEPS
    asked = [c for c in f.gw.llm.calls_for("b11_clarify_question")]
    assert asked and all("LAP-0342" not in repr(c) for c in asked)  # Q1 = a: không gợi ý máy của người gửi
    r = await f.deliver("T1", S_CLARIFYING, {"kind": "user_reply", "text": "LAP-0610"})  # máy của nv005
    v = await f.values("T1")
    assert (r.status, v["exit_code"]) == (S_ESCALATED, "E5"), (v.get("escalation_reason_detail"), f.h.audit.events("T1"))
    action = Action.model_validate(v["intended_action"])
    assert action.target == "device:LAP-0610" and action.facts["device_owner_is_requester"] is False
    _no_action_on_requester_device(v)
    assert f.h.approvals.count("T1") == 0
    assert f.h.executor.calls["T1"] == 0
    assert not {s for s, _ in f.h.audit.events("T1")} & {"B17", "B18"}


@pytest.mark.asyncio
async def test_chain_control_r11_self_zoom_auto() -> None:
    """Đối chứng R11: "cài Zoom cho máy em" → không hỏi, suy LAP-0342, tự cài đúng 1 lần."""
    text = "Cài Zoom cho máy em với"
    f = make_flow(classify(item("software", text, action="install_software", slots={"software_name": "Zoom"})))
    r = await f.submit(text)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait"), f.h.audit.events("T1")
    v = await f.values("T1")
    assert RiskDecision.model_validate(v["risk"]).matched_rule_id == "R11"
    assert Action.model_validate(v["intended_action"]).target == "device:LAP-0342"
    assert f.h.executor.calls["T1"] == 1


@pytest.mark.asyncio
async def test_chain_control_r20_self_vpn_cert() -> None:
    """Đối chứng R20: chứng chỉ máy của chính mình (nêu đúng mã) → cờ không bật, luật tự làm R20 (hoặc R18 ngoài giờ) như cũ."""
    text = "Cấp lại chứng chỉ VPN cho máy LAP-0342"
    f = make_flow(classify(item("vpn", text, action="renew_vpn_cert", slots={"device_id": "LAP-0342"})))
    await f.submit(text)
    v = await f.values("T1")
    assert not (v.get("ctx_flags") or {}).get("target_is_other")
    assert "asked" not in {e for _, e in f.h.audit.events("T1")}
    assert RiskDecision.model_validate(v["risk"]).matched_rule_id in ("R20", "R18"), v.get("risk")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "it"),
    [pytest.param(V1, item("software", V1, action="install_software", slots={"software_name": "Zoom"}), id="V1"),
     pytest.param(DA_A, item("vpn", DA_A, action="renew_vpn_cert"), id="DA-a")],
)  # fmt: skip
async def test_nodes_llm_layer_hitl_then_b15_p6_e5(monkeypatch: pytest.MonkeyPatch, text: str, it: dict[str, Any]) -> None:
    """Như demo (lớp AI chạy): máy người khác → không luật allow (R11/R20 đòi cờ false + chủ máy) → lớp LLM ước lượng THẤP, calibrator
    None → HITL (không AUTO, D-38) → B15 chốt P6 → E5 `approval_target_unverified`, `stage="target_guard"`, 0 phiếu."""
    n = node({"b03_classify": lambda _: Reply({"intents": [it], "is_multi": False}),
              "b11_clarify_question": lambda _: Reply({"text": "Bạn cần xử lý trên máy nào? Vui lòng ghi mã máy."}),
              "b11_extract_slots": lambda _: Reply({"slots": {"device_id": "LAP-0610"}, "off_topic": False})})  # fmt: skip
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": "LAP-0610"})
    state = b3_state(text)
    for name, module, expect in (("b03_classify", b03_classify, S_DIAGNOSING), ("b06_diagnose", b06_diagnose, S_RETRIEVING),
                                 ("b11_slots", b11_slots, S_CLARIFYING), ("clarify_wait", clarify_wait, S_CLARIFYING),
                                 ("b11_slots", b11_slots, S_ASSESSING)):  # fmt: skip
        state = await n.run(name, module, state)
        assert state["status"] == expect, (name, state.get("exit_code"), state.get("escalation_reason_detail"))
    action = Action.model_validate(state["intended_action"])
    assert action.target == "device:LAP-0610" and action.facts["device_owner_is_requester"] is False
    chunk = ChunkRef(chunk_id="KB#0", doc_id="KB-SW-001", version=1, seq=0, title="T", heading_path="H", score=0.95, excerpt="x")
    state = {**state, "retrieved": [chunk], "retrieval_score": 0.95, "kb_version": "a" * 64}
    est = FakeRiskEstimator(RiskEstimate(raw_prob=0.01, p_method="self_report", factors=(FactorCode.ROUTINE_LOW_RISK,),
                                         prompt_id="b14_risk_estimate", prompt_version="1", model="gia", evidence_trimmed=0))  # fmt: skip
    state = await n.run("b12_assess", b12_assess, state, estimator=est, calibrator=None)
    risk = RiskDecision.model_validate(state["risk"])
    assert (risk.decided_by, risk.matched_rule_id, risk.route) == ("llm", None, "HITL"), risk
    state = await n.run("b15_prepare_approval", b15_prepare_approval, state)
    assert (state["exit_code"], state["escalation_reason_detail"]) == ("E5", "approval_target_unverified")
    assert n.row("B15")["detail"]["stage"] == "target_guard"
    assert n.h.approvals.count("t1") == 0


@pytest.mark.asyncio
async def test_chain_da_b_lowercase_device_no_question_never_requester_device() -> None:
    """DA b) LLM đưa "lap-0610" → chuẩn hoá LAP-0610 (máy nv005) → không hỏi, không suy LAP-0342; E5, 0 phiếu, 0 lần cài."""
    f = make_flow(classify(item("software", DA_B, action="install_software", slots={"software_name": "Zoom", "device_id": "lap-0610"})))
    r = await f.submit(DA_B)
    v = await f.values("T1")
    assert (r.status, v["exit_code"]) == (S_ESCALATED, "E5"), (v.get("escalation_reason_detail"), f.h.audit.events("T1"))
    assert v["slots"]["device_id"] == "LAP-0610" and v["ctx_flags"] == {"target_is_other": True}
    action = Action.model_validate(v["intended_action"])
    assert action.target == "device:LAP-0610" and action.facts["device_owner_is_requester"] is False
    assert f.h.approvals.count("T1") == 0 and f.h.executor.calls["T1"] == 0


@pytest.mark.asyncio
async def test_nodes_da_b_llm_hitl_then_b15_p6_e5() -> None:
    """DA b) như demo (lớp AI chạy, ước lượng thấp, chưa hiệu chỉnh → HITL) → B15 chốt P6 → E5 `approval_target_unverified`, 0 phiếu."""
    it = item("software", DA_B, action="install_software", slots={"software_name": "Zoom", "device_id": "lap-0610"})
    n = node({"b03_classify": lambda _: Reply({"intents": [it], "is_multi": False})})
    state = b3_state(DA_B)
    for name, module, expect in (("b03_classify", b03_classify, S_DIAGNOSING), ("b06_diagnose", b06_diagnose, S_RETRIEVING),
                                 ("b11_slots", b11_slots, S_ASSESSING)):  # fmt: skip
        state = await n.run(name, module, state)
        assert state["status"] == expect, (name, state.get("exit_code"), state.get("escalation_reason_detail"))
    chunk = ChunkRef(chunk_id="KB#0", doc_id="KB-SW-001", version=1, seq=0, title="T", heading_path="H", score=0.95, excerpt="x")
    state = {**state, "retrieved": [chunk], "retrieval_score": 0.95, "kb_version": "a" * 64}
    est = FakeRiskEstimator(RiskEstimate(raw_prob=0.01, p_method="self_report", factors=(FactorCode.ROUTINE_LOW_RISK,),
                                         prompt_id="b14_risk_estimate", prompt_version="1", model="gia", evidence_trimmed=0))  # fmt: skip
    state = await n.run("b12_assess", b12_assess, state, estimator=est, calibrator=None)
    assert RiskDecision.model_validate(state["risk"]).route == "HITL"
    state = await n.run("b15_prepare_approval", b15_prepare_approval, state)
    assert (state["exit_code"], state["escalation_reason_detail"]) == ("E5", "approval_target_unverified")
    assert n.h.approvals.count("t1") == 0
