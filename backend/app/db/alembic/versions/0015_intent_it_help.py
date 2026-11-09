"""tickets, audit_logs: CHECK intent nhan them it_help

D-76 (ĐP chốt 09/11, bản demo lo-0811 — lô Q12): intent chỉ-trả-lời `it_help` (câu hỏi IT chung trả lời từ KB `general`). B20 ghi
`tickets.intent`, `goto` ghi `audit_logs.intent` từ state → hai CHECK này phải nhận giá trị mới. `policy_rules` GIỮ 4 loại (không có luật cho
it_help). Danh sách viết tĩnh — migration không đổi theo models (khuôn 0002/0007).

Downgrade dừng nếu đã có dòng `it_help`: `audit_logs` append-only (trigger chặn DELETE) nên không xoá được để siết CHECK lại — giữ DB ở 0015
hoặc dựng lại DB trống. (Số 0015 trước đây dự định cho bn-a/Q7 — nay dời sang 0016.)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("tickets", "audit_logs")  # ck_tickets_intent, ck_audit_logs_intent — KHÔNG policy_rules
OLD_INTENTS = ("account", "vpn", "software", "access")
NEW_INTENTS = ("it_help",)


def _check(values: Sequence[str]) -> str:
    return "intent IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _replace_checks(values: Sequence[str]) -> None:
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_intent"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_intent"), table, _check(values))


def upgrade() -> None:
    _replace_checks((*OLD_INTENTS, *NEW_INTENTS))


def downgrade() -> None:
    placeholders = ", ".join(f"'{v}'" for v in NEW_INTENTS)
    for table in TABLES:
        count: int = op.get_bind().execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE intent IN ({placeholders})")
        ).scalar_one()
        if count:
            raise RuntimeError(
                f"Không hạ được migration 0015: {table} đã có {count} dòng intent {'/'.join(NEW_INTENTS)}. "
                "audit_logs append-only nên không xoá được — giữ DB ở 0015, hoặc dựng lại DB trống."
            )
    _replace_checks(OLD_INTENTS)
