# B17–B18 — Thực thi hành động (điểm ghi duy nhất) và thông báo kết quả

> **Tầng:** T4 · **Module:** Executor · **Objective:** 1 (thực thi) + 2 (kiểm soát trước khi ghi) · **Phase:** 3 (VPN), 5 (đủ executor + hoàn tác)
> **Trạng thái vào:** `S_EXECUTING` · **Ra:** `S_CONFIRMING` | `S_ESCALATED` (E7 thực thi lỗi; E5 hash lệch hoặc kiểm lại thất bại)
> **Bản vá v1.2:** D-15 (sửa: kiểm lại cả người gửi lẫn người hưởng lợi), D-18 (thông báo + đặt hạn idempotent)

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
| Nhánh trước | B13 (luật allow), B14 (p < ngưỡng thấp), hoặc B16 (đã duyệt) |
| Nhận vào | `intended_action`, `action_plan_hash` (nếu đã qua duyệt), `approval_id`, `risk`, `requester_context` |
| Giao cho nhánh sau | Thành công: kết quả đã gửi người dùng (B18), `S_CONFIRMING`, `next=confirm_wait` (`resolution_path` auto/approved do B20 suy ra từ `approval_result`). Lỗi: `S_ESCALATED` E7/E5 kèm `handoff_note` |
| Ai dùng đầu ra | B19, B20/L2 (ghi chú bàn giao), M9 (tỉ lệ thành công, hoàn tác, hash lệch) |

**Chuyển trạng thái của nhánh [Chốt 2.1]:**

| Từ | Sự kiện | Sang |
|---|---|---|
| `S_EXECUTING` | Thực thi thành công | `S_CONFIRMING` |
| `S_EXECUTING` | Thực thi thất bại, đã hoàn tác (nếu được) | `S_ESCALATED` → E7 |
| `S_EXECUTING` | ActionPlan đổi so với lúc duyệt (hash lệch) | `S_ESCALATED` → E5 |

### 0.3. Đặc tả gốc đã chốt

- **Điều kiện tiên quyết:** đã được B13, B14 hoặc B16 cho phép.
- **Kiểm lại trước khi chạy:**
  1. Chính sách hiện tại còn cho phép không (deny hoặc approval_required mà chưa duyệt → E5).
  2. `action_plan_hash` còn khớp không (lệch → E5).
- **Vì sao kiểm lại quyền:** từ lúc gửi duyệt tới lúc thực thi có thể đã 30 phút. Người dùng có thể đã nghỉ việc, chính sách có thể đã đổi, thiết bị có thể đã bị thu hồi. Kiểm lại rẻ và tránh được sự cố.
- **Vì sao còn cần hash:** kiểm lại chính sách chỉ phát hiện được *chính sách* đổi, không phát hiện được *hành động* bị diễn giải lại. Ví dụ: trình lên "cài Chrome cho PC-01" nhưng lúc thực thi phạm vi đã rộng hơn.
- **Hoàn tác — 3 mức:**

  | Mức | Ví dụ | Cách xử lý |
  |---|---|---|
  | Hoàn tác hoàn toàn | Thêm vào nhóm quyền | Gỡ khỏi nhóm |
  | Hoàn tác một phần | Reset mật khẩu đã gửi email | Khóa lại, ghi rõ email đã gửi |
  | Không hoàn tác được | Cấp license có phí | Không rollback, không gọi `undo_fn`, escalate kèm trạng thái nửa chừng |

- **Sửa vòng rà soát 2:**
  - Chỉ gọi `txn.rollback()` khi `action.reversible`; ngược lại ghi `not_attempted`.
  - `TransactionLog.record()` chỉ gọi cho bước hoàn tác được.
