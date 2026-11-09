# B3–B5 — Phân loại intent, kiểm tra phạm vi, tách yêu cầu nhiều ý

> **Tầng:** T2 · **Module:** M1 · **Objective:** 1 · **Phase:** 3 (VPN), 5 (đủ 4 loại + tách ý)
> **Trạng thái vào:** `S_CLASSIFYING` · **Ra:** `S_DIAGNOSING` | `S_ESCALATED` (E1; E2 khi vượt `MAX_LOOPS`) | tạo ticket con (cha chờ tổng hợp)
> **Bản vá v1.2:** D-17 (cha đối soát con từ DB), D-18 (tạo/submit con idempotent), D-27 (tách ca confidence thấp khỏi E1 thật)

---

## 0. Ngữ cảnh nạp sẵn

*File này **tự đứng được**: mục 0 chứa toàn bộ ngữ cảnh đã chốt mà nhánh cần (khối chung + đặc tả gốc + kịch bản test + bất biến), mục 13–15 hướng dẫn mở rộng, sửa lỗi và ghi lịch sử. Giao file này cho người hoặc coding agent là đủ để sửa, xây hoặc tách riêng phần này mà không cần mở tài liệu khác. Các tham chiếu tới file khác trong thân bài chỉ để đọc sâu thêm.*

### 0.1. Khối ngữ cảnh chung của dự án

*Khối này giống hệt nhau ở mọi file trong `build/` (phiên bản khối: **CTX-1.1, 25/09/2026**). Khi tài liệu gốc thay đổi, cập nhật khối này ở tất cả các file cùng lúc và tăng số phiên bản.*

**Đề tài:** AI Agent tự động hóa hỗ trợ IT Service Desk cấp 1 với cơ chế Human-in-the-Loop (EN: *Agentic AI for Level-1 IT Service Desk Automation with Human-in-the-Loop*). Đồ án tốt nghiệp, ĐH FPT, chuyên ngành AI, nhóm 4 người.

**Ba mục tiêu đã chốt:**

| Mục tiêu | Trọng số | Nội dung |
|---|---|---|
| Obj 1 | 50–60% | Agent xử lý yêu cầu L1: M1 phân loại + slot, M2 RAG, M3 tool + chẩn đoán chủ động, M4 điều phối, cùng lớp kỹ thuật agent (trace, bộ nhớ, harness, LLMOps, riêng tư) |
| Obj 2 | 30–40% | Human-in-the-Loop: M5 quyết định khi nào cần người (đóng góp chính), M6 phê duyệt, M7 audit |
| Obj 3 | 0–20% | Đánh giá: bộ kịch bản, so sánh 4 phương án, ablation (M8) |

**Nguyên tắc dự án:**

- Objective quyết định xây gì → Phase quyết định xây khi nào → RQ chỉ quyết định đo gì.
- Luôn phân biệt **[Chốt] / [Suy luận] / [Đề xuất]**.
- Ưu tiên thay đổi nhỏ, kiểm chứng được.
- Với an toàn: **giảm False Negative trước**, giảm escalate thừa sau.

**Bốn nguyên tắc thiết kế [Chốt]:**

1. An toàn ưu tiên hơn tự động hóa.
2. Mọi quyết định giải thích được.
3. Luật cứng có quyền phủ quyết LLM.
4. Chủ động chẩn đoán trước khi hỏi.

**Phạm vi:**

- 4 loại yêu cầu: `account`, `vpn`, `software`, `access`.
- Tiếng Việt.
- Hệ thống ngoài giả lập bằng mock FastAPI.

**4 vai trò [Chốt 2.2]:**

| Vai trò | Quyền chính |
|---|---|
| Nhân viên | Gửi yêu cầu, xem ticket của mình |
| L1 | Duyệt, ghi đè, nhận escalate |
| Trưởng BP IT | Sửa policy, dashboard/audit toàn bộ, cập nhật KB |
| L2 | Nhận escalate, cập nhật KB, **không duyệt** |

L1 không được sửa policy.

**Luồng 20 bước [Chốt]:**

B1 xác thực → B2 chặn injection (E0) → B3 intent → B4 trong phạm vi? (E1) → B5 tách ý → B6 chẩn đoán chủ động → B7 lỗi hệ thống ≠ rỗng (E2) → B8 tra KB (E2) → B9 có căn cứ? (E3) → B10 chỉ cần trả lời? → B11 đủ thông tin? (E4) → B12 luật → B13 quyết định theo luật → B14 LLM hiệu chỉnh (E5) → B15 xung đột lợi ích + `action_plan_hash` → B16 chờ duyệt (E6) → B17 thực thi (E7/E5) → B18 thông báo → B19 xác nhận (E8) → B20 audit + `close_reason`.

Mọi node có lớp bọc lỗi chưa lường trước → E9.

**14 trạng thái:**

- Xử lý: `S_NEW`, `S_SCREENING`, `S_CLASSIFYING`, `S_DIAGNOSING`, `S_RETRIEVING`, `S_ASSESSING`, `S_EXECUTING`.
- Chờ người: `S_CLARIFYING` (24h), `S_PENDING_APPROVAL` (30 phút), `S_CONFIRMING` (48h).
- Kết thúc hoặc chuyển giao: `S_ESCALATED`, `S_RESOLVED`, `S_REJECTED`, `S_BLOCKED`.

**Mã thoát và ưu tiên hàng đợi L2:**

| Mã | Tình huống | Ưu tiên |
|---|---|---|
| E0 | Prompt injection | An ninh |
| E1 | Ngoài phạm vi | Thường |
| E2 | Tool/RAG lỗi hệ thống sau retry | Hạ tầng |
| E3 | Không có căn cứ (`NO_EVIDENCE`) | Thường, kèm cờ bổ sung KB |
| E4 | Hỏi 3 lần vẫn thiếu | Thường |
| E5 | Rủi ro cao / `deny` / hash lệch | Cao |
| E6 | Hết hạn duyệt (fail-safe) | Có SLA |
| E7 | Thực thi lỗi | Rất cao |
| E8 | Người dùng báo chưa xong | Thường |
| E9 | Lỗi chưa lường trước | Ngang E2 |

**`block_reason`:** `invalid_credentials` (không phải sự cố an ninh), `repeated_auth_failure`, `injection_detected`.

**`close_reason` (8 giá trị):** `resolved_user_confirmed`, `resolved_auto_timeout_48h`, `resolved_after_escalation`, `resolved_after_deny_review`, `rejected_by_approver`, `blocked_invalid_credentials`, `blocked_repeated_auth_failure`, `blocked_injection_detected`.

**8 điểm log bắt buộc:**

