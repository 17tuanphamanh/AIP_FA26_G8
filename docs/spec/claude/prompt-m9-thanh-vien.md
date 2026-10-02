# Prompt tối ưu cho agent — M9 (Lưu Dương · Tạ Duy Anh)

*Tạo 29/09/2026. Đi kèm `claude/ke-hoach-m9-chia-viec.md` và `claude/ke-hoach-m9-monitor.md` (v1.1). File này chỉ chứa **prompt để dán** — nội dung kỹ thuật nằm ở hai file kia, prompt chỉ trỏ tới.*

---

## 0. Vì sao tối ưu như thế này

| Cách làm | Lý do | Tác dụng |
|---|---|---|
| **Luật bền để trong `CLAUDE.local.md`** (mỗi người một bản, không commit) | Claude Code tự nạp `CLAUDE.local.md` ở gốc repo vào **mọi** phiên. Luật (chủ file, chỉ-đọc, git, không `.env`…) không phải dán lại mỗi chặng | Prompt mỗi chặng ngắn còn ~1/3; không bao giờ quên luật khi mở phiên mới |
| **Prompt chặng chỉ nói việc của chặng**: mục tiêu, input/output, file, điểm phải kiểm trong code, điểm dừng | Agent đọc đúng mục cần đọc thay vì cả 3 tài liệu dài → ít tốn ngữ cảnh, ít "tự sáng tạo" | Plan sát issue, ít vòng sửa |
| **"Điểm phải xác nhận bằng grep"** trong từng prompt | Kế hoạch có chỗ ghi "agent xác nhận" (vd trường JSON audit B2). Bắt agent kiểm code **trước khi** viết plan | Chặn plan dựa trên giả định sai |
| **Mẫu plan cố định** (bảng) | Tuấn Anh + người review chéo đọc nhanh, so được giữa các chặng | Review ~10 phút |
| **Ba điểm dừng cứng**: sau plan · sau test xanh · sau push | Không để agent tự commit/merge; người làm kiểm từng mốc | Đúng quy trình repo, không mất kiểm soát |
| **Prompt tình huống** dựng sẵn (CI đỏ, xung đột rebase, review đòi sửa, đổi hợp đồng, nguồn pending) | Tình huống lặp lại; gõ tay dễ thiếu luật | Xử lý nhất quán giữa hai người |

**Model:** Opus cho mọi chặng (A2, A4, B3 dùng Sonnet được nếu hết hạn mức). Mỗi chặng **một phiên mới**; sửa theo review thì **cùng phiên**.

---

## 1. Cài một lần (mỗi người, trên máy mình)

Chạy ở thư mục gốc repo:

```bash
git config core.hooksPath .githooks
echo "CLAUDE.local.md" >> .git/info/exclude   # file luật riêng, git bỏ qua, không lọt vào commit
```

Rồi tạo `CLAUDE.local.md` ở gốc repo với nội dung **mục 2.1** (Dương) hoặc **mục 3.1** (Duy Anh). Kiểm: `git status` không hiện `CLAUDE.local.md`.

Mở `claude` ở gốc repo một lần, đồng ý *trust*.

---

## 2. Lưu Dương — luồng A

### 2.1. `CLAUDE.local.md` của Dương

