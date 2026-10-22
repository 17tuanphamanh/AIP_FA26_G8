"""monitor: view child_notices chi doc cua M9 (F12) + GRANT cot app_monitor

Chỉ số câu nhiều ý `multi_intent_first_stop_to_reply_s` (P9 §5.2, D-31; F12 #45) đọc hộp thư con `child_notices` (P7 2.9):
con dừng → notice (`created_at`), cha gửi tin → đánh dấu vòng (`delivered_round`, `delivered_at`).
- `child_notices` không thuộc 9 bảng `MONITOR_TABLES` của 0001 → GRANT THEO CỘT (quy ước 0008), đúng 6 cột chỉ số cần
  (`NOTICE_COLUMNS`). KHÔNG `body` (nội dung tin, đã qua privacy guard nhưng M9 không cần), không `effect_key`, `kind`,
  `needs`, `source_step`.
- `v_child_notices` (`security_invoker = true`, như 0008): chạy theo quyền của NGƯỜI ĐỌC → rào cột ở trên áp tới bảng.
  Chỉ notice của con là LÁ (`JOIN v_leaf`, D-30) — cùng kiểu `v_decisions` của 0008.
- Cột liệt kê tường minh ở `NOTICE_COLUMNS` (chỗ duy nhất), không `SELECT *`; SQL viết tĩnh, không import code
  (`views.V_CHILD_NOTICES` trùng tên — test đối chiếu). Không thêm chỉ mục (`ix_child_notices_pending` có từ 0001).

Revision ID: 0011
Revises: 0009
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0009"  # TODO(F12): khi gộp: đổi sang revision 0010 của 2b
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEW_NAME = "v_child_notices"
NOTICE_COLUMNS: tuple[str, ...] = (
    "notice_id", "parent_ticket_id", "child_ticket_id", "created_at", "delivered_round", "delivered_at",
)  # fmt: skip
MONITOR_ROLE = "app_monitor"


def _cols(alias: str, columns: tuple[str, ...]) -> str:
    return ", ".join(f"{alias}.{c}" for c in columns)


VIEW_SQL = f"SELECT {_cols('n', NOTICE_COLUMNS)} FROM child_notices n JOIN v_leaf c ON c.ticket_id = n.child_ticket_id"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ({', '.join(NOTICE_COLUMNS)}) ON child_notices TO {MONITOR_ROLE}")
    op.execute(f"CREATE VIEW {VIEW_NAME} WITH (security_invoker = true) AS {VIEW_SQL}")
    op.execute(f"GRANT SELECT ON {VIEW_NAME} TO {MONITOR_ROLE}")


def downgrade() -> None:
    # GRANT trên view mất theo view; GRANT cột trên bảng phải REVOKE để quyền về đúng như 0009.
    op.execute(f"REVOKE SELECT ({', '.join(NOTICE_COLUMNS)}) ON child_notices FROM {MONITOR_ROLE}")
    op.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
