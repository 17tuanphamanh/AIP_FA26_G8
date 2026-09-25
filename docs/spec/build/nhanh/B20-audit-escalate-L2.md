# B20 — Ghi audit, đóng ticket; E0–E9 → hàng đợi L2; ghi đè quyết định (M7)

> **Tầng:** T3 · **Module:** M7 (+ UI L2) · **Objective:** 2 (truy vết, giải thích được) · **Phase:** 2 (B20 khung), 4 (đủ 8 điểm log, ghi đè), 7 (L2 + UI)
> **Trạng thái vào:** mọi trạng thái kết thúc (`S_RESOLVED`, `S_REJECTED`, `S_BLOCKED`, `S_ESCALATED`) · **Ra:** đóng ticket (escalate thì nằm ở hàng đợi L2 tới khi L2 đóng)
> **Bản vá v1.2:** D-17 (con đánh thức cha, không gửi dữ liệu), D-18 (tạo escalation + thông báo idempotent), D-26 (ticket mở lại chạy từ B1), D-27 (`reason_detail`)

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

**Mã quyết định mới (chờ nhóm xác nhận):** D-01…D-33 — danh sách đầy đủ, trạng thái và câu hỏi GVHD ở `build/decisions.md`. Các mã mà file này dùng được liệt kê ở mục 0.5 (file nền tảng: trong thân bài).

### 0.2. Vị trí của nhánh trong luồng

| | Nội dung |
|---|---|
| Nhánh trước | **Mọi** nhánh: B1/B2 (BLOCKED), B3–B11 (E1–E4, E9), B12–B14 (E5), B16 (REJECTED, E6), B17 (E7, E5), B19 (RESOLVED, E8), `parent_wait` (cha đã tổng hợp), boundary (E9) |
| Nhận vào | Toàn bộ state cuối: `status`, `exit_code`, `block_reason`, `close_reason`, `escalation_reason_detail`, bộ đếm, thời gian, `risk`, `execution` |
| Giao cho nhánh sau | Kết thúc thread. Nếu escalate: bản ghi `escalations` cho hàng đợi L2. Nếu là con: đánh thức cha (`wake_parent`) |
| Ai dùng đầu ra | L2 (UI), Trưởng BP (dashboard), M8 (toàn bộ chỉ số), M9 (cảnh báo), kiểm toán |

### 0.3. Đặc tả gốc đã chốt

- **Ba đặc điểm của luồng:**
  1. Mọi nhánh đều đi qua bước ghi audit, kể cả từ chối, lỗi, escalate.
  2. Mọi điểm thoát hội tụ về L2; không ticket nào bị bỏ rơi.
  3. Ba điểm có giới hạn vòng lặp.
- **Điểm log 8 (B20):** `final_state`, `exit_code`, `block_reason`, **`close_reason`**, `total_turns`, `total_duration`.
- **Vì sao cần `close_reason`:** `final_state` chỉ có 4 giá trị, `exit_code` chỉ có nghĩa với ca escalate. Không trả lời được "bao nhiêu % RESOLVED là do im lặng 48 giờ" hay "bao nhiêu ca deny đóng vì L2 xác nhận từ chối, so với mở ticket mới".
- **Các trường audit bắt buộc:**

  | Trường | Để làm gì |
  |---|---|
  | `step` | Biết quyết định xảy ra ở bước nào |
  | `intended_action` | Hành động thật, không phải lời nói |
  | `decided_by` | Ablation |
  | `policy_decision` | Phân biệt allow / approval_required / deny |
  | `reason` | Giải thích được |
  | `approver_id` | Truy trách nhiệm |

- **Ma trận xử lý ngoại lệ — thông báo và ưu tiên:**

  | Mã | Thông báo | Ưu tiên |
  |---|---|---|
  | E0 | Trung tính, không tiết lộ | Cao (an ninh) |
  | E1 | "Cần kỹ thuật viên hỗ trợ" | Thường |
  | E2 | "Hệ thống đang gặp sự cố" | Cao (hạ tầng) |
  | E3 | "Chưa có thông tin" | Thường + cần bổ sung KB |
  | E4 | "Chuyển kỹ thuật viên" | Thường |
  | E5 | "Cần xem xét kỹ hơn" | Cao |
  | E6 | "Đang được xử lý" | Cao (có SLA) |
  | E7 | "Có sự cố khi thực hiện" | Rất cao |
  | E8 | "Kiểm tra lại" | Thường |
  | E9 | — | Ngang E2 |

