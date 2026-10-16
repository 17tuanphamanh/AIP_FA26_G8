"""TicketState — state LangGraph truyền qua mọi node (P1 mục 4).

Kiểu phụ ChunkRef (B08), RiskDecision (B12 mục 4.1), ExecutionResult (B17) nằm ở đây vì domain
không được import rag/risk/executor. raw_request KHÔNG có trong state — chỉ redacted_request (D-07).
"""

import re
import typing
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator

from app.domain.action import Action
from app.domain.context import RequesterContext

# Khuôn tin nhắn: `domain/messages.py` (3g, phase3 10.2) — khoá đóng, `sources` chỉ 3 khoá.
type Msg = dict[str, Any]


def append_capped[T](n: int) -> Callable[[list[T], list[T]], list[T]]:
    """Reducer LangGraph: nối tin mới vào cuối, chỉ giữ n phần tử cuối."""
    if n <= 0:
        raise ValueError("n phải dương")

    def reducer(left: list[T], right: list[T]) -> list[T]:
        return [*left, *right][-n:]

    return reducer


class ChunkRef(BaseModel):
    chunk_id: str
    doc_id: str
    version: int
    seq: int
    title: str
    heading_path: str
    score: float
    excerpt: str = Field(max_length=600)


class RiskDecision(BaseModel):
    decided_by: Literal["rule", "llm"]
    policy_decision: Literal["allow", "approval_required", "deny"] | None
    matched_rule_id: str | None
    raw_prob: float | None
    calibrated_prob: float | None
    p_method: Literal["self_report", "sampling_k5"] | None
    risk_level: Literal["low", "medium", "high"]
    route: Literal["AUTO", "HITL", "ESCALATE_L2"]
    reason: str  # đọc được bởi người [Chốt nguyên tắc 2]
    thresholds: tuple[float, float] | None


# Kết quả tool ghi được mang theo tới B18 (Q-3h-2 A): khoá ĐÓNG, giá trị qua regex chặt — tin kết quả và ghi chú bàn giao chỉ
# ghép từ enum/định danh/ngày (P6, luật 8.9). `serial` theo mẫu mock (`VPN-2025-0342`, bản mới cấp `VPN-NEW-0001`).
EXEC_OUTPUT_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "serial": re.compile(r"VPN-(?:\d{4}|NEW)-\d{4,6}"),
    "expires_on": re.compile(r"\d{4}-\d{2}-\d{2}"),
    # Phase 5 T24 P4: kết quả tool ghi account/software/access (mock `ad.py`, `software.py`, `fileserver.py`)
    "delivered_via": re.compile(r"email|sms"),
    "version": re.compile(r"[0-9]+(\.[0-9]+){0,3}"),  # Q-T24-7: chỉ số + dấu chấm (không nhận chuỗi kiểu tên miền)
    "level": re.compile(r"read|write|full"),
    "software": re.compile(r"[a-z0-9][a-z0-9.+#-]{0,63}"),  # cùng mẫu `domain.action.SOFTWARE_NAME`
    "license_id": re.compile(r"LIC-[a-z0-9.+#-]{1,64}-[0-9]{3}"),
}


def _valid_output(key: str, value: object) -> bool:
    pattern = EXEC_OUTPUT_PATTERNS.get(key)
    if pattern is None or not isinstance(value, str) or not pattern.fullmatch(value):
        return False
    if key == "expires_on":
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
    return True


