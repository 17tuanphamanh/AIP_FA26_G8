# B6–B7 — Chẩn đoán chủ động, phân biệt lỗi hệ thống và kết quả rỗng

> **Tầng:** T2 · **Module:** M3 · **Objective:** 1 (điểm khác biệt về trải nghiệm, đo bằng RQ3) · **Phase:** tool ở 1, node ở 3
> **Trạng thái vào:** `S_DIAGNOSING` · **Ra:** `S_RETRIEVING` | `S_ESCALATED` (E2)
> **Tài liệu nền:** `nen-tang/P5-tool-registry-mock.md`
> **Bản vá v1.2:** D-20 (chế độ chẩn đoán lại khi B11 nhận slot mới — cờ tắt mặc định)

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
| Nhánh trước | B3 (hoặc trực tiếp khi là ticket con — xem B03-B05 mục 5.3). **D-20 (cờ bật):** B11 sau khi người dùng bổ sung slot làm đổi tham số tool |
| Nhận vào | `intent`, `slots` (sơ bộ), `requester_context`, `reasoning_loops`, `rediagnose` (D-20) |
| Giao cho nhánh sau | `diagnostics`, `slots` (bổ sung từ chẩn đoán), `tool_retry_count`, `ctx_flags.target_is_other`, `status=S_RETRIEVING`, `next=b08_retrieve` (lần đầu) hoặc `next=b11_slots` (chẩn đoán lại) |
| Ai dùng đầu ra | B8 (câu truy vấn), B11 (không hỏi lại slot đã suy), B12 (dữ kiện cho luật qua `Action.facts`), B17 (kế hoạch thực thi), L2 (ghi chú bàn giao) |

**Chuyển trạng thái của nhánh [Chốt 2.1 + Đề xuất D-20]:**

| Từ | Sự kiện | Sang | Nguồn |
|---|---|---|---|
| `S_DIAGNOSING` | Tool phản hồi bình thường (kể cả rỗng) | `S_RETRIEVING` | **[Chốt]** |
| `S_DIAGNOSING` | Tool lỗi hệ thống sau khi hết retry | `S_ESCALATED` → E2 | **[Chốt]** |
| `S_DIAGNOSING` | Vượt 5 vòng lặp | `S_ESCALATED` → E2 | **[Chốt]** |
| `S_CLARIFYING` | Người dùng bổ sung slot làm đổi tham số tool, `reasoning_loops` < 5 | `S_DIAGNOSING` (chẩn đoán lại) | **[Đề xuất D-20, chờ chốt]** — chưa có trong bảng 2.1 gốc |

### 0.3. Đặc tả gốc đã chốt

- **Chẩn đoán chủ động (mức hỗ trợ 4):** gọi tool kiểm tra trạng thái trước khi hỏi người dùng, chỉ hỏi phần thực sự còn thiếu. Chi phí gần bằng không vì tool đã có cho mức 3, chỉ đổi thứ tự gọi.
- **Bản đồ tool:**

  | Intent | Tool |
  |---|---|
  | account | `check_account_status`, `check_lockout_history`, `check_privilege_level` |
  | vpn | `check_device_registered`, `check_vpn_cert_expiry`, `check_last_connection` |
  | software | `check_catalog_entry`, `check_license_available`, `check_installed_list` |
  | access | `check_current_permissions`, `check_resource_sensitivity`, `check_manager_chain` |

- **`call_with_retry` dùng chung cho B6 và B8:**
  - Chỉ retry lỗi tạm thời (timeout, 5xx, mất kết nối); retry tối đa `TOOL_RETRY=2` lần, backoff `1s·2^(k-1)`.
  - 4xx (ví dụ 404) không retry, vì là dữ liệu hợp lệ.
  - Hết lượt thì báo lỗi hệ thống, không retry vô hạn.
