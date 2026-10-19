"""Diễn viên của harness G2 (P8 §5.2): `ScriptedUser` trả lời theo `turns`; `SimApprover` làm theo `gold.approver_decision`.

- `ScriptedUser` (cấu trúc thật, g2-chot.md): `turns[0]` = text tạo ticket; mỗi lần B11 hỏi lại gửi `reply` KẾ TIẾP THEO THỨ TỰ của
  các phần tử `{on_question_about, reply}` — slot đang hỏi KHÔNG lộ qua API (`TicketView`, `api/tickets.py:134-147`; `conversation`
  chỉ có chữ câu hỏi — `b11_slots.py:184`), chỉ ở `detail.missing` (khoá cấm) → TODO(G2-Q19). Hết reply → `None` (runner chờ tới hạn
  kịch bản rồi ghi `timeout`). B11 hỏi ≤ 2 slot mỗi lượt (`b11_slots.py:150`): gửi tuần tự từng câu, không ghép. Bước xác nhận dùng
  `{on_confirm}` kế tiếp theo thứ tự; hết → "Đã ổn" + `confirm_default = True` (đếm ở manifest).
- `SimApprover`: phiếu `pending` → người được giao (`approvals.approver_id` → `users.username`) → đăng nhập bằng mật khẩu harness
  (`EVAL_PASSWORD`, không hằng trong `app/`) → quyết. `reject` gửi ghi chú cố định (`rejected` thiếu `note` → 422,
  `api/approvals.py:199-200`). `ignore` không gọi gì: worker bắn E6 khi hết `APPROVAL_SLA_MINUTES_DEV`.
"""

from dataclasses import dataclass
from typing import Literal

from app.eval.dataset import ApproverDecision, Scenario
from app.eval.stack import Api, Sql, StackError, pending_approval, username_of

REJECT_NOTE = "eval: sim_approver reject"
DEFAULT_ON_CONFIRM = True  # hết `{on_confirm}` trong kịch bản → "Đã ổn"

type ApproverAction = Literal["approved", "rejected", "ignored"]


class ScriptedUser:
    def __init__(self, scenario: Scenario) -> None:
        self._opening = scenario.opening
        self._replies = list(scenario.replies)
        self._confirms = list(scenario.confirms)
        self.confirm_default = False

    @property
    def first_text(self) -> str:
        return self._opening

    def next_answer(self) -> str | None:
        if not self._replies:
            return None
        return self._replies.pop(0)

    def next_confirm(self) -> bool:
        if self._confirms:
            return self._confirms.pop(0)
        self.confirm_default = True
        return DEFAULT_ON_CONFIRM


@dataclass
class SimApprover:
    api: Api
    sql: Sql
    password: str

    def act(self, ticket_id: str, decision: ApproverDecision) -> ApproverAction:
        if decision == "ignore":
            return "ignored"
        found = pending_approval(self.sql, ticket_id)
        if found is None:
            raise StackError("chờ duyệt nhưng không có phiếu pending")
        approval_id, approver_id = found
        username = username_of(self.sql, approver_id)
        if username is None:
            raise StackError("người duyệt được giao không có dòng users")
        headers = self.api.login(username, self.password)
        if decision == "reject":
            self.api.decide(headers, approval_id, "rejected", REJECT_NOTE)
            return "rejected"
        self.api.decide(headers, approval_id, "approved")
        return "approved"
