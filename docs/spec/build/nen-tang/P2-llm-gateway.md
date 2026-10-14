# P2 — LLM gateway (`backend/app/llm/`)

*Thuộc bộ `build/`. Cổng duy nhất cho mọi lời gọi LLM (B2 tầng L4, B3, B10, B11, B14). Phase 3; router local/API là phần xây dựng bắt buộc của Obj 1 **[Chốt RQ5]**.*

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

**Mã quyết định mới (đã chốt theo đặc tả 25/09/2026):** D-01…D-33 — danh sách đầy đủ, trạng thái và các quyết định Q1–Q14 ở `build/decisions.md`. Các mã mà file này dùng được liệt kê ở mục 0.5 (file nền tảng: trong thân bài).

---

## 1. Mục đích

- Một đường code cho cả LLM cloud và LLM local, để RQ5 chỉ còn là đổi cấu hình.
- Đầu ra luôn là object Pydantic hợp lệ, hoặc một lỗi rõ ràng.
- Mọi lời gọi đều có trace, chi phí, phiên bản prompt và model, và có thể cache khi chạy thực nghiệm.

## 2. Sơ đồ cấu tạo

```
node gọi: await llm.complete(role, prompt_id, variables, schema, sensitivity, cache_policy)
   │
   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ LLMClient.complete                                                    │
│ 1 PromptRegistry.load(prompt_id) → (template, version, sha256)        │
│ 2 ContextBuilder.render(template, variables, budget[role])            │
│ 3 Router.pick(role, sensitivity) → (provider, model, params)          │
│ 4 Cache.get(key)  ── hit ──────────────────────────────┐              │
│ 5 Semaphore(max_concurrency)                           │              │
│ 6 Provider.chat(messages, json_schema, timeout)        │              │
│     retry 429/5xx (backoff+jitter) → fallback chain    │              │
│ 7 schema.model_validate_json(out) ── sai → 1 lần sửa ──┤              │
│ 8 Cache.put(key, out)                                  │              │
│ 9 span "llm" + dòng llm_calls (token, cost, cache_hit) ◄┘              │
└──────────────────────────────────────────────────────────────────────┘
   │                                   │
   ▼                                   ▼
Provider "cloud" (SDK openai,     Provider "local" (Ollama dev /
base_url của nhà cung cấp)        vLLM máy GPU), cùng API OpenAI
```

## 3. Công nghệ

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Transport | SDK `openai` (async), `base_url` cấu hình được | Ollama và vLLM đều có API tương thích OpenAI, nên một client dùng cho cả hai **[Đề xuất D-12]** |
| Provider không tương thích | Adapter riêng trong `llm/providers/` | Đa provider, trần chi tiêu (N1 trong `build/decisions.md`); model chọn bằng probe ở Phase 3 |
| Ép JSON | `response_format={"type":"json_schema",…}` (cloud hỗ trợ); `format=<schema>` (Ollama); guided decoding (vLLM) | Giảm lỗi schema ngay từ nguồn |
| Validate | Pydantic v2 | Giống nhau cho mọi provider **[Chốt]** |
| Đếm token | Trường `usage` trả về; ước lượng bằng tokenizer khi thiếu | Chi phí, ngân sách |
| Cache | Bảng Postgres `llm_cache` | **[Đề xuất D-11]** |
| Phương án B | LiteLLM | Nếu nhóm muốn ít code hơn |

## 4. Hợp đồng

```python
class LLMMeta(BaseModel):
    span_id: str; provider: str; model: str; prompt_id: str; prompt_version: str
    tokens_in: int; tokens_out: int; cost_usd: float; latency_ms: int
    cache_hit: bool; json_valid_first_try: bool; used_fallback: bool
    logprobs: list | None = None         # chỉ khi provider trả (RQ2)

async def complete(role: Literal["fast","strong"], prompt_id: str, variables: dict,
                   schema: type[T], *, sensitivity: Literal["public","internal","sensitive"]="internal",
                   cache_policy: Literal["default","bypass","eval_forever"]="default",
                   n: int = 1, temperature: float | None = None) -> tuple[T | list[T], LLMMeta]
```

- `n>1` dùng cho cách "hỏi nhiều lần" ở B14. Chạy song song, mỗi lần là một span con.
- Lỗi ném ra: `LLMSchemaError` (sai schema sau 1 lần sửa), `LLMUnavailable` (hết retry và fallback), `LLMBudgetExceeded` (vượt trần token). Node quyết định lỗi này thành mã thoát nào (mục 10).

## 5. Cấu hình `config/llm.yaml`

