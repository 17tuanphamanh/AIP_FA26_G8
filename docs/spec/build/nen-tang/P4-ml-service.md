# P4 — ml-service (`ml_service/`)

*Thuộc bộ `build/`. Service riêng phục vụ 4 model chạy CPU: embedding, rerank, phân loại injection, phân loại intent đa nhãn (D-32). **[Đề xuất D-09]** Phase 3 (embed, rerank), Phase 5 (classify). Bản vá v1.2: thêm `/count_tokens` và cảnh báo cắt cụt cho D-21.*

---

## 0. Ngữ cảnh nạp sẵn

*File nền tảng này **tự đứng được**: khối ngữ cảnh chung dưới đây giúp người đọc hoặc coding agent hiểu phần này nằm ở đâu trong dự án mà không cần mở tài liệu khác. Phần riêng của thành phần bắt đầu từ mục 1.*

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

**Mã quyết định dùng trong file (bản vá v1.2):** D-06, D-09, D-21.

---

## 1. Mục đích và vì sao tách riêng

Bốn model cộng lại chiếm khoảng 3–4 GB RAM **[Chốt 13.1, ước lượng; cập nhật v1.2]**:

- `bge-m3` (~568M tham số)
- `bge-reranker-v2-m3` (~568M)
- `injection-clf` và `intent-clf` — mỗi model mDeBERTa-v3-base (~278M) do nhóm fine-tune, **ONNX int8 ~300 MB mỗi model** (D-33, P11). Bản fp32 mỗi model ~1,1 GB → không dùng khi vận hành.

Backend chạy 2–4 worker uvicorn **[Chốt 13.2]**. Nếu model nằm trong backend thì **mỗi worker nạp một bản**, tổng 8–16 GB, vượt VM 16 GB đề xuất. Tách thành một process nạp mỗi model **đúng 1 lần**.

Lợi ích phụ:

- Backend khởi động trong vài giây.
- Test backend dùng `FakeMlService`.
- Khi có GPU thì chỉ ml-service cần GPU.
- Tokenizer của bge-m3 nằm sẵn ở đây, nên bước ingest đếm token đúng tokenizer mà model dùng (D-21), không phải tự nạp lại trong backend.

## 2. Sơ đồ cấu tạo

```
backend (httpx, call_with_retry) ──HTTP nội bộ──► ml-service :8200 (uvicorn 1 worker)
                                                 ├─ lifespan: nạp 4 model 1 lần, warm-up
                                                 ├─ POST /embed        → bge-m3 dense
                                                 ├─ POST /rerank       → bge-reranker-v2-m3
                                                 ├─ POST /classify     → injection-clf (B2 L3)
                                                 ├─ POST /classify_intent → intent-clf đa nhãn (B3a, D-32)
                                                 ├─ POST /count_tokens → tokenizer bge-m3 (D-21)
                                                 ├─ GET  /health       → model đã nạp, phiên bản
                                                 └─ asyncio.Semaphore + batch nhỏ, chạy
                                                    suy luận trong threadpool (không chặn loop)
```

## 3. Công nghệ

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| API | FastAPI, uvicorn **1 worker** | 1 worker để chỉ có 1 bản model; song song hóa bằng threadpool |
| Embed | `FlagEmbedding.BGEM3FlagModel` (hoặc `sentence-transformers`) | dense 1024 chiều, `normalize=True`, `max_length=512` |
| Rerank | `FlagEmbedding.FlagReranker` (hoặc `CrossEncoder`) | `normalize=True` → sigmoid 0..1; `max_length=512` cho cặp (câu hỏi, đoạn) |
| Classify (injection + intent) | `onnxruntime` chạy ONNX int8 xuất từ `optimum`; dự phòng `transformers` `AutoModelForSequenceClassification` khi debug | Hai model `injection-clf`, `intent-clf` do nhóm huấn luyện (P11). Prompt Guard 2 chỉ nạp khi chạy baseline RQ4 |
| Đếm token | Tokenizer đi kèm `BAAI/bge-m3` (XLM-RoBERTa) | Dùng cho chunker của P3 (D-21) |
| Torch | Bản CPU | `torch.set_num_threads(N_CPU)` |
| Model files | Tải sẵn vào volume `models/` khi build image | Khởi động không cần mạng **[Chốt 13.4]** |

## 4. Hợp đồng API

```python
# POST /embed
class EmbedIn(BaseModel):  texts: list[str] = Field(max_length=64)
class EmbedOut(BaseModel): vectors: list[list[float]]; model: str; dim: int
                           truncated: list[bool]            # True nếu văn bản bị cắt ở 512 token (D-21)

# POST /rerank
class RerankIn(BaseModel):  query: str; passages: list[str] = Field(max_length=32)
class RerankOut(BaseModel): scores: list[float]; model: str        # cùng thứ tự passages
                            truncated: list[bool]

# POST /classify
class ClassifyIn(BaseModel):  text: str
class ClassifyOut(BaseModel): p_malicious: float; windows: int; model: str; version: str

# POST /classify_intent                                      [Đề xuất D-32]
class IntentIn(BaseModel):  text: str                      # redacted_request, ≤ 128 token (dài hơn → cắt, cờ truncated)
class IntentOut(BaseModel): probs: dict[str, float]        # 5 nhãn sigmoid, đã hiệu chỉnh nhiệt độ
                            tau_hi: dict[str, float]; tau_lo: dict[str, float]   # từ thresholds.json
                            truncated: bool; model: str; version: str

# POST /count_tokens                                         [Đề xuất D-21]
class CountIn(BaseModel):  texts: list[str] = Field(max_length=256)
class CountOut(BaseModel): counts: list[int]; model: str
```

