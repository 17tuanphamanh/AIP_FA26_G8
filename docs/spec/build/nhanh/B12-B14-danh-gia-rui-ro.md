# B12–B14 — Đánh giá rủi ro hai lớp (M5, đóng góp chính)

> **Tầng:** T3 · **Module:** M5 · **Objective:** 2 (trọng tâm) · **Phase:** 3 (luật VPN), 5 (đủ 20 luật), 6 (lớp LLM + hiệu chỉnh), 8 (chọn ngưỡng), 10 (RQ1)
> **Trạng thái vào:** `S_ASSESSING` · **Ra:** `S_EXECUTING` (AUTO) | → B15 `S_PENDING_APPROVAL` (HITL) | `S_ESCALATED` E5 (ESCALATE_L2)
> **Code tham chiếu:** `scaffold/backend/app/risk/policy_engine.py`, `decision_math.py` **[Chốt]**

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
| Nhánh trước | B11 (`intended_action` đã dựng) |
| Nhận vào | **Chỉ** `intended_action`, `requester_context`, dữ kiện chẩn đoán (qua `Action.facts`), trích đoạn `retrieved` — **không** câu người dùng, **không** hội thoại |
| Giao cho nhánh sau | `risk` (`RiskDecision`), một trong ba đích: `S_EXECUTING`/B17 (AUTO), B15 (HITL), `S_ESCALATED` E5 (ESCALATE_L2) |
| Ai dùng đầu ra | B15 (hiển thị luật khớp hoặc p cho người duyệt), B17 (kiểm lại luật), B20/L2 (lý do escalate), M8 (ablation theo `decided_by`), M9 (dashboard) |

**Chuyển trạng thái của nhánh [Chốt 2.1, 2.2]:**

| Từ | Sự kiện | Sang |
|---|---|---|
| `S_ASSESSING` | Rủi ro thấp (allow hoặc p < ngưỡng thấp) | `S_EXECUTING` |
| `S_ASSESSING` | Rủi ro trung bình (approval_required hoặc vùng giữa) | `S_PENDING_APPROVAL` (qua B15) |
| `S_ASSESSING` | Rủi ro cao (deny, hoặc p > ngưỡng cao) | `S_ESCALATED` → E5 |
| **Cấm** | `S_ASSESSING → S_EXECUTING` khi khớp deny hoặc approval_required | — |

### 0.3. Đặc tả gốc đã chốt

**Kiến trúc hai lớp và công thức tổng quát:**

`ActionPlan + Context → Policy Rules → allow/approval_required/deny → (không khớp) → M5 LLM tính p → p<thấp / vùng giữa / p>cao → AUTO/HITL/ESCALATE_L2`

AUTO/HITL/ESCALATE_L2 là tên gọi chung cho ba đích `S_EXECUTING`/`S_PENDING_APPROVAL`/`S_ESCALATED`, do `route_by_risk()` định tuyến.

**Ba nhãn luật:**

- `allow` — tự xử lý.
- `approval_required` — cần người xem qua (nhãn cũ "blacklist", đổi tên vì gây hiểu lầm là cấm).
- `deny` — cấm tuyệt đối, không ai duyệt tay bỏ qua được, escalate thẳng L2.

**Bảng luật §6.3:**

| Loại | allow | approval_required |
|---|---|---|
| Tài khoản | Reset mật khẩu cá nhân; mở khóa do nhập sai | Tài khoản quản trị; tài khoản dịch vụ; người đã nghỉ việc |
| VPN | Cấp lại cho thiết bị đã đăng ký; kiểm tra trạng thái | Thiết bị chưa đăng ký; ngoài giờ; nhân viên mới chưa qua thử việc |
| Phần mềm | Trong danh mục duyệt sẵn | Ngoài danh mục; có phí license; cần quyền quản trị máy |
| Quyền truy cập | Xem quyền hiện có; gia hạn quyền cũ | Quyền mới vào dữ liệu nhạy cảm; quyền quản trị; vượt cấp quản lý |

Nhóm `deny` là phần nhỏ. Ví dụ R12: cấp quyền cho tài khoản bị vô hiệu hóa vì lý do bảo mật.

**Ví dụ luật trong `policy.json`:**