- **E5 do deny/rủi ro cao:** "L2 xử lý" **không bao giờ** là tự thực hiện lại hành động bị cấm. L2 chỉ có hai lựa chọn:
  - (a) Xác nhận từ chối và đóng.
  - (b) Mở ticket **mới** đi lại từ B12 với `intended_action` dựng lại.

  Chuyển bị cấm: `S_ESCALATED` (deny) → `S_EXECUTING` của cùng Action.

  *Ghi chú v1.2:* câu (b) ở trên là trích nguyên văn `NGU-CANH-DAY-DU.md` Phần VI nguyên tắc 5. `huong-dan-xay-dung-he-thong-2.md` cổng 7 lại ghi "tạo ticket chạy từ B1". Bản build chọn **B1** (D-26, mục 4.3) — cách này vẫn đi qua B12–B17 như NGU-CANH yêu cầu. Chờ nhóm và GVHD xác nhận (Q11).
- **Ghi đè (override):**
  - L1 thấy quyết định sai → bấm "Ghi đè" + lý do → `OverrideEntry{ticket_id, original_decision, override_decision, overrider_id, reason, timestamp}`.
  - Dùng để tính tỉ lệ quyết định sai không bị phát hiện, và loại yêu cầu hay bị ghi đè.
  - Không đổi trạng thái ticket.
- **Thiết kế DB vòng 3:** `tickets` 21 cột, ghi một lần ở B20; `audit_logs` là chủ sở hữu duy nhất của mọi quyết định/sự kiện. **Việc còn mở:** thứ tự ưu tiên E5/E9; tên 3 kết quả đóng của L2; cấu trúc 4 phần của ghi chú bàn giao.

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC23 | Agent tự xử lý, L1 ghi đè sau | Ghi override log, không đổi trạng thái |
| Cổng 4 | Script kiểm audit | 100% ticket e2e đủ trường ở mọi điểm log; không có token/mật khẩu |
| Cổng 7 | Ca deny: L2 chọn "hoàn tất" | 422 |
| Cổng 7 | L2 "mở ticket mới" | Chạy từ B1, liên kết ticket cũ (D-26) |
| Cổng 7 | L2 đóng ticket | Điểm log 8 với lý do đóng đúng |
| TC12 | Ticket cha | Đóng đúng khi mọi con xong, một tin nhắn tổng hợp |
| TC32 (mới, D-17) | Con kết thúc trước khi cha vào `parent_wait` | Cha vẫn đóng đúng |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- Không đường thoát nào bỏ qua B20.
- `tickets` chỉ ghi một lần.
- Audit append-only.
- L2 không hoàn tất ca deny.
- Mỗi ticket escalate có đúng một dòng `escalations`, kể cả khi B20 chạy lại (D-18).
- **Mã quyết định dùng trong file:** D-05, D-14, D-17, D-18, D-26, D-27 (bản vá v1.2), D-30, D-31 (v1.3).

---

## 1. Mục đích và vì sao tồn tại

- **Mọi nhánh đều đi qua B20**, kể cả từ chối, lỗi, escalate. Không có đường thoát nào không để lại dấu vết **[Chốt 4.2]**.
- **Mọi mã thoát E0–E9 hội tụ về một hàng đợi L2**, có mức ưu tiên và ghi chú bàn giao. Không ticket nào bị bỏ rơi **[Chốt]**.
- **Ghi đè (override)** lưu vết khi L1 hoặc Trưởng BP thấy quyết định của agent sai. Đây là dữ liệu để đánh giá và cải tiến **[Chốt 5.4]**.

## 2. Sơ đồ cấu tạo

