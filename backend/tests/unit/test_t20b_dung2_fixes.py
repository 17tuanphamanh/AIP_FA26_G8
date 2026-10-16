"""T20b — test hồi quy cho các chỗ sửa sau duyệt MẪU B DỪNG 2 (agent chính viết, không phải test-writer).

- Q-T20b-8 = A: `redact_reply_items` — kết quả CHỈ có chữ đã che / bool / None; trường lạ → `ValueError` (fail-closed).
- Q-T20b-9 (i): escalation của cha lỗi ghi MÃ trạng thái từng con trong `done_so_far` (chỉ mã + id con).
- Q-T20b-10 = A: vòng cha mỗi lượt quét tối đa `parent_scan_max` mục, hết ngân sách không bắt đầu mục mới; truy vấn đọc có timeout.
- Q-T20b-11: con đã có thread mà cha thiếu dòng `child_submit` → ghi bù, P12 (a) vế 1 thôi đánh thức cha.
- Q-T20b-12: B3 chạy lại cùng lượt ra cách tách khác (số ý / loại ý, hoặc không tách nữa) → E9 cha, không thêm/đổi con.
(Q-T20b-9 (ii) — hạn thường của con mồ côi: `test_t20b_scan.py::test_s3_…`, `test_t20b_q5_q6.py::test_q5_iii_…`, PG `test_t20b_q5_pg.py`.)
"""

import asyncio
import re
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.api.desk import redact_reply_items
from app.db.runtime import OrphanChild
from app.domain.states import S_CLASSIFYING, S_CONFIRMING, S_ESCALATED
from app.graph.late_event import wake_parent
from app.graph.worker_jobs import WorkerJobs
from pydantic import BaseModel
from tests.fakes.desk import MASK, SECRET, MaskingGuard
from tests.fakes.graph import Crash
from tests.unit._t20b import (
    TC34,
    TC35,
    Flow,
    adobe_item,
    classify,
    extend_item,
    make_flow,
    reset_item,
)

pytestmark = pytest.mark.asyncio


# ---- Q-T20b-8 = A ------------------------------------------------------------------------------------------------------------------


class _Answer(BaseModel):
    answer: str


class _Confirm(BaseModel):
    confirmed: bool
    note: str | None = None


class _Odd(BaseModel):
    answer: str
    extra: str


def _desk() -> Any:
    return SimpleNamespace(guard=MaskingGuard())


async def test_q8_redact_reply_items_only_redacted_text_bool_none() -> None:
    items = {"T1-1": _Answer(answer=f"mật khẩu {SECRET}"), "T1-2": _Confirm(confirmed=False, note=f"lỗi {SECRET}"),
             "T1-3": _Confirm(confirmed=True)}  # fmt: skip
    out = await redact_reply_items(_desk(), cast(Any, None), cast(Any, items))
    assert out.items == {"T1-1": {"answer": f"mật khẩu {MASK}"}, "T1-2": {"confirmed": False, "note": f"lỗi {MASK}"},
                         "T1-3": {"confirmed": True, "note": None}}  # fmt: skip
    assert (out.result.secrets_found, out.result.text) == (2, "")


@pytest.mark.parametrize("item", [_Odd(answer="x", extra="y"), SimpleNamespace(model_dump=lambda: {"confirmed": "yes"})],
                         ids=["truong-la", "confirmed-khong-bool"])  # fmt: skip
async def test_q8_redact_reply_items_fail_closed(item: Any) -> None:
    with pytest.raises(ValueError) as exc:
        await redact_reply_items(_desk(), cast(Any, None), {"T1-1": item})
    assert "extra" not in str(exc.value)  # không nêu tên trường (khoá có thể là chữ người dùng)


# ---- Q-T20b-9 (i) ------------------------------------------------------------------------------------------------------------------

_LINE = re.compile(r"Ticket con \(mã trạng thái\): (T1-\d=[a-z_:A-Z+]+)(; T1-\d=[a-z_:A-Z+]+)*\.$")


async def _break(f: Flow, method: str) -> None:
    async def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("lỗi chưa lường ở vòng cha")

    setattr(f.h.runner.children, method, broken)


async def test_q9_i_failed_parent_handoff_lists_child_codes() -> None:
    f = make_flow([classify(reset_item(), extend_item())] * 2, extract={"duration": "30"})
    r = await f.submit(TC35)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait")
    await f.h.txlog.begin("T1-1", "x", "reset_password")  # B17 của con 1 đã bắt đầu lệnh ghi
    await _break(f, "deliver")
    r = await f.deliver("T1", S_CONFIRMING, {"kind": "reply", "items": {"T1-1": {"confirmed": True}, "T1-2": {"answer": "30"}}})
    assert r.values.get("exit_code") == "E9"
    [esc] = f.h.escalations.of("T1")
    done = esc["handoff_note"]["done_so_far"]
    assert done.endswith("Ticket con (mã trạng thái): T1-1=awaiting_confirm+executed; T1-2=awaiting_answer.")
    assert _LINE.search(done)  # chỉ mã + id con