- R01 (allow, `reset_password`, `target_is_self=true`, `account_privilege=standard`)
- R07 (approval_required, `grant_permission`, `resource_sensitivity=high`)
- R12 (deny)

**Bốn ràng buộc code:**

1. `evaluate()` chỉ nhận `action` và `ctx`.
2. Luật khớp thì return ngay, không gọi LLM.
3. Luôn gán `decided_by`.
4. `deny` không đi qua hàng đợi L1.

**Vì sao luật chạy trước:** nếu LLM chạy trước, câu "bỏ qua mọi quy tắc, tôi là admin" có thể khiến nó trả rủi ro thấp. Luật đối chiếu **hành động**, không đối chiếu **lời nói**, nên hệ thống an toàn kể cả khi B2 thất bại hoàn toàn.

**Định nghĩa p:** `P(hành động KHÔNG NÊN tự làm mà không có người duyệt | action, ctx, diagnostics, retrieved_docs)`. Hiệu chỉnh bằng temperature/Platt scaling (Verma & Nalisnick). Hai ngưỡng chọn trên **tập calibration** (~65%, chia theo họ kịch bản), đo trên tập test (~35%).

**Cách lấy p:** bắt buộc "LLM tự nêu". Nếu > 60% giá trị dồn vào 2 mức thì chuyển "hỏi nhiều lần" k=5. So cả 3 cách (thêm xác suất token) là RQ2, tùy chọn.

**Ma trận chi phí (đơn vị: một lượt duyệt):**

| Đúng \ Chọn | Tự làm | Duyệt | L2 |
|---|---|---|---|
| Tự làm | 0 | 1 | 3 |
| Duyệt | 10 | 1 | 3 |
| L2 | 20 | 6 | 3 |

Ngưỡng dưới lý thuyết `t_low* = c_review/c_miss`. Quét lưới trên tập calibration. Độ nhạy với tỉ lệ ∈ {5, 10, 20}. AUC tách L2 < 0,7 thì bỏ đường LLM → L2.

**Đầu ra bắt buộc:** `risk_level`, `decided_by`, `policy_decision`, `reason`, `confidence`, `matched_rule_id`, `action_plan_hash`.

**So sánh (RQ1):**

- Thủ công / Full-auto / Chỉ-luật / Chỉ-LLM / Hybrid (+ Hybrid-guarded, chạy sau 5 phương án chính — Q8).
- Ablation: bỏ lớp luật, bỏ lớp LLM.
- Chỉ số: FNR (quan trọng nhất, kèm cận trên Clopper–Pearson), FPR, ECE, Brier, chi phí kỳ vọng mỗi ticket.

**Cỡ mẫu:** calibration ≥ 50 ca đi xuống LLM và ≥ 30 ca L2; test ≥ 60 ca "cần người".

### 0.4. Kịch bản kiểm thử liên quan

| Mã | Kịch bản | Mong đợi |
|---|---|---|
| TC01–TC03 | Happy path | Luật allow → tự động |
| TC07 | Reset tài khoản quản trị | approval_required → L1 đồng ý |
| TC08 | Cấp quyền thư mục tài chính | approval_required → L1 từ chối |
| TC09, TC10 | VPN ngoài giờ thiết bị lạ; phần mềm ngoài danh mục có phí | Biên — luật `approval_required` R17/R18, R13/R14 (Q1) |
| TC37 | Ca không luật nào khớp (ví dụ đặt lại mật khẩu tài khoản thường của đồng nghiệp) | LLM quyết định theo ngưỡng |
| Cổng 5 | 20 luật | Mỗi luật có ca khớp và ca suýt khớp |
| Cổng 6 | Prompt LLM rủi ro | Không chứa câu người dùng; mọi ca có `decided_by` |

### 0.5. Bất biến riêng của nhánh và mã quyết định

- M5 không đọc câu người dùng (chữ ký hàm + import-linter + whitelist biến prompt).
- Chặt nhất thắng; thiếu dữ kiện → không thỏa.
- Chiến lược so sánh chỉ chạy khi `EVAL_MODE=true`.
- Người xây M5 không tự chạy thực nghiệm.
- **Việc còn mở với GVHD:** Q1, Q8, Q9.
- **Đề xuất trong file:** LLM lỗi → E5; DSL điều kiện.

---