**Model chưa nạp:** `/classify_intent` và `/classify` trả **503** nếu thư mục model không tồn tại. Backend coi như lỗi và đi đường LLM (B3b, B2 L4) — hệ thống chạy được trước khi nhóm huấn luyện xong.

**Quy tắc của `/classify`:**

- Câu > 512 token → cắt thành cửa sổ 512 token, chồng lấn 64, chấm từng cửa sổ, trả **max** p_malicious. Một cửa sổ độc là đủ để cả câu bị coi là độc (khuyến nghị trong model card).
- Endpoint **không log nội dung văn bản**, chỉ log độ dài và điểm.

**Quy tắc cờ `truncated` [Đề xuất D-21]:** `/embed` và `/rerank` không âm thầm cắt văn bản. Mỗi phần tử có cờ `truncated`; backend ghi số lần `truncated=true` vào span `rag:*`, và M9 cảnh báo nếu con số này > 0 khi vận hành. Với chunker theo token của P3, giá trị đúng là **luôn 0** đối với đoạn tài liệu.

## 5. Bảo mật

- Chỉ nghe trong mạng Docker nội bộ; không bind cổng ra host ở bản prod.
- Yêu cầu header `X-Service-Token` (token của backend) **[Đề xuất, nhất quán với P6]**.
- Giới hạn kích thước request 256 KB.

## 6. Cấu hình

| Env | Mặc định |
|---|---|
| `EMBED_MODEL` | `BAAI/bge-m3` |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` |
| `GUARD_MODEL_DIR` | `models/injection-clf/<phiên bản>` (P11 mục 4.3) |
| `INTENT_MODEL_DIR` | `models/intent-clf/<phiên bản>` |
| `BASELINE_GUARD_MODEL` | `meta-llama/Llama-Prompt-Guard-2-86M` — chỉ nạp khi chạy RQ4 |
| `ML_THREADS` | số vCPU − 1 |
| `ML_MAX_CONCURRENCY` | 4 |

## 7. Trace

Backend mở span `ml:<endpoint>` phía client. ml-service trả header `X-Model-Version` để backend ghi vào `lineage` **[Chốt 17.1]**.

## 8. Lỗi

| Tình huống | Phía backend |
|---|---|
| ml-service chết / timeout | `call_with_retry` 2 lần → `ExternalSystemError`. Ở B8 → E2 **[Chốt]**. Ở B2 → xem B02 mục 10 |
| Model chưa nạp xong | `/health` trả 503; `/api/health` của backend báo đỏ |
| Request quá lớn | 413; backend chia batch trước khi gọi |
| Văn bản bị cắt ở 512 token | Không lỗi; `truncated=true`, backend ghi vào span và M9 cảnh báo |

## 9. Kiểm thử và tiêu chí đạt

| Test | Đạt khi |
|---|---|
| Unit | `/rerank` trả đúng số điểm, cùng thứ tự; `/classify` với câu 1.500 token → `windows ≥ 3` |
| Unit | `/count_tokens` trả đúng số token của tokenizer bge-m3; văn bản 600 token gửi `/embed` → `truncated=[true]` |
| Integration | Embed 2 lần cùng câu → vector giống hệt (tất định) |
| Integration | Ingest toàn bộ KB → tổng `truncated=true` = 0 (D-21) |
| Hiệu năng (VM 4 vCPU) | Embed 1 câu p95 < 300 ms; rerank 20 đoạn p95 < 2 giây; classify và classify_intent p95 < 100 ms |
| Unit | Thư mục `INTENT_MODEL_DIR` không tồn tại → `/classify_intent` 503; `/health` báo model thiếu nhưng service vẫn chạy |
| Integration | `/classify_intent` trả đúng 5 nhãn và ngưỡng khớp `thresholds.json` của phiên bản đã nạp |
| Tài nguyên | RSS ổn định sau 1 giờ tải (không rò rỉ bộ nhớ) |
| Bảo mật | Gọi thiếu `X-Service-Token` → 401 |

## 10. Phụ thuộc, phase, việc còn mở

- **Phase:** 3 (embed + rerank + count_tokens + endpoint `/classify_intent`, trả 503 tới khi có model), 5 (nạp `intent-clf` và `injection-clf` từ P11).
- **Việc còn mở:**
  - Đo RAM thật ở Phase 3 **[Chốt 13.1]**.
  - Đo hệ số token/âm tiết tiếng Việt trên KB thật để xác nhận trần chunk của P3.
  - Đo RAM thật khi nạp đủ 4 model; không đủ → xem P11 mục 8.
  - Prompt Guard 2 (Llama 4 Community License) chỉ dùng cho lần chạy baseline RQ4.

## 11. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0 |
| 25/09/2026 | 1.2 | Thêm `/count_tokens`, cờ `truncated` ở `/embed` và `/rerank`, test tương ứng (D-21) |
| 25/09/2026 | 1.2 | Thêm `/classify_intent` (D-32); hai classifier là model nhóm tự huấn luyện, ONNX int8 (D-33, P11); 503 khi chưa có model |
