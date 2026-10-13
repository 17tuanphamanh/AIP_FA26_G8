"""22 bảng — 17 bảng gốc dựng lại từ claude/thiet-ke-database.md + NGU-CANH + huong-dan 17,
rồi áp docs/spec/build/nen-tang/P7-db-thay-doi.md. Bảng nguồn từng cột: backend/app/db/README.md.

Giá trị CHECK của trạng thái / mã thoát / block_reason / close_reason / các Literal lấy từ
app.domain — không viết lại chuỗi. Working state (14 trạng thái, Action đang dựng, hội thoại)
nằm trong checkpoint LangGraph, KHÔNG nhân đôi vào bảng [Chốt DB vòng 3].
"""

import typing
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.context import RequesterContext
from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import ALL_STATES, S_ESCALATED, TERMINAL
from app.domain.ticket_state import ExecutionResult, RiskDecision, TicketState

# ---- Miền giá trị (từ app.domain) ------------------------------------------------------------


def _literal_values(annotation: Any) -> tuple[str, ...]:
    """Lấy các giá trị chuỗi của Literal (bỏ None) — `Literal[...] | None` cũng được."""
    values: list[str] = []
    for arg in typing.get_args(annotation):
        if typing.get_origin(arg) is typing.Literal:
            values.extend(typing.get_args(arg))
        elif isinstance(arg, str):
            values.append(arg)
    return tuple(values)


_ticket_hints = typing.get_type_hints(TicketState)

ROLES = _literal_values(RequesterContext.model_fields["role"].annotation)
EMPLOYMENT_STATUSES = _literal_values(RequesterContext.model_fields["employment_status"].annotation)
FINAL_STATES = tuple(sorted(TERMINAL | {S_ESCALATED}))  # N4 mục 9.2: 4 giá trị
EXIT_CODES = tuple(c.value for c in ExitCode)
BLOCK_REASONS = tuple(r.value for r in BlockReason)
CLOSE_REASONS = tuple(r.value for r in CloseReason)
STATES = tuple(sorted(ALL_STATES))
DECIDED_BY = _literal_values(RiskDecision.model_fields["decided_by"].annotation)
POLICY_DECISIONS = _literal_values(RiskDecision.model_fields["policy_decision"].annotation)
RISK_LEVELS = _literal_values(RiskDecision.model_fields["risk_level"].annotation)
P_METHODS = _literal_values(RiskDecision.model_fields["p_method"].annotation)
ROLLBACK_STATUSES = _literal_values(ExecutionResult.model_fields["rollback_status"].annotation)
APPROVAL_RESULTS = _literal_values(_ticket_hints["approval_result"])

