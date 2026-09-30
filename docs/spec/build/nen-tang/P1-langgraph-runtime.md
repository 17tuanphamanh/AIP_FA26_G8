# P1 — LangGraph runtime (M4: điều phối)

*Thuộc bộ `build/`. Nền tảng mọi nhánh chạy trên đó. Phase 2 (khung, node giả), dùng từ Phase 3 trở đi. Bản vá v1.2: D-17 (ticket cha đối soát con), D-18 (side effect idempotent), D-19 (khóa cấp session), D-20 (chẩn đoán lại, cờ tắt mặc định), D-28 (constrained agent).*

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

**Mã quyết định dùng trong file (bản vá v1.2):** D-08, D-14 (khóa mới), D-17, D-18, D-19, D-20, D-28.

---

## 1. Mục đích

Biến máy trạng thái 14 trạng thái / 20 bước **[Chốt]** thành một graph chạy được, có 3 chỗ dừng chờ người tới 48 giờ, khởi động lại vẫn chạy tiếp đúng chỗ, và không một lỗi nào làm ticket kẹt hay làm sập worker.

### 1.1. Vì sao là "constrained agent" — lập luận khi hội đồng hỏi "đâu là phần agent?" [Đề xuất D-28]

LangGraph ở đây được dùng như một **máy trạng thái bền vững** chứ không phải vòng lặp ReAct nơi LLM tự chọn bước tiếp theo. Đây là lựa chọn có chủ đích:

| Việc | Ai làm | Vì sao |
|---|---|---|
| Hiểu ngôn ngữ: intent, slot, info/action, câu hỏi bổ sung, câu trả lời có trích dẫn | LLM (B3, B10, B11) | Phần mà chỉ LLM làm tốt |
| Ước lượng rủi ro khi không có luật | LLM + calibrator (B14) | Phần xác suất, có hiệu chỉnh |
| Chọn tool chẩn đoán, chọn bước kế tiếp, quyết định hành động | Code (`TOOL_MAP`, `goto()`, luật) | Tất định, test được; câu dẫn dắt không đổi được luồng **[Chốt]** |
| Ghi ra hệ thống ngoài | Chỉ B17, credential riêng | Điểm ghi duy nhất **[Chốt]** |

Tính agent thể hiện ở ba chỗ đo được:

1. **Chủ động thu thập dữ liệu** trước khi hỏi (B6, RQ3).
2. **Tự quyết định tự làm / cần duyệt / chuyển L2** (M5, RQ1).
3. **Tự điều chỉnh hội thoại** (hỏi lại có giới hạn, chẩn đoán lại khi có thông tin mới — D-20).

Căn cứ: ITBench (agent SOTA chỉ giải 11–26% kịch bản IT) và Policy-as-Prompt (luật + LLM + người xem lại). Trong môi trường ghi vào hệ thống thật, để LLM tự chọn hành động là rủi ro không đáng đổi lấy độ linh hoạt. Khi trình bày, gọi đúng tên: *agent có ràng buộc (constrained / workflow agent)*.

## 2. Sơ đồ cấu tạo

```
            API / worker (sự kiện)
                   │ submit(ticket_id) / resume(ticket_id, payload) / recover(ticket_id)
            ┌──────▼───────────────────────────────────────────────┐
            │ runner.py                                             │
            │  1. ticket_lock: pg_advisory_lock(hashtext(ticket_id))│
            │     trên LOCK POOL riêng, lock_timeout (D-19)         │
            │  2. semaphore (N graph đồng thời / process)           │
            │  3. submit/resume: turn_id mới → bảng turns           │
            │     recover: GIỮ turn_id cũ (D-18)                    │
            │  4. graph.ainvoke(input | Command(resume=…) | None)   │
            │  5. finally: pg_advisory_unlock                       │
            └──────┬───────────────────────────────────────────────┘
                   │ config = {thread_id: ticket_id, recursion_limit: 60}
            ┌──────▼───────────────────────────────────────────────┐
            │ CompiledGraph (builder.py)                            │
            │   mỗi node = traced( with_error_boundary( fn ) )      │
            │   cạnh = add_conditional_edges(node, route_next, map) │
            │   checkpointer = AsyncPostgresSaver(pool)             │
            └──────┬───────────────────────────────────────────────┘
                   │ node trả về goto(...) ; side effect qua effects.once(...)
            ┌──────▼──────────────┐      ┌──────────────────────────┐
            │ goto.py             │─────►│ audit_logs (idempotent)  │
            │ kiểm chuyển hợp lệ  │      │ tickets (chỉ ở B20)      │
            └─────────────────────┘      └──────────────────────────┘
            ┌─────────────────────┐      ┌──────────────────────────┐
            │ effects.py (D-18)   │─────►│ side_effects (khóa duy   │
            │ once(key, fn)       │      │ nhất cho mỗi side effect)│
            └─────────────────────┘      └──────────────────────────┘
```

## 3. Công nghệ

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Graph | `langgraph` 1.x, `StateGraph` | **[Chốt]** |
| Checkpoint | `langgraph-checkpoint-postgres`, `AsyncPostgresSaver` + `psycopg_pool.AsyncConnectionPool` | Chung Postgres với ticket/audit **[Chốt]** |
| Dừng chờ người | `langgraph.types.interrupt()` + `Command(resume=…)` | **[Đề xuất D-08]**, xem mục 6 |
| Khóa ticket | `pg_advisory_lock` **cấp session** trên một pool kết nối riêng (`LOCK_POOL_SIZE = GRAPH_CONCURRENCY + 2`), nhả trong `finally`, `SET lock_timeout` | **[Đề xuất D-19]** — không giữ transaction mở suốt lượt có gọi LLM (bản 1.0 dùng `pg_advisory_xact_lock`, xem mục 7.1) |
| Side effect | `effects.once(key, fn)` + bảng `side_effects` | **[Đề xuất D-18]**, xem mục 5.3 |
| Chạy nền | `asyncio.create_task` trong backend + `asyncio.Semaphore` | API trả 202 ngay **[Chốt 14.3]** |
| Lịch | APScheduler (worker) | **[Chốt]** |

## 4. State

```python
# domain/ticket_state.py
class TicketState(TypedDict, total=False):
    # định danh
    ticket_id: str; parent_ticket_id: str | None; is_parent: bool; children: list[str]
    parent_round: int; awaiting: dict[str, str]   # chỉ ticket cha (D-31): vòng tin tổng hợp, ý đang chờ người dùng
    session_id: str; turn_id: str
    # người gửi — do B1 chụp, chỉ đọc sau đó
    requester_context: RequesterContext   # user_id, role, dept, manager_id,
                                          # employment_status, tenure_days, locale
    # nội dung
    redacted_request: str                 # đã qua privacy guard (D-07); raw không vào state
    conversation: Annotated[list[Msg], append_capped(20)]
    # phân loại / chẩn đoán / tra cứu
    intent: str | None; intent_confidence: float | None; span: str | None
    slots: dict; missing_slots: list[str]
    diagnostics: dict; tool_errors: list[str]; tool_retry_count: int
    retrieved: list[ChunkRef]; retrieval_score: float; retrieval_error: str | None
    need_type: Literal["info", "action"] | None
    # hành động + rủi ro + duyệt
    intended_action: Action | None; action_plan_hash: str | None
    risk: RiskDecision | None             # decided_by, policy_decision, matched_rule_id,
                                          # raw_prob, calibrated_prob, risk_level, reason
    approval_id: str | None
    approval_result: Literal["approved", "rejected", "timeout"] | None   # NGU-CANH Phần IV mục 3; FORBIDDEN 2 kiểm trường này
    execution: ExecutionResult | None
    # bộ đếm [Chốt]
    clarification_turns: int; reasoning_loops: int; off_topic_streak: int
    # điều khiển
    status: str                           # 1 trong 14 S_*
    next: str                             # tên node kế tiếp, do goto() đặt
    exit_code: str | None; block_reason: str | None; close_reason: str | None
```

