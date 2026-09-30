"""Kiểu dữ liệu của RAG: ingest (3b, mục 5.2–5.7; PLAN-3b mục 4.2, 4.7, 5) + truy hồi (3c, mục 6.3).

`FrontMatter` kiểm từng file KB (`extra="forbid"`); ba miền giá trị lấy từ hằng của `db/models.py` — không gõ lại
danh sách (lệch với CHECK của DB là lỗi lúc ghi). Lỗi dự kiến của ingest là GIÁ TRỊ (`IngestIssue`) được gom rồi
in một lượt; `IngestError` bọc một issue khi cần thoát sớm khỏi một tài liệu (chunker).

Phần truy hồi (3c): `RetrievalQuery`/`RetrievalResult`/`EvidenceBlock` là hợp đồng của `Retriever` (`rag/retriever.py`,
`rag/expand.py`, S5). `RetrievalSystemError` là lỗi hệ thống DUY NHẤT mà node `b08_retrieve` bắt (E2) — mọi exception
khác (hợp đồng, `ChunkTruncatedError`) nổi lên boundary → E9.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import KB_DOC_TYPES, KB_REQUEST_TYPES, KB_SENSITIVITY
from app.domain.action import (
    DOC_ID_PATTERN,  # một nguồn (domain.action); loader import lại từ đây như trước
)
from app.domain.ticket_state import ChunkRef

# "procedure" (Phase 4 S0-P10): `Retriever.procedure_available` — mọi lỗi của lượt kiểm quy trình ở B11 mang nhãn này.
type Stage = Literal["alias", "pipeline", "embed", "search", "rerank", "expand", "procedure"]


def _one_of(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"phải là một trong: {', '.join(allowed)}")
    return value


class FrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    version: int = Field(ge=1)
    request_type: str  # ∈ KB_REQUEST_TYPES — kiểu str + validator (Literal động không qua được mypy)
    doc_type: str  # ∈ KB_DOC_TYPES
    owner: str = Field(pattern=r"^[a-z0-9_]{3,64}$")  # user_id; không có trong `users` → ghi NULL (3-Q40)
    updated_at: date
    sensitivity: str  # ∈ KB_SENSITIVITY
    enabled: bool
    title: str = Field(min_length=5, max_length=120)
    distractor: bool = False
    tags: list[str] = []
    supersedes: str | None = None  # doc_id bản cũ — loader kiểm mẫu và tồn tại

    @field_validator("request_type")
    @classmethod
    def _request_type(cls, v: str) -> str:
        return _one_of(v, KB_REQUEST_TYPES)

    @field_validator("doc_type")
    @classmethod
    def _doc_type(cls, v: str) -> str:
        return _one_of(v, KB_DOC_TYPES)

    @field_validator("sensitivity")
    @classmethod
    def _sensitivity(cls, v: str) -> str:
        return _one_of(v, KB_SENSITIVITY)


@dataclass(frozen=True, order=True)
class IngestIssue:
    """Một lỗi in cho người soát: `kb/vpn/KB-VPN-003.md:7: version: phải ≥ 1`. Sắp theo file rồi dòng."""

    rel_path: str
    line: int | None  # None = lỗi không gắn dòng (thư mục lạ, thiếu file…) — in không có phần dòng
    message: str
    field: str | None = None

    def __str__(self) -> str:
        where = self.rel_path if self.line is None else f"{self.rel_path}:{self.line}"
        return f"{where}: {self.field}: {self.message}" if self.field else f"{where}: {self.message}"


class IngestError(Exception):
    """Lỗi của MỘT tài liệu làm dừng xử lý tài liệu đó (chunker) — pipeline gom lỗi mọi tài liệu rồi thoát 1."""

    def __init__(self, message: str, rel_path: str, line: int | None) -> None:
        self.issue = IngestIssue(rel_path, line, message)
        super().__init__(str(self.issue))

    @property
    def line(self) -> int | None:
        return self.issue.line


class IngestMlError(Exception):
    """ml-service lỗi hạ tầng khi đếm token / embed lúc ingest → mã thoát 1 (alias giữ nguyên)."""


@dataclass(frozen=True)
class Doc:
    fm: FrontMatter
    path: Path
    rel_path: str  # "<tên kb_dir>/<request_type>/<doc_id>.md" — dùng trong thông báo lỗi
    body: str  # thân bài đã `textnorm.normalize` (chưa bỏ HTML)
    body_start_line: int  # số dòng (1-based, trong file) của dòng đầu thân bài
    content_sha256: str = ""  # tính ở bước 3 (kbversion.content_sha256)


@dataclass(frozen=True)
class Block:
    """Khối nội dung trong một mục: đoạn văn, danh sách, code fence, hoặc một mục danh sách / câu sau khi tách."""

    text: str
    start_line: int  # số dòng trong file
    is_list: bool = False
    sep: str = "\n\n"  # chuỗi nối với khối liền trước khi gom (mục danh sách tách ra giữ cách xuống dòng gốc)
    atomic: bool = False  # một câu đã tách — vượt trần thì là lỗi "câu quá dài", không tách thêm


@dataclass(frozen=True)
class Chunk:
    seq: int
    chunk_id: str  # f"{doc_id}#v{version}#{seq}"
    heading_path: str  # "X" | "X › Y" | "Tổng quan"
    h2: str
    content: str
    content_tokens: int  # n(content), GỒM token đặc biệt
    text: str  # f"{title} › {heading_path}\n\n{content}" — dùng cho cả dense lẫn BM25
    text_tokens: int
    start_line: int


class ChunkPayload(BaseModel):
    """Payload một điểm Qdrant (thiết kế 5.7 + `owner`, Q-3b-7)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    doc_id: str
    version: int
    seq: int
    title: str
    heading_path: str
    request_type: str
    doc_type: str
    sensitivity: str
    enabled: bool
    distractor: bool
    text: str
    token_count: int
    kb_version: str
    owner: str


