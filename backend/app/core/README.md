Tiện ích dùng chung (ids, clock, errors, hashing, logging) — KHÔNG phụ thuộc module nghiệp vụ. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- `turn_budget.py` (3f S0, phase3 9.0): hạn cho cả lượt — contextvar do `graph/runner` gắn (không vào checkpoint);
  `cap_timeout`, `check_sleep`, `window` dùng ở mọi lời gọi ra ngoài (tools, ml, llm, rag). Ở `core` vì các tầng đó không
  được import `graph`.
