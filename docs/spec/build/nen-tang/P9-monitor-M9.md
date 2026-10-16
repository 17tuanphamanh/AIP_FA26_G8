# P9 — Tầng Monitor (M9, `backend/app/monitor/`)

*Thuộc bộ `build/`. Tầng thứ tư, song song Agent/Kiểm soát/B17; chỉ đọc, không quyết định. Objective 1 (lớp kỹ thuật agent: trace, LLMOps) và nền cho giám sát M5 của Objective 2. Nguồn đã chốt: `huong-dan-xay-dung-he-thong-2.md` mục 16.3–16.5, 17.1, 17.5, 17.9; `NGU-CANH-DAY-DU.md` Phần I mục 5.4 và Phần IV mục 9.3; `build/02-cac-tang-he-thong.md` T5.*

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

M9 cho người vận hành **nhìn thấy** hệ thống — sức khỏe, quyết định của M5, hàng đợi, chi phí LLM, cảnh báo — nhưng **không bao giờ điều khiển** nó **[Chốt 17.9]**. Nó gom các thành phần giám sát đã "Phải có" nhưng nằm rải rác (M7 audit, 16.3, 16.5, 17.1, 17.5) thành một tầng có ranh giới rõ, để trả lời câu hỏi hội đồng "hệ thống có tầng giám sát không?" bằng một câu.

### 1.1. Ba điều "không" [Chốt 17.9.1]

1. **Không gọi `goto()`, không sửa state, không gọi API ghi.** Chỉ `SELECT` bằng role Postgres `app_monitor`.
2. **Cảnh báo chỉ báo người.** Escalation rate > 40% → cảnh báo đỏ; **không** tự đổi `THRESHOLD_LOW/HIGH`. Đổi ngưỡng phải qua "mô phỏng tác động" rồi lưu policy mới (16.3).
3. **Không là nguồn dữ liệu cho M5.** Vòng phản hồi "ca xấu" luôn qua người xem xét.

Ngoại lệ ghi duy nhất: tạo bản ghi `alerts` qua **một endpoint riêng của M7** (`audit/alerts_writer`), không ghi bảng nghiệp vụ nào khác **[Chốt T5 ở `02`]**.

## 2. Sơ đồ cấu tạo

```
                 (ghi)                                        (chỉ đọc — role app_monitor)
Agent · Kiểm soát · B17 ──► audit_logs, escalations, approvals, ──► monitor/queries.py (view SQL, lọc is_parent=false)
                            tickets, turns, spans, llm_calls,           │
                            security_events, child_notices               ├─► /api/dashboard/business   (Trưởng BP; L1: phần của mình)
                                                                         ├─► /api/dashboard/ai         (dev/LLMOps)
                                                                         ├─► /api/escalations/queue    (L2, theo ưu tiên)
                                                                         ├─► /api/health               (vận hành)
                                                                         └─► monitor/rules.py ── worker 60s / hằng ngày ──►
                                                                                 alerts_writer (M7) ──► alerts ──► UI + thông báo
```

Không có mũi tên nào từ M9 quay lại Agent, Kiểm soát hay B17 **[Chốt 17.9.2]**.

## 3. Công nghệ

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Truy vấn | SQL view trên Postgres, SQLAlchemy Core, role `app_monitor` | Quyền chỉ-đọc ép ở tầng DB **[Đề xuất D-05]** |
| Ranh giới code | import-linter: `monitor` không import `graph`, `executor`, `tools`, `audit`, `approval`, `risk`, `api`, `guard`, `llm`, `rag`; chỉ `api`, `worker` (và `main`) import `monitor` (`monitor-only-api-worker`) | **[Chốt 17.9.1]**, hợp đồng ở `01` mục 4.3 (mở rộng ở M9 A0) |
| Lịch đánh giá luật | APScheduler trong `worker` (60 giây cho luật tức thời, thứ Hai 02:00 giờ VN hằng tuần cho drift) | Không thêm service **[Chốt]** |
| Drift | PSI tự viết (numpy) | 10 dòng code, không cần thư viện |
| Hiển thị | Frontend P10 | |

## 4. View dữ liệu