- **Không retry lệnh ghi** **[Chốt 17.3]**: tool ghi có timeout 5 giây, 0 lần retry. Tool ghi gọi ngoài B17 → lỗi ngay.
- **Ghi chú cho L2:** với mức 2 và 3, phải nêu **đã làm đến đâu** và **phần nào cần xử lý tay**. "Thực thi thất bại" thôi thì L2 không biết bắt đầu từ đâu.
- **Adapter:** mỗi hệ thống ngoài có một interface (`IdentityProvider`, `VpnGateway`, `SoftwareCatalog`, `FileServer`) và một bản mock. Thay mock bằng hệ thống thật chỉ cần viết adapter mới.

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC02 | Cấp lại VPN cho thiết bị đã đăng ký | Luật R20 allow, gia hạn gọi đúng 1 lần, ticket đóng |
| TC21 | API lỗi khi đang thực thi | Hoàn tác rồi mới chuyển L2 (E7) |
| TC26 | ActionPlan đổi sau khi duyệt | E5, không thực thi |
| TC31 | Người gửi bị vô hiệu hóa trong lúc chờ duyệt | E5, không thực thi — **kể cả khi người gửi khác người hưởng lợi** (D-15 sửa) |
| Cổng 5 | Phần mềm có phí lỗi khi cài | Không gọi hoàn tác |
| Cổng 5 | Ghi chú bàn giao E7 | Nêu bước đã làm, đã hoàn tác tới đâu, phần L2 làm tay |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- Điểm ghi duy nhất ra hệ thống ngoài.
- Không retry ghi.
- Không thực thi khi hash lệch, khi kiểm lại ra deny, khi người gửi **hoặc** người hưởng lợi không còn hợp lệ.
- Lỗi lường trước → E7; bug → E9 (không lẫn nhau).
- Thông báo kết quả gửi đúng một lần, kể cả khi node chạy lại (D-18).
- **Mã quyết định dùng trong file:** D-03 (`svc_executor`), D-15 (kiểm lại — phạm vi sửa ở v1.2), D-18, D-31 (v1.3).

---

## 1. Mục đích và vì sao tồn tại

B17 là **nơi duy nhất trong toàn hệ thống được ghi vào hệ thống ngoài** **[Chốt]**. Mọi lớp phía trên có thể sai; B17 là chốt chặn cuối. Trước khi ghi, B17 kiểm lại bốn điều:

1. Chính sách hiện tại còn cho phép không.
2. `Action` còn đúng cái người duyệt đã thấy không (hash).
3. **Người gửi và người hưởng lợi** còn hợp lệ không.
4. Chỉ credential của `svc_executor` mới ghi được.

Khi ghi lỗi giữa chừng, B17 hoàn tác đúng mức có thể, và nói rõ cho L2 biết đã làm tới đâu.

## 2. Sơ đồ cấu tạo

```
S_EXECUTING (từ B13 allow | B14 p<t_low | B16 approved)
   ▼
[1] recheck = policy_engine.evaluate(action, build_ctx(state))   ← policy HIỆN HÀNH
      deny                                         ─────────────► E5
      approval_required và không có approval=approved ─────────► E5 [Chốt]
[2] nếu có action_plan_hash: hash_action(action) ≠ hash đã duyệt ─► E5 (ghi hash cũ + mới) [Chốt]
[3] idp.get_user cho {requester_context.user_id, action.requested_for}
      bất kỳ ai disabled/terminated, hoặc AD lỗi ──────────────► E5 (D-15, sửa v1.2)
   ▼
[4] Executor (credential svc_executor) — TransactionLog.begin(ticket_id, action)
      for step in PLAN[action.type]:                 # 1..n bước ghi
          r = registry.call(step.tool, args, caller_step="B17")   # 1 lần, timeout 5s, KHÔNG retry
          if action.reversible and step.undo: txn.record(step.name, step.undo, undo_args(r))
   ├─ OK ─► txn.commit ; điểm log 7 (success, hash_matched) ─► [B18] effects.once("notify_user")
   │                                                            effects.once("deadline_set") 48h
   │                                                            ─► S_CONFIRMING
   └─ lỗi ở bước k:
        reversible ? rollback = txn.rollback()  (ngược thứ tự, ghi undone / UNDO_FAILED)
                   : rollback = "not_attempted"
        handoff_note = đã làm bước 1..k-1, đã hoàn tác tới đâu, phần L2 phải làm tay
        điểm log 7 ─► E7 (ưu tiên Rất cao)
```

