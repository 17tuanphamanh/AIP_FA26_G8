# 02 — Các tầng của hệ thống: chức năng, ranh giới, yêu cầu

*Thuộc bộ `build/`. Mở rộng sơ đồ 4 tầng đã chốt (Agent / Kiểm soát / B17 / Monitor — `huong-dan-xay-dung-he-thong-2.md` mục 3 và 17.9) thành 8 tầng triển khai, thêm ba tầng mà sơ đồ gốc vẽ gộp: giao diện, cổng vào bảo mật, và nền tảng dùng chung.*

> **Cập nhật v1.3 (25/09/2026):** bảng chuyển tường minh (D-29); ticket cha không mã thoát, chỉ số trên ticket lá (D-30); một tin tổng hợp cho yêu cầu nhiều ý (D-31).
>
> **Cập nhật v1.2 (25/09/2026):** T4 kiểm cả người yêu cầu và người thụ hưởng (D-15 sửa); T6 bổ sung `effects.once`, khóa phiên, đối soát ticket con (D-17…D-19), DB 21 bảng; RAG chunk theo token và có fallback (D-21…D-24); bảng ánh xạ thêm chuyển `S_CLARIFYING → S_DIAGNOSING` (D-20, sau cờ).

---

## 0. Sơ đồ tổng

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ T0  GIAO DIỆN & BIÊN        React (4 vai trò) · Caddy HTTPS                   │
└───────────────────────────────┬──────────────────────────────────────────────┘
┌───────────────────────────────▼──────────────────────────────────────────────┐
│ T1  CỔNG VÀO & BẢO MẬT      AuthN · RBAC · kiểm tra theo bản ghi ·           │
│                             privacy guard (L0–L1) · giới hạn tần suất        │
└───────────────────────────────┬──────────────────────────────────────────────┘
┌───────────────────────────────▼───────────────────────────┐ ┌────────────────┐
│ T2  AGENT (M1–M4)                                          │ │ T5 MONITOR (M9)│
│  B1 danh tính · B2 sàng lọc · B3–B5 phân loại · B6–B7      │ │ chỉ đọc        │
│  chẩn đoán · B8–B10 tra cứu/trả lời · B11 dựng Action ·    │ │ dashboard ·    │
│  B19 xác nhận · LangGraph runner                           │ │ cảnh báo ·     │
├────────────────────────────────────────────────────────────┤ │ health · drift │
│ T3  KIỂM SOÁT (M5–M7)                                      │ │                │
│  B12–B14 rủi ro · B15–B16 phê duyệt · B20 audit · L2       │◄┤ (role Postgres │
├────────────────────────────────────────────────────────────┤ │  app_monitor)  │
│ T4  THỰC THI — B17 (điểm ghi duy nhất) · B18               │ │                │
└───────────────┬───────────────────────────┬────────────────┘ └────────────────┘
┌───────────────▼───────────────────────────▼──────────────────────────────────┐
│ T6  NỀN TẢNG DÙNG CHUNG   LLM gateway · RAG + ml-service · tool registry ·    │
│                           Postgres (ticket, audit, checkpoint, trace,         │
│                           side_effects) · worker · effects.once · khóa phiên  │
└───────────────────────────────┬──────────────────────────────────────────────┘
                         Mock AD / VPN / Phần mềm / File
┌──────────────────────────────────────────────────────────────────────────────┐
│ T7  ĐÁNH GIÁ (M8) — offline, theo lô, chỉ bật khi EVAL_MODE=true             │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Luật đọc sơ đồ:**

- Mũi tên đi **xuống**: tầng trên gọi tầng dưới.
- Tầng dưới không gọi ngược lên tầng trên.
- T5 chỉ đọc.
- T4 là nơi duy nhất ghi ra hệ thống ngoài.
- LLM chỉ xuất hiện ở T2 và lớp 2 của T3 **[Chốt]**.
- Mọi tác dụng phụ nội bộ (thông báo, tạo phiếu duyệt, tạo ticket con, đặt hạn chờ, tạo escalation) trong node đi qua `effects.once` **[Đề xuất D-18]**.

---

## T0 — Giao diện và biên

