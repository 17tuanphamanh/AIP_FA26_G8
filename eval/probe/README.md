# Bộ câu probe (LLM thật — `make probe F=<file>`, không chạy trong `make test`)

- `cong5-v1.jsonl` — bộ đo cổng 5 (mốc G, 18/10/2026, commit `33b7484`). **Không sửa** — là bản đã đo.
- `cong5-v2.jsonl` — (ĐP chốt 09/11, bản demo lo-0811 — D-57, lô Q12) chép y nguyên v1, CHỈ đổi nhãn vàng 3 câu theo intent chỉ-trả-lời
  `it_help`: `I-OOS-01` (máy in kẹt giấy), `I-OOS-02` (hộp thư email đầy), `I-OOS-03` (Wi-Fi ở nhà chậm) — câu hỏi / báo hiện tượng IT chung
  mà KB `general` hướng dẫn được. `I-OOS-04` (xin cấp thêm màn hình), `I-OOS-05` (lịch nghỉ Tết) giữ `out_of_scope`. Câu nhiều ý (`M-03`,
  `M-09`…) giữ nhãn cũ: ở câu nhiều ý, ý `it_help` được B3 coi như `out_of_scope` (D-57).
  **Chưa chạy được với bộ chấm hiện tại:** `backend/tests/probe/cong5_score.py` `LABELS` chỉ có 5 lớp (macro-F1 5 lớp) → nhãn `it_help` bị từ
  chối. Thêm lớp thứ 6 đổi cách tính macro-F1 so với v1 — chờ ĐP chốt cách chấm. Chưa đo.