## 3. Công nghệ tại nhánh

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Kế hoạch thực thi | `executor/plans.py`: `PLAN[action_type] = [Step(tool, undo, args_fn)]` | Tách "làm gì" khỏi "làm thế nào"; test từng kế hoạch |
| Gọi ghi | Tool registry, kind=write, `allowed_steps={"B17"}`, adapter dùng token `svc_executor` | Hai lớp chặn: code + mạng (D-03) |
| Hoàn tác | `TransactionLog` **[Chốt 5.3]** + bảng `transaction_log` | Chỉ ghi `record()` khi hoàn tác được |
| Kiểm lại luật | `policy_engine.evaluate` với `policy_versions.is_current` | Policy có thể đổi trong 30 phút chờ |
| Kiểm người gửi và người hưởng lợi | `IdentityProvider.get_user` (song song cho tối đa 2 user) | D-15 (sửa v1.2) |
| Thông báo, đặt hạn | `effects.once` | D-18 |

## 4. Hợp đồng node

- **Đọc:** `intended_action`, `action_plan_hash`, `risk`, `approval_id`, `requester_context`.
- **Ghi:** `execution` (`success`, `steps_done`, `rollback_status`, `handoff_note`), `status`, `next`, `exit_code`.

```python
class ExecutionResult(BaseModel):
    success: bool
    steps_done: list[str]
    failed_step: str | None
    rollback_status: Literal["undone", "partial", "undo_failed", "not_attempted", "none_needed"]
    rollback_details: list[tuple[str, str]]          # (step, "undone" | "UNDO_FAILED: …")
    action_plan_hash_matched: bool | None
    handoff_note: str | None
```

## 5. Luồng xử lý chi tiết

```python
async def b17_execute(state):
    action, ctx = state["intended_action"], build_ctx(state)
    approved = state.get("approval_id") and (await approvals.get(state["approval_id"])).status == "approved"

    v = policy_engine.evaluate(action, ctx)                                             # [1]
    if v.decision == "deny" or (v.decision == "approval_required" and not approved):
        return esc(state, "E5", "recheck_failed", detail=v.rule_id)

    matched = None
    if state.get("action_plan_hash"):                                                   # [2]
        cur = hash_action(action); matched = (cur == state["action_plan_hash"])
        if not matched:
            return esc(state, "E5", "action_plan_changed_since_approval",
                       detail={"old": state["action_plan_hash"], "new": cur})

    people = list(dict.fromkeys([state["requester_context"].user_id, action.requested_for]))  # [3] D-15 (sửa)
    checks = await asyncio.gather(*[
        registry.call_internal("ad_get_user", {"user_id": uid}, caller_step="B17") for uid in people])
    for uid, (u, err, _) in zip(people, checks):
        if err or u.employment_status in ("disabled", "terminated"):
            return esc(state, "E5", "person_no_longer_valid",
                       detail={"user_id": uid, "role": "requester" if uid == state["requester_context"].user_id
                               else "beneficiary", "ad_error": bool(err)})

    txn = TransactionLog.begin(state["ticket_id"], action)                              # [4]
    done = []
    try:
        for step in PLAN[action.type]:
            r = await registry.call(step.tool, step.args_fn(action), caller_step="B17")
            if r.error: raise ExecutionStepError(step.name, r.error)
            done.append(step.name)
            if action.reversible and step.undo:
                txn.record(step.name, step.undo, step.undo_args(action, r))
    except ExecutionStepError as e:
        rb = await txn.rollback() if action.reversible else "not_attempted"             # [Chốt: sửa vòng 2]
        res = ExecutionResult(success=False, steps_done=done, failed_step=e.step,
                              rollback_status=summarize(rb), rollback_details=rb if isinstance(rb, list) else [],
                              action_plan_hash_matched=matched,
                              handoff_note=handoff(action, done, e.step, rb))
        audit_point_7(state, res)
        return goto(state, S_ESCALATED, next_node="b20_audit", step="B17",
                    event="exec_failed", exit_code="E7", execution=res)

    await txn.commit()
    res = ExecutionResult(success=True, steps_done=done, failed_step=None,
                          rollback_status="none_needed", rollback_details=[], action_plan_hash_matched=matched)
    audit_point_7(state, res)
    await effects.once(state, "notify_user", notify_user, state, success_message(action),
                       needs="confirm", step="B18")                    # con: child_notices (D-31)
    await effects.once(state, "deadline_set", deadlines.set, state["ticket_id"], "confirm",
                       hours=48, step="B18")
    return goto(state, S_CONFIRMING, next_node="confirm_wait", step="B18", event="executed_ok",
                execution=res)                  # resolution_path do B20 suy ra (v1.4)
```

