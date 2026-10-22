"""Hợp đồng dữ liệu của groundedness offline: đầu vào `answers.jsonl` và kết quả `results.jsonl` (mô-đun docstring: __init__)."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_CLAIMS = 24  # = trần `GroundednessOut.verdicts`

type Verdict = Literal["supported", "partial", "unsupported"]
type Status = Literal["judged", "cannot_answer", "no_claims", "error"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Chunk(_Strict):
    """Khối bằng chứng của MỘT chunk được dẫn: `text` = mọi khối bằng chứng đã gửi cho `b10_answer` ứng với chunk đó, GỒM cả chunk
    liền kề (D-24) — đúng như model viết đã thấy. Nguồn khi thu thập (mốc G): `llm_calls.prompt_full` (EVAL_MODE) [Đề xuất 22/10]."""

    chunk_id: str = Field(min_length=1)
    text: str
    doc_id: str | None = None
    title: str | None = None
    heading_path: str | None = None


class AnswerRow(_Strict):
    """Một câu trả lời B10. `answer` là phần chữ gửi người dùng (hoặc `answer_markdown`); có `steps` thì các bước nằm ở `steps`
    (bước trùng dòng đánh số trong `answer` chỉ tính một lần). `family` BẮT BUỘC: họ = câu hỏi gốc + các biến thể của nó — đơn vị
    rút lại của bootstrap; thiếu → lỗi, KHÔNG suy từ tiền tố `scenario_id`."""

    scenario_id: str = Field(min_length=1)
    family: str = Field(min_length=1, pattern=r"\S")  # BẮT BUỘC (P8 v1.5 6.3.1): họ = câu hỏi gốc + các biến thể; không suy từ scenario_id
    answer: str
    steps: tuple[str, ...] | None = None
    citations: tuple[str, ...]
    chunks: tuple[Chunk, ...]
    cannot_answer: StrictBool = False  # "no"/1 không được ép thành bool

    @field_validator("citations")
    @classmethod
    def _dedupe_citations(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(not c for c in v):
            raise ValueError("citations có mã rỗng")
        return tuple(dict.fromkeys(v))

    @model_validator(mode="after")
    def _unique_chunks(self) -> "AnswerRow":
        ids = [c.chunk_id for c in self.chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("chunks có chunk_id trùng")
        return self


class JudgedClaim(_Strict):
    claim_id: int = Field(ge=1)
    text: str
    verdict: Verdict
    chunk_ids: tuple[str, ...] = ()  # đoạn hỗ trợ (supported) hoặc hỗ trợ một phần (partial); unsupported luôn rỗng


class JudgedAnswer(_Strict):
    scenario_id: str
    family: str
    status: Status
    flags: tuple[str, ...] = ()  # "no_citation"
    citations: tuple[str, ...] = ()
    invalid_citations: tuple[str, ...] = ()  # được dẫn nhưng không có trong `chunks`
    error: str | None = None
    claims: tuple[JudgedClaim, ...] = ()

    @model_validator(mode="after")
    def _error_iff_status(self) -> "JudgedAnswer":
        if (self.status == "error") != (self.error is not None):
            raise ValueError("error phải có đúng khi status = error")
        return self


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[tuple[int, object]]:
    out: list[tuple[int, object]] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append((no, json.loads(line)))
        except ValueError:
            raise ValueError(f"{path.name}: dòng {no} không phải JSON") from None
    return out


def load_answers(path: Path) -> list[AnswerRow]:
    """Nạp + kiểm `answers.jsonl`. Lỗi → `ValueError` nêu số dòng và tên trường (không in giá trị). `scenario_id` không được trùng."""
    rows: list[AnswerRow] = []
    seen: set[str] = set()
    for no, data in _read_jsonl(path):
        try:
            row = AnswerRow.model_validate(data)
        except ValidationError as e:
            fields = sorted({".".join(str(p) for p in err["loc"]) or "(gốc)" for err in e.errors()})
            raise ValueError(f"{path.name}: dòng {no} sai hợp đồng ở {fields}") from None
        if row.scenario_id in seen:
            raise ValueError(f"{path.name}: scenario_id trùng ở dòng {no}")
        seen.add(row.scenario_id)
        rows.append(row)
    if not rows:
        raise ValueError(f"{path.name}: không có dòng nào")
    return rows


def load_results(path: Path) -> list[JudgedAnswer]:
    out: list[JudgedAnswer] = []
    seen: set[str] = set()
    for no, data in _read_jsonl(path):
        try:
            answer = JudgedAnswer.model_validate(data)
        except ValidationError:
            raise ValueError(f"{path.name}: dòng {no} sai hợp đồng kết quả") from None
        if answer.scenario_id in seen:
            raise ValueError(f"{path.name}: scenario_id trùng ở dòng {no}")
        seen.add(answer.scenario_id)
        out.append(answer)
    return out


def dump_jsonl(path: Path, records: Sequence[BaseModel | dict[str, object]]) -> None:
    lines = [
        r.model_dump_json() if isinstance(r, BaseModel) else json.dumps(r, ensure_ascii=False, sort_keys=True)
        for r in records
    ]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
