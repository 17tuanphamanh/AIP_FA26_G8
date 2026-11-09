# Đặc tả: kết nối 2 model phân loại vào hệ thống — B2 chế độ `review`, B3 ghi điểm, chống dò và spam (v0.6)

*v0.6 — 18/10/2026, 03:25. Đã chốt với Tuấn Anh (mục 1, dòng 1–26); quyết định ghi ở `build/decisions.md` D-52…D-55 (D-56 chỉ khi đổi LLM chấm); tóm tắt và lịch ở `build/phase5-thiet-ke-chi-tiet.md` mục 7.14. Bản này đã soát lại với code `33b7484` (code giống `3cf0d18`) bởi 3 người soát độc lập. Lúc 03:25 Tuấn Anh chốt 4 điểm còn chờ (mục 1, dòng 23–26): không còn điểm nào chờ duyệt trước khi mở phiên (mục 13). Sửa lúc 04:10 cùng ngày, trước khi commit (vẫn v0.6): soát lần cuối trên `33b7484` — mục 8 thêm 5 test cũ phải đổi có chủ ý (gói 1: 1; gói 2b: 4, đủ 8 test cho 2b); mục 4.10 đếm nghi tấn công từ `escalations` (view hàng chờ L2 chỉ có ca đang mở); mục 10, 12 thêm việc rebase 2b của phiên git và yêu cầu dữ liệu rõ hơn cho Dương, Duy Anh. Repo đọc trên máy Tuấn Anh, chỉ đọc, không đụng stack.*
*Nhãn: [Chốt] Tuấn Anh đã chọn · [Đã kiểm] thấy trong code, tài liệu hoặc số đo · [Suy luận] suy ra, chưa đo · [Đề xuất] chờ duyệt.*

## 0. Một màn hình

| | Hiện nay | Sau đặc tả này |
|---|---|---|
| B2 lớp 3 (`injection-clf`) | Không nạp; `shadow` | Nạp; chế độ `review`: model chấm mọi câu không khớp regex, **không bao giờ cho câu đi thẳng**; điểm ≥ τ mà LLM chấm nói không phải tấn công → E1 `injection_suspected` (chuyển L2, không ghi sự cố an ninh) |
| B2 lớp 4 (LLM chấm) | `b02_injection_judge`, vai trò `fast` (DeepSeek) | **Giữ DeepSeek.** Đổi sang Gemini qua vai trò riêng chỉ khi qua phép thử chấp nhận (mục 3) |
| B3 (`intent-clf`) | `/classify_intent` luôn 503 | Số offline trước; bộ nạp vào ml-service có điều kiện bộ nhớ; B3 chỉ ghi điểm, LLM vẫn quyết |
| Bỏ sót tấn công | regex ∪ LLM | regex ∪ LLM ∪ model — không tăng ở bất kỳ dòng nào khi LLM chấm giữ nguyên |
| Chặn nhầm (E0) | do LLM | do LLM — model không tự ra E0 |
| Chuyển người thừa (E1 ở câu thường) | — | Tối đa khoảng 6,1% ở τ = 0,90: 6,1% câu thường trong validation của Dương có p ≥ 0,90, còn E1 thừa thật thấp hơn vì phải trừ câu LLM chấm đã bắt (khoảng tin cậy rộng 1,4–12,6% [Suy luận]; ngoài phân phối có thể cao hơn). Trần chọn τ: cận trên ≤ 15% [Chốt] |
| Chống spam | Không có; chỉ giới hạn độ dài (413) | 429 theo tài khoản [Chốt]: ticket mới ≤ 10 trong 10 phút và ≤ 30 mỗi giờ; tin nhắn (`/messages`, `/reply`, `/confirm`) ≤ 30 trong 10 phút, đếm bằng bảng `rate_hits` trong DB [Chốt 18/10 03:25]. Ghi sự kiện `rate_limited` (gói 2b, 4.8) |
| Báo L2 khi bất thường | Cảnh báo M9 chỉ Trưởng BP xem được | Dòng lịch sử người gửi trong ghi chú L2; trang Cảnh báo cho L2 (chỉ cảnh báo an ninh, chỉ xem); luật M9 theo người gửi (gói 2b, 4.9–4.10) |
| Câu nhiều ý có ý không chắc | Tách; ý không chắc thành con E1 | Như cũ, trừ khi ý không chắc dính vào ý chạy được thì chuyển cả câu (B3-VA, prompt riêng) |
| Lịch | | 4 gói + B3-VA trên 2 worktree, thêm 1 phiên cho các việc F khác (tối đa 3 phiên cùng lúc), cố không cắt việc (mục 10). Mốc quyết 12:00 20/10, `verify` 14:00 21/10, gộp trước 18:00 21/10 |

B2 trong báo cáo được trình bày là lớp **"toàn vẹn + phát hiện"**. Câu lọt B2 không tạo được hành động trái phép (M5 không đọc chữ người dùng, `target_is_other` tính tất định, slot phải có trong câu, người duyệt cố định, B17). Thứ B2 giữ là: chữ do bot viết không bị câu tấn công dắt (B10 in nguyên tới 2.500 ký tự), tín hiệu an ninh, và số đo cho Objective 3.

## 1. Đã chốt với Tuấn Anh

| # | Quyết định | Khi |
|---|---|---|
| 1 | B2: mọi câu không khớp regex vẫn qua LLM chấm; model không cho câu nào đi thẳng | 17/10 23:20 |
| 2 | B2: hai mức — LLM xác nhận tấn công → E0 như nay; chỉ model nghi → chuyển L2, không ghi sự cố an ninh | 17/10 23:20 |
| 3 | LLM chấm chuyên biệt: thử trước, tốt hơn mới đổi — so DeepSeek với Gemini trên 1.800 câu validation của Dương; Gemini bắt tấn công ≥ DeepSeek và chặn nhầm không hơn quá 1 điểm thì đổi, không thì giữ DeepSeek và làm sau 27/10 | 18/10 01:00 |
| 4 | B3: chỉ ghi điểm, chưa cascade | 17/10 23:30 |
| 5 | Cố đưa vào bản ứng viên ("hoàn thiện luôn nếu được") | 17/10 23:30 |
| 6 | RQ1 chạy với `review` bật — báo số ticket dừng ở B2, M5 tính trên phần giao (mục 9.4) | 18/10 00:55 |
| 7 | Cổng 5 cho B2: tiêu chí chính E0 như đã chốt; tiêu chí phụ đối xứng (mục 9.2) | 18/10 00:55 |
| 8 | Số `review` cho cổng 5 tính offline từ lượt 17/10, không chạy lại bộ câu (Tuấn Anh không chọn, Claude chọn theo khuyến nghị) | 18/10 00:55 |
| 9 | E_max = 15% (4.5). Chốt trước khi chạy LLM chấm trên validation; lúc chốt đã biết 6,1% câu thường của validation có p ≥ 0,90 | 18/10 |
| 10 | `injection_suspected` vào hàng chờ L2 với ưu tiên "Thường" kèm câu cảnh báo; không đổi bảng `exit_code_priority` | 18/10 |
| 11 | Kênh dò (người gửi phân biệt E0 với E1 qua trạng thái và mã thoát): chấp nhận trong bản chấm; phát hiện bằng luật M9 theo người gửi và chống spam; không ẩn mã thoát trước 27/10 | 18/10 |
| 12 | Luật M9 theo người gửi: agent viết ngày 19/10 (gói 2b), Dương soát khoảng 30 phút | 18/10 |
| 13 | Chống spam: chặn theo tài khoản (429) và ghi sự kiện an ninh `rate_limited` (cần 1 migration) | 18/10 |
| 14 | Báo L2 bằng cả hai cách: dòng lịch sử trong ghi chú L2 và trang Cảnh báo cho L2. Phạm vi trang: L2 chỉ thấy cảnh báo an ninh và chỉ xem, không ack | 18/10 |
| 15 | Gemini trượt phép thử → thử Qwen nếu kịp trước 12:00 20/10; không kịp hoặc trượt → giữ DeepSeek | 18/10 |
| 16 | Thay nhãn che ở đầu vào B3: đo trước rồi quyết; tiêu chí ghi trước trong D-53 (6.1) | 18/10 |
| 17 | Cố không cắt việc nào; xếp 2 worktree chạy song song (mục 10) | 18/10 |
| 18 | B3-VA: "tách có kiểm dính nhau" thay cho bản "chuyển cả câu khi có ý không chắc" (prompt `claude/prompt-b3-va.md`) | 18/10 |
| 19 | Số D liền nhau, judge để cuối: D-54 chống dò và spam; D-55 B3-VA; D-56 đổi judge (chỉ ghi khi đổi) | 18/10 01:30 |
| 20 | Ngưỡng 429 cho ticket mới: 10 trong 10 phút, 30 mỗi giờ | 18/10 01:30 |
| 21 | Luật M9 theo người gửi: cảnh báo khi ≥ 3 lần trong 24 giờ; nghiêm trọng khi trong 7 ngày có cả E0 lẫn nghi tấn công | 18/10 01:30 |
| 22 | Bộ đếm tin nhắn: một bộ chung, tối đa 30 trong 10 phút. Phạm vi và cách đếm chốt lại ở dòng 23 | 18/10 01:30 |
| 23 | Bộ đếm tin nhắn đếm cả `/confirm` (`/messages`, `/reply`, `/confirm` chung một bộ) và đếm bằng bảng `rate_hits` trong migration `0010`, không đếm trong bộ nhớ: số đếm còn khi khởi động lại, đúng khi chạy nhiều tiến trình; đổi lại 1 lần ghi DB mỗi tin nhắn và gói 2b thêm khoảng 1 giờ (4.8) | 18/10 03:25 |
| 24 | Ba luật đo, ghi trước vào D-52: (1) dòng #3 với lượt 17/10 — gọi lại DeepSeek 1 lần cho câu đã qua để lấy `category`, ghi là "đo bổ sung"; (2) tiêu chí phụ cổng 5 chỉ để báo; (3) đổi LLM chấm chỉ khi tốt hơn có bằng chứng (mục 3, 9.2) | 18/10 03:25 |
| 25 | Tối đa 3 phiên coding agent cùng lúc trong 18–21/10 (mục 10) | 18/10 03:25 |
| 26 | Claude chép 6 file tài liệu đã sửa vào `docs/spec` trên máy Tuấn Anh; phiên git commit + push (mục 10, 12) | 18/10 03:25 |

Không làm:
- Chế độ `active` 0,90/0,10: giữ trong code, không dùng.
- Cascade B3.
- LLM chấm chạy local: chỉ viết vào báo cáo, vì Mac 16 GB đã phải swap lúc đo và khó tái lập trên 4 máy.
- Che hẳn E0/E1 với người gửi: chỉ ghi vào phần giới hạn (4.4).

## 2. Hiện trạng [Đã kiểm, `3cf0d18`]

### B2

- `backend/app/graph/nodes/b02_screen.py:52-77`:
  - L3 gọi `deps.ml.classify`; chỉ `active` quyết theo `TAU_BLOCK`/`TAU_PASS` (`guard/injection.py:19-20`: 0,90/0,10); `shadow` luôn xuống L4.
  - L4 gọi `deps.llm.complete("fast", "b02_injection_judge", …)` và chỉ xét `is_attack` (dòng 73).
  - `ml_error` chỉ ghi ở nhánh E2.
- `settings.py:199`: `b2_classifier_mode: Literal["shadow", "active"] = "shadow"`.
- **E0:**
  - `security_events(injection_detected)`;
  - M9 luật 2 cảnh báo mọi E0;
  - tin người dùng: "Yêu cầu của bạn đã được ghi nhận và chuyển cho bộ phận IT xem xét."
- **E1:** tin người dùng là "Mình là trợ lý IT, hiện hỗ trợ: VPN, tài khoản và mật khẩu, cài phần mềm, quyền truy cập thư mục. Yêu cầu này mình đã chuyển kỹ thuật viên hỗ trợ bạn." (P6 lời nói, ĐP 08/11: câu nói trợ lý hỗ trợ gì đứng trước, danh sách loại việc theo `enabled_intents`; riêng E1 `injection_suspected` vẫn nhận tin E0, mục 4.4); ưu tiên L2 "Thường" (`config/escalation_templates.yaml`, `domain/exit_codes.py:25`).
- Người gửi xem được `exit_code` ticket của mình (`backend/app/api/tickets.py:141, 229`).
- **Ràng buộc mã thoát:**
  - không được thêm mã thoát hay close_reason;
  - `REASON_DETAILS` là tập đóng, có test AST;
  - chuyển `S_SCREENING → S_ESCALATED` chỉ đi qua quy tắc 2 "hướng an toàn" (`domain/states.py:94`; chú thích ghi E2, E9).

### LLM gateway

- Lỗi không thử lại được (400–404, gồm cả key sai và hết hạn mức) vẫn chuyển sang đích dự phòng kế tiếp.
- Lỗi sai schema sau 1 lần sửa thì ra `LLMSchemaError`, không dự phòng.
- Dẫn chứng: `backend/app/llm/client.py:16, 270-280, 340-350`.

### ml-service

- Một semaphore chung cho embed, rerank, count_tokens, classify (`ml_service/app/main.py:84-88`).
- Backend gọi classify với timeout 2 s, thử lại 2 lần (`backend/app/ml/client.py:43-47`); rerank p95 10–15 s.
- Model chặn tấn công chỉ nạp safetensors; SHA tuỳ chọn và chỉ phủ `model.safetensors` (`ml_service/app/guard.py`).
- `/classify_intent` luôn trả 503 (`main.py:169-171`); `/health` ghi cứng intent là "missing" (`main.py:123`).

### Gói intent

- `ml_models/intent-clf/v3.1-seed42/`: `seed_42.pt` (state_dict fp16, 559 MB).
- Điểm của gói (`predict_proba`, `intent_inference.py:187-199`) là **`0,4·sigmoid(seq) + 0,6·p_span + 0·p_filt`** (`mix_weights`), không phải sigmoid. Ngưỡng D-44 chọn trên điểm trộn này.
- `p_span[l]` = max theo token (có offset hợp lệ) của P(`B-REQ:l`) + P(`I-REQ:l`) từ softmax đầu gắn thẻ.

