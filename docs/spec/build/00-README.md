# Bộ tài liệu xây dựng hệ thống (build docs) — AI Agent IT Service Desk L1 + HITL

*Phiên bản 1.2 — 25/09/2026. Bổ sung cho `huong-dan-xay-dung-he-thong-2.md`, `NGU-CANH-DAY-DU.md`, `claude/thiet-ke-database.md`, `claude/so-do-kien-truc-he-thong.md`. Không thay thế các tài liệu đó; khi mâu thuẫn, tài liệu gốc thắng trừ các quyết định D-xx liệt kê ở mục 4 (đã được đưa vào bản build này và cần nhóm xác nhận).*

*Bản 1.2 thêm các quyết định D-17…D-28 sửa 12 lỗi phát hiện khi rà soát lõi AI (LangGraph runtime, RAG, thành phần). Báo cáo đầy đủ: `claude/bo-sung-bo-tai-lieu-build.md`.*

---

## 1. Bộ tài liệu này dùng để làm gì

Ba tài liệu gốc trả lời **xây cái gì và vì sao**. Bộ này trả lời **xây như thế nào**: mỗi nhánh (branch) của workflow B1–B20, mỗi tầng kiến trúc và mỗi thành phần nền tảng có một tài liệu riêng ghi rõ: sơ đồ cấu tạo, công nghệ, hợp đồng dữ liệu, mã giả, lý do thiết kế, cấu hình, bảng DB, trace, ca lỗi, kiểm thử và tiêu chí đạt.

Người đọc chính: thành viên nhóm và coding agent. Mỗi file tự đứng được — có thể giao nguyên một file cho coding agent làm một task.

## 2. Mục lục

| # | File | Nội dung | Đọc khi |
|---|---|---|---|
| 0 | `build/00-README.md` | File này: mục lục, quy ước, quyết định mới | Đầu tiên |
| 1 | `build/01-kien-truc-project.md` | Kiểu kiến trúc (modular monolith), sơ đồ process, cây thư mục, quy tắc phụ thuộc, cấu hình, CI/CD | Trước khi tạo repo (T01) |
| 2 | `build/02-cac-tang-he-thong.md` | 8 tầng (T0–T7): chức năng, thành phần, giao diện, điều cấm, yêu cầu chức năng/phi chức năng, tiêu chí đạt | Trước khi code bất kỳ module nào |
| 3 | `build/nen-tang/P1-langgraph-runtime.md` | State, build graph, routing, interrupt, runner, khóa, ticket con, E9, side effect idempotent, constrained agent | Phase 2 |
| 4 | `build/nen-tang/P2-llm-gateway.md` | LLMClient: API/local, router, structured output, cache, retry, trace | Phase 3 |
| 5 | `build/nen-tang/P3-rag-pipeline.md` | Ingest + truy vấn hybrid, Qdrant, bge-m3, BM25 tiếng Việt, rerank, chunk theo token, câu âm tính, ablation | Phase 3–5 |
| 6 | `build/nen-tang/P4-ml-service.md` | Service phục vụ embedding / rerank / injection classifier | Phase 3 |
| 7 | `build/nen-tang/P5-tool-registry-mock.md` | Tool registry, `call_with_retry`, circuit breaker, adapter, mock hệ thống ngoài | Phase 1 |
| 8 | `build/nen-tang/P6-auth-bao-mat.md` | AuthN/AuthZ, RBAC + kiểm tra theo bản ghi, service identity, bảo vệ tầng DB | Phase 1–2, 4, 7 |
| 9 | `build/nen-tang/P7-db-thay-doi.md` | Thay đổi so với 17 bảng đã thiết kế (→ 22 bảng: + security_events, llm_cache, wait_deadlines, side_effects, child_notices), role Postgres | Phase 1 |
| 10 | `build/nen-tang/P8-danh-gia-M8.md` | M8: harness, schema kịch bản, chia tập theo họ, hiệu chỉnh chỉ trên calibration, công thức chỉ số, ma trận chạy RQ1/RQ3 | Phase 8–10 |
| 11 | `build/nen-tang/P9-monitor-M9.md` | M9: ranh giới chỉ đọc, view SQL, 12 luật cảnh báo, API dashboard | Phase 1, 4, 7 |
| 12 | `build/nen-tang/P10-giao-dien.md` | Giao diện 4 vai trò, API, tin tổng hợp (D-31), bảo mật phía giao diện, cổng 7 | Phase 4, 7 |
| 13a | `build/nen-tang/P11-huan-luyen-model.md` | Huấn luyện 2 model phân loại (intent đa nhãn, injection): chọn backbone, dữ liệu, chống rò rỉ, ngưỡng, ONNX, đánh giá | Song song từ Phase 1; tích hợp Phase 3–5 |
| 13 | `build/decisions.md` | Danh sách duy nhất: D-01…D-33, việc nhóm tự chốt (N1–N5, bảng R01–R20, ngân sách LLM), quyết định Q1–Q14, thứ tự chốt | Phase 0 và trước mỗi buổi họp |
| 14–25 | `build/nhanh/B01…B20-*.md` | 12 tài liệu nhánh, mỗi file theo cùng khuôn 16 mục | Khi làm nhánh đó |