| Điểm | Bước | Nội dung |
|---|---|---|
| 1 | B3 | intent |
| 2 | B6 | chẩn đoán |
| 3 | B8 | tra cứu |
| 4 | B12–14 | quyết định rủi ro — quan trọng nhất |
| 5 | B15 | vào hàng đợi duyệt |
| 6 | B16 | kết quả duyệt |
| 7 | B17 | thực thi |
| 8 | B20 | kết thúc |

**Hằng số trong `policy.json`:**

| Hằng số | Giá trị |
|---|---|
| `MAX_LOOPS` | 5 |
| `MAX_CLARIFICATION_TURNS` | 3 |
| `TOOL_RETRY` | 2 (backoff 1s, 2s) |
| `MAX_AUTH_FAILURES` | 5 trong 10 phút |
| `SLA_MINUTES` | 30 |
| `THRESHOLD_LOW` / `THRESHOLD_HIGH` | 0,25 / 0,75 (sẽ chọn lại trên tập calibration) |
| `RETRIEVAL_THRESHOLD` | 0,6 |
| `CLARIFY_TIMEOUT` | 24h |
| `CONFIRM_TIMEOUT` | 48h |

**Công nghệ [Chốt + Đề xuất]:**

- Python 3.12, FastAPI, Pydantic v2.
- LangGraph + checkpoint Postgres.
- PostgreSQL 16 + SQLAlchemy 2 + Alembic.
- Qdrant + bge-m3 + bge-reranker-v2-m3 + BM25/RRF.
- LLM gateway fast/strong, API hoặc local.
- httpx, APScheduler.
- React + Vite + TS.
- Docker Compose, Caddy, GitHub Actions.
- Kiến trúc modular monolith + ml-service + mock (D-13).
- DB 22 bảng (P7).

**Bất biến toàn cục (không nhánh nào được phá):**

1. M5 không bao giờ đọc câu người dùng. `policy_engine.evaluate(action, ctx)` chỉ nhận hai tham số đó.
2. B17 là điểm ghi duy nhất ra hệ thống ngoài; chỉ `svc_executor` có credential ghi.
3. Mọi đổi trạng thái đi qua `goto()` (kiểm chuyển hợp lệ + ghi audit).
4. Mọi nhánh kết thúc ở B20.
5. Hết hạn duyệt không bao giờ tự thực thi.
6. Lỗi hệ thống ≠ kết quả rỗng.
7. Luật `deny` không bao giờ vào hàng đợi duyệt, và L2 không thực hiện lại hành động bị `deny`.
8. Việc cần làm trước khi chờ người nằm ở node đứng trước; sự kiện đến muộn bị bỏ qua (409). Ngoại lệ: tín hiệu `wake_parent` từ ticket con chỉ để đánh thức ticket cha, không bị 409 (D-17).
9. M9 chỉ đọc.
10. Ngưỡng và calibrator chỉ được fit trên tập calibration.
11. Role của người gửi chỉ lấy từ AD, không từ lời người dùng.
12. Một lượt người dùng — một tin trả lời: ticket con không tự nhắn, ticket cha gom (D-31).
13. Mọi chỉ số M8/M9 tính trên ticket lá (`is_parent = false`) (D-30).

**Mã quyết định mới (đã chốt theo đặc tả 25/09/2026):** D-01…D-33 — danh sách đầy đủ, trạng thái và các quyết định Q1–Q14 ở `build/decisions.md`. Các mã mà file này dùng được liệt kê ở mục 0.5 (file nền tảng: trong thân bài).

### 0.2. Vị trí của nhánh trong luồng

| | Nội dung |
|---|---|
| Nhánh trước | B2 (câu đã qua sàng lọc) |
| Nhận vào | `redacted_request`, `conversation`, `requester_context`, `reasoning_loops` |
| Giao cho nhánh sau | `intent`, `intent_confidence`, `span`, `slots` (sơ bộ, gồm `action`), `status=S_DIAGNOSING`, `next=b06_diagnose`; hoặc ticket con + cha ở `parent_wait` |
| Ai dùng đầu ra | Cha: vòng tổng hợp `parent_wait`/`parent_reply_wait` gửi **một** tin mỗi lượt người dùng (D-31). B6 (`TOOL_MAP[intent]`), B8 (lọc theo `request_type`), B11 (`REQUIRED_SLOTS[intent]`), B12 (luật theo intent), M9 (phân bố intent) |

**Chuyển trạng thái của nhánh [Chốt 2.1]:**

| Từ | Sự kiện | Sang |
|---|---|---|
| `S_CLASSIFYING` | Intent thuộc 4 loại, một yêu cầu | `S_DIAGNOSING` |
| `S_CLASSIFYING` | Nhiều yêu cầu | `S_CLASSIFYING` (ticket con) |
| `S_CLASSIFYING` | Ngoài phạm vi | `S_ESCALATED` → E1 |
| `S_CLASSIFYING` | Vượt 5 vòng suy luận | `S_ESCALATED` → E2 (theo mã giả B3) |
| `S_CLASSIFYING` ↔ `S_CONFIRMING` (chỉ cha) | Gửi tin tổng hợp / chuyển câu trả lời xuống con | **[Đề xuất D-29 quy tắc 3, D-31]** |
| `S_CLASSIFYING` hoặc `S_CONFIRMING` → `S_RESOLVED`/`S_REJECTED`/`S_ESCALATED` (chỉ cha) | Mọi con kết thúc | **[Chốt bảng B5; chuyển: Đề xuất D-29]** |

### 0.3. Đặc tả gốc đã chốt

- **B3:**
  - Đầu vào: câu đã qua kiểm tra an ninh. Đầu ra: một trong 4 loại hoặc "ngoài phạm vi".
  - Kỹ thuật: LLM với structured output, schema cố định.
  - Cách thất bại: phân sai loại thì toàn bộ luồng sau sai theo. Chỉ số: accuracy, F1 theo lớp.
- **Schema gốc:** `{intents: [{type, confidence, span}], is_multi}`. Trường `span` giúp truy vết phần nào của câu dẫn tới intent nào — cần cho B5 và cho debug.
- **B5:**
  - Ví dụ: "Reset mật khẩu giúp mình với, tiện thể cài luôn Photoshop nhé" → tách 2 ticket con, mỗi con phân loại rủi ro riêng.
  - Vì sao tách: nếu gộp, hệ thống buộc phải lấy mức rủi ro cao nhất cho cả hai — vừa sai logic vừa giảm tỉ lệ tự động hóa.
  - Mỗi con có một `thread_id`.
  - Thông báo: gom kết quả mọi con thành **một** tin nhắn. Người dùng gửi một câu thì chỉ nhận một câu trả lời tổng hợp. *(Nhóm chọn giữ đúng nguyên văn; cơ chế ở mục 5.4 — D-31.)*