class ExecutionResult(BaseModel):
    success: bool
    steps_done: list[str]
    failed_step: str | None
    rollback_status: Literal["undone", "partial", "undo_failed", "not_attempted", "none_needed"]
    rollback_details: list[tuple[str, str]]  # (step, "undone" | "UNDO_FAILED: …")
    action_plan_hash_matched: bool | None
    handoff_note: str | None
    # Q-3h-2 (A): khoá lạ / giá trị sai mẫu bị BỎ (không lỗi, không vào tin). Mặc định {} — checkpoint cũ không có trường này
    # vẫn nạp được.
    outputs: dict[str, str] = Field(default_factory=dict)

    @field_validator("outputs", mode="before")
    @classmethod
    def _closed_outputs(cls, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            return {}
        return {str(k): v for k, v in value.items() if _valid_output(str(k), v)}


class TicketState(TypedDict, total=False):
    # định danh
    ticket_id: str
    parent_ticket_id: str | None
    is_parent: bool
    children: list[str]
    parent_round: int  # chỉ ticket cha (D-31)
    awaiting: dict[str, str]  # chỉ ticket cha (D-31): ý đang chờ người dùng
    # chỉ ticket cha (Phase 5 T20b P3): seed bền của từng con (bảng 5.2.3, trừ `requester_context`) — ghi ở B5 TRƯỚC khi con chạy
    child_seeds: dict[str, dict[str, Any]]
    session_id: str
    turn_id: str
    # người gửi — do B1 chụp, chỉ đọc sau đó
    requester_context: RequesterContext
    # nội dung
    redacted_request: str  # đã qua privacy guard (D-07)
    # sàng lọc B2 (phase3 mục 3.1, 8.5): {layer_decided, pattern_id, group, p_mal, llm_category} — KHÔNG văn bản
    screening: dict[str, Any]
    security_flag: bool  # B2 E2 khi không sàng lọc được (L3 + L4 lỗi) → B20 ghi vào ghi chú bàn giao
    conversation: Annotated[list[Msg], append_capped(20)]
    # phân loại / chẩn đoán / tra cứu
    intent: str | None
    intent_confidence: float | None
    span: str | None
    slots: dict[str, Any]  # THAM SỐ người dùng/LLM (qua domain.slots.sanitize_slots) — KHÔNG là căn cứ cho luật (3-Q1)
    # DỮ KIỆN cho luật M5 (phase3 3.2): chỉ key thuộc domain.facts.FACT_KEYS, CHỈ B6 (infer_vpn) và B11 validate_targets
    # ghi; B3 đặt lại {}. Không đường nào từ slots/đầu ra LLM vào đây (G-01).
    facts: dict[str, str | int | bool]
    ctx_flags: dict[str, bool]  # {target_is_other} — B6 ghi, B12 build_ctx đọc (VPN Phase 3 luôn false)
    rediagnose: bool  # D-20 (cờ tắt) — 3f chỉ khai báo, B6 ghi False; chế độ chẩn đoán lại ở 3g ("Việc treo" 11)
    changed_slots: list[str]  # D-20 — B11 ghi ở 3g
    missing_slots: list[str]
    # B6: kết quả 3 tool dạng JSON (`model_dump(mode="json")`, không phải model Pydantic — PLAN-3f mục 3); None = 404/rỗng
    diagnostics: dict[str, Any]
    tool_errors: list[str]
    tool_retry_count: int
    retrieved: list[ChunkRef]
    retrieval_score: float
    retrieval_error: str | None
    kb_version: str | None
    intent_filter_fallback: bool
    need_type: Literal["info", "action"] | None
    answer_ref: str | None  # B10 (3g): ref do `notify_user` trả cho câu trả lời — phase3 3.1
    # hành động + rủi ro + duyệt
    intended_action: Action | None
    action_plan_hash: str | None
    risk: RiskDecision | None
    approval_id: str | None
    # Bằng chứng duyệt — chuyển cấm số 2 kiểm trường này (P1 mục 4, 5.1.1); approval_wait đặt.
    approval_result: Literal["approved", "rejected", "timeout"] | None
    execution: ExecutionResult | None
    # bộ đếm [Chốt]
    clarification_turns: int
    reasoning_loops: int
    off_topic_streak: int
    # điều khiển
    status: str  # 1 trong 14 S_*
    next: str  # tên node kế tiếp, do goto() đặt
    exit_code: str | None
    block_reason: str | None
    close_reason: str | None
    # Ghi chú escalate: key không khai báo ở đây bị LangGraph bỏ IM LẶNG khi node trả về.
    escalation_note: str | None  # câu đọc được (boundary E9 — P1 mục 5.2; B1/B17 …)
    escalation_reason_detail: str | None  # D-27 — B20 chép vào escalations.reason_detail
    aggregate_status: str | None  # chỉ ticket cha (D-30) — AGGREGATE_STATUSES ở db/models.py


STATE_KEYS: frozenset[str] = frozenset(typing.get_type_hints(TicketState))


class UnknownStateKey(ValueError):
    """Node trả về key không khai báo trong `TicketState`. LangGraph 1.2 bỏ IM LẶNG key lạ (dữ liệu
    mất mà không ai biết) — chặn thành lỗi để boundary đưa về E9 (quyết định Q-A 2b-2)."""


def check_state_keys(keys: Iterable[str]) -> None:
    unknown = sorted(set(keys) - STATE_KEYS)
    if unknown:
        raise UnknownStateKey(f"key không có trong TicketState: {unknown}")