async def test_q9_i_parent_failed_before_children_started() -> None:
    f = make_flow(classify(reset_item(), adobe_item()))
    await _break(f, "start_missing")
    r = await f.submit(TC34)
    assert r.values.get("exit_code") == "E9"
    [esc] = f.h.escalations.of("T1")
    assert esc["handoff_note"]["done_so_far"].endswith("Ticket con (mã trạng thái): T1-1=not_started; T1-2=not_started.")


async def test_q9_i_children_status_error_still_escalates_with_fixed_code() -> None:
    """Soát lượt 4 NGHI (a): đọc trạng thái con lỗi DB → B20 cha vẫn tạo escalation NGAY, ghi mã cố định `children_status_unavailable`."""
    f = make_flow(classify(reset_item(), adobe_item()))

    async def down(_: str) -> Any:
        raise ConnectionError("DB chết")

    f.h.tickets.children_status = down  # type: ignore[method-assign,assignment]
    await _break(f, "start_missing")
    r = await f.submit(TC34)
    assert (r.status, r.values.get("exit_code")) == (S_ESCALATED, "E9")
    [esc] = f.h.escalations.of("T1")
    assert esc["handoff_note"]["done_so_far"].endswith("Ticket con (mã trạng thái): children_status_unavailable.")
    assert [m["kind"] for m in await f.assistant_msgs()] == ["escalation"]


async def test_q9_i_leaf_ticket_handoff_unchanged() -> None:
    f = make_flow(classify(reset_item(), adobe_item()))
    await _break(f, "start_missing")
    await f.submit(TC34)
    assert all("Ticket con" not in e["handoff_note"]["done_so_far"] for t in ("T1-1", "T1-2") for e in f.h.escalations.of(t))


# ---- Q-T20b-10 = A + soát lượt 4 NGHI (b): hai bước, ngân sách riêng, con mồ côi TRƯỚC ------------------------------------------------


