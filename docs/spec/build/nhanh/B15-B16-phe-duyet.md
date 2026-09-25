# B15–B16 — Chuẩn bị phê duyệt, xung đột lợi ích, chờ duyệt có hạn (M6)

> **Tầng:** T3 · **Module:** M6 · **Objective:** 2 · **Phase:** 4 (luồng HITL hoàn chỉnh), 7 (giao diện)
> **Trạng thái vào:** `S_ASSESSING` (route = HITL) · **Ra:** `S_PENDING_APPROVAL` → `S_EXECUTING` | `S_REJECTED` | `S_ESCALATED` (E6)
> **Kịch bản thử Phase 4:** VPN cho thiết bị chưa đăng ký (luật R17 → cần duyệt; tài liệu cũ ghi R22) **[Chốt]**
> **Bản vá v1.2:** D-18 (tạo phiếu + thông báo idempotent, UNIQUE một phiếu `pending`), D-19 (khóa ticket cấp session)

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
| Nhánh trước | B12–B14 với route = HITL (luật `approval_required` hoặc p ở vùng giữa) |
| Nhận vào | `intended_action`, `requester_context`, `risk`, `intent` |
| Giao cho nhánh sau | Duyệt: `S_EXECUTING`, `next=b17_execute`, `approval_id`, `action_plan_hash`. Từ chối: `S_REJECTED`. Hết hạn: `S_ESCALATED` E6 |
| Ai dùng đầu ra | B17 (so hash, kiểm `approval.status`), B20 (`close_reason=rejected_by_approver`), M9 (thời gian phản hồi, E6, duyệt cho có), M8 |

**Chuyển trạng thái của nhánh [Chốt 2.1, 2.2]:**

| Từ | Sự kiện | Sang |
|---|---|---|
| `S_PENDING_APPROVAL` | Người duyệt đồng ý | `S_EXECUTING` |
| `S_PENDING_APPROVAL` | Người duyệt từ chối | `S_REJECTED` |
| `S_PENDING_APPROVAL` | Hết hạn SLA | `S_ESCALATED` → E6 |
| **Cấm** | `S_PENDING_APPROVAL → S_EXECUTING` khi hết SLA | — |
| **Cấm** | `S_PENDING_APPROVAL → S_EXECUTING` khi hash lúc thực thi khác lúc duyệt | — |

### 0.3. Đặc tả gốc đã chốt

- **B15 — xung đột lợi ích, 3 trường hợp chuyển Trưởng BP IT:**
  1. Người gửi chính là người duyệt.
  2. Người gửi là cấp trên trực tiếp của người duyệt — dễ bị bỏ sót, vì áp lực quyền lực làm việc duyệt mất ý nghĩa.
  3. Yêu cầu liên quan tới tài khoản của chính người duyệt.
- **Tại B15 chốt `action_plan_hash = hash(intended_action)`:**
  - Người duyệt phê duyệt đúng một ActionPlan cụ thể, không phải một sự cho phép chung chung.
  - Người duyệt nhìn thấy đúng nội dung đã băm, không có bản tóm tắt nào khác.
  - B17 băm lại và so; lệch dù chỉ một trường → E5.
- **B16 — ba kết quả:** đồng ý → B17; từ chối → ghi lý do (**bắt buộc**), thông báo, đóng; hết hạn → fail-safe E6.
- **Vì sao fail-safe:** ba hướng xử lý khi hết hạn —
  - Fail-safe: escalate L2.
  - Fail-open: agent tự làm — rủi ro cao, không dùng.
  - Phân tầng: phức tạp hơn.

  Chọn fail-safe vì đề tài lấy an toàn làm trọng tâm. Số lần timeout là chỉ số mới đáng báo cáo.