**Vì sao `ExecutionStepError` là lỗi đã lường trước (trả E7), còn mọi exception khác thì rơi xuống E9:** một bug trong executor không được giả làm "API lỗi". Hai loại lỗi này cần hai người xử lý khác nhau (L2 cho E7, dev cho E9).

**Vì sao kiểm cả người gửi lẫn người hưởng lợi (D-15 sửa, L-07):** bản 1.0 mô tả D-15 là "kiểm lại **người gửi**", nhưng mã giả chỉ gọi `ad_get_user(action.requested_for)`, tức **người hưởng lợi**. Hai người này khác nhau khi người gửi yêu cầu thay cho người khác (`target_is_other=True`). Khi đó, nếu người gửi bị vô hiệu hóa trong 30 phút chờ duyệt, hành động vẫn được thực thi — đúng loại lỗ hổng mà D-15 được đặt ra để chặn. Kiểm cả hai (song song, cùng lắm 2 lời gọi đọc) và lỗi AD khi kiểm cũng dẫn tới E5, vì không có căn cứ thì không ghi.

**Vì sao chạy lại B17 không ghi hai lần:** B17 không nằm sau node chờ nào, nên không bị "chạy lại khi resume". Nếu process chết **giữa** các bước ghi, lần phục hồi sẽ chạy lại B17 từ đầu. Trường hợp này được chặn bởi `transaction_log`: `TransactionLog.begin` kiểm tra đã có bản ghi `begun` cho `(ticket_id, turn_id)` chưa; có rồi → không thực thi lại mà chuyển E7 với ghi chú "thực thi bị gián đoạn, cần L2 kiểm tra trạng thái thật" **[Đề xuất, gắn D-18]**. Thông báo và đặt hạn ở B18 đi qua `effects.once`.

**Ticket con của yêu cầu nhiều ý (D-31, v1.3):** hàm `notify_user` tự kiểm `state["parent_ticket_id"]`. Với ticket con, lời nhắn được ghi vào `child_notices` thay vì gửi, và `deadlines.set` không đặt hạn (hạn do ticket cha giữ). Ticket cha gom mọi lời nhắn thành **một** tin mỗi lượt người dùng **[Chốt B5]** (P1 mục 8.1–8.2). Logic của nhánh này không đổi. Tác dụng ở hệ thống ngoài (ví dụ email mật khẩu mới do mock AD gửi) vẫn xảy ra ngay ở B17; chỉ tin nhắn trong hội thoại là được gom.

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| Kiểm lại luật với policy hiện hành | Trong 30 phút chờ, policy có thể đổi hoặc thiết bị bị thu hồi. Kiểm lại rẻ và tránh được sự cố **[Chốt]** |
| So hash | Kiểm lại luật chỉ phát hiện *chính sách* đổi, không phát hiện được *hành động* bị diễn giải lại. Hash bảo đảm lượt duyệt không bị "mượn" cho hành động khác **[Chốt]** |
| Kiểm lại người gửi **và** người hưởng lợi (D-15, sửa v1.2) | Người bị nghỉ việc trong lúc chờ duyệt không được hưởng hành động, và cũng không được là người khởi xướng — đúng ô luật "người đã nghỉ việc" |
| **Không retry lệnh ghi** | Lệnh ghi không idempotent: retry "reset mật khẩu" có thể reset hai lần; retry "cấp license" có thể trừ tiền hai lần **[Chốt 17.3]** |
| Thực thi bị gián đoạn → E7, không tự thực thi lại | Không biết hệ thống ngoài đang ở trạng thái nào; để người kiểm |
| Hoàn tác chỉ khi `reversible` | Gọi `undo_fn` cho hành động không hoàn tác được thì chắc chắn thất bại và gây nhầm lẫn **[Chốt 5.3, sửa vòng 2]** |
| Ghi chú bàn giao nêu rõ từng bước | "Thực thi thất bại" không đủ để L2 biết bắt đầu từ đâu **[Chốt]** |
| Credential ghi chỉ ở executor (D-03) | Nếu code có bug, `svc_agent` vẫn không có chìa khóa để ghi |
| Thông báo + đặt hạn trước node chờ, qua `effects.once` | Tránh gửi trùng khi resume **[Chốt]** và khi phục hồi sau sự cố (D-18) |

