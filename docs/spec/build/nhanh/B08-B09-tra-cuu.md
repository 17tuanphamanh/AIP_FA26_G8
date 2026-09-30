# B8–B9 — Tra cứu Knowledge Base và kiểm tra căn cứ

> **Tầng:** T2 · **Module:** M2 · **Objective:** 1 · **Phase:** 3 (KB VPN — cổng K1), 5 (≥ 16 tài liệu — cổng K2)
> **Trạng thái vào:** `S_RETRIEVING` · **Ra:** → B10 (cùng trạng thái) | `S_ESCALATED` (E2 lỗi hệ thống, E3 không có căn cứ)
> **Tài liệu nền:** `nen-tang/P3-rag-pipeline.md`, `nen-tang/P4-ml-service.md`
> **Bản vá v1.2:** D-21 (chunk theo token), D-22 (chọn ngưỡng có câu âm tính), D-23 (chạy lại không lọc intent), D-25 (KB có tài liệu gây nhiễu + ablation)

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
| Nhánh trước | B6 (slot đã được làm giàu từ chẩn đoán) |
| Nhận vào | `redacted_request`, `intent`, `slots`, `requester_context` |
| Giao cho nhánh sau | `retrieved` (top-5 `ChunkRef`), `retrieval_score`, `kb_version`, `intent_filter_fallback`, `next=b10_route` |
| Ai dùng đầu ra | B10 (câu trả lời có trích dẫn, phân loại info/action), B14 (trích đoạn quy định cho LLM rủi ro), `lineage`, M9 (lỗ hổng KB, tín hiệu B3 phân sai) |

**Chuyển trạng thái của nhánh [Chốt 2.1]:**

| Từ | Sự kiện | Sang |
|---|---|---|
| `S_RETRIEVING` | Không có tài liệu làm căn cứ (RAG hợp lệ nhưng điểm thấp) | `S_ESCALATED` → E3 |
| `S_RETRIEVING` | RAG lỗi hệ thống sau khi hết retry | `S_ESCALATED` → E2 |
| `S_RETRIEVING` | Có tài liệu | → B10 (các nhánh `S_CONFIRMING`, `S_ASSESSING`, `S_CLARIFYING` do B10/B11 quyết định) |

### 0.3. Đặc tả gốc đã chốt

- **Kỹ thuật:** embedding, hybrid search BM25 + vector, rerank; top_k=20 → rerank → top_n=5.
- **Ba nguyên tắc (vòng rà soát 2):**
  - EMPTY RESULT ≠ ERROR.
  - 429/TIMEOUT/5xx = SYSTEM ERROR.
  - SYSTEM ERROR ≠ retry vô hạn.
- **Bảng phân biệt:**

  | Tình huống | Ý nghĩa | Mã |
  |---|---|---|
  | RAG trả kết quả (kể cả rỗng hoặc điểm thấp) | `NO_EVIDENCE` | E3 |
  | RAG ném lỗi kết nối/timeout/5xx/429 sau `TOOL_RETRY` lần | `SYSTEM_ERROR` | E2 |
  | Lỗi tạm thời, còn lượt retry | Thử lại có backoff | — |

- **Chống bịa, 3 tầng:**
  1. Điểm cao nhất dưới ngưỡng → coi như không có căn cứ.
  2. Mọi câu trả lời phải kèm ít nhất một trích dẫn.
  3. Prompt ghi rõ: "chỉ dùng thông tin trong tài liệu được cung cấp, nếu không có thì nói không biết".
- **Lý do:** một chính sách bịa có thể dẫn người dùng làm sai quy trình bảo mật.
- **Thông báo:**
  - E2: "Hệ thống đang gặp sự cố".
  - E3: "Mình chưa có thông tin về việc này", đánh dấu cần bổ sung KB (đầu vào cho Trưởng BP và L2).
- **Vòng đời dữ liệu [Chốt 17.4]:**
  - Front matter → làm sạch → chia đoạn theo heading → metadata → embed + BM25 → index mới theo `kb_version` → đổi alias → xóa index cũ.
  - `kb_version` = mã băm mọi cặp `(doc_id, version)`.