- **Quy tắc ticket cha (6 trường hợp):**

  | Kết quả các con | Cha |
  |---|---|
  | Tất cả RESOLVED | RESOLVED |
  | ≥1 ESCALATED, còn lại RESOLVED | RESOLVED + `PARTIALLY_ESCALATED` |
  | Tất cả ESCALATED | ESCALATED |
  | ≥1 REJECTED, còn lại RESOLVED/đang chạy | Chờ, rồi RESOLVED + `PARTIALLY_REJECTED` |
  | Tất cả REJECTED | REJECTED |
  | Trộn ESCALATED + REJECTED | ESCALATED |

  Cha chỉ đóng khi mọi con đã kết thúc. Thứ tự ưu tiên: ESCALATED > REJECTED > RESOLVED.
- **Chi phí [Chốt 15.1]:** B3 vai trò fast, P gọi = 100%, khoảng 1.200 token vào và 200 token ra.
- **Mở rộng [Chốt mục 11]:** có thể fine-tune PhoBERT/XLM-R cho intent; slot vẫn dùng LLM. → **D-32 đưa phần này lên đường chính** (model đa nhãn nhóm tự huấn luyện, P11); LLM giữ vai trò dự phòng và tách span.

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC12 | Câu chứa nhiều yêu cầu khác mức rủi ro | Tách ticket con, mỗi con phân loại riêng |
| TC15 | Yêu cầu ngoài 4 loại (hỏng máy in) | E1, chuyển L2 ngay — nhờ kỹ thuật viên làm trực tiếp; hỏi cách làm / báo hiện tượng → `it_help` (D-76 (ĐP chốt 09/11, bản demo lo-0811)) |
| Cổng 3 | 20 câu VPN (viết tắt, không dấu) | Đúng ≥ 18/20 |
| Cổng 5 | 45 câu (10/loại × 4 + 5 ngoài phạm vi; macro-F1 tính 5 lớp) | Macro-F1 ≥ 0,85 |
| Cổng 5 | Bộ 10 câu nhiều ý | Tách đúng; ticket cha đúng 6 trường hợp |
| TC32 (mới, D-17) | Câu nhiều ý, một con bị E1 ngay lập tức | Cha vẫn đóng đúng, một tin nhắn tổng hợp |
| TC34 (mới, D-31) | 2 ý: reset mật khẩu (allow) + Photoshop (cần duyệt) | Không tin nào tới khi L1 duyệt xong; đúng **1** tin gồm 2 kết quả; người dùng xác nhận **1** lần; đúng 1 tin tổng kết |
| TC35 (mới, D-31) | 2 ý: một ý xong, một ý thiếu thông tin | 1 tin gồm kết quả ý 1 + câu hỏi ý 2; một lần trả lời; số tin agent gửi = số lượt người dùng |
| TC36 (mới, D-31) | Người dùng chọn "Chưa ổn" cho ý 1, "Đã ổn" cho ý 2 | Con 1 E8, con 2 `resolved_user_confirmed`; cha `S_RESOLVED` + `PARTIALLY_ESCALATED`, `close_reason=NULL`; 1 tin tổng kết |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- B3 không bao giờ tự quyết hành động.
- Confidence thấp thì không đoán.
- Mỗi ticket con là một thread riêng và có `Action` riêng qua M5.
- Cha **không tin vào thứ tự sự kiện**: trạng thái con luôn đọc từ DB (D-17).
- **Ticket con không bao giờ nhắn trực tiếp cho người dùng**; chỉ ticket cha gửi, đúng một tin mỗi lượt người dùng (D-31).
- Cha không có `exit_code`, không tạo `escalations`, đóng với `close_reason=NULL`; chỉ số chỉ tính ticket lá (D-30).
- **Mã quyết định / đề xuất dùng trong file:**
  - Con bắt đầu từ B6.
  - Bỏ `S_SPLIT` bằng cờ `is_parent`.
  - `TAU_INTENT`.
  - D-17, D-18, D-27 (bản vá v1.2).
  - D-29, D-30, D-31 (bản vá v1.3).
  - D-32 (B3 chạy model phân loại đa nhãn trước, LLM chỉ cho vùng lưng chừng và tách span), D-33 (backbone mDeBERTa-v3-base) — quy trình huấn luyện ở `nen-tang/P11-huan-luyen-model.md`.

---

## 1. Mục đích và vì sao tồn tại

Biến câu tự do thành cấu trúc để mọi bước sau làm việc trên dữ liệu có kiểu. Phân sai ở đây thì toàn bộ luồng phía sau sai theo **[Chốt B3]**.

Ba việc:

1. **B3:** gán intent ∈ {`account`, `vpn`, `software`, `access`} kèm `confidence`, `span` và slot ban đầu.
2. **B4:** ngoài 4 loại → E1.
3. **B5:** câu nhiều ý → tách ticket con.

**Tách ticket con là biện pháp an toàn, không chỉ để tiện xử lý.** Nếu gộp "cài Zoom *và* cấp quyền thư mục Finance", hệ thống buộc phải lấy mức rủi ro cao nhất cho cả hai **[Chốt B5]**. Tách ra thì mỗi `Action` được M5 đánh giá riêng, và phần vô hại không "kéo" phần nhạy cảm đi cùng.

## 2. Sơ đồ cấu tạo

