"""Hàm quyết định của B2 sau L3/L4 (gói 1, D-52; bảng 4.2 của `dac-ta-bat-2-model.md`) — thuần, không import `graph/`.

Node `b02_screen` lo dòng #1 (regex, trước L3), #8 (lỗi LLM → E2), #9 (hết hạn lượt → E2), #10 (`MlContractError` → E9 ở
boundary). Ở đây:

- `classifier_shortcut`: CHỈ `active` (D-44, giữ trong code, không dùng): `p_mal ≥ TAU_BLOCK` → E0, `≤ TAU_PASS` → qua, không
  gọi LLM. `shadow` và `review` không bao giờ quyết thẳng theo điểm — mọi câu không khớp regex đều xuống L4.
- `after_judge` (sau khi LLM chấm trả lời):
  - `is_attack` HOẶC `category ≠ none` → E0 `llm` (#2, #3 — #3 áp MỌI chế độ: cách hiểu an toàn hơn);
  - `review`: `p_mal ≥ τ` (biên p = τ → E1) HOẶC `ml_error = too_many_windows` → E1 `injection_suspected`, lớp `classifier`
    (#4, #5); còn lại (p < τ, lỗi hạ tầng, model chưa nạp) → qua `llm` (#6, #7);
  - `shadow`, `active`: qua `llm` (hành vi cũ).
- `p_mal` NaN/inf → `ValueError` (phòng thủ; `MlClient` đã đổi thành `MlContractError` → E9, bảng 4.2 #10).
"""

import math
from dataclasses import dataclass
from typing import Literal

from app.guard.injection import TAU_BLOCK, TAU_PASS

type ClfMode = Literal["shadow", "active", "review"]
TOO_MANY_WINDOWS = "too_many_windows"  # 422 của /classify: văn bản dài bất thường → coi là đáng ngờ (#5)


@dataclass(frozen=True)
class Verdict:
    outcome: Literal["E0", "E1", "pass"]
    layer: Literal["classifier", "llm"]


def classifier_shortcut(mode: ClfMode, p_mal: float | None) -> Verdict | None:
    if mode != "active" or p_mal is None:
        return None
    if p_mal >= TAU_BLOCK:
        return Verdict("E0", "classifier")
    if p_mal <= TAU_PASS:
        return Verdict("pass", "classifier")
    return None


def after_judge(
    mode: ClfMode, *, p_mal: float | None, ml_error: str | None, is_attack: bool, category: str, tau: float | None
) -> Verdict:
    if p_mal is not None and not math.isfinite(p_mal):  # client đã chặn (#10); ở đây chỉ phòng thủ — không lặng lẽ cho qua
        raise ValueError("p_mal không hữu hạn — lỗi hợp đồng ml-service (E9)")
    if is_attack or category != "none":
        return Verdict("E0", "llm")
    if mode == "review":
        if tau is None:
            raise ValueError("chế độ review cần τ (B2_TAU_REVIEW) — Settings phải đã từ chối khởi động")
        if (p_mal is not None and p_mal >= tau) or ml_error == TOO_MANY_WINDOWS:
            return Verdict("E1", "classifier")
    return Verdict("pass", "llm")
