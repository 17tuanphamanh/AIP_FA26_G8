# B10 — Chỉ cần trả lời hay cần hành động (deflection)

> **Tầng:** T2 · **Module:** M2 + M1 · **Objective:** 1 · **Phase:** 3
> **Trạng thái vào:** `S_RETRIEVING` · **Ra:** `S_CONFIRMING` (đã trả lời) | → B11 (cần hành động) | `S_ESCALATED` (E3: không có trích dẫn hợp lệ; E2: LLM lỗi)
> **Bản vá v1.2:** D-18 (gửi tin + đặt hạn idempotent), D-24 (ghép chunk liền kề làm ngữ cảnh)

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
| Nhánh trước | B8–B9 (đã có căn cứ: top-5 với điểm ≥ ngưỡng) |
| Nhận vào | `redacted_request`, `retrieved`, `intent`, `conversation` (≤ 4 tin), `kb_version` |
| Giao cho nhánh sau | Nhánh info: câu trả lời đã gửi, `status=S_CONFIRMING`, `next=confirm_wait`, `resolution_path=deflected`. Nhánh action: `need_type=action`, `next=b11_slots` |
| Ai dùng đầu ra | B19 (xác nhận), B11 (dựng Action), `lineage`, M9 (deflection rate, tỉ lệ có trích nguồn) |

**Chuyển trạng thái của nhánh [Chốt 2.1]:**

| Từ | Sự kiện | Sang |
|---|---|---|
| `S_RETRIEVING` | Có tài liệu, chỉ cần thông tin | `S_CONFIRMING` |
| `S_RETRIEVING` | Có tài liệu, cần hành động | → B11 (`S_ASSESSING` hoặc `S_CLARIFYING`) |
| `S_RETRIEVING` | Trích dẫn không hợp lệ / output guard chặn | `S_ESCALATED` E3 **[Đề xuất]** |

### 0.3. Đặc tả gốc đã chốt

- **Không phải yêu cầu nào cũng dẫn tới hành động.** Ba dạng:

  | Dạng | Ví dụ | Kết quả |
  |---|---|---|
  | Hỏi thông tin thuần | "VPN công ty dùng cổng nào?" | Trả lời kèm nguồn |
  | Hỏi quy trình | "Muốn xin quyền truy cập thì làm thế nào?" | Mô tả quy trình |
  | Cần hướng dẫn tự làm | "Outlook báo lỗi 0x8004010F" | Hướng dẫn từng bước |

- Nhánh này **không đi qua bộ phân loại rủi ro** vì không có hành động nào được thực hiện. Nó đóng góp vào deflection rate.
- Thiết kế ban đầu bỏ sót nhánh này vì mặc định mọi yêu cầu đều dẫn tới hành động.
- **Mã giả gốc:** `need = llm.structured_output(NeedTypeSchema{type: info|action})` → info: `generate_grounded_answer` + `send_to_user(with_citations=True)` → `S_CONFIRMING`.
- **Công nghệ [Chốt mục 6, 11]:**
  - LLM fast phân loại.
  - LLM strong viết câu trả lời có trích dẫn — **giữ API, không chuyển local**, vì chất lượng tiếng Việt quan trọng.
  - Code hậu kiểm trích dẫn; không có trích dẫn hợp lệ → E3.
- **Chi phí [Chốt 15.1]:**
  - B10 info/action: fast, 100%, khoảng 800 token vào và 30 ra.
  - B10 trả lời: strong, khoảng 30% ca, khoảng 2.500 token vào và 350 ra.
- **Groundedness [Chốt 17.4]:** tách câu trả lời thành từng ý, LLM chấm từng ý có được đoạn trích hỗ trợ không, người soát 30 mẫu. Bản offline là Phải có; kiểm trực tuyến là Nên có.

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC04 | Hỏi VPN công ty dùng cổng nào (mức hỗ trợ 1) | Trả lời kèm trích nguồn, không sinh Action |
| TC05 | Hướng dẫn khắc phục lỗi VPN (mức hỗ trợ 2) | Người dùng tự làm, đóng ticket; **đủ mọi bước** kể cả bước nằm ở chunk liền sau (D-24) |
| Canary | Chuỗi bí mật cài trong KB/prompt | Không xuất hiện trong câu trả lời |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- Không trả lời nếu không có trích dẫn hợp lệ do code xác minh.
- Chỉ dùng top-5 đã truy hồi (và chunk liền kề cùng tài liệu của chúng — D-24); trích dẫn chỉ được trỏ vào top-5.
- Gửi tin và đặt hạn ở node này, không ở node chờ; cả hai đi qua `effects.once`.
- **Mã quyết định dùng trong file:** D-18, D-24 (bản vá v1.2), D-31 (v1.3); các điểm "[Đề xuất]" khác nằm trong bảng mục 6.

