# P5 — Tool registry, `call_with_retry`, circuit breaker, adapter và mock

*Thuộc bộ `build/`. Nền của M3 (B6–B7) và điểm ghi B17. Phase 1 (không cần LLM). Bản vá v1.2: thêm `ToolSpec.arg_slots` cho chế độ chẩn đoán lại (D-20).*

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

**Mã quyết định dùng trong file (bản vá v1.2):** D-03, D-20.

---

## 1. Mục đích

Gom mọi lời gọi ra hệ thống ngoài vào **một cổng**, để các chính sách được áp thống nhất và test được ở một chỗ **[Chốt 17.3]**:

- phân loại đọc/ghi
- timeout, retry, circuit breaker
- schema
- bước nào được gọi tool nào
- trace

## 2. Sơ đồ cấu tạo

```
node B6 / B11 / B17
   │ registry.call("check_vpn_cert_expiry", args, caller_step="B6")
   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ToolRegistry (tools/registry.py) — khai báo Python, kiểm lúc import │
│  1 tra ToolSpec  2 kiểm caller_step ∈ allowed_steps                  │
│  3 kiểm kind: write ⇒ caller phải là Executor (B17)                  │
│  4 validate input (Pydantic)                                         │
│  5 CircuitBreaker[target_system].allow()?  ── mở ─► ToolResult(error="circuit_open") ngay
│  6 đọc: call_with_retry(adapter.fn, retry=2, backoff 1s/2s)          │
│     ghi: gọi 1 lần, timeout 5s, KHÔNG retry                          │
│  7 validate output; 404/rỗng = dữ liệu hợp lệ                        │
│  8 span "tool:<name>"                                                │
└─────────────────────────────────────────────────────────────────────┘
   │
   ▼  adapters/ (ports: IdentityProvider, VpnGateway, SoftwareCatalog, FileServer)
   ├── mock_read_*  (token svc_agent)      ──HTTP──► mock_services :8100
   └── mock_write_* (token svc_executor)   ──HTTP──► mock_services :8100
                                                    ├─ /ad, /vpn, /software, /files
                                                    ├─ /_admin/faults (bơm lỗi)
                                                    └─ seed.json
```

## 3. Công nghệ

httpx (async, timeout theo tool), Pydantic v2, respx (test), FastAPI (mock), argon2-cffi (mật khẩu trong mock AD).

## 4. Khai báo tool

```python
# tools/registry.py
@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: Literal["read", "write"]
    target_system: Literal["ad", "vpn", "software", "files"]
    input_model: type[BaseModel]; output_model: type[BaseModel]
    timeout_s: float
    retries: int                      # read: 2, write: 0 [Chốt 17.3]
    allowed_steps: frozenset[str]     # {"B6","B11"} cho read; {"B17"} cho write
    arg_slots: frozenset[str] = frozenset()   # slot dùng làm tham số (chỉ tool đọc) [Đề xuất D-20]
    reversible: Literal["full", "partial", "none"] | None = None   # chỉ tool ghi
    undo_tool: str | None = None      # ví dụ reset_password → lock_account (partial)

REGISTRY = {s.name: s for s in [...]}
assert all(s.allowed_steps == {"B17"} for s in REGISTRY.values() if s.kind == "write")
assert all(s.arg_slots <= TOOL_ARG_SLOTS for s in REGISTRY.values())   # khớp config/slots.yaml
```

**12 tool đọc [Chốt B6] và `arg_slots` [Đề xuất D-20]:**

| Intent | Tool | `arg_slots` (ngoài danh tính người gửi) |
|---|---|---|
| account | `check_account_status` | `target_user`, `account_type` |
| account | `check_lockout_history` | `target_user` |
| account | `check_privilege_level` | `target_user`, `account_type` |
| vpn | `check_device_registered` | `device_id` |
| vpn | `check_vpn_cert_expiry` | `device_id` |
| vpn | `check_last_connection` | — |
| software | `check_catalog_entry` | `software_name` |
| software | `check_license_available` | `software_name` |
| software | `check_installed_list` | `device_id` |
| access | `check_current_permissions` | `resource_path` |
| access | `check_resource_sensitivity` | `resource_path` |
| access | `check_manager_chain` | — |

`arg_slots` chỉ dùng cho chế độ chẩn đoán lại (B06-B07 mục 5): khi người dùng bổ sung một slot trong cột này, B6 gọi lại đúng những tool có slot đó. Khi `arg_slots` rỗng, tool chỉ phụ thuộc người gửi nên không cần gọi lại. Bảng trên là suy luận từ tên tool, cần chốt cùng mock endpoint ở T05.

**Tool ghi (chỉ B17) [Suy luận từ 4 loại yêu cầu + 20 luật]:**

| Tool | reversible | undo |
|---|---|---|
| `reset_password` | partial (email đã gửi) | `lock_account` |
| `unlock_account` | full | `lock_account` |
| `renew_vpn_cert` / `reissue_vpn_access` | full | `revoke_vpn_cert` |
| `install_software` (miễn phí) | full | `uninstall_software` |
| `assign_paid_license` | none | — |
| `grant_permission` | full | `revoke_permission` |
| `extend_permission` | full | `restore_permission_expiry` |

