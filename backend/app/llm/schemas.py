"""Schema đầu ra của 6 prompt Phase 3 (phase3 mục 7.4). Tên class = trường `schema:` của `config/prompts/<id>.yaml`;
registry từ chối khởi động nếu tên không có trong `SCHEMAS`.

`extra="forbid"`: trường ngoài schema → sai schema → một lần sửa (P2 mục 9) — b03 "không trả trường ngoài schema".
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_OUT = ConfigDict(extra="forbid")


class InjectionJudgeOut(BaseModel):
    """B02 §4 — `b02_injection_judge`."""

    model_config = _OUT

    is_attack: bool
    category: Literal["override", "impersonation", "system_spoof", "prompt_leak", "other", "none"]
    reason: str = Field(max_length=200)


class IntentItem(BaseModel):
    """B03 §4."""

    model_config = _OUT

    type: Literal["account", "vpn", "software", "access", "out_of_scope"]
    confidence: float = Field(ge=0, le=1)
    span: str = Field(max_length=500)  # phần câu dẫn tới intent [Chốt]
    action_hint: str | None = None  # ví dụ "renew_vpn_cert"
    slots: dict[str, str] = Field(default_factory=dict)  # đúng chữ người dùng — B3 làm sạch (3-Q1)


class ClassifyOut(BaseModel):
    """B03 §4 — `b03_classify`."""

    model_config = _OUT

    intents: list[IntentItem] = Field(max_length=4)
    is_multi: bool


class NeedTypeOut(BaseModel):
    """B10 §4 — `b10_need_type`."""

    model_config = _OUT

    type: Literal["info", "action"]
    confidence: float = Field(ge=0, le=1)


class AnswerOut(BaseModel):
    """B10 §4 — `b10_answer`, sửa theo PLAN-3d Q-3d-6: B10 gốc có `citations` `min_length=1`, mâu thuẫn
    `cannot_answer=true` (không có căn cứ thì không có gì để trích) → model trả đúng ý lại ra `LLMSchemaError` → E2
    thay vì E3. Nay hai chiều: `cannot_answer=true` cho phép `citations=[]` (B10 đi E3 `no_grounding`);
    `cannot_answer=false` bắt buộc ≥ 1 trích dẫn."""

    model_config = _OUT

    answer_markdown: str = Field(max_length=2500)
    citations: list[str] = Field(default_factory=list)  # anchor_chunk_id — B10 kiểm thuộc top-5
    steps: list[str] | None = None  # mức hỗ trợ 2: hướng dẫn từng bước
    cannot_answer: bool = False  # LLM tự nhận không đủ căn cứ

    @model_validator(mode="after")
    def _citations_unless_cannot_answer(self) -> "AnswerOut":
        if not self.cannot_answer and not self.citations:
            raise ValueError("citations phải có ít nhất 1 anchor_chunk_id khi cannot_answer=false")
        return self


class QuestionOut(BaseModel):
    """B11 — `b11_clarify_question`."""

    model_config = _OUT

    text: str = Field(min_length=1, max_length=300)


class ExtractSlotsOut(BaseModel):
    """B11 — `b11_extract_slots`."""

    model_config = _OUT

    slots: dict[str, str] = Field(default_factory=dict)
    off_topic: bool


SCHEMAS: dict[str, type[BaseModel]] = {
    cls.__name__: cls
    for cls in (InjectionJudgeOut, ClassifyOut, NeedTypeOut, AnswerOut, QuestionOut, ExtractSlotsOut)
}