```
mọi nhánh ──goto(..., next_node="b20_audit")──► [B20] b20_audit
   │ 1 tổng hợp: final_state, exit_code, block_reason, close_reason, total_turns, total_duration
   │ 2 điểm log 8 (audit_logs, idempotent)                                   [Chốt]
   │ 3 UPDATE tickets (GHI MỘT LẦN): final_state, exit_code, close_reason,
   │     resolution_path, aggregate_status, auto_closed, total_turns, ...   [Chốt DB vòng 3]
   │ 4 exit_code ≠ ∅ ? effects.once("escalation_create"): INSERT escalations(priority,
   │     handoff_note, reason_detail) ; effects.once("notify_user")  ──► hàng đợi L2
   │ 5 là ticket con? wake_parent(parent_id) — chỉ đánh thức, không mang dữ liệu (D-17)
   │ 6 cảnh báo M7→alerts nếu E0 / repeated_auth_failure / E7 / E9 tăng
   ▼
 END (thread)

Hàng đợi L2 (UI) ── L2 mở ── đọc handoff_note + hội thoại (checkpoint, ≤90 ngày)
   POST /api/escalations/{id}/close {result, note}      require escalation:handle + can_close_escalation
     result ∈ {completed, confirmed_denial, reopened_as_new}
       ca deny/rủi ro cao: "completed" → 422 [Chốt] ; "reopened_as_new" → tạo ticket MỚI chạy từ B1
       (D-26), liên kết ticket cũ, intended_action dựng lại từ đầu
     → tickets.close_reason = resolved_after_escalation | resolved_after_deny_review
     → điểm log 8 bổ sung (đóng bởi L2)

Ghi đè (TC23): POST /api/tickets/{id}/override {override_decision, reason}
   require decision:override + can_override → INSERT audit_logs(step="OVERRIDE", ...)
   KHÔNG đổi trạng thái ticket [Chốt cổng 4]
```

## 3. Công nghệ tại nhánh

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Audit | Bảng `audit_logs` append-only (role + trigger), CHECK domain đầy đủ | Không sửa được lịch sử (D-05) **[Chốt DB]** |
| Kết quả cuối | `tickets` (21 cột, ghi một lần ở B20) | Dữ liệu ghi một lần thì nhân đôi vẫn an toàn **[Chốt DB vòng 3]** |
| Escalate | Bảng `escalations` + `exit_code_priority`; tạo qua `effects.once` | **[Chốt khung]**; không tạo trùng khi B20 chạy lại (D-18) |
| Đánh thức cha | `wake_parent(parent_id)` | D-17 — cha tự đối soát từ DB, sự kiện đến sớm/mất không làm cha kẹt |
| Script kiểm audit | `app/audit/verify.py` (CLI) | Cổng 4: 100% ticket e2e đủ trường **[Chốt]** |

## 4. Hợp đồng

### 4.1. Mức ưu tiên hàng đợi L2 [Chốt ma trận 7 + 16.4; thứ tự cụ thể là Suy luận, cần chốt]

| Hạng | Mã | Nhãn | Lý do |
|---|---|---|---|
| 1 | E7 | Rất cao | Có thể đang dở dang trên hệ thống thật |
| 2 | E0 | An ninh | Sự cố an ninh. (B1 `repeated_auth_failure` chỉ gửi cảnh báo Trưởng BP, không có mã E nên không vào hàng đợi L2 **[Chốt 1.3]**) |
| 3 | E6 | Có SLA | Người dùng đang chờ một việc đã được đánh giá là cần duyệt |
| 4 | E2, E9 | Hạ tầng / lỗi hệ thống | E9 ngang E2 **[Chốt bổ sung E9]** |
| 5 | E5 | Cao | Hành động bị chặn vì rủi ro |
| 6 | E1, E3, E4, E8 | Thường | E3 kèm cờ "cần bổ sung KB" |

### 4.2. Ghi chú bàn giao 4 phần [Đề xuất cấu trúc cho việc còn mở số 3 của thiết kế DB]

```python
class HandoffNote(BaseModel):
    request: str            # (1) Yêu cầu: tóm tắt đã che + intent + Action (nếu có)
    done_so_far: str        # (2) Agent đã làm gì: chẩn đoán, tài liệu tra được, bước thực thi, hoàn tác
    why_escalated: str      # (3) Vì sao chuyển: mã E, reason_detail, lý do đọc được, luật/p nếu có
    next_for_l2: str        # (4) L2 cần làm gì + cảnh báo (ví dụ ca deny: KHÔNG thực hiện lại Action này)
```

`next_for_l2` được sinh bằng **mẫu theo mã E** (không dùng LLM), để tất định và không bịa.

### 4.3. Ba kết quả đóng của L2 [Đề xuất tên cho việc còn mở số 2]

