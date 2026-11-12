"""B17–B18 — node THẬT (Phase 3 chặng 3h; phase3 mục 11.4, B17-B18 §5). Gate2 (`FAKE_SCENARIO`) dùng bản giả
`graph/nodes/fake/b17_execute.py`. Điểm ghi DUY NHẤT ra hệ thống ngoài — mọi lớp phía trên có thể sai, đây là chốt cuối.

0. **`transaction_log` TRƯỚC mọi bước kiểm lại** (chốt DỪNG 2, NGHI-2): ticket đã có `begun` ở BẤT KỲ lượt nào → E7
   `exec_interrupted` + `escalation_note` "có thể đã gửi lệnh ghi", 0 lời gọi ghi. Chạy lại B17 sau khi đã ghi mà điều kiện đổi
   (hết giờ, người bị khoá…) thì kiểm lại sẽ ra E5 — L2 đọc E5 là "chưa làm" và có thể làm tay lần 2; E7 bảo L2 kiểm hệ thống
   đích trước. Mỗi ticket tới B17 tối đa một lần (không nhánh nào quay lại B17), nên chặn theo ticket không chặn nhầm.
1. **Kiểm lại luật** với policy + Clock HIỆN HÀNH (P8): `deny` → E5 `recheck_failed`. Ticket đi qua duyệt (`approval_id` hoặc
   `approval_result` có) → "đã duyệt" = `approval_result == "approved"` **và** bảng `approvals` `approved` (`get_status`) — lệch
   → E5 `recheck_failed`, BẤT KỂ luật hiện hành (M-3h-7, M-3h-12). `approval_required` hoặc không luật nào khớp mà không "đã
   duyệt" → E5 `recheck_failed`. **Phase 6 6C P6 (D-42):** ngoại lệ DUY NHẤT — không qua duyệt, luật hiện hành không khớp, và
   `risk` là AUTO do LLM (`decided_by="llm"`, `route="AUTO"`, có `calibrated_prob` — Q-6C-10) với `action_plan_hash` B12 đặt bằng hash
   hành động hiện tại → đi
   tiếp (kiểm người vẫn chạy), điểm log 7 `action_plan_hash_matched` True. `full_auto` (`risk` None) không có ngoại lệ.
2. **Hash:** đi qua duyệt thì `action_plan_hash` phải có và bằng `hash_action(intended_action)` — thiếu/lệch → E5
   `action_plan_changed_since_approval` (cấm 3). **Phase 4 4d P7 (Việc treo 29):** lớp thứ hai — `hash_action(intended_action)` còn phải
   bằng `approvals.action_plan_hash` của PHIẾU (cái người duyệt đã xem, 4c P6); lệch → cùng E5, `detail.hash_source="approval"`, 0 lời
   gọi ghi, TRƯỚC mọi lời tra AD.
3. **Người:** `ad_get_user` (`caller_step="B17_RECHECK"`, 3-Q37) cho người gửi và người hưởng lợi (bỏ trùng, song song) —
   `disabled`/`terminated`, không có, hoặc lỗi AD → E5 `person_no_longer_valid` (D-15). **Phase 4 4b P13 (Q-4b-1, TQ-11):** đi
   qua duyệt thì tra thêm người ĐÃ DUYỆT (`approvals.get(...).decided_by`) trong CÙNG `gather` (một điểm gọi); `decided_by` None
   mà phiếu `approved` → E5 `recheck_failed`. Xét người gửi/người hưởng lợi TRƯỚC (nhánh cũ giữ nguyên), rồi người đã duyệt: lỗi
   AD → E2 `approver_lookup_error`; không còn hợp lệ l1 lẫn Trưởng BP (`domain.approval.invalid_reason`: không có, không
   `active`, nhóm không ra l1/manager) → E5 `approver_no_longer_valid`. 0 lời gọi ghi. `requester_context` chụp ở B1 có thể
   cũ (người bị khoá trong lúc chờ hỏi lại/duyệt) — bước này đóng khe đó. **Q-3h-7:** mọi trường `requester.*` mà một luật
   bất kỳ trong policy tham chiếu (tính lúc dựng node = lúc khởi động; hiện chỉ `employment_status`) — dựng lại từ AD mới bằng
   chính `RequesterContext.from_ad` tại mốc `captured_at` của B1 — khác bản chụp → E5 `recheck_failed` (vd `active` →
   `probation` trong lúc chờ: bản chụp làm R19 trượt). Không dựng lại được (nhóm AD không còn ra role…) → cũng E5.
   **Soát executor 12/11 (TA duyệt sửa lõi):** tài khoản AD `account.enabled=False` cũng là "không còn hợp lệ" (D-15 chỉ xét
   `employment_status` — HR `active` mà AD đã tắt vẫn được cấp chứng chỉ).
0b. **N2 (soát 12/11):** ticket KHÁC của cùng người gửi, cùng intent, còn escalation E7 MỞ mà lệnh ghi CÓ THỂ đã tới đích
   (`deps.escalations.open_write_doubt`, 7 ngày) → E5 `recheck_failed` (`recheck="prior_write_unconfirmed"`), 0 lời gọi ghi. Trước:
   E7 "có thể đã áp dụng" rồi người dùng xin lại → ghi lần 2 (2 SMS, mật khẩu tạm lần 1 mất hiệu lực; chứng chỉ mới lần 1 bị thu hồi).
3c. **N1 (soát 12/11), chỉ ca đi qua duyệt:** đọc lại các fact `action.facts.*` mà luật tham chiếu (+ `cert_status`) bằng ĐÚNG lời gọi + hàm suy luận của
   B11 (`caller_step="B17_RECHECK"`) — khác bản chụp → E5 `recheck_failed` (`recheck="facts_changed"`, `fields`), 0 lời gọi ghi. Trước:
   an ninh khoá lại tài khoản (`lock_reason` → admin) hoặc thu hồi chứng chỉ trong lúc chờ duyệt → B17 vẫn mở khoá / gia hạn (đặc
   tả B17 §0.3 hứa bắt "thiết bị bị thu hồi"). Lỗi tool → E2 `tool_system_error`; hết hạn lượt → E2 `turn_budget_exceeded`.
4–5. `deps.executor.execute(ticket_id, turn_id, action)` (P7: `PlanExecutor` chỉ ở API; worker `RefusingExecutor`):
   `ExecutionInterrupted` → E7 `exec_interrupted` (`begun` có từ trước: 0 lời gọi ghi; lỗi SAU `begin` của lần này — chốt FAIL
   mục 7: audit `cause` = tên lớp lỗi, `write_calls` = cận trên); `TurnBudgetExceeded` (P4 — trước khi gửi) → E2
   `turn_budget_exceeded`; kết quả lỗi → E7 `exec_failed` + `execution` + `escalation_note = handoff_note` (4 phần — B20 chép
   vào ghi chú bàn giao).
6. **B18:** điểm log 7 → `notify_user` (tin THEO MẪU, P6 — `domain.messages.result_text`; T24: `view_permissions` kèm dòng quyền
   từ `diagnostics` B6 qua `permission_rows`; Q3 M6: `install_software` mà `outputs.already_installed == "true"` → mẫu "đã có sẵn"
   `already_installed_text`, audit `executed_ok` thêm `already_installed` (bool)) + hạn confirm qua `effects.once`
   (`step="B18"`) → `conversation` `kind="result"` → `S_CONFIRMING`. Lệnh ghi ĐÃ thành công: lỗi (`Exception`) ở đoạn này → E7
   `exec_interrupted` + câu "có thể đã gửi lệnh ghi…" (chốt FAIL mục 7 c — ticket đã có `begun` không bao giờ mang mẫu E9 "xử lý
   thủ công"); `BaseException` (`CancelledError`) đi tiếp.

Mỗi nhánh một `goto` với `step`/`exit_code`/`escalation_reason_detail` hằng (P1). Audit không có câu người dùng: chỉ định
danh luật/người, enum, hash hex, số lời gọi ghi.
"""

