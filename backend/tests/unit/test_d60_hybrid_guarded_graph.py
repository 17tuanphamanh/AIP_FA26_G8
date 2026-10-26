"""D-60 P1.7 — `hybrid_guarded` lần đầu chạy lúc vận hành (không EVAL_MODE): graph THẬT (`GraphHarness(nodes="real")`, B1 → … → B12
→ B15/B17/B20 thật), LLM giả (ScriptedLLM qua gateway THẬT + `LlmRiskEstimator`), chiến lược CHỤP trên ticket (`tickets.strategies`).

Câu: nv001 "gia hạn VPN cho máy LAP-0342" (máy của chính mình, đã đăng ký — seed mock). Trong giờ → R20 `allow`; 20:00 → R18
`approval_required`. Ngưỡng = `policy.json` (0,25; 0,75), calibrator Platt a=1, b=0 (≈ đồng nhất) để thấy LLM NÂNG mức.

(a) allow + LLM p = 0,5 → HITL (B15, phiếu chờ duyệt, 0 lời gọi ghi); p = 0,9 → chuyển L2 (E5 `llm_high_risk`).
(b) allow + LLM lỗi (`Unavailable`, `Timeout`, JSON sai) → hành vi CÓ SẴN của B12 (không đổi logic): E5 `llm_layer_disabled`, không crash,
    có dòng audit. Test ghi lại NGUYÊN hành vi: exit_code, route của `risk`, final_state, sự kiện audit (MẪU B dán lại).
(c) approval_required (R18, graph thật) → giữ route luật HITL, 0 lời gọi LLM `b14_*`; deny (R12 — chỉ có ở intent access, không có
    luật deny cho VPN) chạy ở mức node B12 thật trên hành động access dựng tay (khuôn `test_b17_llm_auto._access_deny`) → giữ route
    luật ESCALATE_L2, 0 lời gọi estimator.
"""

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from app.core.clock import FakeClock
from app.domain.states import S_ESCALATED, S_PENDING_APPROVAL
from app.domain.ticket_state import ChunkRef
from app.graph.fakes import NodeDeps
from app.llm.providers.scripted import (
    BadJSON,
    Reply,
    Script,
    Step,
    Timeout,
    Unavailable,
)
from app.rag.models import RetrievalResult
from app.risk.calibrator import Calibrator, CalibratorParams, FitInfo
from app.risk.estimator import LlmRiskEstimator
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts

VN = ZoneInfo("Asia/Ho_Chi_Minh")
TRONG_GIO = datetime(2026, 9, 29, 10, 0, tzinfo=VN).astimezone(UTC)  # thứ Ba 10:00 giờ VN → R20 allow
NGOAI_GIO = datetime(2026, 9, 29, 20, 0, tzinfo=VN).astimezone(UTC)  # 20:00 → R18 approval_required
TEXT = "gia hạn VPN cho máy LAP-0342"
CAL = Calibrator(CalibratorParams(
    version="platt-20261027-0123abcd", method="platt", a=1.0, b=0.0,
    fitted_on=FitInfo(split="calibration", n=40, n_pos=10, n_families=8, data_sha256="0" * 64),
    created_at=datetime(2026, 10, 27, tzinfo=UTC),
))  # fmt: skip


@dataclass
class GuardedHarness(GraphHarness):
    """GraphHarness + estimator THẬT trên gateway + calibrator (như wiring 6C; `GraphHarness.deps` để `DisabledEstimator`)."""

    gateway: Gateway | None = None
    calibrator: Calibrator | None = None

    def deps(self) -> NodeDeps:
        assert self.gateway is not None
        estimator = LlmRiskEstimator(self.gateway.client, p_method="self_report", eval_mode=False)
        return dataclasses.replace(super().deps(), estimator=estimator, calibrator=self.calibrator)


def _rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-VPN-004", version=1, seq=0, title="T", heading_path="H", score=0.99, excerpt="x")
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64, intent_filter_fallback=False,
                                          fallback_tried=False, retries=0, query_truncated=False))  # fmt: skip


def _estimate(p: float) -> Script:
    return lambda _v: Reply({"prob_needs_human": p, "factors": ["routine_low_risk"], "rationale": "x"})


def _always(step: Step) -> Script:
    return lambda _v: step


