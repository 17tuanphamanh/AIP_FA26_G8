"""f19 (phase3 mục 9.0; PLAN-3f S0) — lượt XẤU NHẤT trên FakeClock qua graph thật, hạn lượt mặc định (100 s / 2 s).

Mọi phụ thuộc ngoài chậm tới trần riêng của nó: AD (B1) 2 lần quá timeout rồi trả lời sau 4,9 s; ml `/classify` (B2 L3)
3 lần quá timeout; L4 `b02_injection_judge` 3 lần Timeout rồi trả lời; B8 Retriever thật: embed 4,9 s, rerank luôn quá
timeout. Tổng trần riêng > 120 s → hạn lượt phải cắt. Đạt khi: ticket E2 `turn_budget_exceeded`, đồng hồ không vượt hạn,
và KHÔNG lời gọi nào nhận timeout > phần còn lại − biên — đo ở NƠI NHẬN (handler AD, `FakeMlService.seen`,
`ScriptedLLM.calls`). Đột biến M-3f-7b (MlClient bỏ cắt) làm đỏ test này.
"""

from datetime import datetime, timedelta

import pytest
from app.core.clock import FakeClock
from app.domain.states import S_ESCALATED
from app.llm.providers.scripted import Reply, Timeout
from app.settings import Settings
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import SESSION, ad_user
from tests.fakes.llm import make_gateway
from tests.fakes.rag import SpyPoint
from tests.unit.test_rag_retriever import _payload, _retriever, _spy
from tests.unit.test_turn_deadline import SlowHandler, _registry

pytestmark = pytest.mark.asyncio

NORMAL = "VPN không vào được, báo lỗi 809 trên máy LAP-0342"
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}
SETTINGS = Settings(_env_file=None)  # type: ignore[call-arg]


async def test_f19_worst_case_turn_ends_e2_within_budget_and_no_call_exceeds_remaining() -> None:
    clock = FakeClock()
    start = clock.now()
    budget, margin = SETTINGS.turn_budget_s, SETTINGS.safety_margin_s
    usable_end = start + timedelta(seconds=budget - margin)

    ad = SlowHandler(clock, 99, 99, 4.9, result=ad_user())
    directory, _ = _registry(clock, {"ad_get_user": ad})
    ml = FakeMlService().slow("classify", 99, times=3).slow("embed", 4.9).slow("rerank", 99, times=3)
    gw = make_gateway({"b02_injection_judge": [Timeout(), Timeout(), Timeout(), Reply(NOT_ATTACK)]}, clock=clock)
    spy = _spy(points=[SpyPoint("p1", _payload("KB-VPN-001", 0, "vpn lỗi 809 chứng chỉ"), score=0.9)])
    rag = _retriever(spy, ml.client(clock), clock=clock)  # Retriever THẬT (B8), cùng ml-service giả chậm
    h = GraphHarness(clock=clock, nodes="real", directory=directory, ml=ml, llm=gw.client, rag=rag)  # type: ignore[arg-type]

    v = (await h.submit_as("t1", SESSION, text=NORMAL)).values

    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E2", "turn_budget_exceeded")
    assert clock.now() <= usable_end  # không lời gọi nào chạy quá hạn − biên
    assert [r for r in h.audit.rows if r["event"] == "turn_budget_exceeded"]

    seen: list[tuple[str, float, datetime]] = [("ad", t, at) for t, at in ad.seen]
    seen += [(f"ml:{ep}", t, at) for ep, t, at in ml.seen if t is not None and at is not None]
    seen += [(f"llm:{c.prompt_id}", c.timeout_s, c.at) for c in gw.llm.calls if c.timeout_s and c.at]
    kinds = {k for k, _, _ in seen}
    assert {"ad", "ml:classify", "llm:b02_injection_judge", "ml:embed", "ml:rerank"} <= kinds  # lượt đi qua đủ lớp
    assert len(seen) >= 12
    for kind, timeout, at in seen:
        remaining = (usable_end - at).total_seconds()
        assert timeout <= remaining + 1e-9, f"{kind}: timeout {timeout:g}s > còn {remaining:g}s lúc {at}"
    # lượt thật sự bị cắt: tổng trần riêng của các lời gọi vượt hạn (không phải xong sớm một cách tình cờ)
    assert (clock.now() - start).total_seconds() > budget - margin - 5