import asyncio
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from app.core.errors import DomainError
from app.core.hashing import hash_action
from app.core.turn_budget import TurnBudgetExceeded
from app.domain.action import Action
from app.domain.approval import invalid_reason
from app.domain.context import RequesterContext
from app.domain.exit_codes import ExitCode
from app.domain.messages import (
    already_installed_text,
    is_already_installed,
    permission_rows,
    result_msg,
    result_text,
)
from app.domain.policy import referenced_facts
from app.domain.states import S_CONFIRMING, S_ESCALATED
from app.domain.ticket_state import ExecutionResult, RiskDecision
from app.executor.errors import ExecutionInterrupted
from app.executor.txlog import MAY_HAVE_WRITTEN
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.risk.context import build_ctx
from app.risk.policy_engine import evaluate
from app.settings import get_policy
from app.tools.diagnosis import DIAGNOSERS, vpn
from app.tools.specs import RECHECK_STEP

INVALID_PEOPLE = frozenset({"disabled", "terminated"})
INTERRUPTED_NOTE = f"Thực thi bị gián đoạn (transaction_log đã có begun): {MAY_HAVE_WRITTEN}."
# V10 (soát 12/11): executor đã báo THÀNH CÔNG, lỗi ở B18 (đặt hạn / gửi tin kết quả) — L2 biết lệnh ghi đã tới đích, không làm lại
B18_FAILED_NOTE = ("Lệnh ghi ĐÃ THÀNH CÔNG ({steps}) nhưng lỗi ở bước báo kết quả / đặt hạn xác nhận — xác nhận kết quả với người "
                   "dùng, KHÔNG làm lại.")  # fmt: skip
