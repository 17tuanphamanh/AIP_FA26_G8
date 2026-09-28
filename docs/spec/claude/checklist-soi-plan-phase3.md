# Checklist soi plan Phase 3 (Claude chat dùng khi review plan của agent)

*Lập 27/09/2026, đầu Phase 3. Nguồn: `huong-dan-xay-dung-he-thong-2.md` §5.1 (cổng 3), `build/decisions.md` §4, P2, P3, P4, B02, B08-B09, B10, `claude/rag-hien-trang-va-viec-sau-phase2.md`. Nhãn: [Chốt] = spec đã chốt; [Suy luận] = rút từ spec/bài học; [Đề xuất] = mới, cần chốt khi review.*

## 0. Hai điểm phải nắm trước khi soi

1. **Phạm vi Phase 3 rộng hơn "RAG + ml-service + B2–B9".** [Chốt §5.1] Phase 3 là **lát cắt VPN B1 → B20**; cổng 3 code gồm TC02 (R20 tự làm, gia hạn gọi đúng 1 lần), TC04/TC05 (B10 trả lời có trích dẫn), TC06 (0 câu hỏi lại nhờ chẩn đoán), TC16/TC28 (E3/E2), mọi luật VPN có test, M5 không nhận câu người dùng, hỏi lại ≤ 3 lượt × ≤ 2 slot → E4. Phần cần LLM thật (demo 4 ca, intent 18/20, biểu đồ ngưỡng) dồn về mốc G, trừ **một lần** chạy luồng VPN với model rẻ khi xong cổng code Phase 3 (decisions §4).
2. **Dữ liệu KB thật chưa có** (5 tài liệu VPN, `kb-facts.md`, 30 câu có đáp án + ≥ 20 câu không đáp án). Chặng nào cần dữ liệu thật thì chỉ làm **khung + fixture tổng hợp trong `tests/`**; không chọn ngưỡng trên fixture.

Việc treo đã đóng: "đọc trạng thái sau 202 bằng `after_event`" đã chốt ở `2b-4-QA`.

## 1. Chung — mọi chặng

| # | Soi gì | Đạt khi |
|---|---|---|
| A1 | Plan chia chặng có bảng phụ thuộc | Mỗi chặng ghi: phạm vi, TC cổng 3 phủ, có cần KB thật không, mức rủi ro, model đề xuất |
| A2 | Không đổi ngầm spec | Mọi lệch spec nêu thành Q; không tự đổi kiến trúc/tech stack |
| A3 | Test phân biệt đúng/sai | Dữ liệu test làm hai nhánh ra **khác** giá trị; test quét danh sách assert không rỗng (≥ số kỳ vọng) |
| A4 | Mutation nói trước | Mỗi đột biến: test nào đỏ, assert nào, giá trị bao nhiêu; phần SQL/Qdrant qua script Tuấn Anh chạy bằng `!` |
| A5 | Fail-closed | Thiếu cấu hình/model/alias/token → chặn hoặc E2, không âm thầm cho qua |
| A6 | Một nguồn sự thật | Ngưỡng ở `policy.json`; `kb_version` một hàm tính; role chỉ từ AD; đồng hồ từ `Clock` |
| A7 | Mọi lỗi mới có mã thoát | Lỗi đã lường trước → E0–E8 đúng bảng; còn lại để boundary → E9; không `except Exception` nuốt lỗi trong node |
| A8 | Bí mật | Không đọc/in `.env`; secret mới (vd `ML_SERVICE_TOKEN`) do Tuấn Anh tự thêm, agent chỉ ghi tên biến vào `.env.example` |
| A9 | CI không tải model lớn | Unit/integration dùng fake; test cần model thật đánh dấu riêng (probe/slow), không chạy trong CI |
| A10 | Import-linter | Hợp đồng mới cho `rag/`, `llm/`, `guard/` nếu cần; M5 (`risk/`) không import được thứ đọc `redacted_request` |

## 2. ml-service (P4, phần Phase 3)

