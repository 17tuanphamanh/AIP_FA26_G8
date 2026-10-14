Node của graph, một file mỗi nhánh (b01_identity.py … b20_audit.py). Xem docs/spec/build/01-kien-truc-project.md mục 3.

- File ở đây là bản THẬT (b01, b02, b03, b06, b08, b10, b11, b12, b15, b17, b20, các node `*_wait`). Node có cả bản giả (gate2,
  `FAKE_SCENARIO`) để bản giả ở `graph/nodes/fake/` (b02, b03, b06, b08, b10, b11, b12, b15, b17, `clarify_wait`);
  `graph/builder.REAL_NODE_MODULES` liệt kê bản thật. B15 giả (người duyệt `FAKE_APPROVER_ID`, không xét xung đột) chỉ còn cho
  gate2 (Phase 4 4b P15).
- `b15_prepare_approval.py`: node THẬT (Phase 4 chặng 4b, phase4 5.1–5.2, 5.6) — chốt phòng thủ đích `device:` chưa xác minh chủ →
  E5 TRƯỚC mọi lời tra AD; `effects.peek("approval_create")` có (chạy lại) → dùng phiếu cũ, không chọn lại/tra AD; thiếu khoá HMAC
  → E2; `domain.approval.choose_approver` (roster `config/approvers.yaml`, AD bước `B15_APPROVER`, xung đột cả chuỗi quản lý) →
  `ensure` dòng `users` → `effects.once` tạo phiếu + báo `a.approver_id` → điểm log 5 (`audit_columns`, `intended_action`).
- `b12_assess.py`: node THẬT (Phase 3 chặng 3h, phase3 11.3) — `build_ctx` (chỉ `intended_action`, `requester_context`,
  `ctx_flags` + Clock) → `risk.policy_engine.evaluate` (R16–R20, `config/policy.json`): allow → B17, approval_required →
  B15, deny → E5; không luật nào → `deps.estimator` (Phase 6 6C: `LlmRiskEstimator`) → `risk.strategy.decide` (AUTO → B17 +
  `action_plan_hash`, HITL → B15, L2 → E5 `llm_high_risk`); lỗi estimator → E5 `llm_layer_disabled`. Điểm log 4 + `policy_sha256` +
  `lineage` qua `goto`.
- `b17_execute.py`: node THẬT (3h, phase3 11.4) — [0] ticket đã có `begun` (mọi lượt) → E7 `exec_interrupted` TRƯỚC mọi bước
  kiểm lại (NGHI-2); [1] luật + Clock hiện hành, "đã duyệt" = state + bảng `approvals` + hash;
  [2] hash; [3] `ad_get_user` (`B17_RECHECK`) cho người gửi + người hưởng lợi, trường `requester.*` luật dùng mà AD mới khác
  bản chụp B1 → E5 `recheck_failed` (Q-3h-7); Phase 4 4b P13: đi qua duyệt thì tra thêm người ĐÃ DUYỆT (`decided_by`) trong
  cùng lời gọi song song — lỗi AD → E2 `approver_lookup_error`, không còn hợp lệ l1 lẫn Trưởng BP → E5
  `approver_no_longer_valid`; [4–5] `deps.executor` (API: `PlanExecutor`,
  `transaction_log` `begun` trước mỗi lời gọi ghi; worker: `RefusingExecutor`) — `begun` có sẵn → E7 `exec_interrupted`,
  hết hạn lượt → E2, lỗi ghi → E7 `exec_failed` + ghi chú bàn giao 4 phần; [6] B18 tin `result` THEO MẪU + hạn confirm qua
  `effects.once` → `S_CONFIRMING`. Chốt FAIL mục 7 (3h DỪNG 3b): mọi lỗi (`Exception`) SAU `begin` — trong executor và ở
  đoạn B18 — → E7 `exec_interrupted` + câu "có thể đã gửi lệnh ghi…" (audit `cause` = tên lớp lỗi), KHÔNG E9; runner
  `recover_exhausted` trên ticket đã có `begun` (theo ticket) → E7 `execution_interrupted`. Việc treo 21: lỗi nổi lên
  boundary ở BẤT KỲ node nào (goto cuối B17, B19…) trên ticket đã có `begun` → E7 `execution_interrupted` + cùng câu
  (`graph/boundary.py`, `RunContext.txlog`).
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
  `rag.retriever.Retriever`), chỉ bắt `RetrievalSystemError` (E2); RAG không lỗi → LUÔN `b10_route` (Phase 4 S0-P1: B9
  chuyển vào `b10_route`, sau `b10_need_type`), điểm log 3 có `above_threshold`. Bản GIẢ (Phase
  2, đọc `deps.scenario`) nằm ở `graph/nodes/fake/b08_retrieve.py`. `graph/builder.py::select_nodes` (qua
  `FAKE_SCENARIO`) hoặc `real_nodes`/`fake_nodes` chọn bản nào chạy — xem `graph/wiring.py`.