**Chức năng:** giao diện cho 4 vai trò; điểm vào HTTPS duy nhất. Chi tiết: `nen-tang/P10-giao-dien.md`.

| Thành phần | Công nghệ | Việc làm |
|---|---|---|
| App nhân viên | React + TanStack Query | Chat gửi yêu cầu, trạng thái, đồng hồ chờ, nguồn trích dẫn, xác nhận. Yêu cầu nhiều ý: **một** tin tổng hợp mỗi lượt với khối cho từng ý (nút Đã ổn/Chưa ổn, ô trả lời), một lần gửi `POST /tickets/{cha}/reply`; khung tiến độ từng ý (không phải tin nhắn) (D-31) |
| App L1 | React | Hàng đợi duyệt (sắp theo hạn, đỏ khi còn < 20%), trang chi tiết duyệt (Action đã băm, luật khớp hoặc p, chẩn đoán), ghi đè |
| App Trưởng BP | React | Sửa policy (validate, lịch sử, quay lui, mô phỏng tác động), dashboard nghiệp vụ + dashboard AI, cảnh báo |
| App L2 | React | Hàng đợi escalate theo ưu tiên, ghi chú bàn giao (có `reason_detail`, D-27), đóng với 3 kết quả |
| Biên | Caddy | HTTPS, phục vụ build tĩnh, proxy `/api/*`, header bảo mật (HSTS, CSP) |

**Được làm:** gọi `/api/*` với access token trong bộ nhớ, refresh token trong cookie HttpOnly.
**Cấm:** tự quyết quyền. UI ẩn nút chỉ để tiện dùng; quyền thật luôn do T1 kiểm tra. Cấm lưu token trong localStorage.

**Yêu cầu phi chức năng:**

- Polling trạng thái ticket 2 giây/lần khi đang xử lý, 10 giây/lần khi chờ người.
- Theme sáng, đọc được trên máy chiếu **[Chốt]**.

**Đạt khi:**

- Checklist demo 12 ca (Phase 7).
- L1 không thấy trang policy, và gọi thẳng API policy thì bị 403.
- Lint và build sạch.

---

## T1 — Cổng vào và bảo mật

**Chức năng:** trả lời "ai đang gọi", "vai trò đó có được làm loại việc này", "có quyền trên đúng bản ghi này không", và làm sạch dữ liệu **trước khi** nó được lưu. Chi tiết: `nen-tang/P6-auth-bao-mat.md`, `nhanh/B02-sang-loc-injection.md` (phần L0–L1).

| Thành phần | Vị trí code | Việc làm |
|---|---|---|
| AuthN middleware | `auth/middleware.py` | Xác minh JWT, phiên chưa thu hồi, `token_version`, trạng thái user |
| RBAC | `auth/permissions.py`, `require()` | Ma trận 2.2 → permission **[Chốt]** |
| Kiểm tra theo bản ghi | `auth/resource_checks.py` | `can_read_ticket`, `can_decide_approval`, `can_override`, `can_close_escalation`, `can_read_audit` |
| Privacy guard | `guard/normalize.py`, `guard/privacy.py` | Chuẩn hóa, che bí mật/PII ở handler tạo ticket và handler nhận tin nhắn **[Đề xuất D-07]** |
| Giới hạn tần suất | `auth/rate_limit.py` | Đăng nhập 5 lần/10 phút; tạo ticket 20 lần/giờ/người **[Đề xuất]** |

**Được làm:** từ chối request (401/403/404/422/429); ghi `security_events`.
**Cấm:** gọi LLM; ghi `audit_logs` (không thuộc ticket); đọc hoặc lưu mật khẩu.

**Yêu cầu chức năng:**

- FR-T1-1: mọi route khai báo permission, trừ `/auth/login`, `/api/health`.
- FR-T1-2: không văn bản chứa bí mật nào đi qua được T1 xuống DB.
- FR-T1-3: người bị vô hiệu hóa mất quyền trong ≤ 30 giây.

**Yêu cầu phi chức năng:**

- p95 của T1 < 20 ms (không tính privacy guard).
- Privacy guard < 50 ms với câu ≤ 2.000 ký tự.

