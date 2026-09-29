"""f19 (phase3 mục 9.0; PLAN-3f S0, cập nhật S6) — lượt XẤU NHẤT trên FakeClock qua graph thật, hạn lượt mặc định (100 s / 2 s).

Mọi phụ thuộc ngoài chậm tới trần riêng của nó: AD (B1) 2 lần quá timeout rồi trả lời sau 4,9 s; ml `/classify` (B2 L3) 3
lần quá timeout; L4 `b02_injection_judge` 3 lần Timeout rồi trả lời; ml `/classify_intent` (B3) 3 lần quá timeout;
`b03_classify` 2 lần Timeout rồi trả lời; 3 tool VPN (B6) mỗi lời gọi 4,9 s. Tổng trần riêng > 120 s → hạn lượt phải cắt.
Đạt khi: E2 `turn_budget_exceeded`, đồng hồ không vượt hạn − biên, và KHÔNG lời gọi nào nhận timeout > phần còn lại − biên
— đo ở NƠI NHẬN (handler AD/VPN, `FakeMlService.seen`, `ScriptedLLM.calls`). M-3f-7a/b/c làm đỏ test này.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.domain.states import S_ESCALATED
from app.llm.providers.scripted import Reply, Timeout
from app.settings import Settings
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import SESSION, ad_user
from tests.fakes.llm import make_gateway
from tests.fakes.vpn import SeedVpn
from tests.unit.test_turn_deadline import SlowHandler, _registry

pytestmark = pytest.mark.asyncio

NORMAL = "VPN không vào được, báo lỗi 809 trên máy LAP-0342"
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}
VPN_ONE = {"intents": [{"type": "vpn", "confidence": 0.92, "span": NORMAL, "action_hint": "renew_vpn_cert",
                        "slots": {"device_id": "LAP-0342"}}], "is_multi": False}  # fmt: skip
SETTINGS = Settings(_env_file=None)  # type: ignore[call-arg]

type Handler = Callable[[Any, float], Awaitable[object]]


def slow(handler: Handler, clock: FakeClock, latency: float, seen: list[tuple[float, datetime]]) -> Handler:
    """Tool chậm `latency` giây trên FakeClock; ≥ timeout nhận được → tua đúng timeout rồi `ReadTimeout`."""

    async def call(inp: Any, timeout: float) -> object:
        seen.append((timeout, clock.now()))
        if latency >= timeout:
            clock.advance(timedelta(seconds=timeout))
            raise httpx.ReadTimeout("tool chậm quá timeout")
        clock.advance(timedelta(seconds=latency))
        return await handler(inp, timeout)

    return call


async def test_f19_worst_case_turn_ends_e2_within_budget_and_no_call_exceeds_remaining() -> None:
    clock = FakeClock()
    start = clock.now()
    budget, margin = SETTINGS.turn_budget_s, SETTINGS.safety_margin_s
    usable_end = start + timedelta(seconds=budget - margin)

    ad = SlowHandler(clock, 99, 99, 4.9, result=ad_user())
    tool_seen: list[tuple[float, datetime]] = []
    vpn = {name: slow(h, clock, 4.9, tool_seen) for name, h in SeedVpn(clock).handlers().items()}
    directory, _ = _registry(clock, {"ad_get_user": ad, **vpn})
    ml = FakeMlService().slow("classify", 99, times=3).slow("classify_intent", 99, times=3)
    gw = make_gateway({
        "b02_injection_judge": [Timeout(), Timeout(), Timeout(), Reply(NOT_ATTACK)],
        "b03_classify": [Timeout(), Timeout(), Reply(VPN_ONE)],
    }, clock=clock)  # fmt: skip
    h = GraphHarness(clock=clock, nodes="real", directory=directory, ml=ml, llm=gw.client)

    v = (await h.submit_as("t1", SESSION, text=NORMAL)).values

    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E2", "turn_budget_exceeded")
    assert clock.now() <= usable_end  # không lời gọi nào chạy quá hạn − biên
    [row] = [r for r in h.audit.rows if r["event"] == "turn_budget_exceeded"]
    assert row["step"] == "B6"  # hết hạn giữa 3 tool VPN — B6 bắt tường minh (điểm log 2)

    seen: list[tuple[str, float, datetime]] = [("ad", t, at) for t, at in ad.seen]
    seen += [("tool:vpn", t, at) for t, at in tool_seen]
    seen += [(f"ml:{ep}", t, at) for ep, t, at in ml.seen if t is not None and at is not None]
    seen += [(f"llm:{c.prompt_id}", c.timeout_s, c.at) for c in gw.llm.calls if c.timeout_s and c.at]
    kinds = {k for k, _, _ in seen}
    assert {"ad", "ml:classify", "llm:b02_injection_judge", "ml:classify_intent", "llm:b03_classify",
            "tool:vpn"} <= kinds  # lượt đi qua đủ lớp  # fmt: skip
    assert len(seen) >= 18
    for kind, timeout, at in seen:
        remaining = (usable_end - at).total_seconds()
        assert timeout <= remaining + 1e-9, f"{kind}: timeout {timeout:g}s > còn {remaining:g}s lúc {at}"
    assert any(t < 5.0 for t, _ in tool_seen)  # tool cuối bị cắt timeout theo phần còn lại (không phải 5 s riêng)
    assert (clock.now() - start).total_seconds() > budget - margin - 5  # thật sự bị cắt, không xong sớm tình cờ