# Chưa có hằng trong domain — nguồn ghi cạnh từng dòng.
INTENTS = ("account", "vpn", "software", "access")  # N3-9.3, phạm vi 4 loại [Chốt]
RESOLUTION_PATHS = ("auto", "approved", "rejected", "escalated", "deflected")  # N3-9.1
AGGREGATE_STATUSES = (  # B03-B05 mục 5.4
    "ALL_RESOLVED", "PARTIALLY_ESCALATED", "ALL_ESCALATED",
    "PARTIALLY_REJECTED", "ALL_REJECTED", "MIXED",
)  # fmt: skip
APPROVAL_STATUSES = ("pending", "approved", "rejected", "timeout", "late_ignored")  # B15, P7 2.6
CONFLICT_TYPES = ("self", "boss_of_approver", "targets_approver")  # P7 2.6
TXN_STATUSES = ("begun", "undone", "undo_failed")  # TK + B17 mục 8 (begun — chốt Phase 1a)
CLOSE_RESULTS = ("completed", "confirmed_denial", "reopened_as_new")  # B20 mục 4.3
KB_REQUEST_TYPES = (*INTENTS, "general")  # P3 mục 4
KB_DOC_TYPES = ("policy", "howto", "troubleshooting", "faq")  # P3 mục 4
KB_SENSITIVITY = ("public", "internal", "restricted")  # P3 mục 4
KB_EVAL_STATUSES = ("evaluated", "unevaluated")  # migration 0006 (3-Q15)
TURN_EVENTS = ("submit", "resume", "recover")  # P1 mục 7 (runner)
SPAN_TYPES = ("node", "llm", "tool", "rag")  # HD17.1
SPAN_STATUSES = ("ok", "error", "interrupted")  # P1 mục 9
ALERT_STATUSES = ("open", "acked")  # P9 mục 7
REVOKE_REASONS = ("logout", "rotated", "reuse_detected", "user_disabled", "admin", "expired")
SECURITY_EVENT_TYPES = (  # P7 2.3
    "login_success", "login_failed", "account_locked", "logout", "token_refreshed",
    "refresh_reuse_detected", "session_revoked", "permission_denied", "role_changed",
    "mfa_failed", "policy_saved", "injection_detected", "privacy_secret_redacted",
    "mfa_enrolled", "mfa_reset",  # migration 0002 (P7 2.3 bản 1.5)
)  # fmt: skip
AUTH_FAILURE_TYPES = ("login_failed", "mfa_failed")  # view auth_failures (P7 2.3)
LLM_CACHE_MODES = ("runtime", "eval")  # P7 2.4
WAIT_KINDS = ("clarify", "confirm")  # P7 2.5
SIDE_EFFECT_KINDS = (  # P7 2.8
    "notify_user", "notify_approver", "deadline_set", "approval_create",
    "child_create", "child_submit", "escalation_create", "child_event",
    "security_event",  # migration 0007 (phase3 mục 8.2): injection_detected ghi qua effects.once
)  # fmt: skip
NOTICE_KINDS = ("answer", "question", "result", "rejection", "escalation")  # P7 2.9
NOTICE_NEEDS = ("none", "answer", "confirm")  # P7 2.9


def check_in(column: str, values: Iterable[str], name: str | None = None) -> CheckConstraint:
    """CHECK column IN (...) — NULL vẫn qua (Postgres), đúng ý P7 2.10 cho ticket cha."""
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name or column)


# ---- Base ------------------------------------------------------------------------------------

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _user_fk(nullable: bool = True) -> Any:
    return mapped_column(String(64), ForeignKey("users.user_id"), nullable=nullable)


def _ticket_fk(nullable: bool = False) -> Any:
    return mapped_column(String(64), ForeignKey("tickets.ticket_id"), nullable=nullable)


# ---- 1. users (TK ĐỀ XUẤT + P7 2.1) — KHÔNG có cột mật khẩu ---------------------------------


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        check_in("role", ROLES),
        check_in("employment_status", EMPLOYMENT_STATUSES),
    )

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    department: Mapped[str | None] = mapped_column(String(64))
    is_privileged_account: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    ad_object_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    manager_id: Mapped[str | None] = _user_fk()
    employment_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    hired_at: Mapped[date | None] = mapped_column(Date)
    mfa_secret_enc: Mapped[bytes | None] = mapped_column(BYTEA)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


# ---- 2. sessions (HD17.1 + P7 2.2) -----------------------------------------------------------


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        check_in("revoke_reason", REVOKE_REASONS),
        Index("ix_sessions_family", "token_family_id"),
        Index("ix_sessions_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = _user_fk(nullable=False)
    created_at: Mapped[datetime] = _now()
    refresh_token_hash: Mapped[str | None] = mapped_column(CHAR(64), unique=True)
    token_family_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(24))
    ip_prefix: Mapped[str | None] = mapped_column(String(48))  # che octet cuối
    user_agent_hash: Mapped[str | None] = mapped_column(CHAR(64))