```
S_CLASSIFYING
   │  reasoning_loops += 1 ; > MAX_LOOPS(5) → E2 [Chốt]
   ▼
[B3a] ml-service /classify_intent · intent-clf đa nhãn (D-32, P11)
     5 xác suất: account, vpn, software, access, out_of_scope ; ngưỡng τ_lo/τ_hi mỗi nhãn
   │
   ├─ đúng 1 nhãn "chắc có", còn lại "chắc không" ───────────────────► S_DIAGNOSING (B6)  [layer=model]
   ├─ chỉ out_of_scope "chắc có" ────────────────────────────────────► [B4] E1 out_of_scope  [layer=model]
   └─ còn lại (có nhãn lưng chừng / ≥2 nhãn chắc có / mâu thuẫn / ml-service lỗi hoặc chưa có model)
        ▼
[B3b] LLM fast · prompt b03_classify · schema ClassifyOut        [layer=llm]
     input: redacted_request + ≤4 tin gần nhất (context builder, ≤2.000 token)
           + label_hint = các nhãn "chắc có" nếu model thấy ≥2 nhãn (để tách span)
   │
   ├─ intents rỗng / tất cả out_of_scope ───────────────────────────► [B4] E1 (out_of_scope) → B20
   │    D-75 (ĐP chốt 09/11, bản demo lo-0811): intents rỗng (hoặc 1 ý < τ_intent) và CHƯA hỏi → câu hỏi phân loại cố định → S_CLARIFYING;
   │    đã hỏi → E1 như trên. out_of_scope rõ → E1 ngay. D-76: 1 ý it_help → B6 (0 tool) → B8 general → B10 info
   ├─ 1 intent trong phạm vi, confidence ≥ τ_intent ─────────────────► S_DIAGNOSING (B6)
   ├─ 1 intent, confidence < τ_intent ───────────────────────────────► [B4] E1 (intent_low_confidence, D-27)
   └─ ≥2 intent (is_multi) ──► [B5] tạo ticket con (qua effects.once, D-18):
          for i, it in enumerate(intents):
              child = ticket_id-(i+1), parent_ticket_id = ticket_id,
                      redacted_request = it.span, intent = it.type, requester_context (copy)
              effects.once("child_create") ; effects.once("child_submit")   # thread riêng, từ B6
          cha: is_parent=True, children=[…] → parent_wait
               parent_wait ĐỐI SOÁT con từ DB (tickets.final_state + child_notices) mỗi lần chạy (D-17)

VÒNG CỦA CHA (D-31) — người dùng chỉ nhận tin từ cha, một tin mỗi lượt:
   parent_wait (S_CLASSIFYING) ──mọi con đã dừng?──┐ chưa → interrupt, chờ wake_parent
        │ rồi                                       │
        ▼                                           │
   gửi 1 tin tổng hợp (mỗi ý một khối)              │
        ├─ mọi con đã kết thúc → tổng hợp 6 trường hợp → B20 (cha)
        └─ còn ý cần người dùng → S_CONFIRMING → parent_reply_wait
                 người dùng trả lời 1 lần cho mọi ý ─► chuyển từng phần xuống con (child_event)
                 ─► S_CLASSIFYING → parent_wait ───────┘
   "Con đã dừng" = đã kết thúc, HOẶC đang chờ người dùng (câu hỏi B11 / xác nhận B19) và đã để lại notice.
   Chờ L1 duyệt KHÔNG phải điểm dừng.
```

## 3. Công nghệ tại nhánh

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Phân loại + trích slot sơ bộ | LLM gateway, vai trò **fast**, structured output | **[Chốt]**; phân loại là tác vụ dễ, gọi 100% ticket → dùng model rẻ |
| Phân loại intent (đường chính) | `intent-clf` — mDeBERTa-v3-base fine-tune đa nhãn, ONNX int8, qua ml-service `/classify_intent` | **[Đề xuất D-32, D-33]**; tất định, ~20–40 ms, chịu được câu không dấu/viết tắt; nhóm tự huấn luyện (P11). LLM ở dòng trên thành đường dự phòng |
| Schema | Pydantic `ClassifyOut` | Sai schema bị bắt ngay |
| Ticket con | Runner (P1 mục 8), mỗi con 1 thread; tạo/submit qua `effects.once` | **[Chốt]** mỗi con một `thread_id`; không tạo con trùng khi node chạy lại (D-18) |
| Tổng hợp cha | `parent_wait` đọc `tickets.final_state` và `child_notices` của các con | D-17 — không phụ thuộc thứ tự sự kiện |
| Gom tin | `notify_user` của con ghi `child_notices`; `compose_digest` theo mẫu, không LLM | D-31 — một tin mỗi lượt, tất định |
| Mở rộng (Nên có) | Fine-tune PhoBERT/XLM-R cho intent; slot vẫn dùng LLM | **[Chốt mục 11]** — thêm một thành phần có huấn luyện |

## 4. Hợp đồng node

```python
class IntentItem(BaseModel):
    type: Literal["account", "vpn", "software", "access", "it_help", "out_of_scope"]  # D-76 (ĐP chốt 09/11, bản demo lo-0811): + it_help
    confidence: float = Field(ge=0, le=1)
    span: str = Field(max_length=500)                 # phần câu dẫn tới intent [Chốt]
    action_hint: str | None                           # ví dụ "reset_password", "install_software"
    slots: dict[str, str] = {}                        # slot trích được ngay từ câu

class ClassifyOut(BaseModel):
    intents: list[IntentItem] = Field(max_length=4)
    is_multi: bool

class IntentModelOut(BaseModel):                       # ml-service /classify_intent (P4, P11)
    probs: dict[str, float]                           # 5 nhãn, sigmoid độc lập, đã hiệu chỉnh nhiệt độ
    tau_hi: dict[str, float]; tau_lo: dict[str, float]   # đọc từ thresholds.json của phiên bản model
    version: str
```

- **Đọc:** `redacted_request`, `conversation`, `reasoning_loops`, `requester_context.locale`.
- **Ghi:** `intent`, `intent_confidence`, `span`, `slots` (bước đầu), `reasoning_loops`, `status`, `next`, `exit_code`, `is_parent`, `children`, `escalation_reason_detail`.

## 5. Luồng xử lý chi tiết

### 5.1. B3 + B4

```python
async def b03_classify(state):
    loops = state["reasoning_loops"] + 1
    if loops > cfg.MAX_LOOPS:
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B3",
                    event="max_loops_exceeded", exit_code="E2", reasoning_loops=loops)
    # --- B3a: model phân loại đa nhãn (D-32) ---
    res, err, _ = await registry.call_internal("ml_classify_intent",
                        {"text": state["redacted_request"]}, caller_step="B3")
    d = cascade_decide(res) if not err else Decision("uncertain", [])
    if d.kind == "single":
        audit_point_1(state, layer="model", intent=d.labels[0], probs=res.probs, model_version=res.version)
        return goto(state, S_DIAGNOSING, next_node="b06_diagnose", step="B3", event="intent_classified",
                    intent=d.labels[0], intent_confidence=res.probs[d.labels[0]],
                    span=state["redacted_request"], reasoning_loops=loops)   # slot + action: B11 trích
    if d.kind == "oos":
        audit_point_1(state, layer="model", intent="out_of_scope", probs=res.probs, model_version=res.version)
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_out_of_scope",
                    exit_code="E1", reasoning_loops=loops, escalation_reason_detail="out_of_scope")

    # --- B3b: LLM cho vùng lưng chừng, câu nhiều ý (cần span), hoặc model không dùng được ---
    try:
        out, meta = await llm.complete("fast", "b03_classify",
            {"redacted_request": state["redacted_request"],
             "recent_messages": last_n(state["conversation"], 4),
             "label_hint": d.labels if d.kind == "multi" else None}, ClassifyOut)
    except (LLMUnavailable, LLMSchemaError):
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B3",
                    event="classifier_unavailable", exit_code="E2", reasoning_loops=loops)

    in_scope = [i for i in out.intents if i.type != "out_of_scope"]
    audit_point_1(state, out, layer="llm", model_probs=None if err else res.probs)   # điểm log 1 [Chốt]

    if not in_scope:
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B4",
                    event="intent_out_of_scope", exit_code="E1", reasoning_loops=loops,
                    escalation_reason_detail="out_of_scope")
    if len(in_scope) == 1 and in_scope[0].confidence < cfg.TAU_INTENT:     # D-27
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B4",
                    event="intent_low_confidence", exit_code="E1", reasoning_loops=loops,
                    escalation_reason_detail="intent_low_confidence")
    if len(in_scope) >= 2:
        return await b05_split(state, in_scope, loops)
    it = in_scope[0]
    return goto(state, S_DIAGNOSING, next_node="b06_diagnose", step="B3", event="intent_classified",
                intent=it.type, intent_confidence=it.confidence, span=it.span,
                slots={**state["slots"], **it.slots, "action": it.action_hint}, reasoning_loops=loops)
```

