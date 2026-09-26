# B19 — Người dùng xác nhận kết quả

> **Tầng:** T2 · **Module:** M4 · **Objective:** 1 (+ số liệu trải nghiệm cho Obj 3) · **Phase:** 3
> **Trạng thái vào:** `S_CONFIRMING` (từ B10 deflection hoặc B18) · **Ra:** `S_RESOLVED` | `S_ESCALATED` (E8)

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
| Nhánh trước | B10 (đã trả lời thông tin) hoặc B18 (đã thông báo kết quả thực thi). Ticket thường: cả hai đã đặt hạn 48 giờ. Ticket con: không đặt hạn, kết quả nằm trong `child_notices` chờ cha gom (D-31) |
| Nhận vào | Sự kiện resume: `confirmed` / `unresolved` / `timeout`. Ticket con: sự kiện do ticket cha chuyển xuống (`via_parent=True`) |
| Giao cho nhánh sau | `S_RESOLVED` kèm `close_reason`, hoặc `S_ESCALATED` E8; luôn `next=b20_audit` |
| Ai dùng đầu ra | B20, M9 (tỉ lệ giải quyết một lượt, E8), M8 (chỉ số trải nghiệm) |

**Chuyển trạng thái của nhánh [Chốt 2.1]:**

| Từ | Sự kiện | Sang |
|---|---|---|
| `S_CONFIRMING` | Người dùng xác nhận đã xong | `S_RESOLVED` |
| `S_CONFIRMING` | Người dùng báo chưa xong | `S_ESCALATED` → E8 |
| `S_CONFIRMING` | Không phản hồi quá 48 giờ | `S_RESOLVED` (tự động) |

### 0.3. Đặc tả gốc đã chốt

- **Timeout ở B19 khác B16:** hết hạn thì đóng ticket, không escalate. Lý do: hành động đã xong, không còn rủi ro tồn đọng, và người dùng im lặng thường là đã hài lòng.
- **Phải đánh dấu `auto_closed=True` và `close_reason=resolved_auto_timeout_48h`**, để khi tính chỉ số không nhầm với xác nhận thật.
- **Sự kiện muộn:** ticket đã tự đóng mà người dùng mới vào xác nhận hoặc báo lỗi → **không** mở lại ticket cũ (tránh ticket đã tính vào chỉ số `auto_closed` "sống lại" âm thầm). Nếu còn vấn đề → tạo ticket **mới**, tham chiếu ticket cũ.
- **E8:** ưu tiên Thường. Thông báo "Mình chuyển cho kỹ thuật viên kiểm tra lại".
- **[Chốt B5]** Yêu cầu nhiều ý: người dùng gửi một câu thì chỉ nhận một câu trả lời tổng hợp. Vì vậy với ticket con, việc hỏi xác nhận đi qua ticket cha (D-31, mục 5.1).

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC22 | Người dùng báo chưa giải quyết được | E8 |
| TC01 | "Được rồi, cảm ơn" | `resolved_user_confirmed` |
| 48 giờ | Im lặng | `resolved_auto_timeout_48h`, `auto_closed=True` |
| Biến thể TC27 | Phản hồi sau khi đã tự đóng | 409 + `late_event` |
| TC34, TC36 (D-31) | Yêu cầu nhiều ý | Người dùng xác nhận **một lần** cho mọi ý qua ticket cha; mỗi con vẫn ra `resolved_user_confirmed` hoặc E8 riêng |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- Tự đóng không bao giờ được tính là xác nhận thật.
- Không mở lại ticket đã đóng.
- Chỉ chủ ticket được xác nhận **[Đề xuất]**.
- Ticket con không nhận xác nhận trực tiếp từ người dùng; chỉ nhận sự kiện do cha chuyển xuống (D-31).
- **Mã quyết định dùng trong file:** D-08, D-31 (v1.3).

---

## 1. Mục đích và vì sao tồn tại

Hệ thống chỉ biết một yêu cầu thật sự đã xong khi người dùng xác nhận. B19 cũng là nguồn cho hai chỉ số: "tỉ lệ giải quyết trong một lượt" và E8 (người dùng báo chưa xong) **[Chốt]**.

## 2. Sơ đồ cấu tạo

