"""Ràng buộc ở tầng DB — P7 mục 5 (9 tiêu chí) + P6 mục 6 (role, trigger append-only)."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _sha(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def insert(conn: Connection, table: str, **values: Any) -> None:
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), values)


@pytest.fixture
def seeded(rw: Engine) -> Iterator[dict[str, str]]:
    """Một user + một ticket, ghi bằng app_rw (như backend)."""
    user, ticket = _id("u"), _id("t")
    with rw.begin() as conn:
        insert(conn, "users", user_id=user, username=user, role="employee")
        insert(
            conn, "tickets", ticket_id=ticket, requester_id=user, requester_role="employee",
            redacted_request="Quên mật khẩu email",
        )  # fmt: skip
    yield {"user": user, "ticket": ticket}


def _audit(conn: Connection, ticket: str, **extra: Any) -> None:
    insert(conn, "audit_logs", ticket_id=ticket, step="B3", event="classified", **extra)


# ---- 1–2. CHECK, users không có cột mật khẩu -------------------------------------------------


def test_security_event_unknown_type_rejected(rw: Engine) -> None:
    with pytest.raises(DBAPIError, match="ck_security_events_event_type"), rw.begin() as conn:
        insert(conn, "security_events", event_type="hacked")


def test_users_has_no_password_column(owner: Engine) -> None:
    with owner.connect() as conn:
        cols: Any = conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
        ).scalars()
        assert not [c for c in cols if "password" in c]


# ---- 3. audit_logs, security_events append-only: quyền app_rw + trigger (owner) -------------


@pytest.mark.parametrize("stmt", ["UPDATE audit_logs SET note = 'x'", "DELETE FROM audit_logs"])
def test_app_rw_cannot_mutate_audit_logs(rw: Engine, seeded: dict[str, str], stmt: str) -> None:
    with rw.begin() as conn:
        _audit(conn, seeded["ticket"])
    with pytest.raises(DBAPIError, match="permission denied"), rw.begin() as conn:
        conn.execute(text(stmt))


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE audit_logs SET note = 'sửa lén'",
        "DELETE FROM audit_logs",
        "UPDATE security_events SET route = 'x'",
        "DELETE FROM security_events",
    ],
)
def test_trigger_blocks_owner_mutation(
    owner: Engine, rw: Engine, seeded: dict[str, str], stmt: str
) -> None:
    with rw.begin() as conn:
        _audit(conn, seeded["ticket"])
        insert(conn, "security_events", event_type="login_failed", username_attempted="x")
    with pytest.raises(DBAPIError, match="append-only table"), owner.begin() as conn:
        conn.execute(text(stmt))


@pytest.mark.parametrize("table", ["audit_logs", "security_events"])
def test_trigger_blocks_owner_truncate(owner: Engine, table: str) -> None:
    with pytest.raises(DBAPIError, match="append-only table"), owner.begin() as conn:
        conn.execute(text(f"TRUNCATE {table}"))


def test_app_rw_can_insert_and_read_auth_failures(rw: Engine) -> None:
    name = _id("dò")
    with rw.begin() as conn:
        for _ in range(2):
            insert(conn, "security_events", event_type="login_failed", username_attempted=name)
        insert(conn, "security_events", event_type="login_success", username_attempted=name)
        count = conn.execute(
            text(
                "SELECT count(*) FROM auth_failures WHERE username_attempted = :u "
                "AND occurred_at > now() - interval '10 minutes'"
            ),
            {"u": name},
        ).scalar()
    assert count == 2


# ---- M9 chỉ đọc (role app_monitor) ------------------------------------------------------------


def test_app_monitor_cannot_insert_audit_logs(monitor: Engine, seeded: dict[str, str]) -> None:
    with pytest.raises(DBAPIError, match="permission denied"), monitor.begin() as conn:
        _audit(conn, seeded["ticket"])


def test_app_monitor_can_select_monitor_tables(monitor: Engine) -> None:
    with monitor.connect() as conn:
        for table in ("audit_logs", "escalations", "tickets", "llm_calls", "alerts"):
            conn.execute(text(f"SELECT count(*) FROM {table}"))


def test_app_monitor_cannot_read_side_effects(monitor: Engine) -> None:
    with pytest.raises(DBAPIError, match="permission denied"), monitor.connect() as conn:
        conn.execute(text("SELECT count(*) FROM side_effects"))


# ---- 4. khóa idempotent audit (D-14 v1.2) ----------------------------------------------------

AUDIT_IDEM = (
    "INSERT INTO audit_logs (ticket_id, step, event, turn_id, loop_seq, idempotency_key) "
    "VALUES (:t, :step, :event, :turn, 0, :k) "
    "ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING"
)


def test_audit_idempotency_key(rw: Engine, seeded: dict[str, str]) -> None:
    t, turn = seeded["ticket"], _id("turn")
    with rw.begin() as conn:
        for event in ("user_replied", "user_replied", "action_built"):  # lần 2 = node chạy lại
            params = {"t": t, "step": "B11", "event": event, "turn": turn}
            conn.execute(text(AUDIT_IDEM), {**params, "k": _sha(t, "B11", event, turn, 0)})
        rows: Any = conn.execute(
            text("SELECT event FROM audit_logs WHERE ticket_id = :t ORDER BY log_id"), {"t": t}
        ).scalars()
        assert list(rows) == ["user_replied", "action_built"]


@pytest.mark.parametrize(
    ("column", "value"), [("raw_prob", 1.5), ("calibrated_prob", -0.1), ("p_method", "guess")]
)
def test_audit_risk_fields_checked(
    rw: Engine, seeded: dict[str, str], column: str, value: object
) -> None:
    with pytest.raises(DBAPIError, match="ck_audit_logs"), rw.begin() as conn:
        _audit(conn, seeded["ticket"], **{column: value})


def test_audit_accepts_valid_risk_fields(rw: Engine, seeded: dict[str, str]) -> None:
    with rw.begin() as conn:
        _audit(conn, seeded["ticket"], raw_prob=0.3, calibrated_prob=0.2, p_method="sampling_k5")


# Cổng 1 (huong-dan 5.1, thủ công và tài liệu): "Ghi audit thiếu trường bắt buộc bị từ chối".
@pytest.mark.parametrize("missing", ["ticket_id", "step", "event"])
def test_audit_missing_required_field_rejected(
    rw: Engine, seeded: dict[str, str], missing: str
) -> None:
    row = {"ticket_id": seeded["ticket"], "step": "B3", "event": "classified"}
    del row[missing]
    with pytest.raises(DBAPIError, match="not-null|null value"), rw.begin() as conn:
        insert(conn, "audit_logs", **row)


def test_audit_unknown_ticket_rejected(rw: Engine) -> None:
    with pytest.raises(DBAPIError, match="fk_audit_logs_ticket_id_tickets"), rw.begin() as conn:
        _audit(conn, _id("khong-co"))


# ---- 6. một phiếu pending mỗi ticket; rejected phải có note ----------------------------------


def _approval(conn: Connection, s: dict[str, str], **extra: Any) -> None:
    insert(
        conn, "approvals", ticket_id=s["ticket"], approver_id=s["user"],
        deadline=datetime.now(UTC) + timedelta(minutes=30), action_plan_hash=_sha("plan"),
        **extra,
    )  # fmt: skip


def test_second_pending_approval_rejected(rw: Engine, seeded: dict[str, str]) -> None:
    with rw.begin() as conn:
        _approval(conn, seeded)
    with pytest.raises(DBAPIError, match="ux_approvals_one_pending"), rw.begin() as conn:
        _approval(conn, seeded)


def test_new_pending_allowed_after_decision(rw: Engine, seeded: dict[str, str]) -> None:
    with rw.begin() as conn:
        _approval(conn, seeded, status="timeout")
        _approval(conn, seeded)  # phiếu cũ không còn pending → được tạo phiếu mới


def test_rejected_approval_needs_note(rw: Engine, seeded: dict[str, str]) -> None:
    with pytest.raises(DBAPIError, match="ck_approvals_rejected_needs_note"), rw.begin() as conn:
        _approval(conn, seeded, status="rejected")
    with rw.begin() as conn:
        _approval(conn, seeded, status="rejected", note="Không đúng quy trình")


# ---- 7. side_effects: effects.once cùng khóa → làm đúng 1 lần (D-18) -------------------------

ONCE_INSERT = (
    "INSERT INTO side_effects (effect_key, ticket_id, kind, step, turn_id) "
    "VALUES (:k, :t, 'approval_create', 'B15', :turn) ON CONFLICT DO NOTHING RETURNING effect_key"
)


def test_side_effect_key_is_unique(rw: Engine, seeded: dict[str, str]) -> None:
    t, turn = seeded["ticket"], _id("turn")
    key = _sha(t, "B15", turn, 0, "approval_create", "")
    params = {"k": key, "t": t, "turn": turn}
    with rw.begin() as conn:
        assert conn.execute(text(ONCE_INSERT), params).scalar() == key  # lần đầu: được làm
        conn.execute(text("UPDATE side_effects SET result_ref = 'A-1' WHERE effect_key = :k"), params)
    with rw.begin() as conn:
        assert conn.execute(text(ONCE_INSERT), params).scalar() is None  # lần 2: không làm lại
        ref = conn.execute(text("SELECT result_ref FROM side_effects WHERE effect_key = :k"), params)
        assert ref.scalar() == "A-1"


def test_side_effect_kind_checked(rw: Engine, seeded: dict[str, str]) -> None:
    with pytest.raises(DBAPIError, match="ck_side_effects_kind"), rw.begin() as conn:
        insert(
            conn, "side_effects", effect_key=_sha("x"), ticket_id=seeded["ticket"],
            kind="send_email", step="B18", turn_id="t",
        )  # fmt: skip


# ---- 8–9. ticket con/cha (D-30, D-31) ----------------------------------------------------------


def _child(conn: Connection, s: dict[str, str], parent: str, **extra: Any) -> str:
    child = _id("c")
    insert(
        conn, "tickets", ticket_id=child, parent_ticket_id=parent, requester_id=s["user"],
        requester_role="employee", redacted_request="ý con", **extra,
    )  # fmt: skip
    return child


def test_child_notice_effect_key_unique(rw: Engine, seeded: dict[str, str]) -> None:
    parent = seeded["ticket"]
    key = _sha("notify_user", parent)
    with rw.begin() as conn:
        child = _child(conn, seeded, parent)
        for _ in range(2):  # notify_user của con gọi 2 lần cùng khóa
            conn.execute(
                text(
                    "INSERT INTO child_notices (parent_ticket_id, child_ticket_id, source_step, "
                    "kind, needs, body, effect_key) VALUES (:p, :c, 'B18', 'result', 'confirm', "
                    "'Đã bật VPN', :k) ON CONFLICT (effect_key) DO NOTHING"
                ),
                {"p": parent, "c": child, "k": key},
            )
        n = conn.execute(text("SELECT count(*) FROM child_notices WHERE effect_key = :k"), {"k": key})
        assert n.scalar() == 1


def test_parent_closes_without_close_reason_and_is_excluded_from_rates(
    rw: Engine, seeded: dict[str, str]
) -> None:
    user = seeded["user"]
    with rw.begin() as conn:
        parent = _id("p")
        insert(
            conn, "tickets", ticket_id=parent, requester_id=user, requester_role="employee",
            redacted_request="hai ý", is_parent=True, final_state="S_ESCALATED",
            aggregate_status="PARTIALLY_ESCALATED",
        )  # fmt: skip  — close_reason = NULL qua được CHECK (P7 2.10)
        _child(conn, seeded, parent, final_state="S_ESCALATED", exit_code="E4")
        _child(conn, seeded, parent, final_state="S_RESOLVED", close_reason="resolved_user_confirmed")
        rate = conn.execute(
            text(
                "SELECT avg((final_state = 'S_ESCALATED')::int) FROM tickets "
                "WHERE is_parent = false AND (parent_ticket_id = :p OR ticket_id = :p)"
            ),
            {"p": parent},
        ).scalar()
    assert rate is not None and float(rate) == pytest.approx(0.5)  # tính cả cha sẽ ra 2/3


def test_ticket_close_reason_checked(rw: Engine, seeded: dict[str, str]) -> None:
    with pytest.raises(DBAPIError, match="ck_tickets_close_reason"), rw.begin() as conn:
        insert(
            conn, "tickets", ticket_id=_id("t"), requester_id=seeded["user"],
            requester_role="employee", redacted_request="x", close_reason="closed_by_magic",
        )  # fmt: skip


# ---- seed, transaction_log --------------------------------------------------------------------


def test_exit_code_priority_seeded(rw: Engine) -> None:
    with rw.connect() as conn:
        rank: dict[str, int] = dict(conn.execute(text("SELECT exit_code, rank FROM exit_code_priority")).all())
    assert set(rank) == {f"E{i}" for i in range(10)}
    assert rank["E7"] == 1 and rank["E9"] == rank["E2"]  # B20 4.1; E9 ngang E2 [Chốt]


def test_transaction_log_statuses(rw: Engine, seeded: dict[str, str]) -> None:
    with rw.begin() as conn:
        for status in ("begun", "undone", "undo_failed"):
            insert(
                conn, "transaction_log", ticket_id=seeded["ticket"], step_name="add_group",
                status=status,
            )  # fmt: skip
    with pytest.raises(DBAPIError, match="ck_transaction_log_status"), rw.begin() as conn:
        insert(
            conn, "transaction_log", ticket_id=seeded["ticket"], step_name="x",
            status="not_attempted",
        )  # fmt: skip
