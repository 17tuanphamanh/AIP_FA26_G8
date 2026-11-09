"""G4 — node chờ chạy lại nhiều lần trước `interrupt()` KHÔNG ghi DB thêm.

LangGraph resume = chạy lại node TỪ ĐẦU; phần trước `interrupt()` chạy lại mỗi lần. Nếu phần đó ghi (audit, effect, tin nhắn, hạn, phiếu,
sự kiện bảo mật…) mà không idempotent thì mỗi lần đánh thức nhân đôi dòng. Năm node chờ:

- `clarify_wait`, `approval_wait`, `confirm_wait`, `parent_reply_wait`: `interrupt()` là câu lệnh ĐẦU — 0 ghi ngay cả ở lần đầu. Thử trực tiếp ở
  mức node (thay `interrupt` bằng bản dừng ngay, như LangGraph khi chưa có giá trị resume): chạy 3 lần (lần đầu + resume 2 lần), ảnh chụp
  mọi kho giả KHÔNG đổi sau lần nào.
- `parent_wait`: phần trước `interrupt()` có việc thật (`start_missing`, ghi `children_not_started` khi con chưa khởi động được) nhưng phải
  idempotent. Thử trên graph thật hai thread cha/con: đánh thức cha 2 lần → các kho ghi (effect, tin, hạn, ticket con, notice) không đổi;
  audit chỉ thêm đúng một dòng `parent_woken` mỗi lần đánh thức (dòng SAU interrupt, có chủ ý).

Test này chỉ thêm — không đổi mã sản xuất. `snapshot` tự thử: một lần ghi giả làm ảnh chụp đổi (test chống test rỗng).
"""

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

import pytest
from app.domain.states import (
    S_CLARIFYING,
    S_CLASSIFYING,
    S_CONFIRMING,
    S_PENDING_APPROVAL,
)
from app.graph.context import RunContext, bind_run
from app.graph.late_event import wake_parent
from app.graph.nodes import approval_wait, clarify_wait, confirm_wait, parent_reply_wait
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemorySpans
from tests.unit._t20b import (
    ADOBE_PRINTER,
    Flow,
    adobe_item,
    classify,
    make_flow,
    oos_item,
)

pytestmark = pytest.mark.asyncio


def _plain(value: Any) -> Any:
    """Chuỗi hoá ổn định cho so sánh: container → bản sao sâu có thứ tự; đối tượng lạ → repr."""
    if isinstance(value, Mapping):
        return {repr(k): _plain(v) for k, v in value.items()}
    if isinstance(value, Counter):
        return dict(value)
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(repr(v) for v in value)
    return repr(value)


def snapshot(h: GraphHarness) -> dict[str, Any]:
    """Mọi kho giả của harness mà node có thể ghi: audit/lineage, effects, tin gửi, hạn, phiếu duyệt, ticket + notice, escalation, security
    events, cảnh báo, txlog, lượt (turns). Spans KHÔNG tính: mỗi lần chạy node qua graph thật ghi một span (vết kỹ thuật, không phải dữ liệu)."""
    stores: dict[str, Any] = {
        "audit": h.audit, "effects": h.effects, "notifier": h.notifier, "deadlines": h.deadlines, "approvals": h.approvals,
        "tickets": h.tickets, "escalations": h.escalations, "security_events": h.security_events, "alerts": h.alerts,
        "txlog": h.txlog, "turns": h.turns,
    }  # fmt: skip
    out: dict[str, Any] = {}
    for name, store in stores.items():
        for attr, value in vars(store).items():
            if isinstance(value, Mapping | list | tuple | set | frozenset | Counter):
                out[f"{name}.{attr}"] = copy.deepcopy(_plain(value))
    return out


async def test_snapshot_detects_a_write() -> None:
    h = GraphHarness()
    before = snapshot(h)
    h.audit.rows.append({"ticket_id": "t1", "step": "B16", "event": "x"})
    assert snapshot(h) != before
    h2 = GraphHarness()
    h2.notifier.sent.append(("t1", "x", "none"))
    assert snapshot(h2) != snapshot(GraphHarness())
    h3 = GraphHarness()
    h3.deadlines.waits.append({"ticket_id": "t1"})
    assert snapshot(h3) != snapshot(GraphHarness())