| `close_result` | Ý nghĩa | `close_reason` của ticket |
|---|---|---|
| `completed` | L2 hoàn tất đúng việc agent định làm (cho E1–E4, E7, E8, E9; E6 chờ Q2) | `resolved_after_escalation` |
| `confirmed_denial` | L2 xác nhận từ chối là đúng | `resolved_after_deny_review` (ca deny) hoặc `resolved_after_escalation` |
| `reopened_as_new` | Mở ticket mới **chạy lại từ B1**, liên kết ticket cũ (D-26) | theo loại ca như trên |

E6 có được `completed` hay không phụ thuộc Q2 (hỏi GVHD) **[Chốt: câu hỏi]**. Mặc định chặn `completed` cho E6 cho tới khi có câu trả lời, vì an toàn trước.

**Vì sao ticket mới chạy từ B1 (D-26, L-11):**

- Chạy từ B1 thì ticket mới **vẫn đi qua B12–B17**, nên thỏa yêu cầu của NGU-CANH ("đi qua lại toàn bộ B12–B17").
- Ngoài ra, ticket mới còn được chụp lại `requester_context` từ AD (B1), sàng lọc (B2) và chẩn đoán lại (B6) trên trạng thái **hiện tại** — đúng tinh thần "không kế thừa gì từ ca bị deny".
- `intended_action` được dựng lại từ đầu ở B11, không copy từ ticket cũ. Nhờ vậy không có đường nào để hành động bị deny "đi tắt" vào B12.
- Nội dung yêu cầu của ticket mới là ghi chú của L2 (đi qua privacy guard như mọi yêu cầu khác), người gửi vẫn là người gửi gốc.

## 5. Luồng xử lý chi tiết

```python
async def b20_audit(state):
    final = summarize_final(state)                                    # final_state, codes, durations
    audit_point_8(state, **final)                                     # [Chốt]: final_state, exit_code,
                                                                      # block_reason, close_reason,
                                                                      # total_turns, total_duration
    await tickets.finalize_once(state["ticket_id"], **final)          # UPDATE ... WHERE final_state IS NULL
    if state.get("exit_code"):                                        # cha không bao giờ có exit_code (D-30)
        await effects.once(state, "escalation_create", escalations.create, step="B20",   # D-18
                           ticket_id=state["ticket_id"], exit_code=state["exit_code"],
                           priority=PRIORITY[state["exit_code"]],
                           reason_detail=state.get("escalation_reason_detail"),        # D-27
                           handoff_note=build_handoff(state), is_deny_case=is_deny(state))
        await effects.once(state, "notify_user", notify_user, state,
                           ESCALATION_MSG[state["exit_code"]], step="B20")             # [Chốt 7.1]
    if state.get("parent_ticket_id"):
        await wake_parent(state["parent_ticket_id"])                  # D-17: chỉ đánh thức
    await alerts.maybe_raise(state, final)
    return {"status": state["status"], "next": END}
```

`tickets.finalize_once` dùng `WHERE final_state IS NULL`, nên resume hay chạy lại cũng không ghi đè kết quả cuối. `escalations` và thông báo đi qua `effects.once`, nên B20 chạy lại cũng không tạo dòng hay tin nhắn thứ hai.

**`wake_parent` thay cho `deliver_event(…, child_done)` (D-17, L-01):** bản 1.0 gửi sự kiện `child_done` kèm kết quả con tới cha qua guard sự kiện muộn. Nếu con kết thúc trước khi cha kịp checkpoint ở `parent_wait`, guard trả 409 và kết quả con bị mất. Bản v1.2: `finalize_once` đã ghi `final_state` của con vào DB (bước 3) **trước** khi đánh thức cha (bước 5), và `parent_wait` tự đọc DB. `wake_parent` chỉ còn là tín hiệu; nếu cha chưa ở `parent_wait` thì không làm gì và không ghi `late_event`. Mã giả `parent_wait` ở P1 mục 8.1.

**Thông báo người dùng theo mã [Chốt 7.1]:**

| Mã | Thông báo |
|---|---|
| E0 | Trung tính, không tiết lộ lý do |
| E2, E7 | Thừa nhận sự cố hệ thống |
| E3 | "Mình chưa có thông tin về việc này" |
| E1, E4, E8 | "Mình chuyển cho kỹ thuật viên" |
| E5 | "Yêu cầu cần được xem xét kỹ hơn" |
| E6 | "Yêu cầu đang được xử lý, sẽ phản hồi sớm" |
| E9 | Như E2 |

