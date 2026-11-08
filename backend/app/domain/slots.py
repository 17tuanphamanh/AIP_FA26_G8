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

be-target-guard-2 (ĐP 02/11 13:55): `device_id` CHUẨN HOÁ CHỮ HOA trước khi so mẫu (`lap-0610` → `LAP-0610`) — mã máy so không phân
biệt hoa thường (mẫu trong `config/slots.yaml` giữ nguyên). Có thật trong câu vẫn so không phân biệt hoa thường như trên.
M1 (ĐP 08/11): `canonical_device_id` đưa dạng lỏng ("LAP0012", " lap 0012 ") về dạng chuẩn danh mục `LAP-0012` TRƯỚC khi so mẫu — chỉ khi
khớp ĐÚNG dáng mã máy (2–4 chữ cái ASCII, tuỳ chọn MỘT "-" hoặc dấu cách, 3–5 chữ số ASCII); không khớp → giữ nguyên → sai mẫu → `bad_value`
(B11 hỏi lại, không đoán). `nv…` là mã nhân viên, không bao giờ thành mã máy. Có thật trong câu: mã chuẩn trùng một chuỗi dạng mã máy
trong câu sau cùng phép chuẩn hoá (biên token giữ nguyên — "LAP-00123" không cho "LAP-0012"), hoặc khớp biên token như cũ.

Key do LLM đặt là chữ TỰ DO → `audit_dropped` chỉ ghi key đã khai báo; key lạ thành `"<unknown>"` + đếm (Q-3f-5).
"""

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.facts import FACT_KEYS

MAX_VALUE_LEN = 100  # P1: dài hơn → bỏ cả giá trị
# P2 + Q-3f-3 — hằng CODE, không cấu hình được (sửa slots.yaml không tắt được luật chống bịa slot).
# T20a P5: `target_user`, `resource_path`, `software_name` quyết AI/CÁI GÌ bị tác động — LLM tự điền là đổi đích hành động. Slot chuẩn
# hoá (`account_type`, `permission_level`, `duration`, `action`) không đòi có trong câu; `value_rules` chặn ngoài tập.
TOKEN_IN_TEXT = frozenset({"device_id", "error_code", "target_user", "resource_path"})
PHRASE_IN_TEXT = frozenset({"reason", "software_name"})
MUST_APPEAR_IN_TEXT = TOKEN_IN_TEXT | PHRASE_IN_TEXT
UNKNOWN_KEY = "<unknown>"
# M1: dáng mã máy người dùng gõ — chữ/số ASCII (`\d` của Python khớp cả chữ số Unicode). `[A-Za-z]` không có cờ IGNORECASE: chỉ ASCII.
_DEVICE_LOOSE = re.compile(r"([A-Za-z]{2,4})[- ]?([0-9]{3,5})")
_DEVICE_IN_TEXT = re.compile(r"(?<!\w)([A-Za-z]{2,4})[- ]?([0-9]{3,5})(?!\w)")  # biên \w Unicode: "cổng 443" không khớp
_EMPLOYEE_PREFIX = "nv"  # `nvXXX` = mã nhân viên (domain/target.py) — không đổi thành mã máy

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
    # T20a P4 (Q-T22a-2): slot bắt buộc thêm theo `action` (khoá ∈ action_types, giá trị ⊆ optional).
    required_by_action: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> "IntentSlots":
        keys = self.keys
        if clash := sorted(keys & FACT_KEYS):
            raise ValueError(f"slot trùng tên fact (G-01): {clash}")
        if len(keys) != len(self.required) + len(self.optional):
            raise ValueError("slot khai báo trùng giữa required/optional")
        if extra := sorted(set(self.value_rules) - keys):
            raise ValueError(f"value_rules cho slot không khai báo: {extra}")
        if bad := sorted(set(self.required_by_action) - set(self.action_types)):
            raise ValueError(f"required_by_action cho action không khai báo: {bad}")
        for action, needed in sorted(self.required_by_action.items()):
            if extra := sorted(set(needed) - set(self.optional)):
                raise ValueError(f"required_by_action[{action}] ngoài optional: {extra}")
        return self

    def missing(self, slots: Mapping[str, object]) -> list[str]:
        """T20a P4: slot còn thiếu — `required` rồi (khi đã có `action`) `required_by_action[action]`, theo thứ tự khai báo."""
        action = slots.get("action")
        by_action = self.required_by_action.get(action, ()) if isinstance(action, str) else ()
        return [s for s in (*self.required, *by_action) if s not in slots]

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self.required) | frozenset(self.optional)


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def phrase_in_text(value: str, text: str) -> bool:
    """Đoạn chữ tự do có nằm trong câu người dùng không — sau casefold + gộp khoảng trắng (Q-3f-3 `reason`, Q-3f-4 `span`)."""
    return _squash(value) in _squash(text)


def canonical_device_id(value: str) -> str:
    """M1: "lap-0012" / "LAP0012" / " lap 0012 " → `LAP-0012`. Không đúng dáng mã máy (hoặc tiền tố `nv`) → trả NGUYÊN `value`."""
    m = _DEVICE_LOOSE.fullmatch(value.strip())
    if m is None or m.group(1).casefold() == _EMPLOYEE_PREFIX:
        return value
    return f"{m.group(1).upper()}-{m.group(2)}"


def device_ids_in_text(text: str) -> frozenset[str]:
    """M1: mọi chuỗi dạng mã máy trong câu, đã chuẩn hoá như `canonical_device_id` (bỏ `nv…`)."""
    found = _DEVICE_IN_TEXT.finditer(text)
    return frozenset(f"{m.group(1).upper()}-{m.group(2)}" for m in found if m.group(1).casefold() != _EMPLOYEE_PREFIX)


def in_text(key: str, value: str, text: str) -> bool:
    """Giá trị có thật trong câu người dùng không (P2, Q-3f-3)."""
    if key in PHRASE_IN_TEXT:
        return phrase_in_text(value, text)
    if key == "device_id" and value in device_ids_in_text(text):  # M1: người dùng gõ dạng lỏng
        return True
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
        if k == "device_id":  # be-target-guard-2: không phân biệt hoa thường; M1: dạng lỏng → dạng chuẩn trước khi so mẫu
            value = canonical_device_id(value.upper())
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