**Khác với `TicketState` trong `NGU-CANH-DAY-DU.md` Phần IV mục 3:**

- `raw_request` được thay bằng `redacted_request` **[Đề xuất D-07]**.
- `requester_id/role/dept` được gộp thành `requester_context` (thêm `employment_status`, `tenure_days`, `manager_id` cho các luật "nhân viên mới", "người đã nghỉ việc", xung đột lợi ích).
- Thêm `next`, `is_parent`, `children`, `off_topic_streak`; ticket cha thêm `parent_round`, `awaiting` (D-31).
- Bỏ `audit_trail` khỏi state, vì audit đã nằm trong bảng `audit_logs` **[Chốt ở thiết kế DB vòng 3]**.

**Vì sao `retrieved` chỉ chứa `ChunkRef`** (`chunk_id`, `doc_id`, `score`, trích đoạn ≤ 600 ký tự): checkpoint được ghi sau mỗi node, nên state lớn sẽ bị nhân lên theo số node.

**`turn_id` và `loop_seq` [Đề xuất D-18]:** `turn_id` do runner đặt khi có **sự kiện mới** (submit, resume). Khi phục hồi sau sự cố, runner gọi `graph.ainvoke(None, cfg)` để chạy tiếp từ checkpoint cuối và **không** đổi `turn_id`. Nhờ vậy mọi khóa idempotent tính từ `turn_id` giữ nguyên giữa lần chạy hỏng và lần chạy lại. `loop_seq` = giá trị `reasoning_loops` tại thời điểm ghi, dùng để phân biệt hai lần đi qua cùng một bước trong cùng một lượt (xảy ra khi D-20 được bật).

## 5. Build graph

```python
# graph/builder.py
def build_graph(pool) -> CompiledGraph:
    b = StateGraph(TicketState)
    for name, fn in ALL_NODES.items():                  # b01_identity … b20_audit, clarify_wait,
        b.add_node(name, traced(with_error_boundary(fn)))   #   approval_wait, confirm_wait, parent_wait, parent_reply_wait (D-31)
    b.add_edge(START, "b01_identity")
    for name, targets in ROUTES.items():                # định tuyến RIÊNG từng node [Chốt]
        b.add_conditional_edges(name, route_next, targets)
    return b.compile(checkpointer=AsyncPostgresSaver(pool))

def route_next(state) -> str:
    return state["next"]                                # KHÔNG route theo status
```

`ROUTES` là một dict khai báo cho mỗi node tập đích hợp lệ. Test tĩnh kiểm tra: mọi giá trị `next` mà node có thể trả về đều nằm trong tập đích của node đó, và mọi node có đường tới `b20_audit`.

**D-20 (chẩn đoán lại) trong `ROUTES`:** `b11_slots` và `clarify_wait` có thêm đích `b06_diagnose`, chỉ dùng khi cờ `REDIAGNOSE_ON_NEW_SLOT=true` và cặp `(S_CLARIFYING, S_DIAGNOSING)` đã được thêm vào `ALLOWED_TRANSITIONS`. Cờ **mặc định tắt** cho tới khi nhóm chốt D-20, vì nó thêm một chuyển trạng thái chưa có trong bảng 2.1 gốc. Chi tiết ở `B11` mục 5 và `B06-B07` mục 5.

**Ghi chú [Đề xuất nhỏ, không bắt buộc]:** LangGraph 1.x cho phép node trả `Command(update=…, goto=…)`, là cách chính thức để node tự chọn node kế tiếp. Cách `route_next` đọc `state["next"]` cho kết quả tương đương và giữ được test tĩnh trên `ROUTES`. Nếu đổi sang `Command`, phải giữ nguyên test tĩnh "mọi đích nằm trong tập cho phép" và kiểm với phiên bản pin ở T01.

### 5.1. `goto()` — cổng đổi trạng thái duy nhất

```python
# graph/goto.py
def goto(state, to_status, *, next_node, step, event, **fields) -> dict:
    frm = state["status"]
    if (frm, to_status) not in ALLOWED_TRANSITIONS or (frm, to_status, fields) in FORBIDDEN:
        raise IllegalTransition(frm, to_status)          # bị E9 bắt nếu lọt tới đây
    loop_seq = fields.get("reasoning_loops", state.get("reasoning_loops", 0))
    audit.write(ticket_id=state["ticket_id"], turn_id=state["turn_id"], step=step,
                event=event, from_status=frm, to_status=to_status, **audit_fields(fields),
                idempotency_key=sha256(state["ticket_id"], step, event,
                                       state["turn_id"], loop_seq))            # D-14 (khóa v1.2)
    return {"status": to_status, "next": next_node, **fields}
```

**Kiểm key trả về [Chốt khi hiện thực Phase 2b-2]:** `goto()` và `with_error_boundary` từ chối mọi key không khai báo trong `TicketState` (ném lỗi → E9). Lý do: LangGraph 1.x **bỏ im lặng** key không khai báo — node gõ sai tên hoặc đặt key chưa có trong state thì giá trị biến mất, không lỗi, không log, chỉ sai số liệu về sau (phát hiện ở 2b-2 với `resolution_path`). Có test đối chiếu và mutation "bỏ kiểm key" đã bị bắt.

**Vì sao audit ghi bằng khóa idempotent:** khi resume, node chờ chạy lại từ đầu (mục 6), nên có thể gọi `goto()` lần hai. Dùng `INSERT … ON CONFLICT DO NOTHING` theo khóa idempotent để không ghi trùng. **[Đề xuất D-14]**

**Vì sao khóa có thêm `event` và `loop_seq` (sửa ở v1.2):** khóa cũ `(ticket_id, step, turn_id)` trùng nhau khi cùng một bước ghi hai sự kiện khác nhau trong một lượt. Ví dụ: sau khi người dùng trả lời, `clarify_wait` ghi `B11/user_replied`, rồi `b11_slots` ghi `B11/action_built`, cả hai cùng `turn_id` → bản ghi thứ hai bị bỏ qua âm thầm. Thêm `event` khắc phục trường hợp này; thêm `loop_seq` khắc phục trường hợp đi qua cùng một bước hai lần trong một lượt (D-20).

