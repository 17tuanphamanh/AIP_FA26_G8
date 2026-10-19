"""Nạp kịch bản M8 (P8 §4.1) cho harness G2 — mỗi file `*.yaml`/`*.yml` (không đệ quy) là MỘT kịch bản (mapping) hoặc một DANH SÁCH.

Chỉ kiểm chặt trường harness dùng (`id`, `family`, `requester`, `turns`, `gold.intents`, `gold.expected_route`,
`gold.approver_decision`, `gold.gold_doc_ids`, `gold.hidden_factor`); trường còn lại của P8 §4.1 nhận nguyên (`Any`) — harness không
đọc. Trường lạ → từ chối (`extra="forbid"`, bắt gõ nhầm tên); `allow_extra=True` (cờ `--allow-extra-fields`) → bỏ trường lạ, ghi
ĐƯỜNG DẪN trường (chỉ số danh sách thành `*`, không giá trị) vào `Dataset.ignored_fields` — một phần tử mỗi lần bỏ.

Nạp gom MỌI lỗi (không dừng ở lỗi đầu) rồi ném `DatasetError` (lớp con `ValueError`) kèm số kịch bản nạp được. Mỗi lỗi: vị trí file
+ vị trí trường, KHÔNG giá trị (kịch bản chứa câu người dùng và gold). Mặc định vị trí file = `file #<i>/<tổng>` — tên file có thể lộ
thẻ/họ; tên file chỉ hiện ở `render(show_name=True)` (cờ `--per-case`). `sha256` = băm của các cặp (tên file, sha256 nội dung) sắp theo
tên — không phụ thuộc đường dẫn tuyệt đối hay thứ tự tạo file.
"""

import copy
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.risk.decision_math import Route

TEXT_MAX = 4000  # = `TicketIn.text` / `MessageIn.text` (app/api/tickets.py) — dài hơn thì API trả 422 giữa chừng
SUFFIXES = (".yaml", ".yml")

Id = Annotated[str, StringConstraints(min_length=1)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=TEXT_MAX)]
ApproverDecision = Literal["approve", "reject", "ignore"]  # TODO(G2-Q6): tập giá trị thật của gold.approver_decision


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class Turn(_Model):
    """Một câu người dùng gửi. Dạng ngắn trong YAML: chuỗi trơn = `{text: …}`."""

    text: Text
    on_confirm: bool | None = None  # TODO(G2-Q8): chỗ đặt on_confirm; None → harness xác nhận "Đã ổn"


class Gold(_Model):
    intents: tuple[Id, ...] = Field(min_length=1)
    expected_route: Route
    approver_decision: ApproverDecision | None = None
    gold_doc_ids: tuple[Id, ...] = ()
    hidden_factor: bool = False  # P8 v1.4 §4.1
    need_type: Any = None
    expected_exit: Any = None
    action: Any = None
    facts: Any = None


class Scenario(_Model):
    id: Id
    family: Id
    requester: Id  # TODO(G2-Q7): username hay user_id — harness đăng nhập bằng giá trị này
    turns: tuple[Turn, ...] = Field(min_length=1)
    gold: Gold
    source: Any = None
    at: Any = None  # khung giờ `at` là việc G7 (G2-Q10) — bản 20/10 không đọc
    faults: Any = None
    labels: Any = None

    @field_validator("turns", mode="before")
    @classmethod
    def _short_turns(cls, v: Any) -> Any:
        return [{"text": t} if isinstance(t, str) else t for t in v] if isinstance(v, list) else v

    @property
    def gold_intent(self) -> str | None:
        """TODO(G2-Q12): đơn ý → intent duy nhất; nhiều ý → None (lá nhiều ý không vào predictions v1)."""
        return self.gold.intents[0] if len(self.gold.intents) == 1 else None