```markdown
# Luật riêng — Lưu Dương, M9 luồng A (Dashboard & dữ liệu đọc)

Tôi là Lưu Dương. Nhánh: dev-luuduong (gốc origin/dev-tuananh). PR vào dev-tuananh; Tuấn Anh review cuối + merge; Tạ Duy Anh (luồng B) review chéo trước.

Tài liệu (đọc đúng mục prompt chặng chỉ định, không đọc lan man):
- docs/spec/claude/ke-hoach-m9-chia-viec.md — ai làm gì, chủ file (mục 2), hợp đồng hàm (mục 3), thẻ chặng A (mục 5)
- docs/spec/claude/ke-hoach-m9-monitor.md — ranh giới (2), luật (4), công thức chỉ số (5), Q-M9 (10)
- docs/spec/build/nen-tang/P9-monitor-M9.md — đặc tả gốc

Luật cứng:
1. Chỉ sửa file mà bảng mục 2 file chia việc ghi chủ là Dương, hoặc tạo file mới trong vùng của tôi. File của Duy Anh (rules.py, evaluator.py, drift.py, rules_data.py, worker.py phần M9) → không đụng.
2. Giữ ĐÚNG chữ ký hợp đồng mục 3 (monitor_engine, views, window, escalation_rate_weighted, b2_llm_rate, b3_llm_rate, is_pending). Muốn đổi → dừng, báo tôi (Duy Anh đang dựa vào).
3. Tôi là người DUY NHẤT viết migration M9: chỉ view/index/GRANT; down_revision = head của dev-tuananh; sau rebase `uv run alembic heads` phải = 1.
4. M9 chỉ đọc: truy vấn qua engine app_monitor; thiếu DSN → MonitorUnavailable/503; KHÔNG BAO GIỜ rơi về engines.main.
5. Mọi đếm ticket qua v_leaf (is_parent=false). Nguồn chưa có node ghi → null + tên trong `unavailable`; mẫu số 0 → None. Không trả 0 giả.
6. Không đọc/in .env. Không --no-verify. Không nới sandbox. Không sửa docs/spec/, PROGRESS.md, frontend/.
7. Lệnh cần Docker (make test, integration, mutation SQL): đưa tôi từng lệnh (cd về gốc repo), tôi chạy rồi dán kết quả.
8. Stage đích danh từng file; kiểm không có .env*, __pycache__, .pyc, settings.local.json, CLAUDE.local.md. Không commit/push khi tôi chưa bảo. Commit tiếng Việt không dấu, không dòng AI.
9. Không chắc code hiện tại ra sao → grep/đọc code trước, ghi "đã kiểm: file:dòng". Không đoán.
10. Mâu thuẫn giữa tài liệu và code, hoặc giữa hai tài liệu → dừng, ghi rõ, hỏi. Không tự chọn một bên.

Mẫu plan (luôn dùng):
## Plan <chặng> — input → output
| # | File | Tạo/Sửa | Chủ file | Làm gì |
## Điểm đã kiểm trong code (file:dòng)
## Test (tên test → kiểm điều gì; gồm ca ranh giới)
## Mutation dự kiến (đột biến → test đỏ → assert nào)
## Câu hỏi Q-M9-A<x>-<n> (kèm đề xuất + lý do)
## Rủi ro / chỗ đụng file người khác (nếu có)
```

### 2.2. Prompt mở phiên từng chặng

*Thay `<số>` bằng số issue. Dán vào phiên Claude Code mới, bật Plan Mode (Shift+Tab) trước khi gửi.*

**A0 — Nền chỉ-đọc**
```
Chặng A0, issue #<số> (gh issue view <số>). Đọc: file chia việc mục 2, 3, 5 (A0); kế hoạch chung mục 1, 4.1, 4.2.
Mục tiêu: engine app_monitor fail-closed + giao window.py, views.py, db.py đúng hợp đồng mục 3 để Duy Anh dùng. Đây là đường găng của cả M9 — giữ nhỏ.
Input: role app_monitor đã có (migration 0001, MONITOR_TABLES); PG_MONITOR_PASSWORD đã có ở service postgres. Output: settings.monitor_database_url, Engines.monitor, monitor/db.py, views.py, window.py, handler 503, .importlinter siết, compose + .env.example.
Trước khi lập plan, kiểm và ghi file:dòng: (1) Engines + create_engines ở db/session.py; (2) cách main.py gắn exception handler (install_graph_errors, install_request_errors); (3) hợp đồng monitor-read-only hiện tại trong .importlinter; (4) env của service backend/worker trong docker-compose.yml.
Bước 0: git fetch origin && git switch dev-luuduong && git reset --hard origin/dev-tuananh (đã có nhánh thì rebase); đưa tôi lệnh make test để lấy số mốc.
Lập plan theo mẫu trong CLAUDE.local.md. Test bắt buộc: thiếu DSN → 503 và không dùng engines.main; có DSN → current_user = app_monitor; window: 16:59:59Z/17:00:00Z khác ngày VN, week_start thứ Hai, bucket_start 5 phút; thêm thử import app.audit vào app.monitor → lint đỏ. Mutation: trả engines.main khi thiếu; day_start theo UTC; bỏ 1 dòng cấm import.
Chưa code tới khi tôi báo "Duyệt".
```