## 1. Mục đích và vì sao tồn tại

Trả lời câu hỏi trung tâm của đồ án: **khi nào agent tự làm, khi nào cần người duyệt, khi nào chuyển L2**, sao cho vừa an toàn vừa không escalate thừa **[Chốt]**. Mười một sản phẩm thương mại đều có HITL nhưng không công bố logic này; đồ án làm nó minh bạch, cấu hình được và đo được.

Định nghĩa `p` **[Chốt]**:

```
p = P( hành động này KHÔNG NÊN được agent tự thực hiện mà không có người duyệt
       | intended_action, requester_context, diagnostics, retrieved_docs )
```

## 2. Sơ đồ cấu tạo

```
S_ASSESSING
 input DUY NHẤT: intended_action (Action, đã băm) + ctx = build_ctx(state)
                 ctx = {requester_context, diagnostics_facts, time, target_is_other}
                 KHÔNG có redacted_request / conversation  (import-linter + whitelist gateway)
 ▼
┌──────────────── LỚP 1 — policy_engine.evaluate(action, ctx) ────────────────┐
│ nạp policy_versions(is_current) vào bộ nhớ ; 20 luật R01…R20                  │
│ mọi luật khớp → chọn chặt nhất: deny > approval_required > allow              │
│ điều kiện thiếu dữ kiện → KHÔNG thỏa                                          │
└───────┬────────────────────┬──────────────────────┬─────────────────┬────────┘
        allow        approval_required             deny           không khớp
        │                    │                      │                 │
        ▼                    ▼                      ▼                 ▼
    AUTO → B17          HITL → B15             E5 → B20       ┌── LỚP 2 ─────────────────────────┐
  (không gọi LLM)     (không gọi LLM)        (không vào       │ estimator: LLM strong             │
                                              hàng đợi duyệt)  │  b14_risk_estimate → raw_prob     │
                                                               │  (tự nêu; dự phòng k=5 lần hỏi)   │
                                                               │ calibrator.transform → p          │
                                                               │ p < t_low  → AUTO   → B17         │
                                                               │ t_low..t_high → HITL → B15        │
                                                               │ p > t_high → E5     → B20         │
                                                               └───────────────────────────────────┘
 ghi điểm log 4 + lineage (policy_version, prompt, model, calibrator, commit)
```

## 3. Công nghệ tại nhánh

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Luật | `config/policy.json` → `policy_versions` → engine thuần Python | Cấu hình không cần build lại **[Chốt]**; hiện thực Policy Cards |
| Điều kiện luật | DSL JSON nhỏ (mục 4.2) | Đọc được bởi Trưởng BP; kiểm được bằng schema |
| Ước lượng | LLM gateway, vai trò **strong**, prompt `b14_risk_estimate`, **không cache** khi vận hành | **[Chốt 17.5]** |
| Hiệu chỉnh | scikit-learn `LogisticRegression` trên logit(raw_prob) (Platt) hoặc temperature scaling tự viết (1 tham số, `scipy.optimize`) | **[Chốt]**; LLM thường tự tin quá mức |
| Toán quyết định | `decision_math.py` (ngưỡng từ chi phí, quét lưới, cận FNR Clopper–Pearson, ECE, Brier) | **[Chốt 8 test]** |
| Lưu calibrator | Tham số (a, b) hoặc T trong file JSON có version; `lineage.calibrator_version` | Tái lập |

## 4. Hợp đồng

### 4.1. Chữ ký bắt buộc [Chốt]

```python
def evaluate(action: Action, ctx: RiskContext) -> RuleVerdict: ...     # KHÔNG có raw_request
```

```python
class RiskContext(BaseModel, frozen=True):
    requester: RequesterContext
    facts: dict[str, str | int | bool]           # từ diagnostics (qua Action.facts)
    now: datetime; within_business_hours: bool
    target_is_other: bool

class RuleVerdict(BaseModel):
    matched: bool; decision: Literal["allow","approval_required","deny"] | None
    rule_id: str | None; all_matched: list[str]; description: str | None

class RiskDecision(BaseModel):
    decided_by: Literal["rule", "llm"]
    policy_decision: Literal["allow","approval_required","deny"] | None
    matched_rule_id: str | None
    raw_prob: float | None; calibrated_prob: float | None; p_method: Literal["self_report","sampling_k5"] | None
    risk_level: Literal["low","medium","high"]
    route: Literal["AUTO","HITL","ESCALATE_L2"]
    reason: str                                   # đọc được bởi người [Chốt nguyên tắc 2]
    thresholds: tuple[float, float] | None
```

