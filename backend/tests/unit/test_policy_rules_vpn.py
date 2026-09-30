"""h-rule — luật VPN R16–R20 của M5 (phase3 11.2, 11.3; cổng C5 mục 1.3; chốt P3 của lời giao 3h mục 4).

Kỳ vọng chép từ bảng 11.2, không suy từ code. Quy ước route (11.2/11.3): AUTO ↔ `decision == "allow"`,
HITL ↔ `decision == "approval_required"`, "không luật nào → E5" ↔ `matched is False` và `all_matched == []`.
Việc B12 đổi verdict thành route/E5 không test ở đây.

Ba nhóm:
1. `BANG_11_2` — 9 dòng bảng kết quả mong đợi + 2 dòng P3, đi đường thật của M5: state → `build_ctx` → `evaluate`.
2. `LUAT_C5` — mỗi luật R16–R20 có ca khớp + ca suýt khớp, gọi thẳng `evaluate` với `RiskContext` dựng tay (tách từng
   điều kiện, kể cả tổ hợp `build_ctx` không sinh ra — để bắt M-3h-1 bỏ điều kiện owner, M-3h-2 thiếu fact → đúng).
3. P3 + giờ — `build_ctx` tính `target_is_other` và `within_business_hours`.

Người/máy theo `mock_services/seed.json` (bảng 3.7); facts theo nguồn ở bảng FACT_KEYS mục 3.2.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from zoneinfo import ZoneInfo

import pytest
from app.domain.action import Action, FactValue
from app.domain.context import RequesterContext
from app.domain.facts import check_facts
from app.risk.context import build_ctx
from app.risk.models import RiskContext, RuleVerdict
from app.risk.policy_engine import evaluate
from app.settings import get_action_metadata, get_policy

REPO = Path(__file__).resolve().parents[3]
VN = ZoneInfo("Asia/Ho_Chi_Minh")
TRONG_GIO = datetime(2026, 9, 29, 10, 0, tzinfo=VN)  # thứ Ba 29/09/2026, 10:00 giờ VN
NGOAI_GIO = datetime(2026, 9, 29, 20, 0, tzinfo=VN)  # cùng ngày, 20:00 giờ VN
META = get_action_metadata().of("vpn")

RENEW, REISSUE, CHECK = "renew_vpn_cert", "reissue_vpn_access", "check_vpn_status"
AUTO, HITL = "allow", "approval_required"
E5 = None  # không luật nào khớp → decision None (B12 mới đổi thành E5 llm_layer_disabled)

# ---- Người gửi (seed.json, bảng 3.7) -----------------------------------------------------------------------------

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

# ---- Facts như B6 đọc từ tool (mục 3.2) trên seed ------------------------------------------------------------------

# nv001 / LAP-0342: đã đăng ký, của nv001; cert VPN-2025-0342 hết hạn 3 ngày; kết nối gần nhất lỗi CERT_EXPIRED.
F_NV001_LAP0342: dict[str, FactValue] = {
    "device_count": 1, "has_registered_device": True, "device_registered": True, "device_owner_is_requester": True,
    "cert_status": "expired", "cert_days_to_expiry": -3, "last_connection_ok": False,
}  # fmt: skip
# nv003 / LAP-0501: đã đăng ký, cert còn 5 ngày; seed không có kết nối nào của nv003 → không đặt last_connection_ok.
F_NV003_LAP0501: dict[str, FactValue] = {
    "device_count": 1, "has_registered_device": True, "device_registered": True, "device_owner_is_requester": True,
    "cert_status": "valid", "cert_days_to_expiry": 5,
}  # fmt: skip
# nv002 / PC-0977: của nv002 nhưng CHƯA đăng ký, không có cert; kết nối gần nhất (PC-0977, 0,3 ngày) lỗi.
F_NV002_PC0977: dict[str, FactValue] = {
    "device_count": 2, "has_registered_device": True, "device_registered": False, "device_owner_is_requester": True,
    "cert_status": "none", "last_connection_ok": False,
}  # fmt: skip
# G-02: nv001 hỏi LAP-0417 (máy của nv002) — máy tồn tại, đã đăng ký, không phải của người gửi.
F_NV001_LAP0417: dict[str, FactValue] = {"device_registered": True, "device_owner_is_requester": False}


def _bo(facts: dict[str, FactValue], key: str) -> dict[str, FactValue]:
    return {k: v for k, v in facts.items() if k != key}


def _action(action_type: str, device_id: str, requested_for: str, facts: dict[str, FactValue]) -> Action:
    """Dựng `Action` như `build_action`: thuộc tính rủi ro lấy từ `config/action_metadata.yaml`."""
    check_facts(facts)  # tự kiểm ca test: chỉ key thuộc FACT_KEYS, đúng kiểu
    m = META[action_type]
    return Action(
        type=action_type, target=f"device:{device_id}", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": device_id}, facts=dict(facts),
    )  # fmt: skip


def _assert_verdict(v: RuleVerdict, *, khop: frozenset[str], thang: frozenset[str], decision: str | None) -> None:
    assert isinstance(v, RuleVerdict)
    assert v.matched is bool(khop)
    assert v.decision == decision
    assert set(v.all_matched) == khop
    if khop:
        assert v.rule_id in thang
    else:
        assert v.rule_id is None


def _ids(s: str) -> frozenset[str]:
    return frozenset(s.split())


# ---- 1. h-rule: bảng 11.2 + dòng P3, qua build_ctx ----------------------------------------------------------------


@dataclass(frozen=True)
class Ca:
    requester: RequesterContext
    action_type: str
    device_id: str
    facts: dict[str, FactValue]
    now: datetime
    khop: frozenset[str]  # all_matched mong đợi
    thang: frozenset[str]  # rule_id phải thuộc tập này (rỗng khi không luật nào)
    decision: str | None
    requested_for: str | None = None  # None = chính người gửi (như build_action)
    ctx_flags: dict[str, bool] = field(default_factory=lambda: {"target_is_other": False})


def _ca(
    requester: RequesterContext, action_type: str, device_id: str, facts: dict[str, FactValue], now: datetime, *,
    khop: str, thang: str = "", decision: str | None, requested_for: str | None = None,
    ctx_flags: dict[str, bool] | None = None,
) -> Ca:  # fmt: skip
    return Ca(
        requester=requester, action_type=action_type, device_id=device_id, facts=facts, now=now, khop=_ids(khop),
        thang=_ids(thang or khop), decision=decision, requested_for=requested_for,
        ctx_flags=ctx_flags if ctx_flags is not None else {"target_is_other": False},
    )  # fmt: skip


# fmt: off
BANG_11_2 = [
    pytest.param(
        _ca(NV001, RENEW, "LAP-0342", F_NV001_LAP0342, TRONG_GIO, khop="R20", decision=AUTO),
        id="tc02-renew-registered-owner-trong-gio-active-R20-AUTO",
    ),
    pytest.param(
        _ca(NV001, RENEW, "LAP-0342", F_NV001_LAP0342, NGOAI_GIO, khop="R20 R18", thang="R18", decision=HITL),
        id="ngoai-gio-20h-R20+R18-HITL-R18",
    ),
    pytest.param(
        _ca(NV003, RENEW, "LAP-0501", F_NV003_LAP0501, TRONG_GIO, khop="R20 R19", thang="R19", decision=HITL),
        id="thu-viec-probation-R20+R19-HITL-R19",
    ),
    pytest.param(
        _ca(NV002, REISSUE, "PC-0977", F_NV002_PC0977, NGOAI_GIO, khop="R17 R18", decision=HITL),
        id="tc09-nv002-reissue-PC0977-chua-dang-ky-20h-R17+R18-HITL",
    ),
    pytest.param(
        _ca(NV001, REISSUE, "LAP-0342", F_NV001_LAP0342, TRONG_GIO, khop="R20", decision=AUTO),
        id="reissue-cua-minh-nv001-LAP0342-R20-AUTO",
    ),
    pytest.param(
        _ca(NV001, RENEW, "LAP-0417", F_NV001_LAP0417, TRONG_GIO, khop="", decision=E5),
        id="may-nguoi-khac-owner-false-khong-luat-E5",
    ),
    pytest.param(
        _ca(NV001, RENEW, "LAP-0342", _bo(F_NV001_LAP0342, "device_registered"), TRONG_GIO, khop="", decision=E5),
        id="thieu-fact-device_registered-khong-luat-E5",
    ),
    pytest.param(
        _ca(NV001, CHECK, "LAP-0342", F_NV001_LAP0342, TRONG_GIO, khop="R16", decision=AUTO),
        id="R16-check-target-khong-phai-nguoi-khac-AUTO",
    ),
    pytest.param(
        _ca(NV001, CHECK, "LAP-0417", F_NV001_LAP0417, TRONG_GIO, khop="", decision=E5,
            ctx_flags={"target_is_other": True}),
        id="R16-suyt-khop-target_is_other-true-E5",
    ),
    # Dòng P3 (chốt Tuấn Anh): cờ B6 báo False nhưng owner=false → target_is_other TRUE → không luật nào.
    pytest.param(
        _ca(NV001, CHECK, "LAP-0417", F_NV001_LAP0417, TRONG_GIO, khop="", decision=E5,
            ctx_flags={"target_is_other": False}),
        id="P3-check-may-nguoi-khac-co-false-E5",
    ),
    pytest.param(
        _ca(NV001, CHECK, "LAP-0342", _bo(F_NV001_LAP0342, "device_owner_is_requester"), TRONG_GIO, khop="",
            decision=E5),
        id="P3-check-cua-minh-thieu-owner-E5",
    ),
]
# fmt: on

# Suýt khớp chỉ đạt được qua build_ctx: requested_for là người khác (vế đầu của P3), facts đều "của mình".
SUYT_QUA_BUILD_CTX = [
    pytest.param(
        _ca(NV001, RENEW, "LAP-0342", F_NV001_LAP0342, TRONG_GIO, khop="", decision=E5, requested_for="nv002"),
        id="R20-suyt-requested_for-nguoi-khac-E5",
    ),
    pytest.param(
        _ca(NV001, CHECK, "LAP-0342", F_NV001_LAP0342, TRONG_GIO, khop="", decision=E5, requested_for="nv002"),
        id="R16-suyt-requested_for-nguoi-khac-E5",
    ),
]


def _qua_build_ctx(ca: Ca) -> tuple[RiskContext, RuleVerdict]:
    action = _action(ca.action_type, ca.device_id, ca.requested_for or ca.requester.user_id, ca.facts)
    state = {"intended_action": action, "requester_context": ca.requester, "ctx_flags": dict(ca.ctx_flags)}
    ctx = build_ctx(state, ca.now, get_policy().business_hours)
    return ctx, evaluate(action, ctx)


@pytest.mark.parametrize("ca", BANG_11_2)
def test_hrule_bang_11_2(ca: Ca) -> None:
    """h-rule (phase3 11.2, mỗi dòng bảng một test + dòng P3): state → build_ctx → evaluate đúng luật, đúng route."""
    _, verdict = _qua_build_ctx(ca)
    _assert_verdict(verdict, khop=ca.khop, thang=ca.thang, decision=ca.decision)


@pytest.mark.parametrize("ca", SUYT_QUA_BUILD_CTX)
def test_hrule_c5_suyt_khop_requested_for_nguoi_khac(ca: Ca) -> None:
    """C5 (phase3 1.3) + P3: R20/R16 suýt khớp vì requested_for ≠ người gửi (facts đều của mình) → không luật nào."""
    ctx, verdict = _qua_build_ctx(ca)
    assert ctx.target_is_other is True
    _assert_verdict(verdict, khop=ca.khop, thang=ca.thang, decision=ca.decision)


def test_hrule_bang_du_dong() -> None:
    """Quy ước 3.9: bảng tham số hoá không rỗng — đủ 9 dòng bảng 11.2 + 2 dòng P3, id không trùng."""
    ids = [p.id for p in BANG_11_2]
    assert len(ids) == len(set(ids)) >= 11
    assert sum(1 for i in ids if i and i.startswith("P3-")) == 2


# ---- 2. C5: mỗi luật một ca khớp + ca suýt khớp, gọi thẳng evaluate ----------------------------------------------

REG_OWN: dict[str, FactValue] = {"device_registered": True, "device_owner_is_requester": True}
REG_OTHER: dict[str, FactValue] = {"device_registered": True, "device_owner_is_requester": False}
UNREG_OWN: dict[str, FactValue] = {"device_registered": False, "device_owner_is_requester": True}


@dataclass(frozen=True)
class CaLuat:
    luat: str
    loai: Literal["khop", "suyt"]
    action_type: str
    facts: dict[str, FactValue]
    khop: frozenset[str]
    thang: frozenset[str]
    decision: str | None
    requester: RequesterContext = NV001
    trong_gio: bool = True
    target_is_other: bool = False


def _cl(
    luat: str, loai: Literal["khop", "suyt"], action_type: str, facts: dict[str, FactValue], *, khop: str,
    decision: str | None, requester: RequesterContext = NV001, trong_gio: bool = True, target_is_other: bool = False,
) -> CaLuat:  # fmt: skip
    return CaLuat(
        luat=luat, loai=loai, action_type=action_type, facts=facts, khop=_ids(khop), thang=_ids(khop),
        decision=decision, requester=requester, trong_gio=trong_gio, target_is_other=target_is_other,
    )  # fmt: skip


# fmt: off
LUAT_C5 = [
    # R16 — allow check_vpn_status khi ctx.target_is_other is_false.
    pytest.param(_cl("R16", "khop", CHECK, REG_OWN, khop="R16", decision=AUTO), id="R16-khop"),
    pytest.param(_cl("R16", "suyt", CHECK, REG_OWN, khop="", decision=E5, target_is_other=True),
                 id="R16-suyt-target_is_other-true"),
    # R17 — approval_required renew/reissue khi action.facts.device_registered is_false.
    pytest.param(_cl("R17", "khop", RENEW, UNREG_OWN, khop="R17", decision=HITL), id="R17-khop-renew"),
    pytest.param(_cl("R17", "khop", REISSUE, UNREG_OWN, khop="R17", decision=HITL), id="R17-khop-reissue"),
    pytest.param(_cl("R17", "suyt", RENEW, REG_OWN, khop="R20", decision=AUTO), id="R17-suyt-registered-true"),
    pytest.param(_cl("R17", "suyt", RENEW, _bo(UNREG_OWN, "device_registered"), khop="", decision=E5),
                 id="R17-suyt-thieu-device_registered"),
    pytest.param(_cl("R17", "suyt", CHECK, UNREG_OWN, khop="R16", decision=AUTO), id="R17-suyt-action-check"),
    # R18 — approval_required renew/reissue ngoài giờ. owner=false để R20 không chen vào, chỉ còn R18.
    pytest.param(_cl("R18", "khop", RENEW, REG_OTHER, khop="R18", decision=HITL, trong_gio=False,
                     target_is_other=True), id="R18-khop-renew-20h"),
    pytest.param(_cl("R18", "khop", REISSUE, REG_OTHER, khop="R18", decision=HITL, trong_gio=False,
                     target_is_other=True), id="R18-khop-reissue-20h"),
    pytest.param(_cl("R18", "suyt", RENEW, REG_OTHER, khop="", decision=E5, target_is_other=True),
                 id="R18-suyt-trong-gio"),
    pytest.param(_cl("R18", "suyt", CHECK, REG_OWN, khop="R16", decision=AUTO, trong_gio=False),
                 id="R18-suyt-action-check-20h"),
    # R19 — approval_required renew/reissue khi requester.employment_status == probation.
    pytest.param(_cl("R19", "khop", RENEW, REG_OTHER, khop="R19", decision=HITL, requester=NV003,
                     target_is_other=True), id="R19-khop-probation"),
    pytest.param(_cl("R19", "suyt", RENEW, REG_OTHER, khop="", decision=E5, target_is_other=True),
                 id="R19-suyt-active"),
    pytest.param(_cl("R19", "suyt", CHECK, REG_OWN, khop="R16", decision=AUTO, requester=NV003),
                 id="R19-suyt-action-check-probation"),
    # R20 — allow renew/reissue khi registered is_true, owner is_true, target_is_other is_false.
    pytest.param(_cl("R20", "khop", RENEW, REG_OWN, khop="R20", decision=AUTO), id="R20-khop-renew"),
    pytest.param(_cl("R20", "khop", REISSUE, REG_OWN, khop="R20", decision=AUTO), id="R20-khop-reissue"),
    pytest.param(_cl("R20", "suyt", RENEW, REG_OTHER, khop="", decision=E5),  # M-3h-1: chỉ điều kiện owner sai
                 id="R20-suyt-owner-false"),
    pytest.param(_cl("R20", "suyt", RENEW, UNREG_OWN, khop="R17", decision=HITL), id="R20-suyt-registered-false-R17"),
    pytest.param(_cl("R20", "suyt", RENEW, REG_OWN, khop="", decision=E5, target_is_other=True),
                 id="R20-suyt-target_is_other-true"),
    pytest.param(_cl("R20", "suyt", RENEW, _bo(REG_OWN, "device_owner_is_requester"), khop="", decision=E5),
                 id="R20-suyt-thieu-owner"),  # M-3h-2
]
# fmt: on


def _ctx_tay(ca: CaLuat, action: Action) -> RiskContext:
    return RiskContext(
        requester=ca.requester, facts=dict(action.facts), now=TRONG_GIO if ca.trong_gio else NGOAI_GIO,
        within_business_hours=ca.trong_gio, target_is_other=ca.target_is_other,
    )  # fmt: skip


@pytest.mark.parametrize("ca", LUAT_C5)
def test_hrule_c5_luat_khop_va_suyt_khop(ca: CaLuat) -> None:
    """C5 (phase3 1.3, luật 11.2): mỗi luật R16–R20 có ca khớp + ca suýt khớp; thiếu fact → điều kiện sai [Chốt]."""
    action = _action(ca.action_type, "LAP-0342", ca.requester.user_id, ca.facts)
    verdict = evaluate(action, _ctx_tay(ca, action))
    _assert_verdict(verdict, khop=ca.khop, thang=ca.thang, decision=ca.decision)
    assert (ca.luat in verdict.all_matched) is (ca.loai == "khop")


def test_hrule_c5_moi_luat_du_ca() -> None:
    """Quy ước 3.9 + C5: bảng không rỗng; R16–R20 mỗi luật ≥ 1 ca khớp và ≥ 1 ca suýt khớp."""
    cases = [cast(CaLuat, p.values[0]) for p in LUAT_C5]
    assert len(cases) >= 10
    for luat in ("R16", "R17", "R18", "R19", "R20"):
        assert any(c.luat == luat and c.loai == "khop" and luat in c.khop for c in cases), luat
        assert any(c.luat == luat and c.loai == "suyt" and luat not in c.khop for c in cases), luat


# ---- 3. P3 + giờ hành chính trong build_ctx ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested_for", "facts", "mong_doi"),
    [
        pytest.param("nv001", REG_OWN, False, id="cua-minh-owner-true"),
        pytest.param("nv001", REG_OTHER, True, id="owner-false"),
        pytest.param("nv001", _bo(REG_OWN, "device_owner_is_requester"), True, id="thieu-owner-tinh-true"),
        pytest.param("nv002", REG_OWN, True, id="requested_for-nguoi-khac"),
        pytest.param("nv002", REG_OTHER, True, id="ca-hai-ve"),
    ],
)
def test_hrule_p3_build_ctx_target_is_other(requested_for: str, facts: dict[str, FactValue], mong_doi: bool) -> None:
    """P3 (lời giao 3h mục 4): target_is_other = requested_for ≠ người gửi HOẶC device_owner_is_requester không phải
    True (thiếu cũng tính True); cờ ctx_flags B6 báo False không che được."""
    action = _action(CHECK, "LAP-0342", requested_for, facts)
    state = {"intended_action": action, "requester_context": NV001, "ctx_flags": {"target_is_other": False}}
    ctx = build_ctx(state, TRONG_GIO, get_policy().business_hours)
    assert ctx.target_is_other is mong_doi
    assert ctx.requester == NV001


@pytest.mark.parametrize(
    ("now", "mong_doi"),
    [
        pytest.param(TRONG_GIO, True, id="10h-vn"),
        pytest.param(TRONG_GIO.astimezone(UTC), True, id="03h-utc=10h-vn"),
        pytest.param(NGOAI_GIO, False, id="20h-vn"),
        pytest.param(NGOAI_GIO.astimezone(UTC), False, id="13h-utc=20h-vn"),
    ],
)
def test_hrule_build_ctx_gio_hanh_chinh(now: datetime, mong_doi: bool) -> None:
    """phase3 11.2 (time.within_business_hours: đổi now sang tz rồi so) + 11.3 (build_ctx đọc Clock được tiêm)."""
    action = _action(RENEW, "LAP-0342", "nv001", F_NV001_LAP0342)
    state = {"intended_action": action, "requester_context": NV001, "ctx_flags": {"target_is_other": False}}
    ctx = build_ctx(state, now, get_policy().business_hours)
    assert ctx.within_business_hours is mong_doi
    assert ctx.now == now


# ---- Cấu hình: config/policy.json đúng khối JSON ở 11.2 ------------------------------------------------------------

SPEC_11_2 = {
    "business_hours": {"tz": "Asia/Ho_Chi_Minh", "weekdays": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"},
    "rules": [
        {"id": "R16", "type": "allow", "intent": "vpn", "action": "check_vpn_status",
         "conditions": {"all": [{"fact": "ctx.target_is_other", "op": "is_false"}]},
         "description": "Kiểm tra trạng thái VPN của chính mình"},
        {"id": "R17", "type": "approval_required", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [{"fact": "action.facts.device_registered", "op": "is_false"}]},
         "description": "Thiết bị chưa đăng ký"},
        {"id": "R18", "type": "approval_required", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [{"fact": "time.within_business_hours", "op": "is_false"}]},
         "description": "Ngoài giờ hành chính"},
        {"id": "R19", "type": "approval_required", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [{"fact": "requester.employment_status", "op": "eq", "value": "probation"}]},
         "description": "Nhân viên chưa qua thử việc"},
        {"id": "R20", "type": "allow", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [
            {"fact": "action.facts.device_registered", "op": "is_true"},
            {"fact": "action.facts.device_owner_is_requester", "op": "is_true"},
            {"fact": "ctx.target_is_other", "op": "is_false"}]},
         "description": "Cấp lại cho thiết bị đã đăng ký của chính người gửi"},
    ],
}  # fmt: skip


def test_hrule_policy_json_khop_spec_11_2() -> None:
    """phase3 11.2: config/policy.json có đúng business_hours và 5 luật R16–R20 như khối JSON của spec."""
    raw = json.loads((REPO / "config" / "policy.json").read_text(encoding="utf-8"))
    assert raw["business_hours"] == SPEC_11_2["business_hours"]
    assert raw["rules"] == SPEC_11_2["rules"]
    assert len(get_policy().rules) == 5