**Đạt khi:** test quét route; 40 test ma trận; test IDOR; test thu hồi; grep canary không thấy bí mật (chi tiết ở P6, B02).

---

## T2 — Agent (M1–M4)

**Chức năng:** hiểu yêu cầu, chủ động thu thập dữ kiện, tra tri thức, hỏi lại khi thiếu, và **dựng `Action` có cấu trúc**. Ba việc T2 không làm: quyết định có được làm hay không, ghi vào hệ thống ngoài, phê duyệt.

**Định vị [Đề xuất D-28]:** T2 là *constrained agent* — LLM chọn trong không gian hữu hạn (intent, slot, tool đọc, câu trả lời có trích dẫn), còn luồng điều khiển do state machine quyết định. Lý do đầy đủ: P1 §1.1.

| Nhánh | Module | File |
|---|---|---|
| B1 danh tính + `requester_context` | Bảo mật/M4 | `B01-xac-thuc.md` |
| B2 sàng lọc injection (L2–L4) | M1 | `B02-sang-loc-injection.md` |
| B3–B5 intent (model đa nhãn → LLM dự phòng, D-32), phạm vi, tách ý | M1 | `B03-B05-phan-loai-tach-y.md`, `nen-tang/P11-huan-luyen-model.md` |
| B6–B7 chẩn đoán chủ động | M3 | `B06-B07-chan-doan.md` |
| B8–B9 tra cứu, kiểm căn cứ | M2 | `B08-B09-tra-cuu.md` |
| B10 trả lời / deflection | M2 + M1 | `B10-tra-loi-deflection.md` |
| B11 bổ sung thông tin, dựng Action | M1 + M4 | `B11-bo-sung-thong-tin.md` |
| B19 xác nhận | M4 | `B19-xac-nhan.md` |
| Runner, routing, E9 | M4 | `nen-tang/P1-langgraph-runtime.md` |

**Được làm:** gọi LLM gateway, RAG, tool **đọc**; đổi trạng thái qua `goto()`; tác dụng phụ nội bộ qua `effects.once`.
**Cấm:** gọi tool ghi; gọi `policy_engine` (trừ qua B12); dùng `raw_request` ngoài B2–B3 và B10; gọi thẳng hàm thông báo/tạo phiếu/tạo ticket con.

**Yêu cầu chức năng:**

- FR-T2-1: 4 loại yêu cầu.
- FR-T2-2: hỏi lại tối đa 3 lượt, mỗi lượt tối đa 2 slot.
- FR-T2-3: trả lời thông tin luôn có trích dẫn hợp lệ.
- FR-T2-4: tách câu nhiều ý thành ticket con; ticket cha tổng hợp bằng đối soát trạng thái con từ DB, không dựa vào đếm sự kiện (D-17). Ticket con không tự nhắn người dùng; cha gửi **đúng một tin mỗi lượt người dùng** **[Chốt B5; cơ chế D-31]**.
- FR-T2-5: không bao giờ kết luận "không tồn tại" khi hệ thống lỗi.
- FR-T2-6 **[Đề xuất D-20]**: khi slot mới bổ sung ở B11 là tham số của tool chẩn đoán (`ToolSpec.arg_slots`), chẩn đoán lại một lần trước khi dựng Action (bật bằng `REDIAGNOSE_ON_NEW_SLOT`).

**Yêu cầu phi chức năng:**

- p95 lượt đầu < 15 giây, lượt sau < 8 giây **[Chốt 14.2]**.
- Mọi bước có span.

**Đạt khi:** cổng 3 và 5 **[Chốt]** — TC02, 04, 05, 06, 11, 12, 14–18, 28 xanh; TC32 (ticket con, crash giữa chừng) xanh; intent macro-F1 ≥ 0,85; Recall@5 ≥ 0,8.

---

## T3 — Kiểm soát (M5–M7)

**Chức năng:** quyết định hành động có được làm không, ai phải duyệt, và ghi lại mọi quyết định với lý do đọc được.

| Nhánh | Module | File |
|---|---|---|
| B12–B14 luật + LLM hiệu chỉnh | M5 | `B12-B14-danh-gia-rui-ro.md` |
| B15–B16 phê duyệt, SLA, xung đột lợi ích | M6 | `B15-B16-phe-duyet.md` |
| B20, E0–E9, L2, ghi đè | M7 | `B20-audit-escalate-L2.md` |