**Vì sao audit và checkpoint có thể lệch nhau, và cách xử lý:** checkpoint do LangGraph ghi sau khi node trả về, còn audit ghi trong node. Nếu process chết giữa hai lần ghi, ta có audit nhưng chưa có checkpoint. Khi chạy lại (`recover`, giữ `turn_id`), node chạy lại và khóa idempotent bỏ qua bản audit trùng. Kết quả cuối vẫn nhất quán.

### 5.1.1. `ALLOWED_TRANSITIONS` viết tường minh [Đề xuất D-29]

**Vấn đề (L-13):** bảng 2.1 **[Chốt]** chỉ liệt kê các chuyển *có nghĩa nghiệp vụ*, nhưng mã giả của các nhánh còn dùng ba loại chuyển không có trong bảng: giữ nguyên trạng thái (B08→B10, B10→B11 ở `S_RETRIEVING`; B12→B15 ở `S_ASSESSING`), lối thoát E2/E9 từ `S_NEW`/`S_SCREENING`, và ticket cha đóng bằng tổng hợp. Nếu `ALLOWED_TRANSITIONS` chỉ chép bảng 2.1 thì các lời gọi này ném `IllegalTransition`. Tệ nhất là `with_error_boundary` cũng gọi `goto()`, nên lỗi ở B1/B2 làm chính boundary ném lỗi và ticket kẹt.

```python
# domain/states.py
TERMINAL   = {S_RESOLVED, S_REJECTED, S_BLOCKED}          # S_ESCALATED do L2 đóng, không qua graph
PROCESSING = {S_NEW, S_SCREENING, S_CLASSIFYING, S_DIAGNOSING, S_RETRIEVING, S_ASSESSING, S_EXECUTING}

TABLE_2_1 = {...}                                          # chép nguyên bảng 2.1 [Chốt]
TABLE_2_1 |= {(S_CLARIFYING, S_DIAGNOSING)} if cfg.REDIAGNOSE_ON_NEW_SLOT else set()   # D-20

PARENT_ONLY = {                                            # chỉ hợp lệ khi state["is_parent"] (D-31)
    (S_CLASSIFYING, S_CONFIRMING), (S_CONFIRMING, S_CLASSIFYING),
    *((a, b) for a in (S_CLASSIFYING, S_CONFIRMING) for b in (S_RESOLVED, S_REJECTED, S_ESCALATED)),
}

def is_allowed(state, frm, to):
    if (frm, to) in TABLE_2_1:                       return True
    if frm == to and frm in PROCESSING:              return True   # quy tắc 1: chỉ đổi `next`
    if to == S_ESCALATED and frm not in TERMINAL | {S_ESCALATED}:
        return True                                                  # quy tắc 2: hướng an toàn (E2, E9)
    if state.get("is_parent") and (frm, to) in PARENT_ONLY: return True   # quy tắc 3
    return False
```

`goto()` gọi `is_allowed(state, frm, to_status)` thay cho phép thử `in ALLOWED_TRANSITIONS`. Bảng `FORBIDDEN` (6 chuyển cấm **[Chốt 2.2]**) vẫn kiểm **sau** và luôn thắng.

**Cách hiện thực 3 chuyển cấm có điều kiện [Chốt 25/09/2026]** — đều theo hướng chặt hơn chữ gốc (giảm False Negative):

- **Cấm 2** (`S_PENDING_APPROVAL → S_EXECUTING` khi hết SLA): chặn **mọi** ca `approval_result != "approved"`, không chỉ ca hết hạn. Lối duy nhất từ chờ duyệt sang thực thi là đã được duyệt.
- **Cấm 3** (hash lúc thực thi khác lúc duyệt): thiếu hẳn `action_plan_hash` lúc duyệt cũng chặn.
- **Cấm 4** (`→ S_RESOLVED` không qua ghi log): ở `domain` chỉ kiểm `step`/`event` không rỗng; `goto()` (Phase 2) kiểm thêm dòng audit đã ghi trong cùng transaction.

**Chuyển cấm số 5 đã nới (chốt 25/09/2026):** `S_SCREENING` → ngoài {`S_CLASSIFYING`, `S_BLOCKED`, **`S_ESCALATED`**}. Nếu không nới, quy tắc 2 bị cấm 5 chặn và lỗi ở B2 không ra được E2/E9 (test mục 11 đỏ). `S_ESCALATED` chỉ chuyển cho người nên không tạo đường vòng qua sàng lọc. `S_SCREENING → S_SCREENING` (quy tắc 1) **vẫn cấm**: B2 là một node, không cần giữ nguyên trạng thái.

**Vì sao ba quy tắc này không làm yếu an toàn:**

- Quy tắc 1 không đổi trạng thái, nên không bỏ qua bước nào. Bước tiếp theo vẫn do `ROUTES` kiểm.
- Quy tắc 2 chỉ mở đường **về phía con người** (escalate). Đây là hướng mà nguyên tắc 1 **[Chốt]** luôn cho phép. Không có quy tắc nào mở đường mới tới `S_EXECUTING`.
- Quy tắc 3 chỉ áp cho ticket cha. Ticket cha không bao giờ tự thực thi gì, vì mọi `Action` nằm ở con.

**Test tĩnh mới:** quét AST mọi lời gọi `goto(state, S_X, …)` trong `graph/nodes/`, suy ra trạng thái vào từ `ROUTES`, kiểm mọi cặp đều qua `is_allowed`.

### 5.2. `with_error_boundary` — E9 [Chốt 6.4]

Giữ nguyên mã giả ở `huong-dan-xay-dung-he-thong-2.md` mục 6.4, thêm hai điểm:

- **Không** bắt `GraphInterrupt` (exception nội bộ LangGraph dùng để dừng). Bắt nhầm sẽ biến mọi lần chờ người thành E9.
- Ghi span `status="error"` + traceback rút gọn (≤ 4 KB).

```python
def with_error_boundary(fn):
    @wraps(fn)
    async def wrapped(state):
        try:
            return await fn(state)
        except GraphInterrupt:
            raise
        except Exception as e:
            log_error(state, fn.__name__, e)
            return goto(state, S_ESCALATED, next_node="b20_audit", step=fn.__name__,
                        event="unhandled_exception", exit_code="E9",
                        escalation_note=f"Lỗi hệ thống không lường trước tại {fn.__name__}")
    return wrapped
```

### 5.3. Side effect idempotent — `effects.once` [Đề xuất D-18]

**Vấn đề (L-02):** audit đã idempotent, nhưng các side effect khác trong node thì chưa: `notify_user`, `notify(approver)`, `deadlines.set`, `approvals.create`, `tickets.create_child`, `runner.submit(child)`. Nếu process chết **sau** side effect nhưng **trước** khi LangGraph ghi checkpoint, lần chạy lại sẽ làm lại side effect: 2 phiếu duyệt, 2 thông báo, 2 lần submit ticket con.

**Cách làm:** mọi side effect đi qua một hàm duy nhất.