WRITE_DOUBT_WINDOW = timedelta(days=7)
PRIOR_DOUBT_NOTE = (
    "Chưa thực thi: ticket {prior} của cùng người gửi (cùng loại yêu cầu) còn chờ kỹ thuật viên kiểm vì lệnh ghi có thể đã tới hệ "
    "thống đích. Kiểm và đóng ticket đó trước, rồi mới làm việc này — tránh làm hai lần (đặt lại mật khẩu, gia hạn chứng chỉ…)."
)
_MISSING = object()


def _write_calls(res: ExecutionResult) -> int:
    """Số lời gọi ghi THẬT (điểm log 7): bước đã xong + bước lỗi + lần hoàn tác đã gửi. T24 P3: `not_reversible` (bước không
    hoàn tác được — không gọi gì) và `UNDO_FAILED: turn_budget_exceeded` (registry chặn TRƯỚC khi gửi) không tính."""
    undo_sent = sum(
        1 for _, s in res.rollback_details
        if s == "undone" or (s.startswith("UNDO_FAILED: ") and s != "UNDO_FAILED: turn_budget_exceeded")
    )  # fmt: skip
    return len(res.steps_done) + (1 if res.failed_step else 0) + undo_sent


def _point7(res: ExecutionResult) -> dict[str, Any]:
    return {
        "success": res.success, "steps_done": res.steps_done, "failed_step": res.failed_step,
        "rollback_status": res.rollback_status, "action_plan_hash_matched": res.action_plan_hash_matched,
        "write_calls": _write_calls(res),
    }  # fmt: skip


def llm_auto(state: Any, action: Action) -> bool:
    """6C P6 (D-42): AUTO do LLM ở B12 — `risk.decided_by == "llm"` ∧ `risk.route == "AUTO"` ∧ `action_plan_hash` (B12 đặt) bằng
    `hash_action` của hành động ĐANG chạy. `risk` None/vắng (`full_auto`, state cũ) → False; `risk` hỏng → ValidationError → E9.
    Q-6C-10: thêm `calibrated_prob` có giá trị — B12 chỉ ra AUTO do LLM khi đã hiệu chỉnh (D-38); thiếu = state lạ → không thực thi."""
    raw = state.get("risk")
    if raw is None:
        return False
    risk = RiskDecision.model_validate(raw)
    return (
        risk.decided_by == "llm" and risk.route == "AUTO" and state.get("action_plan_hash") == hash_action(action)
        and risk.calibrated_prob is not None  # Q-6C-10
    )  # fmt: skip


