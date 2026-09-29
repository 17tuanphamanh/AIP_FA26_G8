P5 — tool registry, call_with_retry, breaker, adapters. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- Hạn cho cả lượt (phase3 9.0, 3f S0): `registry.call` kiểm lượt đã hết hạn TRƯỚC breaker; tool đọc: timeout mỗi lần thử =
  `core.turn_budget.cap_timeout`, backoff của `retry.call_with_retry` không vượt phần còn lại (`check_sleep`); tool ghi:
  còn không đủ TRỌN `timeout_s` → không gửi. Bỏ giữa chừng vì hết hạn → `breaker.record_abandoned` (không tính lỗi).
- `retry.retries_of` (Q-3f-1): đổi `attempts` (số lần thử THẤT BẠI) ra số lần THỬ LẠI cho `tool_retry_count`.
- `diagnosis/vpn.py` (3f): 3 lời gọi chẩn đoán VPN + `infer_vpn` — hàm thuần, `facts` chỉ từ dữ liệu tool.