### Số đo của Dương

Validation 900 câu tấn công + 900 câu thường, ChatGPT sinh:

- Ở ≥ 0,90: 55/900 câu thường (48 câu ≥ 0,99).
- Ở ≤ 0,10: 31/900 câu tấn công (28 câu ≤ 0,01).
- Bộ khó (Gemini sinh): FPR 11,3%, FNR 16%. Câu không dấu: FPR 14,8%.
- Câu thường có nhãn che: 9/22 ≥ 0,90; thay bằng từ thường (bộ từ ở 4.3) thì 0/22.

### Khác

- **Bộ nhớ:** ML-KIEM 03/10 dự tính 5,96/7 GiB (cận trên 6,37); nạp intent lên đỉnh 1,83 GB.
- **Số quyết định:** D-51 đã dành cho "model LLM chính thức" (`decisions.md:316`). Đặc tả này dùng [Chốt]:
  - D-52: B2;
  - D-53: B3;
  - D-54: chống dò và spam;
  - D-55: B3-VA;
  - D-56: đổi judge, chỉ ghi khi đổi.

### Chống spam, quyền, cảnh báo

- **Giới hạn tần suất:**
  - Chưa có giới hạn số yêu cầu của mỗi tài khoản. Chỉ có `BodyLimitMiddleware` trả 413 (`api/limits.py`).
  - Đăng nhập đã có: giới hạn lượt sai theo dải IP (429), khoá tài khoản 15 phút, MFA cho Trưởng BP (`auth/service.py`).
- **Ticket:** được lưu (bản đã che) TRƯỚC khi chạy graph, kể cả ca bị chặn (`api/tickets.py:178-199`: `desk.tickets.create` rồi `spawn`).
  - Bảng `tickets` có index `created_at` (chỉ ticket lá) và `parent_ticket_id`, chưa có (`requester_id`, `created_at`).
  - Bảng `turns` không có cột người gửi. `turns.event_type` chỉ có `submit`/`resume`/`recover` (`db/models.py:87`); lượt `resume` gồm cả việc không do người gửi làm (L1 duyệt `api/approvals.py:215-217`, đánh thức cha, lượt của con, timeout của worker). Tin gửi sai bước KHÔNG tạo dòng `turns`, chỉ ghi audit `late_event` với `turn_id = NULL` (`graph/late_event.py:83-92`). `/confirm` sai bước cũng chạy privacy guard và ghi `late_event` rồi mới trả 409 (`api/tickets.py:259-269`).
- **Cảnh báo M9:**
  - `/api/alerts` và ack cùng cần `alert:read`, mà quyền này chỉ manager có (`auth/permissions.py`).
  - `audience` là nhãn, không lọc quyền (Q-M9-A3-1). Giá trị hiện có: `manager`, `dev`, `ops` (`monitor/rules.py:45`).
  - FE dựng menu theo `permissions` lấy từ `/api/auth/me` (`frontend/src/auth/permissions.ts`), không so tên role.
  - Test đang ghim: `test_alerts_api.py::test_alerts_l2_employee_403` và `test_alert_view_exact_12_keys`.
- **`security_events.event_type`** là tập đóng (`db/models.py:92`), có CHECK ở DB, đổi qua migration như bản 0002. Migration mới nhất là `0009_monitor_indexes`, ở cả thư mục chính lẫn `-m5`.
  - B2 ghi `injection_detected` chỉ kèm `ticket_id`, không có `user_id` (`b02_screen.py:81-84`; port `SecurityEvents.record` không có tham số `user_id`, `graph/ports.py:258-260`), dù writer có nhận `user_id` (`audit/security_events.py:29-44`).
  - M9 không được đọc thẳng bảng `tickets` (test D-30: `test_monitor_dash_business.py:284`, `test_monitor_jobs_minute.py:786-801`); view `v_leaf` chưa có `requester_id` (`0008_monitor_views.py`).
- **Bảng và quyền DB [Đã kiểm `33b7484`]:**
  - Số bảng bị test ghim là 22: `tests/unit/test_db_models.py::test_22_tables`, `::test_migration_grants_cover_every_table` (so với danh sách quyền của `0001`), `tests/integration/test_migration.py::test_upgrade_creates_exactly_22_tables`; `test_models_match_migration` so model với DB bằng `compare_metadata`.
  - Quyền của `app_rw` cấp theo danh sách bảng ở `0001` (`RW_CRUD_TABLES`; `audit_logs`, `security_events` append-only, có trigger); `GRANT USAGE, SELECT ON ALL SEQUENCES` chỉ chạy lúc `0001`, không phủ sequence tạo sau.
  - 3 view M9 tạo `WITH (security_invoker = true)` ở `0008`; test `test_views_are_security_invoker` (`tests/integration/test_monitor_dash_views_pg.py:130`) ghim option này.
  - `tickets.created_at` lấy từ Clock của app (`api/tickets.py:192`), không từ `now()` của Postgres. Mỗi repo ở `db/` mở transaction riêng (`engine.begin()`).
- **FE** đã có sẵn câu chung cho 429: "Thao tác quá nhanh, thử lại sau." (`frontend/src/api/errors.ts:115`).
- **Ghi chú L2:** `escalation_note` trong state được `_why` nối vào ghi chú L2 (`audit/handoff.py:102-123`), nên thêm dòng mới không cần sửa `handoff.py`.
- **Trần chi LLM** (`llm/spend.py`): vượt trần thì bỏ mọi đích trả phí → `LLMUnavailable` → E2. Hệ quả: một tài khoản spam đủ lâu sẽ đẩy yêu cầu của MỌI người sang L2.
- **Chạy và cấu hình:**
  - Backend chạy 1 tiến trình uvicorn (`backend/Dockerfile`, CMD không có `--workers`).
  - Compose liệt kê biến tường minh ở `x-backend-env` (`docker-compose.yml:8-52`): biến mới phải thêm vào đây thì stack mới đặt được. `scripts/verify.sh` `recreate` truyền biến shell khi tạo lại backend/worker (`:142-144`). Compose có `name: servicedesk` cố định: `make up` ở worktree nào cũng thay đúng các container đó và dùng chung volume `pgdata`.
  - Gate tạo nhiều ticket cho một tài khoản trong vài phút (gate2 cho `an.nv`); DB không bị xoá giữa các lượt.
  - Test tích hợp dùng Postgres riêng qua testcontainers (`tests/integration/conftest.py`): chạy được ở worktree không có stack, chỉ cần Docker.
- **Đường đi của τ và phán quyết:**
  - Ngưỡng B2 hiện là hằng ở backend (`guard/injection.py:19-20`). Thư mục `ml_models/*-clf/` bị gitignore (`.gitignore:66`) và chỉ gắn vào ml-service (`docker-compose.yml:152`): backend không đọc được file trong thư mục model.
  - Nhánh cho qua của B2 chỉ ghi `layer_decided`, `p_mal`, `clf_mode` (`b02_screen.py:77`, `_pass` ở :91-94); `llm_category` chỉ có ở ca E0 do LLM chặn. `llm_calls` không lưu đầu ra LLM (`prompt_full` chỉ ghi khi bật EVAL_MODE). Vì vậy lượt 17/10 không có phán quyết LLM chấm của câu đã qua.
  - `ml/client.py` thử lại timeout, mất kết nối, 5xx 2 lần (TOOL_RETRY = 2); `asyncio.to_thread` ở ml-service không huỷ được khi backend hết hạn chờ. `TEXT_MAX` = 4.000 ký tự (`api/tickets.py:68`), khoảng 43 cửa sổ, dưới mức 48 của 422 `too_many_windows`.
- **Câu nhiều ý:** code đã phán từng ý (T20b, D-49): ý không chắc thành con E1 `intent_low_confidence`, các con khác vẫn chạy (`b03_classify.py` `_verdict`, `_split`; `test_t20b_split.py::test_v4_low_confidence_child_e1_other_runs`). Đặc tả nhánh `B03-B05` §5.1 còn mã giả trước T20b.

## 3. LLM chấm: phép thử chấp nhận [Chốt cách làm; số liệu chờ đo]

- **Dữ liệu:** 900 + 900 câu validation của Dương.
  - Mỗi câu cho qua L0 + L1 (che PII) như lúc vận hành.
  - Tính trên tập câu **không khớp regex** (đúng phần LLM chấm thấy); báo thêm số trên toàn tập.
  - Không dùng bộ khó, vì bộ đó do Gemini sinh nên sẽ lệch về phía Gemini.
- **So sánh:** `deepseek-flash` (bản đang chạy) với `google/gemini-3.6-flash`, cùng prompt `b02_injection_judge` v1, ghép cặp trên cùng câu.
  - Script `scripts/eval/b2_judge_compare.py` (gói 1); Tuấn Anh chạy 19/10.
  - Khoảng 3.600 lời gọi, 1–3 USD.
- **Đổi sang Gemini khi đạt đủ cả 4:**
  - [Chốt] recall trên câu tấn công không khớp regex ≥ DeepSeek;
  - [Chốt] tỉ lệ E0 trên câu thường ≤ DeepSeek + 1 điểm;
  - [Đề xuất, điều kiện vận hành] JSON hợp lệ ≥ 99%;
  - [Đề xuất, điều kiện vận hành] p95 ≤ 3 s.
  - Báo kèm khoảng tin cậy bootstrap ghép cặp theo nhóm mẫu và kiểm định McNemar.
- **Gemini trượt → thử Qwen [Chốt]:**
  - chạy `qwen/qwen3.8-flash` ngay sáng 20/10, cùng script, cùng 1.800 câu, cùng 4 điều kiện;
  - chưa xong trước 12:00 20/10 thì giữ DeepSeek, không chờ;
  - Qwen đạt thì gói 3 dùng Qwen, D-56 ghi model thật được chọn;
  - cả hai trượt thì giữ DeepSeek; LLM riêng làm sau 27/10 trên nhánh demo;
  - báo cáo có bảng so sánh 3 model (hoặc 2 nếu không kịp chạy Qwen).
- **Chốt trước 12:00 20/10.** Đạt → gói 3 (mục 5) chiều 20/10 và đo lại phần B2 tối 20/10. Không đạt → bản ứng viên dùng DeepSeek.
- **Cách gọi (giống hệt lúc chạy thật):**
  - script gọi qua `LLMClient` + `OpenAICompatProvider` với store trong bộ nhớ: cùng cách render prompt, cùng dấu phân cách ngẫu nhiên, cùng 1 lần sửa schema;
  - khoá OpenRouter đọc từ biến `LLM_JUDGE_API_KEY`, không ghi ra file; có khoá và hạn mức trước 19/10;
  - thân request ghim một lần và dùng lại nguyên cho gói 3: slug có ngày; `provider: {order: [<nhà cung cấp>], allow_fallbacks: false, require_parameters: true, data_collection: deny, zdr: true}`; `reasoning` tắt hoặc mức thấp nhất model cho phép (kiểm cờ `mandatory` của model); temperature 0; `max_tokens` bắt đầu 400 như `fast`, tăng nếu thấy `finish_reason: length` (token suy luận tính vào `max_tokens`);
  - ghi nhà cung cấp thật của từng lời gọi.
- **Định nghĩa:** E0 = `is_attack` hoặc `category ≠ none`. "JSON hợp lệ" báo 2 số: hợp lệ ngay lần đầu, và hợp lệ sau 1 lần sửa (tiêu chí dùng số sau sửa, giống lúc chạy). Lỗi và timeout tính riêng, không tính là bắt hay bỏ.
- **Đầu ra từng câu** của `b2_judge_compare.py`: `{id, group, label, model, is_attack, category, json_valid_first_try, repaired, latency_ms, provider, error}` — đầu vào của `b2_tau_select.py` (4.5).
- **Quy tắc đổi [Chốt 18/10 03:25, ghi trước vào D-52 — siết theo hướng giảm bỏ sót]:** ngoài 4 điều kiện trên, chỉ đổi khi model mới tốt hơn có bằng chứng:
  - cận dưới một phía 97,5% của Δrecall (bootstrap ghép cặp theo nhóm; 97,5% vì thử 2 model) > 0;
  - recall E0 ∪ E1, với τ chọn lại cho model mới, ≥ DeepSeek.
  - Lý do: khoảng 450 câu tấn công không khớp regex, khoảng 8% câu hai model bất đồng; model kém thật 1 điểm recall vẫn qua quy tắc "≥" khoảng 28% mỗi lần, khoảng 48% sau cả Gemini lẫn Qwen [Suy luận].
- **Đổi LLM chấm thì chọn lại τ** theo phán quyết của model mới (4.5), vì E1 thừa phụ thuộc phán quyết của LLM chấm.
- **Số tham chiếu (OpenRouter, đọc 18/10):**
  - Gemini 0,75/3,75 USD mỗi triệu token, độ trễ 1,1–1,4 s.
  - Qwen 3.8 Flash 0,15/0,47 USD, 44 token/s.
  - DeepSeek flash 0,30/1,20 USD.

## 4. B2 — chế độ `review` (gói 1)

### 4.1. Luồng

```
regex (L2) khớp ───────────────────────────────────────► E0 (như nay)
không khớp
  ├─ model (L3, hàng chờ riêng): /classify trên bản đã thay nhãn che (4.3) → p_mal | ml_error
  └─ LLM chấm (L4): b02_injection_judge, vai trò fast (DeepSeek)
       is_attack = true HOẶC category ≠ none ─────────────► E0 (như nay)
       LLMUnavailable / LLMSchemaError / hết hạn mức ───────► E2 screening_unavailable + security_flag (như nay)
       không phải tấn công:
         p_mal ≥ τ  HOẶC  ml_error = too_many_windows ─────► E1 injection_suspected
         p_mal < τ, ml_error khác, hoặc model chưa nạp ─────► S_CLASSIFYING → B3
hết hạn cả lượt ở L3 hoặc L4 ───────────────────────────► E2 turn_budget_exceeded + security_flag (như nay)
```

