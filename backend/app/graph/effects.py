"""effects.once — mọi side effect của node đi qua đây (P1 mục 5.3, D-18; bất biến 3).

Khoá sha256(ticket_id|step|turn_id|loop_seq|kind|sub). Chạy lại node (resume, recover sau khi process
chết giữa side effect và checkpoint) → trả `result_ref` cũ, không làm lại: không 2 phiếu duyệt, không
2 thông báo. Test AST (`test_side_effects_ast.py`) cấm node gọi thẳng hàm trong SIDE_EFFECT_FUNCS.

Hàm side effect muốn ghi DB CÙNG transaction với dòng `side_effects` (thông báo trong app, phiếu
duyệt…) dùng `current_tx()` — không có thì tự mở transaction riêng.

`peek` (Phase 4 4b P9): đọc `result_ref` của CÙNG khoá mà `once` sẽ dùng — chỉ SELECT, không ghi, không gọi gì. B15 chạy lại
(TC33) thấy phiếu đã tạo thì bỏ qua chọn người/tra AD/ensure (AD đang lỗi lúc chạy lại không làm mồ côi phiếu `pending`).
"""

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from app.core.hashing import sha256_key
from app.db.models import SIDE_EFFECT_KINDS
from app.db.runtime import current_tx
from app.graph.context import current_run

__all__ = ["current_tx", "effect_key", "once", "peek"]


def effect_key(ticket_id: str, step: str, turn_id: str, loop_seq: int, kind: str, sub: str) -> str:
    return sha256_key(ticket_id, step, turn_id, loop_seq, kind, sub)


async def once(
    state: Mapping[str, Any],
    kind: str,
    fn: Callable[..., Any],
    *args: Any,
    step: str,
    sub: str = "",
    **kwargs: Any,
) -> str | None:
    if kind not in SIDE_EFFECT_KINDS:
        raise ValueError(f"effects.once: kind lạ {kind!r} (P7 2.8)")
    run = current_run()
    loop_seq = int(state.get("reasoning_loops", 0) or 0)

    async def call() -> Any:
        result = fn(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    return await run.effects.run_once(
        key=effect_key(state["ticket_id"], step, run.turn_id, loop_seq, kind, sub),
        ticket_id=state["ticket_id"],
        kind=kind,
        step=step,
        turn_id=run.turn_id,
        call=call,
    )


async def peek(state: Mapping[str, Any], kind: str, *, step: str, sub: str = "") -> str | None:
    """`result_ref` của side effect `kind` đã làm ở lượt này (cùng `effect_key` với `once`) — None = chưa làm."""
    if kind not in SIDE_EFFECT_KINDS:
        raise ValueError(f"effects.peek: kind lạ {kind!r} (P7 2.8)")
    run = current_run()
    loop_seq = int(state.get("reasoning_loops", 0) or 0)  # cùng biểu thức với `once` (dòng khoá của `once` giữ nguyên văn — M-3g-7)
    return await run.effects.peek(effect_key(state["ticket_id"], step, run.turn_id, loop_seq, kind, sub))
