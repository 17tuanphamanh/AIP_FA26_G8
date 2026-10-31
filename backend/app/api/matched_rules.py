"""Các luật khớp ở B13/B14 (`matched_rules`) — MỘT định nghĩa cho trace (khối `policy` của bước B13/B14) và màn duyệt (gốc
`ApprovalView`). Chỉ vai L1/L2/manager đọc được hai route này; route của nhân viên không trả trường này.

- Nguồn: `detail.all_matched` (id luật theo thứ tự trong `policy.json`, `policy_engine.evaluate_rules`) + cột `matched_rule_id` của
  CÙNG dòng audit B13/B14. Thứ tự giữ như `all_matched`.
- `decision`, `description`: tra `rule_id` trong chính sách ĐANG ÁP DỤNG (`rule_index`, cùng hàm trace dùng cho `rule_description`).
  Luật đã bị xoá khỏi chính sách → `decision`/`description` null (Điểm lệch BE Q10).
- `applied`: luật có id = `matched_rule_id` (luật quyết định cuối). Quyết định cuối không do luật (`matched_rule_id` null mà
  `all_matched` không rỗng — vd hybrid_guarded + lỗi AI → E5 `llm_layer_disabled`) → mọi `applied` false (hợp đồng mục 3 cho phép).
- `all_matched` không phải list (dòng không chạy luật: `full_auto`, B12 giả) → None = route BỎ khoá (Q12); không luật nào khớp → [].
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.settings import get_policy

type RuleDecision = Literal["allow", "approval_required", "deny"]
_RULE_ID = re.compile(r"[A-Za-z0-9_.:@/+-]{1,64}")  # cùng mẫu định danh của trace — chuỗi lạ (câu chữ) bị bỏ


@dataclass(frozen=True)
class RuleRef:
    decision: RuleDecision
    description: str


class MatchedRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    description: str | None
    decision: RuleDecision | None
    applied: bool


def rule_index() -> dict[str, RuleRef]:
    """Chính sách đang áp dụng: `rule_id` → (quyết định, mô tả)."""
    return {r.id: RuleRef(r.type, r.description) for r in get_policy().rules}


def matched_rules(all_matched: Any, matched_rule_id: Any, rules: Mapping[str, RuleRef]) -> list[MatchedRule] | None:
    if not isinstance(all_matched, list):
        return None
    out = []
    for rule_id in all_matched:
        if not isinstance(rule_id, str) or not _RULE_ID.fullmatch(rule_id):
            continue
        ref = rules.get(rule_id)
        out.append(MatchedRule(
            rule_id=rule_id, description=ref.description if ref else None, decision=ref.decision if ref else None,
            applied=rule_id == matched_rule_id,
        ))  # fmt: skip
    return out
