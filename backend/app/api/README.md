Router mỏng: auth, tickets, approvals, overrides, escalations, policy, kb, dashboard, health, eval. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- 2b-3: `tickets.py` (tạo 202, đọc, trả lời, xác nhận), `approvals.py` (quyết định duyệt), `desk.py` (phụ thuộc chung, 503 khi runtime lỗi), `background.py` (task nền), `errors.py` (lỗi graph → HTTP), `limits.py` (413 trước mọi kiểm quyền). Thứ tự kiểm và lý do: docstring từng file.