```python
# graph/effects.py
async def once(state, kind: str, fn, *args, step: str, sub: str = "", **kwargs):
    # kind ∈ CHECK của bảng side_effects (P7); sub phân biệt nhiều lần cùng kind trong một bước
    # (ví dụ mỗi ticket con một sub = child_id)
    key = sha256(state["ticket_id"], step, state["turn_id"],
                 state.get("reasoning_loops", 0), kind, sub)
    async with db.tx() as tx:
        inserted = await tx.execute(
            "INSERT INTO side_effects(effect_key, ticket_id, kind, step, turn_id) "
            "VALUES (:k, :t, :kind, :s, :turn) ON CONFLICT DO NOTHING RETURNING effect_key", ...)
        if not inserted:                                   # đã làm ở lần chạy trước
            return await tx.scalar("SELECT result_ref FROM side_effects WHERE effect_key=:k")
        ref = await fn(*args, **kwargs)                    # làm đúng 1 lần
        await tx.execute("UPDATE side_effects SET result_ref=:r WHERE effect_key=:k", ...)
        return ref
```

Ví dụ dùng ở B15: `a_id = await effects.once(state, "approval_create", approvals.create, ..., step="B15")`. Lần chạy lại trả về đúng `approval_id` cũ thay vì tạo phiếu mới.

**Kiểm tĩnh "không gọi thẳng side effect" [Chốt 25/09/2026, thay hợp đồng import-linter số 6]:** vì `once` nhận chính hàm (`fn`) làm tham số, node **phải import** được `approvals.create`, `notify_user`… — nên không thể cấm bằng import-linter. Thay bằng một test AST quét `graph/nodes/**`: mọi lời gọi trực tiếp (`Call`) tới các hàm trong `SIDE_EFFECT_FUNCS = {approvals.create, approvals.notify_approver, notify_user, deadlines.set, tickets.create_child, runner.submit}` đều làm test đỏ; chỉ được **tham chiếu** chúng làm tham số thứ ba của `effects.once`. `tickets` là repository ở `backend/app/db/tickets.py` (`create_child`, `mark_parent_once`, đọc `final_state`) **[Đề xuất]**. Thêm hàm side effect mới thì thêm tên vào `SIDE_EFFECT_FUNCS`.

**Ghi chú:** `side_effects` chỉ là chỉ mục chống trùng, có một chủ sở hữu duy nhất là hàm `once`. Nó không nhân đôi dữ liệu nghiệp vụ của checkpoint, nên không vi phạm nguyên tắc DB vòng 3 (xem P7). Thông báo gửi ra ngoài hệ thống (email, Teams) vẫn có một khe nhỏ "đã gửi nhưng chưa kịp ghi `result_ref`". Chấp nhận khe này vì thông báo trong app (bảng `notifications`) nằm cùng transaction.

## 6. Ba trạng thái chờ người: `interrupt()` [Đề xuất D-08]

Tài liệu LangGraph hiện ghi rõ static interrupt (`interrupt_before`/`interrupt_after`) là công cụ debug, không khuyến nghị cho human-in-the-loop. Cách được khuyến nghị là gọi `interrupt()` trong node rồi resume bằng `Command(resume=value)`. Khi resume, **node chạy lại từ đầu** — đúng lý do tài liệu gốc yêu cầu "việc trước khi chờ nằm ở node đứng trước".

| Node chờ | Trạng thái | Node đứng trước làm gì (side effect, qua `effects.once`) | Resume payload |
|---|---|---|---|
| `clarify_wait` | `S_CLARIFYING` | B11: sinh câu hỏi, gửi cho người dùng, đặt hạn 24 giờ. **Ticket con:** câu hỏi vào hộp thư con, không đặt hạn, đánh thức cha (D-31) | `{"kind":"user_reply","text":…}` hoặc `{"kind":"timeout"}` |
| `approval_wait` | `S_PENDING_APPROVAL` | B15: chọn người duyệt, băm Action, tạo phiếu, gửi thông báo, đặt hạn 30 phút | `{"kind":"approved"|"rejected","note":…,"approver_id":…}` hoặc `{"kind":"timeout"}` |
| `confirm_wait` | `S_CONFIRMING` | B18/B10: gửi kết quả, đặt hạn 48 giờ. **Ticket con:** kết quả vào hộp thư con, không đặt hạn, đánh thức cha (D-31) | `{"kind":"confirmed"|"unresolved","note":…}` hoặc `{"kind":"timeout"}` |
| `parent_wait` | `S_CLASSIFYING` (cha) | B5: tạo ticket con; hoặc `parent_reply_wait`: chuyển câu trả lời xuống các con | `{"kind":"wake"}` — **chỉ là tín hiệu đánh thức** (D-17, mục 8) |
| `parent_reply_wait` | `S_CONFIRMING` (cha) | `parent_notify`: gửi **một** tin tổng hợp, đặt hạn 24 giờ (có câu hỏi) hoặc 48 giờ (chỉ xác nhận) | `{"kind":"reply","items":{child_id:{…}}}` hoặc `{"kind":"timeout"}` (D-31, mục 8.3) |

```python
async def approval_wait(state):                     # KHÔNG có side effect nào trước interrupt()
    ev = interrupt({"wait": "approval", "approval_id": state["approval_id"]})
    return b16_decide(state, ev)                    # hàm thuần → goto(...)
```

### 6.1. Guard sự kiện muộn [Chốt 8.3]

```python
# graph/late_event.py — gọi bởi API và worker TRƯỚC runner.resume
async def deliver_event(ticket_id, expected_status, event):
    async with runner.ticket_lock(ticket_id):
        snap = await graph.aget_state(cfg(ticket_id))
        if snap.values["status"] != expected_status or not snap.next:
            audit.write_late_event(ticket_id, expected_status, snap.values["status"], event)
            raise Conflict409("Yêu cầu đã chuyển sang bước khác")
        await runner.resume(ticket_id, event)       # turn_id mới, Command(resume=event)
```

Sự kiện timeout của worker đi qua **đúng hàm này**, nên timeout và thao tác của người không bao giờ chạy hai đường code khác nhau **[Chốt]**.

**Ticket con không nhận sự kiện trực tiếp từ người dùng (D-31):** API `messages`/`confirm` gọi vào ticket con trả 409 "Vui lòng trả lời trong hội thoại chung". Con chỉ nhận sự kiện do cha chuyển xuống (`via_parent=True`, danh tính `svc_worker`) hoặc timeout của lưới an toàn (mục 8.3).

**Ngoại lệ có chủ đích cho `wake_parent` (D-17):** B20 của ticket con, và các con vừa dừng ở `clarify_wait`/`confirm_wait`, gọi `wake_parent(parent_id)` thay vì `deliver_event`. Nếu cha chưa ở `parent_wait`, lời gọi này **không** báo lỗi và không ghi `late_event` — cha sẽ tự đối soát khi tới `parent_wait` (mục 8).

## 7. Runner, khóa và worker