| # | Soi gì | Đạt khi |
|---|---|---|
| M1 | Endpoint | `/embed`, `/rerank`, `/count_tokens`, `/health`; `/classify`, `/classify_intent` trả **503** khi thiếu thư mục model |
| M2 | Không cắt âm thầm | `/embed`, `/rerank` trả `truncated: list[bool]`; test văn bản ~600 token → `truncated=[true]` |
| M3 | 1 worker uvicorn | Suy luận trong threadpool + `Semaphore(ML_MAX_CONCURRENCY)`; không chặn event loop |
| M4 | Bảo mật | `X-Service-Token` sai/thiếu → 401 (so sánh hằng thời gian); body > 256 KB → 413; không bind cổng ra host ngoài dev; không log nội dung văn bản |
| M5 | Model ngoài git | `.gitignore` chặn `models/`; model nạp từ volume; khởi động không cần mạng; gitleaks/size không lọt file lớn |
| M6 | Compose + health | Service `ml-service` có healthcheck; chưa nạp xong → `/health` 503; backend `/api/health` báo ml-service |
| M7 | Client phía backend | Gọi qua `call_with_retry` (2 lần, 1s/2s); hết retry → `ExternalSystemError`; 4xx hợp đồng không retry |
| M8 | Fake cho test | `FakeMlService` tất định **và có ngữ nghĩa** (vd bag-of-words) để test truy hồi phân biệt được tài liệu đúng/sai — vector băm ngẫu nhiên = xanh oan |
| M9 | Tokenizer thật | Test "đếm token đúng tokenizer bge-m3" cần tokenizer thật (vài MB) — Q: cache trong CI hay chỉ chạy local |
| M10 | Việc đo | Plan liệt kê việc Tuấn Anh đo: RAM khi nạp 2 model, embed p95 < 300 ms, rerank 20 đoạn p95 < 2 s (Mac) |

## 3. Ingest + RAG (P3)

| # | Soi gì | Đạt khi |
|---|---|---|
| R1 | Front matter | Pydantic đủ trường (kể cả `distractor`); sai → dừng cả lượt, in file + dòng; đối chiếu `kb-facts.md` bằng regex |
| R2 | Chunk theo token (D-21) | 120–380 token nội dung, tổng ≤ 480 kèm tiền tố `title › heading_path`; đo bằng `/count_tokens`; vượt → ingest báo lỗi |
| R3 | BM25 | `pyvi` + lowercase + stopword; giữ `809`, `0x8004010F`; `mk → mật khẩu` áp cả ingest lẫn query; `mmh3 mod 2^31`; sparse `modifier: idf` |
| R4 | `kb_version` | sha256 của danh sách **đã sắp xếp** các cặp `(doc_id, version)` còn `enabled`; 2 lần cùng nội dung → cùng giá trị |
| R5 | Đổi alias an toàn | Collection mới → kiểm Recall@5 + tỉ lệ trả lời bừa (khi có bộ kiểm tra) → đổi alias nguyên tử → snapshot → ghi `kb_versions`; kiểm trượt → giữ alias cũ |
| R6 | Payload + index | Đủ trường P3 §4; index `request_type`, `sensitivity`, `enabled`, `doc_id` |
| R7 | Fixture ≠ KB thật | KB tổng hợp nằm trong `tests/fixtures`; `kb/` để nhóm soạn; có tài liệu MFA **cố ý thiếu** và một tài liệu `restricted` để test lọc |

## 4. B8–B9 (truy hồi, E2 ≠ E3)

| # | Soi gì | Đạt khi |
|---|---|---|
| E1 | E2 ≠ E3 (bất biến 6) | Exception sau retry / alias chưa có / ml-service chết → **E2**; rỗng hoặc điểm thấp → **E3**; test đỏ nếu đổi chéo |
| E2 | Ngưỡng trên điểm rerank | So `RETRIEVAL_THRESHOLD` (0,6, từ `policy.json`) với sigmoid của reranker, không với điểm RRF |
| E3 | D-23 | Chạy lại **một lần** không lọc intent, chỉ khi có intent và điểm < ngưỡng; giữ lọc `enabled` + `sensitivity`; không tính vào `tool_retry_count`; cờ `intent_filter_fallback` |
| E4 | Lọc theo role (FN an ninh) | employee không nhận `restricted` ở cả 3 chỗ: lần 1, lần chạy lại D-23, chunk liền kề D-24 (nếu D-24 làm ở chặng này) |
| E5 | Ranh giới bằng | Test có ca `top_score` đúng bằng ngưỡng (quy ước ≥ ngưỡng là có căn cứ) |
| E6 | Điểm log 3 | `query`, `top_score`, `doc_ids`, `retrieval_error`, `tool_retry_count`, `kb_version`, `intent_filter_fallback` — kể cả nhánh lỗi |
| E7 | State nhẹ | Chỉ `ChunkRef` (excerpt ≤ 600) vào state; key mới khai báo trong `TicketState` |
| E8 | E3 có `kb_gap_query` | Ghi vào escalation để Trưởng BP thấy lỗ hổng KB |
| E9 | Chọn ngưỡng (D-22) | Chỉ viết script quét 0,30…0,90 + biểu đồ hai đường; **không** đổi 0,6 cho tới khi có bộ 30 + ≥ 20 câu thật |