```sql
-- mọi chỉ số chỉ tính ticket lá (D-30)
CREATE VIEW v_leaf AS SELECT * FROM tickets WHERE is_parent = false;

-- quyết định M5 = audit điểm 4
CREATE VIEW v_decisions AS
SELECT a.ticket_id, a.created_at, a.decided_by, a.policy_decision, a.risk_level,
       a.matched_rule_id, a.calibrated_prob
FROM audit_logs a JOIN v_leaf t USING (ticket_id)
WHERE a.step IN ('B12','B13','B14','B13/B14');

-- hàng đợi L2 theo ưu tiên (exit_code_priority)
CREATE VIEW v_l2_queue AS
SELECT e.*, p.rank FROM escalations e JOIN exit_code_priority p USING (exit_code)
JOIN v_leaf t USING (ticket_id) WHERE e.closed_at IS NULL
ORDER BY p.rank, e.created_at;
```

**Chỉ mục cần có:** `tickets(created_at) WHERE is_parent=false` (P7), `audit_logs(step, created_at)`, `escalations(closed_at, exit_code)`, `llm_calls(created_at)`. Mục tiêu: truy vấn dashboard < 2 giây trên 10.000 ticket **[Chốt T5]**.

## 5. Thành phần [Chốt 17.9.3]

| Thành phần | Nội dung | Người xem | Quyền |
|---|---|---|---|
| `/api/health` | DB, Qdrant, mock, ml-service, LLM (ping nhẹ, cache 10 giây) | Vận hành | Công khai trong mạng nội bộ |
| Dashboard nghiệp vụ | Automation, escalation (thô + trọng số, cảnh báo 40%), deflection, số hết hạn duyệt, phân bố `decided_by`, top luật khớp, số lần ghi đè, tỉ lệ E1 tách `out_of_scope`/`intent_low_confidence` (D-27), danh sách ca E3 (lỗ hổng KB) | Trưởng BP (toàn bộ); L1 (phần mình duyệt) | `dashboard:read:all` / `:own` |
| Dashboard AI/LLMOps | Token/ticket, chi phí/ngày, p95 độ trễ theo bước, cache hit, JSON lỗi lần đầu, dùng fallback, số E2 do LLM lỗi, **số E9**, tỉ lệ B2 xuống L4, tỉ lệ `intent_filter_fallback` (D-23), tỉ lệ B3 xuống LLM và phiên bản model đang chạy (D-32) | Dev | `dashboard:read:all` |
| Hàng đợi L2 | `v_l2_queue`, có `reason_detail` | L2, L1 | `escalation:handle` |
| Drift (Nên có) | PSI tuần này so tuần mốc: phân bố intent, confidence (10 bin), điểm truy hồi cao nhất, tỉ lệ E3, escalation, ghi đè | Trưởng BP | `dashboard:read:all` |
| Chỉ số ticket nhiều ý | Thời gian từ khi con đầu tiên dừng tới khi cha gửi tin; tin/lượt (= 1) (D-31) | Dev | `dashboard:read:all` |

## 6. Luật cảnh báo

Mười bốn luật: tám luật gộp từ tài liệu gốc **[Chốt 17.9.3]**, bốn luật an ninh/vận hành bổ sung **[Đề xuất ở `02` T5]**, một luật cho model intent (D-32) và một luật ngân sách LLM (N1). Mọi luật dừng ở "báo người".