- **Nhắc:** T+0 gửi; T+50% nhắc lần 1; T+80% nhắc lần 2 và báo người dự phòng; T+100% → E6 và ghi SLA breach.
- **Chỉ số:** thời gian phản hồi trung bình, tỉ lệ timeout, tỉ lệ từ chối, thời gian xem mỗi ticket (dưới 5 giây gần như chắc là duyệt theo phản xạ).
- **Approval fatigue:** escalate > 40% → người duyệt bấm theo phản xạ, cơ chế thành hình thức (căn cứ HAS-Bench).
- **Sự kiện đến muộn:** ticket đã E6 mà người duyệt bấm "Đồng ý" 5 phút sau → bỏ qua, không kéo về `S_EXECUTING`, tránh làm hai lần khi L2 cũng đang xử lý.
- **Phase 4:** thử bằng VPN thiết bị chưa đăng ký → cần duyệt. Rủi ro chính: API và worker cùng xử lý một ticket → khóa `SELECT FOR UPDATE`, có test tranh chấp.

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC07 | Reset tài khoản quản trị, L1 đồng ý | Chỉ thực hiện sau khi duyệt |
| TC08 | Cấp quyền thư mục tài chính, L1 từ chối | Từ chối, ghi lý do |
| TC19 | L1 gửi yêu cầu cho chính mình | Trưởng BP duyệt |
| TC20 | L1 không phản hồi quá SLA | E6, không tự thực hiện |
| TC26 | Đồng ý nhưng ActionPlan đổi trước khi thực thi | E5 |
| TC27 | Bấm đồng ý sau khi đã hết hạn | Bị bỏ qua (409), không thực thi |
| TC23 | L1 ghi đè sau khi agent tự xử lý | Có bản ghi override (B20) |
| TC33 (mới, D-18) | Process chết sau khi tạo phiếu, trước checkpoint | Đúng 1 phiếu, đúng 1 thông báo |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- Không ai tự duyệt cho mình.
- Hết hạn không bao giờ thực thi.
- Từ chối phải có lý do.
- Deny không bao giờ tạo phiếu.
- L2 không duyệt.
- Mọi side effect ở B15, node chờ không có side effect.
- Mỗi ticket có tối đa **một** phiếu `pending` tại một thời điểm (D-18, ràng buộc DB).
- **Mã quyết định dùng trong file:** D-02 (`can_decide_approval`), D-08 (`interrupt()`), D-18, D-19 (bản vá v1.2), D-31 (v1.3).

---

## 1. Mục đích và vì sao tồn tại

Đưa con người vào đúng chỗ và đúng lúc, với bốn bảo đảm:

1. **Không ai tự duyệt cho mình**, kể cả dưới áp lực cấp bậc (3 trường hợp xung đột lợi ích) **[Chốt]**.
2. **Người duyệt duyệt đúng một `Action` cụ thể** (`action_plan_hash`), không phải một sự cho phép chung chung **[Chốt 5.2.1]**.
3. **Hết hạn thì không bao giờ tự làm** (fail-safe → E6) **[Chốt 8.2]**.
4. **Chống duyệt cho có:** đo thời gian xem, nhắc xác nhận lại khi xem dưới 5 giây **[Chốt 8.3, 16.2]**.

## 2. Sơ đồ cấu tạo

```
từ B12–B14 (route = HITL)
   ▼
[B15] b15_prepare_approval   ← MỌI side effect ở đây, không ở node chờ; tất cả qua effects.once (D-18)
   │ approver = pick_approver(intent, dept)         (L1 trực theo lịch; fallback Trưởng BP)
   │ conflict_check (3 trường hợp) ─ trùng ─► approver = Trưởng BP IT, conflict_detected=True
   │ action_plan_hash = hash_action(intended_action)   (chốt tại đây)
   │ effects.once("approval_create"): INSERT approvals(status=pending, deadline=now+SLA, hash, …)
   │     (UNIQUE: tối đa 1 phiếu pending mỗi ticket)
   │ effects.once("notify_approver") ; ghi điểm log 5
   ▼
S_PENDING_APPROVAL ─ approval_wait: interrupt({"wait":"approval"})
   │
   │  API POST /api/approvals/{id}/decision  (T1: require approval:decide + can_decide_approval)
   │     └─ SELECT … FOR UPDATE approvals ; deliver_event(expected=S_PENDING_APPROVAL)
   │  Worker (15s): 50% → nhắc 1 ; 80% → nhắc 2 + báo người dự phòng ; 100% → deliver_event(timeout)
   ▼
[B16] b16_decide (hàm thuần)
   ├─ approved (+ note tùy chọn)    ─► S_EXECUTING (B17 sẽ so hash)
   ├─ rejected (note BẮT BUỘC)      ─► S_REJECTED  (thông báo người dùng kèm lý do) ─► B20
   └─ timeout                       ─► S_ESCALATED E6 (SLA breach) ─► B20
   ghi điểm log 6 (result, note, response_time, view_duration)
```