Danh sách 12 file nhánh:

| File | Nhánh | Module | Phase |
|---|---|---|---|
| `B01-xac-thuc.md` | B1 | Bảo mật / M4 | 1–2 |
| `B02-sang-loc-injection.md` | B2 (+ privacy guard) | Bảo mật / M1 | 5 (khung từ 3) |
| `B03-B05-phan-loai-tach-y.md` | B3, B4, B5 | M1 | 3, 5 |
| `B06-B07-chan-doan.md` | B6, B7 | M3 | 1, 3 |
| `B08-B09-tra-cuu.md` | B8, B9 | M2 | 3, 5 |
| `B10-tra-loi-deflection.md` | B10 | M2 + M1 | 3 |
| `B11-bo-sung-thong-tin.md` | B11 | M1 + M4 | 3 |
| `B12-B14-danh-gia-rui-ro.md` | B12, B13, B14 | M5 | 3, 5, 6 |
| `B15-B16-phe-duyet.md` | B15, B16 | M6 | 4 |
| `B17-B18-thuc-thi.md` | B17, B18 | Điểm ghi duy nhất | 3, 5 |
| `B19-xac-nhan.md` | B19 | M4 | 3 |
| `B20-audit-escalate-L2.md` | B20, E0–E9, L2, ghi đè | M7 | 2, 4, 7 |

## 3. Quy ước

**Nhãn nguồn** (giữ đúng quy ước của project):

- **[Chốt]** — lấy từ tài liệu gốc hoặc đã được nhóm chốt.
- **[Suy luận]** — rút ra từ nhiều đoạn tài liệu gốc, chưa có câu viết tường minh.
- **[Đề xuất]** — ý mới của bộ tài liệu này. Đã được đưa vào bản build (mục 4), cần nhóm xác nhận, báo GVHD nếu ảnh hưởng thiết kế.

**Mỗi file nhánh tự đứng được (khuôn 16 mục, từ mục 0 đến mục 15):**

0. **Ngữ cảnh nạp sẵn:**
   - 0.1 Khối ngữ cảnh chung (CTX, giống hệt nhau ở mọi file).
   - 0.2 Vị trí của nhánh trong luồng: nhận gì từ nhánh trước, giao gì cho nhánh sau, bảng chuyển trạng thái.
   - 0.3 Đặc tả gốc đã chốt, trích từ `NGU-CANH-DAY-DU.md` và `NGU-CANH-DAY-DU.md` Phần IV.
   - 0.4 Kịch bản kiểm thử liên quan.
   - 0.5 Bất biến riêng và mã quyết định.
1. Mục đích và vì sao nhánh tồn tại
2. Sơ đồ cấu tạo
3. Công nghệ tại nhánh
4. Hợp đồng node (state đọc/ghi, schema vào/ra)
5. Luồng xử lý chi tiết + mã giả
6. Quyết định thiết kế và lý do
7. Cấu hình
8. Dữ liệu, DB, điểm log
9. Trace và giám sát (M9)
10. Lỗi và ca biên
11. Kiểm thử và tiêu chí đạt
12. Phụ thuộc, phase, việc còn mở
13. **Mở rộng, thay thế và scale độc lập** (cách nối hệ thống thật, tách thành module riêng, và điều không được phá)
14. **Sổ tay sửa lỗi** (triệu chứng → xem ở đâu → nguyên nhân thường gặp)
15. **Nhật ký thay đổi của file**

File nền tảng P1–P7 cũng có mục 0.1.

**Quy tắc giữ đồng bộ khối CTX:**

