"""Hạn cho cả lượt — hành vi TỪNG điểm gọi ra ngoài (phase3 mục 9.0; PLAN-3f S0, chốt Q-3f-2).

Mỗi lớp: timeout gửi đi ≤ phần còn lại − biên (đo ở NƠI NHẬN: handler tool, `FakeMlService.seen`, `ScriptedLLM.calls`),
không ngủ backoff vượt phần còn lại, còn lại ≤ biên → `TurnBudgetExceeded` TRƯỚC khi gửi, ngoài lượt → không cắt.
Boundary: node không tự bắt (B1, B8) → E2 `turn_budget_exceeded` (không E9 — M-3f-11); B2 bắt riêng giữ `security_flag`.
Lượt xấu nhất qua graph: f19 `test_turn_worst_case.py`.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.core.turn_budget import (
    TurnBudgetExceeded,
    TurnDeadline,
    bind_turn_deadline,
    cap_timeout,
    check_sleep,
    window,
)
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b08_retrieve
from app.llm import LLMUnavailable
from app.llm.providers.scripted import Reply, Timeout
from app.llm.schemas import ClassifyOut
from app.rag.models import RetrievalQuery, RetrievalSystemError
from app.tools.breaker import BreakerBoard, CircuitBreaker
from app.tools.models import UserDeviceRequiredIn, UserIn
from app.tools.registry import ToolRegistry
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.identity import SESSION, ad_user
from tests.fakes.llm import make_gateway
from tests.unit.test_rag_retriever import _cfg, _ctx, _retriever, _spy

MARGIN = 2.0
B03_VARS = {"redacted_request": "vpn lỗi", "recent_messages": [], "label_hint": None}
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "bình thường"}


@contextmanager
def turn(clock: FakeClock, usable_s: float) -> Iterator[TurnDeadline]:
    """Lượt có `usable_s` giây dùng được cho lời gọi ra ngoài (= còn lại − biên)."""
    with bind_turn_deadline(TurnDeadline(clock.now() + timedelta(seconds=usable_s + MARGIN), MARGIN)) as d:
        yield d


def usable_at(d: TurnDeadline, at: datetime) -> float:
    return (d.at - at).total_seconds() - d.margin_s


class SlowHandler:
    """Handler tool trên FakeClock: `latencies` giây mỗi lần (≥ timeout → tua đúng timeout rồi `ReadTimeout`)."""

    def __init__(self, clock: FakeClock, *latencies: float, result: object = ()) -> None:
        self.clock = clock
        self.latencies = list(latencies)
        self.result = list(result) if isinstance(result, tuple) else result
        self.seen: list[tuple[float, datetime]] = []

    async def __call__(self, inp: Any, timeout: float) -> object:
        self.seen.append((timeout, self.clock.now()))
        lat = self.latencies.pop(0) if self.latencies else 0.0
        if lat >= timeout:
            self.clock.advance(timedelta(seconds=timeout))
            raise httpx.ReadTimeout("chậm quá timeout")
        self.clock.advance(timedelta(seconds=lat))
        return self.result


def _registry(clock: FakeClock, handlers: dict[str, Any], *, threshold: int = 5) -> tuple[ToolRegistry, BreakerBoard]:
    board = BreakerBoard(clock, failure_threshold=threshold, window_seconds=60, open_seconds=30)
    return ToolRegistry(handlers, breakers=board, clock=clock), board


# ---- core.turn_budget ---------------------------------------------------------------------------------------------


def test_helpers_outside_turn_do_not_cap() -> None:
    clock = FakeClock()
    assert cap_timeout(5.0, clock, what="x") == 5.0
    check_sleep(1e9, clock, what="x")  # không ném
    assert window(50.0, clock, what="x") == (50.0, False)


def test_helpers_inside_turn() -> None:
    clock = FakeClock()
    with turn(clock, 3.0):
        assert cap_timeout(5.0, clock, what="x") == 3.0
        assert cap_timeout(2.0, clock, what="x") == 2.0
        with pytest.raises(TurnBudgetExceeded):
            cap_timeout(5.0, clock, what="x", full=True)  # ghi: không đủ trọn timeout → không gửi
        assert window(50.0, clock, what="x") == (3.0, True)
        assert window(1.0, clock, what="x") == (1.0, False)
        check_sleep(2.9, clock, what="x")
        with pytest.raises(TurnBudgetExceeded):
            check_sleep(3.0, clock, what="x")
        clock.advance(timedelta(seconds=3))
        with pytest.raises(TurnBudgetExceeded, match="x: còn 0.0s"):
            cap_timeout(0.1, clock, what="x")


# ---- ToolRegistry (B1 AD, B6 tool VPN, B17 ghi) ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_read_caps_each_attempt_and_stops_before_useless_backoff() -> None:
    clock = FakeClock()
    handler = SlowHandler(clock, 99, 99, 99)
    reg, board = _registry(clock, {"check_last_connection": handler}, threshold=1)
    with turn(clock, 8.0) as d, pytest.raises(TurnBudgetExceeded):
        await reg.call("check_last_connection", UserIn(user_id="nv001"), caller_step="B6")
    assert [t for t, _ in handler.seen] == [5.0, 2.0]  # lần 2: min(5, 8−5−1) — backoff 2 s sau đó ≥ còn 0 → dừng
    assert all(t <= usable_at(d, at) + 1e-9 for t, at in handler.seen)
    assert clock.sleeps == [1.0]
    assert board["vpn"].state == "closed"  # threshold 1: một lỗi bị tính là mở — hết hạn lượt không tính


@pytest.mark.asyncio
async def test_registry_precheck_raises_before_breaker_and_handler() -> None:
    clock = FakeClock()
    handler = SlowHandler(clock)
    reg, board = _registry(clock, {"check_last_connection": handler}, threshold=1)
    breaker: CircuitBreaker = board["vpn"]
    breaker.record_failure()  # mở
    clock.advance(timedelta(seconds=31))  # quá open_seconds → lời gọi kế là lượt thử half-open
    with turn(clock, 0.0), pytest.raises(TurnBudgetExceeded):
        await reg.call("check_last_connection", UserIn(user_id="nv001"), caller_step="B6")
    assert handler.seen == []
    assert breaker.allow()  # lượt thử half-open chưa bị tiêu


def test_breaker_abandoned_releases_half_open_probe_without_closing() -> None:
    clock = FakeClock()
    b = CircuitBreaker("vpn", clock, failure_threshold=1, window_seconds=60, open_seconds=30)
    b.record_failure()
    clock.advance(timedelta(seconds=31))
    assert b.allow() and b.state == "half_open"
    assert not b.allow()  # probe đang bay
    b.record_abandoned()
    assert b.state == "half_open" and b.allow()  # nhả probe, không đóng, không mở lại


@pytest.mark.asyncio
async def test_registry_write_needs_full_timeout() -> None:
    clock = FakeClock()
    cert = {"serial": "S1", "device_id": "LAP-0342", "issued_at": "2026-01-01T00:00:00Z",
            "expires_at": "2027-01-01T00:00:00Z", "status": "valid", "days_to_expiry": 365}  # fmt: skip
    handler = SlowHandler(clock, result=cert)
    reg, _ = _registry(clock, {"renew_vpn_cert": handler})
    args = UserDeviceRequiredIn(user_id="nv001", device_id="LAP-0342")
    with turn(clock, 4.0), pytest.raises(TurnBudgetExceeded):
        await reg.call("renew_vpn_cert", args, caller_step="B17")
    assert handler.seen == []  # không gửi với timeout rút ngắn
    with turn(clock, 8.0):
        r = await reg.call("renew_vpn_cert", args, caller_step="B17")
    assert r.error is None and [t for t, _ in handler.seen] == [5.0]


@pytest.mark.asyncio
async def test_registry_outside_turn_unchanged() -> None:
    clock = FakeClock()
    handler = SlowHandler(clock, 99, 99, 99)
    reg, _ = _registry(clock, {"check_last_connection": handler})
    r = await reg.call("check_last_connection", UserIn(user_id="nv001"), caller_step="B6")
    assert r.error is not None and r.attempts == 3
    assert [t for t, _ in handler.seen] == [5.0, 5.0, 5.0] and clock.sleeps == [1.0, 2.0]


# ---- MlClient (B2 L3, B3, B8 embed/rerank) ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ml_caps_timeout_and_raises_instead_of_error_result() -> None:
    clock = FakeClock()
    ml = FakeMlService().slow("classify_intent", 99, times=3)
    client = ml.client(clock)
    with turn(clock, 3.0) as d, pytest.raises(TurnBudgetExceeded):
        await client.classify_intent("vpn lỗi")
    seen = [(t, at) for ep, t, at in ml.seen if ep == "classify_intent"]
    assert [t for t, _ in seen] == [2.0]  # timeout riêng 2 s; sau đó backoff 1 s ≥ còn 1 s → dừng, không MlResult lỗi
    assert all(t is not None and at is not None and t <= usable_at(d, at) + 1e-9 for t, at in seen)


@pytest.mark.asyncio
async def test_ml_timeout_shrinks_to_remaining() -> None:
    clock = FakeClock()
    ml = FakeMlService()
    with turn(clock, 1.5):
        r = await ml.client(clock).classify_intent("vpn lỗi")
    assert r.error == "model_missing"
    assert [t for _, t, _ in ml.seen] == [1.5]


@pytest.mark.asyncio
async def test_ml_exhausted_turn_sends_nothing() -> None:
    clock = FakeClock()
    ml = FakeMlService()
    with turn(clock, 0.0), pytest.raises(TurnBudgetExceeded):
        await ml.client(clock).embed(["x"])
    assert ml.calls["embed"] == 0


# ---- LLM gateway (B2 L4, B3, B10/B11 sau này) -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_turn_bound_deadline_raises_turn_budget_not_unavailable() -> None:
    clock = FakeClock()
    gw = make_gateway({"b03_classify": lambda _: Timeout()}, clock=clock)
    with turn(clock, 20.0) as d, pytest.raises(TurnBudgetExceeded):
        await gw.client.complete("fast", "b03_classify", B03_VARS, ClassifyOut)
    calls = gw.llm.calls_for("b03_classify")
    assert len(calls) >= 2
    assert all(c.timeout_s is not None and c.at is not None and c.timeout_s <= usable_at(d, c.at) + 1e-9 for c in calls)
    assert (clock.now() - (d.at - timedelta(seconds=MARGIN))).total_seconds() <= 1e-9  # không vượt hạn − biên
    assert gw.store.rows[-1].error == "TurnBudgetExceeded"


@pytest.mark.asyncio
async def test_llm_role_deadline_still_gives_unavailable_when_turn_is_roomy() -> None:
    clock = FakeClock()
    gw = make_gateway({"b03_classify": lambda _: Timeout()}, clock=clock)
    with turn(clock, 90.0), pytest.raises(LLMUnavailable):  # deadline_s fast 45 < 90 → vai trò chặn trước
        await gw.client.complete("fast", "b03_classify", B03_VARS, ClassifyOut)


@pytest.mark.asyncio
async def test_llm_exhausted_turn_sends_no_request() -> None:
    clock = FakeClock()
    gw = make_gateway({"b03_classify": [Reply({"intents": [], "is_multi": False})]}, clock=clock)
    with turn(clock, 0.0), pytest.raises(TurnBudgetExceeded):
        await gw.client.complete("fast", "b03_classify", B03_VARS, ClassifyOut)
    assert gw.llm.calls == []


# ---- Retriever (B8) ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retriever_turn_window_raises_turn_budget() -> None:
    clock = FakeClock()
    spy = _spy()
    spy.delay_next("alias_target", 1.0)  # giây THẬT — asyncio.timeout đo bằng đồng hồ vòng lặp
    r = _retriever(spy, FakeMlService().client(clock), clock=clock)
    t0 = asyncio.get_event_loop().time()
    with turn(clock, 0.05), pytest.raises(TurnBudgetExceeded):
        await r.retrieve(RetrievalQuery(text="x", intent=None), _ctx())
    assert asyncio.get_event_loop().time() - t0 < 0.5


@pytest.mark.asyncio
async def test_retriever_exhausted_turn_touches_nothing() -> None:
    clock = FakeClock()
    spy = _spy()
    ml = FakeMlService()
    r = _retriever(spy, ml.client(clock), clock=clock)
    with turn(clock, 0.0), pytest.raises(TurnBudgetExceeded):
        await r.retrieve(RetrievalQuery(text="x", intent=None), _ctx())
    with turn(clock, 0.0), pytest.raises(TurnBudgetExceeded):
        await r.expand_for_answer([], _ctx(), kb_version="a" * 64)
    assert sum(spy.calls.values()) == 0 and sum(ml.calls.values()) == 0


@pytest.mark.asyncio
async def test_retriever_own_deadline_still_rag_system_error() -> None:
    clock = FakeClock()
    spy = _spy()
    spy.delay_next("alias_target", 1.0)
    r = _retriever(spy, FakeMlService().client(clock), cfg=_cfg(deadline_s=0.05), clock=clock)
    with turn(clock, 90.0), pytest.raises(RetrievalSystemError) as err:  # rag deadline_s 0,05 < 90 — lỗi của RAG
        await r.retrieve(RetrievalQuery(text="x", intent=None), _ctx())
    assert err.value.detail == "deadline"


# ---- Boundary: node không tự bắt → E2 turn_budget_exceeded (Q-3f-2) ---------------------------------------------------


@pytest.mark.asyncio
async def test_b1_turn_budget_exceeded_goes_e2_via_boundary() -> None:
    clock = FakeClock()
    ad = SlowHandler(clock, 99, 99, 99, result=ad_user())
    reg, _ = _registry(clock, {"ad_get_user": ad})
    h = GraphHarness(clock=clock, directory=reg, turn_budget_s=8.0, safety_margin_s=2.0)
    v = (await h.submit_as("t1", SESSION)).values
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E2", "turn_budget_exceeded")
    [row] = [r for r in h.audit.rows if r["event"] == "turn_budget_exceeded"]
    assert row["step"] == "b01_identity" and row["detail"]["node"] == "b01_identity"
    assert [t for t, _ in ad.seen] == [5.0]  # còn 6 s: lần 1 timeout 5 → backoff 1 ≥ còn 1 → dừng
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E2", "turn_budget_exceeded")  # B20 chạy, không bỏ rơi


@pytest.mark.asyncio
async def test_b8_turn_budget_exceeded_goes_e2_via_boundary() -> None:
    clock = FakeClock()
    h = GraphHarness(clock=clock)
    h.rag = _retriever(_spy(), h.ml.client(clock), clock=clock)  # type: ignore[assignment]
    node = wrap_node("b08_retrieve", b08_retrieve.make(h.deps()))
    state = {"ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": "vpn lỗi",
             "intent": "vpn", "slots": {}, "requester_context": _ctx(), "reasoning_loops": 2}  # fmt: skip
    audit = MemoryAudit()
    run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                     clock=clock)  # fmt: skip
    with bind_run(run), turn(clock, 0.0):
        out = await node(state)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (
        S_ESCALATED, "E2", "turn_budget_exceeded",
    )  # fmt: skip
    assert [r["event"] for r in audit.rows] == ["turn_budget_exceeded"]


@pytest.mark.asyncio
async def test_b2_turn_budget_exceeded_keeps_security_flag() -> None:
    clock = FakeClock()
    ml = FakeMlService().slow("classify", 99, times=3)
    gw = make_gateway({"b02_injection_judge": [Reply(NOT_ATTACK)]}, clock=clock)
    h = GraphHarness(clock=clock, nodes="real", ml=ml, llm=gw.client, turn_budget_s=8.0, safety_margin_s=2.0)
    v = (await h.submit_as("t1", SESSION, text="VPN không vào được")).values
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E2", "turn_budget_exceeded")
    assert v["security_flag"] is True  # chưa sàng lọc xong — L2 bàn giao có cờ an ninh
    assert gw.llm.calls == []  # hết hạn ở L3, không gửi L4
    [row] = [r for r in h.audit.rows if r["event"] == "turn_budget_exceeded"]
    assert row["step"] == "B2"