**Vì sao tách `intent_low_confidence` khỏi `intent_out_of_scope` (D-27, L-12):** cả hai vẫn ra E1 — "không chắc thì chuyển người" **[Chốt nguyên tắc 1]**. Nhưng nếu chỉ ghi chung một sự kiện, tỉ lệ E1 trên M9 lẫn hai loại ca rất khác nhau: yêu cầu thật sự ngoài phạm vi (cần mở rộng phạm vi) và B3 không chắc (cần sửa prompt hoặc hạ `TAU_INTENT`). `escalation_reason_detail` được B20 ghi vào `escalations.reason_detail` (P7).

**Quy tắc quyết định của B3a (D-32):**

```python
def cascade_decide(r: IntentModelOut) -> Decision:
    IN = ["account", "vpn", "software", "access"]
    sure   = [c for c in IN if r.probs[c] >= r.tau_hi[c]]
    unsure = [c for c in IN + ["out_of_scope"] if r.tau_lo[c] < r.probs[c] < r.tau_hi[c]]
    oos    = r.probs["out_of_scope"] >= r.tau_hi["out_of_scope"]
    if unsure:                     return Decision("uncertain", sure)
    if oos and not sure:           return Decision("oos", [])
    if oos and sure:               return Decision("uncertain", sure)     # mâu thuẫn → để LLM xem
    if len(sure) == 1:             return Decision("single", sure)
    if len(sure) >= 2:             return Decision("multi", sure)         # cần LLM tách span
    return Decision("uncertain", [])                                      # không nhãn nào đủ chắc
```

**Vì sao chỉ đi thẳng khi model chắc ở mọi nhãn:** `τ_hi` chọn theo precision ≥ 0,95 và `τ_lo` theo recall ≥ 98% trên tập validation (P11 mục 4.2). Chỉ cần một nhãn rơi vào vùng giữa là câu được chuyển cho LLM, nên model không bao giờ tự quyết ở ca khó. Model **không** được tự kết luận "độ tin cậy thấp → E1": ca đó luôn qua LLM trước, và chỉ LLM mới ra `intent_low_confidence` (D-27).

**Vì sao câu nhiều ý vẫn cần LLM:** model đa nhãn biết câu có **những** intent nào nhưng không biết **phần câu nào** thuộc intent nào. B5 cần `span` cho từng ticket con, nên LLM được gọi với `label_hint`. Nếu LLM kết luận câu chỉ có một ý (ví dụ "reset mật khẩu VPN" làm model bật cả `account` lẫn `vpn`), kết quả của LLM thắng.

**Slot và `action` ở đường model:** đường model không trích slot; B11 trích bằng `b11_extract_slots` như khi slot còn thiếu. Vì vậy lợi ích chính của D-32 là **độ chính xác và tất định của intent, độ trễ và chi phí ở câu một ý**, không phải bỏ hẳn LLM khỏi ticket.

**Không có model (chưa huấn luyện xong, ml-service lỗi):** `/classify_intent` trả 503 → `err` → toàn bộ đi đường LLM như bản trước. Phase 3 không phải chờ model.

### 5.2. B5 — tách ticket con

```python
async def b05_split(state, intents, loops):
    children = []
    for i, it in enumerate(intents, start=1):
        cid = f'{state["ticket_id"]}-{i}'                                   # id tất định
        await effects.once(state, "child_create", tickets.create_child, cid,
                           parent=state["ticket_id"], requester_context=state["requester_context"],
                           redacted_request=it.span, step="B5", sub=cid)
        await effects.once(state, "child_submit", runner.submit, cid,
                           initial={"intent": it.type, "slots": it.slots, "entry": "b06_diagnose"},
                           step="B5", sub=cid)                              # mục 5.3
        children.append(cid)
    await tickets.mark_parent_once(state["ticket_id"])                     # tickets.is_parent = true (D-30)
    return goto(state, S_CLASSIFYING, next_node="parent_wait", step="B5",
                event=f"split_into_{len(children)}_children", is_parent=True,
                children=children, reasoning_loops=loops)
```

**Vì sao qua `effects.once` (D-18):** tạo và submit con là side effect. Nếu process chết sau khi submit nhưng trước khi checkpoint của cha được ghi, lần chạy lại B5 sẽ submit con lần hai. Id con tất định (`ticket_id-n`) cộng khóa `effects.once` bảo đảm mỗi con chỉ được tạo và chạy đúng một lần.

**Ghi chú về `kind` và `sub`:** bảng `side_effects` giới hạn `kind` bằng CHECK (P7 mục 2.8). Tham số `sub=cid` đưa id con vào khóa băm để mỗi con có một khóa riêng, còn cột `kind` vẫn là `child_create` / `child_submit`.

### 5.3. Ticket con bắt đầu từ đâu

**[Đề xuất]** Con bắt đầu ở **B6**, không phải B1 hoặc B3:

- B1 đã xác lập danh tính và B2 đã sàng lọc cả câu của cha.
- B3 đã gán intent cho từng `span`.

Chạy lại B3 cho con sẽ tốn thêm một lời gọi LLM và có thể cho kết quả khác. Con copy `requester_context` từ cha (vẫn là bản frozen). Mã giả gốc ghi "ticket con quay lại B3" **[Chốt bảng 2.1: `S_CLASSIFYING` (ticket con)]** — đề xuất này rút ngắn đường đi, cần nhóm xác nhận.

### 5.4. Tổng hợp ở ticket cha [Chốt bảng B5 + Đề xuất D-17, D-30, D-31]

**Bảng đóng cha [Chốt B5]:**

| Kết quả các con | Cha đóng ở | `aggregate_status` |
|---|---|---|
| Tất cả `S_RESOLVED` | `S_RESOLVED` | `ALL_RESOLVED` |
| ≥1 `S_ESCALATED`, còn lại `S_RESOLVED` | `S_RESOLVED` | `PARTIALLY_ESCALATED` |
| Tất cả `S_ESCALATED` | `S_ESCALATED` | `ALL_ESCALATED` |
| ≥1 `S_REJECTED`, còn lại `S_RESOLVED` | `S_RESOLVED` | `PARTIALLY_REJECTED` |
| Tất cả `S_REJECTED` | `S_REJECTED` | `ALL_REJECTED` |
| Trộn `ESCALATED` + `REJECTED`, không con nào `RESOLVED` | `S_ESCALATED` | `MIXED` |