- Khi tài liệu gốc hoặc một D-xx được chốt làm đổi nội dung chung (trạng thái, mã thoát, hằng số, bất biến), sửa khối CTX **ở tất cả các file cùng lúc** và tăng phiên bản (CTX-1.0 → CTX-1.1).
- Kiểm nhanh bằng lệnh: mọi file phải có cùng một dòng phiên bản CTX.
- Khi sửa một nhánh, chỉ sửa file của nhánh đó và ghi một dòng vào mục 15.
- Bản vá v1.2 **không** đổi khối CTX (vẫn CTX-1.0): các D-17…D-28 đều ở trạng thái đề xuất, được liệt kê ở mục 0.5 của từng file liên quan. Khi nhóm chốt D-20 (thêm chuyển `S_CLARIFYING → S_DIAGNOSING`) hoặc D-18 (bất biến side effect idempotent), mới nâng lên CTX-1.1.

**Thuật ngữ cố định** (không đổi tên khi code): 14 trạng thái `S_*`, mã thoát `E0–E9`, `block_reason` (3 giá trị), `close_reason` (8 giá trị), `policy_decision` ∈ {`allow`, `approval_required`, `deny`}, `decided_by` ∈ {`rule`, `llm`}, `Action`, `intended_action`, `action_plan_hash`, `requester_context`.

## 4. Quyết định mới được đưa vào bản build (cần nhóm xác nhận)

*Trạng thái, phase phải chốt và các quyết định Q1–Q14 được theo dõi ở `build/decisions.md` (danh sách duy nhất). Bảng dưới giữ lý do và file liên quan.*

### 4.1. D-01…D-16 (bản 1.0)

Các quyết định dưới đây đã được thảo luận trong phiên làm việc 25/09/2026 và được viết vào bộ tài liệu này. Cột "Ảnh hưởng" cho biết tài liệu gốc nào cần cập nhật khi nhóm chốt.

| Mã | Quyết định | Lý do ngắn | Ảnh hưởng | Trạng thái |
|---|---|---|---|---|
| D-01 | Tách đăng nhập (AuthN) ra khỏi graph thành middleware; B1 chỉ còn "xác lập danh tính + chụp `requester_context`" | API duyệt/ghi đè/policy/L2 không chạy qua graph nên cần lớp bảo vệ riêng; role phải đến từ AD, không từ lời người dùng | TC24, TC25 viết lại; `NGU-CANH-DAY-DU.md` Phần IV B1 | Đã chốt (theo đặc tả) |
| D-02 | RBAC + kiểm tra theo từng bản ghi (chống IDOR), deny-by-default có test quét route | Ma trận 2.2 chỉ ở mức vai trò | Thêm TC30 | Đã chốt (theo đặc tả) |
| D-03 | 4 service identity; chỉ `svc_executor` giữ credential ghi | Phòng thủ nhiều lớp cho "B17 là điểm ghi duy nhất" | Mock services | Đã chốt (theo đặc tả) |
| D-04 | Bảng `security_events` (append-only) + view `auth_failures` | `auth_failures` được nhắc nhưng chưa có trong 17 bảng | `thiet-ke-database.md` | Đã chốt (theo đặc tả) |
| D-05 | Ba role Postgres (`app_rw`, `app_monitor`, `app_migrate`), REVOKE UPDATE/DELETE trên bảng audit | Biến "append-only" và "M9 chỉ đọc" thành ràng buộc thật | Migration Phase 1 | Đã chốt (theo đặc tả) |
| D-06 | B2 có 5 lớp: chuẩn hóa → privacy guard → regex → **model phân loại** → LLM chỉ cho vùng lưng chừng | Giảm lời gọi LLM ở B2 từ 100% xuống ~10–20%, tất định, chạy CPU | B2, chi phí 15.1 | Đã chốt (theo đặc tả) |
| D-07 | Privacy guard chạy ở API **trước khi lưu ticket**, không phải node trong graph | Nếu chạy trong graph, `raw_request` đã bị checkpoint trước → không đạt được "mật khẩu không có trong DB" | B2, `TicketState` | Đã chốt (theo đặc tả) |
| D-08 | Dùng `interrupt()` thay `interrupt_before` cho 3 node chờ người | Tài liệu LangGraph hiện ghi static interrupt không khuyến nghị cho HITL | `NGU-CANH-DAY-DU.md` Phần IV 8.2 | Đã chốt (theo đặc tả) |
| D-09 | Thêm process `ml-service` (embedding, rerank, classifier) | Tránh mỗi worker uvicorn nạp model riêng (8–16 GB RAM) | Compose: 7 process | Đã chốt (theo đặc tả) |
| D-10 | BM25 tách từ tiếng Việt, lưu dạng sparse vector trong Qdrant, gộp RRF phía server | Lọc + gộp trong một truy vấn; version cùng index | M2 | Đã chốt (theo đặc tả) |
| D-11 | Bảng `llm_cache` trong Postgres | Không thêm Redis; cache thực nghiệm được sao lưu cùng DB | `thiet-ke-database.md` | Đã chốt (theo đặc tả) |
| D-12 | LLM gateway tự viết trên SDK `openai` (API tương thích OpenAI), LiteLLM là phương án B | Kiểm soát trọn khóa cache, trace, lineage | M4/LLMOps | Đã chốt (theo đặc tả) |
| D-13 | Kiến trúc **modular monolith** + service phụ trợ, không microservices | Xem `01-kien-truc-project.md` mục 1 | Toàn bộ | Đã chốt (theo đặc tả) |
| D-14 | Audit ghi trong `goto()` có khóa idempotent — **sửa ở v1.2:** khóa là `(ticket_id, step, event, turn_id, loop_seq)` thay vì `(ticket_id, step, turn_id)` | Node chờ chạy lại khi resume → tránh ghi trùng; khóa cũ nuốt mất sự kiện thứ hai cùng bước trong một lượt | M7 | Đã chốt (theo đặc tả) |
| D-15 | B17 kiểm tra lại trạng thái trong AD trước khi ghi — **sửa ở v1.2:** kiểm **cả** người gửi (`requester_context.user_id`) lẫn người hưởng lợi (`action.requested_for`) | Người gửi có thể bị vô hiệu hóa trong 30 phút chờ duyệt; mã giả cũ chỉ kiểm người hưởng lợi | B17 | Đã chốt (theo đặc tả) |
| D-16 | Tool chẩn đoán mặc định chỉ tra cứu chính người gửi (`scope_tool_target`) | Agent không thành công cụ dò thông tin đồng nghiệp | B6, M5 ctx | Đã chốt (theo đặc tả) |