**A1 — View + chỉ số nghiệp vụ**
```
Chặng A1, issue #<số>. Đọc: file chia việc mục 3, 5 (A1); kế hoạch chung mục 4.3, 5.1, 5.3, 8.3; P9 §4.
Mục tiêu: migration 3 view + GRANT; queries/business.py 10 chỉ số; metrics.py (METRIC_SOURCES, is_pending); tests/integration/monitor_seed.py (Duy Anh dùng lại). escalation_rate_weighted ĐÚNG chữ ký hợp đồng (luật 1 của Duy Anh gọi nó).
Trước khi lập plan, kiểm và ghi file:dòng: (1) head Alembic hiện tại của dev-tuananh; (2) cột audit_logs của điểm log 4 (decided_by, policy_decision, risk_level, matched_rule_id, calibrated_prob) và giá trị step thật mà code ghi cho B12–B14 (nếu chưa có node ghi thì nói rõ); (3) 4 reason_detail E1 thật (out_of_scope, multi_intent_not_enabled, intent_low_confidence, intent_not_enabled — dùng nguyên văn, + other) cho e1_split; (4) chỉ mục tickets(created_at) WHERE is_parent=false đã có chưa; (5) route /api/escalations/queue hiện có — KHÔNG sửa.
Q-M9-1 (nhóm N3) và Q-M9-5 (own của L1): làm theo mặc định trong kế hoạch chung mục 10 trừ khi issue epic đã chốt khác — kiểm epic trước.
Plan theo mẫu. Test bắt buộc: câu 2 ý (1 cha + 2 con) → mọi đếm = 2; từng chỉ số tính tay; mẫu số 0 → None; app_monitor SELECT 3 view, INSERT bị từ chối; migration up/down/up; alembic heads = 1. Mutation: bỏ is_parent=false; đảo trọng số; nhóm sensitive nhận nhầm allow.
Chưa code tới khi tôi báo "Duyệt".
```

**A2 — Chỉ số AI/LLMOps**
```
Chặng A2, issue #<số>. Đọc: file chia việc mục 3, 5 (A2); kế hoạch chung mục 5.2, 5.3.
Mục tiêu: queries/ai.py 12 chỉ số; b2_llm_rate, b3_llm_rate ĐÚNG chữ ký hợp đồng (luật 12, 13 của Duy Anh gọi). b3_llm_rate + intent_model_version READY từ 3f: đếm điểm log 1 ở CẢ step B3 và B4 (ca E1 ghi ở B4), tử số detail.layer='llm'; Phase 3–4 giá trị ≈ 1,0 là đúng. multi_intent_* → pending. Khóa nguồn pending ở PENDING_SOURCES (tách khỏi METRIC_SOURCES): override_count, multi_intent, b3_cascade, tool_spans (luật của Duy Anh kiểm); approval_view đã hết pending (4c merge).
Trước khi lập plan, kiểm và ghi file:dòng: (1) nơi ghi span node (db/runtime.py) và span LLM + llm_calls (llm/store.py) — name, span_type, attributes thật; (2) đường JSON layer_decided trong audit B2 (graph/nodes/b02_screen.py, TicketState.screening); (3) intent_filter_fallback trong audit B8 (b08_retrieve.py); (4) mọi reason_detail đi E2 do LLM (vd llm_unavailable ở b10_route.py) → hằng một chỗ; (5) chuỗi nối llm_calls → spans → turns → tickets có đủ khóa không.
Plan theo mẫu. Test bắt buộc: p95 trên 20 span biết trước; ticket cha có llm_calls không bị tính; json_valid_first_try NULL không tính lỗi; mẫu số 0 → None; test quét khóa response ↔ METRIC_SOURCES hai chiều, assert số lượng ≥ kỳ vọng. Mutation: bỏ JOIN v_leaf; NULL bị đếm là lỗi.
Chưa code tới khi tôi báo "Duyệt".
```

