"""14 trạng thái và luật chuyển — NGU-CANH-DAY-DU.md Phần IV mục 2, P1 mục 5.1.1 (D-29).

Thứ tự kiểm ở check_transition: is_allowed (bảng 2.1 + 3 quy tắc D-29) rồi FORBIDDEN — 6 chuyển
cấm [Chốt 2.2] kiểm sau và luôn thắng. Không thêm trạng thái mới (docs/spec/CLAUDE.md mục 4).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.core.errors import DomainError
from app.core.hashing import hash_action

S_NEW: Final = "S_NEW"
S_SCREENING: Final = "S_SCREENING"
S_CLASSIFYING: Final = "S_CLASSIFYING"
S_DIAGNOSING: Final = "S_DIAGNOSING"
S_RETRIEVING: Final = "S_RETRIEVING"
S_CLARIFYING: Final = "S_CLARIFYING"
S_ASSESSING: Final = "S_ASSESSING"
S_PENDING_APPROVAL: Final = "S_PENDING_APPROVAL"
S_EXECUTING: Final = "S_EXECUTING"
S_CONFIRMING: Final = "S_CONFIRMING"
S_ESCALATED: Final = "S_ESCALATED"
S_RESOLVED: Final = "S_RESOLVED"
S_REJECTED: Final = "S_REJECTED"
S_BLOCKED: Final = "S_BLOCKED"

ALL_STATES: Final = frozenset({
    S_NEW, S_SCREENING, S_CLASSIFYING, S_DIAGNOSING, S_RETRIEVING, S_CLARIFYING, S_ASSESSING,
    S_PENDING_APPROVAL, S_EXECUTING, S_CONFIRMING, S_ESCALATED, S_RESOLVED, S_REJECTED, S_BLOCKED,
})  # fmt: skip
TERMINAL: Final = frozenset({S_RESOLVED, S_REJECTED, S_BLOCKED})  # S_ESCALATED do L2 đóng
PROCESSING: Final = frozenset({
    S_NEW, S_SCREENING, S_CLASSIFYING, S_DIAGNOSING, S_RETRIEVING, S_ASSESSING, S_EXECUTING,
})  # fmt: skip
WAITING: Final = frozenset({S_CLARIFYING, S_PENDING_APPROVAL, S_CONFIRMING})

type Transition = tuple[str, str]

# Bảng 2.1 [Chốt] — 31 dòng, 27 cặp khác nhau (nhiều dòng chỉ khác sự kiện) + 2 cặp D-75 (lô Q1) + 1 cặp D-78 (lô Q13a) = 30 cặp.
TABLE_2_1: Final[frozenset[Transition]] = frozenset({
    (S_NEW, S_SCREENING),                 # B1 xác thực thành công
    (S_NEW, S_BLOCKED),                   # B1 invalid_credentials / repeated_auth_failure
    (S_SCREENING, S_CLASSIFYING),         # B2 không có injection
    (S_SCREENING, S_BLOCKED),             # B2 injection_detected → E0
    (S_CLASSIFYING, S_DIAGNOSING),        # B3–B5 một yêu cầu
    (S_CLASSIFYING, S_CLASSIFYING),       # B5 nhiều yêu cầu (ticket con)
    (S_CLASSIFYING, S_ESCALATED),         # B4 ngoài phạm vi → E1
    (S_DIAGNOSING, S_RETRIEVING),         # B6–B7 tool bình thường
    (S_DIAGNOSING, S_ESCALATED),          # B7 tool lỗi / B6 vượt vòng lặp → E2
    (S_RETRIEVING, S_CONFIRMING),         # B9–B10 chỉ cần thông tin
    (S_RETRIEVING, S_ASSESSING),          # B9–B11 cần hành động, đủ thông tin
    (S_RETRIEVING, S_CLARIFYING),         # B11 thiếu thông tin
    (S_RETRIEVING, S_ESCALATED),          # B9 → E3 / B8 → E2
    (S_CLARIFYING, S_ASSESSING),          # B11 trả lời đã đủ
    (S_CLARIFYING, S_CLARIFYING),         # B11 vẫn thiếu, lượt < 3
    (S_CLARIFYING, S_ESCALATED),          # B11 hỏi đủ 3 lượt / quá 24h → E4
    (S_ASSESSING, S_EXECUTING),           # B13–B14 rủi ro thấp
    (S_ASSESSING, S_PENDING_APPROVAL),    # B13–B15 rủi ro trung bình
    (S_ASSESSING, S_ESCALATED),           # B14 rủi ro cao → E5
    (S_PENDING_APPROVAL, S_EXECUTING),    # B16 đồng ý
    (S_PENDING_APPROVAL, S_REJECTED),     # B16 từ chối
    (S_PENDING_APPROVAL, S_ESCALATED),    # B16 hết SLA → E6
    (S_EXECUTING, S_CONFIRMING),          # B17 thành công
    (S_EXECUTING, S_ESCALATED),           # B17 lỗi → E7 / hash lệch → E5
    (S_CONFIRMING, S_RESOLVED),           # B19 xác nhận / im lặng 48h
    (S_CONFIRMING, S_ESCALATED),          # B19 báo chưa xong → E8
    (S_ESCALATED, S_RESOLVED),            # L2 xử lý xong
    # D-75 (ĐP chốt 09/11, bản demo lo-0811 — lô Q1, TC11): B3 hỏi MỘT câu phân loại khi yêu cầu mơ hồ; câu trả lời quay lại B2
    # sàng lọc ĐẦY ĐỦ câu ghép. 6 chuyển cấm không đổi (F5 vẫn chỉ cho B2 ra S_CLASSIFYING / S_BLOCKED / S_ESCALATED).
    (S_CLASSIFYING, S_CLARIFYING),        # B3 hỏi phân loại (`triage_asked`)
    (S_CLARIFYING, S_SCREENING),          # trả lời câu hỏi phân loại → B2 (`triage_reply`)
    # D-78 (11/11, bản nộp main — lô Q13a): "Chưa ổn" + ghi chú sau câu trả lời KB → ghi chú ghép vào câu gốc, quay lại B2 sàng lọc
    # ĐẦY ĐỦ (tối đa 2 vòng/ticket). F5 không đổi: B2 vẫn chỉ ra S_CLASSIFYING / S_BLOCKED / S_ESCALATED.
    (S_CONFIRMING, S_SCREENING),          # B19 hỏi tiếp sau câu trả lời KB (`followup_reply`)
})  # fmt: skip

# D-20: chỉ thêm khi cờ REDIAGNOSE_ON_NEW_SLOT bật (mặc định tắt).
REDIAGNOSE_TRANSITION: Final[Transition] = (S_CLARIFYING, S_DIAGNOSING)

# Quy tắc 3 — chỉ hợp lệ khi state["is_parent"] (D-31).
PARENT_ONLY: Final[frozenset[Transition]] = frozenset({
    (S_CLASSIFYING, S_CONFIRMING),
    (S_CONFIRMING, S_CLASSIFYING),
    *((a, b) for a in (S_CLASSIFYING, S_CONFIRMING) for b in (S_RESOLVED, S_REJECTED, S_ESCALATED)),
})  # fmt: skip


def is_allowed(
    state: Mapping[str, Any], frm: str, to: str, *, rediagnose_on_new_slot: bool = False
) -> bool:
    """Bảng 2.1 + 3 quy tắc D-29. Chưa xét FORBIDDEN — dùng check_transition."""
    if (frm, to) in TABLE_2_1:
        return True
    if rediagnose_on_new_slot and (frm, to) == REDIAGNOSE_TRANSITION:
        return True
    if frm == to and frm in PROCESSING:  # quy tắc 1: chỉ đổi `next`
        return True
    if to == S_ESCALATED and frm in ALL_STATES and frm not in TERMINAL | {S_ESCALATED}:
        return True  # quy tắc 2: hướng an toàn (E2, E9)
    return bool(state.get("is_parent")) and (frm, to) in PARENT_ONLY  # quy tắc 3


# ---- 6 chuyển bị cấm [Chốt 2.2] -------------------------------------------------------------

type ForbiddenCheck = Callable[[Mapping[str, Any], str, str, str, str], bool]


@dataclass(frozen=True)
class ForbiddenRule:
    id: str
    description: str
    matches: ForbiddenCheck  # (view, frm, to, step, event) -> True nếu bị cấm


def _field(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _plan_hash_differs(view: Mapping[str, Any]) -> bool:
    # Thiếu Action hoặc thiếu hash lúc duyệt → không chứng minh được "cùng ActionPlan" → cấm.
    action, approved_hash = view.get("intended_action"), view.get("action_plan_hash")
    if action is None or not approved_hash:
        return True
    return hash_action(action) != approved_hash


def _plan_hash_same(view: Mapping[str, Any]) -> bool:
    action, approved_hash = view.get("intended_action"), view.get("action_plan_hash")
    return action is not None and bool(approved_hash) and hash_action(action) == approved_hash


FORBIDDEN: Final[tuple[ForbiddenRule, ...]] = (
    ForbiddenRule(
        "F1_rule_bypass",
        "S_ASSESSING → S_EXECUTING khi khớp deny hoặc approval_required",
        lambda v, frm, to, step, event: (frm, to) == (S_ASSESSING, S_EXECUTING)
        and _field(v.get("risk"), "policy_decision") in {"deny", "approval_required"},
    ),
    ForbiddenRule(
        "F2_no_approval",
        # Fail-safe: không có bằng chứng "approved" (hết SLA, hoặc thiếu hẳn) đều bị chặn.
        "S_PENDING_APPROVAL → S_EXECUTING khi hết SLA (không có approval_result=approved)",
        lambda v, frm, to, step, event: (frm, to) == (S_PENDING_APPROVAL, S_EXECUTING)
        and v.get("approval_result") != "approved",
    ),
    ForbiddenRule(
        "F3_plan_hash_mismatch",
        "S_PENDING_APPROVAL → S_EXECUTING khi action_plan_hash khác lúc duyệt",
        lambda v, frm, to, step, event: (frm, to) == (S_PENDING_APPROVAL, S_EXECUTING)
        and _plan_hash_differs(v),
    ),
    ForbiddenRule(
        "F4_resolved_without_log",
        # Ở domain chỉ kiểm được "có step/event để ghi audit"; ghi audit thật do goto() (Phase 2).
        "Bất kỳ → S_RESOLVED mà không qua ghi log",
        lambda v, frm, to, step, event: to == S_RESOLVED and not (step and event),
    ),
    ForbiddenRule(
        "F5_screening_bypass",
        # Nới theo D-29 (chốt 25/09/2026): thêm S_ESCALATED cho E2/E9.
        "S_SCREENING → bất kỳ đâu ngoài S_CLASSIFYING, S_BLOCKED hoặc S_ESCALATED",
        lambda v, frm, to, step, event: frm == S_SCREENING
        and to not in {S_CLASSIFYING, S_BLOCKED, S_ESCALATED},
    ),
    ForbiddenRule(
        "F6_reexecute_denied",
        "S_ESCALATED (E5) → S_EXECUTING của cùng intended_action/action_plan_hash",
        lambda v, frm, to, step, event: (frm, to) == (S_ESCALATED, S_EXECUTING)
        and v.get("exit_code") == "E5"
        and _plan_hash_same(v),
    ),
)


class IllegalTransition(DomainError):
    def __init__(self, frm: str, to: str, rule_id: str | None = None) -> None:
        self.frm, self.to, self.rule_id = frm, to, rule_id
        why = f"bị cấm ({rule_id})" if rule_id else "không có trong bảng chuyển"
        super().__init__(f"{frm} → {to}: {why}")


def forbidden_rule(
    state: Mapping[str, Any],
    frm: str,
    to: str,
    *,
    step: str,
    event: str,
    fields: Mapping[str, Any] | None = None,
) -> ForbiddenRule | None:
    """Luật cấm đầu tiên khớp, xét trên state sau khi áp `fields` mà goto() sắp ghi."""
    view = {**state, **(fields or {})}
    return next((r for r in FORBIDDEN if r.matches(view, frm, to, step, event)), None)


def check_transition(
    state: Mapping[str, Any],
    frm: str,
    to: str,
    *,
    step: str,
    event: str,
    fields: Mapping[str, Any] | None = None,
    rediagnose_on_new_slot: bool = False,
) -> None:
    """Ném IllegalTransition nếu chuyển không hợp lệ. FORBIDDEN luôn thắng is_allowed."""
    rule = forbidden_rule(state, frm, to, step=step, event=event, fields=fields)
    if rule is not None:
        raise IllegalTransition(frm, to, rule.id)
    if not is_allowed(
        {**state, **(fields or {})}, frm, to, rediagnose_on_new_slot=rediagnose_on_new_slot
    ):
        raise IllegalTransition(frm, to)