## 7. Cấu hình

- Timeout ghi 5 giây, retries = 0 **[Chốt]**
- `PLAN` và `undo` theo `action_metadata.yaml`
- `CONFIRM_TIMEOUT=48h` **[Chốt]**

## 8. Dữ liệu, DB, điểm log

- **`transaction_log`:** mỗi bước `undone` / `undo_failed` **[Chốt DB]**. Không có dòng nào khi `reversible=False`. Thêm bản ghi `begun` mỗi lượt thực thi để phát hiện thực thi bị gián đoạn.
- **Điểm log 7 [Chốt]:** `success`, `rollback_status` (gồm `not_attempted`), `action_plan_hash_matched`.
- **`escalations`** (E7): ưu tiên **Rất cao** (có thể dở dang) **[Chốt]**; `handoff_note` 4 phần. E5 do kiểm lại người: `reason_detail=person_no_longer_valid`.
- **`side_effects`:** `notify_user`, `deadline_set` (D-18).

## 9. Trace và giám sát

- **Span:** `node:b17_execute`, `tool:<write>` từng bước, `tool:ad_get_user` (tối đa 2).
- **M9:**
  - Tỉ lệ thực thi thành công.
  - Tỉ lệ phải hoàn tác.
  - Tỉ lệ bị chặn do hash lệch **[Chốt chỉ số B17]**.
  - Số ca E5 do người gửi/người hưởng lợi không còn hợp lệ.
  - E7 → cảnh báo ngay.

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| Gia hạn VPN hợp lệ | Gọi đúng 1 lần, `S_CONFIRMING` | TC02 |
| API lỗi giữa chừng, hành động hoàn tác được | Hoàn tác → E7 | TC21 |
| Cài phần mềm có phí lỗi | `not_attempted`, không gọi undo **[Chốt cổng 5]** | — |
| Reset mật khẩu lỗi sau khi đã gửi email | Hoàn tác một phần (khóa lại), ghi chú "email đã gửi" | — |
| Action đổi sau khi duyệt | E5, 0 lời gọi ghi | TC26 |
| Policy đổi thành deny trong lúc chờ | E5 | — |
| Người hưởng lợi bị terminated trong lúc chờ | E5 | TC31 |
| **Người gửi bị disabled trong lúc chờ, người hưởng lợi vẫn active** | **E5 (bản 1.0 bỏ lọt ca này)** | TC31 biến thể (D-15 sửa) |
| AD lỗi khi kiểm lại người | E5, không ghi | — |
| Process chết giữa các bước ghi | Phục hồi thấy `transaction_log` đã `begun` → E7 "thực thi bị gián đoạn", không ghi lại | — |
| Mock ghi nhận token `svc_agent` | 403 (không bao giờ xảy ra nếu code đúng; test mạng) | — |
| Bug trong `PLAN` (KeyError) | E9, không bị gắn nhầm E7 | TC29 biến thể |

