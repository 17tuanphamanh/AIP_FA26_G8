"""Luật M5 dạng dữ liệu (`config/policy.json`) + DSL điều kiện THUẦN — B12-B14 mục 4.2, phase3 mục 11.2, PLAN-3h.

**Hình dạng một luật** (B12 §4.2 + mở rộng 11.2): `{"id", "type", "intent", "action": chuỗi | danh sách, "conditions":
{"all" | "any": [điều kiện | nhóm lồng]}, "description"}`; điều kiện `{"fact": "<nguồn>.<tên>", "op", "value"?}`.

**Nguồn fact** (danh sách TRẮNG — tên ngoài danh sách → nạp policy thất bại, không khởi động): `action.*` (trường của
`Action`), `action.facts.*` (chỉ `FACT_KEYS`), `requester.*` (`RequesterContext`), `time.*` (`within_business_hours`),
`ctx.*` (`target_is_other`). Không có nguồn nào chứa câu người dùng, slot hay hội thoại.

**Lúc chạy** [Chốt]: fact thiếu → điều kiện SAI (kể cả `is_false`, `ne`, `not_in`) — luật `allow` không bao giờ khớp nhờ
thiếu dữ liệu. Kiểu chặt: `bool` không so bằng/không so lớn nhỏ với số (`bool` là lớp con của `int`), khác kiểu → SAI.
Nhiều luật khớp → chặt nhất thắng `deny > approval_required > allow` (`strictest`).

**Giờ hành chính** (11.2): đổi thời điểm sang `tz`, thứ ISO ∈ `weekdays` và `start ≤ giờ < end`; không xét ngày lễ.
`tz` phải nạp được bằng `ZoneInfo` (gói `tzdata`, Q-3h-5) — không nạp được → không khởi động.

Domain thuần: không đọc file, không biết `RiskContext` (ở `risk/`) — `risk/policy_engine.py` dựng "khung nhìn fact"
(`FactView`: nguồn → {tên: giá trị}) từ `(action, ctx)` rồi gọi các hàm ở đây.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.domain.facts import FACT_KEYS

type Decision = Literal["allow", "approval_required", "deny"]
type Op = Literal["eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "is_true", "is_false"]
type Scalar = str | int | float | bool
# Kiểu CHẶT khi nạp luật: `[true]` không bị ép thành `(1,)`, `"1"` không thành số (soát S7 NGHI 1)
type StrictScalar = StrictStr | StrictInt | StrictFloat | StrictBool
type FactView = Mapping[str, Mapping[str, Any]]  # nguồn ("action", "action.facts", …) → {tên fact: giá trị}

DECISION_RANK: Mapping[str, int] = {"allow": 1, "approval_required": 2, "deny": 3}  # chặt nhất thắng [Chốt]

# Danh sách trắng đường fact: nguồn → tên được phép.
FACT_SOURCES: Mapping[str, frozenset[str]] = {
    "action": frozenset({
        "type", "target", "requested_for", "scope", "privilege_level", "reversible", "reversibility", "data_sensitivity",
    }),
    "action.facts": FACT_KEYS,
    "requester": frozenset({
        "user_id", "role", "department", "employment_status", "tenure_days", "is_privileged_account",
    }),
    "time": frozenset({"within_business_hours"}),
    "ctx": frozenset({"target_is_other"}),
}  # fmt: skip
NO_VALUE_OPS = frozenset({"is_true", "is_false"})
LIST_OPS = frozenset({"in", "not_in"})
ORDER_OPS = frozenset({"lt", "lte", "gt", "gte"})


def split_fact(path: str) -> tuple[str, str]:
    """`"action.facts.device_registered"` → `("action.facts", "device_registered")`. Nguồn dài nhất khớp trước.
    Đường ngoài danh sách trắng → `ValueError` (lỗi cấu hình, bắt lúc nạp)."""
    for source in sorted(FACT_SOURCES, key=len, reverse=True):
        prefix = source + "."
        if path.startswith(prefix):
            name = path[len(prefix) :]
            if name in FACT_SOURCES[source]:
                return source, name
            break
    raise ValueError(f"fact {path!r} ngoài danh sách trắng {sorted(FACT_SOURCES)}")


def _is_number(v: object) -> bool:
    return type(v) in (int, float)


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact: str
    op: Op
    value: StrictScalar | tuple[StrictStr | StrictInt, ...] | None = None

    @field_validator("fact")
    @classmethod
    def _known_fact(cls, v: str) -> str:
        split_fact(v)
        return v

    @model_validator(mode="after")
    def _value_matches_op(self) -> "Condition":
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError(f"{self.fact}: value phải là số hữu hạn")
        if self.op in NO_VALUE_OPS:
            if self.value is not None:
                raise ValueError(f"{self.fact}: toán tử {self.op} không nhận value")
        elif self.op in LIST_OPS:
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError(f"{self.fact}: toán tử {self.op} cần value là danh sách không rỗng")
        elif self.op in ORDER_OPS:
            if not _is_number(self.value):
                raise ValueError(f"{self.fact}: toán tử {self.op} cần value là số")
        elif self.value is None or isinstance(self.value, tuple):
            raise ValueError(f"{self.fact}: toán tử {self.op} cần value là một giá trị")
        return self


class Conditions(BaseModel):
    """Nhóm `{"all": [...]}` hoặc `{"any": [...]}` — đúng một khoá, danh sách không rỗng; phần tử là điều kiện hoặc nhóm."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    all_: tuple["Condition | Conditions", ...] | None = Field(default=None, alias="all")
    any_: tuple["Condition | Conditions", ...] | None = Field(default=None, alias="any")

    @model_validator(mode="after")
    def _exactly_one(self) -> "Conditions":
        groups = [g for g in (self.all_, self.any_) if g is not None]
        if len(groups) != 1 or not groups[0]:
            raise ValueError("conditions phải có đúng một trong all/any, danh sách không rỗng")
        return self

    def facts(self) -> Iterable[str]:
        for item in self.all_ or self.any_ or ():
            yield from item.facts() if isinstance(item, Conditions) else (item.fact,)