def watched_requester_fields() -> tuple[str, ...]:
    """Q-3h-7: trường `requester.*` mà luật trong policy (lúc khởi động) tham chiếu. Trường không có trong `RequesterContext` →
    không dựng node (danh sách trắng `FACT_SOURCES` đã chặn khi nạp policy — đây là lớp thứ hai)."""
    fields = tuple(sorted(referenced_facts(get_policy().rules, "requester")))
    unknown = [f for f in fields if f not in RequesterContext.model_fields]
    if unknown:
        raise RuntimeError(f"policy tham chiếu requester.{unknown} không có trong RequesterContext")
    return fields


def watched_action_facts() -> frozenset[str]:
    """N1 (soát 12/11): fact `action.facts.*` mà luật trong policy (lúc khởi động) tham chiếu, cộng `cert_status` (chứng chỉ bị an
    ninh thu hồi trong lúc chờ duyệt — luật hiện không xét nhưng người duyệt đã thấy trạng thái cũ)."""
    prefix = "action.facts."
    names = {f.removeprefix(prefix) for rule in get_policy().rules for f in rule.conditions.facts() if f.startswith(prefix)}
    return frozenset(names | {"cert_status"})


def fact_recheck_calls(state: Any, requester_id: str) -> list[tuple[str, dict[str, str]]]:
    """Đúng bộ lời gọi B11 `_build` dùng để dựng `action.facts` (VPN: tool nhận `device_id`; intent khác: `module.target_calls`)."""
    intent = state.get("intent")
    slots = dict(state.get("slots") or {})
    if intent == "vpn":
        return vpn.target_calls(requester_id, slots["device_id"]) if slots.get("device_id") else []
    module = DIAGNOSERS.get(intent) if isinstance(intent, str) else None
    return [] if module is None else module.target_calls(requester_id, slots)


def fresh_facts(state: Any, results: list[Any], requester_id: str) -> dict[str, Any]:
    """Đúng hàm suy luận B11 `_build` trên kết quả đọc lại. VPN chỉ lấy `vpn.DEVICE_FACTS` (B11 chỉ làm mới phần máy)."""
    intent = state.get("intent")
    slots = dict(state.get("slots") or {})
    if intent == "vpn":
        diag = {t: None for t in vpn.TOOLS} | {r.tool: (None if r.empty else r.data) for r in results}
        _, facts = vpn.infer_vpn(diag, requester_id=requester_id, device_id=slots["device_id"])
        return {k: v for k, v in facts.items() if k in vpn.DEVICE_FACTS}
    module = DIAGNOSERS[intent]
    diag = {t: None for t in module.TOOLS} | {r.tool: r.data for r in results}
    _, facts = module.infer(diag, requester_id=requester_id, slots=slots)
    return dict(facts)


