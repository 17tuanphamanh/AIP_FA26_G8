Kiểu dữ liệu thuần, không I/O: 14 trạng thái, E0–E9, Action, TicketState, RequesterContext. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- `slots.py` / `facts.py` (3f, 3-Q1 — G-01): slot = tham số người dùng/LLM (qua `sanitize_slots`), fact = dữ kiện cho
  luật, CHỈ từ tool (`FACT_KEYS` đóng). `action.build_action` kiểm `facts` (`FactKeyViolation` → E9).