**A3 — API dashboard + cảnh báo**
```
Chặng A3, issue #<số>. Đọc: file chia việc mục 5 (A3); kế hoạch chung mục 4.5, 5.1, 11; P9 §7.
Mục tiêu: GET /api/dashboard/business, GET /api/dashboard/ai, GET /api/alerts, POST /api/alerts/{id}/ack; audit.alerts.ack() (ghi bằng engine app_rw, M7 — không phải monitor); response_model cho cả 4 route; response dashboard có `unavailable`.
Trước khi lập plan, kiểm và ghi file:dòng: (1) cách route hiện có dùng Depends(require(...)) và thứ tự kiểm 403/404/409 (api/tickets.py, api/escalations.py); (2) quyền trong auth/permissions.py cho manager/l1/l2/employee; (3) Clock của app lấy ở đâu (acked_at phải dùng nó); (4) AlertWriter.raise_once để dựng dữ liệu test (không chờ luật của Duy Anh).
Plan theo mẫu. Test bắt buộc: manager 200 toàn bộ; L1 200 chỉ phần mình (2 L1 không thấy số nhau); L2 + nhân viên 403; ack 200 → lần 2 409 (acked_by giữ người đầu) → id lạ 404; L1 ack 403; from/to sai → 422; openapi.json có 4 schema. Mutation: bỏ lọc own; bỏ AND status='open'; ack dùng engine monitor.
Sau khi mở PR: soạn giúp tôi tin nhắn gửi TV3 kèm phần openapi.json của 4 route.
Chưa code tới khi tôi báo "Duyệt".
```

**A4 — Health + hiệu năng + nghiệm thu**
```
Chặng A4, issue #<số>. Đọc: file chia việc mục 5 (A4), 7.2; kế hoạch chung mục 7.1, 10 (Q-M9-7); P9 §5, §8. Đọc comment issue A4 xem Duy Anh có xin chỉ mục nào không.
Mục tiêu: /api/health thêm llm (KHÔNG gọi LLM thật; scripted / real:configured / real:missing_pricing / spend_cap_reached; chỉ báo, không đổi mã 200/503 — như kb) + cache 10 giây; test 10.000 ticket mỗi truy vấn dashboard < 2 giây; chỉ mục bổ sung trong migration M9 mới (gộp chỉ mục Duy Anh xin); bảng nghiệm thu P9 §8 trong PR.
Trước khi lập plan, kiểm và ghi file:dòng: (1) api/health.py + main._default_checks, cách kb chỉ báo mà không đổi mã; (2) llm/config.py, llm/spend.py — lấy trạng thái cấu hình/trần chi thế nào mà không gọi provider; (3) repo có marker pytest cho test chậm chưa (chưa có → hỏi tôi, không tự thêm).
Plan theo mẫu. Test bắt buộc: 2 lần gọi trong 10 giây → mỗi phụ thuộc kiểm 1 lần (đồng hồ tiêm, không sleep); llm không đổi mã HTTP ở cả 4 trạng thái; hiệu năng in thời gian từng truy vấn. Chậm → EXPLAIN ANALYZE trước, thêm chỉ mục sau, ghi lý do.
Chưa code tới khi tôi báo "Duyệt".
```

---

## 3. Tạ Duy Anh — luồng B

### 3.1. `CLAUDE.local.md` của Duy Anh

