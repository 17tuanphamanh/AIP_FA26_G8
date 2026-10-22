"""Nạp kịch bản M8 cho harness G2 theo CẤU TRÚC THẬT (Tuấn Anh 19/10, `~/m9-notes/g2-chot.md` — chỉ tên trường + kiểu, giống nhau 186
file) — mỗi file `*.yaml`/`*.yml` (không đệ quy) là MỘT kịch bản (mapping) hoặc một DANH SÁCH.

Schema CHỈ đúng các khoá của cấu trúc thật, BẮT BUỘC đủ (trừ `gold.action.requested_for` — vắng → `requester.user_id` của người gửi, D-41 — và
`gold.action.params` — vắng → `{}`; `gold.approver_decision` bắt buộc có khoá, nhận null = không có bước duyệt — #58),
`extra="forbid"` ở MỌI tầng (bắt gõ nhầm tên); `gold.hidden_factor` (P8 v1.4)
KHÔNG có trong dữ liệu → để PR hợp đồng v1.1. `allow_extra=True` (cờ `--allow-extra-fields`) → bỏ trường lạ, ghi ĐƯỜNG DẪN trường (chỉ
số danh sách thành `*`, không giá trị) vào `Dataset.ignored_fields` — một phần tử mỗi lần bỏ.
- `requester{user_id, role, dept, tenure_days}`: `user_id` → `username` tra seed của mock (`load_seed_users`, `mock_services/seed.json`);
  không có trong seed → lỗi nạp. `role`, `dept`, `tenure_days`, `source`, `at`, `faults`, `labels`: chỉ nạp (`at` cho G7).
- `turns`: `[0]` = câu đầu (chuỗi); phần tử sau là `{on_question_about: <slot>, reply}` HOẶC `{on_confirm: bool}`.
- `gold.expected_route = null` (tới 25/10) → kịch bản CHƯA NHÃN (`Scenario.labelled = False`), nạp được.

Nạp gom MỌI lỗi (không dừng ở lỗi đầu) rồi ném `DatasetError` (lớp con `ValueError`) kèm số kịch bản nạp được. Mỗi lỗi: vị trí file
+ vị trí trường, KHÔNG giá trị (kịch bản chứa câu người dùng và gold). Mặc định vị trí file = `file #<i>/<tổng>` — tên file có thể lộ
thẻ/họ; tên file chỉ hiện ở `render(show_name=True)` (cờ `--per-case`). `sha256` = băm của các cặp (tên file, sha256 nội dung) sắp theo
tên — không phụ thuộc đường dẫn tuyệt đối hay thứ tự tạo file.
"""

import copy
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StringConstraints,
    Tag,
    ValidationError,
    field_validator,
)

from app.risk.decision_math import Route

TEXT_MAX = 4000  # = `TicketIn.text` / `MessageIn.text` (app/api/tickets.py) — dài hơn thì API trả 422 giữa chừng
SUFFIXES = (".yaml", ".yml")

Id = Annotated[str, StringConstraints(min_length=1)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=TEXT_MAX)]
ApproverDecision = Literal["approve", "reject", "ignore"]  # TODO(G2-Q20): dữ liệu thật là `str` — tập giá trị chờ Tuấn Anh xác nhận
Slot = Literal["account_type", "permission_level", "resource_path", "duration", "device_id", "software_name", "action",
               "target_corrected"]  # fmt: skip  # g2-chot.md:14
SLOTS: tuple[str, ...] = get_args(Slot)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class Requester(_Model):
    user_id: Id
    role: str
    dept: str
    tenure_days: int


class Reply(_Model):
    """Câu trả lời cho một lần hỏi lại. `on_question_about` CHƯA dùng để khớp (slot không lộ qua API — G2-Q19): khớp theo thứ tự."""

    on_question_about: Slot
    reply: Text


class Confirm(_Model):
    on_confirm: bool


# Thẻ phân loại phần tử `turns` — xuất hiện trong `loc` lỗi của pydantic, bị bỏ khỏi đường dẫn trường (`_clean`).
_TAGS = frozenset({"opening", "reply_turn", "confirm_turn"})


def _turn_kind(v: Any) -> str:
    if isinstance(v, str):
        return "opening"
    if isinstance(v, Confirm) or (isinstance(v, dict) and "on_confirm" in v):
        return "confirm_turn"
    return "reply_turn"


Turn = Annotated[
    Annotated[Text, Tag("opening")] | Annotated[Reply, Tag("reply_turn")] | Annotated[Confirm, Tag("confirm_turn")],
    Discriminator(_turn_kind),
]


class Action(_Model):
    type: str
    target: str | None  # TODO(G2-Q21): kiểu thật của target / requested_for
    requested_for: str | None = None  # vắng khoá → người gửi (D-41): `Dataset.requested_for`
    params: dict[str, Any] = Field(default_factory=dict)  # vắng khoá → {}


