"""B6–B7 — node THẬT, Phase 3 chỉ VPN (thiết kế mục 9.4; 3-Q8; PLAN-3f chốt Q-3f-1, Q-3f-7). Node giả (Phase 2,
`FAKE_SCENARIO`): `graph/nodes/fake/b06_diagnose.py`.

1. `reasoning_loops + 1 > MAX_LOOPS` → E2 `max_loops_exceeded`.
2. `ENABLE_PROACTIVE_DIAGNOSIS=false` (ablation RQ3) → 0 lời gọi, `facts={}`, sang B8.
3. 3 tool đọc VPN gọi SONG SONG qua registry (`caller_step="B6"`, retry/breaker/hạn lượt ở registry). `device_id` tuỳ chọn.
4. B7: bất kỳ tool nào lỗi hệ thống (sau retry, breaker mở) → E2 `tool_system_error` — cả nhánh (B06 mục 6: thiếu một
   dữ kiện có thể thành False Negative). `tool_errors` chỉ "tên tool: loại lỗi" (không URL/user_id). 404/rỗng = DỮ LIỆU.
   Hết hạn cả lượt → E2 `turn_budget_exceeded`. Lỗi hợp đồng (`ToolContractError`…) → ném → boundary E9.
5. `facts` CHỈ từ `infer_vpn` (dữ liệu tool) — không bao giờ từ `slots` (G-01, test AST P3). Slot suy ra chỉ bổ sung, không
   ghi đè slot người dùng đã nêu. `diagnostics` lưu JSON (`model_dump(mode="json")`, PLAN-3f mục 3). `tool_retry_count` =
   số lần THỬ LẠI (`retries_of`, Q-3f-1). `ctx_flags.target_is_other` luôn false ở VPN Phase 3 (máy của người khác thể hiện
   qua fact `device_owner_is_requester=false`).
6. D-20 (Q-3f-7): 3f luôn gọi đủ 3 tool, ghi `rediagnose=False`; `next` về B11 nếu state đang chẩn đoán lại (3g).

Điểm log 2 ở MỌI nhánh: `tools_called`, `tool_retry_count`, `slots_inferred`, `facts`, `rediagnose`, `phase`.
"""

import asyncio
from typing import Any

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.ports import ToolResult
from app.graph.tracing import NodeFn
from app.tools.diagnosis import vpn
from app.tools.retry import retries_of


def _point2(tools: list[str], *, device_id: str | None, rediagnose: bool) -> dict[str, Any]:
    return {
        "tools_called": tools, "tool_retry_count": 0, "slots_inferred": [], "facts": {}, "rediagnose": rediagnose,
        "phase": "device" if device_id else "lookup",
    }  # fmt: skip


def _error_kind(error: str) -> str:
    """"TimeoutException: …url…" → "TimeoutException" — không chép URL (có user_id/device_id) vào state/audit."""
    return error.split(":", 1)[0].strip()[:64]


def make(deps: NodeDeps) -> NodeFn:
    async def b06_diagnose(state: Any) -> dict[str, Any]:
        loops = int(state.get("reasoning_loops") or 0) + 1
        rediag = bool(state.get("rediagnose"))
        slots = dict(state.get("slots") or {})
        device_id = slots.get("device_id")
        if loops > deps.constants.MAX_LOOPS:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B6", event="max_loops_exceeded",
                audit_detail=_point2([], device_id=device_id, rediagnose=rediag), exit_code=ExitCode.E2.value,
                reasoning_loops=loops, escalation_reason_detail="max_loops_exceeded",
            )  # fmt: skip
        if not deps.enable_proactive_diagnosis:  # ablation RQ3: 0 lời gọi, không dữ kiện → B11 phải hỏi
            return await goto(
                state, S_RETRIEVING, next_node="b11_slots" if rediag else "b08_retrieve", step="B6",
                event="diagnosis_skipped", audit_detail=_point2([], device_id=device_id, rediagnose=rediag),
                facts={}, ctx_flags={"target_is_other": False}, rediagnose=False, reasoning_loops=loops,
            )  # fmt: skip
        if state.get("intent") != "vpn":  # B3 chỉ cho qua intent đã bật (Phase 3: vpn) — khác là bug → E9
            raise ValueError(f"b06_diagnose Phase 3 chỉ có VPN, nhận intent {state.get('intent')!r}")
        requester = state["requester_context"].user_id
        calls = vpn.calls(requester, device_id)
        point2 = _point2([t for t, _ in calls], device_id=device_id, rediagnose=rediag)
        try:
            results = await _gather(calls)
        except TurnBudgetExceeded:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B6", event="turn_budget_exceeded",
                audit_detail=point2, exit_code=ExitCode.E2.value, reasoning_loops=loops,
                escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip
        retries = sum(retries_of(r.attempts, failed=r.error is not None) for r in results)
        point2["tool_retry_count"] = retries
        if errors := [f"{r.tool}: {_error_kind(r.error)}" for r in results if r.error is not None]:  # B7
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B7", event="tool_system_error",
                audit_detail={**point2, "tool_errors": errors}, exit_code=ExitCode.E2.value, tool_errors=errors,
                tool_retry_count=retries, reasoning_loops=loops, escalation_reason_detail="tool_system_error",
            )  # fmt: skip
        diag = {r.tool: (None if r.empty else r.data) for r in results}  # 404/rỗng = dữ liệu hợp lệ
        inferred, facts = vpn.infer_vpn(diag, requester_id=requester, device_id=device_id)
        added = {k: v for k, v in inferred.items() if k not in slots}  # không ghi đè slot người dùng đã nêu
        point2.update(slots_inferred=sorted(added), facts=facts)
        return await goto(
            state, S_RETRIEVING, next_node="b11_slots" if rediag else "b08_retrieve", step="B6",
            event="diagnosed", audit_detail=point2,
            diagnostics={t: (None if m is None else m.model_dump(mode="json")) for t, m in diag.items()},
            slots={**slots, **added}, facts=facts, tool_retry_count=retries, ctx_flags={"target_is_other": False},
            rediagnose=False, reasoning_loops=loops,
        )  # fmt: skip

    async def _gather(calls: list[tuple[str, dict[str, str]]]) -> list[ToolResult]:
        """Gọi song song; mọi lời gọi tự cắt theo hạn lượt ở registry. Lỗi hợp đồng ưu tiên ném (E9 — bug phải thấy), sau đó
        mới tới hết hạn lượt."""
        outs = await asyncio.gather(
            *[deps.directory.call(t, a, caller_step="B6") for t, a in calls], return_exceptions=True
        )
        excs = [o for o in outs if isinstance(o, BaseException)]
        if bug := next((e for e in excs if not isinstance(e, TurnBudgetExceeded)), None):
            raise bug
        if excs:
            raise excs[0]
        return [o for o in outs if not isinstance(o, BaseException)]

    return b06_diagnose