```
(B10 hoặc B18 đã gửi kết quả + đặt hạn confirm 48h — side effect ở node TRƯỚC)
   ▼
S_CONFIRMING ─ confirm_wait: interrupt({"wait":"confirm"})
   │  Ticket thường: API POST /api/tickets/{id}/confirm {confirmed: bool, note?}
   │                 (require ticket:confirm + can_read_ticket + là chủ ticket)
   │  Ticket con:    sự kiện do cha chuyển xuống (parent_reply_wait, D-31);
   │                 API confirm gọi thẳng vào con → 409
   │  Worker: 48h → deliver_event(timeout)   (ticket con: timeout do cha chuyển xuống)
   ▼
   ├─ confirmed=true   ─► S_RESOLVED  close_reason=resolved_user_confirmed       ─► B20
   ├─ confirmed=false  ─► S_ESCALATED E8 (ghi phản hồi người dùng)              ─► B20
   └─ timeout          ─► S_RESOLVED  auto_closed=True,
                                      close_reason=resolved_auto_timeout_48h    ─► B20
Phản hồi đến sau khi ticket đã đóng → 409 + late_event ; nếu vẫn còn vấn đề:
   tạo ticket MỚI tham chiếu ticket cũ (không mở lại ticket cũ) [Chốt 8.3]
```

## 3. Công nghệ

`interrupt()` (P1), guard `deliver_event`, worker APScheduler, bảng `wait_deadlines` (kind=`confirm`). Ticket con: vòng `parent_reply_wait` của cha (P1 mục 8.2).

## 4. Hợp đồng

```python
class ConfirmIn(BaseModel):
    confirmed: bool
    note: str | None = Field(default=None, max_length=1000)   # đi qua privacy guard trước khi dùng
    satisfaction: int | None = Field(default=None, ge=1, le=5)  # "Có thể" [Chốt 16.1]

class ParentReplyIn(BaseModel):                                # D-31: một lần trả lời cho mọi ý
    items: dict[str, ConfirmIn | ClarifyAnswerIn]              # key = child_ticket_id
```

- **Đọc:** `ticket_id`, `requester_context`, `parent_ticket_id`.
- **Ghi:** `status`, `next`, `exit_code`, `close_reason`, `auto_closed`, `user_feedback`.

## 5. Luồng xử lý chi tiết

```python
async def confirm_wait(state):
    ev = interrupt({"wait": "confirm"})
    if ev["kind"] == "timeout":
        return goto(state, S_RESOLVED, next_node="b20_audit", step="B19", event="auto_closed_no_response_48h",
                    auto_closed=True, close_reason="resolved_auto_timeout_48h")
    if ev["confirmed"]:
        return goto(state, S_RESOLVED, next_node="b20_audit", step="B19", event="user_confirmed",
                    close_reason="resolved_user_confirmed", user_feedback=ev.get("satisfaction"))
    return goto(state, S_ESCALATED, next_node="b20_audit", step="B19", event="user_reported_unresolved",
                exit_code="E8", user_feedback=ev.get("note"))
```

**Chỉ chủ ticket mới được xác nhận:** `can_read_ticket` cộng thêm điều kiện `p.user_id == requester_id`. L1 xem được ticket nhưng không xác nhận thay người dùng được **[Đề xuất]**.

### 5.1. Ticket con của yêu cầu nhiều ý [Chốt B5; cơ chế Đề xuất D-31]

`confirm_wait` của con **giữ nguyên mã** ở trên. Chỉ nguồn sự kiện khác:

1. B10/B18 của con không gửi tin mà ghi notice `needs=confirm` vào `child_notices`, không đặt hạn, rồi đánh thức cha.
2. Khi mọi con đã dừng, cha gửi **một** tin: mỗi ý một khối, có nút "Đã ổn"/"Chưa ổn" và ô ghi chú.
3. Người dùng gửi **một** lần `POST /api/tickets/{cha}/reply`. API kiểm chủ ticket, privacy guard cho ghi chú, đủ mọi ý (thiếu → 422).
4. Cha chuyển `{"kind":"confirmed","confirmed":…,"note":…}` xuống `confirm_wait` của từng con (`effects.once`, kind `child_event`). Mỗi con tự ra `resolved_user_confirmed` hoặc E8 như ticket thường.
5. Hết hạn tin tổng hợp (48 giờ, hoặc 24 giờ nếu cùng tin có câu hỏi B11) → cha chuyển `timeout` xuống → con ra `resolved_auto_timeout_48h` **[Chốt nhãn]**.