- **B7 — ví dụ sai và đúng:**
  - Sai: `except: account=None` → "Tài khoản của bạn không tồn tại" trong khi server đang chết.
  - Đúng: HTTP 500/timeout đã retry đủ → E2 "Hệ thống đang gặp sự cố"; HTTP 200 rỗng → "Không tìm thấy tài khoản này, bạn kiểm tra lại giúp mình".
- **Giới hạn:** tối đa 5 vòng suy luận mỗi ticket.
- **Ví dụ TC06:** "Máy mình không vào được mạng nội bộ" → agent tự gọi 3 tool → LAP-0342 đã đăng ký; chứng chỉ VPN hết hạn 3 ngày trước; tài khoản bình thường → "Chứng chỉ VPN của bạn hết hạn từ 3 ngày trước. Mình gia hạn ngay được không?" — **0 lượt hỏi** thay vì 4–5.
- **Ablation [Chốt]:** cờ `enable_proactive_diagnosis = True/False`, đo chênh lệch `clarification_turns` trung bình. Đây là RQ3 (bắt buộc).
- **Nguồn gốc:** nhận định của nhóm Microsoft (Roy et al., 2024) — điểm mạnh của agent so với RAG thuần là chủ động thu thập dữ liệu chẩn đoán.

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC06 | Báo lỗi chung chung: không vào được mạng | Giảm số lượt hỏi lại (0 lượt) |
| TC17 | Tool trả kết quả rỗng | Đi tiếp, báo đúng "không tồn tại" |
| TC18 | Tool trả lỗi 500 | E2, không báo nhầm "không tồn tại" |
| Cổng 1 | `call_with_retry` | 404 → không lỗi, không retry; 500 liên tục → đúng 3 lần gọi, chờ 1s rồi 2s |
| Cổng 3 | TC06 với chẩn đoán bị tắt | Agent phải hỏi |
| D-20 (cờ bật) | "Cài Zoom cho máy mình" → hỏi `device_id` → người dùng trả "PC-0977" | B6 chạy lại chỉ các tool cần `device_id`; `facts` có `device_registered` của PC-0977 |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- LLM không tự chọn tool.
- B6 chỉ gọi tool **đọc**.
- Rỗng ≠ lỗi.
- Không retry vô hạn.
- Mỗi lần vào B6 (kể cả chẩn đoán lại) tăng `reasoning_loops`; vượt 5 → E2.
- **Mã quyết định dùng trong file:** D-16 (`scope_tool_target`), D-03 (token `svc_agent`), D-20 (bản vá v1.2).

---

## 1. Mục đích và vì sao tồn tại

Agent **tự kiểm tra hệ thống trước khi hỏi người dùng**: mức hỗ trợ 4 **[Chốt]**, lấy từ nhận định của nhóm Microsoft về agent phân tích nguyên nhân gốc. Ví dụ TC06: 0 câu hỏi lại thay vì 4–5 **[Chốt]**. Chi phí gần bằng không, vì tool đã có sẵn cho mức 3; chỉ đổi thứ tự gọi.

B7 tách **"hệ thống hỏng"** khỏi **"dữ liệu không tồn tại"**. Nhầm hai thứ này thì agent sẽ nói "tài khoản của bạn không tồn tại" trong khi server đang chết **[Chốt]**.

**Chẩn đoán lại (D-20, L-08):** ở bản 1.0, B6 chỉ chạy một lần, trước khi hỏi. Nếu người dùng bổ sung một slot làm đổi đối tượng của tool (thiết bị, thư mục, tài khoản), không có tool nào chạy lại, nên `Action.facts` thiếu dữ kiện cho đối tượng mới. Hệ quả vẫn **an toàn** (thiếu fact → luật `allow` không khớp **[Chốt]**) nhưng tỉ lệ tự động giảm và phải gọi LLM rủi ro hoặc người duyệt nhiều hơn không cần thiết. Chế độ chẩn đoán lại chỉ gọi các tool bị ảnh hưởng.

## 2. Sơ đồ cấu tạo