class Parked(Exception):
    """`interrupt()` khi chưa có giá trị resume: LangGraph dừng lượt tại đây."""


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"ticket_id": "t1", "turn_id": "T1", "reasoning_loops": 0, "conversation": [], "approval_id": "A1",
                            "parent_round": 0, "awaiting": {}}  # fmt: skip
    return {**base, **over}


CASES = [
    pytest.param(clarify_wait, S_CLARIFYING, {"wait": "clarify"}, id="clarify_wait"),
    pytest.param(approval_wait, S_PENDING_APPROVAL, {"wait": "approval", "approval_id": "A1"}, id="approval_wait"),
    pytest.param(confirm_wait, S_CONFIRMING, {"wait": "confirm"}, id="confirm_wait"),
    pytest.param(parent_reply_wait, S_CONFIRMING, {"wait": "parent_reply"}, id="parent_reply_wait"),
]


@pytest.mark.parametrize(("module", "status", "payload"), CASES)
async def test_wait_node_writes_nothing_before_interrupt_on_every_rerun(
    module: Any, status: str, payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    reached: list[Any] = []

    def parked(value: Any) -> Any:
        reached.append(value)
        raise Parked

    monkeypatch.setattr(module, "interrupt", parked)
    h = GraphHarness()
    node = module.make(h.deps())
    before = snapshot(h)
    for _ in range(3):  # lần đầu + resume 2 lần (chưa có giá trị → vẫn dừng ở interrupt)
        run = RunContext(turn_id="T1", trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=MemorySpans(), clock=h.clock,
                         txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run), pytest.raises(Parked):
            await node(_state(status=status))
        assert snapshot(h) == before
    assert reached == [payload] * 3  # node thật sự tới interrupt mỗi lần (không thoát sớm vì lý do khác)
    assert h.notifier.sent == [] and h.effects.rows == {} and h.audit.rows == []


# ---- parent_wait: việc trước interrupt phải idempotent ------------------------------------------------------------------------


def _writes(f: Flow) -> dict[str, Any]:
    """Các kho GHI của cha/con, bỏ audit (kiểm riêng) và turns/spans (mỗi lần đánh thức mở một lượt — có chủ ý)."""
    snap = snapshot(f.h)
    return {k: v for k, v in snap.items() if not k.startswith(("audit.", "turns."))}


def _audit_events(f: Flow) -> list[tuple[str, str, str]]:
    return [(r["ticket_id"], r["step"], r["event"]) for r in f.h.audit.rows]


async def test_parent_wait_prewake_part_is_idempotent_across_wakes(monkeypatch: pytest.MonkeyPatch) -> None:
    f = make_flow(classify(adobe_item(), oos_item()))
    r = await f.submit(ADOBE_PRINTER)  # D-77: con 1 → approval_wait, con 2 → E1; vòng 1 đã báo → cha chờ con ở parent_wait
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")

    passes = {"n": 0}
    real = f.h.tickets.started_children

    async def counting(parent: str) -> Any:  # câu ĐẦU của parent_wait — đếm số lần phần trước interrupt chạy
        passes["n"] += 1
        return await real(parent)

    monkeypatch.setattr(f.h.tickets, "started_children", counting)
    base_writes, base_events = _writes(f), _audit_events(f)

    for wake in (1, 2):
        again = await wake_parent(f.h.runner, "T1")
        assert again is not None and (again.status, again.waiting_at) == (S_CLASSIFYING, "parent_wait")
        assert passes["n"] >= 2 * wake  # mỗi lần đánh thức chạy lại phần trước interrupt (resume) rồi vào vòng mới
        assert _writes(f) == base_writes  # effect, tin, hạn, ticket con, notice: KHÔNG đổi
        assert _audit_events(f) == base_events + [("T1", "B5", "parent_woken")] * wake  # chỉ dòng SAU interrupt
    assert [e for e in _audit_events(f) if e[2] == "children_not_started"] == []
