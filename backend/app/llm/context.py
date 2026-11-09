"""Context builder: whitelist biến + render + cắt theo `budget_in` (P2 mục 7 [Chốt 17.2]; PLAN-3d Q-3d-8).

- **Whitelist:** biến ngoài `allowed_vars` hoặc thiếu biến → `PromptVariableError` (bug → E9) — cách ép "M5 không đọc
  câu người dùng" ở tầng gateway cho `b14_risk_estimate` (P2 mục 7). Thông điệp chỉ nêu TÊN biến, không giá trị.
- **Render MỘT lượt:** `{{ tên }}` thay bằng giá trị; giá trị không bao giờ bị quét lại → câu người dùng chứa
  `{{ … }}` được giữ nguyên chữ (chống chèn template). Không dùng Jinja (không logic, không thêm phụ thuộc).
- **Biến đặc biệt:** `evidence` (khối `[anchor_chunk_id] title › heading\\n<text>`, 7.4), `recent_messages` (≤ 4 tin
  mới nhất, P2 mục 7). Giá trị khác: chuỗi giữ nguyên, còn lại JSON gọn.
- **Cắt:** ước lượng token vượt `budget_in` → bỏ khối bằng chứng điểm thấp nhất trước, rồi tin nhắn cũ nhất, rồi (chỉ prompt khai
  `trim_vars`, vd. `user_request` của `b11_clarify_question` v4) CẮT ĐUÔI biến chuỗi đó tới độ dài lớn nhất còn vừa trần — ở ranh giới
  từ, nên mặt nạ che (`<SĐT_1>`, `[BÍ_MẬT_ĐÃ_ẨN]`, không có khoảng trắng) không bao giờ bị cắt đôi — thêm "…"; vẫn vượt (kể cả khi
  cắt hết) → `LLMBudgetExceeded` (P2 mục 4 "vượt trần token"), không request nào được gửi. Không bao giờ cắt nhiệm vụ.
  Q1 điểm 2 (ĐP chốt 09/11, bản demo lo-0811): lời gọi truyền `keep_tail={biến: k}` (biến ∈ `trim_vars`) → giữ NGUYÊN `k` ký tự cuối, cắt
  PHẦN ĐẦU phần trước ở ranh giới từ ("…" ở đầu); riêng `k` ký tự cuối đã vượt → bỏ phần đầu rồi cắt đuôi như trên. Dùng cho B3 sau câu hỏi
  phân loại: phần cuối là câu trả lời của người dùng — thông tin chính, không được mất.
- **`random_boundary`:** sinh `boundary` ngẫu nhiên mỗi lần render (b02_injection_judge, 7.4); không trùng giá trị nào.
"""

import json
import re
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
    trimmed_chars: int = 0  # số ký tự bị cắt đuôi khỏi các biến `trim_vars` (chưa ghi vào span/`llm_calls` — không đổi cột DB)


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


_SPACE = re.compile(r"\s")
ELLIPSIS = "…"


def _clip(text: str, n: int) -> str:
    """Phần đầu của `text` dài tối đa `n` ký tự, cắt ở RANH GIỚI TỪ + "…". Không có ranh giới nào trong `n` ký tự → "" (không cắt giữa
    một từ — mặt nạ che không chứa khoảng trắng nên không bao giờ bị cắt đôi). `n ≥ len(text)` → giữ nguyên. Không giảm khi `n` tăng."""
    if n >= len(text):
        return text
    head = text[:n]
    if not text[n].isspace():  # điểm cắt rơi giữa từ → lùi về khoảng trắng gần nhất
        spaces = list(_SPACE.finditer(head))
        head = head[: spaces[-1].start()] if spaces else ""
    head = head.rstrip()
    return head + ELLIPSIS if head else ""


def _longest_fitting(text: str, fits: Callable[[str], bool]) -> str:
    """Bản `_clip` dài nhất của `text` mà `fits` còn đúng; "" nếu ngay cả bản rỗng cũng không vừa. Tìm nhị phân — không giả định công
    thức ước lượng token (`estimate` do `LLMClient` tiêm)."""
    best = ""
    if not fits(""):
        return best
    lo, hi = 0, len(text) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = _clip(text, mid)
        if fits(cand):
            best, lo = cand, mid + 1
        else:
            hi = mid - 1
    return best