```markdown
# Luật riêng — Tạ Duy Anh, M9 luồng B (Cảnh báo)

Tôi là Tạ Duy Anh. Nhánh: dev-duyanh (gốc origin/dev-tuananh). PR vào dev-tuananh; Tuấn Anh review cuối + merge; Lưu Dương (luồng A) review chéo trước.

Tài liệu (đọc đúng mục prompt chặng chỉ định):
- docs/spec/claude/ke-hoach-m9-chia-viec.md — chủ file (mục 2), hợp đồng hàm (mục 3), thẻ chặng B + BẢNG NGUỒN ĐÃ KIỂM (mục 6)
- docs/spec/claude/ke-hoach-m9-monitor.md — luật (4.4), bảng 16 luật (6), Q-M9 (10)
- docs/spec/build/nen-tang/P9-monitor-M9.md — đặc tả gốc

Luật cứng:
1. Chỉ sửa file mà bảng mục 2 ghi chủ là Duy Anh (monitor/rules.py, evaluator.py, drift.py, queries/rules_data.py, worker.py phần M9, test test_monitor_rules_* / _evaluator_* / _drift_* / _jobs_*, tests/integration/monitor_rules_seed.py) hoặc file mới trong vùng của tôi. File của Dương → không đụng; cần đổi → soạn comment để tôi gửi Dương.
2. KHÔNG viết migration. Cần view/chỉ mục → soạn yêu cầu (bảng, cột, lý do, EXPLAIN) để tôi comment vào issue A4.
3. Dùng hàm luồng A ĐÚNG chữ ký hợp đồng mục 3 (monitor_engine, window.*, escalation_rate_weighted, b2_llm_rate, b3_llm_rate, is_pending). KHÔNG tự tính lại chỉ số của A (một nguồn sự thật). Hàm A chưa merge → luật nhận GIÁ TRỊ làm tham số, test unit không DB; nối gọi hàm sau.
4. Hàm luật THUẦN: (data, ctx: RuleContext) -> list[AlertDraft]; không I/O; không datetime.now() — chỉ ctx.now.
5. M9 chỉ đọc: rules_data đọc qua engine app_monitor. Ghi alerts CHỈ bằng audit.AlertWriter.raise_once, gọi từ worker — không bao giờ từ app.monitor.
6. Chống bỏ sót (FN trước): subject tường minh (SYSTEM_SUBJECT cho luật tổng hợp); window_start lấy từ DB, không phải giờ chạy luật; luật theo sự kiện lookback 24 giờ; 2 đối tượng cùng cửa sổ → 2 cảnh báo. Nghi ngờ giữa "báo thừa" và "có thể sót" → chọn báo thừa, ghi lý do.
7. Mọi đếm ticket qua V_LEAF. Nguồn pending → skipped_rules + log "nguồn chưa có", không báo, không đoán.
8. Một luật lỗi không được chặn luật khác (bắt lỗi theo từng luật, log tên luật, không log dữ liệu).
9. Không đọc/in .env. Không --no-verify. Không nới sandbox. Không sửa docs/spec/, PROGRESS.md, tools/, auth/, graph/.
10. Lệnh cần Docker: đưa tôi từng lệnh (cd về gốc repo), tôi chạy rồi dán kết quả.
11. Stage đích danh; kiểm không có .env*, __pycache__, .pyc, settings.local.json, CLAUDE.local.md. Không commit/push khi tôi chưa bảo. Commit tiếng Việt không dấu, không dòng AI.
12. Không chắc code hiện tại ra sao → grep/đọc code trước, ghi "đã kiểm: file:dòng". Mâu thuẫn tài liệu/code → dừng, hỏi.

Mẫu plan (luôn dùng):
## Plan <chặng> — input → output
| # | File | Tạo/Sửa | Chủ file | Làm gì |
## Điểm đã kiểm trong code (file:dòng)
## Bảng luật | rule_id | nguồn (bảng/cột/event) | subject | window_start | chu kỳ | ngưỡng
## Test (tên → kiểm gì; mỗi luật: vượt / không / bằng ngưỡng; luật theo đối tượng: 2 đối tượng → 2 draft)
## Mutation dự kiến (đột biến → test đỏ → assert nào)
## Câu hỏi Q-M9-B<x>-<n> (kèm đề xuất + lý do)
## Phụ thuộc luồng A (hàm nào, đã merge chưa)
```

### 3.2. Prompt mở phiên từng chặng

**B0 — Khung luật thuần** *(bắt đầu ngay ngày 1, song song A0)*
```
Chặng B0, issue #<số> (gh issue view <số>). Đọc: file chia việc mục 2, 3, 6 (B0); kế hoạch chung mục 3, 4.4.
Mục tiêu: monitor/rules.py (Every, RuleContext, @rule, REGISTRY, hourly_median, spike) + monitor/evaluator.py (evaluate → EvalResult(drafts, failed_rules, skipped_rules)) ĐÚNG chữ ký hợp đồng mục 3. Thuần Python, KHÔNG cần DB — nguồn dữ liệu là một giao diện (Protocol) mà B1 sẽ nối SQL.
Input: backend/app/domain/alerts.py (AlertDraft, SYSTEM_SUBJECT, bruteforce_alert) — đọc trước. Output: 2 module + test unit.
Trước khi lập plan, kiểm và ghi file:dòng: (1) AlertDraft và kiểu Severity; (2) Clock của app (core/clock.py) để RuleContext.now dùng đúng kiểu; (3) cách repo viết Protocol/port (graph/ports.py) để làm giống.
Bước 0: git fetch origin && git switch dev-duyanh && git reset --hard origin/dev-tuananh; đưa tôi lệnh make test lấy số mốc. Khi A0 merge: rebase và dùng window.py của Dương, không tự viết lại.
Plan theo mẫu. Test bắt buộc: trùng rule_id → lỗi lúc import; luật A ném lỗi → luật B vẫn ra draft, failed_rules == ["A"]; hourly_median 168 giờ có giờ trống = 0; spike: bằng ngưỡng không báo, hơn 1 báo, dưới tối thiểu 3 không báo; hàm luật không gọi datetime.now (test hoặc kiểm AST). Mutation: bắt lỗi ngoài vòng lặp; trung vị bỏ giờ trống; spike dùng >=.
Chưa code tới khi tôi báo "Duyệt".
```