- **Nội dung KB:** 16 tài liệu (4 mỗi loại), 300–800 từ, số liệu khớp `kb-facts.md`. **Cố ý không có** tài liệu MFA (cho TC16). Cổng K1: 5 tài liệu VPN trước Phase 3.

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC16 | KB không có tài liệu liên quan | E3, không bịa chính sách |
| TC28 | RAG lỗi kết nối/timeout | E2 (không phải E3), "hệ thống đang gặp sự cố" |
| Cổng 5 | 30 câu kiểm tra truy hồi | Recall@5 ≥ 0,8 |
| Cổng 3 | Biểu đồ phân phối điểm | Ngưỡng đề xuất cập nhật vào `policy.json` |
| D-22 | ≥ 20 câu không có đáp án | Tỉ lệ trả lời bừa ≤ 5% tại ngưỡng đã chọn |
| D-23 | Câu reset mật khẩu bị B3 gắn nhầm `access` | Vẫn tìm thấy tài liệu account, `intent_filter_fallback=true` |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- E2 và E3 không bao giờ lẫn nhau.
- Chỉ truy vấn trên alias `kb_current`.
- Lọc tài liệu theo mức nhạy của role — **kể cả** ở lần chạy lại không lọc intent.
- Không chunk nào bị model cắt cụt âm thầm.
- **Mã quyết định dùng trong file:** D-09 (ml-service), D-10 (BM25 tiếng Việt trong Qdrant), D-21, D-22, D-23, D-25 (bản vá v1.2).

---

## 1. Mục đích và vì sao tồn tại

Lấy đúng đoạn tài liệu nội bộ làm căn cứ cho mọi câu trả lời và mọi hành động. Không có căn cứ thì không trả lời, vì một chính sách bịa trong môi trường IT có thể khiến người dùng làm sai quy trình bảo mật **[Chốt]**.

B8 và B9 tách rõ hai tình huống **[Chốt, vòng rà soát 2]**:

- **`SYSTEM_ERROR`** (hạ tầng RAG hỏng) → E2.
- **`NO_EVIDENCE`** (RAG chạy bình thường nhưng KB không có tài liệu phù hợp) → E3.

**Hệ quả cần lưu ý [Suy luận]:** B9 nằm **trước** B10, nên cả yêu cầu **hành động** cũng phải có tài liệu KB đạt ngưỡng mới đi tiếp. Độ phủ KB vì vậy giới hạn trực tiếp tỉ lệ tự động hóa: mỗi `action_type` trong `ACTION_METADATA` phải có ít nhất một tài liệu KB tương ứng. Bảng kiểm "action_type ↔ tài liệu" nằm trong cổng K2.

## 2. Sơ đồ cấu tạo

```
S_RETRIEVING
   ▼
build_query(redacted_request, intent, slots[:3])
   ▼
call_with_retry( rag.retrieve(query, requester_context) )          ← P3 mục 6
   │   embed (ml-service) → Qdrant prefetch dense+bm25 (filter intent/enabled/sensitivity)
   │   → RRF top-20 → rerank (ml-service) → top-5, bỏ trùng doc
   │   top_score < ngưỡng ? chạy lại 1 lần KHÔNG lọc intent (giữ sensitivity/enabled) (D-23)
   │
   ├─ lỗi sau 2 lần retry ───────────────────────────► E2  (retrieval_error, SYSTEM_ERROR)
   ▼
[B9] top_score < RETRIEVAL_THRESHOLD hoặc rỗng ──────► E3  (NO_EVIDENCE, đánh dấu lỗ hổng KB)
   ▼
retrieved = [ChunkRef…] , retrieval_score, kb_version, intent_filter_fallback ──► B10 (b10_route)
```

## 3. Công nghệ tại nhánh

Qdrant (hybrid dense + BM25 tiếng Việt, RRF), `bge-m3`, `bge-reranker-v2-m3` qua ml-service, `call_with_retry` dùng chung với B6 **[Chốt]**. Chunk đo bằng tokenizer bge-m3 (≤ 380 token nội dung, D-21) để không đoạn nào bị cắt ở 512 token. Chi tiết và lý do chọn ở P3.