def make(deps: NodeDeps) -> NodeFn:
    watched = watched_requester_fields()
    watched_facts = watched_action_facts()

    async def _reads(calls: list[tuple[str, dict[str, str]]]) -> list[Any]:
        """MỘT điểm gọi tool đọc của B17 (người ở [3], fact ở [3c]) — song song, hạn lượt/retry/breaker ở registry."""
        return await asyncio.gather(
            *[deps.directory.call(t, a, caller_step=RECHECK_STEP) for t, a in calls], return_exceptions=True
        )

    async def b17_execute(state: Any) -> dict[str, Any]:
        run = current_run()
        if await deps.txlog.has_begun(state["ticket_id"]):  # [0] NGHI-2 — TRƯỚC mọi bước kiểm lại
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="exec_interrupted",
                audit_detail={"stage": "txlog_before_recheck", "success": False, "write_calls": 0},
                exit_code=ExitCode.E7.value, escalation_reason_detail="exec_interrupted", escalation_note=INTERRUPTED_NOTE,
            )  # fmt: skip
        action = Action.model_validate(state["intended_action"])  # thiếu = bug → E9
        requester = RequesterContext.model_validate(state["requester_context"])
        prior = await deps.escalations.open_write_doubt(  # [0b] N2 — ca trước còn "có thể đã ghi"
            requester_id=requester.user_id, intent=str(state.get("intent")), since=run.clock.now() - WRITE_DOUBT_WINDOW,
            exclude_ticket_id=state["ticket_id"],
        )  # fmt: skip
        # E11 (soát 12/11, agent 12 L1): ca trước mà transaction_log TRỐNG (chết trước lời gọi ghi đầu) không "có thể đã ghi" → không chặn
        if prior is not None and await deps.txlog.has_begun(prior):
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="recheck_failed",
                audit_detail={"recheck": "prior_write_unconfirmed", "prior_ticket_id": prior, "write_calls": 0},
                exit_code=ExitCode.E5.value, escalation_reason_detail="recheck_failed",
                escalation_note=PRIOR_DOUBT_NOTE.format(prior=prior),
            )  # fmt: skip
        verdict = evaluate(action, build_ctx(state, run.clock.now(), deps.business_hours))  # [1] P8: hiện hành
        rule = {"policy_decision": verdict.decision, "matched_rule_id": verdict.rule_id,
                "all_matched": verdict.all_matched, "write_calls": 0}  # fmt: skip
        if verdict.decision == "deny":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="recheck_failed",
                audit_detail={**rule, "recheck": "deny"}, exit_code=ExitCode.E5.value,
                escalation_reason_detail="recheck_failed",
            )  # fmt: skip
        via_approval = bool(state.get("approval_id")) or state.get("approval_result") is not None
        approved = False
        matched: bool | None = None
        decided_by: str | None = None
        if via_approval:
            db_status = await deps.approvals.get_status(state["approval_id"]) if state.get("approval_id") else None
            approved = state.get("approval_result") == "approved" and db_status == "approved"
            if not approved:
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="recheck_failed",
                    audit_detail={**rule, "recheck": "approval_mismatch", "approval_state": state.get("approval_result"),
                                  "approval_db": db_status},
                    exit_code=ExitCode.E5.value, escalation_reason_detail="recheck_failed",
                )  # fmt: skip
            current, approved_hash = hash_action(action), state.get("action_plan_hash")
            matched = bool(approved_hash) and current == approved_hash
            if not matched:  # [2] cấm 3
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="action_plan_changed_since_approval",
                    audit_detail={**rule, "hash_old": approved_hash, "hash_new": current, "action_plan_hash_matched": False},
                    exit_code=ExitCode.E5.value, escalation_reason_detail="action_plan_changed_since_approval",
                )  # fmt: skip
            row = await deps.approvals.get(state["approval_id"])  # P13: AI đã duyệt
            if row is not None and row.action_plan_hash != current:  # [2b] 4d P7: hai lớp — so thêm hash của PHIẾU (Việc treo 29)
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="action_plan_changed_since_approval",
                    audit_detail={**rule, "hash_source": "approval", "hash_old": row.action_plan_hash, "hash_new": current,
                                  "action_plan_hash_matched": False},
                    exit_code=ExitCode.E5.value, escalation_reason_detail="action_plan_changed_since_approval",
                )  # fmt: skip
            decided_by = None if row is None else row.decided_by
            if decided_by is None:  # "đã duyệt" mà không biết người duyệt → không thực thi
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="recheck_failed",
                    audit_detail={**rule, "recheck": "no_decided_by"}, exit_code=ExitCode.E5.value,
                    escalation_reason_detail="recheck_failed",
                )  # fmt: skip
        via_llm = not via_approval and not verdict.matched and llm_auto(state, action)  # 6C P6 (D-42)
        if not approved and not via_llm and (verdict.decision == "approval_required" or not verdict.matched):
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="recheck_failed",
                audit_detail={**rule, "recheck": "not_approved"}, exit_code=ExitCode.E5.value,
                escalation_reason_detail="recheck_failed",
            )  # fmt: skip
        matched = True if via_llm else matched  # điểm log 7 `action_plan_hash_matched` (TQ-10)

        people = list(dict.fromkeys([requester.user_id, action.requested_for]))  # [3] D-15 (sửa)
        lookups = list(dict.fromkeys([*people, *([decided_by] if decided_by else [])]))  # P13: + người đã duyệt, CÙNG gather
        checks = await _reads([("ad_get_user", {"user_id": uid}) for uid in lookups])
        for outcome in checks:  # lỗi hợp đồng (bug) ném trước — E9; hết hạn lượt sau — E2
            if isinstance(outcome, BaseException) and not isinstance(outcome, TurnBudgetExceeded):
                raise outcome
        if any(isinstance(o, TurnBudgetExceeded) for o in checks):
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="turn_budget_exceeded",
                audit_detail={**rule, "stage": "recheck_person"}, exit_code=ExitCode.E2.value,
                escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip
        found = dict(zip(lookups, checks, strict=True))
        ad_requester: Any = None
        for uid in people:
            data, err, _ = found[uid]  # type: ignore[misc]
            status = getattr(data, "employment_status", None)
            ad_disabled = getattr(getattr(data, "account", None), "enabled", True) is False  # soát 12/11: AD đã tắt, HR còn active
            if err is not None or data is None or status in INVALID_PEOPLE or ad_disabled:
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="person_no_longer_valid",
                    audit_detail={**rule, "user_id": uid, "role": "requester" if uid == requester.user_id else "beneficiary",
                                  "ad_error": err is not None, "employment_status": status, "ad_disabled": ad_disabled},
                    exit_code=ExitCode.E5.value, escalation_reason_detail="person_no_longer_valid",
                )  # fmt: skip
            if uid == requester.user_id:
                ad_requester = data
        try:  # Q-3h-7 — dựng lại bằng chính hàm của B1, mốc thời gian của B1 (tenure_days không trôi theo thời gian chờ)
            fresh: RequesterContext | None = RequesterContext.from_ad(ad_requester, requester.captured_at)
        except (DomainError, ValidationError):
            fresh = None
        changed = [f for f in watched if fresh is None or getattr(fresh, f) != getattr(requester, f)]
        if fresh is None or changed:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="recheck_failed",
                audit_detail={**rule, "recheck": "requester_changed", "fields": changed, "rebuilt": fresh is not None},
                exit_code=ExitCode.E5.value, escalation_reason_detail="recheck_failed",
            )  # fmt: skip

        if decided_by is not None:  # P13 — SAU người gửi/người hưởng lợi
            data, err, _ = found[decided_by]  # type: ignore[misc]
            if err is not None:
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="approver_lookup_error",
                    audit_detail={**rule, "user_id": decided_by, "role": "approver", "ad_error": True},
                    exit_code=ExitCode.E2.value, escalation_reason_detail="approver_lookup_error",
                )  # fmt: skip
            reason = invalid_reason(data, "l1")
            if reason is not None and invalid_reason(data, "manager") is not None:
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="approver_no_longer_valid",
                    audit_detail={**rule, "user_id": decided_by, "role": "approver", "reason": reason},
                    exit_code=ExitCode.E5.value, escalation_reason_detail="approver_no_longer_valid",
                )  # fmt: skip

        # [3c] N1 — chỉ ca ĐÃ QUA DUYỆT: khe thời gian (chờ duyệt, tới 30 phút) nằm ở đây; ca AUTO đi B11 → B12 → B17 trong CÙNG lượt,
        # fact B11 vừa đọc.
        if via_approval and (calls := fact_recheck_calls(state, requester.user_id)):
            outs = await _reads(calls)
            for outcome in outs:  # lỗi hợp đồng (bug) ném trước — E9; hết hạn lượt sau — E2
                if isinstance(outcome, BaseException) and not isinstance(outcome, TurnBudgetExceeded):
                    raise outcome
            if any(isinstance(o, TurnBudgetExceeded) for o in outs):
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="turn_budget_exceeded",
                    audit_detail={**rule, "stage": "recheck_facts"}, exit_code=ExitCode.E2.value,
                    escalation_reason_detail="turn_budget_exceeded",
                )  # fmt: skip
            if failed := [r.tool for r in outs if r.error is not None]:
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="tool_system_error",
                    audit_detail={**rule, "stage": "recheck_facts", "tools": failed}, exit_code=ExitCode.E2.value,
                    escalation_reason_detail="tool_system_error",
                )  # fmt: skip
            reread = fresh_facts(state, outs, requester.user_id)
            snapshot = set(action.facts) & vpn.DEVICE_FACTS if state.get("intent") == "vpn" else set(action.facts)
            keys = watched_facts & (set(reread) | snapshot)
            changed = sorted(k for k in keys if reread.get(k, _MISSING) != action.facts.get(k, _MISSING))
            if changed:
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B17", event="recheck_failed",
                    audit_detail={**rule, "recheck": "facts_changed", "fields": changed}, exit_code=ExitCode.E5.value,
                    escalation_reason_detail="recheck_failed",
                )  # fmt: skip

        try:  # [4–5]
            res = await deps.executor.execute(state["ticket_id"], run.turn_id, action)
        except ExecutionInterrupted as exc:  # `cause` chỉ là tên lớp lỗi (luật 8.9)
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="exec_interrupted",
                audit_detail={**rule, "success": False, "write_calls": exc.write_calls, "cause": exc.cause,
                              "action_plan_hash_matched": matched},
                exit_code=ExitCode.E7.value, escalation_reason_detail="exec_interrupted", escalation_note=INTERRUPTED_NOTE,
            )  # fmt: skip
        except TurnBudgetExceeded:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="turn_budget_exceeded",
                audit_detail={**rule, "stage": "execute", "write_calls": 0}, exit_code=ExitCode.E2.value,
                escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip
        res = res.model_copy(update={"action_plan_hash_matched": matched})
        if not res.success:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="exec_failed",
                audit_detail={**rule, **_point7(res)}, exit_code=ExitCode.E7.value,
                escalation_reason_detail="exec_failed", execution=res, escalation_note=res.handoff_note,
            )  # fmt: skip

        # [6] B18 — tin theo mẫu (P6), gửi + đặt hạn qua effects.once TRƯỚC node chờ
        try:
            # T24 P4: dòng quyền từ chẩn đoán B6 (dữ liệu tool, qua mẫu) — None = chưa đọc được (Q-T24-5)
            rows = (
                permission_rows((state.get("diagnostics") or {}).get("check_current_permissions"), deps.business_hours.tz)
                if action.type == "view_permissions" else ()
            )  # fmt: skip
            already = is_already_installed(action, res.outputs)  # Q3 M6: máy đã có sẵn → không nói "Đã cài"
            text = (already_installed_text(action, res.outputs) if already
                    else result_text(action, res.outputs, action.facts, requester_id=requester.user_id, rows=rows))  # fmt: skip
            # V10 (soát 12/11, agent 12 M2): đặt hạn TRƯỚC, gửi tin SAU — lỗi/chết ở bước hạn thì người dùng chưa nhận tin "Đã …" rồi lại
            # nhận "Có sự cố…" cùng lượt; hạn treo khi chết chỉ thành `late_event` (vô hại)
            deadline = run.clock.now() + timedelta(hours=deps.constants.CONFIRM_TIMEOUT_HOURS)
            await effects.once(
                state, "deadline_set", deps.deadlines.set, state["ticket_id"], "confirm", deadline, run.turn_id, step="B18",
            )  # fmt: skip
            ref = await effects.once(
                state, "notify_user", deps.notifier.notify_user, state["ticket_id"], text, "confirm", step="B18",
            )  # fmt: skip
        # Sau lời gọi ghi đã thành công, MỌI lỗi phải thành E7 có câu cảnh báo (chốt FAIL mục 7 c), không E9 "xử lý thủ công".
        except Exception as exc:  # noqa: BLE001 — xem dòng trên
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="exec_interrupted",
                audit_detail={**rule, **_point7(res), "stage": "b18", "cause": type(exc).__name__},
                exit_code=ExitCode.E7.value, escalation_reason_detail="exec_interrupted",
                escalation_note=B18_FAILED_NOTE.format(steps=", ".join(res.steps_done) or "—"), execution=res,
            )  # fmt: skip
        return await goto(
            state, S_CONFIRMING, next_node="confirm_wait", step="B18", event="executed_ok",
            audit_detail={**rule, **_point7(res), "already_installed": already}, execution=res,
            conversation=[result_msg(text, ref)],
        )  # fmt: skip

    return b17_execute