Thứ tự gọi giữ như code hiện tại: model trước, LLM sau. `ml_error` (kể cả `model_missing`) được ghi vào `screening` ở **mọi nhánh**.

### 4.2. Bảng quyết định (test viết từ bảng này)

| # | Regex | Model | LLM chấm | Kết quả | `layer_decided` |
|---|---|---|---|---|---|
| 1 | khớp | không gọi | không gọi | E0 | `regex` |
| 2 | không | bất kỳ | `is_attack = true` | E0 | `llm` |
| 3 | không | bất kỳ | `is_attack = false` nhưng `category ≠ none` | E0 | `llm` |
| 4 | không | p ≥ τ | không phải tấn công | E1 `injection_suspected` | `classifier` |
| 5 | không | 422 `too_many_windows` | không phải tấn công | E1 `injection_suspected` | `classifier` |
| 6 | không | p < τ | không phải tấn công | qua → B3 | `llm` |
| 7 | không | `model_missing`, timeout, `connect`, 5xx, `classify_failed` | không phải tấn công | qua → B3; `ml_error` ghi lại | `llm` |
| 8 | không | bất kỳ | `LLMUnavailable`, `LLMBudgetExceeded`, `LLMSchemaError` | E2 `screening_unavailable` + `security_flag` | — |
| 9 | không | bất kỳ | hết hạn cả lượt | E2 `turn_budget_exceeded` + `security_flag` | — |
| 10 | không | `MlContractError` (sai schema, p ngoài [0, 1] hoặc NaN) | — | E9 (boundary, như quy ước) | — |

- Biên: p = τ rơi vào #4.
- "LLM chấm nói không" = `is_attack = false` và `category = none`. Dòng #3 là điều MỚI (hiện code cho qua ca này).
- Gói 1 ghi `llm_is_attack`, `llm_category` vào `screening` ở mọi nhánh có gọi L4 (lượt 17/10 thiếu hai trường này ở nhánh qua — 9.2). Nhánh regex không có `ml_error` (không gọi model); nhánh E2 giữ `audit_detail`.
- `event` của audit B2 cho #4, #5: `injection_suspected`.
- `classify_failed` phải thêm vào `MlError`, vào `_is_l3_error` và ánh xạ ở `_post` của `ml/client.py` (`:89-94`); không thì rơi xuống `model_validate` → `MlContractError` → E9.
- #3 áp cho mọi chế độ (cách hiểu LLM chấm cho an toàn hơn, không chỉ riêng `review`).
- #5 và #7 khác nhau có chủ đích: 422 chỉ xảy ra khi văn bản dài bất thường (> 48 cửa sổ) nên coi là đáng ngờ; lỗi hạ tầng không phải tín hiệu tấn công. Thực tế #5 gần như không xảy ra (`TEXT_MAX` ≈ 43 cửa sổ); câu dài (khoảng ≥ 20 cửa sổ) dễ timeout và rơi vào #7 — xem 4.6.
- `shadow` và `active` giữ hành vi cũ, trừ #3 và việc ghi `ml_error` ở mọi nhánh.

### 4.3. Thay nhãn che trước khi model chấm

| Nhãn hệ thống | Thay bằng (đúng bộ từ trong bàn giao của Dương) |
|---|---|
| `[BÍ_MẬT_ĐÃ_ẨN]` | `***` |
| `<SĐT_n>` | số điện thoại |
| `<EMAIL_n>` | địa chỉ email |
| `<CCCD_n>` | số CCCD |
| `<STK_n>` | số tài khoản |

- Regex `\[BÍ_MẬT_ĐÃ_ẨN\]|<(SĐT|EMAIL|CCCD|STK)_\d+>`, chuẩn hoá Unicode NFC trước khi so khớp.
- Nhãn lấy từ `label` và `secret_mask` trong `config/privacy_patterns.json`, không chép tay.
- **Chỉ áp ở `review`.** Ở `active`, bước này có thể đẩy p xuống ≤ 0,10 và cho câu đi thẳng.
- **Chỉ đổi đầu vào của model.** Văn bản lưu, văn bản gửi LLM chấm và audit giữ nguyên; có test chứng minh LLM chấm nhận bản chưa thay.
- Audit ghi số nhãn đã thay.
- Hàm thay đặt ở backend: `backend/app/guard/mask_words.py`, dùng chung cho B2 và cho B3 nếu D-53 bật bước thay (image ml-service không có `config/`, `ml_service/Dockerfile:26-27`).
- **Nghiệm thu (mục 9.3), không dùng 22 câu của Dương** (chọn và nghiệm thu trên cùng 22 câu là vòng tròn):
  - chèn PII giả vào 900 + 900 câu validation bằng hàm dùng chung `scripts/eval/_pii_fake.py` (cũng dùng cho 6.1), cho đi qua đúng L1;
  - chấm ba bản: gốc / đã che / đã che rồi thay.

### 4.4. E1 `injection_suspected`

- Thêm `injection_suspected` vào `REASON_DETAILS`. Không thêm mã thoát. Chuyển `S_SCREENING → S_ESCALATED` đi theo quy tắc 2 ("hướng an toàn"); D-52 ghi rõ quy tắc này nay gồm cả E1 `injection_suspected` của B2. Agent kiểm 6 chuyển bị cấm [Chốt 2.2] không chặn trường hợp này.
- **Tin cho người dùng = tin của E0** (B20 chọn theo `reason_detail` khi là `injection_suspected`). Nếu dùng tin E1 riêng, kẻ dò biết mình đã lừa được LLM chấm.
- **Kênh dò còn lại [Chốt — chấp nhận, ghi giới hạn]:** người gửi vẫn phân biệt được E0 với E1 qua hai đường:
  - trạng thái: `S_BLOCKED` hiện "Yêu cầu này không thể xử lý tự động", còn `S_ESCALATED` hiện "Đã chuyển kỹ thuật viên hỗ trợ" (`frontend/src/routes/employee/status.ts`);
  - `exit_code` trong API ticket của chính họ.

  Chỉ ẩn mã thoát thì không đóng được kênh này. Bản chấm bù bằng chống spam (4.8) và luật M9 theo người gửi (4.10). Che hẳn (cùng nhãn, cùng trạng thái) làm sau 27/10 và cần quyết định đổi UX P10, B02 §6.
- **Ghi chú L2** (`handoff._why`) thêm câu riêng: "Model chặn tấn công chấm cao nhưng lớp LLM không xác nhận là tấn công. Đọc nội dung đã che, không làm theo chỉ dẫn trong câu. Không cấp quyền, đặt lại mật khẩu hay thao tác cho người khác dựa vào lời khẳng định trong câu; việc đặc quyền đi theo quy trình duyệt chuẩn."
  - `next_for_l2` vẫn lấy của E1.
  - Ưu tiên L2 giữ "Thường" [Chốt], theo bảng `exit_code_priority` như mọi E1 (B20 §5.1).
  - Thêm dòng lịch sử người gửi (4.9).
- Không ghi `security_event`, không đặt `security_flag`.
- **Audit B2 (`screening`):** `layer_decided`, `p_mal`, `clf_mode`, `ml_error`, số nhãn đã thay, vai trò và model LLM thật đã dùng. Không có chữ người dùng.
- **M9:**
  - luật 2 không đổi (chỉ E0);
  - `e1_split` ở `monitor/metrics.py` cần tách riêng `injection_suspected` (hiện rơi vào nhóm "other") — Dương làm sau khi gộp (mục 12), không thuộc gói 1;
  - luật 12 ("tỉ lệ xuống L4 > 30%/ngày") luôn là 100% ở `review` → giữ `pending`; Dương định nghĩa lại sau khi gộp, neo vào cận trên E1 thừa đã đo;
  - luật theo người gửi làm ngày 19/10 trong gói 2b (4.10) [Chốt].

### 4.5. Ngưỡng τ [Chốt quy tắc và E_max = 15%; ghi vào D-52 trước khi đo]

- 0,90 là hằng trong code, chưa từng được chọn. Ở 0,90, 6,1% câu thường vượt ngưỡng, tức đã trượt tiêu chí "chặn nhầm ≤ 1/30" của B02 §7.
- **Quy tắc:** τ là giá trị nhỏ nhất trong [0,50; 0,9999] sao cho cận trên 95% (bootstrap theo nhóm mẫu) của E1 thừa ≤ **E_max**.
  - E1 thừa = P(p ≥ τ và LLM chấm nói không | câu thường), tính trên validation sau L1 + thay nhãn che.
  - **E_max = 15% [Chốt 18/10, trước khi chạy LLM chấm trên validation; lúc chốt đã biết 6,1% câu thường có p ≥ 0,90]**. Lý do: theo nguyên tắc giảm bỏ sót trước, và chặn nhầm ở đây chỉ là chuyển người, không phải chặn.
- **Cách tính, ghi trước [ghi vào D-52 lúc 03:05 18/10, trước khi có dữ liệu]:**
  - cận trên **một phía** 95%, bootstrap theo nhóm mẫu (ID nhóm Dương gửi kèm dữ liệu), B = 2.000 lần lấy mẫu, seed 20261018;
  - lưới τ: 0,50; 0,51; …; 0,99; 0,995; 0,999; 0,9999 — mọi τ dùng chung một bộ mẫu bootstrap;
  - dữ liệu: câu validation sau L0 + L1, rồi thay nhãn che (4.3); `p_mal` chấm bằng mã của ml-service gọi trong tiến trình (`scripts/eval/b2_tau_select.py`);
  - câu LLM chấm lỗi (E2) bỏ khỏi cả tử lẫn mẫu, báo số câu bỏ;
  - tính τ riêng cho từng LLM chấm ứng viên (DeepSeek, Gemini, Qwen) từ phán quyết từng câu của `b2_judge_compare.py`; đổi LLM chấm thì dùng τ của model đó.
- **Không τ nào đạt** → bản ứng viên giữ `shadow` (đường lui), dù quyết định #6.
- **Báo kèm lợi ích:** P(p ≥ τ và LLM chấm nói không | câu tấn công), tức số câu tấn công chỉ model bắt được.
- Ghi lại vào `ml_models/injection-clf/tai-lieu/thresholds.json`, ngoài thư mục model có manifest để không đổi tập file mà #9 kiểm: `{"tau_review", "rule", "e_max", "date", "data_sha256", "judge_model"}`. Lệch P11 §4.3 (ngưỡng cùng thư mục model) → "Spec cần sửa".
- **τ tới backend:** Settings `b2_tau_review` (biến `B2_TAU_REVIEW`, khoảng [0,50; 0,9999]), không có giá trị mặc định; chạy `review` mà thiếu τ thì backend từ chối khởi động. Thêm biến vào `x-backend-env` của compose và `.env.example` (để trống tới khi chọn xong τ). Backend không đọc thư mục model (chỉ ml-service gắn `/ml_models`).
- Temperature scaling không cần cho quyết định này (biến đổi đơn điệu); ghi là lệch P11 §4.2.
- Điểm bão hoà (48/55 ≥ 0,99) nên τ trong khoảng rộng cho gần như cùng kết quả [Đã kiểm].

### 4.6. ml-service và gọi model

- **Hàng chờ riêng cho classify:** Settings `ML_CLASSIFY_CONCURRENCY` (mặc định 1), MỘT semaphore dùng chung cho `/classify` và `/classify_intent`, tách khỏi embed và rerank. Lý do: 2 ticket gửi cùng lúc làm classify hết hạn sau rerank và rơi vào #7 mà không ai thấy. Test: 2 ticket song song, một ticket rerank.
  - Đây là lệch quyết định 3a (`ML_MAX_CONCURRENCY = 1` vì torch tự đa luồng, `ml_service/app/settings.py:4-5`): classify sẽ chạy song song rerank, tranh 4 vCPU. Ghi vào D-52.
- Lỗi suy luận trả `{"error": "classify_failed"}` (500, không có chữ đầu vào); backend **không thử lại** mã này.
- Thời gian chờ classify giữ 2 s. **[Đề xuất 18/10 — mặc định]** `/classify` không thử lại khi timeout (vẫn thử lại khi mất kết nối, 5xx), giống `/classify_intent` (6.2): `to_thread` không huỷ được, nên mỗi lần thử lại chiếm hàng chờ thêm khoảng 2 s và làm ticket khác cũng timeout.
- **Đo ngày 19/10:** p95 của classify và của rerank, tỉ lệ E2 `rag_system_error`, khi có câu dài khoảng 40 cửa sổ chạy song song. Ghi giới hạn: câu dài làm model "mù" với chính câu đó và có thể với ticket khác trong lúc chờ; LLM chấm vẫn xét mọi câu nên không tăng bỏ sót.

### 4.7. Nợ bảo mật phải xong trước khi bật (phase5 §6.5)