## 5. B2 — privacy guard + sàng lọc injection (an ninh → Opus)

| # | Soi gì | Đạt khi |
|---|---|---|
| G1 | Vị trí guard (D-07) | Guard thật thay `NotRedactingGuard` ở API **trước INSERT** cho cả tickets/messages/note duyệt; giữ thứ tự 2b-3 (413 → quyền → … → guard) |
| G2 | Không lưu câu gốc | Canary: grep toàn DB **kể cả bảng checkpoint** + log → 0 lần xuất hiện mật khẩu mẫu |
| G3 | Không log body trước guard | Middleware/log lỗi 422 không in body thô |
| G4 | Guard lỗi thì sao | Guard ném lỗi → từ chối request (fail-closed), không lưu bản chưa che |
| G5 | Giữ định danh slot | Username, mã thiết bị, đường dẫn thư mục không bị che; entropy không bắt nhầm mã thiết bị (có ca suýt khớp) |
| G6 | Bảng ánh xạ PII | Mã hóa AES-GCM, khóa từ secret riêng; hoặc Q hoãn sang Phase 5 có lý do |
| G7 | L0/L2 | Chuẩn hóa NFC, xóa zero-width, bản không dấu; regex 4 nhóm, mỗi mẫu có ca khớp + suýt khớp |
| G8 | L3/L4 | Phase 3 chưa có classifier → mọi câu không khớp regex xuống L4; L4 prompt riêng, **không cache**; L3 và L4 cùng lỗi → E2 + `security_flag`, không E0 |
| G9 | E0 | `security_events(injection_detected)` không chứa câu gốc; thông báo trung tính không chứa "injection/mẫu/phát hiện" |
| G10 | Dev guard | `NotRedactingGuard` còn dùng được trong test? Nếu giữ thì vẫn chỉ `APP_ENV ∈ {dev,test}` |

## 6. P2 gateway + ScriptedLLM

| # | Soi gì | Đạt khi |
|---|---|---|
| L1 | Prompt registry | YAML có `id`, `version`, `schema`; hash ghi `llm_calls`; test biến template khớp biến node truyền |
| L2 | Whitelist trường | `b14_risk_estimate` nhận `redacted_request`/`conversation` → lỗi khi render |
| L3 | ScriptedLLM có ca xấu | JSON sai 1 lần rồi đúng, thiếu trường, timeout, 429 → nhánh `LLMSchemaError`/`LLMUnavailable` được test |
| L4 | Ánh xạ lỗi | B2 → E2 + cờ an ninh; B3/B10/B11 → E2; B14 → **E5** (không tự làm khi không có p) |
| L5 | Cache | Bỏ qua cho `b02_injection_judge`, `b14_risk_estimate`; khóa cache có `kb_version` |
| L6 | Trace | Mỗi lời gọi (kể cả cache hit) 1 span + 1 dòng `llm_calls`; không ghi prompt đầy đủ |
| L7 | `spend_cap` | Vượt → `LLMBudgetExceeded` ánh xạ như `LLMUnavailable` |

## 7. Các nút còn lại của lát cắt VPN (soi khi tới chặng)

| # | Soi gì | Đạt khi |
|---|---|---|
| V1 | B3 (D-32) | Model chưa có → 503 → đường LLM; confidence thấp tách khỏi E1 thật (D-27) |
| V2 | B6–B7 | 404/rỗng là dữ liệu, không phải lỗi; LLM không tự chọn tool; lọc tool theo `arg_slots` (việc treo) |
| V3 | B10 | Hậu kiểm trích dẫn bằng code (rỗng/ngoài top-5 → E3); `notify_user` qua `effects.once`; D-24 ghép ±1 chunk |
| V4 | B11 | ≤ 2 slot/lượt, ≤ 3 lượt; lạc đề 2 lần hoặc quá 24 h → E4; không hỏi slot đã suy từ chẩn đoán |
| V5 | B12–B14 | M5 chỉ nhận `(action, ctx)`; luật khớp thì **không** gọi LLM (đếm lời gọi); mọi luật VPN có ca khớp + suýt khớp |
| V6 | B17 (Opus) | Thay `RefusingExecutor` cho gia hạn VPN; so hash; không retry lệnh ghi; TC02 gọi gia hạn **đúng 1 lần** kể cả khi recover |

## 8. Chọn model theo chặng

- ml-service, ingest khung, UI/seed/test theo mẫu → `opusplan` hoặc Sonnet.
- B8–B9 lọc theo role, B2 guard, B12–B14, B17 → **Opus**.
- Chuyển lên Opus ngay khi: mutation sống không giải thích được, plan sót nhiều mục trên, sửa qua lại > 2 vòng.