# ---- 3–4. policy_versions, policy_rules (TK, N3-9.3) ----------------------------------------


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        Index(
            "ux_policy_versions_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_by: Mapped[str | None] = _user_fk()
    updated_at: Mapped[datetime] = _now()


class PolicyRule(Base):
    """Bản mirror có cấu trúc cho UI Trưởng BP; engine KHÔNG query bảng này theo ticket (TK)."""

    __tablename__ = "policy_rules"
    __table_args__ = (
        PrimaryKeyConstraint("rule_id", "version_id"),
        check_in("rule_type", POLICY_DECISIONS),
        check_in("intent", INTENTS),
    )

    rule_id: Mapped[str] = mapped_column(String(16))
    version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.version_id"))
    rule_type: Mapped[str] = mapped_column(String(24), nullable=False)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


# ---- 5–6. kb_versions, kb_documents (P3 mục 4, 8) -------------------------------------------


class KbVersion(Base):
    __tablename__ = "kb_versions"
    __table_args__ = (
        check_in("eval_status", KB_EVAL_STATUSES),
        # Nhiều nhất một bản hiện hành (migration 0006, Q-3b-5).
        Index("ux_kb_versions_current", "is_current", unique=True, postgresql_where=text("is_current")),
    )

    kb_version: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    created_at: Mapped[datetime] = _now()
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recall_at5: Mapped[float | None] = mapped_column(Float)
    false_grounding_rate: Mapped[float | None] = mapped_column(Float)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # migration 0006 (3-Q15, 3-Q16): số đoạn; 'unevaluated' = nạp không có bộ kiểm tra (dev/test).
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    eval_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'evaluated'"))


class KbDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        PrimaryKeyConstraint("doc_id", "version"),
        check_in("request_type", KB_REQUEST_TYPES),
        check_in("doc_type", KB_DOC_TYPES),
        check_in("sensitivity", KB_SENSITIVITY),
    )

    doc_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    owner: Mapped[str | None] = _user_fk()
    updated_at: Mapped[date] = mapped_column(Date, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    distractor: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    kb_version: Mapped[str | None] = mapped_column(CHAR(64), ForeignKey("kb_versions.kb_version"))
    # sha256(front matter chuẩn + thân bài) — sửa nội dung mà không tăng version → ingest dừng (0006, 3-Q4).
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64))


# ---- 7. tickets (TK 20 cột + P7 is_parent) — chỉ ghi lúc tạo và một lần ở B20 ---------------


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        check_in("requester_role", ROLES),
        check_in("intent", INTENTS),
        check_in("final_state", FINAL_STATES),
        check_in("exit_code", EXIT_CODES),
        check_in("block_reason", BLOCK_REASONS),
        check_in("close_reason", CLOSE_REASONS),  # NULL qua được — ticket cha (P7 2.10)
        check_in("resolution_path", RESOLUTION_PATHS),
        check_in("aggregate_status", AGGREGATE_STATUSES),
        Index("ix_tickets_leaf", "created_at", postgresql_where=text("is_parent = false")),
        Index("ix_tickets_parent", "parent_ticket_id"),
    )

    ticket_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_ticket_id: Mapped[str | None] = _ticket_fk(nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("sessions.session_id"))
    requester_id: Mapped[str] = _user_fk(nullable=False)
    requester_role: Mapped[str] = mapped_column(String(16), nullable=False)
    requester_dept: Mapped[str | None] = mapped_column(String(64))
    redacted_request: Mapped[str] = mapped_column(Text, nullable=False)  # D-07: đã che
    intent: Mapped[str | None] = mapped_column(String(16))
    slots: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    final_state: Mapped[str | None] = mapped_column(String(24))
    exit_code: Mapped[str | None] = mapped_column(String(4))
    block_reason: Mapped[str | None] = mapped_column(String(32))
    close_reason: Mapped[str | None] = mapped_column(String(40))
    resolution_path: Mapped[str | None] = mapped_column(String(16))
    aggregate_status: Mapped[str | None] = mapped_column(String(24))
    auto_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    total_turns: Mapped[int | None] = mapped_column(Integer)
    total_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_parent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


# ---- 8. approvals (B15 mục 8, P7 2.6, TK) ---------------------------------------------------


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        check_in("status", APPROVAL_STATUSES),
        check_in("conflict_type", CONFLICT_TYPES),
        CheckConstraint("status <> 'rejected' OR note IS NOT NULL", name="rejected_needs_note"),
        Index(
            "ux_approvals_one_pending",
            "ticket_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_approvals_ticket", "ticket_id"),  # M9 A4, migration 0009
    )

    approval_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = _ticket_fk()
    approver_id: Mapped[str] = _user_fk(nullable=False)
    backup_approver_id: Mapped[str | None] = _user_fk()
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action_plan_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    conflict_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    conflict_type: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = _user_fk()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_1_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_2_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