## 4. Hợp đồng node

- **Đọc:** `redacted_request`, `intent`, `slots`, `requester_context`.
- **Ghi:** `retrieved`, `retrieval_score`, `retrieval_error`, `kb_version`, `intent_filter_fallback`, `tool_retry_count`, `status`, `next`, `exit_code`.

```python
class ChunkRef(BaseModel):
    chunk_id: str; doc_id: str; version: int; seq: int; title: str; heading_path: str
    score: float; excerpt: str = Field(max_length=600)
```

## 5. Luồng xử lý chi tiết

```python
async def b08_retrieve(state):
    q = build_query(state["redacted_request"], state["intent"], state["slots"])
    res, err, attempts = await call_with_retry(rag.retrieve, q, state["requester_context"])
    audit_point_3(state, query=q.text, top_score=res.top_score if res else None,
                  doc_ids=[c.doc_id for c in res.chunks] if res else [],
                  retrieval_error=err, tool_retry_count=attempts,
                  kb_version=res.kb_version if res else None,
                  intent_filter_fallback=res.intent_filter_fallback if res else None)  # điểm log 3 [Chốt]
    if err:
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B8",
                    event="rag_system_error_after_retry", exit_code="E2", retrieval_error=err)
    if not res.chunks or res.top_score < policy.RETRIEVAL_THRESHOLD:           # B9
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B9",
                    event="no_grounding", exit_code="E3", retrieval_score=res.top_score,
                    kb_gap_query=q.text)
    return goto(state, S_RETRIEVING, next_node="b10_route", step="B8", event="retrieved",
                retrieved=res.chunks, retrieval_score=res.top_score, kb_version=res.kb_version,
                intent_filter_fallback=res.intent_filter_fallback)
```

**Chạy lại không lọc intent (D-23)** nằm bên trong `rag.retrieve` (P3 mục 6), nên node không đổi cấu trúc. Nếu lần chạy lại tìm thấy tài liệu đạt ngưỡng, luồng đi tiếp bình thường với `intent_filter_fallback=true` — đây là tín hiệu B3 có thể đã phân sai intent, **không** phải lỗi của KB. Lần chạy lại không tính vào `tool_retry_count`.

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| E2 ≠ E3 | Hai cách xử lý khác nhau: E2 → sửa hạ tầng (ưu tiên Cao); E3 → viết thêm tài liệu KB (ưu tiên Thường + đánh dấu lỗ hổng) **[Chốt ma trận 7]** |
| Ngưỡng tính trên **điểm rerank** (0..1) | Điểm RRF không có thang tuyệt đối; điểm cross-encoder sau sigmoid mới so được với ngưỡng **[Suy luận]** |
| Chọn ngưỡng trên bộ có câu **không có đáp án** (D-22) | Chỉ khi có câu âm tính mới đo được tỉ lệ trả lời bừa — đúng loại lỗi mà B9 tồn tại để chặn |
| Chạy lại một lần không lọc intent (D-23) | Lỗi phân loại ở B3 không được biến thành E3 oan; lọc `sensitivity` vẫn giữ |
| Lọc theo `sensitivity` của role | Nhân viên thường không nhận đoạn tài liệu hạn chế (P6 ↔ P3) |
| Chỉ lưu `ChunkRef` trong state | Checkpoint nhẹ (P1 mục 4) |
| B8 chạy **sau** B6 | Slot suy từ chẩn đoán (ví dụ "chứng chỉ hết hạn") làm câu truy vấn chính xác hơn **[Chốt thứ tự]** |

## 7. Cấu hình

- `RETRIEVAL_THRESHOLD=0,6` **[Chốt]** — chọn lại ở Phase 3 theo quy trình P3 mục 7.1 (quét ngưỡng trên 30 câu có đáp án + ≥ 20 câu không có đáp án; ngưỡng thấp nhất mà tỉ lệ trả lời bừa ≤ 5%), cập nhật `policy.json` **[Chốt cổng 3 + Đề xuất D-22]**
- `TOOL_RETRY=2`
- `RAG_TOP_N=5`
- `RAG_INTENT_FALLBACK=true` **[Đề xuất D-23]**