| Việc | Cách làm | Vì sao |
|---|---|---|
| Khóa theo ticket | `pg_advisory_lock(hashtext(ticket_id))` **cấp session** trên pool khóa riêng; `SET lock_timeout = '20s'`; nhả bằng `pg_advisory_unlock` trong `finally` **[Đề xuất D-19]** | Hai sự kiện cùng lúc không chạy song song trên một ticket **[Chốt 14.3]**, mà không giữ transaction mở suốt lượt |
| Giới hạn đồng thời | `Semaphore(GRAPH_CONCURRENCY=8)` mỗi process | Không làm cạn pool DB và hạn mức LLM |
| Turn | Mỗi lần submit/resume tạo `turn_id`; ghi `turns` lúc bắt đầu và kết thúc. `recover` giữ `turn_id` cũ **[Đề xuất D-18]** | Nền cho trace **[Chốt 17.1]**; khóa idempotent ổn định khi phục hồi |
| Phục hồi sau sự cố | Khi khởi động, worker tìm `turns` có `ended_at IS NULL` quá 2 phút → `runner.recover(ticket_id)` = `ainvoke(None, cfg)` dưới khóa ticket | Ticket không kẹt khi process chết giữa lượt |
| Giới hạn phục hồi [Chốt 2b-2] | Trước **mỗi** lần recover, worker `UPDATE turns SET recover_attempts = recover_attempts + 1 … RETURNING` (migration 0005). Vượt 3: lượt kẹt ở B20 → audit `finalize_failed_permanent` + đóng lượt; kẹt ở node khác → ticket sang E9 (`reason_detail=recover_exhausted`) qua B20 | Đếm **số lần thử**, không đếm số lần thất bại: process bị giết (OOM, SIGKILL) không kịp ghi span lỗi, đếm lỗi sẽ ra 0 và thử vô hạn |
| Recursion | `recursion_limit=60` | Lưới cuối, sau `MAX_LOOPS=5` |
| Tạo ticket [Chốt 2b-3] | `POST /api/tickets`: một transaction `INSERT tickets(created_at = Clock của app)` + `INSERT turns('submit')` → task nền `runner.run_new(ticket_id, turn_id)` → 202. `run_new` dưới khóa: lượt đã đóng hoặc thread đã có state → không làm gì; ngược lại chạy initial dựng từ dòng `tickets` | Worker recover và task nền có thể tới theo thứ tự bất kỳ; chỉ một bên chạy |
| Sự kiện qua API [Chốt 2b-3] | Request lấy khóa ticket (chờ ≤ `lock_timeout`), guard → 409/422; hợp lệ → **giao khóa** cho task nền (`resume_locked`), trả 202. try/finally + cờ `handed_off`: chưa giao (lỗi, 409, request bị hủy) → request nhả; đã giao → task nền nhả trong `finally`. Đang giữ khóa quá `lock_timeout` → 503 + `Retry-After` | Khóa advisory cấp session nằm trên kết nối của pool: request bị hủy mà không nhả thì kết nối về pool vẫn giữ khóa, ticket khóa vĩnh viễn |
| Snapshot rỗng khi recover [Chốt 2b-3] | Lượt mở mà thread chưa có checkpoint (process chết sau khi commit `tickets.create`, trước checkpoint input) → `recover` (đang giữ khóa) chạy state đầu dựng từ dòng `tickets` như `run_new`, giữ `turn_id` — **không gọi** `run_new`, vì `run_new` tự lấy khóa ticket mà recover đang giữ (tự khóa chết). Vượt 3 lần thử ở khe này → `_give_up_before_checkpoint`: dựng state từ dòng `tickets`, E9 `recover_exhausted` (audit `no_checkpoint`), chạy B20 (finalize + escalation + thông báo) | Trước đây nhánh này đóng lượt → ticket không `final_state`, biến mất khỏi mọi hàng đợi. Chết ở B1 thì đã có checkpoint input (LangGraph ghi trước node đầu) nên đi đường E9 `recover_exhausted` sẵn có |
| Task nền trong backend [Chốt 2b-3] | Tập giữ tham chiếu task; `done_callback` log exception; tắt app: chờ ≤ N giây rồi hủy. `CancelledError` là `BaseException` → boundary không biến thành E9, lượt còn mở cho worker recover | asyncio chỉ giữ tham chiếu yếu tới task; exception của task không ai `await` sẽ mất |
| Worker | Mỗi 15 giây: `SELECT … WHERE deadline < now() AND status IN (chờ) FOR UPDATE SKIP LOCKED LIMIT 200` → `deliver_event(timeout)` | `SKIP LOCKED` cho phép nhiều worker không đụng nhau |
| Nhắc duyệt | Worker gửi nhắc ở 50% và 80% thời hạn; ghi `approvals.reminder_1_at/2_at` để không gửi lại | **[Chốt]** |

**Bảng hạn chờ:** worker đọc hạn từ `approvals.deadline` (duyệt) và từ bảng nhẹ `wait_deadlines(ticket_id, kind, deadline)` cho `clarify`/`confirm` **[Đề xuất — ghi vào P7]**. Worker không đọc checkpoint.

### 7.1. Vì sao đổi khóa ở v1.2 [Đề xuất D-19]

Bản 1.0 dùng `pg_advisory_xact_lock`. Khóa này sống theo **transaction**, nên muốn giữ khóa suốt một lượt thì phải giữ một transaction mở suốt lượt đó. Mà một lượt kéo dài 10–15 giây vì gọi LLM **[Chốt 14.2]**. Hệ quả:

- Mỗi graph đang chạy chiếm 1 kết nối DB suốt lượt, cộng thêm kết nối của checkpointer và các lần ghi audit → với `GRAPH_CONCURRENCY=8`, pool mặc định dễ cạn.
- Transaction dài giữ snapshot, cản autovacuum và tăng nguy cơ deadlock khi API và worker cùng chạm một ticket.

Khóa cấp session tách "giữ khóa" khỏi "giữ transaction": kết nối trong pool khóa chỉ giữ khóa, còn mọi lần ghi nghiệp vụ dùng transaction ngắn trên pool chính. `lock_timeout` bảo đảm một ticket bị treo không làm treo worker. Nếu process chết, Postgres tự nhả khóa cấp session khi kết nối đóng.

## 8. Ticket con [Chốt B5, Đề xuất cơ chế + D-17, D-30, D-31]

- B5 tạo mỗi con một ticket mới, **thread riêng** (`ticket_id-n`), với `parent_ticket_id`. Việc tạo và submit con đi qua `effects.once` (D-18), nên chạy lại B5 không tạo con trùng. Cha chuyển sang `parent_wait` với `is_parent=True` và `children=[…]`.
- **Không dùng `Send` hay subgraph**, vì chúng chạy trong cùng một thread: con đang chờ duyệt 30 phút sẽ giữ chân con khác.
- `S_SPLIT` trong mã giả gốc được thay bằng cờ `is_parent`. Ticket cha ở `S_CLASSIFYING` khi đang chờ các con xử lý, và ở `S_CONFIRMING` khi đang chờ người dùng trả lời tin tổng hợp (D-31). Không thêm trạng thái thứ 15 **[Đề xuất — xem README mục 5]**.

### 8.1. Nguyên tắc "một lượt người dùng — một tin trả lời" [Chốt B5, diễn giải: Suy luận; cơ chế: Đề xuất D-31]

**[Chốt B5]:** "Gom kết quả mọi con thành **một** tin nhắn. Người dùng gửi một câu thì chỉ nhận một câu trả lời tổng hợp." Nhóm đã chọn giữ **đúng nguyên văn** (không cho mỗi ý nhắn riêng).

