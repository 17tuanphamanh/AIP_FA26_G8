"""L2 đóng ca escalate (B20 mục 4.3) — luật thuần, MỘT nguồn cho `auth.authz`, `db/escalations` và route `/close`.

- 3 kết quả đóng: `completed`, `confirmed_denial`, `reopened_as_new` (= `db.models.CLOSE_RESULTS`, CHECK của `escalations.close_result`).
- `completed` bị cấm cho ca deny (`is_deny_case` — mọi E5, B20 5.1) và cho E5/E6 (B20:303, Q2 `decisions.md`): L2 không hoàn tất hành động bị
  chặn / hết hạn duyệt.
- `close_reason` của ticket (bảng B20:297–301): `completed` → `resolved_after_escalation`; `confirmed_denial`, `reopened_as_new` → theo loại ca:
  ca deny → `resolved_after_deny_review`, còn lại → `resolved_after_escalation`.
"""

from typing import Final, Literal, get_args

from app.domain.exit_codes import CloseReason, ExitCode

type CloseResult = Literal["completed", "confirmed_denial", "reopened_as_new"]
CLOSE_RESULT_VALUES: Final = get_args(CloseResult.__value__)
NO_COMPLETE_EXIT_CODES: Final = frozenset({ExitCode.E5.value, ExitCode.E6.value})


def cannot_complete(result: str, *, exit_code: str, is_deny_case: bool) -> bool:
    return result == "completed" and (is_deny_case or exit_code in NO_COMPLETE_EXIT_CODES)


def close_reason_for(result: CloseResult, *, is_deny_case: bool) -> CloseReason:
    if result != "completed" and is_deny_case:
        return CloseReason.RESOLVED_AFTER_DENY_REVIEW
    return CloseReason.RESOLVED_AFTER_ESCALATION