Thứ tự ưu tiên khi đóng: `ESCALATED` > `REJECTED` > `RESOLVED`. Cha chỉ đóng khi **mọi** con đã kết thúc.

**Cha biết con đã kết thúc bằng cách nào (D-17, L-01):** `parent_wait` đọc `tickets.final_state` của mọi con **mỗi lần chạy**, kể cả lần đầu trước `interrupt()`. `wake_parent` chỉ là tín hiệu đánh thức. Worker quét mỗi 60 giây làm lưới an toàn.

#### 5.4.1. Một tin nhắn tổng hợp [Chốt B5; cơ chế Đề xuất D-31]

**Vấn đề (L-15):** ở bản v1.2, mỗi con tự gửi tin ở B10/B16/B18/B20 và tự hỏi xác nhận ở B19, trái với câu đã chốt "gom thành một tin". Hai yêu cầu còn va nhau: con muốn kết thúc phải qua B19, mà B19 cần người dùng đã thấy kết quả. Nhóm chọn **giữ đúng nguyên văn**: ticket con không tự nhắn, bước xác nhận đi qua cha.

**Cơ chế (chi tiết mã giả ở P1 mục 8.1–8.2):**

1. **Con không gửi, chỉ để lại notice.** `notify_user` của con ghi vào `child_notices` (P7), kèm `needs`: `answer` (câu hỏi B11), `confirm` (kết quả B10/B18), `none` (từ chối B16, chuyển kỹ thuật viên B20). Logic các nhánh không đổi.
2. **Con dừng ở điểm cần người dùng mà không đặt hạn riêng.** Con ở `clarify_wait`/`confirm_wait` chờ sự kiện do cha chuyển xuống. Con chờ L1 duyệt thì chưa "dừng".
3. **Cha gửi một tin khi mọi con đã dừng.** Mỗi ý một khối có tiền tố "Ý n – …". Nội dung theo mẫu, không dùng LLM.
4. **Người dùng trả lời một lần cho mọi ý** qua `POST /api/tickets/{cha}/reply`. Cha chuyển từng phần xuống đúng con (`effects.once`, kind `child_event`): trả lời câu hỏi → `clarify_wait` của con chạy tiếp B11; "Đã ổn"/"Chưa ổn" → B19 của con ra `resolved_user_confirmed` hoặc E8.
5. **Lặp** cho tới khi mọi con kết thúc, rồi gửi tin tổng kết và đóng cha theo bảng trên.

Kết quả: **số tin agent gửi đúng bằng số lượt người dùng** (câu gốc + mỗi lần trả lời). Đây là cách hiểu câu chốt mà thiết kế dùng **[Suy luận]**.

**Ví dụ TC34:** "Reset mật khẩu giúp mình, tiện cài luôn Photoshop."

```
Con 1 (reset, R01 allow) ─► B17 xong ─► B18 → notice(result, needs=confirm) ─► confirm_wait (dừng)
Con 2 (Photoshop, cần duyệt) ─► chờ L1 … 12 phút … duyệt ─► B17 xong ─► notice(result, confirm) ─► dừng
Cha: mọi con đã dừng ─► 1 tin:
   "Ý 1 – Reset mật khẩu: đã reset, mật khẩu mới gửi qua email.  [Đã ổn] [Chưa ổn]
    Ý 2 – Cài Photoshop: IT đã duyệt và cài xong.                [Đã ổn] [Chưa ổn]"
Người dùng: Ý 1 ✓, Ý 2 ✓  ─► cha chuyển xuống ─► 2 con resolved_user_confirmed ─► B20 từng con
Cha: mọi con kết thúc ─► 1 tin tổng kết "Cả 2 yêu cầu đã hoàn tất" ─► S_RESOLVED, ALL_RESOLVED
```

**Đánh đổi đã chấp nhận:** trong ví dụ trên, người dùng không nhận tin nào trong 12 phút chờ duyệt, dù ý 1 xong ngay (email mật khẩu mới vẫn đến ngay vì đó là hệ thống ngoài). Giảm nhẹ: khung tiến độ từng ý trên giao diện (không phải tin nhắn). Thời gian chờ tối đa bị chặn bởi `SLA_MINUTES=30` **[Chốt]**: hết hạn thì con thành E6 và đã dừng.

#### 5.4.2. Đóng ticket cha [Đề xuất D-30]

- `close_reason = NULL`: 8 giá trị **[Chốt]** không có giá trị cho "đóng vì tổng hợp"; ý nghĩa nằm ở `aggregate_status`.
- Cha không có `exit_code`, không tạo `escalations`: việc của L2 nằm ở con đã escalate.
- Mọi chỉ số M8/M9 và hàng đợi L2 lọc `tickets.is_parent = false`, để một câu hai ý không bị đếm thành ba ticket.

`S_BLOCKED` ở con không xảy ra, vì con không chạy B1/B2 (mục 5.3).

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| LLM fast + structured output | Tác vụ phân loại đơn giản, gọi ở mọi ticket; chi phí 15.1 **[Chốt]** |
| Trả `span` cho từng intent | Truy vết phần câu dẫn tới intent, cần cho tách ticket và debug **[Chốt]** |
| Confidence thấp → E1, không đoán | Nguyên tắc "không chắc thì chuyển người" **[Chốt nguyên tắc 1]** |
| Tách sự kiện `intent_low_confidence` khỏi `intent_out_of_scope` | Chỉ số E1 không lẫn hai nguyên nhân (D-27) |
| Trích slot sơ bộ ngay ở B3 | Tiết kiệm một lời gọi ở B11 khi câu đã đủ thông tin; B11 vẫn kiểm lại đủ/thiếu |
| Model phân loại chạy trước, LLM cho vùng lưng chừng (D-32) | Intent tất định và nhanh cho phần lớn câu một ý; LLM chỉ xử lý ca khó và câu nhiều ý. Giống khuôn đã dùng ở B2 (D-06) |
| Model không bao giờ tự ra E1 `intent_low_confidence` | Ca không chắc luôn được LLM xem lại trước — giữ nguyên nghĩa của D-27 |
| Giới hạn ≤ 4 intent mỗi câu | Câu có > 4 ý gần như chắc là bất thường → cắt ở 4, phần còn lại báo người dùng gửi riêng |
| Ticket con = thread riêng | Con chờ duyệt không giữ chân con khác (P1 mục 8) |
| Tạo/submit con qua `effects.once`, id tất định | Không có con trùng khi B5 chạy lại (D-18) |
| Cha đối soát con từ DB | Không phụ thuộc thứ tự sự kiện (D-17) |
| Con không tự nhắn; cha gửi một tin mỗi lượt người dùng | Giữ đúng câu chốt "một câu trả lời tổng hợp"; người dùng trả lời một lần cho mọi ý (D-31) |
| Tin tổng hợp theo mẫu, không LLM | Tất định, không bịa, không tốn thêm lời gọi |
| Cha `close_reason=NULL`, không `escalations`, chỉ số trên ticket lá | Không đếm trùng, không có ticket mồ côi trong hàng đợi L2 (D-30) |