async def _graph(at: datetime, b14: Script, *, strategy: str = "hybrid_guarded") -> tuple[GuardedHarness, dict[str, Any], Gateway]:
    clock = FakeClock(at)
    gw = make_gateway(vpn_scripts(b14_risk_estimate=b14), clock=clock)  # type: ignore[arg-type]
    h = GuardedHarness(clock=clock, nodes="real", llm=gw.client, rag=_rag(), ad=FakeAd(ad_user("nv001")), gateway=gw,
                       calibrator=CAL)  # fmt: skip
    h.identity.add_session("s-nv001", "nv001", expires_at=clock.now() + timedelta(days=365))
    h.tickets.register("t1", clock.now(), requester_id="nv001")
    h.tickets.strategies["t1"] = strategy  # D-60: chụp lúc tạo (API); vận hành, không EVAL_MODE
    values = (await h.runner.submit("t1", session_id="s-nv001", redacted_request=TEXT)).values
    return h, cast(dict[str, Any], values), gw


def _point4(h: GraphHarness) -> dict[str, Any]:
    rows = [r for r in h.audit.rows if r["ticket_id"] == "t1" and r["step"] == "B13/B14"]
    assert len(rows) == 1, h.audit.events("t1")
    return rows[0]


def _b14(gw: Gateway) -> list[str]:
    return [c.prompt_id for c in gw.llm.calls if c.prompt_id.startswith("b14")]


def behaviour(h: GraphHarness, v: dict[str, Any]) -> dict[str, Any]:
    """Hành vi thực tế để dán nguyên văn vào MẪU B."""
    final = h.tickets.final("t1")
    risk = v.get("risk")
    return {
        "status": v.get("status"), "exit_code": v.get("exit_code"), "escalation_reason_detail": v.get("escalation_reason_detail"),
        "risk.route": getattr(risk, "route", None) if risk is not None else None,
        "risk.decided_by": getattr(risk, "decided_by", None) if risk is not None else None,
        "final_state": final.final_state if final else None,
        "audit": [list(e) for e in h.audit.events("t1")],
    }  # fmt: skip


# ---- (a) allow + LLM nâng mức -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_allow_rule_llm_raises_to_hitl() -> None:
    """(a) R20 allow + p = 0,5 (giữa 0,25 và 0,75) → HITL: phiếu chờ duyệt, 0 lời gọi ghi; điểm 4 `decided_by=llm`,
    `policy_decision=allow`, `matched_rule_id=R20`, `detail.strategy=hybrid_guarded` (lúc vận hành)."""
    h, v, gw = await _graph(TRONG_GIO, _estimate(0.5))
    assert v["status"] == S_PENDING_APPROVAL, behaviour(h, v)
    assert _b14(gw) == ["b14_risk_estimate"]
    row = _point4(h)
    assert (row["decided_by"], row["policy_decision"], row["matched_rule_id"]) == ("llm", "allow", "R20")
    assert (row["detail"]["route"], row["detail"]["strategy"]) == ("HITL", "hybrid_guarded")
    assert row["reason"].startswith("Luật R20 cho phép; kiểm tra bổ sung bằng mô hình:")
    assert h.approvals.count("t1") == 1
    assert h.executor.calls["t1"] == 0


@pytest.mark.asyncio
async def test_a_allow_rule_llm_raises_to_l2() -> None:
    """(a) R20 allow + p = 0,9 (> 0,75) → chuyển L2 (E5 `llm_high_risk`), 0 phiếu, 0 lời gọi ghi."""
    h, v, _ = await _graph(TRONG_GIO, _estimate(0.9))
    assert (v["status"], v["exit_code"], v.get("escalation_reason_detail")) == (S_ESCALATED, "E5", "llm_high_risk"), behaviour(h, v)
    assert _point4(h)["detail"]["route"] == "ESCALATE_L2"
    assert h.approvals.count("t1") == 0 and h.executor.calls["t1"] == 0


@pytest.mark.asyncio
async def test_a_allow_rule_llm_low_keeps_auto_floor() -> None:
    """Đối chứng (a): p = 0,05 → AUTO giữ sàn của luật allow (B17 thực thi, 1 lời gọi ghi) — LLM chỉ NÂNG mức, không hạ."""
    h, v, _ = await _graph(TRONG_GIO, _estimate(0.05))
    row = _point4(h)
    assert (row["decided_by"], row["detail"]["route"], row["detail"]["strategy"]) == ("llm", "AUTO", "hybrid_guarded")
    assert h.executor.calls["t1"] == 1, behaviour(h, v)