**Được làm:**

- Đọc `Action`, `requester_context`, diagnostics, trích đoạn tài liệu.
- Gọi LLM strong ở B14.
- Tạo phiếu duyệt (qua `effects.once`; tối đa một phiếu `pending` mỗi ticket — `ux_approvals_one_pending`).
- Ghi `audit_logs`, `escalations`, `approvals`.

**Cấm:**

- Đọc `raw_request` hoặc `conversation` (kiểm bằng import-linter + chụp prompt).
- Gọi LLM khi luật đã khớp.
- Tạo phiếu duyệt cho luật `deny`.
- Tự thực thi khi hết hạn duyệt.

**Yêu cầu chức năng:**

- FR-T3-1: mọi ticket qua M5 có `decided_by`.
- FR-T3-2: nhiều luật khớp → chặt nhất thắng.
- FR-T3-3: thiếu dữ kiện → điều kiện không thỏa.
- FR-T3-4: 3 trường hợp xung đột lợi ích chuyển Trưởng BP.
- FR-T3-5: từ chối phải có lý do.
- FR-T3-6: 8 điểm log đủ trường; khóa idempotency audit gồm `(ticket_id, step, event, turn_id, loop_seq)` (D-18).
- FR-T3-7 **[Đề xuất D-27]**: escalate vì intent độ tin cậy thấp ghi `event=intent_low_confidence` và `escalations.reason_detail`.

**Yêu cầu phi chức năng:**

- Lớp luật < 5 ms.
- Audit append-only ở tầng DB.
- Hai người bấm duyệt cùng lúc → đúng 1 lần thực thi (TC33).

**Đạt khi:** cổng 4 và 6 **[Chốt]**; 20 luật có ca khớp và ca suýt khớp; 8 test `decision_math`; TC33 xanh.

---

## T4 — Thực thi (B17, B18)

**Chức năng:** thực hiện đúng `Action` đã được cho phép, một cách an toàn. Chi tiết: `B17-B18-thuc-thi.md`.

**Được làm:** giữ credential `svc_executor`; gọi adapter ghi; ghi `transaction_log`; hoàn tác khi `reversible`.

**Cấm:**

- Retry lệnh ghi.
- Thực thi khi hash lệch.
- Thực thi khi kiểm lại luật ra `deny`.
- Thực thi khi người yêu cầu **hoặc** người thụ hưởng (`requested_for`) đã bị vô hiệu hóa **[D-15, sửa v1.2]**.
- Tự chạy lại lệnh ghi khi `transaction_log` có bản ghi `begun` chưa kết thúc (lệnh bị gián đoạn) — chuyển L2 để người kiểm tra.

**Yêu cầu chức năng:**

- FR-T4-1: kiểm lại luật + hash + trạng thái của cả người yêu cầu và người thụ hưởng trước khi ghi.
- FR-T4-2: hoàn tác theo 3 mức.
- FR-T4-3: ghi chú bàn giao nêu rõ đã làm đến đâu.

**Yêu cầu phi chức năng:** timeout ghi 5 giây, không retry **[Chốt 17.3]**.

**Đạt khi:** TC02 gọi đúng 1 lần; TC21, TC26 xanh; test mạng `svc_agent` gọi endpoint ghi → 403; test người thụ hưởng bị vô hiệu hóa → không ghi, E5.

---

## T5 — Monitor (M9)

**Chức năng:** nhìn thấy hệ thống, không bao giờ điều khiển nó **[Chốt 17.9]**. Chi tiết: `nen-tang/P9-monitor-M9.md`.

| Thành phần | Nguồn | Người xem |
|---|---|---|
| `/api/health` | DB, Qdrant, mock, ml-service, LLM | Vận hành |
| Dashboard nghiệp vụ | `tickets`, `audit_logs`, `escalations` | Trưởng BP (toàn bộ), L1 (phần của mình) |
| Dashboard AI/LLMOps | `turns`, `spans`, `llm_calls` | Dev |
| Cảnh báo | Bảng luật 17.9.3 + 3 luật mới từ `security_events` | Trưởng BP, dev |
| Drift (Nên có) | Phân bố intent, điểm truy hồi, tỉ lệ E3, tỉ lệ `intent_filter_fallback` theo tuần | Trưởng BP |