- `b02_screen.py`: node THẬT (Phase 3 chặng 3e) — L2 regex (`guard.injection.match`) → L3 `deps.ml.classify`
  (`TAU_BLOCK`/`TAU_PASS`) → L4 LLM fast `b02_injection_judge` (không cache). Chặn → E0 `S_BLOCKED` +
  `security_events(injection_detected)` qua `effects.once("security_event")` (`detail` không chứa câu); L3 và L4 đều
  không trả lời → E2 `S_ESCALATED` + `security_flag`, `screening_unavailable` (không cho qua). Bản GIẢ (đọc
  `deps.scenario`, gate2 dùng) ở `graph/nodes/fake/b02_screen.py`.
- `confirm_wait.py` (node chung, không có bản giả): `note` qua `guard.screen_reply` (L0 + L2) NGAY sau `interrupt()` —
  khớp → E0 `S_ESCALATED` `injection_in_reply`. KHÔNG gửi tin nào (câu trả lời B10 gửi ở B10 — M-3g-2).
- `approval_wait.py` (B16 — node chung, không có bản giả; Phase 4 4c): `interrupt()` là lệnh đầu → che L1 ghi chú
  (`redact_text` thuần) → `approvals.close` (0/1, `decided_at` cả 3 nhánh) → đọc lại phiếu → từ chối: output guard trên ghi chú
  (chặn → bỏ câu ghi chú, `note_suppressed`) → tin THEO MẪU `kind=rejection` qua `effects.once("notify_user", step="B16")`.
  Điểm log 6 cả 3 nhánh: `approval_result` (state), `note` + `response_time_seconds` qua `audit_columns`, `detail` số/enum/bool.
  Hết hạn → E6, không bao giờ thực thi. Duyệt mà kế hoạch đã đổi (4d Q-4d-3, TC26): SAU `close(approved)`, TRƯỚC `S_EXECUTING`, so
  `hash_action(intended_action)` với hash state (phép so của cấm F3) rồi hash PHIẾU → lệch: E5 `action_plan_changed_since_approval` ở
  B16 (`hash_source` state|approval, `hash_old`, `hash_new`, đủ điểm 6); cấm F3 và hai lớp của B17 giữ làm lớp sau.
- `b10_route.py`: node THẬT (Phase 3 chặng 3g; Phase 4 S0) — `b10_need_type` (fast) TRƯỚC mọi kiểm ngưỡng: `action` → B11
  BẤT KỂ điểm (cờ `GROUNDING_GATE_ACTIONS=true` → B9 như 3h); `info` → B9 (rỗng/dưới ngưỡng → E3 `no_grounding`, step `B9`,
  event `no_evidence` — như nhánh cũ ở B8; 0 `expand`/`b10_answer`) → `expand_for_answer`
  trên `kb_version` đã ghim → `b10_answer` (strong) → gateway cắt khối → E3 `invalid_citation` (audit `evidence_truncated=true`); hậu kiểm bằng CODE
  (`domain.answer.check_citations`): `cannot_answer` → E3 `no_grounding`, trích ngoài anchor (top-5 ∩ khối thật sự gửi
  LLM, KHÔNG chunk liền kề) → E3 `invalid_citation` → `render_answer` theo mẫu → `guard.output` (E3
  `output_guard_block`, 0 tin) → `notify_user` + hạn confirm 48 h qua `effects.once` → `goto(lineage=…)` (cùng
  transaction audit) → `S_CONFIRMING`.
- `b11_slots.py`: node THẬT (3g, chỉ VPN) — đủ slot → `validate_targets` (tool có `device_id` trong `arg_slots`, LUÔN
  kiểm lại máy đích) → `infer_vpn` tính lại fact phụ thuộc máy, bỏ fact máy cũ, BỎ slot do `infer_vpn` trả →
  `build_action` → căn cứ quy trình (Phase 4 S0-P10): `procedure_doc` của `action_type` phải có trong KB HIỆN HÀNH (alias
  đọc lúc này), enabled, người gửi được xem (`deps.rag.procedure_available`) — không → E3 `no_procedure`, lỗi RAG → E2
  `rag_system_error`; thiếu → `b11_clarify_question` → output guard → `notify_user`/hạn clarify qua `effects.once` khoá
  riêng từng lượt hỏi (`sub=f"q{n}"`); hết `MAX_CLARIFICATION_TURNS` → E4. D-20 không có ở 3g (cờ bật → không khởi động).
- `clarify_wait.py`: node THẬT (3g) — `interrupt()` là lệnh đầu; `screen_reply` → timeout E4 → che L1 (`redact_text`
  thuần) → `b11_extract_slots` với bản đã che → `sanitize_slots(text=bản đã che, allowed=missing)` → lạc đề 2 lần E4.
  Chỉ bản đã che vào `conversation`/LLM; nhánh injection không lưu câu trả lời vào `conversation` (giá trị resume
  đã che vẫn nằm trong checkpoint — phase3 10.7 #13).
- Tin gửi người dùng: khuôn ở `domain/messages.py` (`answer`/`question`/`user`); chữ LLM gửi/lưu đều qua
  `guard.output.OutputGuard` (B10 body, B11 câu hỏi).
