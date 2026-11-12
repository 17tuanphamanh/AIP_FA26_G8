"""chi muc llm_calls(span_id), app_rw khong xoa duoc phieu duyet

E12 (soát 20 agent 12/11 — agent 20 V21, agent 14/15 V14; kế hoạch `claude/KE-HOACH-sua-het-12-11.md`). Test viết trước:
`unit/test_migration_0017_static.py`, `integration/test_migration_0017.py`.

- `ix_llm_calls_span_id` ON llm_calls(span_id): tab "So sánh 30 ngày" nối `llm_calls` với `spans` theo `span_id`; 10 000 ca mất 11,5 s khi
  quét tuần tự (agent 20). `llm_calls` mới có chỉ mục `created_at` (P9 mục 4).
- REVOKE DELETE ON approvals FROM app_rw: phiếu duyệt là bằng chứng AI đã duyệt hành động nào (P13). Code chỉ INSERT/UPDATE phiếu
  (B15 tạo, route/B16/worker đóng) — test canh `test_code_khong_xoa_phieu_duyet`. Không thêm trigger (UPDATE vẫn cần để đóng phiếu);
  owner `app_migrate` vẫn xoá được — đây là chặn lỡ tay của ứng dụng, không phải chống người có quyền chủ.

Downgrade: trả quyền DELETE như 0001, bỏ chỉ mục.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_llm_calls_span_id"


def upgrade() -> None:
    op.create_index(INDEX, "llm_calls", ["span_id"], unique=False)
    op.execute("REVOKE DELETE ON approvals FROM app_rw")


def downgrade() -> None:
    op.execute("GRANT DELETE ON approvals TO app_rw")
    op.drop_index(INDEX, table_name="llm_calls")