## 7. Cấu hình

- `MAX_LOOPS=5` **[Chốt]**
- `TAU_INTENT=0,6` **[Đề xuất; KHÔNG chỉnh theo bộ probe cổng 5 — bộ đó chỉ để đo (chốt 15/10/2026)]** — chỉ áp cho đường LLM
- `INTENT_MODEL_DIR` (ml-service) — `tau_lo`/`tau_hi` nằm trong `thresholds.json` của phiên bản model, không nằm trong `policy.json` (P11 mục 4.3)
- `PARENT_RECONCILE_INTERVAL=60s` (worker) **[Đề xuất D-17]**
- Prompt `b03_classify` (version ghi vào lineage)

## 8. Dữ liệu, DB, điểm log

- **Điểm log 1 [Chốt]:** `intent`, `confidence` (+ `span`, `is_multi`, `prompt_version`; bổ sung D-32: `layer` ∈ {`model`, `llm`}, `model_probs`, `model_version`).
- **`tickets`:**
  - Tạo dòng con với `parent_ticket_id`.
  - Cột `intent` và `slots` được ghi **một lần khi đóng ở B20**, theo nguyên tắc bảng `tickets` chỉ ghi định danh và kết quả cuối **[Chốt thiết kế DB vòng 3]**.
- **Cha:** `aggregate_status` ghi ở B20; `close_reason = NULL`; `tickets.is_parent = true` ghi một lần ở B5 (D-30).
- **`child_notices`:** mọi lời nhắn của con, được cha gửi theo vòng (D-31).
- **`side_effects`:** `notify_user` của cha với `sub=round:n`; `child_event` cho mỗi lần chuyển câu trả lời xuống con.
- **`side_effects`:** `child_create`, `child_submit` cho mỗi con (D-18).
- **`escalations.reason_detail`:** `out_of_scope` hoặc `intent_low_confidence` (D-27).

## 9. Trace và giám sát

- **Span:** `node:b03_classify`, `ml:classify_intent`, `llm:b03_classify`.
- **M9 (D-32):** tỉ lệ câu B3 phải xuống LLM theo ngày; > 30% → cảnh báo model intent xuống cấp (P9 luật 13).
- **M9:**
  - Phân bố intent theo tuần (nguồn tính drift).
  - Tỉ lệ E1, **tách hai phần**: `out_of_scope` và `intent_low_confidence` (D-27).
  - Tỉ lệ câu nhiều ý.
  - Số cha ở `parent_wait` quá 1 giờ mà mọi con đã kết thúc (phải = 0 nhờ D-17).
  - Thời gian từ khi con đầu tiên dừng tới khi cha gửi tin (đo đánh đổi của D-31).
  - Số tin agent gửi / số lượt người dùng ở ticket nhiều ý (phải = 1).

## 10. Lỗi và ca biên

| Tình huống | Kết quả |
|---|---|
| "Máy in hỏng" | `out_of_scope` → E1 (TC15 **[Chốt]**) — (ĐP chốt 09/11, bản demo lo-0811): "sửa máy in giúp em" → `out_of_scope`; "máy in không in được" → `it_help` (D-76) |
| "reset mk email giúp mình" (viết tắt) | `account`, slot `account_type=email`, `action=reset_password` |
| Một intent trong phạm vi nhưng confidence 0,4 | E1, `reason_detail=intent_low_confidence` (D-27) |
| "Reset mật khẩu, tiện cài luôn Photoshop" | 2 con: account (R01 allow) + software (ngoài danh mục → duyệt) (TC12 **[Chốt]**) |
| Hai ý cùng loại ("cài Zoom và Slack") | Vẫn tách 2 con: mỗi phần mềm có thể khác danh mục hoặc license |
| Một con bị E1/E2 ngay, trước khi cha vào `parent_wait` | Cha đối soát từ DB khi tới `parent_wait` → đóng đúng (TC32, D-17) |
| Process chết sau khi submit con, trước checkpoint của cha | B5 chạy lại → `effects.once` không tạo/submit lại (D-18) |
| Một ý xong ngay, ý kia chờ L1 duyệt | Không tin nào tới khi ý kia dừng; khung tiến độ trên UI cập nhật (TC34, D-31) |
| Người dùng trả lời thiếu một ý | 422, không chuyển gì xuống con |
| Người dùng gọi thẳng API xác nhận của ticket con | 409 "Vui lòng trả lời trong hội thoại chung" |
| Người dùng im lặng sau tin tổng hợp | Hạn của cha (24h nếu có câu hỏi, 48h nếu chỉ xác nhận) → timeout chuyển xuống từng con: E4 hoặc `resolved_auto_timeout_48h` **[Chốt]** |
| LLM trả JSON sai sau 1 lần sửa | E2 (mở rộng — việc còn mở ở P2 mục 10) |
| Model chắc chắn 1 nhãn ("vpn ko vào dc") | Đi thẳng B6, không gọi LLM (D-32) |
| Model bật cả `account` và `vpn` cho "reset mật khẩu VPN" | Xuống LLM với `label_hint`; LLM kết luận một ý → một ticket |
| ml-service chết hoặc chưa có model | Toàn bộ đi đường LLM |
| Vượt 5 vòng suy luận | E2 **[Chốt]** |