## 3. Công nghệ tại nhánh

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Phiếu duyệt | Bảng `approvals` (CHECK: `rejected` phải có `note`; UNIQUE một phiếu `pending` mỗi ticket) | Chủ sở hữu vòng đời phê duyệt **[Chốt DB]**; lớp chặn thứ hai cho D-18 |
| Khóa | `SELECT … FOR UPDATE` trên phiếu + khóa ticket `pg_advisory_lock` cấp session trong `deliver_event` | Hai người bấm cùng lúc → 1 lần thực thi **[Chốt]**; khóa không giữ transaction dài (D-19, P1 mục 7.1) |
| Tạo phiếu, thông báo | `effects.once` | D-18 — không tạo phiếu/thông báo trùng khi B15 chạy lại |
| Hạn và nhắc | APScheduler (worker), `FOR UPDATE SKIP LOCKED` | **[Chốt]** |
| Chờ | `interrupt()` trong `approval_wait` | D-08 (P1 mục 6) |
| Quyền | `require("approval:decide")` + `can_decide_approval` | P6; L2 → 403 **[Chốt]** |
| Thông báo | Thông báo trong app (bảng `notifications` hoặc polling `/api/me/notifications`) | **[Chốt 16.1: Phải có]** |

## 4. Hợp đồng

```python
class ApprovalView(BaseModel):              # thứ người duyệt thấy (UI L1) — đúng thứ đã băm
    approval_id: str; ticket_id: str; deadline: datetime
    requester: RequesterContext             # role, dept
    request_summary: str                    # redacted_request (đã che), chỉ để hiểu ngữ cảnh
    action: Action                          # ĐÚNG object đã băm, hiển thị đủ trường + facts
    action_plan_hash: str
    risk: RiskDecision                      # luật khớp hoặc p + lý do
    diagnostics_summary: dict

class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=1000)
    reason_code: str | None                 # mẫu lý do chọn nhanh (Nên có) [Chốt 16.2]
    view_started_at: datetime               # client gửi; server đối chiếu approvals.first_viewed_at
```

**Quy tắc:** `rejected` mà thiếu `note` → 422 **[Chốt cổng 4]**.

## 5. Luồng xử lý chi tiết

```python
async def b15_prepare_approval(state):
    rc, action = state["requester_context"], state["intended_action"]
    approver = await approval.pick_approver(state["intent"], rc.department, at=clock.now())
    conflict = approval.conflict_type(requester=rc, approver=approver, action=action)
    #   "self"            : approver.id == rc.user_id
    #   "boss_of_approver": rc.user_id == approver.manager_id
    #   "targets_approver": action.target/requested_for là tài khoản của approver      [Chốt 3 trường hợp]
    if conflict:
        approver = await approval.department_head()               # Trưởng BP IT
    h = hash_action(action)
    a_id = await effects.once(state, "approval_create", approvals.create, step="B15",   # D-18
                              ticket_id=state["ticket_id"], approver_id=approver.id,
                              backup_approver_id=await approval.backup_for(approver),
                              deadline=clock.now() + timedelta(minutes=policy.SLA_MINUTES),
                              action_plan_hash=h, conflict_detected=bool(conflict),
                              conflict_type=conflict)
    a = await approvals.get(a_id)                                 # lần chạy lại: đúng phiếu cũ
    await effects.once(state, "notify_approver", approvals.notify_approver, a.approver_id, approval_link(a_id), step="B15")
    # dùng a.approver_id, không dùng approver vừa chọn: lần chạy lại có thể chọn người khác theo giờ trực
    audit_point_5(state, approver_id=a.approver_id, deadline=a.deadline,
                  conflict_detected=bool(conflict), action_plan_hash=h)          # [Chốt]
    return goto(state, S_PENDING_APPROVAL, next_node="approval_wait", step="B15", event="queued",
                approval_id=a_id, action_plan_hash=h)

async def approval_wait(state):
    ev = interrupt({"wait": "approval", "approval_id": state["approval_id"]})
    return await b16_decide(state, ev)

async def b16_decide(state, ev):
    a = await approvals.get(state["approval_id"])
    if ev["kind"] == "timeout":
        await approvals.close(a, "timeout")
        audit_point_6(state, result="timeout", response_time=None)
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B16",
                    event="sla_timeout", exit_code="E6")                 # KHÔNG BAO GIỜ tự làm [Chốt]
    await approvals.close(a, ev["kind"], note=ev.get("note"), decided_by=ev["approver_id"])
    audit_point_6(state, result=ev["kind"], note=ev.get("note"),
                  response_time=ev["at"] - a.created_at, view_duration=ev.get("view_duration"))
    if ev["kind"] == "approved":
        return goto(state, S_EXECUTING, next_node="b17_execute", step="B16", event="approved")
    await effects.once(state, "notify_user", notify_user, state, rejection_message(ev["note"]),
                       step="B16")                   # needs="none"; con: child_notices (D-31)
    return goto(state, S_REJECTED, next_node="b20_audit", step="B16", event="rejected",
                close_reason="rejected_by_approver")
```