**Diễn giải dùng để thiết kế [Suy luận]:** mỗi lần người dùng gửi một tin trong hội thoại (câu gốc, hoặc một lần trả lời), hệ thống trả **đúng một** tin, và tin đó do **ticket cha** gửi. Ticket con **không bao giờ** nhắn trực tiếp cho người dùng.

Ba thành phần:

1. **Hộp thư con (`child_notices`, P7).** Mọi chỗ con định nhắn người dùng — B10 (câu trả lời), B11 (câu hỏi), B16 (lý do từ chối), B18 (kết quả), B20 (thông báo chuyển kỹ thuật viên) — đều gọi cùng hàm `notify_user`. Hàm này kiểm `state["parent_ticket_id"]`: nếu là con thì ghi vào `child_notices` (kèm `needs ∈ {none, answer, confirm}`) thay vì gửi. **Không nhánh nào phải đổi logic**, chỉ thêm tham số `needs` ở B10, B11, B18.
2. **Điểm dừng của con.** Con được coi là "đã dừng" khi (a) đã kết thúc (`tickets.final_state` có giá trị), hoặc (b) đang chờ người dùng ở `clarify_wait`/`confirm_wait` và có notice `needs≠none` chưa gửi. `S_PENDING_APPROVAL` **không** phải điểm dừng, vì đó là chờ L1, không phải chờ người dùng. Con ở điểm dừng (b) **không** đặt hạn riêng — hạn do cha giữ.
3. **Vòng của cha.** Cha lặp: chờ mọi con dừng → gửi một tin tổng hợp → chờ người dùng trả lời một lần → chuyển từng phần câu trả lời xuống đúng con → chờ các con dừng lại lần nữa → … cho tới khi mọi con kết thúc.

```python
# notify/service.py — điểm gửi tin DUY NHẤT cho người yêu cầu (luôn được gọi qua effects.once)
async def notify_user(state, text, *, needs="none"):
    if state.get("parent_ticket_id"):                              # ticket con (D-31)
        await child_notices.put(parent=state["parent_ticket_id"], child=state["ticket_id"],
                                step=current_step(), kind=kind_of(current_step()), needs=needs,
                                body=text, effect_key=current_effect_key())
        if needs != "none":
            await wake_parent(state["parent_ticket_id"])           # con sắp dừng ở clarify/confirm
        return "buffered"
    return await chat.send(state["ticket_id"], text)               # ticket thường hoặc ticket cha

# deadlines.set(...) với ticket con → không làm gì: hạn do cha giữ.
```

### 8.2. Mã giả vòng của cha

```python
async def parent_wait(state):                                    # S_CLASSIFYING (cha)
    view = await children_view(state["children"])                # đọc DB, không tin sự kiện (D-17)
    # view[cid] = {"final": final_state | None, "pending": [notice chưa gửi], "needs": none|answer|confirm}
    if not all(v["final"] or v["needs"] != "none" for v in view.values()):
        interrupt({"wait": "children"})                          # có con đang xử lý hoặc chờ L1 duyệt
        # Khi được đánh thức, LangGraph chạy lại node và interrupt() TRẢ VỀ giá trị resume
        # (không dừng lần nữa). Vì vậy phải quay lại chính node này để đối soát với dữ liệu mới,
        # thay vì đi tiếp với `view` cũ — đánh thức sớm (một con dừng, con khác chưa) là chuyện bình thường.
        return goto(state, S_CLASSIFYING, next_node="parent_wait", step="B5", event="parent_woken")
    rnd = state.get("parent_round", 0) + 1
    msg = compose_digest(view, round=rnd)                        # 1 tin, mỗi ý một khối, theo thứ tự ý
    await effects.once(state, "notify_user", send_to_requester, state, msg,
                       step="B5", sub=f"round:{rnd}")            # gửi THẬT — cha là nơi duy nhất gửi
    await child_notices.mark_delivered(state["children"], round=rnd)
    if all(v["final"] for v in view.values()):                   # không còn gì cần người dùng
        agg, final = aggregate_children(view)                    # bảng 6 trường hợp [Chốt B5]
        return goto(state, final, next_node="b20_audit", step="B5", event="children_aggregated",
                    aggregate_status=agg, parent_round=rnd)      # D-30: không exit_code, không close_reason
    kind = "clarify" if any(v["needs"] == "answer" for v in view.values()) else "confirm"
    await effects.once(state, "deadline_set", deadlines.set, state["ticket_id"], kind,
                       step="B5", sub=f"round:{rnd}")            # 24h nếu có câu hỏi, 48h nếu chỉ xác nhận
    return goto(state, S_CONFIRMING, next_node="parent_reply_wait", step="B5",
                event="digest_sent", parent_round=rnd,
                awaiting={cid: v["needs"] for cid, v in view.items() if not v["final"]})

async def parent_reply_wait(state):                              # S_CONFIRMING (cha)
    ev = interrupt({"wait": "parent_reply"})
    for cid, need in state["awaiting"].items():
        payload = ({"kind": "timeout"} if ev["kind"] == "timeout"
                   else to_child_event(need, ev["items"][cid]))  # answer → user_reply ; confirm → confirmed/unresolved
        await effects.once(state, "child_event", deliver_child_event, cid, payload,
                           step="B5", sub=f"{cid}:{state['parent_round']}")
    return goto(state, S_CLASSIFYING, next_node="parent_wait", step="B5",
                event="reply_dispatched" if ev["kind"] != "timeout" else "reply_timeout")
```

**Vì sao phải `goto` quay lại sau `interrupt()`:** khi resume, LangGraph chạy lại node từ đầu và `interrupt()` **trả về** giá trị resume thay vì dừng. Bản v1.2 kết thúc hàm ngay sau `interrupt()` nên ngầm dựa vào việc `next` vẫn là `parent_wait`. Bản này có thêm mã phía sau (gửi tin, đặt hạn), nên phải quay lại tường minh; nếu không, một lần đánh thức sớm (mới có một con dừng) sẽ gửi tin tổng hợp khi chưa đủ dữ liệu. Quy tắc 1 của D-29 cho phép giữ nguyên `S_CLASSIFYING`.

**`compose_digest` sinh tin theo mẫu, không dùng LLM** (tất định, không bịa). Mỗi ý một khối, có tiền tố "Ý 1 – Reset mật khẩu", gồm:

| Tình trạng con | Nội dung khối | Người dùng cần làm |
|---|---|---|
| Đã xong, chờ xác nhận | Kết quả (từ B10/B18) | Chọn "Đã ổn" / "Chưa ổn" + ghi chú |
| Cần thêm thông tin | Câu hỏi (từ B11) | Điền câu trả lời |
| Bị từ chối | Lý do từ chối (B16) | Không |
| Đã chuyển kỹ thuật viên | Thông báo E-code theo mẫu 7.1 **[Chốt]** | Không |

