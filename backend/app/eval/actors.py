"""Diễn viên của harness G2 (P8 §5.2): `ScriptedUser` trả lời theo `turns`; `SimApprover` làm theo `gold.approver_decision`.

- `ScriptedUser`: câu 1 = text tạo ticket; mỗi lần B11 hỏi lại gửi câu kế tiếp; hết câu → `None` (runner chờ tới hạn kịch bản rồi
  ghi `timeout` — không chờ 24 giờ). B11 hỏi ≤ 2 slot mỗi lượt (`graph/nodes/b11_slots.py:150`): bản 20/10 gửi tuần tự từng câu,
  không ghép 2 câu (cắt theo plan G2 mục 9).
- `SimApprover`: phiếu `pending` → người được giao (`approvals.approver_id` → `users.username`) → đăng nhập bằng mật khẩu harness
  (`EVAL_PASSWORD`, không hằng trong `app/`) → quyết. `reject` gửi ghi chú cố định (`rejected` thiếu `note` → 422,
  `api/approvals.py:199-200`). `ignore` không gọi gì: worker bắn E6 khi hết `APPROVAL_SLA_MINUTES_DEV`.
"""

from dataclasses import dataclass
from typing import Literal

from app.eval.dataset import ApproverDecision, Scenario
from app.eval.stack import Api, Sql, StackError, pending_approval, username_of

REJECT_NOTE = "eval: sim_approver reject"
DEFAULT_DECISION: ApproverDecision = "approve"  # TODO(G2-Q6): ca tới chờ duyệt mà gold không có approver_decision
DEFAULT_ON_CONFIRM = True  # TODO(G2-Q8): thiếu on_confirm → "Đã ổn"

type ApproverAction = Literal["approved", "rejected", "ignored"]


class ScriptedUser:
    def __init__(self, scenario: Scenario) -> None:
        self._turns = scenario.turns
        self._sent = 1  # câu 1 là text tạo ticket

    @property
    def first_text(self) -> str:
        return self._turns[0].text

    def next_answer(self) -> str | None:
        if self._sent >= len(self._turns):
            return None
        self._sent += 1
        return self._turns[self._sent - 1].text

    @property
    def on_confirm(self) -> bool:
        """TODO(G2-Q8): `on_confirm` của câu ĐÃ GỬI gần nhất có đặt; không câu nào đặt → mặc định."""
        for turn in reversed(self._turns[: self._sent]):
            if turn.on_confirm is not None:
                return turn.on_confirm
        return DEFAULT_ON_CONFIRM


@dataclass
class SimApprover:
    api: Api
    sql: Sql
    password: str

    def act(self, ticket_id: str, decision: ApproverDecision | None) -> ApproverAction:
        decision = decision or DEFAULT_DECISION
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