# ---- (b) allow + LLM lỗi / hết thời gian --------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("step", [Unavailable(), Timeout(), BadJSON("{khong-phai-json")], ids=["mat-ket-noi", "het-thoi-gian", "json-sai"])
async def test_b_allow_rule_llm_error_existing_behaviour(step: Step, capsys: pytest.CaptureFixture[str]) -> None:
    """(b) R20 allow + LLM lỗi → hành vi CÓ SẴN của B12 (bắt `LLMUnavailable`/`LLMSchemaError`/`LLMBudgetExceeded` TRƯỚC `decide`):
    E5 `llm_layer_disabled`, `risk.route = ESCALATE_L2`, `decided_by=llm`, 0 phiếu, 0 lời gọi ghi; B20 ghi `final_state` S_ESCALATED;
    không crash (không E9); có dòng audit `B13/B14 llm_layer_disabled` mang `detail.strategy=hybrid_guarded` + `estimator_error`."""
    h, v, _ = await _graph(TRONG_GIO, _always(step))
    got = behaviour(h, v)
    print(f"\nHANH_VI_B {type(step).__name__}: {got}")  # MẪU B — `pytest -s -k test_b_` để in
    assert (got["status"], got["exit_code"], got["escalation_reason_detail"]) == (S_ESCALATED, "E5", "llm_layer_disabled"), got
    assert (got["risk.route"], got["risk.decided_by"]) == ("ESCALATE_L2", "llm")
    assert got["final_state"] == S_ESCALATED
    assert ["B13/B14", "llm_layer_disabled"] in got["audit"]
    assert not [e for e in got["audit"] if e[1] == "boundary_error" or e[0] == "B15"]
    row = _point4(h)
    assert row["event"] == "llm_layer_disabled"
    assert row["detail"]["strategy"] == "hybrid_guarded" and row["detail"]["estimator_error"]
    assert h.approvals.count("t1") == 0 and h.executor.calls["t1"] == 0
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E5", "llm_layer_disabled")


# ---- (c) approval_required / deny: giữ route luật, 0 lời gọi LLM ---------------------------------------------------------


@pytest.mark.asyncio
async def test_c_approval_required_keeps_rule_route_no_llm() -> None:
    """(c) R18 (20:00) approval_required → HITL theo luật (`decided_by=rule`), 0 lời gọi `b14_*`, phiếu chờ duyệt."""
    h, v, gw = await _graph(NGOAI_GIO, _estimate(0.05))
    assert v["status"] == S_PENDING_APPROVAL, behaviour(h, v)
    assert _b14(gw) == []
    row = _point4(h)
    assert (row["decided_by"], row["policy_decision"], row["matched_rule_id"]) == ("rule", "approval_required", "R18")
    assert (row["detail"]["route"], row["detail"]["strategy"]) == ("HITL", "hybrid_guarded")


@pytest.mark.asyncio
async def test_c_deny_keeps_rule_route_no_llm() -> None:
    """(c) R12 deny (access — không có luật deny cho VPN, nên ở mức node B12 thật trên hành động dựng tay, khuôn
    `test_b17_llm_auto`): `hybrid_guarded` lúc vận hành → giữ route luật ESCALATE_L2 (E5), `decided_by=rule`, 0 lời gọi estimator,
    0 lời gọi `b14_*`; `detail.strategy=hybrid_guarded`."""
    from tests.fakes.risk_estimator import FakeRiskEstimator
    from tests.unit.test_b17_llm_auto import (
        IN_HOURS,
        Env,
        _access_deny,
        _b12_state,
        _est,
    )

    env = Env(IN_HOURS)
    fake = FakeRiskEstimator(_est(0.05))
    out = await env.b12(_b12_state(_access_deny(), other=True), strategy="hybrid_guarded", eval_mode=False, estimator=fake)
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E5")
    assert fake.calls == [] and env.b14_calls() == []
    [row] = env.rows("risk_decided")
    assert (row["decided_by"], row["policy_decision"], row["matched_rule_id"]) == ("rule", "deny", "R12")
    assert (row["detail"]["route"], row["detail"]["strategy"]) == ("ESCALATE_L2", "hybrid_guarded")