class Gold(_Model):
    intents: tuple[Id, ...] = Field(min_length=1)
    need_type: str
    expected_route: Route | None  # None = chưa nhãn (tới 25/10)
    expected_exit: str | None
    approver_decision: ApproverDecision | None  # None = không có bước duyệt (luật cấm); khoá vẫn bắt buộc
    gold_doc_ids: tuple[Id, ...]
    action: Action
    facts: dict[str, Any]


class Labels(_Model):
    annotator_1: Any
    annotator_2: Any


class Scenario(_Model):
    id: Id
    family: Id
    source: str
    at: str  # khung giờ `at` là việc G7 (G2-Q10) — bản này chỉ nạp
    faults: tuple[Any, ...]
    requester: Requester
    turns: tuple[Turn, ...] = Field(min_length=1)
    gold: Gold
    labels: Labels

    @field_validator("turns")
    @classmethod
    def _opening_first(cls, v: tuple[Any, ...]) -> tuple[Any, ...]:
        if not isinstance(v[0], str) or any(isinstance(t, str) for t in v[1:]):
            raise ValueError("turns: phần tử đầu là câu đầu (chuỗi), các phần tử sau là {on_question_about, reply} hoặc {on_confirm}")
        return v

    @property
    def opening(self) -> str:
        return str(self.turns[0])

    @property
    def replies(self) -> tuple[str, ...]:
        return tuple(t.reply for t in self.turns[1:] if isinstance(t, Reply))

    @property
    def confirms(self) -> tuple[bool, ...]:
        return tuple(t.on_confirm for t in self.turns[1:] if isinstance(t, Confirm))

    @property
    def labelled(self) -> bool:
        return self.gold.expected_route is not None

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
    usernames: Mapping[str, str] = field(default_factory=dict)  # scenario_id → username (tra seed theo requester.user_id)

    def requested_for(self, s: Scenario) -> str | None:
        """D-41: vắng `gold.action.requested_for` → người gửi (`requester.user_id` — giá trị có sẵn trong dữ liệu là user_id, Tuấn Anh
        22/10); có khoá (kể cả null) → giữ nguyên."""
        a = s.gold.action
        return a.requested_for if "requested_for" in a.model_fields_set else s.requester.user_id


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


class _SeedUser(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)  # seed có nhiều trường khác — chỉ cần 2 trường này
    user_id: Id
    username: Id


class _Seed(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    users: list[_SeedUser]


def load_seed_users(path: Path) -> dict[str, str]:
    """`user_id → username` từ seed của mock (`mock_services/seed.json`: `users[*].user_id`, `users[*].username`). Lỗi → `ValueError`
    có chữ "seed", không giá trị."""
    try:
        seed = _Seed.model_validate_json(path.read_bytes())
    except OSError:
        raise ValueError("seed: không đọc được file seed") from None
    except ValidationError:
        raise ValueError("seed: file seed sai dạng (cần users[*].user_id, users[*].username)") from None
    out = {u.user_id: u.username for u in seed.users}
    if len(out) != len(seed.users):
        raise ValueError("seed: user_id trùng")
    return out


def _clean(loc: tuple[int | str, ...]) -> tuple[int | str, ...]:
    return tuple(p for p in loc if p not in _TAGS)


def _path(loc: tuple[int | str, ...]) -> str:
    return ".".join("*" if isinstance(p, int) else str(p) for p in _clean(loc))


def _where(e: ValidationError) -> str:
    locs = {".".join(str(p) for p in _clean(err["loc"])) or "<kịch bản>" for err in e.errors(include_url=False, include_input=False)}
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
        keys = _clean(loc)
        for key in keys[:-1]:
            node = node[key]
        del node[keys[-1]]
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


def load_scenarios(directory: Path, *, users: Mapping[str, str], allow_extra: bool = False) -> Dataset:
    """`users` = `load_seed_users(...)` (user_id → username)."""
    if not directory.is_dir():
        raise ValueError("thư mục kịch bản: không phải thư mục")
    paths = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in SUFFIXES)
    if not paths:
        raise ValueError("thư mục kịch bản: không có file kịch bản (*.yaml, *.yml)")
    h = hashlib.sha256()
    scenarios: list[Scenario] = []
    usernames: dict[str, str] = {}
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
            if s.requester.user_id not in users:
                issues.append(LoadIssue(n, len(paths), p.name, pos, "requester.user_id không có trong seed"))
                continue
            seen.add(s.id)
            scenarios.append(s)
            usernames[s.id] = users[s.requester.user_id]
            ignored += dropped
    if issues:
        raise DatasetError(issues, loaded=len(scenarios))
    return Dataset(scenarios=tuple(scenarios), sha256=h.hexdigest(), files=tuple(p.name for p in paths),
                   ignored_fields=tuple(ignored), usernames=usernames)  # fmt: skip