```yaml
# Đa provider (N1): mỗi provider một khóa; vai trò trỏ tới provider nào cũng được.
providers:
  cloud_a: {kind: openai_compat, base_url: ${LLM_A_BASE_URL}, api_key: ${LLM_A_API_KEY}}
  cloud_b: {kind: openai_compat, base_url: ${LLM_B_BASE_URL}, api_key: ${LLM_B_API_KEY}}   # bỏ trống nếu chỉ dùng 1 provider
  local:   {kind: openai_compat, base_url: ${LOCAL_LLM_URL:-http://ollama:11434/v1}, api_key: none}
roles:
  fast:   {provider: ${FAST_PROVIDER:-cloud_a},   model: ${FAST_MODEL},   timeout_s: 8,  max_tokens: 400, temperature: 0, budget_in: 2000}
  strong: {provider: ${STRONG_PROVIDER:-cloud_a}, model: ${STRONG_MODEL}, timeout_s: 20, max_tokens: 900, temperature: 0, budget_in: 6000}
fallback:
  fast: [{provider: local}, {provider: cloud_b, model: ${FAST_MODEL_B}}]   # bỏ phần tử chưa cấu hình
  strong: []           # KHÔNG fallback — kể cả sang provider khác (giữ số liệu thực nghiệm nhất quán)
# Trần chi tiêu toàn đồ án (N1: ≤ 1.000.000 đ ≈ 38 USD). Tính từ SUM(llm_calls.cost_usd), cache hit = 0.
spend:
  cap_usd: ${LLM_SPEND_CAP_USD:-38}
  warn_ratio: 0.8      # ≥ 80% → cảnh báo M9 (P9 luật 14)
  hard_stop: true      # ≥ 100% → không gọi provider trả phí nữa: ném LLMBudgetExceeded (local và cache vẫn chạy)
sensitivity_routing:
  sensitive: local_if_available   # nếu không có local: chỉ gửi phần đã che
limits: {max_concurrency: 8, retry_on: [429, 500, 502, 503, 504], max_retries: 3, backoff_base_s: 1}
cache: {ttl_hours_runtime: 24, no_cache_prompts: [b02_injection_judge, b14_risk_estimate]}
pricing:                          # USD / 1M token — thay bằng bảng giá thật khi chốt provider
  ${FAST_MODEL}:   {in: 0.25, out: 1.0}
  ${STRONG_MODEL}: {in: 3.0,  out: 15.0}
```

**Vì sao `strong` không có fallback:** B10 (câu trả lời) và B14 (rủi ro) mà âm thầm rơi xuống model yếu sẽ làm hỏng chất lượng và số liệu thực nghiệm mà không ai hay biết. Thà ném `LLMUnavailable` rõ ràng.

**Giá trị `budget_in`** lấy từ mục 17.2 **[Chốt]**: fast ≤ 2.000 token, strong ≤ 6.000 token.

**Trần chi tiêu `spend` [Đề xuất, theo N1]:** kiểm trước mỗi lời gọi tới provider trả phí bằng tổng `llm_calls.cost_usd` (cache trong bộ nhớ, làm mới mỗi 60 giây). Vượt trần → `LLMBudgetExceeded`, node ánh xạ như `LLMUnavailable` (mục 10) — tức B14 vẫn ra E5, không bao giờ "tự làm vì hết tiền". Khi chạy thực nghiệm, harness M8 kiểm trần **trước** khi bắt đầu một lượt và dừng sớm nếu ước lượng lượt đó vượt phần còn lại. Kế hoạch chia ngân sách: `build/decisions.md` mục 1.2.

## 6. Prompt registry

Mỗi prompt là một file YAML:

```yaml
# config/prompts/b03_classify.yaml
id: b03_classify
version: 3
role: fast
schema: ClassifyOut              # tên class Pydantic, kiểm lúc import
system: |
  Bạn phân loại yêu cầu IT tiếng Việt vào 4 loại: account, vpn, software, access,
  hoặc out_of_scope. Trả JSON đúng schema. Không suy đoán ngoài câu người dùng.
user: |
  Yêu cầu: {{ redacted_request }}
  Hội thoại gần nhất: {{ recent_messages }}
fewshot: [...]
```

- Khi nạp, hash sha256 của nội dung được ghi vào `llm_calls.prompt_hash` và `lineage` **[Chốt 17.1]**.
- **Test:** mọi prompt đều có schema tồn tại; các biến trong template khớp `variables` mà node truyền vào.

**Danh sách prompt dự kiến:**

- `b02_injection_judge`
- `b03_classify` — từ D-32 chỉ còn là đường dự phòng của B3: câu model phân loại chưa chắc, câu nhiều ý cần tách span (biến `label_hint`), hoặc khi chưa có model
- `b10_need_type`
- `b10_answer`
- `b11_clarify_question`
- `b11_extract_slots`
- `b14_risk_estimate`
- `eval_groundedness` (chỉ dùng cho M8)

## 7. Context builder

Thứ tự ghép **[Chốt 17.2]**:

