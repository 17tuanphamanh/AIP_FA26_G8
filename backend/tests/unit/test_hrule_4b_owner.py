"""h-rule Phase 4 P7 (Q-4-M, G4-16): R17, R18, R19 đòi `action.facts.device_owner_is_requester is_true` (phase4 mục 5.1 P7; bảng 3.2
x5, x6). Viết TỪ ĐẶC TẢ, trước khi sửa `config/policy.json`.

Quy ước như `test_policy_rules_vpn.py`: HITL ↔ `decision == "approval_required"`; "không luật nào → E5" ↔ `matched is False`,
`all_matched == []`, `decision is None`.

1. Ba dòng h-rule MỚI (P7), đi đường thật `build_ctx` → `evaluate`: "ngoài giờ + máy người khác → E5", "thử việc + máy người khác → E5",
   "máy không tồn tại → E5" (+ tổ hợp của chúng).
2. Mỗi luật R17/R18/R19: ≥ 1 ca khớp DƯƠNG với máy CỦA CHÍNH người gửi (không nới lỏng quá tay) + ca suýt khớp vì owner false/thiếu —
   `RiskContext` dựng tay (khuôn `LUAT_C5`, `target_is_other=False` để chỉ còn điều kiện owner của chính luật đó quyết; M-4b-6, M-4b-7).
3. x5, x6 cấp graph (`GraphHarness(nodes="real")`, B1 → … → B12 thật, VPN giả đọc seed, ScriptedLLM `vpn_scripts`): E5
   `llm_layer_disabled`, 0 phiếu, 0 lời gọi ghi, không chạm B15.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from app.core.clock import FakeClock
from app.domain.action import Action, FactValue
from app.domain.context import RequesterContext
from app.domain.facts import check_facts
from app.domain.messages import device_not_found_question
from app.domain.states import S_CLARIFYING, S_ESCALATED
from app.domain.ticket_state import ChunkRef
from app.graph.late_event import deliver_event
from app.rag.models import RetrievalResult
from app.risk.context import build_ctx
from app.risk.models import RiskContext, RuleVerdict
from app.risk.policy_engine import evaluate
from app.settings import get_action_metadata, get_policy
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts

REPO = Path(__file__).resolve().parents[3]
VN = ZoneInfo("Asia/Ho_Chi_Minh")
TRONG_GIO = datetime(2026, 9, 29, 10, 0, tzinfo=VN)  # thứ Ba 29/09/2026 10:00 giờ VN
NGOAI_GIO = datetime(2026, 9, 29, 20, 0, tzinfo=VN)  # cùng ngày 20:00 giờ VN
META = get_action_metadata().of("vpn")
RENEW, REISSUE = "renew_vpn_cert", "reissue_vpn_access"
HITL = "approval_required"

NV001 = RequesterContext(
    user_id="nv001", role="employee", department="Finance", manager_id="fin_head", employment_status="active",
    tenure_days=980, is_privileged_account=False, captured_at=TRONG_GIO,
)  # fmt: skip
NV002 = RequesterContext(
    user_id="nv002", role="employee", department="Engineering", manager_id="eng_head", employment_status="active",
    tenure_days=720, is_privileged_account=False, captured_at=TRONG_GIO,
)  # fmt: skip
NV003 = RequesterContext(
    user_id="nv003", role="employee", department="Finance", manager_id="fin_head", employment_status="probation",
    tenure_days=30, is_privileged_account=False, captured_at=TRONG_GIO,
)  # fmt: skip

# Facts như B6/B11 đọc từ tool trên seed (phase3 mục 3.2):
F_LAP0417_OTHER: dict[str, FactValue] = {"device_registered": True, "device_owner_is_requester": False}  # của nv002
F_LAP9999_NONE: dict[str, FactValue] = {"device_registered": False, "device_owner_is_requester": False}  # không tồn tại
F_PC0977_OTHER: dict[str, FactValue] = {"device_registered": False, "device_owner_is_requester": False}  # nv001 hỏi máy nv002
REG_OWN: dict[str, FactValue] = {"device_registered": True, "device_owner_is_requester": True}
UNREG_OWN: dict[str, FactValue] = {"device_registered": False, "device_owner_is_requester": True}


def _action(action_type: str, device_id: str, requested_for: str, facts: dict[str, FactValue]) -> Action:
    check_facts(facts)
    m = META[action_type]
    return Action(
        type=action_type, target=f"device:{device_id}", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": device_id}, facts=dict(facts),
    )  # fmt: skip


def _bo(facts: dict[str, FactValue], key: str) -> dict[str, FactValue]:
    return {k: v for k, v in facts.items() if k != key}


def _qua_build_ctx(requester: RequesterContext, action: Action, now: datetime) -> RuleVerdict:
    state = {"intended_action": action, "requester_context": requester, "ctx_flags": {"target_is_other": False}}
    return evaluate(action, build_ctx(state, now, get_policy().business_hours))


def _khong_luat_nao(v: RuleVerdict) -> None:
    assert (v.matched, v.all_matched, v.decision, v.rule_id) == (False, [], None, None), v


# ---- 1. Ba dòng h-rule mới (P7) — qua build_ctx ------------------------------------------------------------------------


@dataclass(frozen=True)
class Dong:
    requester: RequesterContext
    action_type: str
    device_id: str
    facts: dict[str, FactValue]
    now: datetime


# fmt: off
HRULE_P7 = [
    pytest.param(Dong(NV001, RENEW, "LAP-0417", F_LAP0417_OTHER, NGOAI_GIO),
                 id="P7-ngoai-gio-20h-may-nguoi-khac-E5-x5"),
    pytest.param(Dong(NV003, RENEW, "LAP-0417", F_LAP0417_OTHER, TRONG_GIO),
                 id="P7-thu-viec-may-nguoi-khac-E5"),
    pytest.param(Dong(NV001, RENEW, "LAP-9999", F_LAP9999_NONE, TRONG_GIO),
                 id="P7-may-khong-ton-tai-E5-x6"),
    # tổ hợp: nhiều điều kiện "rủi ro" cùng đúng vẫn không mở được phiếu cho máy không phải của mình
    pytest.param(Dong(NV001, REISSUE, "LAP-9999", F_LAP9999_NONE, NGOAI_GIO),
                 id="P7-may-khong-ton-tai-20h-E5"),
    pytest.param(Dong(NV003, RENEW, "LAP-9999", F_LAP9999_NONE, NGOAI_GIO),
                 id="P7-thu-viec-may-khong-ton-tai-20h-E5"),
    pytest.param(Dong(NV001, REISSUE, "PC-0977", F_PC0977_OTHER, TRONG_GIO),
                 id="P7-may-chua-dang-ky-cua-nguoi-khac-E5"),
    pytest.param(Dong(NV001, RENEW, "LAP-0417", _bo(F_LAP0417_OTHER, "device_owner_is_requester"), NGOAI_GIO),
                 id="P7-20h-thieu-fact-owner-E5"),
]
# fmt: on


@pytest.mark.parametrize("dong", HRULE_P7)
def test_hrule_p7_not_own_device_no_rule_e5(dong: Dong) -> None:
    """h-rule P7 (Q-4-M): máy không phải của người gửi (người khác / không tồn tại / thiếu fact owner) → KHÔNG luật nào → E5
    `llm_layer_disabled` ở B12, nhất quán ngày/đêm (G4-16: trước P7 R17/R18/R19 mở phiếu duyệt cho các ca này)."""
    action = _action(dong.action_type, dong.device_id, dong.requester.user_id, dong.facts)
    _khong_luat_nao(_qua_build_ctx(dong.requester, action, dong.now))


def test_hrule_p7_has_three_spec_rows() -> None:
    """Quy ước 3.9: bảng không rỗng, đủ 3 dòng P7 (ngoài giờ + người khác, thử việc + người khác, máy không tồn tại)."""
    ids = [str(p.id) for p in HRULE_P7]
    assert len(ids) == len(set(ids)) >= 3
    for key in ("ngoai-gio-20h-may-nguoi-khac", "thu-viec-may-nguoi-khac", "may-khong-ton-tai-E5-x6"):
        assert any(key in i for i in ids), key


# ---- 2. R17/R18/R19 khớp dương với máy CỦA MÌNH + suýt khớp vì owner ------------------------------------------------------


@dataclass(frozen=True)
class CaLuat:
    luat: str
    loai: str  # "khop" | "suyt"
    action_type: str
    facts: dict[str, FactValue]
    requester: RequesterContext
    trong_gio: bool
    khop: frozenset[str]
    decision: str | None


def _cl(luat: str, loai: str, action_type: str, facts: dict[str, FactValue], *, khop: str, decision: str | None,
        requester: RequesterContext = NV001, trong_gio: bool = True) -> CaLuat:  # fmt: skip
    return CaLuat(luat, loai, action_type, facts, requester, trong_gio, frozenset(khop.split()), decision)


# fmt: off
LUAT_P7 = [
    # R17 — chưa đăng ký + của chính mình (bảng 3.2 x2/x3/x4 dùng máy chưa đăng ký của chính người gửi)
    pytest.param(_cl("R17", "khop", RENEW, UNREG_OWN, khop="R17", decision=HITL), id="R17-khop-may-minh-chua-dang-ky"),
    pytest.param(_cl("R17", "khop", REISSUE, UNREG_OWN, khop="R17", decision=HITL, requester=NV002),
                 id="R17-khop-reissue-tc09-PC0977"),
    pytest.param(_cl("R17", "suyt", RENEW, {"device_registered": False, "device_owner_is_requester": False},
                     khop="", decision=None), id="R17-suyt-owner-false"),
    pytest.param(_cl("R17", "suyt", RENEW, _bo(UNREG_OWN, "device_owner_is_requester"), khop="", decision=None),
                 id="R17-suyt-thieu-owner"),
    # R18 — ngoài giờ + máy đã đăng ký của mình (R20 cũng khớp; approval_required thắng allow)
    pytest.param(_cl("R18", "khop", RENEW, REG_OWN, khop="R18 R20", decision=HITL, trong_gio=False),
                 id="R18-khop-may-minh-20h"),
    pytest.param(_cl("R18", "khop", RENEW, UNREG_OWN, khop="R17 R18", decision=HITL, trong_gio=False),
                 id="R18-khop-may-minh-chua-dang-ky-20h-cung-R17"),
    pytest.param(_cl("R18", "suyt", RENEW, F_LAP0417_OTHER, khop="", decision=None, trong_gio=False),
                 id="R18-suyt-owner-false-20h-M-4b-6"),
    pytest.param(_cl("R18", "suyt", RENEW, _bo(REG_OWN, "device_owner_is_requester"), khop="", decision=None,
                     trong_gio=False), id="R18-suyt-thieu-owner-20h"),
    # R19 — thử việc + máy của mình (bảng 3.2 x1: nv003 LAP-0501)
    pytest.param(_cl("R19", "khop", RENEW, REG_OWN, khop="R19 R20", decision=HITL, requester=NV003),
                 id="R19-khop-thu-viec-may-minh"),
    pytest.param(_cl("R19", "suyt", RENEW, F_LAP0417_OTHER, khop="", decision=None, requester=NV003),
                 id="R19-suyt-owner-false"),
    pytest.param(_cl("R19", "suyt", REISSUE, _bo(REG_OWN, "device_owner_is_requester"), khop="", decision=None,
                     requester=NV003), id="R19-suyt-thieu-owner"),
]
# fmt: on


@pytest.mark.parametrize("ca", LUAT_P7)
def test_hrule_p7_rule_needs_owner(ca: CaLuat) -> None:
    """P7: R17/R18/R19 có thêm điều kiện chủ máy — khớp với máy của chính người gửi, không khớp khi owner false/thiếu. Ctx dựng
    tay với `target_is_other=False` → chỉ điều kiện owner CỦA CHÍNH luật quyết (bắt M-4b-6/M-4b-7 dù R20/build_ctx không đổi)."""
    action = _action(ca.action_type, "LAP-0501", ca.requester.user_id, ca.facts)
    ctx = RiskContext(
        requester=ca.requester, facts=dict(action.facts), now=TRONG_GIO if ca.trong_gio else NGOAI_GIO,
        within_business_hours=ca.trong_gio, target_is_other=False,
    )  # fmt: skip
    v = evaluate(action, ctx)
    assert set(v.all_matched) == ca.khop, v
    assert v.decision == ca.decision
    assert v.matched is bool(ca.khop)
    assert (ca.luat in v.all_matched) is (ca.loai == "khop")


def test_hrule_p7_each_rule_has_positive_and_near_miss() -> None:
    cases = [cast(CaLuat, p.values[0]) for p in LUAT_P7]
    for luat in ("R17", "R18", "R19"):
        assert any(c.luat == luat and c.loai == "khop" and luat in c.khop for c in cases), luat
        assert any(c.luat == luat and c.loai == "suyt" and luat not in c.khop for c in cases), luat


def test_hrule_p7_policy_json_r17_r18_r19_carry_owner_condition() -> None:
    """P7: đúng điều kiện `{"fact": "action.facts.device_owner_is_requester", "op": "is_true"}` nằm trong `conditions.all` của
    R17, R18, R19; R16, R20 không đổi so với 3h."""
    owner = {"fact": "action.facts.device_owner_is_requester", "op": "is_true"}
    raw = json.loads((REPO / "config" / "policy.json").read_text(encoding="utf-8"))
    rules = {r["id"]: r for r in raw["rules"]}
    for rid in ("R17", "R18", "R19"):
        assert owner in rules[rid]["conditions"]["all"], rid
    vpn = ["R16", "R17", "R18", "R19", "R20"]  # T22a 4.7b: file nay có thêm R01–R15 — R16–R20 vẫn có mặt, đúng thứ tự
    assert set(vpn) <= set(rules)
    assert [r.id for r in get_policy().rules if r.id in vpn] == vpn


# ---- 3. x5, x6 cấp graph --------------------------------------------------------------------------------------------------


def _rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-VPN-004", version=1, seq=0, title="T", heading_path="H",
                     score=0.99, excerpt="x")  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False))  # fmt: skip


async def _graph(at: datetime, text: str) -> tuple[GraphHarness, dict[str, Any]]:
    """Khuôn `test_s0_grounding.py::_graph`: nv001 gửi, B1 → B12 thật, VPN giả đọc `mock_services/seed.json`."""
    clock = FakeClock(at)
    gw = make_gateway(vpn_scripts(), clock=clock)  # type: ignore[arg-type]
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=_rag(), ad=FakeAd(ad_user("nv001")))
    h.identity.add_session("s-nv001", "nv001", expires_at=clock.now() + timedelta(days=365))
    h.tickets.register("t1", clock.now(), requester_id="nv001")
    values = (await h.runner.submit("t1", session_id="s-nv001", redacted_request=text)).values
    return h, cast(dict[str, Any], values)


def _e5_no_approval_no_write(h: GraphHarness, v: dict[str, Any]) -> None:
    got = (v.get("status"), v.get("exit_code"), v.get("escalation_reason_detail"))
    assert got == (S_ESCALATED, "E5", "llm_layer_disabled"), (got, h.audit.events("t1"))
    assert ("B13/B14", "llm_layer_disabled") in h.audit.events("t1")
    assert not [e for e in h.audit.events("t1") if e[0] == "B15"]  # không vào B15
    assert h.approvals.count("t1") == 0 and h.approvals.notified == []  # 0 phiếu
    assert h.executor.calls["t1"] == 0  # 0 lời gọi ghi
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E5", "llm_layer_disabled")


@pytest.mark.asyncio
async def test_x5_graph_other_persons_device_at_20h_e5_no_approval() -> None:
    """x5 (bảng 3.2) / P7: nv001 xin gia hạn LAP-0417 (máy đã đăng ký của nv002) lúc 20:00 → không luật nào (R18 nay đòi chủ máy)
    → E5 `llm_layer_disabled`, 0 phiếu, 0 lời gọi ghi (3h: R18 → phiếu duyệt — G4-16)."""
    h, v = await _graph(NGOAI_GIO.astimezone(UTC), "gia hạn VPN cho máy LAP-0417")
    facts = v["intended_action"].facts
    assert (facts["device_registered"], facts["device_owner_is_requester"]) == (True, False)
    _e5_no_approval_no_write(h, v)


@pytest.mark.asyncio
async def test_x6_graph_nonexistent_device_e5_no_approval() -> None:
    """x6 (bảng 3.2, h14 mới) / P7: nv001 xin gia hạn LAP-9999 (không tồn tại) trong giờ → R17 nay đòi chủ máy → không luật nào
    → E5 `llm_layer_disabled`, 0 phiếu, 0 lời gọi ghi (3h: R17 → phiếu duyệt).
    Q2 (ĐP 09/11 điểm 1): mã máy nêu ngay câu đầu mà B6 tra ra 404 → B11 hỏi lại mã MỘT lần (0 Action, 0 phiếu, 0 ghi); người dùng
    gửi lại đúng LAP-9999 → máy này B6 không tra → luồng cũ tới B12 như trên (x6 vẫn được kiểm qua đồ thị)."""
    h, v = await _graph(TRONG_GIO.astimezone(UTC), "gia hạn VPN cho máy LAP-9999")
    assert (v["status"], v.get("intended_action")) == (S_CLARIFYING, None)
    assert [t for _, t, n in h.notifier.sent if n == "answer"] == [device_not_found_question("LAP-9999")]
    assert h.approvals.count("t1") == 0 and h.executor.calls["t1"] == 0
    v = cast(dict[str, Any], (await deliver_event(h.runner, "t1", S_CLARIFYING,
                                                  {"kind": "user_reply", "text": "LAP-9999"})).values)  # fmt: skip
    facts = v["intended_action"].facts
    assert facts["device_registered"] is False and facts.get("device_owner_is_requester") is not True
    _e5_no_approval_no_write(h, v)
