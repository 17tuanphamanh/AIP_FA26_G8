"""B6–B7 — node THẬT, Phase 3 chỉ VPN (thiết kế mục 9.4; 3-Q8; PLAN-3f chốt Q-3f-1, Q-3f-7). Node giả (Phase 2,
`FAKE_SCENARIO`): `graph/nodes/fake/b06_diagnose.py`.

1. `reasoning_loops + 1 > MAX_LOOPS` → E2 `max_loops_exceeded`.
2. `ENABLE_PROACTIVE_DIAGNOSIS=false` (ablation RQ3) → 0 lời gọi, `facts={}`, sang B8.
3. 3 tool đọc VPN gọi SONG SONG qua registry (`caller_step="B6"`, retry/breaker/hạn lượt ở registry). `device_id` tuỳ chọn.
4. B7: bất kỳ tool nào lỗi hệ thống (sau retry, breaker mở) → E2 `tool_system_error` — cả nhánh (B06 mục 6: thiếu một
   dữ kiện có thể thành False Negative). `tool_errors` chỉ "tên tool: loại lỗi" (không URL/user_id). 404/rỗng = DỮ LIỆU.
   Hết hạn cả lượt → E2 `turn_budget_exceeded`. Lỗi hợp đồng (`ToolContractError`…) → ném → boundary E9.
5. `facts` CHỈ từ `infer_vpn` / `module.infer` (dữ liệu tool) — không bao giờ từ `slots` (G-01, test AST P3). Slot suy ra chỉ bổ sung, không
   ghi đè slot người dùng đã nêu. `diagnostics` lưu JSON (`model_dump(mode="json")`, PLAN-3f mục 3). `tool_retry_count` =
   số lần THỬ LẠI (`retries_of`, Q-3f-1). B6 không tự đặt `ctx_flags.target_is_other=True` (máy của người khác thể hiện
   qua fact `device_owner_is_requester=false`; người bị tác động qua `requested_for`) — chỉ giữ cờ B3 đã đặt (mục 8).
6. D-20 (Q-3f-7): 3f luôn gọi đủ 3 tool, ghi `rediagnose=False`; `next` về B11 nếu state đang chẩn đoán lại (3g).
7. T20a (phase5 5.1.5, PLAN-T20a TQ-2/3/17): `vpn` giữ đúng dòng code cũ; intent trong `DIAGNOSERS` (account, software, access) →
   `module.calls(requester, slots)` → `diag[tool] = ToolResult.data` (RootModel rỗng = "rỗng", `None` = 404/không gọi — mọi tool
   của `TOOLS` có khoá) → `module.infer(...)`. Chẩn đoán với slot chưa đủ chỉ là GỢI Ý — B11 tính lại toàn bộ. Intent khác → E9.
8. Q-T20a-4 (duyệt DỪNG 1): `ctx_flags.target_is_other` KHÔNG bị ghi đè về False — B3 đặt True khi `target_user` bị bỏ (người
   dùng nhắm người khác mà định danh không qua được `sanitize_slots`); mọi nhánh ở đây giữ True nếu state đã True, mặc định False.
9. be-target-guard-2 (L-03 Phần 2 D): vpn/software, cờ `target_is_other` bật (B3 thấy câu nhắm MÁY người khác) → KHÔNG tự suy máy duy
   nhất của người gửi (`allow_infer=False`) — không slot `device_id`/`action` suy ra, không fact máy; B11 hỏi mã máy.
10. Q3 M3 (ĐP 09/11): account — `infer_account` suy `account_type="ad"` khi AD của CHÍNH người gửi đang khoá (điều kiện ở
   `tools/diagnosis/account.py`); cờ `target_is_other` bật → `allow_infer=False` như mục 9. Audit `slots_inferred` như VPN.

Điểm log 2 ở MỌI nhánh: `tools_called`, `tool_retry_count`, `slots_inferred`, `facts`, `rediagnose`, `phase`.
"""

import asyncio
from typing import Any

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.domain.target import DEVICE_INTENTS
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.ports import ToolResult
from app.graph.tracing import NodeFn
from app.tools.diagnosis import DIAGNOSERS, vpn
from app.tools.retry import retries_of

# Cờ `target_is_other` bật → không tự suy slot: máy (vpn/software — be-target-guard-2), loại tài khoản (account — Q3 M3).
NO_INFER_WHEN_OTHER = DEVICE_INTENTS | {"account"}


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
        other = bool((state.get("ctx_flags") or {}).get("target_is_other"))  # Q-T20a-4: B3 đã đặt True thì giữ
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
                facts={}, ctx_flags={"target_is_other": other}, rediagnose=False, reasoning_loops=loops,
            )  # fmt: skip
        intent = state.get("intent")
        module = DIAGNOSERS.get(intent) if isinstance(intent, str) else None
        if intent != "vpn" and module is None:  # B3 chỉ cho qua intent đã bật — intent không có bộ chẩn đoán là bug → E9
            raise ValueError(f"b06_diagnose không có bộ chẩn đoán cho intent {intent!r}")
        requester = state["requester_context"].user_id
        calls = vpn.calls(requester, device_id) if module is None else module.calls(requester, slots)
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
        if module is None:  # VPN: 404/rỗng = dữ liệu hợp lệ, gộp về None (không đổi)
            diag = {r.tool: (None if r.empty else r.data) for r in results}
            inferred, facts = vpn.infer_vpn(diag, requester_id=requester, device_id=device_id, allow_infer=not other)
        else:  # TQ-2: giữ phân biệt 404 (None) / rỗng (RootModel rỗng)
            diag = {t: None for t in module.TOOLS} | {r.tool: r.data for r in results}
            no_infer = {"allow_infer": False} if other and intent in NO_INFER_WHEN_OTHER else {}  # be-target-guard-2, Q3 M3
            inferred, facts = module.infer(diag, requester_id=requester, slots=slots, **no_infer)
        added = {k: v for k, v in inferred.items() if k not in slots}  # không ghi đè slot người dùng đã nêu
        point2.update(slots_inferred=sorted(added), facts=facts)
        return await goto(
            state, S_RETRIEVING, next_node="b11_slots" if rediag else "b08_retrieve", step="B6",
            event="diagnosed", audit_detail=point2,
            diagnostics={t: (None if m is None else m.model_dump(mode="json")) for t, m in diag.items()},
            slots={**slots, **added}, facts=facts, tool_retry_count=retries, ctx_flags={"target_is_other": other},
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