**API trả lời (một lần cho mọi ý):** `POST /api/tickets/{parent_id}/reply` với `{"items": {child_id: {"answer": …} | {"confirmed": bool, "note": …}}}`. Yêu cầu: `ticket:message` + chủ ticket; mọi ý trong `awaiting` phải có mặt (thiếu → 422). Văn bản trả lời đi qua privacy guard (L0–L1) như mọi tin nhắn **[Chốt 17.6]**. Sau đó gọi `deliver_event(parent_id, S_CONFIRMING, …)`, nên trả lời muộn sau khi cha đã đóng → 409 như mọi sự kiện muộn **[Chốt 8.3]**.

**Hết hạn:** worker phát `timeout` cho cha qua `deliver_event`. Cha chuyển `timeout` xuống từng con: con đang ở `clarify_wait` → E4 **[Chốt]**; con đang ở `confirm_wait` → `resolved_auto_timeout_48h` **[Chốt]**. Hạn của cha là 24 giờ nếu có ít nhất một câu hỏi, để không kéo dài `CLARIFY_TIMEOUT` **[Chốt]**; các ý chỉ cần xác nhận trong cùng tin cũng hết hạn theo 24 giờ này — sớm hơn 48 giờ, nhưng kết quả vẫn là `resolved_auto_timeout_48h` như **[Chốt]** (tên nhãn giữ nguyên để không đổi 8 giá trị `close_reason`).

**Chuyển xuống con khi con chưa kịp checkpoint:** `deliver_child_event` gọi `deliver_event(child_id, expected_status, payload)`. Nếu con vừa ghi notice nhưng chưa checkpoint ở node chờ (khe rất ngắn), guard trả 409; `deliver_child_event` thử lại sau 1 giây, tối đa 5 lần, và không ghi `late_event` cho các lần thử lại này.

**Lưới an toàn:** worker quét mỗi 60 giây: (a) cha ở `parent_wait` mà mọi con đã dừng → đánh thức; (b) con đang ở `clarify_wait`/`confirm_wait` mà cha đã kết thúc hoặc không tồn tại → phát `timeout` cho con. Không con nào bị treo vì cha lỗi.

### 8.3. Đánh đổi đã chấp nhận và cách giảm nhẹ

- **Người dùng chờ ý chậm nhất.** Nếu ý 1 xong ngay còn ý 2 chờ L1 duyệt, tin đầu tiên chỉ đến khi ý 2 có kết quả hoặc hết hạn duyệt (tối đa `SLA_MINUTES=30` **[Chốt]**, sau đó con thành E6 và đã dừng). **Giảm nhẹ [Đề xuất]:** khung trạng thái trên giao diện (T0, polling 2 giây **[Chốt]**) hiển thị tiến độ từng ý ("Đang xử lý", "Chờ IT duyệt", "Đã có kết quả — chờ tổng hợp"). Khung này không phải tin nhắn, nên không phá nguyên tắc một tin.
- **Tác dụng phụ bên ngoài vẫn xảy ra ngay.** Ví dụ reset mật khẩu gửi email mật khẩu mới ngay ở B17. Đó là hành vi của hệ thống ngoài, không phải tin trong hội thoại.
- **Câu hỏi làm rõ cũng bị gom.** Nếu ý 2 cần hỏi thêm trong khi ý 1 đang chờ duyệt, câu hỏi chỉ đến cùng tin tổng hợp. Đổi lại người dùng trả lời một lần cho mọi ý.

### 8.4. Đóng ticket cha [Đề xuất D-30]

- **`close_reason = NULL`** cho ticket cha. Không giá trị nào trong 8 giá trị **[Chốt]** mô tả "đóng vì tổng hợp", và CHECK `IN (…)` của Postgres cho qua NULL. Ý nghĩa nằm ở `aggregate_status`.
- **Cha không bao giờ có `exit_code` và không tạo dòng `escalations`.** Việc của L2 nằm ở ticket con đã escalate. Cha ở `S_ESCALATED` (theo bảng 6 trường hợp) chỉ để phản ánh kết quả; hàng đợi L2 lọc `is_parent=false`.
- **Mọi chỉ số M8/M9 chỉ tính ticket lá** (`tickets.is_parent = false`). Nếu không, một câu hai ý bị đếm thành ba ticket và tỉ lệ escalate bị thổi phồng.
- **Nguồn sự thật:** `tickets.final_state` của con được ghi đúng một lần ở B20 (`finalize_once`) **[Chốt DB vòng 3]**; notice chưa gửi đọc từ `child_notices`. Cha không đọc checkpoint của con.

## 9. Trace

`traced(fn)` mở span `node:<tên>` (thuộc `turn_id`, `trace_id`), ghi thời lượng và trạng thái (`ok`, `error`, `interrupted`). LLM gateway, tool registry và RAG tự mở span con. Tên span theo quy ước OpenTelemetry để sau này xuất sang Langfuse hoặc Jaeger **[Chốt 17.1]**.

## 10. Lỗi và ca biên

| Tình huống | Xử lý |
|---|---|
| Node ném exception chưa lường trước | E9, span error, worker không sập (TC29) |
| Process chết giữa lượt | Worker gọi `recover` (giữ `turn_id`) → chạy lại từ checkpoint cuối; audit và side effect idempotent (D-18) |
| Process chết sau khi B15 tạo phiếu, trước checkpoint | Chạy lại B15 → `effects.once` trả `approval_id` cũ; đúng 1 phiếu, 1 thông báo |
| Sự kiện đến khi không ở trạng thái chờ tương ứng | 409 + `late_event` (TC27 và 2 biến thể) |
| Con kết thúc trước khi cha vào `parent_wait` | Cha đối soát từ DB khi tới `parent_wait` → đóng đúng (D-17) |
| Người dùng gọi thẳng API xác nhận/nhắn tin vào ticket con | 409, hướng dẫn trả lời trong hội thoại chung (D-31) |
| Người dùng trả lời thiếu một ý | 422, không chuyển gì xuống con |
| Cha lỗi (E9) khi con đang chờ người dùng | Lưới an toàn phát `timeout` cho con → E4 hoặc tự đóng 48h |
| Hai sự kiện đồng thời | Khóa ticket: sự kiện thứ hai chờ, sau đó bị guard trả 409 |
| Process chết sau khi commit ticket, trước checkpoint đầu | Worker recover chạy state đầu dựng từ dòng `tickets` (như `run_new`), giữ `turn_id`; quá 3 lần → E9 `recover_exhausted` qua B20 (chốt 2b-3, mục 7) |
| Runtime không mở được lúc khởi động | Route ticket/duyệt 503; `/api/health` vẫn 200 với `"runtime": "down"` |
| Ticket bị treo giữ khóa quá `lock_timeout` | Sự kiện sau nhận lỗi tạm thời, worker thử lại chu kỳ sau; không treo worker |
| Chuyển trạng thái bị cấm | `IllegalTransition` → E9 (đây là bug, cần dev xem) |
| Vượt `recursion_limit` | `GraphRecursionError` → E9 |

## 11. Kiểm thử và tiêu chí đạt (cổng 2)