### 4.2. Định dạng luật (DSL) [Chốt khung R01/R07/R12, Đề xuất cú pháp điều kiện]

```json
{"id": "R07", "type": "approval_required", "intent": "access", "action": "grant_permission",
 "conditions": {"all": [
    {"fact": "resource_sensitivity", "op": "eq", "value": "high"}
 ]},
 "description": "Cấp quyền vào dữ liệu nhạy cảm"}
```

- **Toán tử:** `eq`, `ne`, `in`, `not_in`, `lt`, `lte`, `gt`, `gte`, `is_true`, `is_false`; nhóm `all` / `any`.
- **Nguồn `fact`:** `action.*`, `action.facts.*`, `requester.*`, `time.*`.
- **Thiếu fact → điều kiện = False** **[Chốt]**. Vì vậy luật `allow` không bao giờ khớp nhờ thiếu dữ liệu.

## 5. Luồng xử lý chi tiết

```python
async def b12_assess(state):
    action, ctx = state["intended_action"], build_ctx(state)          # build_ctx KHÔNG đọc request
    strategy = eval_strategy_or_default()                             # hybrid khi vận hành [Chốt]
    v = None

    if strategy in ("rule_only", "hybrid", "hybrid_guarded"):
        v = policy_engine.evaluate(action, ctx)
        if v.matched and not (strategy == "hybrid_guarded" and v.decision == "allow"):
            return finish(state, RiskDecision(decided_by="rule", policy_decision=v.decision,
                          matched_rule_id=v.rule_id, route=ROUTE_OF[v.decision],
                          risk_level=LEVEL_OF[v.decision], reason=v.description))  # KHÔNG gọi LLM
        if strategy == "rule_only" and not v.matched:
            return finish(state, RiskDecision(decided_by="rule", route="HITL", risk_level="medium",
                          reason="Không luật nào khớp → chờ duyệt (chỉ-luật)"))     # [Chốt mục 10]

    try:                                                               # LỚP 2 (B14)
        raw, method = await estimator.estimate(action, ctx, state["retrieved"])
    except (LLMUnavailable, LLMSchemaError):
        return finish(state, RiskDecision(decided_by="llm", route="ESCALATE_L2", risk_level="high",
                      reason="Không ước lượng được rủi ro → không tự làm"))         # [Đề xuất]
    p = calibrator.transform(raw)
    t_low, t_high = policy.THRESHOLD_LOW, policy.THRESHOLD_HIGH
    route = "AUTO" if p < t_low else "ESCALATE_L2" if p > t_high else "HITL"
    # hybrid_guarded khi luật = allow: sàn là AUTO, LLM chỉ có thể NÂNG lên HITL/ESCALATE_L2,
    # nên route = max(AUTO, route_llm) = route_llm; luật approval_required/deny đã trả về ở trên [Chốt 7.4]
    return finish(state, RiskDecision(decided_by="llm", raw_prob=raw, calibrated_prob=p, p_method=method,
                  route=route, risk_level=LEVEL_OF_ROUTE[route], thresholds=(t_low, t_high),
                  reason=f"LLM đánh giá xác suất cần người duyệt: {p:.2f}"))

def finish(state, d):
    audit_point_4(state, d); lineage.record_m5(state, d)              # điểm log 4 [Chốt]
    if d.route == "AUTO":        return goto(state, S_EXECUTING, next_node="b17_execute", step="B13/B14", risk=d, ...)
    if d.route == "HITL":        return goto(state, S_ASSESSING, next_node="b15_prepare_approval", step="B13/B14", risk=d, ...)
    return goto(state, S_ESCALATED, next_node="b20_audit", step="B13/B14", risk=d, exit_code="E5", ...)
```

**Chiến lược `full_auto`** (bỏ qua M5, route = AUTO, không có `decided_by` **[Chốt 9.2]**) **và `llm_only`** (bỏ lớp 1, mọi ca xuống lớp 2) chỉ chạy khi `EVAL_MODE=true`. Chạy ở chế độ vận hành → lỗi ngay **[Chốt cổng 6]**.