1. Nhiệm vụ (system).
2. Dữ kiện có cấu trúc (JSON gọn).
3. Bằng chứng: top-k đoạn, bỏ trùng, xếp theo điểm.
4. Tối đa 4 tin nhắn gần nhất.

Vượt trần thì cắt bằng chứng điểm thấp trước, rồi tới tin nhắn cũ. Không bao giờ cắt nhiệm vụ hay schema.

**Danh sách trường được phép đọc theo từng prompt** (whitelist):

- `b14_risk_estimate` chỉ nhận `intended_action`, `requester_context`, `diagnostics`, `retrieved` (trích đoạn). Truyền thêm `redacted_request` hoặc `conversation` → ném lỗi ngay khi render. Đây là cách **ép bất biến "M5 không đọc câu người dùng" ở tầng gateway**, thêm một lớp ngoài import-linter **[Chốt 6.2, Đề xuất cơ chế]**.

## 8. Khóa cache [Chốt 17.5]

```
key = sha256(provider | model | model_version | prompt_id | prompt_version |
             rendered_messages | json_schema | temperature | n | kb_version)
```

| Chế độ | Khi nào | TTL |
|---|---|---|
| `default` | Vận hành | 24 giờ; **bỏ qua** cho `b02_injection_judge`, `b14_risk_estimate` **[Chốt]** |
| `eval_forever` | `LLM_CACHE_MODE=eval` | Không hết hạn → chạy lại thực nghiệm không tốn tiền và ra kết quả giống hệt **[Chốt]** |
| `bypass` | Lần đo độ dao động của LLM | Không đọc, không ghi |

Cache ngữ nghĩa cho B10 (độ giống ≥ 0,95, khóa chứa `kb_version`) là mức **Có thể**, không làm ở bản đầu **[Chốt]**.

## 9. Retry, timeout, đồng thời

- Retry với 429/5xx/timeout: backoff `base · 2^(k-1)` + jitter ngẫu nhiên 0–250 ms, tối đa 3 lần. Header `Retry-After` được ưu tiên nếu có.
- Hết retry → thử lần lượt chuỗi fallback của vai trò. Không còn gì → `LLMUnavailable`.
- `Semaphore(max_concurrency)` dùng chung cho cả process, để thực nghiệm 180 kịch bản không bị nhà cung cấp chặn **[Chốt 14.3]**.
- Sai schema: gửi lại một lần kèm thông báo lỗi Pydantic rút gọn ("Trường `intent` phải là một trong …"). Vẫn sai → `LLMSchemaError`.

## 10. Ánh xạ lỗi gateway → mã thoát (tại node)

| Lỗi | B2 (L4) | B3/B10/B11 | B14 |
|---|---|---|---|
| `LLMUnavailable`, `LLMBudgetExceeded` | E2 + cờ an ninh (xem dưới) | E2 | E5 (không có p → không tự làm) |
| `LLMSchemaError` | E2 + cờ an ninh | E2 (mở rộng) | E5 |

**B2 khi LLM không trả lời được:** câu đã nằm ở vùng lưng chừng của model phân loại. Chọn **escalate E2 kèm cờ an ninh** thay vì E0, vì chưa có bằng chứng tấn công. Như vậy an toàn (không đi tiếp) mà không gắn nhãn tấn công sai **[Đề xuất]**.

**B14 khi LLM lỗi:** không có p thì không có căn cứ để tự làm. Chuyển E5 thay vì E2, vì đây là quyết định an toàn: giảm False Negative **[Đề xuất, theo nguyên tắc dự án]**.

**Việc còn mở từ tài liệu gốc (17.3):** gộp lỗi structured-output vào E2 mở rộng hay tạo mã riêng. Bảng trên tạm dùng E2 mở rộng cho B3/B10/B11. Nếu nhóm chốt khác thì chỉ sửa bảng này.

## 11. Trace và `llm_calls` [Chốt 17.1]

Mỗi lời gọi (kể cả cache hit) ghi 1 span `llm:<prompt_id>` + 1 dòng `llm_calls`:

- provider, model, phiên bản
- `prompt_id@version`, prompt_hash
- tokens vào/ra, chi phí, latency
- `cache_hit`, `json_valid_first_try`, `used_fallback`, lỗi

**Không ghi nội dung prompt đầy đủ khi vận hành**, chỉ hash. Khi `EVAL_MODE=true` thì ghi thêm để phân tích lỗi.

## 12. Model local (khi có GPU) [Chốt mục 11]

- **Dev:** `ollama` trong compose, model khoảng 7–8B lượng tử 4-bit cho vai trò fast.
- **Máy GPU:** `vllm serve <model> --guided-decoding-backend …` cho throughput cao và logprobs (cách "xác suất token" của RQ2).
- **Chọn model bằng probe**, không theo cảm tính:
  - Probe intent 40 câu (F1).
  - Tỉ lệ JSON hợp lệ trên 100 lời gọi.
  - p95 độ trễ.
  - Ghi kết quả vào `decisions.md`.

