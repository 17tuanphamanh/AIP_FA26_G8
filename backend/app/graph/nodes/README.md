Node của graph, một file mỗi nhánh (b01_identity.py … b20_audit.py). Xem docs/spec/build/01-kien-truc-project.md mục 3.

- Hầu hết các file ở đây (b01, b02, b03, b06, b10, b11, b12, b15, b17, b20, các node `*_wait`) đã là bản THẬT
  từ các phase trước — "giả" chỉ còn ở NHỮNG CHỖ chưa tới phase (vd `b03_classify`/`b06_diagnose` hiện còn
  Phase 2a: cố định `intent="vpn"`, không đọc câu — sẽ thay ở Phase 5).
- `b08_retrieve.py`: node THẬT (Phase 3 chặng 3c) — gọi `deps.rag.retrieve()` (`RagPort`, thật là
  `rag.retriever.Retriever`), chỉ bắt `RetrievalSystemError` (E2); rỗng/dưới ngưỡng → E3 (B9). Bản GIẢ (Phase
  2, đọc `deps.scenario`) nằm ở `graph/nodes/fake/b08_retrieve.py`. `graph/builder.py::select_nodes` (qua
  `FAKE_SCENARIO`) hoặc `real_nodes`/`fake_nodes` chọn bản nào chạy — xem `graph/wiring.py`.
- `b02_screen.py`: node THẬT (Phase 3 chặng 3e) — L2 regex (`guard.injection.match`) → L3 `deps.ml.classify`
  (`TAU_BLOCK`/`TAU_PASS`) → L4 LLM fast `b02_injection_judge` (không cache). Chặn → E0 `S_BLOCKED` +
  `security_events(injection_detected)` qua `effects.once("security_event")` (`detail` không chứa câu); L3 và L4 đều
  không trả lời → E2 `S_ESCALATED` + `security_flag`, `screening_unavailable` (không cho qua). Bản GIẢ (đọc
  `deps.scenario`, gate2 dùng) ở `graph/nodes/fake/b02_screen.py`.
- `clarify_wait.py` / `confirm_wait.py` (node chung, không có bản giả): câu trả lời / `note` qua `guard.screen_reply`
  (L0 + L2) NGAY sau `interrupt()` — khớp → E0 `S_ESCALATED` `injection_in_reply`, tin không vào `conversation`.