**B1 — Luật theo sự kiện + job 60 giây**
```
Chặng B1, issue #<số>. Đọc: file chia việc mục 6 (B1 — bảng nguồn đã kiểm, đọc KỸ luật 3 và 9); kế hoạch chung mục 4.4, 6. Kiểm A0 và A1 đã merge (gh pr list --state merged --search M9-A), rồi rebase.
Mục tiêu: 7 luật 2, 3, 9, 10, 11, 15, 16; queries/rules_data.py phần sự kiện (engine monitor, lookback 24 giờ, V_LEAF); job monitor_rules_minute trong worker.py (60 s, max_instances=1, coalesce=True) → AlertWriter.raise_once; RuleContext dựng trong worker (cap_usd, warn_ratio đọc config/llm.yaml bằng loader của app.llm Ở WORKER, không ở monitor).
Trước khi lập plan, kiểm và ghi file:dòng: (1) worker.py schedule_jobs + cách Clock/engines được truyền vào job; (2) auth/service.py: account_locked(threshold) và lock_start = now ≠ security_events.occurred_at (hai lần gọi đồng hồ) — xác nhận lại; (3) refresh_reuse_detected: detail chỉ có revoked_sessions (không token_family_id); (4) permission_denied ghi user_id hay username_attempted ở những nơi nào (auth/deps.py, auth/service.py); (5) audit event injection_detected (step B2) và finalize_failed_permanent (graph/runner.py); (6) E7 có hai reason_detail: exec_interrupted (graph/nodes/b17_execute.py) và execution_interrupted (graph/runner.py, graph/boundary.py) — luật 16 đếm MỌI E7, window = created_at nhỏ nhất của audit_logs có exit_code='E7' của ticket (không lọc step); (7) nếu Phase 4a đã merge: username ma trong security_events thành "h:"+HMAC — luật 3/10 dùng đúng giá trị auth ghi, thêm test ca username ma.
Luật 3 = ĐỐI SOÁT: tra alerts (rule_id, subject = bruteforce_subject(...), |window_start − occurred_at| ≤ 60 s); có → bỏ qua; không → bruteforce_alert(..., lock_start=occurred_at, source="m9_reconcile"). KHÔNG dựng khóa từ occurred_at rồi trông vào ON CONFLICT.
Plan theo mẫu (có bảng luật). Test bắt buộc: mỗi luật có / không / ngoài 24 giờ; 2 đối tượng → 2 draft; job chạy 2 lần không trùng; luật 3: auth đã ghi (lệch vài ms) → không thêm, xóa dòng auth → tạo đúng 1; worker "chết" 1 giờ (FakeClock) vẫn bắt; một luật lỗi → luật khác vẫn ghi; thiếu engine monitor → job log 1 dòng, bỏ qua. Mutation: subject luật 10 = ""; window_start = ctx.now; lookback 60 s; luật 3 bỏ bước tra ±60 s.
Chưa code tới khi tôi báo "Duyệt".
```