**Vì sao registry viết bằng Python thay vì bảng DB:** `input_model`/`output_model` là class chỉ tồn tại trong code; không có UI nào cần sửa tool **[Chốt ở thiết kế DB vòng 3]**.

## 5. `call_with_retry` [Chốt workflow mục 4]

```python
async def call_with_retry(fn, *args, retries=TOOL_RETRY, base=BACKOFF_BASE_SECONDS, clock=CLOCK, **kw):
    attempt = 0
    while True:
        try:
            return await fn(*args, **kw), None, attempt
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            err = e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None, None, attempt             # không tồn tại = dữ liệu hợp lệ
            if e.response.status_code not in (429,) and e.response.status_code < 500:
                raise                                   # 4xx khác: lỗi hợp đồng, không retry
            err = e
        attempt += 1
        if attempt > retries:
            return None, f"{type(err).__name__}: {err}", attempt
        await clock.sleep(base * 2 ** (attempt - 1))   # 1s, 2s
```

Hàm trả thêm `attempt` để ghi `tool_retry_count` vào điểm log 2 và 3 **[Chốt]**. `clock` tiêm được, nên `FakeClock` làm test chạy trong vài mili giây.

## 6. Circuit breaker [Chốt 17.3]

Mỗi `target_system` có một breaker:

- **closed → open:** 5 lỗi liên tiếp trong 60 giây.
- **open:** mọi lời gọi tới hệ thống đó trả lỗi ngay trong 30 giây.
- **half-open:** cho qua đúng 1 lời gọi thử; thành công thì đóng lại, lỗi thì mở tiếp.

Trạng thái breaker nằm trong bộ nhớ process (không lưu DB) **[Chốt]**. Khi breaker mở hoặc đóng, ghi span + metric (không ghi `security_events`, vì đây là sự cố hạ tầng chứ không phải an ninh) để M9 cảnh báo "hạ tầng ngoài yếu" **[Chốt 17.9.3]**.

**Vì sao:** khi AD chết, mỗi ticket không phải mất 3 giây retry mới biết. Ticket đi E2 ngay.

### 6.1. Kiểu trả của `registry.call` [Chốt 26/09/2026]

`registry.call(...)` **không raise** khi hệ thống ngoài lỗi. Nó luôn trả:

```python
@dataclass(frozen=True)
class ToolResult:
    tool: str
    data: Any | None          # None khi lỗi hoặc 404
    error: str | None         # "circuit_open" | "TimeoutException: …" | None
    attempts: int             # → tool_retry_count (điểm log 2, 3)
    empty: bool               # 404 / rỗng = dữ liệu hợp lệ, KHÔNG phải lỗi (E2 ≠ E3)
    def __iter__(self): return iter((self.data, self.error, self.attempts))   # cho B01/B17: data, err, _ = ...
```

- Breaker mở → `error="circuit_open"`, node đi **E2** như mọi lỗi hạ tầng đã biết.
- Chỉ lỗi **hợp đồng** (4xx khác 404/429, output sai schema, `caller_step` không được phép) mới raise — đó là lỗi lập trình, rơi xuống **E9** là đúng.
- **Tool ghi gặp 404/409** (máy chưa đăng ký, hết license… phát hiện lúc thực thi): trả `error` như thất bại thực thi → B17 đi **E7** (có hoàn tác theo mục 5.3 của B17), **không** raise và **không** tính vào breaker — đây là trạng thái nghiệp vụ của hệ thống đích, không phải bug hay hạ tầng chết.
- **Breaker đếm theo lần gọi registry** (sau khi `call_with_retry` đã thử xong), không theo từng HTTP attempt: một lời gọi thử 3 lần rồi thất bại = 1 lỗi. Đếm theo attempt thì chỉ 2 ticket lỗi đã mở breaker.
- **Tool có `arg_slots` bắt buộc mà thiếu slot** → lỗi hợp đồng (raise). Vì vậy B6 **phải lọc** tool theo `arg_slots` đã có trước khi gọi (D-20), không gọi "thử".
- **Lý do:** B01, B06, B17 đều xử lý lỗi tool như giá trị (`r.error`, `data, err, _ = …`). Nếu breaker raise, node nào quên bắt sẽ rơi xuống E9, làm lẫn "hạ tầng ngoài chết" (E2) với "bug chưa lường trước" (E9) trong số liệu M9.

## 7. Mock services [Chốt]