# ---- 9. transaction_log (TK, N4 mục 5.3, B17) -----------------------------------------------


class TransactionLogEntry(Base):
    __tablename__ = "transaction_log"
    __table_args__ = (
        check_in("status", TXN_STATUSES),
        Index("ix_transaction_log_ticket", "ticket_id"),
    )

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = _ticket_fk()
    turn_id: Mapped[str | None] = mapped_column(String(64))
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)  # "UNDO_FAILED: …"
    created_at: Mapped[datetime] = _now()


# ---- 10–11. exit_code_priority, escalations (B20 mục 4, 8; P7 2.11) -------------------------


class ExitCodePriority(Base):
    __tablename__ = "exit_code_priority"
    __table_args__ = (check_in("exit_code", EXIT_CODES),)

    exit_code: Mapped[str] = mapped_column(String(4), primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (
        check_in("exit_code", EXIT_CODES),
        check_in("close_result", CLOSE_RESULTS),
        Index("ix_escalations_ticket", "ticket_id"),
        Index("ix_escalations_closed_at_exit_code", "closed_at", "exit_code"),  # P9 mục 4
    )

    escalation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = _ticket_fk()
    exit_code: Mapped[str] = mapped_column(
        String(4), ForeignKey("exit_code_priority.exit_code"), nullable=False
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(String(48))
    handoff_note: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # 4 phần (B20 4.2)
    is_deny_case: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    assigned_to: Mapped[str | None] = _user_fk()
    close_result: Mapped[str | None] = mapped_column(String(24))
    closed_by: Mapped[str | None] = _user_fk()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_ticket_id: Mapped[str | None] = _ticket_fk(nullable=True)
    created_at: Mapped[datetime] = _now()


# ---- 12. audit_logs (N3-9.2, N4-9, TK, P7 2.7, B20) — append-only ---------------------------


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        check_in("from_status", STATES),
        check_in("to_status", STATES),
        check_in("intent", INTENTS),
        check_in("decided_by", DECIDED_BY),
        check_in("policy_decision", POLICY_DECISIONS),
        check_in("risk_level", RISK_LEVELS),
        check_in("p_method", P_METHODS),
        check_in("approval_result", APPROVAL_RESULTS),
        check_in("rollback_status", ROLLBACK_STATUSES),
        check_in("final_state", FINAL_STATES),
        check_in("exit_code", EXIT_CODES),
        check_in("block_reason", BLOCK_REASONS),
        check_in("close_reason", CLOSE_REASONS),
        CheckConstraint("raw_prob BETWEEN 0 AND 1", name="raw_prob_range"),
        CheckConstraint("calibrated_prob BETWEEN 0 AND 1", name="calibrated_prob_range"),
        Index(
            "ux_audit_idem",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_audit_logs_ticket", "ticket_id", "created_at"),
        Index("ix_audit_logs_step_created_at", "step", "created_at"),  # P9 mục 4
        Index(  # M9 A4, migration 0009
            "ix_audit_logs_exit_created_at",
            "created_at",
            postgresql_where=text("exit_code IS NOT NULL"),
        ),
    )

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = _ticket_fk()
    created_at: Mapped[datetime] = _now()
    turn_id: Mapped[str | None] = mapped_column(String(64))
    loop_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    idempotency_key: Mapped[str | None] = mapped_column(CHAR(64))
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    intended_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outcome: Mapped[str | None] = mapped_column(String(32))
    kb_version: Mapped[str | None] = mapped_column(CHAR(64))
    # điểm 1 (B3)
    intent: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    # điểm 2 (B6)
    tools_called: Mapped[list[Any] | None] = mapped_column(JSONB)
    slots_inferred: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tool_retry_count: Mapped[int | None] = mapped_column(SmallInteger)
    # điểm 3 (B8)
    query: Mapped[str | None] = mapped_column(Text)
    top_score: Mapped[float | None] = mapped_column(Float)
    doc_ids: Mapped[list[Any] | None] = mapped_column(JSONB)
    retrieval_error: Mapped[str | None] = mapped_column(Text)
    # điểm 4 (B12–B14) — quan trọng nhất
    decided_by: Mapped[str | None] = mapped_column(String(8))
    policy_decision: Mapped[str | None] = mapped_column(String(24))
    risk_level: Mapped[str | None] = mapped_column(String(8))
    reason: Mapped[str | None] = mapped_column(Text)
    matched_rule_id: Mapped[str | None] = mapped_column(String(16))
    calibrated_prob: Mapped[float | None] = mapped_column(Float)
    raw_prob: Mapped[float | None] = mapped_column(Float)  # B12 mục 8, P8 fit calibrator
    p_method: Mapped[str | None] = mapped_column(String(16))
    # điểm 5 (B15)
    approver_id: Mapped[str | None] = _user_fk()
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conflict_detected: Mapped[bool | None] = mapped_column(Boolean)
    action_plan_hash: Mapped[str | None] = mapped_column(CHAR(64))
    # điểm 6 (B16)
    approval_result: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    response_time_seconds: Mapped[float | None] = mapped_column(Float)
    # điểm 7 (B17)
    success: Mapped[bool | None] = mapped_column(Boolean)
    rollback_status: Mapped[str | None] = mapped_column(String(16))
    action_plan_hash_matched: Mapped[bool | None] = mapped_column(Boolean)
    # điểm 8 (B20)
    final_state: Mapped[str | None] = mapped_column(String(24))
    exit_code: Mapped[str | None] = mapped_column(String(4))
    block_reason: Mapped[str | None] = mapped_column(String(32))
    close_reason: Mapped[str | None] = mapped_column(String(40))
    total_turns: Mapped[int | None] = mapped_column(Integer)
    total_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    # ghi đè (B20 mục 8, N4 mục 5.4)
    original_decision: Mapped[str | None] = mapped_column(String(24))
    override_decision: Mapped[str | None] = mapped_column(String(24))
    overrider_id: Mapped[str | None] = _user_fk()
    # phần bổ sung của từng nhánh: thresholds, all_matched, layer, model_probs…
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


# ---- 13–16. lineage, turns, spans, llm_calls (HD17.1, P1, P2) -------------------------------


class Lineage(Base):
    __tablename__ = "lineage"
    __table_args__ = (
        check_in("p_method", P_METHODS),
        Index("ix_lineage_ticket", "ticket_id"),
    )

    lineage_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = _ticket_fk()
    turn_id: Mapped[str | None] = mapped_column(String(64))
    step: Mapped[str] = mapped_column(String(32), nullable=False)  # B12-B14 hoặc B10
    policy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("policy_versions.version_id")
    )
    prompt_id: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(128))
    calibrator_version: Mapped[str | None] = mapped_column(String(64))
    kb_version: Mapped[str | None] = mapped_column(CHAR(64))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    p_method: Mapped[str | None] = mapped_column(String(16))
    intent_model_version: Mapped[str | None] = mapped_column(String(64))  # P11
    guard_model_version: Mapped[str | None] = mapped_column(String(64))  # P11
    created_at: Mapped[datetime] = _now()


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        check_in("event_type", TURN_EVENTS),
        Index("ix_turns_ticket", "ticket_id"),
        Index("ix_turns_open", "started_at", postgresql_where=text("ended_at IS NULL")),
    )

    turn_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[str] = _ticket_fk()
    session_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("sessions.session_id"))
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = _now()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Số lần worker chạy lại lượt dở dang — tăng TRƯỚC khi chạy (migration 0005, 2b-Q6).
    recover_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )


class Span(Base):
    __tablename__ = "spans"
    __table_args__ = (
        check_in("span_type", SPAN_TYPES),
        check_in("status", SPAN_STATUSES),
        Index("ix_spans_turn", "turn_id"),
        Index("ix_spans_trace", "trace_id"),
    )

    span_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(32))
    turn_id: Mapped[str] = mapped_column(String(64), ForeignKey("turns.turn_id"), nullable=False)
    span_type: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = _now()
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_created_at", "created_at"),)  # P9 mục 4

    call_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    span_id: Mapped[str] = mapped_column(String(32), ForeignKey("spans.span_id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64))
    prompt_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(CHAR(64))
    prompt_full: Mapped[str | None] = mapped_column(Text)  # chỉ khi EVAL_MODE (P2 mục 11)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    json_valid_first_try: Mapped[bool | None] = mapped_column(Boolean)
    used_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


# ---- 17. alerts (P9) ------------------------------------------------------------------------


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        check_in("status", ALERT_STATUSES),
        # Chống trùng theo (luật, đối tượng, cửa sổ) — migration 0004, quyết định Q1 26/09/2026.
        UniqueConstraint("rule_id", "subject", "window_start"),
    )

    alert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(48), nullable=False)
    # user_id (luật theo người) | ticket_id (luật theo ticket) | SYSTEM_SUBJECT '' (luật tổng hợp) —
    # domain/alerts.py. KHÔNG có DEFAULT: INSERT quên subject phải lỗi (gộp cảnh báo = False Negative).
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'open'"))
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    acked_by: Mapped[str | None] = _user_fk()
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