## 8. Dữ liệu, DB, điểm log

- **Điểm log 3 [Chốt]:** `query`, `top_score`, `doc_ids`, `retrieval_error`, `tool_retry_count`; thêm `kb_version`, `intent_filter_fallback`.
- **E3:** `escalations` + `kb_gap_query` → danh sách "lỗ hổng KB" cho Trưởng BP và L2 **[Chốt 16.3, 16.4]**.
- **`lineage`:** `kb_version` của mọi câu trả lời B10 **[Chốt 17.1]**.
- **Nội dung KB:** cổng K2 giữ **16 tài liệu tối thiểu** **[Chốt]**; mục tiêu mở rộng ≥ 50 tài liệu có khoảng 30% tài liệu gây nhiễu **[Đề xuất D-25]** (P3 mục 8).

## 9. Trace và giám sát

- **Span:** `node:b08_retrieve`, `rag:embed`, `rag:search`, `rag:search_nofilter` (D-23), `rag:rerank`.
- **M9:**
  - Tỉ lệ E3 theo tuần.
  - Tỉ lệ `intent_filter_fallback` theo intent (D-23).
  - Số văn bản bị cắt ở 512 token (`truncated`, phải = 0, D-21).
  - Phân phối `top_score` (drift, Nên có).
  - p95 rerank.

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| Qdrant timeout sau 2 lần retry | E2 "Hệ thống đang gặp sự cố" | TC28 **[Chốt]** |
| KB không có tài liệu MFA | E3 "Mình chưa có thông tin về việc này" (cả lần chạy lại cũng không tìm thấy) | TC16 **[Chốt]** |
| Chưa từng ingest (alias chưa có) | E2; `/api/health` đỏ | — |
| Câu chứa mã lỗi hiếm "809" | BM25 kéo đúng tài liệu vào top-5 | — |
| Nhân viên hỏi quy trình nội bộ đánh dấu `restricted` | Đoạn đó bị lọc (cả ở lần chạy lại) → có thể E3 | — |
| B3 gắn nhầm intent | Lần chạy lại không lọc intent tìm thấy → đi tiếp, `intent_filter_fallback=true` | — |
| Hướng dẫn dài, bước cuối nằm cuối tài liệu | Chunk theo token, không bị cắt → bước cuối vẫn tìm được | — |