**Ghi chú về `approvals.close` trong B16:** B16 chạy lại khi resume (node chờ chạy lại từ đầu). `approvals.close` phải là thao tác cập nhật có điều kiện (`UPDATE … WHERE status='pending'`), nên lần chạy thứ hai không đổi gì. Đây là idempotent tự nhiên của một cập nhật trạng thái, không cần `effects.once`.

**Handler API:**

```python
@router.post("/api/approvals/{approval_id}/decision")
async def decide(approval_id, body: DecisionIn, p=Depends(require("approval:decide"))):
    async with db.tx():
        a = await approvals.get_for_update(approval_id)                      # khóa hàng
        if not can_decide_approval(p, a): raise Forbidden403()               # duyệt hộ / tự duyệt
        if a.status != "pending" or clock.now() >= a.deadline:
            await approvals.mark_late(a, p.user_id)                          # "bỏ qua vì muộn" [Chốt TC27]
            raise Conflict409()
        if body.decision == "rejected" and not body.note: raise Unprocessable422()
    await deliver_event(a.ticket_id, S_PENDING_APPROVAL,
                        {"kind": body.decision, "note": body.note, "approver_id": p.user_id,
                         "at": clock.now(), "view_duration": view_duration(a, body)})
```

Transaction khóa hàng ở trên ngắn (chỉ đọc và kiểm tra). `deliver_event` lấy khóa ticket cấp session riêng (D-19), không nằm trong transaction đó.

**Ticket con của yêu cầu nhiều ý (D-31, v1.3):** hàm `notify_user` tự kiểm `state["parent_ticket_id"]`. Với ticket con, lời nhắn được ghi vào `child_notices` thay vì gửi, và `deadlines.set` không đặt hạn (hạn do ticket cha giữ). Ticket cha gom mọi lời nhắn thành **một** tin mỗi lượt người dùng **[Chốt B5]** (P1 mục 8.1–8.2). Logic của nhánh này không đổi. Với ticket con, lý do từ chối **[Chốt: bắt buộc có]** xuất hiện trong tin tổng hợp. `S_PENDING_APPROVAL` **không** phải điểm dừng của con: cha chờ tới khi phiếu có kết quả hoặc hết hạn (E6), rồi mới gửi tin. Vì vậy thời gian người dùng chờ tin đầu tiên tối đa bằng `SLA_MINUTES` **[Chốt]**.

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| Ba trường hợp xung đột lợi ích chuyển Trưởng BP | Trường hợp "người gửi là sếp người duyệt" dễ bị bỏ sót; áp lực cấp bậc làm việc duyệt mất ý nghĩa **[Chốt]** |
| Chốt hash tại B15, hiển thị đúng object đã băm | Người duyệt duyệt đúng cái sẽ được thực thi (chống lỗi TOCTOU) **[Chốt]** |
| Fail-safe khi hết hạn | Không bao giờ làm việc nhạy cảm khi thiếu giám sát **[Chốt]**. Số lần hết hạn là chỉ số đáng báo cáo |
| Nhắc 50% / 80% + người dự phòng | Giảm E6 mà không nới lỏng an toàn **[Chốt]** |
| Side effect ở B15, node chờ trống | Resume chạy lại node chờ → tránh gửi thông báo 2 lần **[Chốt]** |
| Tạo phiếu + thông báo qua `effects.once`, UNIQUE phiếu `pending` (D-18) | Process chết giữa lúc tạo phiếu và checkpoint → không có phiếu thứ hai; hai lớp chặn: mã và DB |
| Kiểm quyền theo bản ghi ở API | UI có bug hay người dùng sửa URL cũng không duyệt hộ được (P6) |
| Ghi `first_viewed_at` và thời gian xem | Phát hiện duyệt cho có (< 5 giây) **[Chốt]** |
| Không có "hủy yêu cầu đang chờ duyệt" | Cần một chuyển trạng thái không có trong gốc **[Chốt 16]** |