**B2 — Luật tổng hợp + job giờ/ngày**
```
Chặng B2, issue #<số>. Đọc: file chia việc mục 6 (B2 — bảng nguồn đã kiểm); kế hoạch chung mục 6. Kiểm B1 đã merge; A2 đã merge chưa (quyết định làm luật 1, 12, 13 ngay hay sau), rồi rebase.
Mục tiêu: 8 luật 1, 4, 5, 6, 7, 12, 13, 14 + job monitor_rules_hourly, monitor_rules_daily (02:00 giờ VN = 19:00 UTC; scheduler chạy UTC). Làm 4, 5, 6, 7, 14 trước; 1, 12, 13 sau khi A2 merge.
Trước khi lập plan, kiểm và ghi file:dòng: (1) tools/registry.py::_span hiện chỉ ghi log, chưa ghi bảng spans → luật 5 viết trên hợp đồng dự kiến (span_type='tool', status='error', attributes.error='circuit_open'), để pending, KHÔNG sửa tools/; (2) luật 7: 4c đã merge (b457e6e) — kiểm audit B16 có detail.decided_without_view, decided_as, view_duration và approvals.reminder_2_at; (3) config/llm.yaml spend (cap_usd, warn_ratio); (4) chữ ký thật của escalation_rate_weighted, b2_llm_rate, b3_llm_rate, is_pending sau khi A merge — lệch hợp đồng mục 3 thì dừng, báo tôi.
Luật 1/12/13 GỌI hàm của A, không tự tính. Luật 7: nguồn audit B16; tính < 5 giây khi decided_without_view=true, hoặc view_duration < 5, hoặc (decided_as='primary' và approvals.reminder_2_at khác NULL — ca mơ hồ, tính để không bỏ sót); bỏ nhánh timeout; KHÔNG dùng first_viewed_at làm nguồn. Luật 13: nguồn có nhưng chưa có cascade (Phase 5) → is_pending("b3_cascade") → skipped_rules + log cascade_not_enabled (Q-M9-9).
Plan theo mẫu (có bảng luật). Test bắt buộc: mỗi luật vượt / không / bằng ngưỡng; luật 4/6: trung vị 0 và 2 ca → không báo; RANH GIỚI luật 1: vượt → policy_versions không đổi (so trước/sau), đúng 1 dòng alerts; luật 14: 79% không, 80% có, chạy lại cùng ngày không thêm; job ngày đăng ký 19:00 UTC. Mutation: luật 1 dùng raw; luật 7 bỏ nhánh mơ hồ; luật 14 window = hour_start.
Chưa code tới khi tôi báo "Duyệt".
```

**B3 — Drift PSI (Nên có)**
```
Chặng B3, issue #<số>. Đọc: file chia việc mục 6 (B3); kế hoạch chung mục 6 (luật 8). Kiểm B2 và A3 đã merge, rồi rebase.
Mục tiêu: monitor/drift.py (psi bằng numpy, bin rỗng dùng epsilon cố định có lý do); luật 8 drift (subject = tên phân bố, window = week_start); job tuần thứ Hai 02:00 giờ VN; khối drift trong GET /api/dashboard/business (chỉ :all) — file của Dương → làm PR RIÊNG, ghi rõ để Dương review.
Trước khi lập plan, kiểm và ghi file:dòng: (1) response_model hiện tại của dashboard business (thêm trường không được phá kiểu cũ của TV3); (2) nguồn từng phân bố (intent, confidence, điểm truy hồi cao nhất B8, tỉ lệ E3, escalation, ghi đè — cái nào pending).
Đề xuất cách chọn tuần mốc trong phần câu hỏi (Tuấn Anh chốt).
Plan theo mẫu. Test bắt buộc: PSI trên 2 phân bố tính tay khớp (≤ 1e-6); luật 8 vượt / không / bằng 0,2; 2 phân bố → 2 draft; schema dashboard cũ không vỡ.
Chưa code tới khi tôi báo "Duyệt".
```

---

## 4. Prompt dùng chung (cả hai người)

**Duyệt plan** *(sau khi Tuấn Anh trả lời "Duyệt" trong issue)*
```
Plan đã duyệt. Chốt từ issue: <dán nguyên văn các chốt/sửa>.
Làm theo thứ tự: code → make lint → unit (sandbox) → mutation logic (mỗi đột biến: nói trước test nào đỏ ở assert nào → chạy → hoàn nguyên; cuối cùng git diff chỉ còn thay đổi thật). Báo bảng kết quả mutation. Lệnh cần Docker (make test, integration, mutation SQL) đưa tôi từng lệnh. Chưa commit.
```