---

## 1. Mục đích và vì sao tồn tại

Không phải yêu cầu nào cũng dẫn tới hành động **[Chốt]**. Nhánh này xử lý ba dạng:

- Hỏi thông tin ("VPN dùng cổng nào?").
- Hỏi quy trình.
- Cần hướng dẫn tự làm ("Outlook báo lỗi 0x8004010F").

Nhánh này làm ra chỉ số deflection rate, và **không đi qua M5** vì không có hành động nào được thực hiện **[Chốt]**. Thiết kế ban đầu bỏ sót nhánh này vì mặc định mọi yêu cầu đều dẫn tới hành động **[Chốt]**.

**Nhận xét về độ an toàn khi phân loại sai [Suy luận]:** nhầm theo cả hai chiều đều an toàn. Câu cần hành động bị nhầm thành info → chỉ trả lời, không làm gì. Câu info bị nhầm thành action → sang B11/M5 và vẫn được kiểm. Chi phí của nhầm lẫn chỉ là trải nghiệm, không phải rủi ro.

## 2. Sơ đồ cấu tạo

```
S_RETRIEVING (đã có retrieved top-5)
   ▼
[10a] LLM fast · b10_need_type · {type: info|action, confidence}
   ├─ action ─────────────────────────────────────────────► B11 (b11_slots)
   ▼ info
[10b'] expand_for_answer(top-5): ghép ±1 chunk liền kề cùng tài liệu (D-24, P3 mục 6.1)
   ▼
[10b] LLM strong · b10_answer · chỉ dùng các khối bằng chứng trên · schema AnswerOut
   │   {answer_markdown, citations:[chunk_id…], steps?:[…]}
   ▼
[10c] Hậu kiểm bằng CODE (không LLM):
   ├─ citations rỗng, hoặc có chunk_id ∉ retrieved (top-5) ─► E3 (không có căn cứ hợp lệ)
   ├─ output guard: có mẫu bí mật / đoạn prompt hệ thống / PII của người khác ─► thay câu an toàn + E3
   ▼ hợp lệ
effects.once("notify_user") answer + nguồn [title › heading] ; effects.once("deadline_set") confirm 48h
   ▼
S_CONFIRMING (confirm_wait)
```

## 3. Công nghệ tại nhánh

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Phân loại info/action | LLM **fast** | Tác vụ dễ, gọi ở mọi ticket (chi phí 15.1) **[Chốt]** |
| Mở rộng ngữ cảnh | `rag.expand_for_answer` (Qdrant scroll theo `doc_id`, `seq`) | D-24 — hướng dẫn nhiều bước không bị cắt |
| Viết câu trả lời | LLM **strong**, temperature 0 | Chất lượng tiếng Việt quan trọng; **giữ API, không chuyển local** **[Chốt mục 11]** |
| Kiểm trích dẫn | Code thuần | LLM có thể bịa trích dẫn nghe rất hợp lý; chỉ code xác minh chắc chắn được |
| Output guard | Dùng lại mẫu của privacy guard + chuỗi canary | **[Chốt 17.6: kiểm đầu ra]** |
| Gửi tin, đặt hạn | `effects.once` | D-18 — không gửi trùng khi node chạy lại sau sự cố |

## 4. Hợp đồng node

```python
class NeedTypeOut(BaseModel):
    type: Literal["info", "action"]; confidence: float

class AnswerOut(BaseModel):
    answer_markdown: str = Field(max_length=2500)
    citations: list[str] = Field(min_length=1)       # chunk_id — phải thuộc top-5 (anchor)
    steps: list[str] | None = None                   # mức hỗ trợ 2: hướng dẫn từng bước
    cannot_answer: bool = False                       # LLM tự nhận không đủ căn cứ
```

- **Đọc:** `redacted_request`, `retrieved`, `intent`, `conversation` (≤ 4 tin).
- **Ghi:** `need_type`, `answer` (tham chiếu), `status`, `next`, `exit_code`, `resolution_path="deflected"`.

## 5. Luồng xử lý chi tiết

