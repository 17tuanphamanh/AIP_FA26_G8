"""T20b — test hồi quy cho 3 chỗ sửa sau soát bảo mật S10 (DỪNG 1). Agent chính viết (không phải test-writer) — ghi ở MẪU B.

- 8a: `parent_wait` không lấy khoá con ĐÃ khởi động — con đang bị giữ khoá (lượt dài khác) không làm cha `TicketBusy` → E9.
- B-ii: lượt lồng khởi động con lỗi TRƯỚC checkpoint đầu của con → không ghi `child_submit` (con coi như chưa khởi động), cha không E9.
- B-iii: `parent_wait` chạy lại cùng lượt SAU khi tin vòng 1 đã gửi → dựng lại ĐÚNG notice vòng 1, không gom notice mới tới sau.
"""

import asyncio
from typing import Any

import pytest
from app.domain.states import S_CLASSIFYING, S_CONFIRMING
from app.graph.late_event import wake_parent
from tests.fakes.graph import Crash
from tests.unit._t20b import (
    ADOBE_PRINTER,
    TC34,
    TC35,
    adobe_item,
    classify,
    extend_item,
    make_flow,
    oos_item,
    reset_item,
)

pytestmark = pytest.mark.asyncio


async def test_s10_8a_started_child_held_elsewhere_does_not_block_parent() -> None:
    f = make_flow(classify(adobe_item(), oos_item()), lock_timeout=3.0)
    await f.submit(ADOBE_PRINTER)
    assert (await f.waiting("T1")) == "parent_wait"  # D-77: vòng 1 đã báo, con 1 chờ duyệt → cha chờ con
    async with f.h.lock.hold("T1-1"):  # một lượt khác đang giữ khoá con 1 (lâu hơn lock_timeout)
        r = await asyncio.wait_for(wake_parent(f.h.runner, "T1"), timeout=1)  # không CHỜ khoá con đã khởi động
    assert r is not None and (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")
    assert f.h.audit.of("T1", "unhandled_exception") == [] and (await f.values("T1")).get("exit_code") is None


async def test_s10_bii_nested_failure_before_child_checkpoint_not_recorded_as_started() -> None:
    f = make_flow(classify(reset_item(), adobe_item()))
    graph = f.h.runner.graph
    original = graph.aupdate_state

    async def broken(config: Any, values: Any, *args: Any, **kw: Any) -> Any:
        if config["configurable"]["thread_id"] == "T1-2":
            raise RuntimeError("lỗi DB tạm thời khi gieo con 2")
        return await original(config, values, *args, **kw)

    graph.aupdate_state = broken  # type: ignore[method-assign]
    r = await f.submit(TC34)
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")  # cha KHÔNG E9
    assert (await f.h.runner.snapshot("T1-2")).values == {}
    assert f.h.effects.count("T1", "child_submit") == 1  # chỉ con 1 được ghi là đã khởi động
    graph.aupdate_state = original  # type: ignore[method-assign]
    await wake_parent(f.h.runner, "T1")  # lần đối soát sau khởi động lại con 2
    assert (await f.h.runner.snapshot("T1-2")).values and f.h.effects.count("T1", "child_submit") == 2


async def test_s10_biii_rerun_after_sent_rebuilds_same_round_without_new_notice() -> None:
    f = make_flow([classify(reset_item(), extend_item())] * 2, extract={"duration": "30"})
    f.h.audit.crash_once.add("digest_sent")
    with pytest.raises(Crash):
        await f.submit(TC35)
    sent = {n["notice_id"] for n in f.h.tickets.notices if n["delivered_round"] == 1}
    late = await f.h.notices.insert(
        parent_id="T1", child_id="T1-1", source_step="B20", kind="escalation", needs="none", body="NOTICE-MOI",
        effect_key="k" * 64,
    )  # notice mới tới trong lúc chờ phục hồi
    [turn] = [t["turn_id"] for t in f.h.turns.of("T1") if t["ended_at"] is None]
    f.h.restart()
    r = await f.h.runner.recover("T1", turn)
    assert r is not None and (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait")
    [digest] = [m for m in (await f.values("T1"))["conversation"] if m.get("kind") == "digest"]
    assert "NOTICE-MOI" not in digest["text"]
    assert {n["notice_id"] for n in f.h.tickets.notices if n["delivered_round"] == 1} == sent
    [new] = [n for n in f.h.tickets.notices if n["notice_id"] == late]
    assert new["delivered_at"] is None  # còn cho vòng sau
