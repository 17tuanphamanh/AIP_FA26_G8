# backend/app/db — 22 bảng, pool, migration

SQLAlchemy 2.0 (`models.py`), engine async với pool chính + lock pool (`session.py`, D-19), migration
Alembic (`alembic/`). Xem `docs/spec/build/01-kien-truc-project.md` mục 3 và
`docs/spec/build/nen-tang/P7-db-thay-doi.md`.

`schema.sql` gốc (17 bảng) không còn, nên 17 bảng gốc được **dựng lại từ tài liệu** rồi áp P7 lên
trên (Phase 1a, 25/09/2026). Bảng dưới ghi nguồn từng nhóm cột; **[ĐX]** là cột không có nguồn
(Đề xuất). Người đã duyệt, kèm các quyết định A1–A4 ghi trong `PROGRESS.md`.

**Ký hiệu nguồn:**

| Ký hiệu | Tài liệu |
|---|---|
| TK | `docs/spec/claude/thiet-ke-database.md` |
| N3-9.x | NGU-CANH Phần III mục 9.x |
| N4-9 | NGU-CANH Phần IV mục 9 (8 điểm log) |
| HD17.1 | `huong-dan` mục 17.1 |
| P/B | File tương ứng trong `docs/spec/build/` |

| Bảng | Cột → nguồn |
|---|---|
| `users` | `user_id`, P7 2.1 (DDL nguyên văn); `role` (P7 "giữ CHECK"); `department`, `is_privileged_account` (B01 `RequesterContext`); `username`, `full_name`, `created_at` [ĐX]. Không có cột mật khẩu. |
| `sessions` | `session_id`, `user_id` (HD17.1); cột và index của P7 2.2; `created_at` [ĐX] |
| `policy_versions` | `version_id`, `policy_json` (TK); `version`, `updated_by`, `updated_at` (N3-9.3); `is_current` (01 mục 5.3); UNIQUE một dòng `is_current` [ĐX] |
| `policy_rules` | PK (`rule_id`, `version_id`) (TK); `rule_type`, `intent`, `action`, `conditions`, `description` (N3-9.3) |
| `kb_versions` | toàn bộ theo P3 mục 8 |
| `kb_documents` | front matter P3 mục 4; PK (`doc_id`, `version`) và `kb_version` [ĐX] |
| `tickets` | 20 cột (TK, N3-9.1, N4-9 điểm 8, B03-B05 5.4, B19) + `is_parent` (P7 2.10) = 21. `redacted_request` thay `raw_request` (D-07, A1). Migration 0013 (D-60): `strategy` (chiến lược M5 chụp lúc tạo, NULL = ticket cũ), `source` (`real`/`sim`/`eval`) = 23 |
| `approvals` | B15 mục 8 + P7 2.6; CHECK "rejected phải có note" (TK); `created_at` [ĐX] |
| `transaction_log` | `step_name`, `status` {begun, undone, undo_failed}, `detail` (TK, N4 5.3, B17 mục 8 — A3); `log_id`, `turn_id`, `created_at` [ĐX] |
| `exit_code_priority` | seed đúng B20 4.1 (E7 = 1 … E1/E3/E4/E8 = 6, E9 ngang E2) |
| `escalations` | B20 mục 8, 4.2, 4.3; `reason_detail` (P7 2.11); `created_at` [ĐX] |
| `audit_logs` | `step`/`event`/`from_status`/`to_status` (P1 5.1); cột của 8 điểm log (N4-9); CHECK domain (TK); `raw_prob`, `p_method` (B12 mục 8 — điều chỉnh 2); cột ghi đè (B20 mục 8); `turn_id`, `loop_seq`, `kb_version`, `idempotency_key` (P7 2.7); `outcome` (N3-9.2); `detail` JSONB [ĐX] chứa `thresholds`, `all_matched`, `layer`, `model_probs` |
| `lineage` | HD17.1, B12 mục 8, P11 (`intent_model_version`, `guard_model_version`); khóa và `created_at` [ĐX] |
| `turns` | HD17.1, P1 mục 7 (`ended_at`); danh sách giá trị `event_type` [ĐX] |
| `spans` | HD17.1, P1 mục 9 (`status`); `parent_span_id`, `started_at` [ĐX] |
| `llm_calls` | HD17.1, P2 mục 11; `call_id`, `created_at` [ĐX] |
| `alerts` | P9 mục 6–7 (`rule_id`, `severity`, `value`, `status`, `acked_by`, UNIQUE (`rule_id`, `window_start`)); `acked_at`, `detail`, `created_at` [ĐX] |
| `security_events`, `llm_cache`, `wait_deadlines`, `side_effects`, `child_notices` | DDL nguyên văn P7 2.3–2.9 |
| `m5_strategy_changes` | Migration 0013 (D-60): lịch sử đổi chiến lược M5 lúc vận hành, CHỈ GHI THÊM (`app_rw` SELECT/INSERT + trigger `forbid_mutation`); hiện hành = dòng `id` lớn nhất, chưa có dòng → `hybrid` |

**Index thêm theo P9 mục 4 (điều chỉnh 3):** `audit_logs(step, created_at)`,
`escalations(closed_at, exit_code)`, `llm_calls(created_at)`.

**Role (P6 mục 6, A4):**
- `docker/postgres/init-roles.sh` chạy bằng superuser lúc khởi tạo volume. Script tạo `app_migrate`,
  `app_rw`, `app_monitor` với mật khẩu lấy từ env, và cho `app_migrate` làm owner schema.
- Alembic chạy bằng `app_migrate`. Downgrade không đụng role.
- Trigger `forbid_mutation` chặn UPDATE/DELETE trên `audit_logs` và `security_events` (0013: cả `m5_strategy_changes`). Thêm
  [ĐX]: chặn cả TRUNCATE.

**Checkpoint LangGraph** (`checkpointer.setup()`) làm ở Phase 2.

**Đổi schema:** sửa `models.py`, rồi `uv run alembic revision --autogenerate -m "…"` (chạy bằng
`app_migrate`), đọc lại file sinh ra, thêm grant cho bảng mới. Không sửa `0001` đã chạy.
`backend/tests/integration/test_migration.py::test_models_match_migration` sẽ đỏ nếu models và
migration lệch nhau.
