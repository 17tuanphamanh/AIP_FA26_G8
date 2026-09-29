"""slots — THAM SỐ do người dùng (qua LLM) hoặc chẩn đoán cung cấp để dựng hành động (phase3 mục 3.2, 3-Q1 — vá G-01).

Slot có thể sai hoặc bị bịa → KHÔNG BAO GIỜ là căn cứ cho luật (đó là `domain/facts.py`). Mọi chỗ nhận slot từ LLM (B3,
B11) đi qua `sanitize_slots` — hàm thuần, không đọc file (schema `IntentSlots` nạp từ `config/slots.yaml` ở
`settings.SlotsFile`), không bao giờ raise vì dữ liệu người dùng. Thứ tự loại (mỗi key một lý do):

1. key thuộc `FACT_KEYS` → `fact_key` (người dùng "nói" dữ kiện: "device_registered=true") — audit `slot_fact_collision`;
2. key ngoài required ∪ optional của intent (hoặc ngoài `allowed`) → `unknown_key`;
3. giá trị rỗng → `bad_value`; dài > 100 ký tự → `too_long` (BỎ, không cắt — P1);
4. `action` ngoài `action_types` → `bad_action`; sai `value_rules` → `bad_value`;
5. key thuộc `MUST_APPEAR_IN_TEXT` mà giá trị không có trong câu người dùng → `slot_not_in_text` (chống LLM bịa slot —
   P2, Q-3f-3). Mã (`device_id`, `error_code`): khớp theo BIÊN TOKEN, không phân biệt hoa thường ("LAP-04171" không cho
   "LAP-0417"). `reason` (chữ tự do): đoạn con sau chuẩn hoá casefold + gộp khoảng trắng — câu người dùng đã qua guard
   nên `reason` giữ lại cũng đã được che (luật chung 8.9).

Key do LLM đặt là chữ TỰ DO → `audit_dropped` chỉ ghi key đã khai báo; key lạ thành `"<unknown>"` + đếm (Q-3f-5).
"""

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.facts import FACT_KEYS

MAX_VALUE_LEN = 100  # P1: dài hơn → bỏ cả giá trị
# P2 + Q-3f-3 — hằng CODE, không cấu hình được (sửa slots.yaml không tắt được luật chống bịa slot).
TOKEN_IN_TEXT = frozenset({"device_id", "error_code"})
PHRASE_IN_TEXT = frozenset({"reason"})
MUST_APPEAR_IN_TEXT = TOKEN_IN_TEXT | PHRASE_IN_TEXT
UNKNOWN_KEY = "<unknown>"

type DropReason = Literal["fact_key", "unknown_key", "too_long", "bad_action", "bad_value", "slot_not_in_text"]


class ValueRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: str | None = None  # fullmatch
    max_len: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_rule(self) -> "ValueRule":
        if self.pattern is None and self.max_len is None:
            raise ValueError("value_rule cần pattern hoặc max_len")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as e:  # regex hỏng → lỗi schema → không khởi động
                raise ValueError(f"value_rule pattern hỏng: {e}") from e
        return self

    def ok(self, value: str) -> bool:
        if self.max_len is not None and len(value) > self.max_len:
            return False
        return self.pattern is None or re.fullmatch(self.pattern, value) is not None


class IntentSlots(BaseModel):
    """Một mục `intents.<tên>` của `config/slots.yaml`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required: tuple[str, ...] = Field(min_length=1)
    optional: tuple[str, ...] = ()
    action_types: tuple[str, ...] = Field(min_length=1)
    value_rules: dict[str, ValueRule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> "IntentSlots":
        keys = self.keys
        if clash := sorted(keys & FACT_KEYS):
            raise ValueError(f"slot trùng tên fact (G-01): {clash}")
        if len(keys) != len(self.required) + len(self.optional):
            raise ValueError("slot khai báo trùng giữa required/optional")
        if extra := sorted(set(self.value_rules) - keys):
            raise ValueError(f"value_rules cho slot không khai báo: {extra}")
        return self

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self.required) | frozenset(self.optional)


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def in_text(key: str, value: str, text: str) -> bool:
    """Giá trị có thật trong câu người dùng không (P2, Q-3f-3)."""
    if key in PHRASE_IN_TEXT:
        return _squash(value) in _squash(text)
    return re.search(rf"(?<!\w){re.escape(value.casefold())}(?!\w)", text.casefold()) is not None


def sanitize_slots(
    spec: IntentSlots, raw: Mapping[str, object], *, text: str, allowed: frozenset[str] | None = None
) -> tuple[dict[str, str], dict[str, DropReason]]:
    """(slot sạch, key bị bỏ → lý do). `text` = câu người dùng đã qua guard + L0 (`redacted_request`). `allowed`: B11 chỉ
    nhận slot đang hỏi. Không bao giờ raise vì dữ liệu người dùng."""
    keep = spec.keys if allowed is None else allowed & spec.keys
    clean: dict[str, str] = {}
    dropped: dict[str, DropReason] = {}
    for key, raw_value in raw.items():
        k = str(key)
        if k in FACT_KEYS:
            dropped[k] = "fact_key"
            continue
        if k not in keep:
            dropped[k] = "unknown_key"
            continue
        value = str(raw_value).strip()
        if len(value) > MAX_VALUE_LEN:
            dropped[k] = "too_long"
        elif not value:
            dropped[k] = "bad_value"
        elif k == "action" and value not in spec.action_types:
            dropped[k] = "bad_action"
        elif (rule := spec.value_rules.get(k)) is not None and not rule.ok(value):
            dropped[k] = "bad_value"
        elif k in MUST_APPEAR_IN_TEXT and not in_text(k, value, text):
            dropped[k] = "slot_not_in_text"
        else:
            clean[k] = value
    return clean, dropped


def audit_dropped(dropped: Mapping[str, DropReason], known: frozenset[str]) -> dict[str, object]:
    """Phần điểm log 1 về slot bị bỏ — KHÔNG chép key lạ (chữ tự do của LLM) vào audit (Q-3f-5)."""
    listed = known | FACT_KEYS
    keys = sorted({k if k in listed else UNKNOWN_KEY for k in dropped})
    return {
        "dropped_slot_keys": keys,
        "dropped_slot_reasons": {k: r for k, r in sorted(dropped.items()) if k in listed},
        "dropped_unknown_count": sum(1 for k in dropped if k not in listed),
        "slot_fact_collision": any(k in FACT_KEYS for k in dropped),
    }