## 7. Cấu hình

- `SLA_MINUTES=30` **[Chốt]**; chế độ demo 2 phút **[Chốt 16.5]**
- Mốc nhắc 50% và 80% **[Chốt]**
- `MIN_REVIEW_SECONDS=5` → hỏi xác nhận lại trên UI (Nên có) **[Chốt]**

## 8. Dữ liệu, DB, điểm log

- **`approvals`:** `approval_id`, `ticket_id`, `approver_id`, `backup_approver_id`, `deadline`, `action_plan_hash`, `conflict_detected`, `conflict_type`, `status` (`pending`/`approved`/`rejected`/`timeout`/`late_ignored`), `note`, `decided_by`, `decided_at`, `first_viewed_at`, `reminder_1_at`, `reminder_2_at`.
  - Các cột chưa có trong thiết kế DB (`backup_approver_id`, `conflict_type`, `first_viewed_at`, `reminder_*`) và chỉ mục `ux_approvals_one_pending` được bổ sung ở P7.
- **`side_effects`:** `approval_create`, `notify_approver`, `notify_user` (D-18).
- **Điểm log 5 [Chốt]:** `approver_id`, `deadline`, `conflict_detected`, `action_plan_hash`.
- **Điểm log 6 [Chốt]:** `result`, `note`, `response_time` (+ `view_duration`).

## 9. Trace và giám sát

- **M9:**
  - Thời gian phản hồi trung bình.
  - Tỉ lệ E6.
  - Tỉ lệ từ chối.
  - Thời gian xem mỗi phiếu (< 5 giây → cảnh báo "duyệt theo phản xạ") **[Chốt 17.9.3]**.
  - E6 tăng bất thường theo khung giờ → "thiếu người duyệt trực".
- **Dashboard L1:** chỉ phần của mình **[Chốt 2.2]**.

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| L1 đồng ý | Thực thi sau khi B17 so hash | TC07 |
| L1 từ chối có lý do | `S_REJECTED`, thông báo lý do | TC08 |
| Từ chối không lý do | 422 | cổng 4 |
| L1 gửi yêu cầu cho chính mình | Trưởng BP duyệt | TC19 |
| Người gửi là sếp của người duyệt; hành động tác động tài khoản người duyệt | Trưởng BP duyệt | 2 ca bổ sung **[Chốt cổng 4]** |
| Quá 30 phút | E6, không có lời gọi thực thi nào | TC20 |
| Bấm duyệt sau khi hết hạn | 409, phiếu `late_ignored` | TC27 |
| Action bị sửa sau khi duyệt | B17 phát hiện hash lệch → E5 | TC26 |
| L2 gọi API duyệt | 403 | cổng 4 |
| L1-X duyệt phiếu giao cho L1-Y | 403 | TC30 (mới) |
| Hai người cùng bấm | Đúng 1 lần thực thi; người sau nhận 409 | test tranh chấp |
| Luật deny | Không bao giờ tạo phiếu | cổng 4 |
| Process chết sau khi tạo phiếu, trước checkpoint | Chạy lại B15 → `effects.once` trả `approval_id` cũ; đúng 1 phiếu, 1 thông báo | TC33 (D-18) |

## 11. Kiểm thử và tiêu chí đạt (cổng 4)

**Tự động:**