### 4.2. D-17…D-28 (bản vá v1.2 — sửa lỗi lõi AI)

| Mã | Quyết định | Sửa lỗi | File | Trạng thái |
|---|---|---|---|---|
| D-17 | `parent_wait` tự đối soát trạng thái các con từ bảng `tickets` mỗi lần chạy; `child_done` chỉ là tín hiệu đánh thức | L-01: cha không bao giờ đóng khi con xong trước lúc cha vào `parent_wait` | P1, B03-B05, B20 | Đã chốt (theo đặc tả) |
| D-18 | Mọi side effect (thông báo, đặt hạn, tạo phiếu duyệt, tạo/submit ticket con) đi qua `effects.once(key, fn)` với bảng `side_effects`; phục hồi sau sự cố bằng `ainvoke(None)`, giữ nguyên `turn_id` | L-02: phiếu duyệt/thông báo trùng khi process chết giữa chừng | P1, P7, B03-B05, B10, B11, B15-B16, B17-B18 | Đã chốt (theo đặc tả) |
| D-19 | Khóa ticket bằng `pg_advisory_lock` cấp session trên pool khóa riêng, nhả trong `finally`, có `lock_timeout` | L-03: transaction mở suốt lượt có gọi LLM, cạn pool | P1, B15-B16 | Đã chốt (theo đặc tả) |
| D-20 | Chẩn đoán lại khi slot mới thay đổi tham số tool: B11 → B6 (tính `reasoning_loops`); cần thêm chuyển `S_CLARIFYING → S_DIAGNOSING`. Cờ `REDIAGNOSE_ON_NEW_SLOT` **mặc định tắt** tới khi chốt | L-08: facts cũ/thiếu sau khi hỏi lại; `MAX_LOOPS` không có vòng thật | P1, P5, B06-B07, B11 | Cờ tắt ở bản đầu (Q10 đã chốt) |
| D-21 | Chunk đo bằng tokenizer bge-m3, trần 380 token nội dung | L-04: chunk > 512 token bị cắt âm thầm | P3, P4, B08-B09 | Đã chốt (theo đặc tả) |
| D-22 | Bộ ≥ 20 câu không có đáp án; chọn `RETRIEVAL_THRESHOLD` theo cặp tỉ lệ lỗi | L-05: ngưỡng E3 không kiểm chứng được | P3, B08-B09 | Đã chốt (theo đặc tả) |
| D-23 | Truy hồi lại một lần không lọc intent khi điểm dưới ngưỡng; ghi `intent_filter_fallback` | L-06: B3 phân sai → E3 oan | P3, B08-B09 | Đã chốt (theo đặc tả) |
| D-24 | Mở rộng ngữ cảnh cho B10 bằng chunk liền kề cùng tài liệu | L-09: hướng dẫn thiếu bước | P3, B10 | Đã chốt (theo đặc tả) |
| D-25 | K2 giữ 16 tài liệu tối thiểu; mục tiêu ≥ 50 tài liệu có tài liệu gây nhiễu; ablation RAG 4 cấu hình (Recall@5, MRR, nDCG@5) | L-10: pipeline quá phức tạp so với KB, chưa có số liệu biện minh | P3, B08-B09 | Đã chốt (theo đặc tả) |
| D-26 | Ticket mới do L2 mở lại (`reopened_as_new`) chạy **từ B1**; `intended_action` dựng lại từ đầu | L-11: mâu thuẫn B1 / B12 giữa NGU-CANH và huong-dan | B20 | Từ B1 (Q11 đã chốt) |
| D-27 | Ca confidence thấp vẫn ra E1 nhưng ghi `event=intent_low_confidence` và `escalations.reason_detail` | L-12: chỉ số E1 lẫn hai loại ca | B03-B05 | Đã chốt (theo đặc tả) |
| D-28 | Viết tường minh lập luận "constrained agent" (LLM hiểu ngôn ngữ và ước lượng; code nắm điều khiển và hành động) | Chuẩn bị câu hỏi hội đồng "đâu là phần agent?" | P1 | Đã chốt (theo đặc tả) |

