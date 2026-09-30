"""Context builder: whitelist biến + render + cắt theo `budget_in` (P2 mục 7 [Chốt 17.2]; PLAN-3d Q-3d-8).

- **Whitelist:** biến ngoài `allowed_vars` hoặc thiếu biến → `PromptVariableError` (bug → E9) — cách ép "M5 không đọc
  câu người dùng" ở tầng gateway cho `b14_risk_estimate` (P2 mục 7). Thông điệp chỉ nêu TÊN biến, không giá trị.
- **Render MỘT lượt:** `{{ tên }}` thay bằng giá trị; giá trị không bao giờ bị quét lại → câu người dùng chứa
  `{{ … }}` được giữ nguyên chữ (chống chèn template). Không dùng Jinja (không logic, không thêm phụ thuộc).
- **Biến đặc biệt:** `evidence` (khối `[anchor_chunk_id] title › heading\\n<text>`, 7.4), `recent_messages` (≤ 4 tin
  mới nhất, P2 mục 7). Giá trị khác: chuỗi giữ nguyên, còn lại JSON gọn.
- **Cắt:** ước lượng token vượt `budget_in` → bỏ khối bằng chứng điểm thấp nhất trước, rồi tin nhắn cũ nhất; vẫn vượt
  → `LLMBudgetExceeded` (P2 mục 4 "vượt trần token"), không request nào được gửi. Không bao giờ cắt nhiệm vụ.
- **`random_boundary`:** sinh `boundary` ngẫu nhiên mỗi lần render (b02_injection_judge, 7.4); không trùng giá trị nào.
"""

import json
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.llm.errors import LLMBudgetExceeded, PromptVariableError
from app.llm.registry import BOUNDARY_VAR, PLACEHOLDER, Prompt

EVIDENCE_VAR = "evidence"
MESSAGES_VAR = "recent_messages"
MAX_RECENT_MESSAGES = 4  # P2 mục 7 [Chốt 17.2]
EMPTY = "(không có)"

type TokenEstimator = Callable[[str], int]
type BoundaryFactory = Callable[[], str]


def estimate_tokens(text: str) -> int:
    """ceil(số ký tự / 3) — ƯỚC TÍNH, chưa đo trên tokenizer của LLM (chưa chọn, mốc G; Q-3d-8). Span ghi kèm
    `usage.prompt_tokens` thật để hiệu chỉnh."""
    return -(-len(text) // 3)


def new_boundary() -> str:
    return secrets.token_hex(8)


@dataclass(frozen=True)
class Rendered:
    messages: list[dict[str, str]]  # [system, user]
    est_tokens: int
    trimmed_evidence: int  # số khối bằng chứng bị cắt
    trimmed_messages: int  # số tin nhắn cũ bị cắt (ngoài phần vượt MAX_RECENT_MESSAGES)


@dataclass(frozen=True)
class _Evidence:
    anchor_chunk_id: str
    title: str
    heading_path: str
    text: str
    score: float


def _field(item: Any, name: str) -> Any:
    return item[name] if isinstance(item, Mapping) else getattr(item, name)


def _evidence(items: Sequence[Any]) -> list[_Evidence]:
    return [
        _Evidence(str(_field(i, "anchor_chunk_id")), str(_field(i, "title")), str(_field(i, "heading_path")),
                  str(_field(i, "text")), float(_field(i, "score")))
        for i in items
    ]  # fmt: skip


def _fmt_evidence(blocks: Sequence[_Evidence]) -> str:
    return "\n\n".join(f"[{b.anchor_chunk_id}] {b.title} › {b.heading_path}\n{b.text}" for b in blocks) or EMPTY


def _fmt_messages(messages: Sequence[Any]) -> str:
    return "\n".join(f"{_field(m, 'role')}: {_field(m, 'text')}" for m in messages) or EMPTY


def _fmt(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sub(template: str, values: Mapping[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], template)  # re.sub không quét lại chuỗi thay vào


def check_variables(prompt: Prompt, variables: Mapping[str, Any]) -> None:
    allowed, given = set(prompt.spec.allowed_vars), set(variables)
    extra, missing = sorted(given - allowed), sorted(allowed - given)
    if extra or missing:
        raise PromptVariableError(f"{prompt.id}: biến ngoài allowed_vars {extra}, thiếu biến {missing}")


def render(
    prompt: Prompt,
    variables: Mapping[str, Any],
    *,
    budget_in: int,
    estimate: TokenEstimator = estimate_tokens,
    boundary: BoundaryFactory = new_boundary,
) -> Rendered:
    check_variables(prompt, variables)
    spec = prompt.spec
    fixed = {k: _fmt(v) for k, v in variables.items() if k not in (EVIDENCE_VAR, MESSAGES_VAR)}
    evidence = _evidence(variables[EVIDENCE_VAR] or []) if EVIDENCE_VAR in variables else None
    messages = list(variables[MESSAGES_VAR] or []) if MESSAGES_VAR in variables else None
    trimmed_messages = 0
    if messages is not None and len(messages) > MAX_RECENT_MESSAGES:
        messages = messages[-MAX_RECENT_MESSAGES:]
    trimmed_evidence = 0
    mark: str | None = None
    while True:
        values = dict(fixed)
        if evidence is not None:
            values[EVIDENCE_VAR] = _fmt_evidence(evidence)
        if messages is not None:
            values[MESSAGES_VAR] = _fmt_messages(messages)
        if spec.random_boundary:
            while mark is None or any(mark in v for v in values.values()):
                mark = boundary()
            values[BOUNDARY_VAR] = mark
        system, user = _sub(spec.system, values), _sub(spec.user, values)
        est = estimate(system) + estimate(user)
        if est <= budget_in:
            msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            return Rendered(msgs, est, trimmed_evidence, trimmed_messages)
        if evidence:
            # điểm thấp nhất trước; hoà điểm → khối xếp sau (hạng thấp hơn) bị cắt trước
            evidence.pop(min(range(len(evidence)), key=lambda i: (evidence[i].score, -i)))
            trimmed_evidence += 1
        elif messages:
            messages.pop(0)  # tin cũ nhất
            trimmed_messages += 1
        else:
            raise LLMBudgetExceeded(f"{prompt.id}: {est} token (ước tính) > budget_in {budget_in} sau khi cắt")


def check_evidence_budget(prompt: Prompt, budget_in: int, evidence_max_tokens: int) -> None:
    """f1 (PLAN-3g): khung prompt (bỏ mọi biến) + trần bằng chứng `RAG_EVIDENCE_MAX_TOKENS` phải ≤ `budget_in` của vai trò —
    kiểm lúc khởi động. ƯỚC TÍNH, hai đơn vị: khung đếm `ceil(ký tự/3)` như gateway, bằng chứng đếm token tokenizer bge-m3
    (chưa đo tỉ lệ). Lúc chạy gateway vẫn có thể cắt khối (câu hỏi dài, tỉ lệ khác) → B10 ra E3 `invalid_citation` với
    `evidence_truncated=true` (không đoán anchor)."""
    frame = estimate_tokens(PLACEHOLDER.sub("", prompt.spec.system)) + estimate_tokens(PLACEHOLDER.sub("", prompt.spec.user))
    if frame + evidence_max_tokens > budget_in:
        raise ValueError(
            f"{prompt.id}: khung ~{frame} + RAG_EVIDENCE_MAX_TOKENS {evidence_max_tokens} > budget_in {budget_in} "
            "— từ chối khởi động"
        )