class _Mono:
    """Đồng hồ đơn điệu giả: `now` chỉ đổi khi test (hoặc lời gọi giả) đẩy."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _patch_scan(f: Flow, mono: _Mono, *, orphans: list[OrphanChild], parents: list[str], wake_cost: float = 0.0,
                deliver_cost: float = 0.0) -> dict[str, list[Any]]:  # fmt: skip
    seen: dict[str, list[Any]] = {"orphan_limit": [], "parent_limit": [], "woken": [], "timed_out": []}

    async def orphan_children(now: Any, limit: int, *, clarify_hours: int, confirm_hours: int) -> list[OrphanChild]:
        seen["orphan_limit"].append(limit)
        return orphans

    async def parents_to_wake(limit: int) -> list[str]:
        seen["parent_limit"].append(limit)
        return parents

    async def wake(parent_id: str) -> None:
        seen["woken"].append(parent_id)
        mono.now += wake_cost

    f.h.deadlines.orphan_children = orphan_children  # type: ignore[method-assign]
    f.h.deadlines.parents_to_wake = parents_to_wake  # type: ignore[method-assign]
    f.h.runner.wake_parent = wake  # type: ignore[method-assign,assignment]
    return seen


async def test_q10_each_step_capped_and_budgeted_separately() -> None:
    f, mono = make_flow(classify(reset_item(), adobe_item())), _Mono()
    seen = _patch_scan(f, mono, orphans=[OrphanChild("X-1", "confirm"), OrphanChild("X-2", "answer")], parents=["P1", "P2", "P3"],
                       wake_cost=4.0)  # fmt: skip
    jobs = WorkerJobs(f.h.runner, f.h.deadlines, f.h.turns, parent_scan_max=7, parent_scan_budget_s=10.0, monotonic=mono)
    report = await jobs.scan_parents()
    assert seen["orphan_limit"] == [7] and seen["parent_limit"] == [7]
    assert report.late == 2  # cả 2 con mồ côi được xử lý (id giả → TicketNotFound)
    assert seen["woken"] == ["P1", "P2", "P3"] and (report.woken, report.deferred) == (3, 0)  # 0, 4, 8 < 10
    mono.now = 0.0
    seen["woken"].clear()
    _patch_scan(f, mono, orphans=[], parents=["P1", "P2", "P3", "P4"], wake_cost=4.0)
    report = await jobs.scan_parents()
    assert (report.woken, report.deferred) == (3, 1)  # mục 4 bắt đầu lúc 12 ≥ 10 → để chu kỳ sau


async def test_q10_slow_parent_does_not_starve_orphans() -> None:
    """Soát lượt 4 NGHI (b): một cha đánh thức rất chậm ở MỌI chu kỳ — bước con mồ côi vẫn chạy (chạy trước, ngân sách riêng)."""
    f, mono = make_flow(classify(reset_item(), adobe_item())), _Mono()
    _patch_scan(f, mono, orphans=[OrphanChild("X-1", "confirm")], parents=["SLOW", "P2"], wake_cost=100.0)
    jobs = WorkerJobs(f.h.runner, f.h.deadlines, f.h.turns, parent_scan_budget_s=10.0, monotonic=mono)
    for _ in range(3):
        report = await jobs.scan_parents()
        assert (report.late, report.woken, report.deferred) == (1, 1, 1)


@pytest.mark.parametrize("slow", ["orphan_children", "parents_to_wake"])
async def test_q10_slow_read_skips_only_that_step(slow: str) -> None:
    f, mono = make_flow(classify(reset_item(), adobe_item())), _Mono()
    seen = _patch_scan(f, mono, orphans=[OrphanChild("X-1", "confirm")], parents=["P1"])

    async def hang(*_: Any, **__: Any) -> list[Any]:
        await asyncio.sleep(5)
        return []

    setattr(f.h.deadlines, slow, hang)
    jobs = WorkerJobs(f.h.runner, f.h.deadlines, f.h.turns, parent_scan_budget_s=0.05, monotonic=mono)
    report = await asyncio.wait_for(jobs.scan_parents(), timeout=2)
    assert report.failed == 1
    assert (report.late, seen["woken"]) == ((1, []) if slow == "parents_to_wake" else (0, ["P1"]))
    assert (await asyncio.wait_for(jobs.scan_deadlines(), timeout=2)).failed == 0  # phần quét hạn không bị ảnh hưởng


# ---- Q-T20b-11 ---------------------------------------------------------------------------------------------------------------------


async def test_q11_missing_child_submit_backfilled_once_no_restart() -> None:
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    assert (await f.waiting("T1")) == "parent_wait"  # con 2 chờ duyệt
    lost = [k for k, e in f.h.effects.rows.items() if e["kind"] == "child_submit" and e["result_ref"] == "started:T1-2"]
    assert len(lost) == 1
    del f.h.effects.rows[lost[0]]  # chết giữa lượt lồng của con 2 và lúc ghi `child_submit`
    assert "T1" in await f.h.deadlines.parents_to_wake(10)  # P12 (a) vế 1
    turns_before = len(f.h.turns.of("T1-2"))
    r = await wake_parent(f.h.runner, "T1")
    assert r is not None and (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")
    assert await f.h.tickets.started_children("T1") == frozenset({"T1-1", "T1-2"})  # ghi bù
    assert len(f.h.turns.of("T1-2")) == turns_before  # con 2 KHÔNG bị khởi động lại
    assert "T1" not in await f.h.deadlines.parents_to_wake(10)  # thôi đánh thức mỗi 60 s
    await wake_parent(f.h.runner, "T1")
    assert f.h.effects.count("T1", "child_submit") == 2  # lần đánh thức sau không ghi thêm (đã có dòng)


# ---- Q-T20b-12 ---------------------------------------------------------------------------------------------------------------------


def _open_turn(f: Flow, ticket_id: str) -> str:
    [turn] = [t["turn_id"] for t in f.h.turns.of(ticket_id) if t["ended_at"] is None]
    return turn


@pytest.mark.parametrize(
    "second",
    [classify(reset_item(), extend_item()), classify(reset_item())],
    ids=["khac-loai-y", "khong-tach-nua"],
)
async def test_q12_rerun_with_different_split_parent_e9_no_new_children(second: Any) -> None:
    f = make_flow([classify(reset_item(), adobe_item()), second])
    f.h.audit.crash_once.add("split_into_2_children")  # chết sau `child_create` cả 2 con, trước checkpoint cha
    with pytest.raises(Crash):
        await f.submit(TC34)
    turn = _open_turn(f, "T1")
    f.gw.store.cache.clear()  # cache LLM không giữ kết quả lần trước (bypass / model dự phòng / chết trước cache_put — Q-T20b-12)
    f.h.restart()
    r = await f.h.runner.recover("T1", turn)
    assert f.b03_calls() == 2  # B3 thật sự gọi lại LLM
    assert r is not None and (r.status, r.values.get("exit_code")) == (S_ESCALATED, "E9")
    assert f.h.tickets.created_children == ["T1-1", "T1-2"] and f.h.effects.count("T1", "child_create") == 2
    assert (await f.h.runner.snapshot("T1-1")).values == {} and (await f.h.runner.snapshot("T1-2")).values == {}
    assert f.h.audit.of("T1", "split_into_2_children") == []
    [esc] = f.h.escalations.of("T1")  # soát lượt 4 mục 4: state cha chưa có `children` — vẫn liệt kê con đã tạo từ DB
    assert esc["handoff_note"]["done_so_far"].endswith("Ticket con (mã trạng thái): T1-1=not_started; T1-2=not_started.")
