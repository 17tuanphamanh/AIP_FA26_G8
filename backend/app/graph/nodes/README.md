Node của graph, một file mỗi nhánh (b01_identity.py … b20_audit.py). Xem docs/spec/build/01-kien-truc-project.md mục 3.

- Hầu hết các file ở đây (b01, b02, b03, b06, b10, b11, b12, b15, b17, b20, các node `*_wait`) đã là bản THẬT
  từ các phase trước — "giả" chỉ còn ở NHỮNG CHỖ chưa tới phase. Node có cả bản giả (gate2, `FAKE_SCENARIO`) để bản
  giả ở `graph/nodes/fake/` (b02, b03, b06, b08, b10, b11, `clarify_wait`); `graph/builder.REAL_NODE_MODULES` liệt
  kê bản thật.
- `b03_classify.py`: node THẬT (Phase 3 chặng 3f, chỉ VPN) — `deps.ml.classify_intent` (Phase 3 `model_missing`) → LLM
  fast `b03_classify` (prompt v2). Thứ tự kiểm cố định: ngoài phạm vi → ≥ 2 ý (đếm MỌI ý, câu xã giao không là ý) →
  confidence < `TAU_INTENT` → intent chưa bật (E1, `step="B4"`); lỗi LLM / hết hạn lượt → E2. Slot CHỈ qua
  `domain.slots.sanitize_slots` (bỏ key trùng fact, key lạ, > 100 ký tự, mã/lý do không có trong câu); `facts={}`.
  Điểm log 1 ở mọi nhánh, không câu người dùng, không giá trị slot, key lạ ghi `"<unknown>"`.
- `b06_diagnose.py`: node THẬT (Phase 3 chặng 3f, chỉ VPN) — 3 tool đọc song song (`tools/diagnosis/vpn.calls`), lỗi hệ
  thống → B7 E2 `tool_system_error` (`tool_errors` chỉ tên lớp lỗi), 404/rỗng = dữ liệu, hết hạn lượt → E2; `facts` CHỈ
  từ `tools/diagnosis/vpn.infer_vpn` (test AST `test_facts_ast.py`), slot suy ra không ghi đè slot người dùng,
  `diagnostics` lưu JSON. Cờ `ENABLE_PROACTIVE_DIAGNOSIS=false` → 0 lời gọi. Kiểm lại máy đích sau khi slot đổi: B11
  `validate_targets` (3g); D-20 chẩn đoán lại chưa làm.
- Hạn cho cả lượt (3f S0): node gọi ra ngoài chỉ qua `deps.directory` / `deps.ml` / `deps.llm` / `deps.rag` (đã cắt
  theo `core.turn_budget`). Hết hạn → E2 `turn_budget_exceeded` — boundary làm lưới chung; B2 (giữ `security_flag`),
  B3, B6 (giữ điểm log) bắt tường minh.
- `b08_retrieve.py`: node THẬT (Phase 3 chặng 3c) — gọi `deps.rag.retrieve()` (`RagPort`, thật là
  `rag.retriever.Retriever`), chỉ bắt `RetrievalSystemError` (E2); rỗng/dưới ngưỡng → E3 (B9). Bản GIẢ (Phase
  2, đọc `deps.scenario`) nằm ở `graph/nodes/fake/b08_retrieve.py`. `graph/builder.py::select_nodes` (qua
  `FAKE_SCENARIO`) hoặc `real_nodes`/`fake_nodes` chọn bản nào chạy — xem `graph/wiring.py`.
- `b02_screen.py`: node THẬT (Phase 3 chặng 3e) — L2 regex (`guard.injection.match`) → L3 `deps.ml.classify`
  (`TAU_BLOCK`/`TAU_PASS`) → L4 LLM fast `b02_injection_judge` (không cache). Chặn → E0 `S_BLOCKED` +
  `security_events(injection_detected)` qua `effects.once("security_event")` (`detail` không chứa câu); L3 và L4 đều
  không trả lời → E2 `S_ESCALATED` + `security_flag`, `screening_unavailable` (không cho qua). Bản GIẢ (đọc
  `deps.scenario`, gate2 dùng) ở `graph/nodes/fake/b02_screen.py`.
- `confirm_wait.py` (node chung, không có bản giả): `note` qua `guard.screen_reply` (L0 + L2) NGAY sau `interrupt()` —
  khớp → E0 `S_ESCALATED` `injection_in_reply`. KHÔNG gửi tin nào (câu trả lời B10 gửi ở B10 — M-3g-2).
- `b10_route.py`: node THẬT (Phase 3 chặng 3g) — `b10_need_type` (fast): `action` → B11; `info` → `expand_for_answer`
  trên `kb_version` đã ghim → `b10_answer` (strong) → gateway cắt khối → E3 `invalid_citation` (audit `evidence_truncated=true`); hậu kiểm bằng CODE
  (`domain.answer.check_citations`): `cannot_answer` → E3 `no_grounding`, trích ngoài anchor (top-5 ∩ khối thật sự gửi
  LLM, KHÔNG chunk liền kề) → E3 `invalid_citation` → `render_answer` theo mẫu → `guard.output` (E3
  `output_guard_block`, 0 tin) → `notify_user` + hạn confirm 48 h qua `effects.once` → `goto(lineage=…)` (cùng
  transaction audit) → `S_CONFIRMING`.
- `b11_slots.py`: node THẬT (3g, chỉ VPN) — đủ slot → `validate_targets` (tool có `device_id` trong `arg_slots`, LUÔN
  kiểm lại máy đích) → `infer_vpn` tính lại fact phụ thuộc máy, bỏ fact máy cũ, BỎ slot do `infer_vpn` trả →
  `build_action`; thiếu → `b11_clarify_question` → output guard → `notify_user`/hạn clarify qua `effects.once` khoá
  riêng từng lượt hỏi (`sub=f"q{n}"`); hết `MAX_CLARIFICATION_TURNS` → E4. D-20 không có ở 3g (cờ bật → không khởi động).
- `clarify_wait.py`: node THẬT (3g) — `interrupt()` là lệnh đầu; `screen_reply` → timeout E4 → che L1 (`redact_text`
  thuần) → `b11_extract_slots` với bản đã che → `sanitize_slots(text=bản đã che, allowed=missing)` → lạc đề 2 lần E4.
  Chỉ bản đã che vào `conversation`/LLM; nhánh injection không lưu câu trả lời vào `conversation` (giá trị resume
  đã che vẫn nằm trong checkpoint — phase3 10.7 #13).
- Tin gửi người dùng: khuôn ở `domain/messages.py` (`answer`/`question`/`user`); chữ LLM gửi/lưu đều qua
  `guard.output.OutputGuard` (B10 body, B11 câu hỏi).