| # | Luật | Điều kiện | Chu kỳ | Người nhận |
|---|---|---|---|---|
| 1 | Escalation rate cao | > 40% trên phân bố vận hành giả định, cửa sổ 7 ngày | Hằng ngày | Trưởng BP |
| 2 | Injection | Mỗi ticket `exit_code = E0` | 60 giây | Trưởng BP (ngay) |
| 3 | Dò mật khẩu | `security_events.account_locked` | 60 giây | Trưởng BP (ngay) |
| 4 | Lỗi chưa lường trước | Số E9 trong 1 giờ > 3 × trung vị 7 ngày (tối thiểu 3 ca) | 60 giây | Dev |
| 5 | Hạ tầng ngoài yếu | Circuit breaker mở (5 lỗi/60 giây) | 60 giây | Vận hành |
| 6 | Dồn hạn chờ duyệt | Số E6 trong 1 giờ > 3 × trung vị 7 ngày | 60 giây | Trưởng BP |
| 7 | Duyệt theo phản xạ | Một L1 có ≥ 3 phiếu trong ngày với thời gian xem < 5 giây | Hằng ngày | Trưởng BP |
| 8 | Drift | PSI > 0,2 ở bất kỳ phân bố nào | Hằng tuần | Trưởng BP |
| 9 | Refresh token bị dùng lại | Mỗi `refresh_reuse_detected` | 60 giây | Trưởng BP (ngay) |
| 10 | Bị từ chối quyền dồn dập | > 10 `permission_denied` / 5 phút / một người | 60 giây | Trưởng BP |
| 11 | Policy vừa được lưu | Mỗi `policy_saved` | 60 giây | Trưởng BP |
| 12 | Classifier B2 xuống cấp | Tỉ lệ câu xuống L4 > 30% trong ngày | Hằng ngày | Dev |
| 13 | Model intent xuống cấp (D-32) | Tỉ lệ câu B3 xuống LLM > 30% trong ngày | Hằng ngày | Dev |
| 14 | Sắp hết ngân sách LLM (N1) | Tổng `llm_calls.cost_usd` ≥ 80% `spend.cap_usd` (P2 mục 5) | Hằng giờ | Dev + cả nhóm |

```python
# monitor/rules.py — hàm thuần: (dữ liệu đã truy vấn) → list[AlertDraft]; không I/O ghi
@rule(id="escalation_rate_high", every="daily")
def escalation_rate_high(q) -> list[AlertDraft]:
    r = q.weighted_escalation_rate(days=7)
    return [AlertDraft("escalation_rate_high", severity="warning", value=r)] if r > 0.40 else []
```

**Khóa chống trùng (v1.3, migration 0004):** `alerts` có `UNIQUE (rule_id, subject, window_start)`, nên chạy lại luật không sinh cảnh báo trùng, mà hai đối tượng khác nhau trong cùng cửa sổ vẫn ra hai cảnh báo. Khóa cũ `(rule_id, cửa sổ thời gian)` gộp chúng làm một — bỏ sót sự cố an ninh ở các luật "mỗi sự kiện" (2, 3, 9, 10) **[Chốt khi hiện thực Phase 2b-1]**.

`subject` là bắt buộc, cột không có DEFAULT (P7 mục 2.12). `window_start`: luật theo sự kiện dùng thời điểm sự kiện; luật tổng hợp dùng đầu cửa sổ đánh giá.

| # | `rule_id` | `subject` | `window_start` | Trạng thái |
|---|---|---|---|---|
| 1 | `escalation_rate_high` | `SYSTEM_SUBJECT` (`""`) | Đầu ngày đánh giá | [Đề xuất, chốt ở Phase 7] |
| 2 | `injection_detected` | `ticket_id` | Thời điểm B2 chặn | [Đề xuất, chốt ở Phase 7] |
| 3 | `password_bruteforce` | `user_id` (không có dòng `users` → `username:<tên>`) | Thời điểm bắt đầu khóa | **[Chốt 2b-1]** — auth ghi lúc khóa, B1 ghi lại cùng khóa (B01 mục 5.1) |
| 4 | `e9_spike` | `""` | Đầu giờ | [Đề xuất] |
| 5 | `breaker_open` | Tên tool | Thời điểm breaker mở | [Đề xuất] |
| 6 | `e6_spike` | `""` | Đầu giờ | [Đề xuất] |
| 7 | `reflex_approval` | `user_id` của L1 | Đầu ngày | [Đề xuất] |
| 8 | `drift` | Tên phân bố | Đầu tuần | [Đề xuất] |
| 9 | `refresh_reuse` | `token_family_id` | Thời điểm phát hiện | [Đề xuất] |
| 10 | `permission_denied_burst` | `user_id` | Đầu cửa sổ 5 phút | [Đề xuất] |
| 11 | `policy_saved` | Phiên bản policy | Thời điểm lưu | [Đề xuất] |
| 12–14 | `b2_degraded`, `b3_degraded`, `llm_budget` | `""` | Đầu ngày / đầu giờ | [Đề xuất] |