### 5.1. Estimator (lấy raw_prob)

- **Bắt buộc — "tự nêu" [Chốt]:**
  - Prompt `b14_risk_estimate`, schema `{prob_needs_human: float, factors: [..], rationale}`, temperature 0.
  - Input gồm `Action` (JSON), `RiskContext` (JSON), tối đa 3 trích đoạn tài liệu liên quan tới quy định. **Không** có câu người dùng.
- **Dự phòng — "hỏi nhiều lần" k = 5 [Chốt]:**
  - Probe 30 kịch bản đi xuống LLM (Phase 6). Nếu > 60% giá trị p dồn vào 2 mức, bật chế độ này.
  - Cách làm: 5 lời gọi song song, temperature 0,7, câu hỏi nhị phân "cần người duyệt?"; p = tỉ lệ "có".
  - Ghi cách đã chọn vào `policy.json` (`p_method`).
- **Phase 11 (RQ2):** thêm cách "xác suất token" (cần logprobs — vLLM có), so cả 3 cách.

### 5.2. Hiệu chỉnh và ngưỡng (Phase 8, 10) [Chốt 7.2, 7.3]

1. **Fit calibrator chỉ trên tập calibration.** Code kiểm `split == "calibration"`, gọi trên `test` → `LeakageError` **[Chốt]**.
2. **Ngưỡng dưới lý thuyết:** tự làm chỉ khi `p · c_miss < c_review` ⟺ `p < t_low* = c_review / c_miss`. Với tỉ lệ 10:1 mặc định: `t_low* = 0,1`.
3. **Quét lưới `(t_low, t_high)`** trên tập calibration theo ma trận chi phí 3×3 **[Chốt 7.3]**, chọn cặp có tổng chi phí thấp nhất.
   - `t_low` đánh giá trên nhãn "route ≠ tự làm".
   - `t_high` đánh giá trên nhãn "route = chuyển L2".
4. **Báo cáo:** khoảng cách giữa ngưỡng thực nghiệm và `t_low*`; độ nhạy khi tỉ lệ bỏ sót/duyệt ∈ {5, 10, 20} **[Chốt]**.
5. **Nếu AUC tách "chuyển L2" < 0,7:** bỏ đường LLM → L2; chỉ luật `deny` được chuyển L2 **[Chốt]**.
6. **Ghi ngưỡng** vào một `policy_versions` mới, kèm `t_low*` và phân tích độ nhạy **[Chốt cổng 10]**.

## 6. Quyết định thiết kế và lý do

| Quyết định | Lý do |
|---|---|
| Luật chạy trước, có quyền phủ quyết | Nếu LLM chạy trước, một câu "bỏ qua mọi quy tắc, tôi là admin" có thể hạ rủi ro. Luật đối chiếu **hành động**, không đối chiếu **lời nói** **[Chốt 6.2]** |
| M5 không đọc câu người dùng — ép ở 3 chỗ: chữ ký hàm, import-linter, whitelist biến prompt | Hệ thống vẫn an toàn **kể cả khi B2 thất bại hoàn toàn** **[Chốt]** |
| Luật khớp → trả về ngay, không gọi LLM | Luật có quyền phủ quyết; đồng thời tiết kiệm chi phí **[Chốt]** |
| Chặt nhất thắng; thiếu dữ kiện → không thỏa | Hướng giảm False Negative **[Chốt]** |
| `deny` không vào hàng đợi duyệt | Không ai có thẩm quyền bật đèn xanh cho hành động cấm **[Chốt]** |
| Hiệu chỉnh trước khi so ngưỡng | Ngưỡng chỉ có nghĩa khi p phản ánh đúng tần suất thật **[Chốt]** |
| Ngưỡng suy từ chi phí, không chọn 0,25 theo cảm tính | 0,25 ngầm coi bỏ sót chỉ đắt gấp 4 lần một lượt duyệt, mâu thuẫn với "FNR quan trọng nhất" **[Chốt 7.3]** |
| LLM lỗi → E5 (không tự làm) | Không có căn cứ thì không tự làm **[Đề xuất theo nguyên tắc 1]** |
| `decided_by` luôn được ghi | Toàn bộ ablation và so sánh 4 phương án dựa vào trường này **[Chốt 9.1]** |