**Luật cảnh báo mới** **[Đề xuất]**:

- `refresh_reuse_detected` (luôn báo).
- `permission_denied` > 10 lần/5 phút từ một user.
- `policy_saved` (luôn báo).
- Tỉ lệ B2 phải gọi LLM > 30% trong ngày (dấu hiệu model phân loại xuống cấp).

**Được làm:** SELECT bằng role `app_monitor`; tạo bản ghi `alerts` qua một endpoint riêng của M7.
**Cấm:** gọi `goto()`; sửa `policy.json`; ghi bảng nghiệp vụ.

**Yêu cầu chức năng:** mọi luật cảnh báo chỉ dừng ở mức "báo người". Mọi chỉ số và hàng đợi L2 lọc `tickets.is_parent = false` (D-30).

**Yêu cầu phi chức năng:** truy vấn dashboard < 2 giây trên 10.000 ticket (index theo `created_at`, `exit_code`).

**Đạt khi:** import-linter xanh; role `app_monitor` INSERT vào `audit_logs` → lỗi; 8 + 4 luật cảnh báo có test.

---

## T6 — Nền tảng dùng chung

Các cổng chung mà mọi nhánh đi qua. Không nhánh nào gọi thẳng ra ngoài **[Chốt 17]**.

| Thành phần | File | Việc làm | Đạt khi (tóm tắt) |
|---|---|---|---|
| LangGraph runtime | `P1-langgraph-runtime.md` | State, routing theo `next`, `interrupt()`, runner, E9; `effects.once` (D-18); khóa phiên trên lock pool (D-19); `parent_wait` đối soát ticket con (D-17); `recover()` giữ `turn_id` | Khởi động lại vẫn chạy tiếp, không lặp thông báo/phiếu duyệt; TC29, TC32 |
| LLM gateway | `P2-llm-gateway.md` | Router fast/strong, API/local, structured output, cache, retry, trace | Đổi API ↔ local chỉ đổi cấu hình; JSON hợp lệ ≥ 99% sau retry |
| RAG | `P3-rag-pipeline.md` | Ingest có version, chunk theo token bge-m3 (D-21), hybrid + RRF, rerank, fallback bỏ lọc intent (D-23), mở rộng đoạn lân cận cho B10 (D-24) | Recall@5 ≥ 0,8; false-grounding ≤ 5% trên tập không trả lời được (D-22); ablation 4 cấu hình (D-25) |
| ml-service | `P4-ml-service.md` | embed, rerank, classify (injection), `classify_intent` (D-32), `count_tokens`; hai model phân loại do nhóm huấn luyện (P11) | Nạp model 1 lần; p95 rerank 20 đoạn < 2 giây; `truncated` = 0 khi ingest |
| Tool registry + mock | `P5-tool-registry-mock.md` | Khai báo tool (`arg_slots`), retry đọc, circuit breaker, adapter, `/_admin/faults` | 245 test hợp đồng |
| Auth | `P6-auth-bao-mat.md` | Dịch vụ cho T1 | Xem T1 |
| DB | `P7-db-thay-doi.md` | 22 bảng (thêm `side_effects`, `child_notices`), `tickets.is_parent`, 3 role, trigger append-only, `ux_approvals_one_pending` | Migration trên DB trống |
| Worker | `P1` mục 7 | Quét hạn chờ 15 giây/lần, nhắc duyệt, phát timeout qua guard | 200 phiếu hết hạn trong 1 phút → xử lý hết trong 1 chu kỳ |

---

## T7 — Đánh giá (M8)

**Chức năng:** chạy ma trận thực nghiệm trên dữ liệu đã khóa, tái lập được **[Chốt mục 10]**. Chi tiết: `nen-tang/P8-danh-gia-M8.md`.

**Được làm:**