**Ticket con và ticket cha (D-30, D-31, v1.3):**

- **Ticket con:** thông báo "chuyển kỹ thuật viên" đi qua `notify_user`, nên được ghi vào `child_notices` (needs=`none`) và xuất hiện trong tin tổng hợp của cha, không gửi riêng. Dòng `escalations` của con vẫn được tạo bình thường: việc của L2 nằm ở con.
- **Ticket cha:** tới B20 qua `parent_wait` với `aggregate_status`, **không có `exit_code`** nên không tạo `escalations`; `close_reason = NULL` (không giá trị nào trong 8 giá trị **[Chốt]** mô tả "đóng vì tổng hợp"). Tin tổng kết cuối đã do `parent_wait` gửi trước khi vào B20, nên B20 của cha không gửi thêm gì.
- **Hàng đợi L2 và chỉ số** lọc `tickets.is_parent = false`, để không đếm trùng.

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| B20 là node cuối duy nhất | Một chỗ duy nhất bảo đảm "không thoát mà không có dấu vết" |
| `tickets` chỉ ghi ở B20 | Tránh hai nguồn sự thật lệch nhau **[Chốt DB vòng 3]** |
| `close_reason` bắt buộc | `final_state` và `exit_code` không đủ phân biệt "xác nhận thật" với "tự đóng 48 giờ", hay "L2 hoàn tất" với "L2 xác nhận deny" **[Chốt 9.2]** |
| Ca deny: chặn `completed` (422) | L2 không phải cửa sau vượt qua luật; chỉ xác nhận hoặc mở ticket mới đi lại từ đầu **[Chốt nguyên tắc 5]** |
| Ticket mở lại chạy từ B1 (D-26) | Chụp lại danh tính và trạng thái hiện tại; vẫn đi qua B12–B17 |
| Ghi đè không đổi trạng thái | Là dữ liệu đánh giá, không phải cách "sửa" ticket **[Chốt]** |
| Ghi chú bàn giao theo mẫu, không LLM | Tất định; không bịa việc đã làm |
| Con chỉ đánh thức cha, cha đọc DB (D-17) | Không phụ thuộc thứ tự sự kiện; cha không bao giờ kẹt |
| Escalation + thông báo qua `effects.once` (D-18) | Không có dòng `escalations` trùng khi B20 chạy lại |

## 7. Cấu hình

- Bảng `exit_code_priority` (seed từ mục 4.1)
- Mẫu thông báo theo mã (i18n file)
- Thời gian lưu 90 ngày cho hội thoại/checkpoint **[Chốt]**

## 8. Dữ liệu, DB, điểm log

- **Điểm log 8 [Chốt]:** `final_state`, `exit_code`, `block_reason`, `close_reason`, `total_turns`, `total_duration`.
- **`escalations`:** `escalation_id`, `ticket_id`, `exit_code`, `priority`, `reason_detail` (D-27), `handoff_note` (JSON 4 phần), `is_deny_case`, `assigned_to`, `close_result`, `closed_by`, `closed_at`, `new_ticket_id`.
- **`side_effects`:** `escalation_create`, `notify_user` (D-18).
- **Override:** `audit_logs` với `step="OVERRIDE"`, `original_decision`, `override_decision`, `overrider_id`, `reason` **[Chốt 5.4]**.

## 9. Trace và giám sát

M9 đọc toàn bộ nhánh này:

- Automation, escalation, deflection.
- Hết hạn duyệt.
- Phân bố `decided_by`, top luật, số lần ghi đè **[Chốt 16.3]**.
- Số E9 tách khỏi E2 **[Chốt bổ sung E9]**.
- Phân bố `reason_detail` trong từng mã E (ví dụ E1: `out_of_scope` so với `intent_low_confidence`) (D-27).
- Danh sách lỗ hổng KB (E3).

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| L1 ghi đè một ca AUTO | Có bản ghi override, trạng thái không đổi | TC23 |
| L2 chọn "hoàn tất" ca deny | 422 | cổng 7 |
| L2 "mở ticket mới" | Ticket mới chạy từ B1, có liên kết, `intended_action` dựng lại | cổng 7 |
| Ticket con kết thúc | `final_state` con ghi trước, rồi đánh thức cha; cha đóng khi đủ con | TC12 |
| Con kết thúc trước khi cha vào `parent_wait` | `wake_parent` không làm gì; cha tự đối soát khi tới `parent_wait` | TC32 (D-17) |
| B20 chạy lại khi resume hoặc phục hồi | Không ghi trùng (audit idempotent, `finalize_once`, `effects.once`) | — |
| Bất kỳ exception nào ở B20 | E9 — boundary vẫn bọc B20; lần chạy lại chỉ ghi phần còn thiếu | — |