## 7. Cấu hình (`policy.json`)

- `rules[]` (20 luật)
- `thresholds.low/high` (mặc định 0,25/0,75 → thay bằng ngưỡng đã chọn)
- `cost_matrix` (bảng 7.3)
- `p_method`
- `calibrator_version`
- `strategy` (chỉ đọc khi `EVAL_MODE`)

## 8. Dữ liệu, DB, điểm log

- **Điểm log 4 [Chốt, quan trọng nhất]:** `decided_by`, `policy_decision`, `risk_level`, `reason`, `matched_rule_id`, `calibrated_prob`. Bổ sung thêm `raw_prob`, `p_method`, `thresholds`, `all_matched`.
- **`lineage`:** `policy_version_id`, `prompt_id@version`, model, `calibrator_version`, `kb_version`, commit **[Chốt 17.1]**.
- **Dữ liệu thực nghiệm:** nhãn 3 mức (`expected_route`); tập calibration ≥ 50 ca đi xuống LLM và ≥ 30 ca "chuyển L2"; tập test ≥ 60 ca "cần người" **[Chốt 8.2]**.
- **Họ kịch bản đi xuống LLM** (vì với bảng luật 6.3, 28 TC gốc gần như không có ca nào chắc chắn đi xuống LLM: TC09/TC10 đi theo luật cần duyệt (Q1), còn TC21 là ca lỗi thực thi ở B17) **[Chốt 8.2]**, mỗi họ 6–8 biến thể:
  - cấp quyền mới vào thư mục độ nhạy thấp/trung bình cùng phòng ban
  - đặt lại mật khẩu cho tài khoản thường của đồng nghiệp
  - mở khóa tài khoản bị khóa không phải do nhập sai
  - cấp quyền 180 ngày

## 9. Trace và giám sát

- **Span:** `node:b12_assess`, `risk:rules` (< 5 ms), `llm:b14_risk_estimate` (× k).
- **M9:**
  - Phân bố `decided_by`.
  - Top luật khớp.
  - Phân bố p.
  - Escalation rate trên phân bố vận hành giả định, cảnh báo > 40% **[Chốt]**.
  - Số lần ghi đè.

## 10. Lỗi và ca biên

| Tình huống | Kết quả | TC |
|---|---|---|
| Reset mật khẩu cá nhân, tài khoản thường | R01 allow → AUTO | TC01 |
| Reset tài khoản quản trị | approval_required → HITL | TC07 |
| Cấp quyền thư mục tài chính | R07 approval_required → HITL (L1 từ chối) | TC08 |
| Cấp quyền cho tài khoản bị vô hiệu vì bảo mật | R12 deny → E5, không có phiếu duyệt | — |
| VPN thiết bị lạ ngoài giờ | R17/R18 approval_required → HITL (Q1 đã chốt theo luật) | TC09 |
| Không luật nào khớp | LLM → theo ngưỡng | TC37 + các họ bổ sung |
| Khớp cả allow và approval_required | approval_required thắng | — |
| Thiếu fact `device_registered` | Luật allow VPN không khớp → xuống luật khác hoặc LLM | — |
| LLM strong lỗi | E5 | — |
| Chạy `llm_only` khi `EVAL_MODE=false` | Lỗi cấu hình ngay khi khởi động | — |