@dataclass(frozen=True)
class Dataset:
    scenarios: tuple[Scenario, ...]
    sha256: str
    files: tuple[str, ...]
    ignored_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadIssue:
    index: int  # 1-based trong các file kịch bản (sắp theo tên)
    total: int
    name: str
    item: int | None  # vị trí trong file danh sách; None = file một kịch bản / lỗi cả file
    what: str  # chỉ vị trí trường / loại lỗi — không giá trị

    def render(self, show_name: bool = False) -> str:
        where = self.name if show_name else f"file #{self.index}/{self.total}"
        return f"{where}{'' if self.item is None else f'[{self.item}]'}: {self.what}"


class DatasetError(ValueError):
    def __init__(self, issues: Sequence[LoadIssue], loaded: int) -> None:
        self.issues = tuple(issues)
        self.loaded = loaded
        super().__init__("; ".join(self.render()))

    def render(self, show_name: bool = False) -> list[str]:
        return [i.render(show_name) for i in self.issues]


def _path(loc: tuple[int | str, ...]) -> str:
    return ".".join("*" if isinstance(p, int) else str(p) for p in loc)


def _where(e: ValidationError) -> str:
    locs = {".".join(str(p) for p in err["loc"]) or "<kịch bản>" for err in e.errors(include_url=False, include_input=False)}
    return ", ".join(sorted(locs))


def _validate(item: dict[str, Any], allow_extra: bool) -> tuple[Scenario, list[str]]:
    """`allow_extra`: bỏ mọi khoá `extra_forbidden` (pydantic báo hết trong một lần) rồi kiểm lại; lỗi khác vẫn ném."""
    try:
        return Scenario.model_validate(item), []
    except ValidationError as e:
        extras = [err["loc"] for err in e.errors(include_url=False, include_input=False) if err["type"] == "extra_forbidden"]
        if not allow_extra or not extras:
            raise
    trimmed = copy.deepcopy(item)
    for loc in extras:
        node: Any = trimmed
        for key in loc[:-1]:
            node = node[key]
        del node[loc[-1]]
    return Scenario.model_validate(trimmed), [_path(loc) for loc in extras]


def _parse(raw: bytes, allow_extra: bool) -> tuple[list[tuple[int | None, Scenario, list[str]]], list[tuple[int | None, str]]]:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        return [], [(None, "YAML lỗi" + (f" dòng {mark.line + 1}" if mark is not None else ""))]
    items: Sequence[Any] = data if isinstance(data, list) else [data]
    if not items or not all(isinstance(x, dict) for x in items):
        return [], [(None, "phải là một kịch bản (mapping) hoặc danh sách kịch bản")]
    ok, bad = [], []
    for i, item in enumerate(items):
        pos = i if isinstance(data, list) else None
        try:
            ok.append((pos, *_validate(item, allow_extra)))
        except ValidationError as e:
            bad.append((pos, f"không hợp lệ ({_where(e)})"))
    return ok, bad


def load_scenarios(directory: Path, *, allow_extra: bool = False) -> Dataset:
    if not directory.is_dir():
        raise ValueError("thư mục kịch bản: không phải thư mục")
    paths = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in SUFFIXES)
    if not paths:
        raise ValueError("thư mục kịch bản: không có file kịch bản (*.yaml, *.yml)")
    h = hashlib.sha256()
    scenarios: list[Scenario] = []
    ignored: list[str] = []
    issues: list[LoadIssue] = []
    seen: set[str] = set()
    for n, p in enumerate(paths, start=1):
        raw = p.read_bytes()
        h.update(f"{p.name}\0{hashlib.sha256(raw).hexdigest()}\n".encode())
        ok, bad = _parse(raw, allow_extra)
        issues += [LoadIssue(n, len(paths), p.name, pos, what) for pos, what in bad]
        for pos, s, dropped in ok:
            if s.id in seen:
                issues.append(LoadIssue(n, len(paths), p.name, pos, "id kịch bản trùng với kịch bản trước"))
                continue
            seen.add(s.id)
            scenarios.append(s)
            ignored += dropped
    if issues:
        raise DatasetError(issues, loaded=len(scenarios))
    return Dataset(scenarios=tuple(scenarios), sha256=h.hexdigest(), files=tuple(p.name for p in paths),
                   ignored_fields=tuple(ignored))  # fmt: skip