| Endpoint | Ghi chú |
|---|---|
| `/ad/authenticate` | Nhận username + mật khẩu, so với hash argon2id trong seed, trả thuộc tính + nhóm AD **[Đề xuất, phục vụ P6]** |
| `/ad/users/{id}`, `/ad/users/{id}/lockouts`, `/ad/users/{id}/privilege` | Đọc |
| `/vpn/devices/{id}`, `/vpn/devices?owner_id=` (thêm 26/09/2026 — B6 tự tìm máy khi người dùng chưa nêu `device_id`, TC06), `/vpn/certs/{user}`, `/vpn/connections/{user}` | Đọc |
| `/software/catalog/{name}`, `/software/licenses/{name}`, `/software/installed/{device}` | Đọc |
| `/files/permissions/{user}`, `/files/resources/{path}`, `/ad/users/{id}/manager-chain` | Đọc |
| `POST /ad/…/reset-password`, `/vpn/…/renew`, `/software/…/install`, `/files/…/grant` … | **Ghi, bắt buộc token `svc_executor`** **[Đề xuất D-03]** |
| `/_admin/faults` | Bơm lỗi 500/429/timeout/latency theo endpoint; tắt bơm lỗi **[Chốt]** |
| `/_admin/reset` | Đặt lại seed (chế độ demo) **[Chốt 16.5]** |

`seed.json` **[Chốt]** được mở rộng thêm:

- người dùng có `employment_status` ∈ {active, probation, disabled, terminated}
- `manager_id`
- nhóm AD (`IT-Users`, `IT-L1`, `IT-Manager`, `IT-L2`)
- hash mật khẩu demo
- dữ liệu cho các họ kịch bản đi xuống LLM (mục 8.2 hướng dẫn)
- ít nhất một cặp "người gửi disabled, người hưởng lợi active" cho test D-15 (B17) **[Đề xuất v1.2]**
- ít nhất hai thiết bị cùng người dùng có trạng thái khác nhau (một đã đăng ký, một chưa) cho test chẩn đoán lại D-20 **[Đề xuất v1.2]**

## 8. Kiểm thử và tiêu chí đạt (cổng 1)

| Test | Đạt khi |
|---|---|
| Hợp đồng (245 test đã có) | Xanh **[Chốt]** |
| `call_with_retry` | 404 → không lỗi, không retry; 500 liên tục → đúng 3 lần gọi, chờ 1s rồi 2s; rỗng → `[]` **[Chốt]** |
| Registry | Tool ghi gọi từ B6 → `ForbiddenToolCall`; tool ghi không khai báo đúng `{"B17"}` → import lỗi; `arg_slots` ngoài `TOOL_ARG_SLOTS` → import lỗi |
| Breaker | 5 lỗi → mở; lời gọi thứ 6 không chạm mock; sau 30s (FakeClock) → half-open |
| Mạng | Gọi endpoint ghi bằng token `svc_agent` → 403 |
| Thủ công | Gọi tay 12 tool với seed, đối chiếu bảng mong đợi; bật/tắt `/_admin/faults` **[Chốt]** |

## 9. Phụ thuộc, phase, việc còn mở

- **Phase:** 1.
- **Việc còn mở:**
  - Danh sách tool ghi ở mục 4 là suy luận. Chốt cùng lúc với 20 luật (T22a).
  - Bảng `arg_slots` là suy luận từ tên tool; chốt cùng mock endpoint (T05).

### Chốt khi hiện thực Phase 3 (30/09/2026)

Phase 3 hiện thực theo `build/phase3-thiet-ke-chi-tiet.md` mục 9.4, 11.4, 11.10; khi lệch, file đó thắng (trừ bất biến và mục [Chốt]).

- Giữ `call_internal`; tool VPN dùng đúng tên trong `tools/specs.py` (`check_device_registered`/`check_vpn_cert_expiry` với `device_id` tùy chọn; ghi `renew_vpn_cert`, `reissue_vpn_access`, hoàn tác `revoke_vpn_cert`).
- `ad_get_user` có nhãn bước `B17_RECHECK` (tool đọc không bao giờ khai báo `B17`); registry ghi riêng (token `svc_executor`) chỉ dựng ở API process.
- Tool ghi không gửi nếu không đủ trọn timeout (9.8 #2); 404/409 của tool ghi là dữ liệu → E7 `exec_failed` có handoff.
- Mock thêm `/_admin/calls`, `/_admin/calls/reset`, `/_admin/users/{id}/status` (chỉ dưới `/_admin`, 11.10 #12).

## 10. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0 |
| 25/09/2026 | 1.2 | Thêm `ToolSpec.arg_slots` + bảng cho 12 tool đọc (D-20); seed cho test D-15, D-20 |
| 26/09/2026 | 1.3 | Chốt kiểu trả `ToolResult` của `registry.call` (không raise khi breaker mở → E2); sửa sơ đồ mục 2 |
| 26/09/2026 | 1.4 | Chốt khi hiện thực Phase 1c: tool ghi 404/409 → E7 không tính breaker; breaker đếm theo lời gọi; thiếu slot bắt buộc = lỗi hợp đồng; mock thêm `GET /vpn/devices?owner_id=` |
| 30/09/2026 | 1.5 | Thêm mục "Chốt khi hiện thực Phase 3" trỏ về `phase3-thiet-ke-chi-tiet.md` (mục 9.4, 11.4, 11.10) |