```
S_DIAGNOSING
   │ reasoning_loops += 1 ; > 5 → E2 [Chốt]
   │ enable_proactive_diagnosis == False (ablation RQ3) → bỏ qua, sang S_RETRIEVING
   ▼
chế độ?  ─ lần đầu ─────────► tools = TOOL_MAP[intent]                     (3 tool đọc) [Chốt]
         └ chẩn đoán lại (D-20) ► tools = [t ∈ TOOL_MAP[intent] | t.arg_slots ∩ changed_slots ≠ ∅]
   │  target = scope_tool_target(ctx, slots)   (D-16: mặc định = requester_id)
   ▼
asyncio.gather( registry.call(t, args, caller_step="B6") for t in tools )   ← chạy song song
   │   mỗi call: breaker → call_with_retry(2 lần, 1s/2s) → validate output
   ▼
[B7] phân loại từng kết quả:
   ├─ lỗi hệ thống sau retry (timeout / 5xx / 429 / breaker mở) → tool_errors
   ├─ 404 / rỗng  → diagnostics[t] = None   (DỮ LIỆU HỢP LỆ)
   └─ có dữ liệu  → diagnostics[t] = result
   │
   ├─ tool_errors ≠ ∅ ─────────────────────────────► S_ESCALATED E2 (ghi tool nào lỗi, số lần retry)
   └─ slots ← infer_slots_from_diagnostics(intent, diagnostics)
         ├─ lần đầu        ─► S_RETRIEVING, next = b08_retrieve (B8)
         └─ chẩn đoán lại  ─► S_RETRIEVING, next = b11_slots   (không tra KB và phân loại lại)
```

## 3. Công nghệ tại nhánh

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Gọi tool | `ToolRegistry` + httpx async + `call_with_retry` + circuit breaker | Một cổng chung **[Chốt 17.3]** |
| Song song | `asyncio.gather` | 3 tool độc lập; giảm từ khoảng 3× xuống 1× độ trễ **[Chốt sơ đồ 10.3: "gọi 3 tool song song"]** |
| Suy slot | Hàm thuần `infer_slots_from_diagnostics` (bảng luật, không LLM) | Tất định, test được |
| Chọn tool | Code theo `TOOL_MAP`, **không** để LLM chọn | **[Chốt]** |
| Chọn tool khi chẩn đoán lại | `ToolSpec.arg_slots` (slot mà tool dùng làm tham số) giao với slot vừa đổi | D-20 — vẫn do code chọn, tất định |

## 4. Hợp đồng node

- **Đọc:** `intent`, `slots`, `requester_context`, `reasoning_loops`, `rediagnose`, `changed_slots`.
- **Ghi:** `diagnostics`, `tool_errors`, `tool_retry_count`, `slots` (bổ sung), `ctx_flags.target_is_other`, `reasoning_loops`, `rediagnose=False`, `status`, `next`, `exit_code`.

```python
class ToolResult(BaseModel):
    tool: str; ok: bool; data: dict | None; empty: bool
    error: str | None; attempts: int; latency_ms: int
```

## 5. Luồng xử lý chi tiết

