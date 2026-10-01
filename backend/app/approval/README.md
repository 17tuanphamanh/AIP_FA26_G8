M6 — chọn người duyệt, xung đột lợi ích, SLA. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- `store.py` (2b-Q3): `SqlApprovals` — `create` (trong transaction của `effects.once`), `close` (B16, chỉ từ `pending`), `lock_row` (route duyệt, `FOR UPDATE` ngắn), `get`. Bấm muộn KHÔNG đổi `status` (2b-3 Q2). Chọn người duyệt thật: `domain/approval.py` + B15 (4b). `close` trả số dòng đổi (4c). `notify_approver(kind)` + `log_approver_notice` — MỘT hàm log cho B15 và worker nhắc 50 %/80 % (4c; Phase 4 chỉ log, hộp thư = API). Truy vấn nhắc nằm ở `db/runtime.SqlDeadlineStore` (Q-4c-2 = A).