## 13. Kiểm thử và tiêu chí đạt

| Test | Đạt khi |
|---|---|
| Unit: khóa cache | Đổi bất kỳ thành phần nào của khóa → khóa khác |
| Unit: whitelist biến của `b14_risk_estimate` | Truyền `redacted_request` → lỗi |
| Unit (respx): 429 ×2 rồi 200 | Đúng 3 request, có tôn trọng `Retry-After` |
| Unit: JSON sai → sửa → đúng | 2 request, `json_valid_first_try=False` |
| Unit: strong lỗi hết retry | `LLMUnavailable`, **không** gọi local hay provider khác |
| Unit: tổng `cost_usd` ≥ `cap_usd` | Lời gọi cloud ném `LLMBudgetExceeded`; cache hit và `local` vẫn chạy |
| Unit: fast provider A lỗi hết retry | Thử lần lượt `local` rồi `cloud_b`; `used_fallback=True` |
| Integration: đổi `roles.fast.provider` cloud → local | Không sửa dòng code nào; probe intent chạy được |
| Integration: `LLM_CACHE_MODE=eval`, chạy 20 kịch bản 2 lần | Kết quả giống hệt, lần 2 có 0 request ra ngoài |
| Probe (LLM thật) | JSON hợp lệ sau retry ≥ 99% trên 200 lời gọi |

## 14. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P7 (`llm_calls`, `llm_cache`, `lineage`); P1 (span).
- **Phase:** 3 (router + cache + trace). Fallback local khi có phần cứng mức 1.
- **Việc còn mở:** chọn model cụ thể bằng probe và điền bảng giá thật (Phase 3, N1 — hướng đa provider và trần 1 triệu đ đã chốt); mã lỗi cho structured-output (17.3).


### Chốt khi hiện thực Phase 3 (30/09/2026)

Phase 3 hiện thực theo `build/phase3-thiet-ke-chi-tiet.md` mục 7, 7.8; khi lệch, file đó thắng (trừ bất biến và mục [Chốt]).

- Đóng việc mở §10: structured output lỗi → E2 `llm_schema_error`; không gọi được/hết trần → E2 `llm_unavailable`.
- `LLM_BACKEND=scripted|real` (scripted bị chặn ngoài dev/test); `pricing` bắt buộc cho model thật.
- Trần chi duy nhất là `spend.cap_usd` trong `config/llm.yaml` (Q-3d-3, không có biến env); giữ chỗ chi phí xấu nhất trước mỗi request trả phí; `make vpn-smoke` từ chối khi cap > 1 hoặc thiếu pricing (11.10 #14).
- LLM hết khung vì hạn lượt → `TurnBudgetExceeded` (không phải `LLMUnavailable`) (9.8 #2).

### Chốt khi hiện thực Phase 6 — 6B (10/10/2026)

Phase 6 chặng 6B hiện thực theo `build/phase6-thiet-ke-chi-tiet.md` mục 5, 5.11; khi lệch, file đó thắng (trừ bất biến và mục [Chốt]).

- **§4 `n`:** gateway chỉ nhận `n = 1` (`n ≠ 1` → `ValueError`). "Hỏi nhiều lần" k = 5 = **5 lời gọi `n = 1`** (`asyncio.gather`), mỗi lời có biến `sample_idx` (0…4) nằm **trong thân** prompt → khoá cache khác nhau (Q-6-6, D-39).
- **§5, §8 cache B14:** 2 prompt `b14_risk_estimate`, `b14_risk_vote` để `cache: default` trong file prompt; **estimator** truyền `cache_policy="bypass"` khi `EVAL_MODE=false` (vận hành không bao giờ cache B14) và `"default"` khi đánh giá (cache eval tái lập). Không dùng danh sách `no_cache_prompts`.
- **§6, §7 prompt + whitelist:** thêm `b14_risk_vote` (câu hỏi nhị phân, schema `RiskVoteOut`). `allowed_vars` của `b14_risk_estimate` = `[intended_action, risk_context, evidence]`, của `b14_risk_vote` thêm `sample_idx` — dựng **chỉ** qua hàm thuần `risk/estimator.estimator_vars`; `risk_context` bỏ `now`, `captured_at`, `user_id`, `manager_id`. Schema `RiskEstimateOut {prob_needs_human, factors: list[FactorCode] ≤ 5, rationale ≤ 600}` — `rationale` không ra khỏi estimator.
- **Nợ 6C (N1):** `intended_action` hiện là `Action.model_dump` đầy đủ → giá trị slot chữ tự do trong `Action.params` (vd `software_name`) vào prompt; 6C thêm danh sách trắng `params` theo `action_type` trước khi nối estimator cho software/access.