```python
async def b06_diagnose(state):
    loops = state["reasoning_loops"] + 1
    if loops > cfg.MAX_LOOPS:
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B6",
                    event="max_loops_exceeded", exit_code="E2", reasoning_loops=loops)
    rediag = state.get("rediagnose", False)                      # D-20
    if not flags.ENABLE_PROACTIVE_DIAGNOSIS:                     # ablation RQ3 [Chốt]
        return goto(state, S_RETRIEVING, next_node="b11_slots" if rediag else "b08_retrieve",
                    step="B6", event="diagnosis_skipped", reasoning_loops=loops, rediagnose=False)

    target, is_other = scope_tool_target(state["requester_context"], state["slots"])
    tools = TOOL_MAP[state["intent"]]
    if rediag:
        tools = [t for t in tools if set(REGISTRY[t].arg_slots) & set(state["changed_slots"])]
    results = await asyncio.gather(*[
        registry.call(t, build_args(t, target, state["slots"]), caller_step="B6") for t in tools])

    diagnostics, errors, retries = dict(state.get("diagnostics", {})), [], 0
    for r in results:                                            # B7
        retries += r.attempts
        if r.error:  errors.append(f"{r.tool}: {r.error}")
        else:        diagnostics[r.tool] = None if r.empty else r.data

    if errors:
        audit_point_2(state, tools_called=tools, tool_retry_count=retries, slots_inferred=[])
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B7",
                    event="tool_system_error_after_retry", exit_code="E2",
                    tool_errors=errors, tool_retry_count=retries, reasoning_loops=loops)

    inferred = infer_slots_from_diagnostics(state["intent"], diagnostics)
    audit_point_2(state, tools_called=tools, tool_retry_count=retries,
                  slots_inferred=list(inferred), rediagnose=rediag)   # điểm log 2 [Chốt]
    return goto(state, S_RETRIEVING, next_node="b11_slots" if rediag else "b08_retrieve",
                step="B6", event="rediagnosed" if rediag else "diagnosed",
                diagnostics=diagnostics, slots={**state["slots"], **inferred},
                tool_retry_count=retries, ctx_flags={"target_is_other": is_other},
                reasoning_loops=loops, rediagnose=False)
```

**Chế độ chẩn đoán lại (D-20):**

- Chỉ được B11 kích hoạt, khi cờ `REDIAGNOSE_ON_NEW_SLOT=true` và slot vừa nhận thuộc `TOOL_ARG_SLOTS` = {`device_id`, `resource_path`, `target_user`, `software_name`, `account_type`} (xem B11 mục 5).
- Chỉ gọi tool có tham số bị đổi. Ví dụ đổi `device_id` → gọi lại `check_device_registered`, `check_vpn_cert_expiry` (VPN) hoặc `check_installed_list` (software).
- Sau khi chẩn đoán lại, đi thẳng về B11 (`S_DIAGNOSING → S_RETRIEVING`, chuyển đã có trong bảng gốc). Không tra KB và không phân loại info/action lại, vì B10 đã xác định đây là ca cần hành động.
- Mỗi lần chẩn đoán lại tính vào `reasoning_loops`. Nhờ vậy `MAX_LOOPS=5` có vòng thật để giới hạn: người dùng liên tục đổi đối tượng sẽ chạm trần → E2.
- Khóa audit và `effects.once` có `loop_seq`, nên B6/B11 lần hai trong cùng một lượt không bị coi là bản ghi trùng (P1 mục 5.1).

**Bảng suy slot (trích):**

| Intent | Kết quả chẩn đoán | Slot suy ra |
|---|---|---|
| vpn | `check_device_registered` → thiết bị LAP-0342 đã đăng ký | `device_id=LAP-0342`, `device_registered=true` |
| vpn | `check_vpn_cert_expiry` → hết hạn 3 ngày trước | `action=renew_vpn_cert` (khi người dùng chưa nói rõ) |
| account | `check_account_status` → locked, lý do nhập sai | `action=unlock_account`, `lock_reason=bad_password` |
| software | `check_catalog_entry` → có trong danh mục, miễn phí | `in_catalog=true`, `paid=false` |
| access | `check_current_permissions` → từng có quyền, hết hạn | `action=extend_permission` |

