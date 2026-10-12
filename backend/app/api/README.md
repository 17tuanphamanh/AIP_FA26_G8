Router mỏng: auth, tickets, approvals, overrides, escalations, policy, kb, dashboard, health, eval. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- 2b-3: `tickets.py` (tạo 202, đọc, trả lời, xác nhận), `approvals.py` (quyết định duyệt), `desk.py` (phụ thuộc chung, 503 khi runtime lỗi), `background.py` (task nền), `errors.py` (lỗi graph → HTTP), `limits.py` (413 trước mọi kiểm quyền). Thứ tự kiểm và lý do: docstring từng file.
- 4c: `approvals.py` thêm `GET /api/approvals?mine=1` (hộp thư) và `GET /api/approvals/{id}` (`ApprovalView` 12 khoá; không được xem → 404 cùng thân; hash lệch → 409 `plan_changed`). Route quyết đặt `decided_as` theo `approval_role`.
- 4d: `tickets.py` thêm `POST /api/tickets/{id}/override` (201; `decision:override` + đăng nhập ≤ 10 phút; ghi 1 dòng audit `OVERRIDE` qua `desk.approvals.record_override`, không đổi ticket; lần 2 cùng người → 409 `already_overridden`). Thứ tự kiểm: docstring module.