**Vì sao xác nhận vẫn nằm ở con, chỉ đường đi qua cha:** mỗi ý có kết quả riêng. Người dùng có thể thấy ý 1 ổn mà ý 2 chưa. Giữ `confirm_wait` ở con thì E8 chỉ gắn vào đúng ý bị lỗi, `close_reason` của từng ý vẫn là một trong 8 giá trị **[Chốt]**, và chỉ số "giải quyết trong một lượt" vẫn tính trên ticket lá (D-30).

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| Timeout ở B19 → đóng (khác B16 → escalate) | Hành động đã xong, không còn rủi ro tồn đọng; im lặng thường là đã hài lòng **[Chốt]** |
| Nhãn riêng `resolved_auto_timeout_48h` + `auto_closed` | Không thổi phồng tỉ lệ giải quyết — trung thực số liệu cho Obj 3 **[Chốt 9.2]** |
| Phản hồi muộn không mở lại ticket cũ | Ticket đã tính vào chỉ số không được "sống lại" âm thầm **[Chốt 8.3]** |
| E8 ưu tiên Thường | Hành động đã thực hiện, chỉ cần kiểm tra lại **[Chốt]** |
| Ticket con: xác nhận một lần qua cha, kết quả vẫn ghi ở từng con | Đúng câu chốt "một câu trả lời tổng hợp" mà không mất độ chi tiết theo từng ý (D-31) |

## 7. Cấu hình

`CONFIRM_TIMEOUT=48h` **[Chốt]**.

## 8. Dữ liệu, DB, điểm log

`close_reason` và `auto_closed` được ghi ở điểm log 8 (B20) **[Chốt]**. `wait_deadlines.fired_at` được cập nhật khi worker phát timeout. Ticket con: hạn nằm ở `wait_deadlines` của **cha**; lần chuyển sự kiện xuống con ghi `side_effects` kind `child_event`.

## 9. Trace và giám sát

**M9** (chỉ tính ticket lá, D-30):

- Tỉ lệ xác nhận thật so với tự đóng.
- Tỉ lệ E8.
- Điểm hài lòng trung bình (nếu làm).

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| "Được rồi, cảm ơn" | `resolved_user_confirmed` | TC01 |
| "Vẫn chưa vào được" | E8 | TC22 |
| Im lặng 48 giờ | `resolved_auto_timeout_48h`, `auto_closed=True` | — |
| Xác nhận sau khi đã tự đóng | 409 + `late_event`; gợi ý tạo ticket mới | biến thể TC27 |
| L1 bấm xác nhận thay người dùng | 403 | — |
| Người dùng gọi thẳng API confirm của ticket con | 409 "Vui lòng trả lời trong hội thoại chung" | D-31 |
| Nhiều ý: "Ý 1 ổn, ý 2 chưa" | Con 1 `resolved_user_confirmed`, con 2 E8 | TC36 |

## 11. Kiểm thử và tiêu chí đạt

- **FakeClock 48 giờ:** nhãn đúng.
- **Sự kiện muộn:** 409 và trạng thái không đổi.
- **TC22:** E8.
- **Resume 2 lần:** không sinh 2 bản ghi đóng (audit idempotent).
- **TC34, TC36:** một lần `POST /reply` → mỗi con nhận đúng một sự kiện; không tin nào gửi riêng từ con.

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P1 (kể cả mục 8.2 cho ticket con), B10, B17–B18.
- **Phase:** 3 (ticket thường), 5 (ticket con).
- **Việc còn mở:** không (D-31 đã chốt theo đặc tả).

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Khảo sát hài lòng (Có thể) | Trường `satisfaction` 1–5 trong `ConfirmIn` | Không bắt buộc; không ảnh hưởng `close_reason` |
| Nhắc trước khi tự đóng | Worker gửi nhắc ở 24 giờ | Vẫn tự đóng ở 48 giờ với nhãn riêng; với yêu cầu nhiều ý, nhắc do cha gửi |
| Kênh xác nhận khác (email một chạm) | Link có token một lần, gọi cùng API | Qua guard sự kiện muộn và kiểm chủ ticket; ticket con vẫn chỉ qua cha |
| Scale | Không có điểm nghẽn | — |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| Tỉ lệ giải quyết cao bất thường | Tỉ lệ `resolved_auto_timeout_48h` | Gộp nhầm tự đóng với xác nhận thật |
| Ticket không bao giờ tự đóng | `wait_deadlines` `kind=confirm` | B10/B18 quên đặt hạn; worker không chạy; ticket con: cha lỗi → lưới an toàn P1 mục 8.2 |
| Xác nhận muộn mở lại ticket | Guard `deliver_event` | Gọi thẳng graph thay vì qua guard |
| Người dùng bị hỏi xác nhận nhiều lần cho một câu | `child_notices`, `side_effects` kind `notify_user` | Con gửi tin trực tiếp thay vì qua `notify_user` (vi phạm D-31) |

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.3 | Ticket con xác nhận một lần qua ticket cha (D-31); thêm mục 5.1, TC34/TC36 |