```python
async def b10_route(state):
    try:
        need, _ = await llm.complete("fast", "b10_need_type",
                   {"text": state["redacted_request"], "evidence_titles": titles(state["retrieved"])}, NeedTypeOut)
    except (LLMUnavailable, LLMSchemaError):
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B10", event="llm_unavailable", exit_code="E2")

    if need.type == "action":
        return goto(state, S_RETRIEVING, next_node="b11_slots", step="B10", event="needs_action", need_type="action")

    evidence = await rag.expand_for_answer(state["retrieved"])                 # D-24
    try:
        ans, meta = await llm.complete("strong", "b10_answer",
                     {"question": state["redacted_request"], "evidence": evidence}, AnswerOut)
    except (LLMUnavailable, LLMSchemaError):
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B10", event="llm_unavailable", exit_code="E2")

    valid_ids = {c.chunk_id for c in state["retrieved"]}                       # chỉ top-5 (anchor)
    if ans.cannot_answer or not ans.citations or not set(ans.citations) <= valid_ids:
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B10", event="invalid_citation", exit_code="E3")
    if output_guard.violates(ans.answer_markdown):
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B10", event="output_guard_block", exit_code="E3")

    await effects.once(state, "notify_user", notify_user, state,
                       render_answer(ans, state["retrieved"]), needs="confirm",
                       step="B10")                             # con: ghi child_notices (D-31)
    await effects.once(state, "deadline_set", deadlines.set, state["ticket_id"], "confirm",
                       hours=48, step="B10")
    lineage.record(state, prompt=meta, kb_version=state["kb_version"])     # [Chốt 17.1]
    return goto(state, S_CONFIRMING, next_node="confirm_wait", step="B10", event="deflected_info_only",
                need_type="info", resolution_path="deflected")
```

**Vì sao `expand_for_answer` không đổi tập trích dẫn hợp lệ (D-24):** chunk liền kề chỉ là ngữ cảnh đọc thêm. Mỗi khối bằng chứng gửi cho LLM mang `anchor_chunk_id` của chunk top-5 gốc, và prompt yêu cầu trích dẫn theo anchor. Nhờ vậy hậu kiểm trích dẫn bằng code (`citations ⊆ top-5`) giữ nguyên, và ngưỡng căn cứ của B9 vẫn áp lên đúng các chunk đã được chấm điểm.

**Ticket con của yêu cầu nhiều ý (D-31, v1.3):** hàm `notify_user` tự kiểm `state["parent_ticket_id"]`. Với ticket con, lời nhắn được ghi vào `child_notices` thay vì gửi, và `deadlines.set` không đặt hạn (hạn do ticket cha giữ). Ticket cha gom mọi lời nhắn thành **một** tin mỗi lượt người dùng **[Chốt B5]** (P1 mục 8.1–8.2). Logic của nhánh này không đổi. Tham số `needs="confirm"` cho cha biết ý này cần người dùng xác nhận.

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| Hai lời gọi (fast phân loại, strong viết) | Chỉ trả tiền model mạnh cho khoảng 30% ca cần trả lời **[Chốt 15.1]** |
| Ba tầng chống bịa | (1) ngưỡng truy hồi ở B9; (2) bắt buộc trích dẫn, code kiểm; (3) prompt "chỉ dùng tài liệu, không có thì nói không biết" **[Chốt]** |
| Trích dẫn sai → E3, không phải "trả lời không kèm nguồn" | Trả lời sai về quy trình IT còn tệ hơn không trả lời |
| Ghép chunk liền kề làm ngữ cảnh (D-24) | Hướng dẫn nhiều bước trải qua 2–3 chunk; `dedupe_by_doc` chỉ giữ 1 chunk mỗi tài liệu → thiếu bước (L-09) |
| Gửi tin + đặt hạn **trước** node chờ, qua `effects.once` | Node chờ chạy lại khi resume → tránh gửi 2 lần **[Chốt]**; process chết sau khi gửi → không gửi lại (D-18) |
| Không cache ngữ nghĩa ở bản đầu | Là mức "Có thể" **[Chốt 17.5]** |

## 7. Cấu hình

- Prompt `b10_need_type`, `b10_answer` (version vào lineage); `b10_answer` yêu cầu trích theo `anchor_chunk_id`
- `CONFIRM_TIMEOUT=48h` **[Chốt]**
- Trần token strong ≤ 6.000 **[Chốt]**; bằng chứng mở rộng ≤ 4.000 token (cắt khối điểm thấp trước)
- `RAG_NEIGHBOR_WINDOW=1` **[Đề xuất D-24]**

## 8. Dữ liệu, DB, điểm log

- **`audit_logs`:** bước B10 (`deflected_info_only` / `needs_action` / `invalid_citation`).
- **`lineage`:** prompt, model, `kb_version`, commit **[Chốt]**.
- **`tickets`:** `resolution_path="deflected"` ghi ở B20.
- **`side_effects`:** `notify_user`, `deadline_set` (D-18).

## 9. Trace và giám sát

- **Span:** `llm:b10_need_type`, `rag:expand` (D-24), `llm:b10_answer`.
- **M9:**
  - Deflection rate.
  - Tỉ lệ có trích nguồn **[Chốt chỉ số]**.
  - Tỉ lệ `invalid_citation`.