Conditions.model_rebuild()  # nhóm lồng tự tham chiếu


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^R\d{2}$")
    type: Decision
    intent: str = Field(min_length=1)
    action: str | tuple[str, ...]
    conditions: Conditions
    description: str = Field(min_length=1)

    @field_validator("action")
    @classmethod
    def _non_empty(cls, v: str | tuple[str, ...]) -> str | tuple[str, ...]:
        if (isinstance(v, str) and not v) or (isinstance(v, tuple) and (not v or not all(v))):
            raise ValueError("action phải là chuỗi hoặc danh sách chuỗi không rỗng")
        return v

    @property
    def actions(self) -> tuple[str, ...]:
        return (self.action,) if isinstance(self.action, str) else self.action


class BusinessHours(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tz: str
    weekdays: tuple[int, ...] = Field(min_length=1)  # thứ ISO: 1 = thứ Hai … 7 = Chủ nhật
    start: time
    end: time

    @field_validator("tz")
    @classmethod
    def _tz_loads(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"business_hours.tz {v!r} không nạp được (cần gói tzdata)") from e
        return v

    @model_validator(mode="after")
    def _sane(self) -> "BusinessHours":
        if len(set(self.weekdays)) != len(self.weekdays) or not all(1 <= d <= 7 for d in self.weekdays):
            raise ValueError("business_hours.weekdays: thứ ISO 1..7, không trùng")
        if not self.start < self.end:
            raise ValueError("business_hours: start phải trước end")
        return self


def within_business_hours(now: datetime, hours: BusinessHours) -> bool:
    """`start ≤ giờ địa phương < end` và thứ ISO ∈ `weekdays` (h20: 07:59 F, 08:00 T, 17:59 T, 18:00 F, thứ Bảy F)."""
    if now.tzinfo is None:
        raise ValueError("within_business_hours cần datetime có múi giờ")
    local = now.astimezone(ZoneInfo(hours.tz))
    return local.isoweekday() in hours.weekdays and hours.start <= local.time() < hours.end


def check_rules(rules: Sequence[Rule]) -> None:
    ids = [r.id for r in rules]
    if len(set(ids)) != len(ids):
        raise ValueError(f"policy.rules: id trùng {sorted({i for i in ids if ids.count(i) > 1})}")


def referenced_facts(rules: Iterable[Rule], source: str) -> frozenset[str]:
    """Tên fact thuộc nguồn `source` mà ít nhất một luật tham chiếu (kể cả nhóm lồng). B17 dùng với `"requester"` (Q-3h-7):
    đúng các trường này phải khớp giữa bản chụp B1 và AD đọc mới."""
    names: set[str] = set()
    for rule in rules:
        for fact in rule.conditions.facts():
            fact_source, name = split_fact(fact)
            if fact_source == source:
                names.add(name)
    return frozenset(names)


# ---- Đánh giá (thuần) -------------------------------------------------------------------------------------------------

_MISSING = object()


def _lookup(view: FactView, path: str) -> object:
    source, name = split_fact(path)
    return view.get(source, {}).get(name, _MISSING)


def _same_kind(a: object, b: object) -> bool:
    """So được với nhau: cùng là bool, cùng là chuỗi, hoặc cùng là số (không bool)."""
    if type(a) is bool or type(b) is bool:
        return type(a) is bool and type(b) is bool
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str)
    return _is_number(a) and _is_number(b)


def condition_holds(cond: Condition, view: FactView) -> bool:
    got = _lookup(view, cond.fact)
    if got is _MISSING or got is None:
        return False  # thiếu fact → điều kiện SAI [Chốt]
    op, want = cond.op, cond.value
    if op == "is_true":
        return got is True
    if op == "is_false":
        return got is False
    if op in LIST_OPS:
        assert isinstance(want, tuple)
        hit = any(_same_kind(got, w) and got == w for w in want)
        comparable = any(_same_kind(got, w) for w in want)
        return comparable and (hit if op == "in" else not hit)
    if not _same_kind(got, want):
        return False
    if op == "eq":
        return got == want
    if op == "ne":
        return got != want
    assert _is_number(got) and _is_number(want)
    a, b = float(got), float(want)  # type: ignore[arg-type]
    return {"lt": a < b, "lte": a <= b, "gt": a > b, "gte": a >= b}[op]


def conditions_hold(group: Conditions, view: FactView) -> bool:
    items = group.all_ if group.all_ is not None else group.any_
    assert items
    results = (
        conditions_hold(i, view) if isinstance(i, Conditions) else condition_holds(i, view) for i in items
    )  # fmt: skip
    return all(results) if group.all_ is not None else any(results)


def rule_matches(rule: Rule, *, intent: str | None, action_type: str, view: FactView) -> bool:
    """Luật áp cho hành động (intent + action) VÀ mọi điều kiện đúng. `intent=None` (không suy được) → không khớp."""
    if intent is None or rule.intent != intent or action_type not in rule.actions:
        return False
    return conditions_hold(rule.conditions, view)


def strictest(matched: Sequence[Rule]) -> Rule | None:
    """Chặt nhất thắng; cùng mức → luật đứng trước trong file."""
    best: Rule | None = None
    for r in matched:
        if best is None or DECISION_RANK[r.type] > DECISION_RANK[best.type]:
            best = r
    return best