## 11. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Unit | Logic B4 với `ClassifyOut` soạn sẵn | Đúng nhánh cho 6 dạng đầu vào; ca confidence thấp có `event=intent_low_confidence` |
| Unit | `cascade_decide` | Đúng 6 nhánh (single, oos, multi, lưng chừng, mâu thuẫn, không nhãn nào) với xác suất soạn sẵn |
| Integration | FakeMlService trả 503 | B3 đi đường LLM, kết quả như bản không có model |
| Unit | Bảng tổng hợp cha | 6 trường hợp + tổ hợp có cả 3 loại kết quả **[Chốt cổng 5]** |
| Integration (ScriptedLLM) | TC12 | 2 con, mỗi con có `Action` và `decided_by` riêng; một tin nhắn tổng hợp |
| Integration | TC34, TC35, TC36 | Như mục 0.4; đếm tin gửi người dùng = số lượt người dùng (D-31) |
| Integration | Cha đóng | `close_reason IS NULL`, không dòng `escalations` cho cha; truy vấn escalation rate trên ticket lá không đếm cha (D-30) |
| Integration | TC15 | E1, ghi chú "cần kỹ thuật viên" (ca nhờ kỹ thuật viên làm trực tiếp; ca hỏi cách làm → `it_help` — D-76 (ĐP chốt 09/11, bản demo lo-0811)) |
| Integration | TC32: một con E1 tức thì | Cha đóng đúng, không cần `child_done` (D-17) |
| Integration | Giết process sau `child_submit`, trước checkpoint cha | Đúng 2 con, mỗi con chạy 1 lần (D-18) |
| Probe (LLM thật) | Intent VPN | ≥ 18/20 câu tiếng Việt (viết tắt, không dấu) **[Chốt cổng 3]** |
| Probe (model thật) | Cascade trên bộ 45 câu | Macro-F1 ≥ 0,85 **[Chốt cổng 5]**; câu xuống LLM ≤ 30% |
| Probe | 45 câu (10 câu/loại × 4 + 5 ngoài phạm vi; macro-F1 5 lớp) | Macro-F1 ≥ 0,85 **[Chốt cổng 5]** |
| Probe | 10 câu nhiều ý | Tách đúng ≥ 9/10 |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P4 (`/classify_intent`), P11 (model `intent-clf`), P2, P1 (runner, `parent_wait`, `effects.once`), P7 (`side_effects`, `escalations.reason_detail`), B1, B2.
- **Phase:** 3 (chỉ VPN, chưa tách ý), 5 (đủ 4 loại + B5).
- **Việc còn mở:** con bắt đầu từ B6 thay vì B3 (mục 5.3); bỏ `S_SPLIT` bằng cờ `is_parent` (README mục 5); D-17, D-18, D-27, D-29, D-30, D-31 đã chốt theo đặc tả. Báo cáo GVHD đánh đổi "người dùng chờ ý chậm nhất" của D-31 (mục 5.4.1).

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Thêm loại yêu cầu thứ 5 (ví dụ `email`, `printer`) | Thêm vào `Literal` của `IntentItem`, prompt `b03_classify`, `TOOL_MAP`, `slots.yaml`, luật M5, tài liệu KB; tăng version prompt | Loại mới phải có luật; không có luật thì M5 đi xuống LLM → phải có dữ liệu calibration |
| Đổi model intent (phiên bản mới, PhoBERT, model lớn hơn) | Huấn luyện theo P11, xuất thư mục phiên bản mới, đổi `INTENT_MODEL_DIR`; chọn lại `τ_lo/τ_hi` trên validation | Đầu ra vẫn là `IntentModelOut`; không đổi sau tag `v1.0-freeze` |
| Scale | Node không giữ state; chi phí nằm ở LLM → cache runtime 24h cho `b03_classify` (được phép vì không phải B2/B14) | Khóa cache chứa `prompt_version` |
| Đa ngôn ngữ | Thêm câu ví dụ few-shot tiếng Anh; `locale` trong `requester_context` | Ngoài phạm vi gốc — ghi Future Work |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| E1 tăng đột biến | Điểm log 1: `intent`, `confidence`; tỉ lệ `intent_low_confidence` so với `out_of_scope` | `TAU_INTENT` quá cao; prompt mới làm confidence thấp; câu viết tắt mới |
| Tỉ lệ B3 xuống LLM tăng | Điểm log 1 `layer`, phân bố `model_probs` | Dữ liệu thật lệch khỏi dữ liệu huấn luyện (câu mới, từ viết tắt mới) → bổ sung dữ liệu, huấn luyện lại (P11) |
| Phân sai loại giữa `account` và `access` | Probe 45 câu, ma trận nhầm lẫn; tỉ lệ `intent_filter_fallback` ở B8 | Thiếu ví dụ few-shot "quyền thư mục" và "quyền tài khoản" |
| Ticket cha không bao giờ đóng | `children` của cha + `tickets.final_state` của con; worker đối soát có chạy không | Một con bị kẹt (xem E9); worker đối soát tắt; `parent_wait` không đọc DB (vi phạm D-17) |
| Người dùng nhận nhiều tin cho một câu | `side_effects` kind `notify_user` theo ticket con | Có đường gửi tin của con không đi qua `notify_user` (vi phạm D-31) |
| Cha gửi tin tổng hợp khi một ý còn đang chờ duyệt | `children_view` của vòng đó | Coi `S_PENDING_APPROVAL` là điểm dừng — sai định nghĩa D-31 |
| Con bị tạo hai lần | `side_effects` với `kind=child_create` | Tạo con không qua `effects.once`; id con không tất định |
| Tách thừa ("cài Zoom" thành 2 ý) | `span` của từng intent | Prompt chưa có ví dụ câu một ý nhiều cụm từ |

### Chốt khi hiện thực Phase 3 (30/09/2026)

Phase 3 hiện thực theo `build/phase3-thiet-ke-chi-tiet.md` mục 9.3, 9.8; khi lệch, file đó thắng (trừ bất biến và mục [Chốt]).

- `ENABLED_INTENTS` (Phase 3 chỉ `vpn`); thứ tự kiểm E1 cố định; ≥ 2 ý → E1 `multi_intent_not_enabled`.
- `sanitize_slots(spec, raw, *, text, allowed=None)`: slot > 100 ký tự bị bỏ; `device_id`/`error_code` phải có trong câu (biên token); key trùng `FACT_KEYS` bị loại; slot không bao giờ thành fact.
- Không helper `esc`: mỗi nhánh một `goto` với hằng.

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.2 | Bản vá: cha đối soát con từ DB (D-17), tạo/submit con idempotent (D-18), tách `intent_low_confidence` (D-27); thêm TC32 |
| 25/09/2026 | 1.3 | Một tin tổng hợp: con không tự nhắn, cha gửi một tin mỗi lượt, xác nhận qua cha (D-31); cha `close_reason=NULL`, chỉ số trên ticket lá (D-30); chuyển trạng thái của cha (D-29); thêm TC34–TC36 |
| 25/09/2026 | 1.4 | B3 chạy model phân loại đa nhãn trước, LLM cho vùng lưng chừng và tách span (D-32); backbone mDeBERTa-v3-base (D-33) |
| 30/09/2026 | 1.5 | Thêm mục "Chốt khi hiện thực Phase 3" trỏ về `phase3-thiet-ke-chi-tiet.md` (mục 9.3, 9.8) |
| 17/10/2026 | 1.6 | Bộ probe intent cổng 5 = 45 câu (10/loại × 4 + 5 ngoài phạm vi), macro-F1 tính 5 lớp; `TAU_INTENT` không chỉnh theo bộ probe — bộ probe chỉ để đo (chốt 15/10/2026) |
