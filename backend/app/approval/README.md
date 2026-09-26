M6 — chọn người duyệt, xung đột lợi ích, SLA. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- `store.py` (2b-Q3): `SqlApprovals` — `create` (trong transaction của `effects.once`), `close` (B16, chỉ từ `pending`), `lock_row` (route duyệt, `FOR UPDATE` ngắn), `get`. Bấm muộn KHÔNG đổi `status` (2b-3 Q2). Chọn người duyệt thật + thông báo: Phase 4.