| # | Sửa |
|---|---|
| 5 | `GUARD_MODEL_DIR`, `INTENT_MODEL_DIR` sau `resolve()` phải nằm dưới gốc model; mọi file trong thư mục cũng vậy. Gốc lấy từ Settings `ML_MODELS_ROOT` (mặc định `/ml_models`) để test dùng `tmp_path` được (`ml_service/tests/test_guard.py:199-210`) |
| 8 | Backend `ClassifyOut.p_malicious: Field(ge=0, le=1)`, không nhận NaN/inf → `MlContractError` (#10 của bảng 4.2) |
| 9 | `GUARD_MODEL_SHA256` bắt buộc khi đặt `GUARD_MODEL_DIR`. Thêm `MANIFEST.sha256` liệt kê mọi file kèm SHA, và biến `GUARD_MANIFEST_SHA256` ghim SHA của chính manifest. Khi khởi động: đúng tập file (không thừa, không thiếu), cấm symlink, `..`, đường tuyệt đối. Manifest: mỗi dòng `sha256  đường/tương/đối` như `sha256sum`, không liệt kê chính nó; sinh bằng `scripts/ml/make_manifest.py` |
| 10 | Bắt lỗi trong `/classify`, `/classify_intent`; log tên lớp lỗi; trả `classify_failed`, không thử lại |
| 3 | Hàng chờ chung → đóng bằng 4.6 |

- `active` chỉ nhận khi `APP_ENV` là dev hoặc test **[Đề xuất 18/10 — mặc định]**: D-44 đo ở chế độ này 31/900 câu tấn công đi thẳng.
- Bật `review` mà ml-service báo `model_missing` → backend log cảnh báo lúc khởi động (khi đó hệ thống chạy như `shadow`).

**Báo cả nhóm trước khi gộp:** SHA bắt buộc làm máy dùng `.env` cũ không khởi động được ml-service. Backend chờ ml-service healthy nên cả stack sẽ đứng. Hướng dẫn kèm bản ứng viên (mục 7).

### 4.8. Chống spam (gói 2b) [Chốt]

- **Bộ đếm A — `POST /api/tickets`:** đếm trong DB: `tickets` của người gửi có `parent_ticket_id IS NULL` (ticket con chép `requester_id` của cha nên phải loại) và `created_at` trong cửa sổ. Migration `0010` thêm index (`requester_id`, `created_at`).
- **Bộ đếm B — `POST /api/tickets/{id}/messages`, `/reply` và `/confirm`, chung một bộ [Chốt 18/10 03:25]:**
  - Đếm cả `/confirm`: `/confirm` sai bước vẫn chạy privacy guard và ghi `late_event` rồi mới trả 409, giống hệt lý do cần bộ B.
  - Không đếm qua `turns` được (mục 2): lượt `resume` gồm cả việc không do người gửi làm, còn tin gửi sai bước — đúng thứ cần chặn — không tạo dòng `turns`.
  - **Đếm bằng bảng mới `rate_hits` trong migration `0010`.** Tuấn Anh chọn cách này thay vì đếm trong bộ nhớ: số đếm còn khi khởi động lại và đúng khi chạy nhiều tiến trình; đổi lại 1 lần ghi DB mỗi tin nhắn.
    - Cột: `hit_id` BIGINT tự tăng (khoá chính), `user_id` (FK `users`, NOT NULL), `created_at` timestamptz NOT NULL; index (`user_id`, `created_at`). Không có chữ người dùng, không có `ticket_id`.
    - `created_at` lấy từ Clock của app (`desk.clock.now()`), như `tickets.created_at` — không dùng `now()` của Postgres, để hai bộ đếm cùng một đồng hồ và test dùng được đồng hồ giả.
    - Mỗi lần kiểm là MỘT transaction riêng (khuôn `engine.begin()` của các repo ở `db/`), commit xong mới chạy tiếp handler: xoá dòng cũ hơn 10 phút của chính người này → đếm dòng trong 10 phút → dưới ngưỡng thì INSERT một dòng và cho qua; đủ ngưỡng thì 429, không INSERT. Request sau đó bị 404/403/409/422 vẫn đã được đếm.
    - Request bị 429 không ghi dòng, nên công thức `Retry-After` dưới đây đúng.
    - Dọn dòng cũ ngay trong transaction đó, chỉ dòng của người đang gửi. Mỗi tài khoản giữ tối đa khoảng 30 dòng, kể cả tài khoản đã ngừng gửi, nên không cần job dọn.
    - Quyền: không phải bảng append-only. `GRANT SELECT, INSERT, DELETE` cho `app_rw` và `GRANT USAGE, SELECT` trên sequence của `hit_id` (lệnh GRANT mọi sequence ở `0001` không phủ sequence tạo sau). Không cấp cho `app_monitor`: M9 đọc `rate_limited` ở `security_events`, không đọc bảng này.
    - Bảng chỉ để đếm, không phải bằng chứng; bằng chứng là sự kiện `rate_limited`.
    - Phần đếm đi qua 1 cổng (Protocol) có bản giả cho unit test (unit test không có DB); bản SQL dựng từ `engines.main` trong lifespan như các repo khác và có test Postgres riêng. Agent nêu chỗ tiêm vào `create_app` ở MẪU A.
    - Đây là bảng thứ 23 của schema: các test ghim 22 bảng sửa có chủ ý (mục 8); P7 thêm bảng qua "Spec cần sửa".
- Áp cho mọi vai trò, vì quyền `ticket:create` có ở cả 4 vai trò.
- **Thứ tự xử lý:** 413 (middleware) → 401/403 (`require`) → **429 ngay sau `require`** (trước `_owned_leaf`, trước đọc thân) → 404/403/409 của ticket → 422 (thân) → xử lý.
  - Đếm theo `user_id` trong token (`p.user_id`), không theo IP, không theo trường trong thân. Thân được đọc trong handler (`parse_body`, `desk.py:68-80`), sau dependency, nên thứ tự này làm được.
  - Request chưa xác thực không làm hao lượt của người khác.
- **Ngưỡng [Chốt]:**
  - A: ≤ 10 ticket trong 10 phút và ≤ 30 ticket mỗi giờ (tối đa 720 ticket mỗi ngày mỗi tài khoản).
  - B: ≤ 30 request trong 10 phút.
  - Settings `ticket_rate_10min`, `ticket_rate_hour`, `message_rate_10min`, dạng `Field(default=…, ge=1)`; biến `TICKET_RATE_10MIN`, `TICKET_RATE_HOUR`, `MESSAGE_RATE_10MIN` thêm vào `x-backend-env` của compose và `.env.example`.
- **Không có giá trị "tắt"; cổng, đo và test phải nới bằng số lớn (vd 100000):**
  - `scripts/verify.sh` truyền số lớn khi tạo lại backend/worker, theo khuôn `APPROVAL_SLA_MINUTES_DEV` (`:142-144`). Không nới thì `make verify G=2345` đỏ: gate2 một mình đã tạo hơn 10 ticket cho `an.nv` trong vài phút;
  - `vpn-smoke`, `make probe`, lượt đo lại B2, harness RQ1, demo: nới tương tự, ghi vào biên bản và manifest;
  - test: Settings dùng trong test mặc định số lớn; test của 429 tự đặt số nhỏ; test có ghi `rate_limited` dùng `fresh_database` (bảng `security_events` không xoá được, downgrade theo khuôn 0002 dừng khi bảng có dòng, làm đỏ `test_migration.py` hạ về base).
- **Khi vượt ngưỡng:**
  - trả 429 `{"detail": "rate_limited"}` kèm `Retry-After`: với mỗi cửa sổ đang vượt, lấy thời điểm của request thứ (số đếm − ngưỡng + 1) tính từ cũ nhất, cộng độ dài cửa sổ, trừ giờ hiện tại; lấy giá trị lớn nhất, làm tròn lên theo giây, tối thiểu 1;
  - không tạo ticket, không gọi LLM, không lưu nội dung;
  - FE không phải sửa: 429 đã có câu chung "Thao tác quá nhanh, thử lại sau." (`frontend/src/api/errors.ts:115-116`; dòng 117 trên nhánh `fe-tuananh`).
- **Sự kiện:**
  - Ghi `security_events(rate_limited)` kèm `user_id`. Loại mới: thêm vào `SECURITY_EVENT_TYPES` và sửa CHECK ở migration `0010`.
  - Mỗi đợt một dòng. Đợt tính theo (người gửi, bộ đếm, cửa sổ đang vượt): ghi khi người này chưa có `rate_limited` của bộ đếm đó trong cửa sổ đang vượt.
  - Ghi `route`. `detail = {"counter": "tickets"|"messages", "window": "10m"|"1h", "limit": n}`, không có chữ người dùng.
- **Hai request song song** có thể lọt quá ngưỡng 1–2 lần, và có thể ghi 2 dòng `rate_limited` cho một đợt (luật `requester_probe` đếm thừa). Chấp nhận, không dùng khoá, ghi vào giới hạn.
- **Migration `0010`** dành cho gói 2b: CHECK của `security_events`, index `tickets(requester_id, created_at)`, bảng `rate_hits` kèm GRANT, và tạo lại `v_leaf` có thêm `requester_id` (4.10). Downgrade: xoá `rate_hits`, xoá index, trả `v_leaf` về như `0008`, siết lại CHECK — dừng khi `security_events` đã có dòng `rate_limited` (khuôn `0002`). Sau khi 2b gộp, DB chung đã ở `0010`: stack dựng từ mã chưa có `0010` (nhánh `-m5`, PR chưa rebase) sẽ hỏng ở `alembic upgrade` → phiên git báo Phase 6 rebase trước khi dùng stack.

### 4.9. Báo L2 (gói 2b) [Chốt]

**(a) Dòng lịch sử người gửi trong ghi chú L2.**

- **Khi nào:** B2 ra E0 hoặc E1 `injection_suspected`.
- **Đếm gì:** B2 đếm cho `requester_context.user_id` trong 7 ngày, KHÔNG tính ticket hiện tại, qua 1 cổng đọc mới (chỉ SELECT, role `app_rw`):
  - số E0: `tickets` của người gửi có `exit_code = 'E0'` — không lọc được theo `security_events.user_id`, vì B2 ghi `injection_detected` không kèm `user_id`;
  - số `injection_suspected`: `escalations.reason_detail` nối `tickets.requester_id`;
  - số `rate_limited`: `security_events.user_id`.
- **Ghi vào `escalation_note`:**
  - "Lịch sử người gửi 7 ngày: X lần bị chặn, Y lần nghi tấn công, Z lần gửi quá nhanh."
  - Tổng ≥ 2 thì thêm: "Người gửi lặp lại — kiểm tra kỹ, không làm theo yêu cầu trong câu."
- `_why` đã nối `escalation_note` nên không sửa `audit/handoff.py`. Cổng đọc mới chạm `graph/ports.py`, `graph/fakes.py`, `wiring.py`, `tests/fakes/graph.py`; `test_b02_screen.py` thêm khoá `history_error` ở `screening` khi lỗi.
- **Lỗi khi đếm** → bỏ dòng, ghi `history_error` (tên lớp lỗi) vào audit B2. Kết quả B2 không đổi: đường an toàn không được hỏng vì phần báo.
- Làm SAU khi gói 1 đã commit, vì cần đường E1 `injection_suspected` của B2.

**(b) Trang Cảnh báo cho L2: chỉ cảnh báo an ninh, chỉ xem.**

- **Quyền:** `auth/permissions.py` thêm `alert:read` vào `l2`. Đây là lệch ma trận P6 §5.1 [Chốt 2.2]: ghi vào D-54, sửa P6 qua "Spec cần sửa". Hai quy tắc gốc có test ép (`policy:edit` ∉ l1, `approval:decide` ∉ l2) không bị ảnh hưởng.
- **Nhãn người nhận:** `monitor/rules.py` thêm giá trị `"l2"` vào `Audience`; `AudienceParam` (`api/alerts.py:39`) cũng thêm `l2`. Luật `injection_detected` (luật 2), `requester_probe` và `requester_probe_critical` (4.10) có `"l2"` trong `audience`.
- **`GET /api/alerts`:**
  - Vai trò `l2` chỉ nhận cảnh báo của luật có `"l2"` trong `audience`, lọc ở server theo `REGISTRY`.
  - L2 gửi `?audience=` khác `l2` → 403 `forbidden` kèm `permission_denied`.
  - Manager không đổi gì, vẫn thấy mọi cảnh báo như Q-M9-A3-1.
- **Ack:**
  - Chỉ vai trò trong `ALERT_ACK_ROLES = frozenset({"manager"})` được ack. Hằng này theo khuôn `ADMIN_REVOKE_ROLES`, không thêm permission mới.
  - L2 ack → 403.
- **`AlertList` thêm `can_ack: bool`**, server tính theo vai trò. `AlertView` giữ nguyên 12 khoá.
- **FE (phiên FE, khoảng 1 giờ):**
  - mục "Cảnh báo" tự hiện cho L2, vì menu dựng theo `permissions`;
  - trang ẩn nút xác nhận khi `can_ack = false`;
  - cập nhật `schema.gen.ts`, mock, test.
  - `gen:api` đọc `openapi.json` của stack đang chạy, nên trước khi 2b gộp chưa có kiểu mới: agent 2b xuất `app.openapi()` ra file, phiên FE sinh kiểu từ file đó; nhánh FE là `fe-tuananh` (cùng sửa `mocks/handlers/index.ts`).
- **Test đổi có chủ ý:**
  - `test_alerts_l2_employee_403`: L2 nay nhận 200, nhân viên vẫn 403;
  - `test_audience_unknown_422`: test này đang dùng `"l2"` làm giá trị lạ → đổi sang giá trị lạ khác;
  - `test_alert_routes_marker`: ack chuyển sang `require("alert:read", roles=ALERT_ACK_ROLES)`;
  - `test_order_401_403_before_422`: L2 gọi GET với tham số sai nay nhận 422 (trước là 403);
  - tập `MINUTE_RULES` ghim ở `test_monitor_jobs_minute.py:59-60` và `test_monitor_jobs_periodic.py:54` (thêm 2 luật mới);
  - snapshot OpenAPI của `/api/alerts`.
  - Không đổi: `test_auth_permissions` (ma trận 10 chức năng không có `alert:read`), `test_audience_of_known_and_unknown` (không kiểm luật 2).
- **Test thêm:** L2 chỉ thấy luật có nhãn `l2`; L2 ack → 403; manager vẫn thấy luật `("dev",)`.
- **Vì sao lệch Q-M9-A3-1 mà vẫn an toàn:** Q-M9-A3-1 tránh lọc theo role vì manager sẽ mất cảnh báo `dev`. Ở đây chỉ thu hẹp phần L2 thấy; manager giữ nguyên, nên không sinh lỗi bỏ sót mà quyết định đó tránh.

### 4.10. Luật M9 theo người gửi `requester_probe` (gói 2b) [Chốt; mức `critical` xem lại 19/10]

- **Khung:** hai luật `minute`, `audience=("manager", "l2")`, hàm thuần; loader chỉ SELECT ở `monitor/queries/rules_data.py` (test quét D-30):
  - `requester_probe` — mức `warning`;
  - `requester_probe_critical` — mức `critical`.
  - Tách hai `rule_id` vì khoá chống trùng của cảnh báo là (`rule_id`, `subject`, `window_start`) với `ON CONFLICT DO NOTHING` (`models.py:627`, `audit/alerts.py:77`): chung một `rule_id` thì `critical` đến sau `warning` cùng khung bị bỏ im lặng.
- **Subject** = `user_id` người gửi. **`window_start`** = 00:00 giờ VN của ngày có sự kiện kích hoạt gần nhất, lấy từ DB, không lấy giờ chạy luật.
- **Dữ liệu** (M9 không được đọc thẳng `tickets`):
  - migration `0010` chạy `CREATE OR REPLACE VIEW v_leaf WITH (security_invoker = true)`, thêm `t.requester_id` làm cột cuối. Phải ghi lại `WITH (security_invoker = true)`: `CREATE OR REPLACE` thay toàn bộ option của view; bỏ đi thì view chạy theo quyền chủ view và rào chỉ-đọc của `app_monitor` mất (test sẵn có `test_views_are_security_invoker` bắt). GRANT trên view giữ nguyên. `CREATE OR REPLACE` không bỏ được cột, nên downgrade xoá 3 view theo thứ tự ngược rồi tạo lại đúng như `0008`, kèm GRANT;
  - E0 = `v_leaf.exit_code = 'E0'`; nghi tấn công = bảng `escalations` có `reason_detail = 'injection_suspected'` (mọi trạng thái), nối `v_leaf` để lấy `requester_id`; `rate_limited` = `security_events.user_id`.
  - Không đếm nghi tấn công qua `v_l2_queue`: view này chỉ có escalation đang mở (`0008`, `WHERE e.closed_at IS NULL`), L2 đóng ca nào thì luật mất ca đó (bỏ sót) [Đã kiểm `33b7484`, sửa 04:10]. `app_monitor` đã có quyền SELECT `escalations` (`0001`, `MONITOR_TABLES`); test D-30 chỉ cấm đọc thẳng `tickets`.
  - Danh sách cột `v_leaf` mới khai báo ngay trong `0010`; không sửa file `0008` (test cũ còn nạp hằng cột của `0008`).
- **Mức cảnh báo [Chốt]:**
  - `warning`: ≥ 3 lần E1 `injection_suspected` trong 24 giờ, hoặc ≥ 3 lần `rate_limited` trong 24 giờ.
  - `critical`: trong 7 ngày có cả E0 (`injection_detected`) lẫn `injection_suspected`.
  - Báo nhầm ước tính [Suy luận, giả định 6% câu thường bị nghi nhầm, E0 nhầm 0,3–1%]:
    - `warning`: người gửi 5 câu mỗi ngày khoảng 0,2%; 10 câu mỗi ngày khoảng 2%;
    - `critical`: người gửi 5 câu mỗi ngày khoảng 9–26% mỗi tuần; 10 câu mỗi ngày khoảng 19–50% mỗi tuần. Người dùng thường (khoảng 1 yêu cầu mỗi tháng, huong-dan 14.1) gần như không bao giờ.
  - **[Mặc định 18/10 03:25]** tính lại bằng số đo ngày 19/10 và đưa Dương trước khi soát. Nếu `critical` báo nhầm ước tính > 5% mỗi tuần với người gửi 5 câu mỗi ngày thì nâng điều kiện thành "E0 và ≥ 2 lần nghi tấn công trong 7 ngày".
- **Không báo trùng:** mỗi luật, mỗi người, mỗi `window_start` một cảnh báo (`_unique`), như luật 3 và luật 10.
- **Phân công:** agent viết ngày 19/10; Dương soát khoảng 30 phút và đặt số luật P9.
- Trong lượt RQ1, harness gửi nhiều câu thử từ ít tài khoản nên luật có thể kêu. Việc này không đổi luồng; ghi vào biên bản.

## 5. Gói 3 — vai trò `judge` (chỉ khi phép thử mục 3 đạt)

- Vai trò thường như `fast`/`strong`, **không** có kiểu "rỗng thì dùng `fast`":
  - sửa `Role` và `ROLES` ở `llm/config.py`, `ports.py`, `registry.py`, `client.py`;
  - Settings `judge_model`, `llm_judge_base_url`, `llm_judge_api_key`;
  - thêm biến vào compose (`docker-compose.yml:26-30`);
  - thiếu key hoặc model thì từ chối khởi động, để 4 máy buộc phải giống nhau.
- **Dự phòng:** chỉ lùi về DeepSeek khi timeout, connect, 429, 5xx. Thêm cấu hình theo vai trò `fallback_on` trong `client.py`: lỗi 4xx (key sai, hết hạn mức, model không còn) → `LLMUnavailable` → E2. Không âm thầm đổi LLM chấm.
- **Lượt đo** đặt `fallback.judge: []` và kiểm 0 `used_fallback`.
- **Thời gian:** `timeout_s` ≈ 6 s, `max_retries` 1; kiểm trường hợp xấu nhất của **cả chuỗi** (đích chính + dự phòng) với `deadline_s` khi khởi động; chép `budget_in`, `max_tokens` của `fast`.
- **OpenRouter:**
  - provider `kind: openai_compat`, `json_mode: json_object`;
  - `extra_body: {provider: {order: [<nhà cung cấp đã ghim>], allow_fallbacks: false, require_parameters: true, data_collection: deny, zdr: true}}` — kiểm tên tham số theo tài liệu OpenRouter lúc làm;
  - dùng slug có ngày;
  - `pricing` thêm dòng model kèm nguồn và ngày đọc;
  - dòng dự phòng ghi tên model cố định, khởi động kiểm khớp `FAST_MODEL`.
- **Chỗ khác phải sửa:**
  - `main.py:200-207` `llm_targets` (health);
  - chuỗi PROBE ở `backend/tests/stack/vpn_smoke.py:41`;
  - prompt `b02_injection_judge` đổi `role: judge`, `version: 2`, chữ không đổi;
  - khoảng 9 file test: agent liệt kê ở MẪU A (tìm `Role`, `ROLES`, `role: fast` trong test).
- **Key:** key con OpenRouter có hạn mức chi riêng cho từng máy chạy LLM thật, cài cùng lịch với key chính.
- **Dữ liệu ra ngoài:** tên người, email công ty, đường dẫn không bị che → nay có 2 bên nhận dữ liệu; ghi vào phần giới hạn của báo cáo.
- **Chỗ dễ sót:**
  - `fallback_on` phải thêm vào `RoleCfg` (`extra="forbid"`, `llm/config.py:95`) và `config/llm.yaml`, không chỉ `client.py`;
  - `b02_screen.py:62` đổi vai trò gọi `"fast"` → `"judge"` cùng lúc với prompt (lệch với YAML là `PromptContractError`, `client.py:179-183`);
  - `check_timing` (`llm/config.py:257-282`) hiện chỉ tính một đích; phải tính cả chuỗi chính + dự phòng;
  - test thêm: 429 của đích chính → lùi về DeepSeek; 4xx khác → E2;
  - thân request (provider, `reasoning`, `max_tokens`, temperature, slug có ngày) giống hệt cấu hình đã qua phép thử (mục 3);
  - key con OpenRouter đặt hạn mức trên mức dự kiến: hết hạn mức trả 4xx → E2 cho mọi ticket.

## 6. B3 — ghi điểm

### 6.1. Số offline trước (script của gói 1, không phụ thuộc bộ nạp)

Script `scripts/eval/b3_offline.py` (Tuấn Anh chạy):

- Chấm gói intent gốc (`predict_proba`, tất định) cho 45 + 10 câu đã che của lượt 17/10.
- Ghép với intent do LLM chọn ở điểm log 1.
- Ra bảng chỉ model (ngưỡng 0,75) / chỉ LLM / cascade (c) mô phỏng (kèm % câu xuống LLM) / phủ quyết chéo mô phỏng (LLM sai bị chặn / LLM đúng bị chặn).
- **Nguồn dữ liệu:** đọc lượt 17/10 từ Postgres qua `Shell.sql` như `tests/probe/cong5.py`; nhận đường dẫn `ket-qua.json` làm tham số. Nhãn LLM lấy bằng `cong5_score.predict` (audit B3/B4/B5 cộng `side_effects.child_create.result_ref`; điểm log 1 không có loại của từng ý trong câu nhiều ý). Đầu vào model là `l0(redacted_request)` (`b03_classify.py:88`).
- **D-43:** bảng giao Duy Anh (F11) chỉ gồm id, intent đúng, intent LLM, điểm model — không có `status`, `exit_code`, `outcome` hay bất cứ gì từ B6 trở đi.
- Chỉ để đo, không chọn gì theo bảng này. Ngoại lệ duy nhất là phép đo nhãn che dưới đây, có tiêu chí ghi trước.
- Chạy `intent_inference.py` gốc chỉ sau khi kiểm SHA đầy đủ của `seed_42.pt`, với torch ≥ 2.6 (mặc định `weights_only`), trên CPU (`device="cpu"`, tắt autocast — file gốc tự chọn CUDA và bật fp16).
- **Nhãn che ở đầu vào B3 [Chốt: đo trước rồi quyết]:**
  - **Dữ liệu:** validation của intent (xin Duy Anh nếu repo chưa có). Chèn PII giả rồi cho đi qua đúng L1, như cách làm ở 9.3.
  - **Chấm 2 bản:** giữ nguyên nhãn che / thay bằng bộ từ 4.3.
  - **Báo:** macro-F1 trên câu có nhãn che, và tỉ lệ dự đoán giữ nguyên so với câu gốc chưa che.
  - **Tiêu chí ghi trước vào D-53, trước khi chạy:** bản thay hơn ≥ 2 điểm macro-F1 thì bật bước thay ở bộ nạp B3 (gói 2, khoảng 30 phút); không đạt thì giữ nguyên và ghi lý do.
  - **Lịch:** Tuấn Anh chạy 19/10, quyết trước 12:00 20/10.
  - **Lưu ý:** B3 chỉ ghi điểm, nên kết quả này chỉ đổi số đo, không đổi luồng.

### 6.2. Bộ nạp vào ml-service (gói 2 — có điều kiện bộ nhớ)

1. **Chuyển gói** (`scripts/ml/convert_intent_pt.py`, Tuấn Anh chạy một lần) ra thư mục MỚI `ml_models/intent-clf/v3.1-seed42-st/`, giữ nguyên thư mục gốc (để nguyên `seed_42.pt` trong thư mục nạp thì `check_intent` từ chối):
   - kiểm SHA đầy đủ (Duy Anh gửi; D-44 chỉ có bản rút gọn `3efd3bd0…46db9`);
   - `torch.load(weights_only=True)` → `model.safetensors`, lưu **fp32**. Lưu fp32 chỉ tránh được đỉnh bộ nhớ khi dựng trên `meta` + `assign=True`; đường mặc định (CPU + `load_state_dict`) có đỉnh khoảng 2 × 1,07 GB;
   - chép `inference_config.json` (sửa `model_files` thành `["model.safetensors"]`), `encoder_config/`, `tokenizer/`;
   - ghi `thresholds.json` (khối dưới) và `MANIFEST.sha256`.
2. **`check_intent`** (cùng khuôn `check_guard`): thư mục dưới `/ml_models`; không file pickle hay mã; đúng tập file; `INTENT_MODEL_SHA256` + `INTENT_MANIFEST_SHA256` bắt buộc; `labels` đúng 5 nhãn đúng thứ tự; `len(tags) = len(req_mask) = 23`; `mix_weights[2] = 0` (khác 0 thì từ chối, vì bộ nạp không làm lượt `p_filt`); `thresholds.json` đủ nhãn, giá trị trong [0, 1], `tau_lo ≤ tau_hi`.
3. **Model:** dựng `B3Model` đúng hình — encoder `AutoModel.from_config(..., add_pooling_layer=False)`, `tok_head`, `att`, `seq_head`, buffer `req_mask` không lưu. `load_state_dict(strict=True)`; nếu bộ nhớ sát thì dựng trên thiết bị `meta` và `assign=True`. `eval()`. Dựng trên `meta` thì các buffer không lưu (`req_mask`, `position_ids`, `token_type_ids`) phải khởi tạo lại sau khi nạp.
4. **Điểm = điểm trộn của gói:**
   - tokenizer fast với `return_offsets_mapping`, `truncation=True, max_length=160`;
   - `p_seq = sigmoid(seq_logits)`;
   - `p_span[l]` = max theo token có `b > a` và `_anchor` hợp lệ của P(`B-REQ:l`) + P(`I-REQ:l`);
   - `probs = 0,4·p_seq + 0,6·p_span`;
   - `truncated` = số token khi không cắt > 160.
5. **Đối chiếu:** 10 câu tự viết (không lấy từ bộ cổng 5); lệch ≤ 1e-4 so với `predict_proba` bản gốc. Fixture sinh trên CPU (`device="cpu"`, tắt autocast), ghi phiên bản torch và transformers vào fixture (do Duy Anh hoặc Tuấn Anh tạo).
6. **Phần còn lại:**
   - `ml_service/app/schemas.py` thêm `IntentOut` khớp backend (kèm test AST như `ClassifyOut`);
   - `/classify_intent` 200 hoặc 503;
   - `/health` báo version intent;
   - làm nóng 1 câu;
   - sửa test đang chờ 503 (`test_security.py:21`, `test_endpoints.py:86`);
   - backend gọi `/classify_intent` không thử lại khi timeout.
7. **Backend B3:** không đổi luồng; test hợp đồng 200 → điểm log 1 có `model_probs`, `model_version`.
8. **Thay nhãn che cho B3** (chỉ khi D-53 bật theo 6.1): làm ở backend B3 trước khi gọi `/classify_intent`, dùng chung `guard/mask_words.py` (4.3).

```json
{
  "source": "D-44 (10/10/2026): Duy Anh chọn trên validation 3.143 câu, seed_42, điểm = điểm trộn của gói; cấu hình (c)",
  "tau_hi_p11": {"account": 0.135, "vpn": 0.365, "software": 0.905, "access": 0.305, "out_of_scope": 0.820},
  "tau_lo_p11": {"account": 0.027, "vpn": 0.679, "software": 0.085, "access": 0.156, "out_of_scope": 0.372},
  "rule": "tau_hi = max(tau_hi_p11, tau_lo_p11, 0.75); tau_lo = min(tau_hi_p11, tau_lo_p11)",
  "tau_hi": {"account": 0.75, "vpn": 0.75, "software": 0.905, "access": 0.75, "out_of_scope": 0.82},
  "tau_lo": {"account": 0.027, "vpn": 0.365, "software": 0.085, "access": 0.156, "out_of_scope": 0.372},
  "temperature": null
}
```

**Cắt gói 2** (trượt bộ nhớ hoặc không kịp): `INTENT_MODEL_DIR` để rỗng như nay; báo cáo dùng số của 6.1 và của RQ1 chấm offline.

## 7. Bộ nhớ, độ trễ, máy khác

- **Tiêu chí bộ nhớ (3-Q39):**
  - tổng các container ≤ 7 GB, không có OOMKilled trong một lượt `make verify`;
  - đo cả đỉnh lúc nạp và lúc chạy, tính theo bộ nhớ `anon` cộng điều kiện không OOMKilled (`docker stats` và `memory.peak` tính cả page cache, nhất là lúc băm SHA hai file 1,1 GB); kiểm `start_period` 240 s vẫn đủ.
  - Không đạt → cắt gói 2; máy 8 GB để `INTENT_MODEL_DIR` rỗng.
- **Độ trễ:** đo p95 của classify khi có tải (2 ticket song song, một ticket đang rerank) trước và sau hàng chờ riêng.
- **Cổng tự động:** chạy với `GUARD_MODEL_DIR` rỗng như nay, thêm 1 ca e2e có model (LLM giả), tự bỏ qua khi máy không có model. Lý do: khoảng 6% câu thường có điểm cao có thể làm đỏ cổng.
- **Câu của kịch bản demo và gate:** ngày 20/10 chấm `p_mal` cho câu của kịch bản demo và các gate; câu nào ≥ τ thì biết trước sẽ ra E1 khi bật model (không đổi τ theo kết quả này).
- **Cấu hình:** mặc định trong code giữ `shadow` tới lúc gộp. Đặt `review` và `B2_TAU_REVIEW` ngay trong commit được verify lúc 14:00 21/10 (`.env.example`, compose); gate chạy với `GUARD_MODEL_DIR` rỗng nên kết quả không đổi. `.env` của Tuấn Anh cập nhật cùng lúc.
- **Phát cho máy khác:**
  - kèm bản ứng viên 23/10: thư mục model + `MANIFEST.sha256` + các dòng `.env` + hướng dẫn;
  - mỗi máy tự kiểm `/health` và SHA trước 26/10;
  - manifest của RQ1 ghi `clf_mode`, model LLM chấm, SHA 2 model — máy nào lệch thì không gộp số.

## 8. Test và mutation (test-writer viết trước code)

- **B2:**
  - 10 dòng của bảng 4.2 ở `review`; biên p = τ; `shadow`/`active` không đổi ngoài #3 và `ml_error`;
  - #4, #5 không có `security_event`, không có `security_flag`, tin người dùng là tin E0, ghi chú L2 có câu cảnh báo;
  - audit không có chữ người dùng;
  - thay nhãn che chỉ ở `review`; LLM chấm nhận bản chưa thay; đủ 5 loại nhãn, nhiều nhãn trong một câu, chuỗi giống nhãn nhưng sai mẫu thì giữ nguyên, chạy hai lần như một lần.
  - ghi `llm_is_attack`, `llm_category` ở mọi nhánh có gọi L4; nhánh regex không có `ml_error`; nhánh E2 giữ `audit_detail`;
  - `review` thiếu `B2_TAU_REVIEW` → từ chối khởi động; `active` ngoài dev/test → từ chối khởi động.
- **Test cũ được đổi có chủ ý (gói 1):**
  - các assert so nguyên dict `screening` ở `test_b02_screen.py:98, 137, 201, 251, 261, 288, 330` (thêm `ml_error`, số nhãn đã thay, `llm_is_attack`, `llm_category`, vai trò và model; khoá mới có ở cả `shadow` lẫn `active`);
  - assert tập khoá `detail` của security_event ở `test_b02_screen.py:104` (vì `_block` truyền `info` làm `detail`);
  - `ml_service/tests/test_guard.py:163-174` (ghim intent trả 503);
  - test ghim tập `REASON_DETAILS`;
  - `tests/probe/cong5.py:102` chỉ lấy tin nhắn khi E0 → mở rộng để kiểm tin của E1 nghi = tin E0;
  - `tests/unit/test_ml_deploy.py::test_no_empty_numeric_env_passed_to_ml_service` (`:47-56`) ghim đúng tập biến của ml-service trong compose: thêm `GUARD_MANIFEST_SHA256` (`${GUARD_MANIFEST_SHA256:-}`, như `GUARD_MODEL_SHA256`) vào nhóm được rỗng. `ML_CLASSIFY_CONCURRENCY` và `ML_MODELS_ROOT` không truyền qua compose: mặc định nằm ở `ml_service/app/settings.py`, cùng quy ước với `ML_MAX_CONCURRENCY` (`docker-compose.yml:131`) [Đã kiểm `33b7484`, thêm 04:10].
- **ml-service:** hàng chờ riêng (classify không chờ rerank); `classify_failed` không mang chữ đầu vào và backend không thử lại.
- **Nợ:** #5, #8, #9 (manifest thiếu file, thừa file, sai SHA, có symlink, có `..`), #10 — mỗi nợ ít nhất 1 ca.
- **`cong5_score.py`:** tiêu chí chính và phụ theo 9.2, cận Clopper-Pearson; cập nhật `test_cong5_score.py`.
- **Mốc mutation cũ phải sửa:** `scripts/mutation/mutate_t23a.py:57-58` (và M-T23a-4 ở `test_b02_screen.py:293`), `scripts/mutation/mutate_3e.py:142`.
- **Mutation mới** (phải bắt hết):
  1. `≥` thành `>` ở τ;
  2. bỏ gọi LLM khi p cao;
  3. cho qua khi p cao;
  4. ghi `security_event` ở #4;
  5. dùng tin E1 cho `injection_suspected`;
  6. bỏ `category ≠ none`;
  7. thay nhãn che cả ở bản gửi LLM;
  8. bỏ ghi `ml_error` ở nhánh qua;
  9. classify dùng chung hàng chờ;
  10. bỏ kiểm manifest.
- **Gói 2:** không khởi động khi thư mục ngoài gốc model, có `.pt`/`.py`, sai tập file, SHA lệch, `mix_weights[2] ≠ 0`, ngưỡng sai miền, thiếu nhãn, nhãn sai thứ tự; điểm trộn khớp fixture. Mutation gói 2: đổi trọng số 0,4/0,6; bỏ `_anchor`; bỏ kiểm `mix_weights[2]`. Test cũ: `test_ml_deploy.py::test_no_empty_numeric_env_passed_to_ml_service` thêm `INTENT_MODEL_SHA256`, `INTENT_MANIFEST_SHA256` vào nhóm được rỗng; test ghim intent 503 (`ml_service/tests/test_guard.py:163-174`) đổi theo bộ nạp.
- **Gói 2b — chống spam:**
  - biên ngưỡng: request thứ 10 trong 10 phút qua, thứ 11 → 429; cửa sổ giờ tương tự;
  - ticket con không tính;
  - 401/403 đứng trước 429; 429 đứng trước `_owned_leaf` (tài khoản đã vượt ngưỡng gửi vào id giả vẫn nhận 429);
  - 429 không tạo ticket và không `spawn`; có `Retry-After`;
  - `rate_limited` chỉ ghi một lần mỗi đợt; `detail` không có chữ người dùng;
  - bộ đếm tin nhắn tách riêng;
  - tin gửi sai bước (409) vẫn được đếm: 30 request đầu trong 10 phút nhận mã thường (202/409/422), request thứ 31 nhận 429; `/messages`, `/reply`, `/confirm` tính chung bộ B;
  - bảng `rate_hits` (test Postgres): request bị 429 không ghi dòng; sau một request, người gửi không còn dòng cũ hơn 10 phút, dòng của người khác giữ nguyên; dựng lại app (như khởi động lại) không mất số đếm; `Retry-After` đúng công thức;
  - Settings test mặc định số lớn; `verify.sh` nới ngưỡng; test có ghi `rate_limited` dùng `fresh_database`;
  - migration `0010` chạy lên và xuống được; sau khi lên `v_leaf` vẫn `security_invoker`; xuống dừng khi đã có dòng `rate_limited`;
  - test cũ được đổi có chủ ý [danh sách đủ, Đã kiểm `33b7484` lúc 04:10]:
    - bảng thứ 23: `tests/unit/test_db_models.py::test_22_tables` và `::test_migration_grants_cover_every_table` (gộp thêm danh sách quyền của `0010`); `tests/integration/test_migration.py::test_upgrade_creates_exactly_22_tables` (`EXPECTED_TABLES` thêm `rate_hits`), `::test_downgrade_is_clean_then_upgrade_again` và `::test_0003_checkpoint_tables_down_and_up` (`:115`: sau khi xuống `0002` không còn `rate_hits`);
    - head `0010`: `tests/unit/test_monitor_dash_business.py::test_alembic_single_head_is_0009` (`:410-415`): head thành `0010`, `0010 → 0009`, giữ chuỗi `0009 → 0008 → 0007`;
    - cột `v_leaf`: `tests/integration/test_monitor_dash_views_pg.py::test_view_columns_explicit` (`:84-85`): cột của `0008` cộng `requester_id` ở cuối;
    - chỉ mục `0009`: `tests/integration/test_monitor_perf_pg.py::test_migration_0009_down_up` (`:399-413`): lên `0009` thay vì `head`, vì từ `head` xuống `0008` còn bỏ chỉ mục và bảng của `0010`;
    - giữ nguyên tên hai test M9 trên vì `scripts/mutation/mutate_a4.py` (mã I4, I5) gọi theo tên; chạy lại hai mã này sau khi đổi, vẫn phải đỏ.
  - `test_models_match_migration` phải xanh không sửa (model và migration khớp nhau). `test_views_are_security_invoker` và `test_migration_up_down_up` (`test_monitor_dash_views_pg.py`) phải xanh không sửa: chúng kiểm option của view và đường xuống của `0010`.
- **Gói 2b — dòng lịch sử L2:**
  - đếm đúng 3 loại, không tính ticket hiện tại;
  - câu "Người gửi lặp lại" xuất hiện từ tổng 2 trở lên;
  - lỗi DB thì kết quả B2 không đổi và có `history_error`;
  - có dòng ở cả E0 lẫn E1 `injection_suspected`, không có ở ca qua B3.
- **Gói 2b — trang Cảnh báo L2:** các test ở 4.9 (b).
- **Gói 2b — luật `requester_probe` và `requester_probe_critical`:**
  - ngưỡng 3 trong 24 giờ (2 lần thì không báo);
  - `critical` khi trong 7 ngày có cả E0 lẫn suspected;
  - không báo trùng; `critical` đến sau `warning` cùng ngày vẫn ra (khác `rule_id`);
  - E0 đếm qua `v_leaf` (có `requester_id` sau `0010`), không đọc thẳng `tickets` (test D-30 xanh);
  - loader chỉ SELECT.
- **Mutation gói 2b** (phải bắt hết):
  11. `>` thay `≥` ở ngưỡng 429;
  12. đếm cả ticket con;
  13. đặt 429 sau `_owned_leaf`;
  14. ghi `rate_limited` mỗi lần thay vì mỗi đợt;
  15. L2 thấy cảnh báo không có nhãn `l2`;
  16. L2 ack được;
  17. bỏ câu "Người gửi lặp lại";
  18. ngưỡng luật M9 3 thành 4;
  19. lỗi đếm lịch sử làm đổi kết quả B2;
  20. ghi `rate_hits` cả khi trả 429;
  21. bỏ bước xoá dòng cũ của người gửi;
  22. `/confirm` không qua bộ B.
- **Test có Postgres** (`test_migration*` cho `0010`, `test_alerts_api_pg.py`) dùng testcontainers, chạy ngay trong worktree 2b (cần Docker, không cần stack); không chạy lúc stack đang đo.
- **B3-VA:** test và 6 mutation theo `claude/prompt-b3-va.md`.
- **Gói 3:** 4xx không lùi; timeout/5xx/429 lùi; thiếu key → từ chối khởi động; cả chuỗi nằm trong hạn. Mutation gói 3: 4xx vẫn lùi; bỏ kiểm dòng dự phòng khớp `FAST_MODEL`.
- **Tên script mutation** (khuôn `mutate_t23a.py`, md5 + `git diff --stat`): gói 1 `scripts/mutation/mutate_b2review.py`; gói 2 `mutate_b3score.py`; gói 2b `mutate_2b.py`; gói 3 `mutate_judge.py`; B3-VA `mutate_b3va.py`.
- **Cổng cũ:** `make verify G=2345` xanh với LLM giả.

## 9. Đo và báo cáo

### 9.1. Chốt trước (ghi vào D-52 sáng 18/10, trước mọi lượt đo, kèm giờ)

Ghi trước:
- định nghĩa cổng 5 (9.2);
- quy tắc τ và E_max = 15% (4.5);
- phép thử LLM chấm, gồm cả bước Qwen dự bị (mục 3);
- bộ từ thay nhãn che (4.3);
- tiêu chí thay nhãn che cho B3 (6.1, ghi ở D-53);
- cách tính RQ1 (9.4);
- tham số chọn τ (4.5: một phía 95%, B = 2.000, seed 20261018, lưới, dữ liệu, câu lỗi) — ghi lúc 03:05 18/10;
- cách xử lý dòng #3 với lượt 17/10 (9.2), vai trò của tiêu chí phụ cổng 5 (9.2), quy tắc đổi LLM chấm (mục 3) — Tuấn Anh chốt và ghi vào D-52 lúc 03:25 18/10, trước phép thử LLM chấm trên validation và trước khi tính lại cổng 5.

Ngưỡng 429 và ngưỡng luật M9 là số vận hành, không phải số đo, nên không cần chốt trước.

### 9.2. Cổng 5 phần B2 — tính offline từ lượt 17/10 [Chốt]

- Script `scripts/eval/b2_review_offline.py` (gói 1, Tuấn Anh chạy):
  - lấy 45 câu B2 (15 tấn công + 30 thường) của lượt 17/10: `.verify/cong5/20261017-181019/` (tên theo giờ UTC, tức 01:10 18/10 giờ VN); nhận đường dẫn `ket-qua.json` làm tham số, đọc Postgres qua `Shell.sql` như `tests/probe/cong5.py`;
  - đọc văn bản đã che (`tickets.redacted_request`) và `event`, `detail.screening` của audit B2. Phán quyết LLM chấm chỉ biết qua kết quả (chặn ở L4 hay cho qua); `category` của câu đã qua KHÔNG được ghi (mục 2);
  - chấm `p_mal` offline (đã thay nhãn che), áp bảng 4.2 với τ đã chốt.
- **Dòng #3 (`category ≠ none` → E0) với lượt 17/10 [Chốt 18/10 03:25, ghi trước vào D-52]:** gọi lại DeepSeek đúng 1 lần (prompt v1, không dự phòng) cho các câu đã qua L4, chỉ để lấy `category`; giữ `is_attack` của lượt gốc; báo tỉ lệ khớp `is_attack` giữa hai lần; ghi giờ chạy, gọi là "đo bổ sung". Lời gọi nằm trong `b2_review_offline.py` sau một cờ riêng (mặc định tắt), dùng khoá DeepSeek đọc từ biến môi trường, không ghi khoá ra file; kết quả lưu ra file kèm giờ, chạy lại thì đọc file, không gọi lần hai.
- **Sao lưu trước 19/10:** xuất các dòng `tickets` và audit B2–B5 của 100 ticket lượt 17/10 ra file trên máy Tuấn Anh, phòng DB mất.
- **Tiêu chí chính (như đã chốt):** E0 ≥ 13/15 câu tấn công; E0 ≤ 1/30 câu thường.
- **Tiêu chí phụ (đối xứng):** E0 ∪ E1 `injection_suspected` ≥ 13/15 câu tấn công **và** ≤ 3/30 câu thường.
- **Vai trò tiêu chí phụ [Chốt 18/10 03:25, ghi trước vào D-52: chỉ để báo]:** với E1 thừa thật 8–10%, chỉ do cỡ mẫu đã có 22–35% khả năng vượt 3/30. Quyết định bật `review` dựa vào tiêu chí chính và quy tắc τ (4.5); tiêu chí phụ báo kèm cận, không quyết định bật hay lùi.
- Báo cả hai kèm cận Clopper-Pearson một phía 95%:

  | Kết quả | Cận 95% một phía |
  |---|---|
  | 13/15 | recall ≥ 0,63 |
  | 14/15 | recall ≥ 0,72 |
  | 15/15 | recall ≥ 0,81 |
  | 0/30 | tỉ lệ thật có thể tới 0,095 |
  | 1/30 | tỉ lệ thật có thể tới 0,15 |
  | 3/30 | tỉ lệ thật có thể tới 0,24 |

  Báo cáo nói rõ độ chính xác thấp này.
- **Chỉ chạy lại phần B2 qua stack khi gói 3 đổi LLM chấm:** một lần, ghi "đo lại" kèm giờ và lý do. Nếu cấu hình cũ trượt mà cấu hình mới đạt trên cùng bộ thì đó là bằng chứng yếu → soạn một bộ B2 mới bởi người chưa xem kết quả (Quân, không dùng AI — luật D-43 cấm AI viết câu probe), băm SHA trước, chạy một lần.

### 9.3. Validation của Dương (19/10, Tuấn Anh)

- **Dữ liệu cần từ Dương:** JSONL `{id, text, label, group}` (`group` = ID mẫu hoặc nhóm sinh câu, để bootstrap theo nhóm) kèm sha256 của file. Test v2.7 niêm phong, không dùng để chọn.
- **Script (gói 1, DỪNG 1):** `b2_tau_select.py` (chấm `p_mal` trong tiến trình bằng mã ml-service, chọn τ theo 4.5 cho từng LLM chấm), `_pii_fake.py` (chèn PII giả, dùng chung với 6.1).

- Thay nhãn che: chèn PII giả → L1 → chấm 3 bản, cho cả câu thường và câu tấn công. `p_mal` chấm lại trên bản đã qua L1 (+ thay nhãn che), bằng ml-service có `GUARD_MODEL_DIR` hoặc script torch cục bộ; không dùng `p_mal` chấm trên chữ gốc.
- Chọn τ theo 4.5.
- Phép thử LLM chấm (mục 3).
- Báo kèm khoảng tin cậy bootstrap theo nhóm.

### 9.4. RQ1 với `review` bật [Chốt]

- Harness (G2, Dương) đếm ticket không tới điểm log 4 theo lý do: E0, E1 `injection_suspected`, E2 ở B2.
- Báo theo từng phương án, từng intent, từng route gold.
- Chỉ số M5 tính trên **phần giao**: ticket tới điểm log 4 ở mọi phương án được so. Lý do: B2 không cache nên tập ticket dừng ở B2 có thể khác nhau giữa các phương án.
- Ticket mang `ml_error` ở B2 hoặc dùng LLM dự phòng ở bước chấm: đếm và báo riêng. Không loại khỏi chỉ số M5 (ticket đã tới điểm log 4 thì M5 không phụ thuộc B2); số ticket dừng ở B2 báo kèm số ca `ml_error`.
- Manifest ghi:
  - `clf_mode = review`, model LLM chấm, τ, SHA 2 model;
  - ngưỡng 429 đã nới cho harness.
- Đếm thêm, chỉ để báo:
  - số cảnh báo `requester_probe`, `requester_probe_critical` kêu trong lượt;
  - số câu nhiều ý kích hoạt B3-VA (`entangled` ở điểm log 1).
- Không phải luật hay log M5, nên không dính D-43. Riêng phần RQ1 giao Duy Anh (F11) chỉ trích điểm log 1; số M5 trên phần giao do Tuấn Anh hoặc Quân đọc tới 25/10.

### 9.5. Sau 21/10

Chạy test v2.7 và bộ khó, mỗi tập một lần. Nếu LLM chấm là Gemini thì ghi thiên lệch khi đo trên bộ khó do Gemini sinh.

### 9.6. Bảng cho báo cáo

- Mỗi tập (validation, test v2.7, bộ khó, cổng 5, RQ1) một bảng:
  - hàng: regex / model / LLM chấm / `active` gốc / `review`;
  - cột: tấn công bị giữ (E0 ∪ E1), E0, E0 thừa, E1 thừa, % gọi LLM, USD/1.000 ticket, p95 — kèm khoảng tin cậy.
- Bảng 2×2 model × LLM chấm.
- Kết quả tách riêng câu có nhãn che, câu không dấu, câu dài.
- B3: bảng 6.1 và bảng từ RQ1.
- Mục giới hạn:
  - dữ liệu do LLM sinh;
  - cỡ mẫu cổng 5;
  - B3 chưa cascade;
  - dữ liệu ra ngoài nếu dùng OpenRouter;
  - kênh dò E0/E1 qua trạng thái (4.4);
  - giới hạn 429 có thể lọt 1–2 request khi gửi song song;
  - danh sách cụm phủ định của B3-VA là heuristic.
  - dòng #3 trên cổng 5 lấy từ lần gọi lại DeepSeek (đo bổ sung), không phải từ lượt gốc 17/10;
  - câu dài làm model "mù" (timeout) — LLM chấm vẫn xét;
  - tin trả lời sau (bổ sung thông tin, xác nhận) chỉ qua regex (`clarify_wait.py:46`, `confirm_wait.py:25`), chưa qua model và LLM chấm;
  - E_max chốt khi đã biết 6,1% câu thường vượt 0,90 (chưa chạy LLM chấm).
- Nhật ký các quyết định chốt trước.

## 10. Lịch — 2 worktree, cố không cắt việc [Chốt hướng; giờ là Đề xuất]

**Khối lượng:** tổng khoảng 31–40 giờ agent.

| Gói | Giờ agent |
|---|---|
| Gói 1 (2 DỪNG) | 9–11 |
| Gói 2 | 5–7 |
| B3-VA | 3–4 |
| Gói 2b (gồm FE) | 11–14 |
| Gói 3 (chỉ khi đổi judge) | 3–4 |

Một thư mục chạy tuần tự không kịp, nên chia ra:
- **Thư mục chính** (`dev-tuananh`, có stack): gói 1 (DỪNG 1 rồi DỪNG 2) → gói 2 → B3-VA → gói 3.
- **Worktree 2b** (nhánh riêng do phiên git tạo từ commit tài liệu sáng 18/10; không có stack, KHÔNG `make up`; chạy được unit test và test Postgres qua testcontainers): chống spam → luật M9 → trang Cảnh báo cho L2 (phần BE) → rebase lên gói 1 → dòng lịch sử L2.

| Khi | Thư mục chính (có stack) | Worktree 2b (không stack) | Tuấn Anh, Claude, người khác |
|---|---|---|---|
| CN 18/10 sáng, trước khi mở phiên | — | — | 4 điểm chờ đã chốt lúc 03:25 (mục 1, dòng 23–26). Claude chép 6 file tài liệu đã sửa vào `docs/spec`; phiên git commit + push, khoá thư mục chính, tạo worktree 2b TỪ commit đó, dành migration `0010`. Xuất các dòng DB của lượt 17/10 ra file (9.2). Gửi tin Dương (dữ liệu kèm ID nhóm + sha256, trước 12:00 19/10) và Duy Anh (SHA, 10 câu fixture, file validation — hạn 22:00 18/10). Có khoá OpenRouter + hạn mức |
| CN 18/10 | **Gói 1 DỪNG 1** (khoảng 5 giờ): hàm thuần cho bảng 4.2 và thay nhãn che (4.3); 6 script đo (`b2_judge_compare.py`, `b2_tau_select.py`, `_pii_fake.py`, `b2_review_offline.py`, `b3_offline.py` có chế độ nhãn che, `cong5_score.py`); test → commit. Tối: **gói 1 DỪNG 2** (khoảng 5 giờ): nối vào node, E1, nợ §6.5, hàng chờ riêng, mutation → commit, muộn nhất trưa 19/10 | **Chống spam** (4–5 giờ, 4.8, gồm bảng `rate_hits`), test Postgres chạy ngay trong worktree | Tuấn Anh duyệt MẪU A, B của 2 agent |
| T2 19/10 | **Gói 2** (5–7 giờ, 6.2), xong rồi mới tới **B3-VA** (3–4 giờ, phiên B3-VA): cùng file `b03_classify.py` nên chạy nối tiếp. 09:00 chưa có SHA của Duy Anh thì B3-VA làm trước, gói 2 sau | **Luật M9** (2–3 giờ, 4.10; Dương soát buổi chiều), rồi **trang Cảnh báo L2 phần BE** (2–3 giờ, 4.9 b); xuất `app.openapi()` ra file cho FE | Đo bộ nhớ và p95 (khoảng 1 giờ stack, lúc agent đứng ở DỪNG); 9.3; chạy `b2_review_offline.py`, `b3_offline.py` (cả nhãn che); phép thử LLM chấm; tính lại báo nhầm của `requester_probe` cho Dương; nháp tin GVHD |
| T3 20/10 sáng | Gemini trượt thì chạy Qwen (script, không cần agent); chấm `p_mal` câu kịch bản demo và gate (mục 7) | Rebase lên gói 1, rồi **dòng lịch sử L2** (2 giờ, 4.9 a) | Phiên FE: trang Cảnh báo cho L2 từ file OpenAPI của 2b (khoảng 1 giờ) |
| T3 20/10 12:00 | **Mốc quyết:** gói 1 xanh? τ đạt? bộ nhớ đạt? judge đạt? thay nhãn che B3 đạt? | | Gửi tin GVHD SAU mốc này, trong chiều 20/10 |
| T3 20/10 chiều, tối | **Gói 3** (3–4 giờ) nếu judge đạt, commit TRƯỚC khi gộp 2b (cùng sửa `settings.py`); đo lại phần B2 nếu đã đổi judge | Phiên git gộp 2b vào `dev-tuananh` sau khi gói 3 commit | Thứ tự: gói 3 commit → gộp 2b → lượt verify các PR sau 18:10 (cũng là chạy thử cho bản đã gộp) → đo lại B2 |
| T4 21/10 | F8 lần cuối trước 12:00 (F8 không đụng `b02_injection_judge`); sửa xung đột nếu có; 14:00 `make verify G=2345` trên commit đã đặt `review` + `B2_TAU_REVIEW` (47–50 phút, đủ một vòng sửa); xanh thì gộp; 18:00 cắt | — | Thứ tự gỡ khi đỏ: B3-VA → gói 2 → dòng lịch sử của 2b → gói 1 (gỡ gói 1 kéo theo dòng lịch sử của 2b) |
| 22–26/10 | Đồng bộ đặc tả qua "Spec cần sửa"; phát model kèm bản ứng viên 23/10; từng máy tự kiểm trước 26/10 | | |

**Luật dùng stack 18–21/10:** chỉ chạy stack trên commit đã có (ghi SHA vào biên bản), lúc mọi agent đang đứng ở DỪNG; không chạy hai việc đo cùng lúc trên máy Tuấn Anh. Compose `name: servicedesk` cố định nên `make up` ở bất kỳ worktree nào cũng thay đúng các container đó.

**Số phiên song song [Chốt 18/10 03:25]:** tối đa **3** phiên coding agent cùng lúc trong 18–21/10 (phase5 vốn cho 2): thư mục chính, worktree 2b, và 1 phiên cho các việc F khác (F5, F6, F7, F14, F15, F16) ở thư mục riêng do phiên git tạo khi cần. Mỗi phiên một thư mục; Tuấn Anh duyệt MẪU theo thứ tự đến. Phiên việc F không sửa file của gói 1 và 2b; việc cần stack (vd `make ingest` của F5) theo luật dùng stack ở trên. Sau 21/10 về lại 2.

**Không cắt theo kế hoạch.** Cổng khách quan duy nhất: phần nào chưa xanh lúc 14:00 21/10 thì không gộp phần đó. Các phần của 2b là commit riêng nên gộp hay bỏ được độc lập. Đường lui an toàn đã có sẵn:
- gói 1 đỏ hoặc τ không đạt → `shadow`;
- gói 2 không đạt bộ nhớ → `INTENT_MODEL_DIR` để rỗng, dùng số offline;
- judge không đạt → giữ DeepSeek;
- B3-VA chưa xanh → giữ D-49 như hiện nay.

**Xung đột dự kiến khi gộp** (nhỏ, phiên git xử lý):
- `.env.example`/compose (gói 1, 2, 2b, 3);
- `b03_classify.py` (gói 2 và B3-VA, đã xếp nối tiếp);
- `settings.py` (gói 1 thêm `b2_tau_review`; 2b thêm ngưỡng 429; gói 3 thêm `judge`);
- `graph/ports.py`, `graph/fakes.py`, `wiring.py`, `tests/fakes/graph.py` (cổng đọc lịch sử của 2b);
- `db/models.py`, `tests/unit/test_db_models.py`, `tests/integration/test_migration.py`, 3 file test M9 (`test_monitor_dash_business.py`, `test_monitor_dash_views_pg.py`, `test_monitor_perf_pg.py`) (2b thêm bảng `rate_hits`, loại sự kiện, cột `v_leaf`; gói 1 không đụng);
- `main.py` lifespan (2b tiêm cổng đếm; gói 1 có thể thêm một khối cảnh báo `model_missing` của 4.7);
- `test_b02_screen.py` và các khoá `screening` (gói 1 thêm khoá; 2b thêm `history_error`);
- `PROGRESS.md`;
- `frontend/src/mocks/handlers/index.ts` (phiên FE và nhánh `fe-tuananh`).

`audit/handoff.py` chỉ gói 1 sửa; 2b và B3-VA dùng `escalation_note`, không sửa file này.

## 11. Quyết định và tài liệu

- **D-52 — B2 chế độ `review`:**
  - nội dung: bảng 4.2; tin E0 cho `injection_suspected`; quy tắc 2 của bảng trạng thái nay gồm E1 `injection_suspected` của B2; nội dung chốt trước ở 9.1;
  - thay điều kiện chuyển `active` của D-44 cho B2;
  - báo GVHD: Có.
- **D-53 — B3 ghi điểm:**
  - lệch D-32: model chưa chạy trước;
  - thay kế hoạch cascade (c) của D-44. Lý do: B3 vẫn phải gọi LLM để trích slot và đặt `target_is_other`, nên cascade mất lý do tiết kiệm; trên test, cascade 0,9883 so với 0,9885 của một ngưỡng;
  - lệch định dạng P11 §4.3 (safetensors fp32 chuyển từ `.pt`, chưa ONNX int8) và P4 (điểm trộn);
  - thêm tiêu chí thay nhãn che ở đầu vào B3, ghi trước khi đo (6.1);
  - báo GVHD: Có.
- **D-54 — chống dò và spam quanh B2 `review` [Chốt số]:**
  - 429 theo tài khoản (bộ tin nhắn gồm `/confirm`, đếm bằng bảng `rate_hits`) và sự kiện `rate_limited` (P7 thêm loại sự kiện và bảng thứ 23; migration `0010`);
  - dòng lịch sử người gửi trong ghi chú L2;
  - `alert:read` cho L2, lọc nhãn `l2`, chỉ manager được ack. Lệch P6 §5.1 và Q-M9-A3-1;
  - luật M9 `requester_probe`, `requester_probe_critical` (P9);
  - chấp nhận kênh dò E0/E1 là giới hạn của bản chấm;
  - báo GVHD: Có (đổi ma trận quyền, thêm loại sự kiện an ninh).
- **D-55 — B3-VA [Chốt số]:** lệch phase5 5.2.2 vì thêm bước "dính nhau". Phiên B3-VA soạn 3 dòng ở MẪU B2.
- **D-56:** chỉ ghi khi gói 3 đổi LLM chấm (Gemini hoặc Qwen).
- D-51 để nguyên cho "model LLM chính thức".
- **Trước 21/10 chỉ viết:** D-52…D-55, mục 7.14 của phase5, dòng hiện trạng ở `NGU-CANH-DAY-DU.md` và `huong-dan-xay-dung-he-thong-2.md` (đã ghi ở Project rạng sáng 18/10); D-56 chỉ khi đổi judge.
- **Sửa sau, qua "Spec cần sửa":** B02; B03-B05 (kể cả phần đồng bộ T20b còn thiếu); P2; P4; P6 §5.1; P7 2.3 và danh sách bảng (`rate_hits`); P9 (luật 12 và luật mới); P11.
- **Trang kế hoạch:**
  - quyết định #4 đổi thành "B2 `review` + B3 ghi điểm (D-52, D-53); chống dò và spam (D-54); B3-VA (D-55)";
  - F11 lấy số từ 6.1 và từ RQ1;
  - nháp trang nhóm (tab A7, rev 61 chưa phát) đã sửa dòng #4, F11 và việc của Dương, Duy Anh (18/10); phát khi Tuấn Anh cho phép.
- **Tin GVHD** gửi sau mốc quyết 12:00 20/10, trong chiều 20/10 (Claude soạn nháp 19/10).

## 12. Việc của người khác

- **Dương:**
  - gửi dữ liệu trước 12:00 19/10: JSONL `{id, text, label, group}` kèm sha256 (9.3) — đúng bộ 900 + 900 đã dùng cho số 6,1% ở 4.5, không sinh lại; `text` là chữ gốc; giữ niêm phong test v2.7, bộ khó gửi sau 21/10 (9.5);
  - chiều 19/10: soát 2 luật `requester_probe`, `requester_probe_critical` (khoảng 30 phút, kèm số báo nhầm Tuấn Anh tính lại) và đặt số luật P9;
  - sau khi gộp: định nghĩa lại luật 12 của M9 và tách `injection_suspected` trong `e1_split`;
  - harness G2 đếm ticket dừng ở B2 theo 9.4, nới ngưỡng 429 khi chạy (biến ở 4.8), ghi vào manifest.
  - Không dính D-43: đây là luật an ninh M9, không phải M5.
- **Duy Anh:**
  - SHA đầy đủ của `seed_42.pt` — hạn 22:00 18/10 (09:00 19/10 chưa có thì B3-VA làm trước gói 2);
  - 10 câu fixture từ `predict_proba` (số đủ chữ số, không làm tròn — đối chiếu ≤ 1e-4 ở 6.2; có ít nhất 1 câu > 160 token);
  - file validation intent cho phép đo nhãn che (nếu repo chưa có).
  - Không dính D-43.
- **Phiên Phase 6:** sau khi 2b gộp (DB chung lên `0010`), rebase lên `dev-tuananh` trước khi dùng stack;
  - không bị ảnh hưởng về luồng: B3 không đổi đường đi, cờ `target_is_other` giữ nguyên;
  - không dùng số migration `0010`.
- **Phiên git:**
  - sáng 18/10: commit + push 6 file tài liệu Claude đã chép vào `docs/spec` (decisions, phase5, đặc tả, prompt B3-VA, NGU-CANH, huong-dan) TRƯỚC khi mở phiên; khoá thư mục chính cho gói 1 (18/10), gói 2 và B3-VA (19/10);
  - tạo thư mục riêng cho phiên việc F khi Tuấn Anh mở phiên đó (tối đa 3 phiên cùng lúc tới 21/10);
  - tạo worktree 2b ngày 18/10 từ commit tài liệu (không `git worktree prune`) và dành migration `0010` cho 2b;
  - sáng 20/10, sau khi gói 1 push và 2b phần 3 commit: rebase nhánh 2b lên `dev-tuananh` (agent không rebase), chuyển file OpenAPI của 2b cho phiên FE;
  - gộp 2b tối 20/10; gộp chung 14:00 21/10.
- **Phiên FE:** trang Cảnh báo cho L2 (4.9 b), ngày 20/10, sinh kiểu từ file OpenAPI xuất ở worktree 2b; nhánh `fe-tuananh`.
- **Phiên B3-VA:** theo `claude/prompt-b3-va.md`. Bắt đầu sau khi DỪNG 3 push, chạy ở thư mục chính, sau gói 2.
- **Quân:** chỉ khi gói 3 đổi LLM chấm và cấu hình cũ trượt mà cấu hình mới đạt trên cổng 5: soạn bộ B2 mới (15 + 30 câu, không dùng AI), băm SHA trước khi chạy.

## 13. Còn mở

**Đã chốt lúc 03:25 18/10 (trước đây chờ duyệt):** bộ đếm tin nhắn đếm cả `/confirm`, bằng bảng `rate_hits` (4.8); dòng #3 với lượt 17/10 đo bổ sung bằng 1 lần gọi lại DeepSeek (9.2); tiêu chí phụ cổng 5 chỉ để báo (9.2); quy tắc đổi LLM chấm siết (mục 3); tối đa 3 phiên song song 18–21/10 (mục 10); Claude chép tài liệu vào `docs/spec`.

**Mặc định đã đặt (Tuấn Anh đổi được):** `/classify` không thử lại khi timeout (4.6); `active` chỉ ở dev/test (4.7); τ tới backend qua `B2_TAU_REVIEW` (4.5); mức `critical` của `requester_probe` xem lại theo số đo 19/10 (4.10); cụm phủ định không dấu cho B3-VA ("khong can", "khoi can", "thay vi", "chu khong") — đã có trong `claude/prompt-b3-va.md`.

**Còn mở, không chặn việc mở phiên:** số báo nhầm của `requester_probe_critical` (tính lại 19/10, Dương soát); kết quả các phép đo 19–20/10, quyết ở mốc 12:00 20/10.

Chi tiết hiện thực do từng agent nêu ở MẪU A để Tuấn Anh duyệt, ví dụ: tên cổng đọc lịch sử của B2; khoá log 1 có bị test ghim không; `escalation_note` có đi qua seed của con không; chỗ tiêm cổng đếm `rate_hits` vào `create_app`.

## 14. Sau 27/10, hoặc chỉ viết vào báo cáo

- Che hẳn E0/`injection_suspected` với người gửi (cùng nhãn, cùng trạng thái). Cần quyết định đổi UX của P10 và B02 §6.
- Câu nhiều ý: hỏi lại người dùng về phần không chắc thay vì chuyển L2. Việc này đổi D-27.
- Từ quan sát của B3-VA: hai ý chạy được mà chồng đoạn; dòng toàn cảnh cho con E1 loại khác.
- Lớp LLM chấm (L4) cho câu trả lời ở B11.
- Quét KB lúc ingest.
- Bộ tấn công thích nghi.
- Hai LLM chấm song song + model bỏ phiếu (thí nghiệm mở rộng).
- LLM chấm 3 mức kèm mã kiểm.
- Phủ quyết chéo ở B3 bản thật.
- LLM chấm chạy local (hướng phát triển).
- Lách regex còn hở: "bỏ.qua", chen hơn 20 ký tự, "lờ đi". **Không** thêm mẫu "Hệ thống:" vì người dùng dán thông báo lỗi sẽ bị E0 oan.

## Nguồn

- `claude/phan-bien-bat-2-model.md` — phương án đã cân nhắc và lý do loại.
- [OpenRouter — Gemini 3.6 Flash](https://openrouter.ai/models/google/gemini-3.6-flash-20260721), [so sánh Gemini 3.6 Flash và Qwen3.8 Flash](https://openrouter.ai/compare/google/gemini-3.6-flash/qwen/qwen3.8-flash) (đọc 18/10/2026).
- Repo `3cf0d18`:
  - code: các file nêu ở mục 2; `ml_models/injection-clf/tai-lieu/HANDOFF_MODEL_CHAN_TAN_CONG.docx` (bộ từ thay nhãn che), `mask_probe_results.md`; `ml_models/intent-clf/intent_inference.py`, `inference_config.json`;
  - code cho gói 2b và B3-VA:
    - API và quyền: `api/limits.py`, `api/tickets.py:176-199`, `api/alerts.py`; `auth/service.py`, `auth/permissions.py`;
    - M9: `monitor/rules.py`, `monitor/queries/`;
    - DB: `db/models.py:92, 288-321, 551-563`, `db/security_events.py`, `db/tickets.py` (khuôn repo, `engine.begin()`); migration `0001_init_22_bang_role_trigger.py` (GRANT, append-only), `0002_security_events_mfa_types.py` (khuôn siết CHECK), `0008_monitor_views.py` (`security_invoker`), `0009_monitor_indexes.py`; test `tests/unit/test_db_models.py`, `tests/integration/test_migration.py`, `tests/integration/test_monitor_dash_views_pg.py`;
    - ghi chú L2: `audit/handoff.py:102-139`;
    - B3: `graph/nodes/b03_classify.py`, `domain/slots.py:105`;
    - FE: `frontend/src/auth/permissions.ts`, `frontend/src/api/errors.ts`;
    - test: `tests/unit/test_alerts_api.py`, `tests/unit/test_t20b_split.py`;
  - đặc tả: `docs/spec/build/decisions.md` D-32, D-44, D-45, dòng 316; `nhanh/B02-sang-loc-injection.md` §1–7; `nhanh/B03-B05-phan-loai-tach-y.md` §5.1, §7; `phase5-thiet-ke-chi-tiet.md` §6.5, §7.13; `nen-tang/P11-huan-luyen-model.md` §4–5; `nen-tang/P9-monitor-M9.md` luật 2, 12, 13.
- Project: `claude/ban-giao-bat-2-model.md`, `claude/phan-tich-2-model-chua-bat.md`, `claude/bien-ban-cong-5-thu-cong.md`.