def _clip_head(text: str, n: int) -> str:
    """Phần CUỐI của `text` dài tối đa `n` ký tự, bắt đầu ở RANH GIỚI TỪ, đánh dấu "…" ở đầu — đối xứng `_clip`. `n ≥ len(text)` → giữ
    nguyên; không có ranh giới nào → "" (mặt nạ che không chứa khoảng trắng nên không bị cắt đôi)."""
    if n >= len(text):
        return text
    if n <= 0:
        return ""
    start = len(text) - n
    tail = text[start:]
    if not text[start - 1].isspace():  # điểm cắt rơi giữa từ → tiến tới khoảng trắng kế tiếp
        found = _SPACE.search(tail)
        tail = tail[found.end():] if found else ""
    tail = tail.lstrip()
    return ELLIPSIS + tail if tail else ""


def _keep_tail_fitting(text: str, keep: int, fits: Callable[[str], bool]) -> str:
    """Q1 điểm 2 (ĐP chốt 09/11): giữ NGUYÊN `keep` ký tự cuối (câu trả lời phân loại), cắt PHẦN ĐẦU phần trước (câu gốc) ở ranh giới
    từ cho vừa. Riêng phần cuối đã không vừa → bỏ hết phần đầu rồi cắt ĐUÔI phần cuối như `_longest_fitting`."""
    keep = max(0, min(keep, len(text)))
    head, tail = text[: len(text) - keep], text[len(text) - keep :]
    if not fits(tail):
        return _longest_fitting(tail, fits)
    body = head.rstrip()
    sep = head[len(body):]  # dấu ngăn giữa hai phần (xuống dòng) — giữ khi còn phần đầu

    def joined(n: int) -> str:
        part = _clip_head(body, n)
        return part + sep + tail if part else tail

    best, lo, hi = tail, 0, len(body)
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = joined(mid)
        if fits(cand):
            best, lo = cand, mid + 1
        else:
            hi = mid - 1
    return best


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
    keep_tail: Mapping[str, int] | None = None,
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
    trimmed_chars = 0
    trimmable = [n for n in spec.trim_vars if isinstance(variables[n], str)]  # chỉ biến chuỗi — JSON/khối đặc biệt không cắt đuôi
    head_trimmed: set[str] = set()  # Q1 điểm 2: biến đã cắt đầu (keep_tail) — chỉ một lần
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
            return Rendered(msgs, est, trimmed_evidence, trimmed_messages, trimmed_chars)
        if evidence:
            # điểm thấp nhất trước; hoà điểm → khối xếp sau (hạng thấp hơn) bị cắt trước
            evidence.pop(min(range(len(evidence)), key=lambda i: (evidence[i].score, -i)))
            trimmed_evidence += 1
        elif messages:
            messages.pop(0)  # tin cũ nhất
            trimmed_messages += 1
        elif name := next((n for n in trimmable if fixed[n]), None):
            whole = fixed[name]

            def est_with(candidate: str, name: str = name, base: dict[str, str] = values) -> int:
                vals = {**base, name: candidate}
                return estimate(_sub(spec.system, vals)) + estimate(_sub(spec.user, vals))

            keep = (keep_tail or {}).get(name, 0) if name not in head_trimmed else 0
            if keep:  # Q1 điểm 2: cắt đầu, giữ trọn phần cuối (câu trả lời phân loại); một lần cho mỗi biến
                head_trimmed.add(name)
                fixed[name] = _keep_tail_fitting(whole, keep, lambda c: est_with(c) <= budget_in)
            else:
                fixed[name] = _longest_fitting(whole, lambda c: est_with(c) <= budget_in)
            trimmed_chars += max(1, len(whole) - len(fixed[name])) if fixed[name] != whole else 0
            if not fixed[name]:  # cắt hết mà khung vẫn không vừa (hoặc chỉ vừa khi bỏ trống) → không gửi câu hỏi mù
                raise LLMBudgetExceeded(f"{prompt.id}: {est_with('')} token (ước tính) > budget_in {budget_in} sau khi cắt")
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