Các slot như `device_registered`, `in_catalog`, `paid`, `resource_sensitivity` cũng là **dữ kiện cho luật M5**. Vì vậy chẩn đoán phục vụ cả trải nghiệm lẫn an toàn.

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| Code chọn tool, LLM không chọn | Tất định, test được; câu dẫn dắt không khiến agent gọi tool ngoài phạm vi **[Chốt]** |
| 404/rỗng là dữ liệu hợp lệ | **[Chốt B7]** — ba nguyên tắc: EMPTY ≠ ERROR; 429/timeout/5xx = SYSTEM ERROR; không retry vô hạn |
| Chỉ retry đọc | Đọc lại không gây hại; ghi thì không (B17) |
| Một tool lỗi → cả nhánh E2 | Chẩn đoán thiếu một phần có thể khiến M5 thiếu dữ kiện → nguy cơ False Negative. Chọn an toàn **[Chốt: E2 khi `tool_errors` không rỗng]** |
| Target mặc định = người gửi (D-16) | Agent không thành công cụ dò thông tin đồng nghiệp; target khác được gắn cờ cho M5 |
| Chạy song song | Giảm độ trễ lượt đầu; 3 tool độc lập |
| Chẩn đoán lại chỉ tool bị ảnh hưởng, cờ tắt mặc định (D-20) | Có `facts` đúng cho đối tượng mới mà không gọi thừa; chờ chốt vì thêm một chuyển trạng thái |

## 7. Cấu hình

- `TOOL_RETRY=2`, `BACKOFF_BASE_SECONDS=1`, `MAX_LOOPS=5` **[Chốt]**
- Timeout tool đọc 5 giây **[Chốt 17.3]**
- Circuit breaker 5 lỗi/60 giây, mở 30 giây **[Chốt]**
- Cờ `ENABLE_PROACTIVE_DIAGNOSIS` (mặc định `true`)
- Cờ `REDIAGNOSE_ON_NEW_SLOT` (mặc định `false` tới khi D-20 được chốt) **[Đề xuất D-20]**
- `ToolSpec.arg_slots` cho 12 tool (khai báo trong tool registry, P5)

## 8. Dữ liệu, DB, điểm log

- **Điểm log 2 [Chốt]:** `tools_called`, `slots_inferred`, `tool_retry_count`; thêm `rediagnose` (D-20).
- **E2:** bản ghi `escalations` kèm tool nào lỗi và số lần retry **[Chốt ma trận 7]**; mức ưu tiên "Cao (hạ tầng)".

## 9. Trace và giám sát

- **Span:** `node:b06_diagnose`, 3 span `tool:<name>` (song song).
- **M9:**
  - Tỉ lệ gọi tool thành công **[Chốt chỉ số kỹ thuật]**.
  - Breaker mở → cảnh báo "hạ tầng ngoài yếu" **[Chốt 17.9.3]**.
  - p95 theo tool.
  - Số lần chẩn đoán lại mỗi ticket (D-20).

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| Tool trả rỗng | Đi tiếp, báo đúng "không tìm thấy" | TC17 **[Chốt]** |
| Tool trả 500 liên tục | Đúng 3 lần gọi → E2, không báo "không tồn tại" | TC18 **[Chốt]** |
| 500 rồi 200 | Thành công ở lần 2; `tool_retry_count=1` | — |
| Breaker AD đang mở | Lỗi ngay, E2 trong < 100 ms | — |
| "Kiểm tra VPN của anh Minh giúp em" | Target = Minh, `target_is_other=True` → M5 thấy cờ này | — |
| Tắt chẩn đoán (ablation) | Bỏ qua B6; B11 phải hỏi lại slot | TC06 biến thể **[Chốt cổng 3]** |
| Người dùng đổi `device_id` sau khi được hỏi (cờ D-20 bật) | Chỉ chạy lại tool dùng `device_id`; về B11 với `facts` mới | — |
| Người dùng đổi đối tượng liên tục | `reasoning_loops` chạm 5 → E2 | — |

