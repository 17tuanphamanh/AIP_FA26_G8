"""`parent_reply_wait` — cha chờ người dùng trả lời tin tổng hợp ở `S_CONFIRMING` (node THẬT, Phase 5 T20b P8 — phase5 5.2.4; P1 §8.2;
D-31). Bản giả (gate2, `FAKE_SCENARIO`): `graph/nodes/fake/parent_reply_wait.py`.

KHÔNG side effect trước `interrupt()`. Sự kiện `reply` (`items`, đã che ở API) hoặc `timeout` (worker) → với từng con trong `awaiting`
(thứ tự `index`): `timeout` → `{"kind":"timeout"}`; `needs=answer` → `{"kind":"user_reply","text":answer}`; `needs=confirm` →
`{"kind":"confirmed"|"unresolved","note":…}` → `peek("child_event", sub=f"{cid}:{round}")` có → bỏ; chưa →
`current_run().children.deliver(...)` → `effects.once("child_event", sub=f"{cid}:{round}")` ghi lại. Một tin người dùng ghép
(`reply_text`) vào `conversation` cha (không với timeout). → `S_CLASSIFYING` → `parent_wait` (`reply_dispatched` | `reply_timeout`).
"""

from collections.abc import Mapping
from typing import Any

from langgraph.types import interrupt

from app.domain.children import child_index
from app.domain.messages import reply_text, user_msg
from app.domain.states import S_CLASSIFYING
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def child_event(needs: str, item: Mapping[str, Any] | None) -> dict[str, Any]:
    """Sự kiện cho con (P8): `item` None = timeout của cha; `answer` → `user_reply`; `confirm` → `confirmed`/`unresolved`."""
    if item is None:
        return {"kind": "timeout"}
    if needs == "answer":
        return {"kind": "user_reply", "text": str(item["answer"])}
    return {"kind": "confirmed" if item["confirmed"] else "unresolved", "note": item.get("note")}


def make(deps: NodeDeps) -> NodeFn:
    async def parent_reply_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "parent_reply"})
        run = current_run()
        if run.children is None:
            raise RuntimeError("RunContext không có ChildOps — parent_reply_wait chỉ chạy qua Runner")
        timeout = ev["kind"] == "timeout"
        items: Mapping[str, Mapping[str, Any]] = {} if timeout else ev["items"]
        rnd = int(state.get("parent_round") or 0)
        awaiting: Mapping[str, str] = state.get("awaiting") or {}
        skipped: list[str] = []
        for cid in sorted(awaiting, key=child_index):
            sub = f"{cid}:{rnd}"
            if await effects.peek(state, "child_event", step="B5", sub=sub) is not None:
                continue  # đã giao + ghi ở lần chạy trước của lượt này (D-18)
            outcome = await run.children.deliver(cid, awaiting[cid], child_event(awaiting[cid], None if timeout else items[cid]))
            if outcome == "skipped":
                skipped.append(cid)  # lệch node/trạng thái — đã giao trước đó hoặc con đã đi tiếp; KHÔNG late_event
            await effects.once(state, "child_event", _delivered, cid, outcome, step="B5", sub=sub)
        update: dict[str, Any] = {}
        if not timeout:  # MỘT tin người dùng (đã che ở API), ghép theo thứ tự ý — hợp đồng FE (d)
            update["conversation"] = [user_msg(reply_text([(child_index(cid), items[cid]) for cid in awaiting]))]
        return await goto(
            state, S_CLASSIFYING, next_node="parent_wait", step="B5",
            event="reply_timeout" if timeout else "reply_dispatched", audit_detail={"skipped": skipped}, **update,
        )  # fmt: skip

    return parent_reply_wait


def _delivered(cid: str, outcome: str) -> str:
    return f"{outcome}:{cid}"