## 11. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Unit | Mỗi `PLAN` | Đúng thứ tự tool; undo đúng với các bước hoàn tác được |
| Unit | `TransactionLog` | `reversible=False` → `steps` rỗng, `rollback()` không gọi gì |
| Integration (mock faults) | TC21, TC26, phần mềm có phí | Như mục 10 |
| Integration | Đếm lời gọi ghi | TC02 = 1; mọi ca E5 = 0 |
| Integration | Người gửi disabled, người hưởng lợi active (`target_is_other=True`) | E5, 0 lời gọi ghi (D-15 sửa) |
| Integration | Đếm thông báo khi resume `confirm_wait` | 1 |
| Integration | Giết process sau `notify_user`, trước checkpoint → recover | 1 thông báo, 0 lời gọi ghi thêm (D-18) |
| Bảo mật | `svc_agent` → endpoint ghi | 403 |
| Cổng 5 | Ghi chú bàn giao E7 | Nêu rõ bước đã làm, đã hoàn tác tới đâu, phần L2 làm tay **[Chốt]** |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** B12–B16, P1 (`effects.once`), P5 (tool ghi, token), P6, P7 (`transaction_log`, `side_effects`).
- **Phase:** 3 (gia hạn VPN), 5 (mọi executor + hoàn tác).
- **Việc còn mở:** danh sách tool ghi và `PLAN` chốt cùng 20 luật (T22a, T24); bản ghi `begun` trong `transaction_log` cần thêm vào thiết kế DB khi chốt.

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Nối hệ thống thật (AD, VPN, Intune/SCCM, file server) | Adapter ghi mới cho port tương ứng, dùng credential riêng của executor (service principal có quyền tối thiểu) | Không retry ghi; `reversibility` phải đúng với API thật |
| Idempotency phía hệ thống ngoài | Gửi `Idempotency-Key = sha256(ticket_id, step)` nếu API hỗ trợ; khi đó có thể cho phép retry an toàn và cho phục hồi thực thi bị gián đoạn | Chỉ bật retry cho tool nào được xác nhận idempotent |
| Hành động mới | Thêm `PLAN[type]` + undo + metadata + luật M5 + test hoàn tác | Thiếu `PLAN` phải là lỗi cấu hình khi khởi động, không phải E9 lúc chạy |
| Scale | Executor chạy trong backend; tách thành worker riêng có hàng đợi nếu hành động chạy lâu (cài phần mềm) | Mỗi ticket vẫn chỉ một lần thực thi (khóa ticket) |
| Tách thành module "Executor" | `executor/` + tool ghi + `transaction_log`; nhận `(Action, approval_proof)` | Kiểm lại luật + hash + người ở phía executor, không tin người gọi |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| E5 "hash lệch" dù không ai sửa | So `Action` lúc B15 và B17 | Trường không tất định trong `Action`; hash không sắp khóa |
| E5 "recheck_failed" hàng loạt | `policy_versions` mới nhất | Policy mới vừa lưu siết luật; hoặc luật đọc fact thiếu |
| E5 "person_no_longer_valid" hàng loạt | Span `tool:ad_get_user`; `users.last_synced_at` | AD mock lỗi; đồng bộ AD sai trạng thái |
| E7 không hoàn tác | `transaction_log` rỗng | `reversible=False` (đúng thiết kế) hoặc `record()` không được gọi |
| E9 thay vì E7 | Traceback trong span | Exception không bọc thành `ExecutionStepError` (bug trong `PLAN`) |
| Gọi ghi 2 lần | Log mock + `transaction_log` | Retry ghi bị bật nhầm; phục hồi chạy lại B17 mà không kiểm bản ghi `begun` |

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
| 25/09/2026 | 1.2 | Bản vá: D-15 kiểm cả người gửi lẫn người hưởng lợi (sửa L-07); thông báo + đặt hạn qua `effects.once` (D-18); phát hiện thực thi bị gián đoạn qua `transaction_log` |
| 25/09/2026 | 1.3 | Thông báo kết quả của ticket con để lại notice `needs=confirm` cho cha gom (D-31) |
| 26/09/2026 | 1.4 | Bỏ việc B18 tự đặt `resolution_path` (bị LangGraph bỏ im lặng); B20 suy ra (Phase 2b-2) |