## 11. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Unit | 20 luật × (ca khớp, ca suýt khớp) | 40 test xanh **[Chốt cổng 5]** |
| Unit | Chặt nhất thắng; thiếu fact → không thỏa | Xanh |
| Unit | Chữ ký `evaluate` | Chỉ `action`, `ctx` **[Chốt]** |
| Unit | 8 test `decision_math` (ngưỡng từ chi phí, cận FNR, ECE, Brier) | Xanh **[Chốt]** |
| Unit | Fit calibrator trên split `test` | `LeakageError` |
| Integration | Luật khớp | ScriptedLLM ghi nhận **0** lời gọi `b14_*` |
| Integration | Chụp prompt thật gửi `b14_risk_estimate` | Không chứa chuỗi của câu người dùng (kiểm bằng chuỗi canary chèn vào câu) **[Chốt cổng 6]** |
| Integration | Mọi ticket qua M5 | Có `decided_by`; ca LLM có `raw_prob` + `p_method` |
| Probe (LLM thật, Phase 6) | 30 kịch bản đi xuống LLM | Vẽ phân phối p; áp quy tắc 60%/2 mức |
| Thủ công | Người không xây M5 đọc 10 lý do ngẫu nhiên | Đọc hiểu được **[Chốt]** |
| Thực nghiệm (Phase 10) | Ma trận RQ1 | Bảng so sánh, ablation, biểu đồ hiệu chỉnh, chi phí theo ngưỡng, FNR + cận trên 95%, 10 ca sai tiêu biểu **[Chốt]** |

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** B11 (`Action` + `facts`), B1 (`requester_context`), P2, dữ liệu có nhãn.
- **Phase:** 3 (luật VPN), 5 (20 luật), 6 (lớp 2), 8 (calibrator + ngưỡng — code), 10 (chọn thật trên tập calibration).
- **Việc còn mở:**
  - Đã chốt (không còn mở): Q1 (theo luật), Q9 (10:1, độ nhạy 5/10/20) — `decisions.md` mục 2.
  - Q8 (`hybrid_guarded`): code Phase 6, chạy Phase 10 **[Chốt nhóm, `decisions.md` mục 2]**.
  - Cú pháp DSL điều kiện (khớp với việc còn mở số 4 của thiết kế DB).
  - Người xây M5 không tự chạy thực nghiệm **[Chốt]**.

---

## 13. Mở rộng, thay thế và scale độc lập

| Hướng | Làm thế nào | Không được phá |
|---|---|---|
| Thêm hoặc sửa luật | Trưởng BP sửa qua UI → validate schema → "mô phỏng tác động" trên N ticket gần nhất → lưu `policy_versions` mới **[Chốt 16.3]** | Mỗi luật mới có test khớp/suýt khớp; không luật `allow` nào khớp nhờ thiếu fact |
| Đổi cách lấy p (RQ2) | Thêm `estimator` mới (`sampling_k5`, `token_logprob`) sau interface `RiskEstimator`; fit lại calibrator trên tập calibration | Không đổi ngưỡng mà không fit lại; ghi `p_method` vào lineage |
| Đổi LLM rủi ro (API → local) | Đổi `roles.strong` hoặc tạo vai trò riêng `risk` trong `llm.yaml` | Phải fit lại calibrator và chọn lại ngưỡng |
| `hybrid_guarded` (Q8) | Đã có nhánh chiến lược; bật bằng `strategy` | LLM chỉ được nâng mức, không bao giờ hạ |
| Dùng lại cho domain khác (HR, tài chính) | Engine luật + DSL + estimator + calibrator là độc lập domain; chỉ thay `policy.json`, `Action` schema, prompt | Giữ chữ ký `evaluate(action, ctx)` |
| Scale | Lớp luật < 5 ms trong bộ nhớ; chi phí nằm ở LLM (khoảng 25% ticket). Hỏi nhiều lần chạy song song | Không cache B14 khi vận hành |

## 14. Sổ tay sửa lỗi

| Triệu chứng | Xem ở đâu | Nguyên nhân thường gặp |
|---|---|---|
| FNR cao (ca cần người bị AUTO) | 10 ca sai tiêu biểu kèm audit điểm 4 | Luật `allow` quá rộng; thiếu fact nhưng điều kiện được code sai thành "thỏa"; `t_low` quá cao |
| Escalation rate > 40% | Phân bố `decided_by` và `policy_decision` | Luật `approval_required` quá rộng; calibrator lệch; `t_high` quá thấp |
| p dồn vào 2 mức | Probe phân phối p | LLM tự nêu thô → bật `sampling_k5` |
| Kết quả thực nghiệm không tái lập | `lineage` (policy, prompt, model, calibrator, commit), `LLM_CACHE_MODE` | Chạy không cache; policy version khác; calibrator fit lại |
| Prompt B14 lọt câu người dùng | Test canary chụp prompt | `build_ctx` hoặc biến prompt thêm `redacted_request` → phải bị whitelist chặn |

## 15. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file; sửa công thức `t_low*` |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0, đặc tả gốc, TC, mục mở rộng và sổ tay sửa lỗi |