**Chuẩn bị PR** *(khi `make test` xanh)*
```
make test xanh: <dán dòng tổng kết>. Làm:
1. git fetch origin && git rebase origin/dev-tuananh — xung đột ở file không thuộc mình thì DỪNG, báo tôi.
2. uv run alembic heads (phải = 1) · make lint · unit.
3. git diff --stat origin/dev-tuananh... → đối chiếu bảng chủ file mục 2; có file lạ thì dừng.
4. Stage đích danh, kiểm stage, commit (tiếng Việt không dấu, không dòng AI), push nhánh của tôi.
5. Soạn mô tả PR theo mẫu 8.2 kế hoạch chung (Closes #<số>; input → output; file; test + số; mutation; câu hỏi đã chốt; Spec cần sửa; chưa làm) và tin nhắn ngắn nhờ <người kia> review chéo.
Rồi DỪNG.
```

**CI đỏ**
```
CI đỏ ở PR #<số>: <dán gh run view <id> --log-failed, phần lỗi>. Tìm nguyên nhân gốc (không sửa test cho xanh). Nói rõ: lỗi ở code mình, ở rebase, hay ở môi trường CI. Đề xuất sửa + test chứng minh, chờ tôi duyệt rồi mới sửa.
```

**Review yêu cầu sửa**
```
Review PR #<số> yêu cầu: <dán comment>. Với từng ý: đồng ý / không đồng ý + lý do (trích code/tài liệu). Sửa các ý đồng ý, chạy lại lint + unit (+ lệnh Docker đưa tôi), cập nhật mô tả PR mục "Đã sửa theo review". Chưa push.
```

**Xung đột khi rebase**
```
Rebase lên origin/dev-tuananh bị xung đột: <dán git status>. Với từng file: ai là chủ (bảng mục 2)? File của mình → giữ cả hai phía, giải thích từng khối. File của người khác hoặc của Tuấn Anh → KHÔNG tự sửa, git rebase --abort và soạn tin nhắn cho chủ file. Migration: nếu 2 head → chỉ sửa down_revision của migration M9 CHƯA merge.
```

**Hợp đồng mục 3 cần đổi**
```
Tôi (hoặc agent) thấy cần đổi hợp đồng mục 3: <hàm/kiểu>. Đừng đổi code. Soạn comment cho issue epic gồm: chữ ký cũ → mới, lý do, ảnh hưởng tới luồng kia (file/test nào phải sửa), phương án không đổi (nếu có). Tag người kia + Tuấn Anh. Chờ đồng ý.
```

**Nguồn dữ liệu mới có** *(Tuấn Anh báo trong epic: vd B3 LLM, điểm log 4, span tool)*
```
Tuấn Anh báo nguồn mới: <tên nguồn, commit>. Kiểm và ghi file:dòng: event/cột/trường thật mà code ghi. Lập plan chặng nhỏ "nối nguồn <tên>": bỏ pending ở METRIC_SOURCES (Dương) hoặc bỏ skipped ở luật (Duy Anh), test trên dữ liệu thật của node (không chỉ fixture). Chưa code tới khi tôi báo "Duyệt".
```

**Review chéo PR của người kia**
```
Review chéo PR #<số> của <người kia> (chỉ đọc, không sửa, không checkout đè nhánh mình: dùng gh pr diff <số>). Soi theo checklist mục 9 kế hoạch chung + mục 7.1 file chia việc, thêm: chữ ký hợp đồng mục 3 có giữ nguyên không; có file ngoài vùng chủ không; đếm ticket có qua v_leaf; engine monitor; subject/window_start (nếu là luật). Kết luận: "Peer OK" hoặc danh sách điểm cần sửa (file:dòng + lý do). Soạn comment để tôi dán vào PR.
```

---

## 5. Nhật ký thay đổi

| Ngày | Thay đổi |
|---|---|
| 01/10/2026 | Nhánh `dev-luuduong` / `dev-duyanh` (thay `m9-*`); giao bằng PR vào `dev-tuananh` |
| 30/09/2026 | Cập nhật theo Phase 3 đóng (`5d0a990`): A2 `b3_llm_rate` ready + danh sách khóa pending; B1 E7 hai reason_detail + HMAC 4a; B2 luật 7 chờ 4c, luật 13 skipped tới Phase 5 (Q-M9-9) |
| 29/09/2026 | Tạo file: `CLAUDE.local.md` riêng cho Dương và Duy Anh (luật bền, mẫu plan), prompt mở phiên A0–A4, B0–B3 có "điểm phải xác nhận bằng grep", 8 prompt tình huống dùng chung |