@dataclass
class IngestReport:
    """Tóm tắt một lượt ingest thành công (dòng cuối stdout)."""

    kb_version: str
    collection: str
    doc_count: int
    chunk_count: int
    eval_status: str
    recall_at5: float | None = None
    false_grounding_rate: float | None = None
    warnings: list[str] = field(default_factory=list)


# ---- Truy hồi (Phase 3 chặng 3c, mục 6.3) ------------------------------------------------------


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    intent: str | None


class RetrievalResult(BaseModel):
    chunks: list[ChunkRef]
    top_score: float  # 0.0 khi rỗng
    kb_version: str  # suy từ tên collection đã ghim
    intent_filter_fallback: bool
    fallback_tried: bool
    retries: int  # tổng số lần THỬ LẠI (Q-3c-10)
    query_truncated: bool


class ProcedureCheck(BaseModel):
    """Kết quả `Retriever.procedure_available` (Phase 4 S0-P10, chốt S0-A3): tài liệu quy trình có trong KB HIỆN HÀNH (alias tại
    lúc B11 kiểm — không phải `kb_version` ghim ở B8), `enabled`, người gửi được xem (`base_filter`)."""

    model_config = ConfigDict(frozen=True)

    available: bool
    kb_version: str  # collection mà alias trỏ tới lúc kiểm — audit B11 `procedure_kb_version`
    retries: int


class RetrievalSystemError(Exception):
    """Lỗi hệ thống DUY NHẤT mà `b08_retrieve` bắt (→ E2). `detail`: loại lỗi + thao tác, ví dụ
    "ConnectError: query kb_…" hoặc "deadline" — KHÔNG BAO GIỜ chứa câu truy vấn người dùng."""

    def __init__(self, stage: Stage, retries: int, *, kb_version: str | None = None, detail: str = "") -> None:
        self.stage = stage
        self.retries = retries
        self.kb_version = kb_version
        self.detail = detail
        super().__init__(f"{stage}: {detail}" if detail else stage)


class ChunkTruncatedError(Exception):
    """Reranker báo cắt đoạn tài liệu (`rr.data.truncated`) → vi phạm D-21 → E9 (không phải RetrievalSystemError)."""


class EvidenceBlock(BaseModel):
    anchor_chunk_id: str
    doc_id: str
    title: str
    heading_path: str
    score: float
    text: str
    tokens: int  # Σ token_count các điểm ghép (spec 6.3 ghi `_tokens`)