### 4.3. D-29…D-31 (bản vá v1.3 — ticket cha/con và chuyển trạng thái)

| Mã | Quyết định | Sửa lỗi | File | Trạng thái |
|---|---|---|---|---|
| D-29 | `ALLOWED_TRANSITIONS` viết tường minh = bảng 2.1 **[Chốt]** + 3 quy tắc: giữ nguyên trạng thái xử lý; mọi trạng thái chưa kết thúc → `S_ESCALATED`; chuyển riêng của ticket cha. `FORBIDDEN` vẫn thắng | L-13: HITL, deflection, E9 ở B1/B2, đóng cha đều ném `IllegalTransition` | P1, B03-B05 | Đã chốt (theo đặc tả) |
| D-30 | Ticket cha đóng với `close_reason = NULL`, không `exit_code`, không `escalations`; `tickets.is_parent`; mọi chỉ số M8/M9 và hàng đợi L2 chỉ tính ticket lá | L-14: cha mồ côi trong hàng đợi L2, chỉ số đếm trùng | P1, P7, B03-B05, B20 | Đã chốt (theo đặc tả) |
| D-31 | **Giữ đúng câu chốt "một câu trả lời tổng hợp"**: ticket con không tự nhắn (`notify_user` ghi `child_notices`); cha gửi **một tin mỗi lượt người dùng** khi mọi con đã dừng; người dùng trả lời/xác nhận một lần cho mọi ý qua `POST /tickets/{cha}/reply`; cha chuyển xuống từng con | L-15: câu chốt không có cơ chế, va với B19 | P1, P7, B03-B05, B10, B11, B15-B16, B17-B18, B19, B20 | Nhóm đã chọn phương án; nên báo GVHD đánh đổi "người dùng chờ ý chậm nhất" (tối đa `SLA_MINUTES`) |

### 4.4. D-32…D-33 (model phân loại do nhóm huấn luyện)