**Việc Phase 7 (đã ghi PROGRESS 2b):** thêm luật cho audit `finalize_failed_permanent` (B20 thử lại 3 lần vẫn lỗi — B20 mục 5.1); cảnh báo E0/E7/E9 ở bước 6 sơ đồ B20 do M9 làm qua luật 2 và 4.

### 6.1. Chốt khi hiện thực M9 (A0, B0, plan B1 — 01/10/2026; B3 — 14/10/2026)

Thiết kế hiện thực chi tiết, chia việc, câu hỏi Q-M9: `claude/ke-hoach-m9-monitor.md` và `claude/ke-hoach-m9-chia-viec.md` (bản mới nhất). Khi lệch với mục 5–6 ở trên (vd `/api/health` không ping LLM thật — Q-M9-7; E1 tách 4 `reason_detail` + `other`; drift chạy hằng tuần; luật 14 người nhận = dev, manager, ops), hai file đó thắng (trừ bất biến và mục [Chốt]).

| Điểm | Chốt | Lý do |
|---|---|---|
| Engine | `monitor_engine(engines)`; thiếu `MONITOR_DATABASE_URL` → `MonitorUnavailable` → 503 `{"detail": "monitor_unavailable"}`; không bao giờ rơi về `app_rw` | Fail-closed — rơi về là mất rào chỉ-đọc mà không ai biết |
| Hàm luật | Thuần, `(data, ctx: RuleContext) -> list[AlertDraft]`; dữ liệu qua `@loader` (chỉ SELECT); `evaluate` bắt lỗi theo từng luật; nguồn chưa có → `Pending` → `skipped_rules` | Một luật hỏng không làm mất cảnh báo của luật khác |
| Savepoint (B1) | Mỗi luật chạy trong savepoint riêng; test Postgres "loader A lỗi SQL → luật B vẫn ra draft" | Một câu SQL lỗi làm hỏng cả transaction → mất cảnh báo cả job (FN) |
| Người nhận | Khai báo bắt buộc `@rule(rule_id, every, audience=...)`; **không** ghi `alerts.detail.audience` | Một nguồn sự thật cạnh luật, đổi không cần sửa dữ liệu cũ |
| Luật 2 | Mọi E0 (B2 + B11/B19 `injection_in_reply`); `window_start` = `created_at` nhỏ nhất của `audit_logs` có `exit_code='E0'` | Không chỉ bắt tấn công ở B2 |
| Luật 3 | Đối soát: tra `alerts` ±60 s, chỉ xét sự kiện cũ hơn 60 s; không dựng khóa từ `occurred_at` | `lock_start` của auth ≠ `occurred_at` (hai lần gọi đồng hồ) |
| Luật 9 | `subject = user_id` (sự kiện không có `token_family_id`) | Kiểm code 29/09 |
| Luật 13 | Skipped tới Phase 5 (`b3_cascade` pending) | Chưa có cascade → tỉ lệ ≈ 100%, báo mỗi ngày = nhiễu |
| Luật 15, 16 | Thêm `finalize_failed` (không lọc lá) và `execution_failed` (mọi E7) | B20 bước 6 yêu cầu cảnh báo E7; ticket cha lỗi finalize cũng phải báo |
| Lookback | Luật theo sự kiện quét lại 24 giờ | Worker chết một lúc không mất cảnh báo; khóa chống trùng chặn bản sao |
| Luật 8 drift (B3, PR #37) | 6 phân bố (intent, confidence 10 bin, điểm truy hồi cao nhất, tỉ lệ E3, escalation, ghi đè), mốc bin là hằng trong code; tuần đo so tuần mốc liền trước; PSI > 0,2 nghiêm ngặt, bin rỗng ε = 1e-4 không chuẩn hoá lại; một phía 0 mẫu → không đo (không trả 0); job thứ Hai 02:00 giờ VN; khối `drift` dashboard do luồng A làm (Q-M9-B3-4). Chi tiết Q-M9-B3-1…17: thẻ B3 của `claude/ke-hoach-m9-chia-viec.md` | Không đọc ngưỡng/mốc từ `config/` (D-43); thiếu mẫu mà trả 0 là che drift (FN) |

## 7. API

| Endpoint | Quyền | Ghi chú |
|---|---|---|
| `GET /api/health` | nội bộ | 200 khi mọi phụ thuộc lõi sống; 503 kèm danh sách phụ thuộc lỗi. Phụ thuộc lõi = DB, Qdrant, mock, ml-service; `runtime`/`kb`/`llm`/`monitor` chỉ báo, không đổi mã (D-50) |
| `GET /api/dashboard/business?from&to` | `dashboard:read:all` hoặc `:own` | L1 chỉ thấy phiếu mình duyệt **[Chốt 2.2]** |
| `GET /api/dashboard/ai?from&to` | `dashboard:read:all` | |
| `GET /api/escalations/queue` | `escalation:handle` | |
| `GET /api/alerts?status=open` | `alert:read` | Trưởng BP |
| `POST /api/alerts/{id}/ack` | `alert:read` | Ghi `acked_by` — thao tác duy nhất người dùng làm với cảnh báo |

## 8. Kiểm thử và tiêu chí đạt

| Loại | Test | Đạt khi |
|---|---|---|
| Tĩnh | import-linter hợp đồng monitor | Xanh **[Chốt]** |
| DB | `INSERT audit_logs` dưới `app_monitor` | Lỗi quyền **[Chốt]** |
| Unit | Mỗi luật 1–13 với dữ liệu mẫu vượt và không vượt ngưỡng | 26 test xanh |
| Unit | PSI trên hai phân bố tính tay | Khớp |
| Integration | Câu 2 ý | Dashboard đếm 2 ticket lá, không đếm cha (D-30) |
| Hiệu năng | 10.000 ticket giả | Mỗi truy vấn dashboard < 2 giây |
| Ranh giới | Luật 1 vượt ngưỡng | `policy_versions` không đổi, chỉ có 1 dòng `alerts` |

## 9. Phase

- **Phase 1:** `/api/health`.
- **Phase 2:** `turns`, `spans` (P1).
- **Phase 4:** view `v_decisions`, `v_l2_queue`; luật 2, 3, 6.
- **Phase 7:** dashboard nghiệp vụ + AI trên giao diện; luật 1, 4, 5, 7, 9–12.
- **Phase 8 (Nên có):** drift, luật 8.

## 10. Nhật ký thay đổi

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file: ranh giới chỉ đọc, view SQL, 12 luật cảnh báo, API, kiểm thử |
| 25/09/2026 | 1.1 | Thêm luật 13 (model intent xuống cấp) và chỉ số đường B3 (D-32) |
| 25/09/2026 | 1.2 | Thêm luật 14 (sắp hết ngân sách LLM, N1) |
| 26/09/2026 | 1.3 | Khóa chống trùng `(rule_id, subject, window_start)`, bảng `subject` cho 14 luật (luật 3 chốt ở Phase 2b-1, còn lại đề xuất); việc Phase 7: luật `finalize_failed_permanent` |
| 01/10/2026 | 1.5 | Mục 6.1: hai file `claude/ke-hoach-m9-*.md` thắng cả khi lệch mục 5 (không chỉ mục 6), kèm ví dụ đã lệch |
| 01/10/2026 | 1.4 | Mục 3 ranh giới import mở rộng (M9 A0); mục 6.1 "Chốt khi hiện thực M9" trỏ về `claude/ke-hoach-m9-*.md` |
| 14/10/2026 | 1.6 | B3 (luật 8 drift) merge: mục 3 lịch drift hằng tuần (thứ Hai 02:00 giờ VN), mục 5 drift `confidence` 10 bin (không phải "confidence TB"), mục 6.1 thêm dòng luật 8 |
| 16/10/2026 | 1.7 | Mục 7 dòng `GET /api/health`: phụ thuộc lõi = DB, Qdrant, mock, ml-service; `runtime`/`kb`/`llm`/`monitor` chỉ báo (D-50, P6→P5 #23) |