## 11. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Tĩnh | Mọi node có đường tới `b20_audit` | Xanh (P1) |
| Integration | Mỗi mã E0–E9 | Đúng 1 dòng `escalations`, đúng mức ưu tiên, `handoff_note` đủ 4 phần |
| Integration | B20 chạy lại 2 lần cho ca E7 | Vẫn đúng 1 dòng `escalations`, 1 thông báo (D-18) |
| Integration | 8 giá trị `close_reason` | Mỗi giá trị có ít nhất 1 ca sinh ra |
| Integration | E1 do confidence thấp | `escalations.reason_detail='intent_low_confidence'` (D-27) |
| Integration | TC32 | Cha đóng đúng dù con kết thúc trước (D-17) |
| Script | `python -m app.audit.verify` trên toàn bộ ticket e2e | 100% đủ trường ở mọi điểm log áp dụng; log không chứa token/mật khẩu **[Chốt cổng 4]** |
| Integration | TC23; deny → 422; mở ticket mới chạy từ B1 | **[Chốt cổng 4, 7]** |
| DB | UPDATE `audit_logs` | Lỗi (D-05) |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P1 (`effects.once`, `wake_parent`, `parent_wait`), P6, P7; mọi nhánh.
- **Phase:** 2 (khung), 4 (8 điểm log + override + script kiểm), 7 (UI L2).
- **Việc còn mở:**
  - Thứ tự ưu tiên chính xác của E5/E9 (việc còn mở số 1 của thiết kế DB).
  - Tên 3 kết quả đóng (mục 4.3).
  - Cấu trúc ghi chú bàn giao (mục 4.2).
  - Q2 về E6.
  - Q11 / D-26: ticket mở lại chạy từ B1 hay B12.

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Đẩy ticket escalate sang ITSM thật (Jira SM, ServiceNow) | Adapter `TicketingSystem`: B20 gọi thêm `create_incident(handoff_note)` qua `effects.once` | Bản ghi `escalations` nội bộ vẫn là nguồn sự thật; lỗi ITSM không làm mất escalate |
| Xuất audit ra SIEM | Job đọc `audit_logs` và `security_events` bằng role `app_monitor`, đẩy ra syslog/JSON | Chỉ đọc |
| Xuất audit một ticket ra JSON (Có thể) **[Chốt 16.5]** | Endpoint dùng quyền `audit:read:*` | Che dữ liệu cá nhân |
| Scale | `audit_logs` tăng nhanh nhất → partition theo tháng; index `(ticket_id)`, `(step, created_at)` | Không UPDATE/DELETE |
| Tách thành module "Governance" | `audit/` + `escalations` + script `verify` + UI L2 | Hợp đồng 8 điểm log |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| Ticket không có điểm log 8 | Chạy `audit.verify`; đồ thị `ROUTES` | Một nhánh kết thúc không qua `b20_audit` |
| `escalations` trùng | `side_effects` kind `escalation_create` | Tạo escalation không qua `effects.once` |
| Cha không đóng | `tickets.final_state` của các con; worker đối soát; span `parent_wait` | Con lỗi trước bước 3 (`finalize_once`) → E9 → cần chạy lại; `parent_wait` không đọc DB (vi phạm D-17) |
| Dashboard sai tỉ lệ | Phân bố `close_reason` | Code đọc `final_state` thay vì `close_reason` |
| L2 không biết bắt đầu từ đâu | `handoff_note` | Phần `done_so_far` hoặc `next_for_l2` trống do mẫu theo mã chưa đủ |

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.2 | Bản vá: `wake_parent` thay `child_done` (D-17); escalation + thông báo qua `effects.once` (D-18); ticket mở lại chạy từ B1 và giải thích mâu thuẫn tài liệu (D-26); `reason_detail` (D-27); thêm TC32 |
| 25/09/2026 | 1.3 | Cha đóng không `exit_code`, `close_reason=NULL`, không `escalations` (D-30); thông báo escalate của con đi qua tin tổng hợp (D-31) |
