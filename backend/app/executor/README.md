B17 — Executor, TransactionLog; điểm ghi duy nhất ra hệ thống ngoài. Xem docs/spec/build/01-kien-truc-project.md mục 3.

Phase 3 chặng 3h (phase3 11.4):
- `plans.py` — `PLAN[action_type]` (chỉ metadata, không import adapter ghi) + `check_plans` (khởi động, h23).
- `txlog.py` — `transaction_log`: `begun` commit riêng TRƯỚC lời gọi ghi; `undone`/`undo_failed`; `has_begun(ticket_id)` theo
  ticket, MỌI lượt (B17 bước 0 + lớp thứ hai trong executor — chốt DỪNG 2, NGHI-2; boundary và runner cạn lượt — Việc treo
  21). `MAY_HAVE_WRITTEN` — câu cảnh báo L2 dùng chung cho mọi đường E7 sau `begun` (một nguồn, không chép chữ).
- `plan_executor.py` — `PlanExecutor` (T24: đổi tên từ `vpn.py`/`VpnExecutor`): P4 (đủ trọn timeout ghi trước `begun`), gọi 1 lần (retries=0), hoàn tác nếu `reversible`,
  ghi chú bàn giao 4 phần chỉ từ mã lỗi tập đóng + định danh (P6; lỗi mơ hồ timeout/5xx → "có thể đã được áp dụng"). Mọi
  `Exception` SAU `begin` → `ExecutionInterrupted(cause=<tên lớp>, write_calls=<cận trên>)` (chốt FAIL mục 7, 3h DỪNG 3b);
  trước `begun` → nổi nguyên (E9); `BaseException` (`CancelledError`) không bắt.
- `wiring.py` — registry GHI (token `svc_executor`); CHỈ `app.main` (API process) import (P7, import-linter hợp đồng 3).
- `errors.py` — `ExecutionInterrupted` (E7 `exec_interrupted`; `cause`, `write_calls`).