| Mã | Quyết định | Lý do | File | Trạng thái |
|---|---|---|---|---|
| D-32 | B3 chạy model phân loại intent **đa nhãn** trước (`intent-clf` qua ml-service `/classify_intent`); chỉ vùng lưng chừng, câu nhiều ý (cần tách span) hoặc khi chưa có model mới gọi LLM `b03_classify` | Nâng mục "fine-tune model intent" (Nên có, `huong-dan` mục 11) lên đường chính theo cùng khuôn B2; intent tất định, nhanh, chịu câu không dấu | B03-B05, P4, P2, P9, P11 | Đã chốt (theo đặc tả) |
| D-33 | Backbone `microsoft/mdeberta-v3-base` cho cả `intent-clf` và `injection-clf`; PhoBERT-base-v2 làm baseline so sánh intent; Prompt Guard 2 chỉ làm baseline RQ4 | Câu thật không dấu, viết tắt, trộn tiếng Anh; một script/tokenizer/đường ONNX cho cả hai model | P11, B02, P4 | Đã chốt (theo đặc tả) |

Các patch cho tài liệu gốc (`NGU-CANH-DAY-DU.md`, `huong-dan-xay-dung-he-thong-2.md`, `NGU-CANH-DAY-DU.md` Phần IV, `thiet-ke-database.md`, sơ đồ kiến trúc) được gom ở `claude/bo-sung-bo-tai-lieu-build.md`. Các patch "áp ngay" (sửa lỗi gõ, thêm mục trỏ sang `build/`) đã được áp vào `huong-dan-xay-dung-he-thong-2.md` ngày 25/09/2026. Các patch còn lại chỉ áp sau khi quyết định tương ứng được chốt.

## 5. Điểm lệch với tài liệu gốc còn cần xử lý

- Mã luật R22 (tài liệu cũ) vượt quá 20 luật → đã đánh số lại thành **R17**; bảng R01–R20 ở `decisions.md` mục 1.1 (N4).
- `S_SPLIT` trong mã giả B5 gốc được thay bằng cờ `is_parent` (P1 mục 8).
- Ticket L2 mở lại chạy từ B1 hay B12 → Q11 (D-26).

## 6. Thứ tự đọc cho coding agent

```
00-README → 01-kien-truc-project → 02-cac-tang-he-thong
         → P7-db-thay-doi → P5-tool-registry-mock → P6-auth-bao-mat   (Phase 1)
         → P1-langgraph-runtime → B01 → B20                              (Phase 2)
         → P2-llm-gateway → P4-ml-service → P3-rag-pipeline
         → B03-B05 → B06-B07 → B08-B09 → B10 → B11 → B12-B14 → B17-B18 → B19 (Phase 3)
         → B15-B16                                                       (Phase 4)
         → B02 + phần còn lại của B03-B05, B12-B14, B17-B18              (Phase 5)
         → B12-B14 lớp 2                                                 (Phase 6)
         → P10-giao-dien + P9-monitor-M9 (dashboard)                     (Phase 7)
         → P8-danh-gia-M8                                                (Phase 8–10)
  Song song từ Phase 1 (nhóm dữ liệu + TV1): P11-huan-luyen-model
```

Trước Phase 0: đọc `build/decisions.md` để biết phải chốt gì trước từng phase.

Câu giao task mẫu: *"Làm nhánh B06-B07. Đọc `build/00-README.md`, `build/01-kien-truc-project.md`, `build/nen-tang/P5-tool-registry-mock.md` rồi `build/nhanh/B06-B07-chan-doan.md`. Chỉ sửa file trong `backend/app/tools/` và `backend/app/graph/nodes/b06_diagnose.py`. Xong khi mọi test ở mục 11 xanh."*

## 7. Nhật ký thay đổi

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo bộ tài liệu; D-01…D-16 |
| 25/09/2026 | 1.1 | Khuôn 16 mục, khối CTX-1.0 cho mọi file |
| 25/09/2026 | 1.2 | Bản vá lõi AI: D-17…D-28; sửa khóa D-14 và phạm vi D-15; P7 lên 21 bảng; thêm điểm phát hiện 4–5; trỏ sang `claude/bo-sung-bo-tai-lieu-build.md` |
| 25/09/2026 | 1.3 | D-29…D-31: bảng chuyển tường minh, đóng ticket cha, một tin tổng hợp cho yêu cầu nhiều ý; P7 lên 22 bảng; TC34–TC36 |
| 25/09/2026 | 1.4 | Thêm P8 (M8), P9 (M9), P10 (giao diện), `decisions.md`; khối CTX-1.1; sửa TC21/TC37, D-02, tham chiếu `workflow-chi-tiet.md` |
| 25/09/2026 | 1.5 | Thêm P11 (huấn luyện model phân loại); D-32, D-33 |