- **Groundedness offline** (Phase 8): tách ý, LLM chấm từng ý có được đoạn trích hỗ trợ không, người soát 30 mẫu **[Chốt 17.4]**.

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| "VPN công ty dùng cổng nào?" | Trả lời kèm nguồn, không sinh Action | TC04 **[Chốt]** |
| "Kết nối VPN lỗi, làm sao?" | Hướng dẫn từng bước (`steps`), đủ bước kể cả phần ở chunk liền sau | TC05 **[Chốt]** |
| LLM trích `chunk_id` không có trong top-5 (kể cả trích chunk liền kề) | E3 | — |
| Câu vừa hỏi vừa cần làm ("cổng nào, và cấp lại VPN giúp") | Đã được B3/B5 tách từ trước; nếu lọt thì `need=action` → B11 | — |
| Câu trả lời chứa chuỗi canary | Output guard chặn → E3 | Bộ test lộ dữ liệu **[Chốt 17.6]** |
| Process chết sau khi gửi câu trả lời, trước checkpoint | Chạy lại B10 → `effects.once` không gửi lại | — |

## 11. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Unit | Hậu kiểm trích dẫn | Rỗng / ngoài tập / hợp lệ → E3 / E3 / qua |
| Integration (ScriptedLLM) | TC04, TC05 | Có trích dẫn, không có `intended_action` **[Chốt cổng 3]** |
| Integration | TC05 với hướng dẫn trải 3 chunk | Bằng chứng gửi LLM chứa cả 3 chunk; trích dẫn vẫn là chunk top-5 (D-24) |
| Integration | Resume `confirm_wait` 2 lần | Đúng 1 tin nhắn trả lời |
| Integration | Giết process sau `notify_user`, trước checkpoint → recover | Đúng 1 tin nhắn (D-18) |
| Probe | Canary | Tỉ lệ lộ = 0 |
| Đánh giá (Phase 8) | Groundedness offline | Báo cáo tỉ lệ ý được hỗ trợ + citation precision |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** B8–B9, P2, P3 (`expand_for_answer`), P1 (`effects.once`).
- **Phase:** 3.
- **Việc còn mở:** kiểm chứng groundedness trực tuyến trước khi gửi là mức Nên có (tăng độ trễ và chi phí) **[Chốt 17.4]**.

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Kiểm groundedness trực tuyến (Nên có) | Sau `b10_answer`, gọi thêm `eval_groundedness` với vai trò fast; ý nào không được hỗ trợ thì bỏ ý đó hoặc chuyển E3 | Tăng độ trễ khoảng 1–2 giây; đo trước khi bật |
| Trả lời kèm hành động gợi ý ("Bạn có muốn mình gia hạn luôn không?") | Sinh `suggested_action` → nếu người dùng đồng ý, tạo lượt mới đi B11 | Không tự thực hiện; vẫn qua M5 |
| Scale | Cache ngữ nghĩa cho câu hỏi thông tin phổ biến (Có thể), khóa chứa `kb_version` | Không cache khi `kb_version` đổi |
| Đổi model viết câu trả lời | Đổi `roles.strong` trong `llm.yaml`; chạy lại groundedness offline trên bộ cố định | Không fallback sang model yếu |
| Tách thành module "Answering" | `b10_route` + prompt + hậu kiểm; phụ thuộc `retrieve()`, `expand_for_answer()` và LLM gateway | Hậu kiểm trích dẫn luôn bằng code |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| Nhiều `invalid_citation` → E3 | `llm_calls` của `b10_answer` (bản ghi đầy đủ khi `EVAL_MODE`) | Prompt không yêu cầu đúng định dạng `chunk_id`; model trích tiêu đề thay vì id; model trích chunk liền kề thay vì anchor |
| Hướng dẫn thiếu bước | Span `rag:expand` có chạy không; `seq` của chunk | `RAG_NEIGHBOR_WINDOW=0`; chunk thiếu `seq`; ingest cũ chưa có `seq` |
| Câu hỏi hành động bị trả lời như câu hỏi thông tin | Đầu ra `b10_need_type` | Thiếu ví dụ few-shot; câu vừa hỏi vừa nhờ làm |
| Người dùng nhận 2 câu trả lời | Số lần gọi `notify_user`; `side_effects` kind `notify_user` | Gửi tin trong `confirm_wait` thay vì ở B10; gửi không qua `effects.once` |
| Câu trả lời sai số liệu (cổng, thời hạn) | `kb-facts.md` so với tài liệu KB | Tài liệu KB lệch với facts; ingest bản cũ |

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.2 | Bản vá: ghép chunk liền kề làm ngữ cảnh (D-24), gửi tin + đặt hạn qua `effects.once` (D-18) |
| 25/09/2026 | 1.3 | Ticket con không tự gửi câu trả lời, để lại notice `needs=confirm` cho cha gom (D-31) |