| Loại | Test |
|---|---|
| Unit | Bảng chuyển: mọi cặp hợp lệ qua, mọi cặp khác bị chặn, 6 chuyển cấm bị chặn **[Chốt]** |
| Unit | Khóa idempotent: `B11/user_replied` và `B11/action_built` cùng lượt → 2 dòng audit (D-14 v1.2) |
| Tĩnh | Mọi `next` có trong `ROUTES`; mọi node tới được `b20_audit`; mọi node được bọc boundary + traced |
| Tĩnh | Không node nào gọi trực tiếp `notify_user`, `approvals.create`, `deadlines.set`, `runner.submit` — chỉ qua `effects.once` (quét AST) |
| Integration | Tạo ticket → dừng ở `approval_wait` → **khởi động lại backend** → resume → chạy tiếp đúng chỗ |
| Integration | 3 trạng thái chờ × sự kiện muộn → 409 + `late_event`, trạng thái không đổi |
| Integration | Đếm thông báo: resume 2 lần → vẫn đúng 1 thông báo cho người duyệt |
| Integration | **Giết process ngay sau `approvals.create`, trước checkpoint** → recover → đúng 1 phiếu, 1 thông báo (D-18) |
| Integration | TC29: node giả ném `ValueError` → `S_ESCALATED`, E9, span error; 10 ticket khác song song vẫn xong |
| Integration | Hai `deliver_event` đồng thời cho một ticket → đúng 1 lần chạy tiếp |
| Integration | Ticket cha 3 con (resolved / rejected / escalated) → cha `S_ESCALATED`, `close_reason=NULL`, không dòng `escalations` cho cha (D-30) |
| Integration | TC34: 2 ý (allow + cần duyệt) → người dùng nhận **đúng 1 tin** sau khi L1 duyệt; trả lời 1 lần → 2 con `resolved_user_confirmed` → đúng 1 tin tổng kết (D-31) |
| Integration | TC35: 1 ý xong + 1 ý thiếu thông tin → 1 tin gồm kết quả + câu hỏi; trả lời → con 2 chạy tiếp; tổng số tin = số lượt người dùng (D-31) |
| Integration | TC36: người dùng chọn "Chưa ổn" cho ý 1 → con 1 E8, con 2 resolved → cha `RESOLVED + PARTIALLY_ESCALATED`, 1 tin tổng kết (D-31) |
| Tĩnh | Không node nào của ticket con gửi tin thật: `notify_user` với `parent_ticket_id` luôn ghi `child_notices` (D-31) |
| Tĩnh | Mọi `goto` trong `graph/nodes/` qua `is_allowed` (D-29) |
| Integration | Lỗi giả ở B1 và B2 → `S_ESCALATED` E9, không kẹt ở `S_NEW`/`S_SCREENING` (D-29) |
| Integration | **Ticket cha có 1 con bị E1 tức thì (trước khi cha vào `parent_wait`)** → cha vẫn đóng đúng (D-17) |
| Tải | 8 graph đồng thời, LLM giả chậm 10 giây/lượt → pool không cạn; không transaction nghiệp vụ nào mở quá 1 giây (`pg_stat_activity`) (D-19) |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P7 (bảng `turns`, `spans`, `audit_logs`, `wait_deadlines`, `side_effects`); `domain/states.py`.
- **Phase:** 2. Mọi nhánh sau dùng lại.
- **Việc còn mở:**
  - D-08 (`interrupt()`) và cách bỏ `S_SPLIT` cần nhóm xác nhận.
  - D-17, D-18, D-19 nên chốt **trước khi code Phase 2**, vì sửa sau rất đắt.
  - D-20 (thêm chuyển `S_CLARIFYING → S_DIAGNOSING`): cờ tắt ở bản đầu (Q10 đã chốt); chỉ bật khi tối ưu.
  - D-29 nên chốt **trước Phase 2** (mọi node đi qua `goto`).
  - D-30, D-31 chốt trước Phase 5 (ticket nhiều ý). Nhóm đã chọn giữ đúng câu "một tin nhắn" **[Chốt B5]**; nên báo GVHD đánh đổi ở mục 8.3.
  - Pin phiên bản LangGraph ở T01 và chạy test "khởi động lại" mỗi khi nâng phiên bản.

### Chốt khi hiện thực Phase 3 (30/09/2026)

Phase 3 hiện thực theo `build/phase3-thiet-ke-chi-tiet.md` mục 3.1, 9.0, 9.8, 10.7, 11.10; khi lệch, file đó thắng (trừ bất biến và mục [Chốt]).

- Bảng key `TicketState` Phase 3 (3.1); model trong state giữ Pydantic + `STATE_TYPES` (như code 2b).
- Hạn cho cả lượt `TURN_BUDGET_S=100`, `SAFETY_MARGIN_S=2`, đặt trước semaphore; hết hạn → E2 `turn_budget_exceeded` (ngoại lệ của quy tắc boundary → E9) (9.0, 9.8).
- `goto(..., lineage=…)` ghi lineage cùng transaction với audit (10.7 #3).
- Runner chạy graph với `durability="sync"`; worker recover tới B17 → E7 `execution_interrupted` với ghi chú "có thể đã gửi lệnh ghi…" (11.10 #9–10).
- 3h DỪNG 3b (phase3 11.10 #16): `RunContext.txlog` bắt buộc; `with_error_boundary` hỏi `begun` theo ticket trước nhánh E2/E9 → E7 `execution_interrupted` (lỗi `has_begun` → ném tiếp); runner `recover` lấy node còn dở qua `_pending` (`snap.next`, rỗng thì `snap.tasks`) — node chờ vừa resume mà ném lỗi không còn bị coi là thread đã kết thúc.

## 13. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0 |
| 25/09/2026 | 1.2 | Bản vá lõi AI: mục 1.1 constrained agent (D-28); khóa idempotent mới (D-14); `effects.once` + recover giữ `turn_id` (D-18); khóa cấp session (D-19); đối soát con từ DB (D-17); đích D-20 trong `ROUTES` (cờ tắt); thêm test tương ứng |
| 25/09/2026 | 1.3 | `ALLOWED_TRANSITIONS` tường minh với 3 quy tắc (D-29); đóng ticket cha, chỉ số trên ticket lá (D-30); vòng tổng hợp của cha, hộp thư con, `parent_reply_wait` (D-31); TC34–TC36 |
| 26/09/2026 | 1.4 | Chốt Phase 2b-2: `goto()`/boundary chặn key ngoài `TicketState` (mục 5.1); giới hạn phục hồi bằng `turns.recover_attempts`, tăng trước khi recover (mục 7) |
| 26/09/2026 | 1.5 | Chốt Phase 2b-3 (mục 7, 10): tạo ticket + `run_new` idempotent; sự kiện qua API trả 202 và giao khóa cho task nền; recover snapshot rỗng → chạy state đầu từ dòng `tickets` (không gọi `run_new`, tránh tự khóa chết), quá 3 lần → E9 qua B20; task nền và `CancelledError`; `/api/health` có `runtime` |
| 30/09/2026 | 1.6 | Thêm mục "Chốt khi hiện thực Phase 3" trỏ về `phase3-thiet-ke-chi-tiet.md` (mục 3.1, 9.0, 9.8, 10.7, 11.10) |