# ---- 18–22. năm bảng mới của P7 (DDL nguyên văn) --------------------------------------------


class SecurityEvent(Base):
    """P7 2.3 — append-only; view auth_failures tạo ở migration."""

    __tablename__ = "security_events"
    __table_args__ = (
        check_in("event_type", SECURITY_EVENT_TYPES),
        Index("ix_sec_user_time", "username_attempted", text("occurred_at DESC")),
        Index("ix_sec_type_time", "event_type", text("occurred_at DESC")),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = _now()
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = _user_fk()
    username_attempted: Mapped[str | None] = mapped_column(String(128))
    ip_prefix: Mapped[str | None] = mapped_column(String(48))
    route: Mapped[str | None] = mapped_column(String(128))
    ticket_id: Mapped[str | None] = mapped_column(String(64))  # không FK (P7)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class LlmCache(Base):
    __tablename__ = "llm_cache"
    __table_args__ = (
        check_in("mode", LLM_CACHE_MODES),
        Index("ix_llm_cache_exp", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
    )

    cache_key: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    prompt_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String(8), nullable=False)


class WaitDeadline(Base):
    __tablename__ = "wait_deadlines"
    __table_args__ = (
        PrimaryKeyConstraint("ticket_id", "kind", "created_turn"),
        check_in("kind", WAIT_KINDS),
        Index("ix_wait_due", "deadline", postgresql_where=text("fired_at IS NULL")),
    )

    ticket_id: Mapped[str] = _ticket_fk()
    kind: Mapped[str] = mapped_column(String(12))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_turn: Mapped[str] = mapped_column(String(64))
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SideEffect(Base):
    """P7 2.8 (D-18) — chỉ mục chống trùng của effects.once; không append-only."""

    __tablename__ = "side_effects"
    __table_args__ = (
        check_in("kind", SIDE_EFFECT_KINDS),
        Index("ix_side_effects_ticket", "ticket_id"),
    )

    effect_key: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    ticket_id: Mapped[str] = _ticket_fk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[str] = mapped_column(String(16), nullable=False)
    turn_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result_ref: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _now()


class ChildNotice(Base):
    """P7 2.9 (D-31) — hộp thư của ticket con, cha gom thành một tin."""

    __tablename__ = "child_notices"
    __table_args__ = (
        check_in("kind", NOTICE_KINDS),
        check_in("needs", NOTICE_NEEDS),
        CheckConstraint(
            "(delivered_at IS NULL) = (delivered_round IS NULL)", name="delivered_pair"
        ),
        Index(
            "ix_child_notices_pending",
            "parent_ticket_id",
            postgresql_where=text("delivered_at IS NULL"),
        ),
    )

    notice_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_ticket_id: Mapped[str] = _ticket_fk()
    child_ticket_id: Mapped[str] = _ticket_fk()
    source_step: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    needs: Mapped[str] = mapped_column(String(8), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)  # đã qua privacy guard
    effect_key: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _now()
    delivered_round: Mapped[int | None] = mapped_column(SmallInteger)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