## 11. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Integration | TC28, TC16 | E2 và E3 đúng, thông báo đúng **[Chốt]** |
| Integration | Filter role | Employee không nhận chunk `restricted`, kể cả ở lần chạy lại |
| Integration | B3 gắn nhầm intent (ScriptedLLM) | Tìm thấy tài liệu đúng; `intent_filter_fallback=true` (D-23) |
| Probe | 30 câu kiểm tra truy hồi | Recall@5 ≥ 0,8 **[Chốt cổng 5]** |
| Probe | ≥ 20 câu không có đáp án | Tỉ lệ trả lời bừa ≤ 5% tại ngưỡng đã chọn; báo cáo kèm tỉ lệ E3 oan (D-22) |
| Thủ công | Biểu đồ hai đường (trả lời bừa, E3 oan) theo ngưỡng + ngưỡng đã chọn | Đã cập nhật `policy.json` **[Chốt cổng 3]** |
| Đánh giá (Phase 8) | Ablation RAG 4 cấu hình (P3 mục 11.1) | Bảng Recall@5, MRR, nDCG@5, trả lời bừa, p95 (D-25) |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P3, P4, P5 (`call_with_retry`), nội dung KB.
- **Phase:** 3, 5, 8 (ablation).
- **Việc còn mở:**
  - Nếu điểm rerank ở tiếng Việt dồn thấp, ngưỡng 0,6 có thể phải hạ. Quyết định bằng biểu đồ hai đường ở Phase 3, không đổi trước.
  - Soạn bộ ≥ 20 câu không có đáp án trước Phase 3 (D-22).
  - D-25 tăng khối lượng soạn KB — cần nhóm cân đối.

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Đổi vector DB (Chroma, pgvector) | Viết adapter mới cho port `VectorIndex` (`upsert`, `hybrid_query`, `switch_alias`); pgvector cần tự gộp RRF | Hợp đồng `RetrievalResult`; phân biệt E2/E3 |
| Đổi embedding/reranker | Đổi model ở ml-service → ingest lại toàn bộ (collection mới) → kiểm Recall@5 và tỉ lệ trả lời bừa → đổi alias | Không trộn vector của hai model trong một collection; chunk vẫn đo bằng tokenizer của model mới |
| Thêm nguồn tài liệu (Confluence, SharePoint) | Thêm bộ nạp trong `rag/ingest/sources/`, chuyển về cùng front matter | `kb_version` vẫn tính từ `(doc_id, version)` |
| Scale | Qdrant chạy riêng, có thể thêm replica; rerank là điểm nghẽn → giảm K còn 10, dùng GPU, hoặc thêm replica ml-service | p95 rerank < 2 giây |
| Cache ngữ nghĩa (Có thể) | Chỉ cho câu trả lời thông tin ở B10, độ giống ≥ 0,95, khóa chứa `kb_version` | Không bao giờ dùng cho hành động |
| Tách thành module "Knowledge" | Gói `rag/` + ml-service embed/rerank; API `retrieve(query, ctx)` | Lọc theo quyền vẫn ở server |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| E3 tăng sau khi ingest | `kb_versions.recall_at5`, `false_grounding_rate`; so điểm trước/sau | Chunk mất đường dẫn heading; tài liệu bị `enabled=false`; đổi model mà không ingest lại |
| E3 oan nhiều, `intent_filter_fallback` cao ở một intent | Ma trận nhầm lẫn của B3 | B3 phân sai giữa hai loại gần nhau; xem B03-B05 |
| E2 ở B8 | Span `rag:*`; `/api/health` | Alias chưa tồn tại; Qdrant hoặc ml-service chết |
| Tìm không ra bước cuối của hướng dẫn | Số `truncated` ở span `rag:*`; `token_count` của chunk | Chunk đo theo từ thay vì token (vi phạm D-21) |
| Tìm không ra câu có mã lỗi | Nhánh bm25 trả gì | Tokenizer tách "0x8004010F"; stopword xóa số |
| Trả lời dùng tài liệu restricted cho nhân viên | Filter `sensitivity` | `allowed_sensitivity(role)` sai; payload thiếu index; lần chạy lại D-23 quên giữ lọc |
| Chậm | Thời lượng `rag:rerank`; tần suất `rag:search_nofilter` | K quá lớn; ml-service thiếu CPU; B3 phân sai nhiều làm lần chạy lại xảy ra thường xuyên |

### Chốt khi hiện thực Phase 3 (30/09/2026)

Phase 3 hiện thực theo `build/phase3-thiet-ke-chi-tiet.md` mục 6.8, 6.13; khi lệch, file đó thắng (trừ bất biến và mục [Chốt]).

- Bỏ `call_with_retry` bọc ngoài (retry một tầng trong `rag/`); không có cột `kb_gap_query` (câu truy vấn ở điểm log 3); `reason_detail='no_grounding'`.
- Việc treo 17: B9 chạy trước B10 → yêu cầu hành động có điểm truy hồi thấp bị E3 (h14) — xem lại Phase 5/mốc G.
- Q-3h-11 (phase3 11.10 #17): `build_query` bỏ thẻ `[fake:…]` khỏi câu truy hồi. Việc treo 17 (B9 chặn yêu cầu hành động: tc09 0,047, có mục đúng cách nói vẫn 0,261) chuyển Phase 4 S0 (Q-4-U, phase4-thiet-ke-chi-tiet.md 3.3/4.0) — chưa giải quyết ở Phase 3.

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.2 | Bản vá: chunk theo token (D-21), chọn ngưỡng có câu âm tính (D-22), chạy lại không lọc intent (D-23), KB mở rộng + ablation (D-25); ghi chú B9 chặn cả luồng hành động |
| 30/09/2026 | 1.3 | Thêm mục "Chốt khi hiện thực Phase 3" trỏ về `phase3-thiet-ke-chi-tiet.md` (mục 6.8, 6.13) |