- TC07, TC08, TC19 + 2 ca xung đột, TC20 (FakeClock), TC26, TC27.
- Test tranh chấp: 2 request đồng thời → 1 lần thực thi.
- Deny không tạo phiếu; L2 → 403.
- Nhắc ở 50% / 80% (FakeClock), đúng 1 lần mỗi mốc.
- Mở trang chi tiết lần đầu ghi `first_viewed_at` **[Chốt]**.
- Resume 2 lần → vẫn 1 thông báo cho người duyệt.
- TC33: giết process ngay sau `approvals.create` → recover → đúng 1 phiếu `pending`, đúng 1 thông báo (D-18).
- Tạo phiếu `pending` thứ hai cho cùng ticket bằng SQL trực tiếp → lỗi UNIQUE.

**Thủ công (Phase 7):** duyệt, từ chối, SLA rút còn 2 phút trên giao diện **[Chốt cổng 7]**.

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** B12–B14, P1 (`interrupt`, guard, `effects.once`, khóa ticket), P6 (`can_decide_approval`), P7.
- **Phase:** 4.
- **Việc còn mở:**
  - Cách chọn L1 trực (lịch trực tĩnh trong seed hay xoay vòng) **[Đề xuất: lịch tĩnh trong seed]**.
  - Q2: L2 có được hoàn tất tay ca E6 không.
  - Q3: Action đổi sau duyệt → escalate L2 (E5); chạy lại M5 chỉ sau cờ `RERUN_M5_ON_NONSENSITIVE_CHANGE` (mặc định tắt) **[Chốt nhóm, `decisions.md` mục 2]**.

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Duyệt qua Teams/Slack/email | Thêm kênh thông báo có link tới trang duyệt (không duyệt trực tiếp trong tin nhắn) | Quyết định vẫn qua API có `can_decide_approval` và khóa hàng |
| Duyệt nhiều cấp (hai người cho hành động rất nhạy) | Thêm `required_approvals` theo luật; phiếu chỉ `approved` khi đủ | Mỗi người duyệt vẫn kiểm xung đột lợi ích; hash không đổi giữa các cấp; nới UNIQUE `pending` thành theo cấp |
| Lịch trực và xoay vòng người duyệt | Thay `pick_approver` bằng lịch trực từ DB | Luôn có `backup_approver_id` |
| SLA theo mức rủi ro | `SLA_MINUTES` theo luật hoặc theo p | Hết hạn vẫn là fail-safe |
| Scale | Hàng đợi là bảng `approvals` + index `(approver_id, status, deadline)`; worker `SKIP LOCKED` cho nhiều worker | Đúng 1 lần thực thi khi tranh chấp |
| Tách thành module "Approval" | `approval/` + API + worker nhắc; phụ thuộc `hash_action`, `deliver_event` | Hợp đồng `ApprovalView` = đúng object đã băm |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| E6 tăng | `approvals.reminder_*`, `first_viewed_at`; theo khung giờ | Không có L1 trực; thông báo không tới; SLA demo quá ngắn |
| Thực thi 2 lần | Dòng `approvals` + `transaction_log` | Thiếu `FOR UPDATE`; `deliver_event` không qua khóa ticket |
| Hai phiếu `pending` cho một ticket | `side_effects` kind `approval_create`; chỉ mục `ux_approvals_one_pending` | Tạo phiếu không qua `effects.once`; migration thiếu chỉ mục |
| Người duyệt nhận 2 thông báo | Số lần `notify`; `side_effects` kind `notify_approver` | Gửi trong `approval_wait` thay vì B15; gửi không qua `effects.once` |
| L1 duyệt được phiếu người khác | Test IDOR | `can_decide_approval` không kiểm `approver_id` |
| Duyệt cho có (< 5 giây) | `first_viewed_at` so với `decided_at` | Escalation rate cao → xem lại ngưỡng M5 |
| API duyệt chờ lâu rồi lỗi | Log `lock_timeout` | Ticket đang giữ khóa lâu (một lượt treo); xem P1 mục 7 |

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.2 | Bản vá: tạo phiếu + thông báo qua `effects.once`, UNIQUE một phiếu `pending` (D-18); khóa ticket cấp session (D-19); thêm TC33 |
| 25/09/2026 | 1.3 | Lý do từ chối của ticket con đi qua tin tổng hợp của cha; chờ duyệt không phải điểm dừng (D-31) |