- Chọn chiến lược (`manual`, `full_auto`, `rule_only`, `llm_only`, `hybrid`, `hybrid_guarded`).
- Bật/tắt RAG, tool, chẩn đoán chủ động.
- Chạy ablation truy hồi (dense / BM25 / hybrid / hybrid + rerank) trên tập dev **[Đề xuất D-25]**.
- Dùng cache LLM không hết hạn.
- Tính mọi chỉ số trên ticket lá (`is_parent = false`), để câu nhiều ý không bị đếm trùng (D-30).

**Cấm:**

- Chạy khi `EVAL_MODE=false`.
- Fit calibrator hoặc chọn ngưỡng (kể cả `RETRIEVAL_THRESHOLD`) trên tập test (code từ chối) **[Chốt]**.
- Mở ra Internet.

**Đạt khi:** cổng 8 **[Chốt]**; 20 kịch bản chạy 2 lần với cache → kết quả giống hệt.

---

## Bảng ánh xạ nhánh → tầng → trạng thái → mã thoát

| Nhánh | Tầng | Trạng thái vào | Trạng thái ra | Mã thoát |
|---|---|---|---|---|
| B1 | T1 + T2 | `S_NEW` | `S_SCREENING`, `S_BLOCKED` | — (`invalid_credentials`, `repeated_auth_failure`) |
| B2 | T1 + T2 | `S_SCREENING` | `S_CLASSIFYING`, `S_BLOCKED` | E0 |
| B3–B5 | T2 | `S_CLASSIFYING` | `S_DIAGNOSING`, `S_ESCALATED`, (ticket con); cha: `S_CONFIRMING` ↔ `S_CLASSIFYING`, rồi `S_RESOLVED`/`S_REJECTED`/`S_ESCALATED` (D-29, D-31) | E1, E2 (vượt vòng lặp); cha không có mã thoát (D-30) |
| B6–B7 | T2 | `S_DIAGNOSING` | `S_RETRIEVING`, `S_ESCALATED`; chế độ chẩn đoán lại → quay về B11 (D-20) | E2 |
| B8–B9 | T2 | `S_RETRIEVING` | → B10, `S_ESCALATED` | E2, E3 |
| B10 | T2 | `S_RETRIEVING` | `S_CONFIRMING`, → B11 | E3 (trích dẫn không hợp lệ) |
| B11 | T2 | `S_RETRIEVING`, `S_CLARIFYING` | `S_ASSESSING`, `S_CLARIFYING`, `S_DIAGNOSING` (D-20, sau cờ), `S_ESCALATED` | E4 |
| B12–B14 | T3 | `S_ASSESSING` | `S_EXECUTING`, `S_PENDING_APPROVAL` (qua B15), `S_ESCALATED` | E5 |
| B15–B16 | T3 | `S_ASSESSING` → `S_PENDING_APPROVAL` | `S_EXECUTING`, `S_REJECTED`, `S_ESCALATED` | E6 |
| B17–B18 | T4 | `S_EXECUTING` | `S_CONFIRMING`, `S_ESCALATED` | E7, E5 |
| B19 | T2 | `S_CONFIRMING` | `S_RESOLVED`, `S_ESCALATED` | E8 |
| B20 | T3 | mọi trạng thái kết thúc | đóng; ticket L2 mở lại (`reopened_as_new`) chạy từ B1 (D-26) | — |
| Mọi node | T6 (boundary) | bất kỳ | `S_ESCALATED` | E9 |

---

## Lịch sử thay đổi

| Phiên bản | Ngày | Thay đổi |
|---|---|---|
| v1.2 | 25/09/2026 | D-15 sửa (T4 kiểm cả người thụ hưởng); D-17/18/19 vào T6; D-20 (FR-T2-6, bảng ánh xạ); D-21…D-25 vào RAG/T7; D-26, D-27, D-28; DB 21 bảng; TC32, TC33 |
| v1.3 | 25/09/2026 | D-29 (T6 runtime), D-30 (T5/T7 chỉ tính ticket lá), D-31 (T0, T2 FR-T2-4, bảng ánh xạ); 22 bảng |
| v1.4 | 25/09/2026 | B3 dùng model phân loại đa nhãn trước (D-32); ml-service thêm `classify_intent` |