## 11. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Unit | `infer_slots_from_diagnostics` | Bảng mục 5 đúng cho 4 intent |
| Unit | Chọn tool khi chẩn đoán lại | `changed_slots={"device_id"}`, intent vpn → đúng 2 tool có `device_id` trong `arg_slots` |
| Integration (respx / mock faults) | TC17, TC18 | Như bảng mục 10 |
| Integration | TC06 | 0 câu hỏi lại; `device_id` suy từ chẩn đoán |
| Integration | TC06 với cờ tắt | Agent hỏi `device_id` |
| Integration (cờ D-20 bật) | Hỏi `device_id` → trả lời → B6 chạy lại → B11 | `Action.facts.device_registered` đúng với thiết bị mới; 2 dòng điểm log 2 (`diagnosed`, `rediagnosed`) |
| Integration | Thời gian | 3 tool mỗi cái chậm 300 ms → cả bước < 500 ms (chứng minh chạy song song) |
| Probe (RQ3) | Cả bộ kịch bản, bật/tắt | Báo cáo số lượt hỏi lại trung bình và tỉ lệ giải quyết một lượt |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P5 (thêm `arg_slots` vào `ToolSpec`), P6 (`scope_tool_target`), B3, B11 (kích hoạt chẩn đoán lại).
- **Phase:** 1 (12 tool + test hợp đồng), 3 (node VPN), 5 (đủ 4 intent).
- **Việc còn mở:**
  - "Một tool lỗi → E2" có thể quá thận trọng với tool phụ (ví dụ `check_last_connection`). Có thể thêm cờ `critical` cho từng tool sau khi đo tỉ lệ E2 ở Phase 5 — không làm trước khi có số liệu.
  - D-20 cần nhóm và GVHD đồng ý (Q10) vì thêm chuyển `S_CLARIFYING → S_DIAGNOSING`.

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Thêm tool đọc | Khai báo `ToolSpec(kind="read", allowed_steps={"B6","B11"}, arg_slots=[…])`, adapter, schema; thêm vào `TOOL_MAP`; thêm dòng suy slot | Tool mới lỗi cũng đưa cả nhánh vào E2 → cân nhắc cờ `critical` (việc còn mở) |
| Nối hệ thống thật (AD, VPN gateway, SCCM/Intune, file server) | Viết adapter mới cho port tương ứng; giữ mock cho test | Không đổi schema đầu ra của tool; 404 vẫn là dữ liệu hợp lệ |
| Scale | Các tool chạy song song; breaker riêng cho từng hệ thống; cache đọc ngắn (≤ 60 giây) cho tool ít thay đổi (`check_catalog_entry`) | Không cache tool trạng thái (`check_account_status`) |
| Chẩn đoán nhiều bước (tool sau phụ thuộc tool trước) | Thêm "kế hoạch chẩn đoán" dạng DAG khai báo trong code, vẫn không để LLM chọn | Giữ giới hạn `MAX_LOOPS` |
| Tách thành module "Diagnostics" | Gói `tools/` (đọc) + `b06_diagnose`; phụ thuộc port và `call_with_retry` | Không đưa tool ghi vào module này |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| E2 tăng ở B6 | Điểm log 2 `tool_retry_count`; span `tool:*`; trạng thái breaker | Mock đang bơm lỗi; breaker mở lâu; timeout quá ngắn |
| Agent nói "không tồn tại" sai | Span tool: status 200 rỗng hay 5xx? | Adapter nuốt exception → trả None (vi phạm B7) |
| Agent vẫn hỏi `device_id` dù đã có | `slots` sau B6; bảng suy slot | Thiếu dòng suy slot cho intent đó; cờ ablation đang tắt |
| Luật allow không khớp sau khi người dùng bổ sung thiết bị | `Action.facts` có dữ kiện của thiết bị mới không | Cờ `REDIAGNOSE_ON_NEW_SLOT` tắt (hành vi an toàn mặc định); `arg_slots` của tool khai báo thiếu |
| B6 chậm | Thời lượng 3 span tool có chồng nhau không | Gọi tuần tự thay vì `asyncio.gather` |
| Tool tra cứu người khác | `ctx_flags.target_is_other` | `scope_tool_target` bị bỏ qua ở `build_args` |

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.2 | Bản vá: chế độ chẩn đoán lại (D-20, cờ tắt mặc định), `ToolSpec.arg_slots`, test tương ứng |
