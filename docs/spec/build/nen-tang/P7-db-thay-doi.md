# P7 — Thay đổi cơ sở dữ liệu so với `claude/thiet-ke-database.md`

*Thuộc bộ `build/`. Bản thiết kế DB hiện có 17 bảng (đã qua 3 vòng review). Bộ build thêm **5 bảng**, **mở rộng 6 bảng** và thêm **3 role Postgres + 2 trigger**. Tổng: 22 bảng. Mọi thay đổi đều là thêm (không xóa, không đổi tên cột), nên an toàn với migration theo từng đợt **[Chốt 13.3]**. Bản vá v1.2 thêm bảng `side_effects` (D-18), sửa khóa idempotent của `audit_logs` (D-14), thêm UNIQUE một phiếu `pending` mỗi ticket ở `approvals` và cột `reason_detail` ở `escalations` (D-27). Bản v1.3 thêm bảng `child_notices` và cột `tickets.is_parent` cho cơ chế một tin tổng hợp (D-30, D-31).*

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

**Mã quyết định dùng trong file (bản vá v1.2):** D-04, D-05, D-11, D-14 (khóa mới), D-18, D-27.

---

## 1. Tóm tắt

| Loại | Bảng | Lý do | Quyết định |
|---|---|---|---|
| Mới | `security_events` (+ view `auth_failures`) | Sự kiện an ninh không thuộc ticket; `auth_failures` được nhắc nhưng chưa có | D-04 |
| Mới | `llm_cache` | Cache LLM cho thực nghiệm tái lập, không thêm Redis | D-11 |
| Mới | `wait_deadlines` | Worker cần hạn chờ của `S_CLARIFYING` (24h) và `S_CONFIRMING` (48h) mà không đọc checkpoint | P1 mục 7 |
| Mới | `side_effects` | Chống làm lại side effect khi node chạy lại sau sự cố: thông báo, đặt hạn, tạo phiếu duyệt, tạo/submit ticket con | D-18 (v1.2) |
| Mới | `child_notices` | Hộp thư của ticket con: lời nhắn con định gửi người dùng được giữ lại để ticket cha gom thành một tin | D-31 (v1.3) |
| Mở rộng | `tickets` | `is_parent` để lọc ticket lá khi tính chỉ số và hàng đợi L2; cha đóng với `close_reason = NULL` | D-30 (v1.3) |
| Mở rộng | `users` | Thuộc tính cho AuthN/AuthZ và M5 | D-01, D-02 |
| Mở rộng | `sessions` | Refresh token xoay vòng, thu hồi | D-01 |
| Mở rộng | `audit_logs` | Khóa idempotent `(ticket_id, step, event, turn_id, loop_seq)`, `turn_id`, `kb_version` | D-14 (sửa v1.2) |
| Mở rộng | `approvals` | Người dự phòng, loại xung đột, thời điểm xem, mốc nhắc; **tối đa 1 phiếu `pending` mỗi ticket** | B15–B16, D-18 |
| Mở rộng | `escalations` | `reason_detail` để tách E1 thật khỏi ca confidence thấp | D-27 (v1.2) |
| Role + trigger | `app_rw`, `app_monitor`, `app_migrate`; trigger append-only trên `audit_logs`, `security_events` | Ép ràng buộc ở tầng DB | D-05 |

**Nguyên tắc giữ nguyên từ thiết kế DB vòng 3 [Chốt]:** dữ liệu đổi liên tục (trạng thái, Action đang dựng, hội thoại) nằm trong checkpoint LangGraph, không nhân đôi vào bảng. Năm bảng mới không vi phạm nguyên tắc này:

- `security_events` là sự kiện ghi một lần.
- `llm_cache` là dữ liệu dẫn xuất.
- `wait_deadlines` chỉ là chỉ mục hạn chờ, có một chủ sở hữu duy nhất là node đặt hạn.
- `side_effects` chỉ là chỉ mục chống trùng, có một chủ sở hữu duy nhất là hàm `effects.once` (P1 mục 5.3); nó lưu **tham chiếu** tới kết quả (`result_ref`, ví dụ `approval_id`), không lưu dữ liệu nghiệp vụ.
- `child_notices` là hàng đợi ghi một lần (mỗi dòng chỉ đổi một lần: `delivered_at` từ NULL sang có giá trị). Ticket cha phải đọc được lời nhắn của **các thread khác** (các con); checkpoint của con không đọc chéo được, nên cần một bảng. `tickets.is_parent` được ghi đúng một lần ở B5.

## 2. DDL

### 2.1. `users` (mở rộng)

```sql
ALTER TABLE users
  ADD COLUMN ad_object_id      VARCHAR(64) UNIQUE,
  ADD COLUMN manager_id        VARCHAR(64) REFERENCES users(user_id),
  ADD COLUMN employment_status VARCHAR(16) NOT NULL DEFAULT 'active'
      CHECK (employment_status IN ('active','probation','disabled','terminated')),
  ADD COLUMN hired_at          DATE,
  ADD COLUMN mfa_secret_enc    BYTEA,
  ADD COLUMN token_version     INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN locked_until      TIMESTAMPTZ,
  ADD COLUMN last_synced_at    TIMESTAMPTZ;
-- KHÔNG có cột mật khẩu: xác thực qua IdentityProvider (AD/mock).
```

`role` giữ CHECK ∈ {employee, l1, manager, l2} như bản hiện có **[Chốt]**.

### 2.2. `sessions` (mở rộng)

```sql
ALTER TABLE sessions
  ADD COLUMN refresh_token_hash CHAR(64) UNIQUE,
  ADD COLUMN token_family_id    UUID NOT NULL,
  ADD COLUMN last_seen_at       TIMESTAMPTZ,
  ADD COLUMN expires_at         TIMESTAMPTZ NOT NULL,
  ADD COLUMN revoked_at         TIMESTAMPTZ,
  ADD COLUMN revoke_reason      VARCHAR(24)
      CHECK (revoke_reason IN ('logout','rotated','reuse_detected','user_disabled','admin','expired')),
  ADD COLUMN ip_prefix          VARCHAR(48),   -- che octet cuối (IPv4 /24, IPv6 /48)
  ADD COLUMN user_agent_hash    CHAR(64);
CREATE INDEX ix_sessions_family ON sessions(token_family_id);
CREATE INDEX ix_sessions_user_active ON sessions(user_id) WHERE revoked_at IS NULL;
```

### 2.3. `security_events` (mới)

```sql
CREATE TABLE security_events (
  event_id           BIGSERIAL PRIMARY KEY,
  occurred_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type         VARCHAR(32) NOT NULL CHECK (event_type IN (
      'login_success','login_failed','account_locked','logout','token_refreshed',
      'refresh_reuse_detected','session_revoked','permission_denied','role_changed',
      'mfa_failed','mfa_enrolled','mfa_reset',         -- mfa_enrolled/mfa_reset: thêm ở migration 0002 (26/09/2026)
      'policy_saved','injection_detected','privacy_secret_redacted')),
  user_id            VARCHAR(64) REFERENCES users(user_id),
  username_attempted VARCHAR(128),
  ip_prefix          VARCHAR(48),
  route              VARCHAR(128),
  ticket_id          VARCHAR(64),          -- chỉ với injection_detected, privacy_secret_redacted
  detail             JSONB NOT NULL DEFAULT '{}'::jsonb   -- KHÔNG chứa mật khẩu/token/nội dung chat
);
CREATE INDEX ix_sec_user_time ON security_events(username_attempted, occurred_at DESC);
CREATE INDEX ix_sec_type_time ON security_events(event_type, occurred_at DESC);

CREATE VIEW auth_failures AS
  SELECT * FROM security_events WHERE event_type IN ('login_failed','mfa_failed');
```

**`mfa_enrolled`, `mfa_reset` [Chốt 26/09/2026]:** ghi mỗi khi lệnh CLI `python -m app.auth.mfa enroll|reset` chạy (P6: MFA chỉ đăng ký qua kênh vận hành, không qua đăng nhập). `detail` chỉ chứa người thực hiện và lý do, **không** chứa secret hay URI `otpauth`. Hai loại này **không** nằm trong view `auth_failures`.

**Truy vấn đếm dò mật khẩu [Chốt 5/10 phút]:**

```sql
SELECT count(*) FROM auth_failures
WHERE username_attempted = :u AND occurred_at > now() - interval '10 minutes';
```

### 2.4. `llm_cache` (mới)

```sql
CREATE TABLE llm_cache (
  cache_key     CHAR(64) PRIMARY KEY,           -- sha256 theo P2 mục 8
  prompt_id     VARCHAR(64) NOT NULL,
  prompt_version VARCHAR(16) NOT NULL,
  model         VARCHAR(128) NOT NULL,
  response_json JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ,                     -- NULL = không hết hạn (chế độ eval)
  mode          VARCHAR(8) NOT NULL CHECK (mode IN ('runtime','eval'))
);
CREATE INDEX ix_llm_cache_exp ON llm_cache(expires_at) WHERE expires_at IS NOT NULL;
```

### 2.5. `wait_deadlines` (mới)

```sql
CREATE TABLE wait_deadlines (
  ticket_id   VARCHAR(64) NOT NULL REFERENCES tickets(ticket_id),
  kind        VARCHAR(12) NOT NULL CHECK (kind IN ('clarify','confirm')),
  deadline    TIMESTAMPTZ NOT NULL,
  created_turn VARCHAR(64) NOT NULL,
  fired_at    TIMESTAMPTZ,
  PRIMARY KEY (ticket_id, kind, created_turn)
);
CREATE INDEX ix_wait_due ON wait_deadlines(deadline) WHERE fired_at IS NULL;
```

Hạn duyệt vẫn nằm ở `approvals.deadline` **[Chốt]**, vì `approvals` là chủ sở hữu vòng đời phê duyệt.

### 2.6. `approvals` (mở rộng)

```sql
ALTER TABLE approvals
  ADD COLUMN backup_approver_id VARCHAR(64) REFERENCES users(user_id),
  ADD COLUMN conflict_type      VARCHAR(24)
      CHECK (conflict_type IN ('self','boss_of_approver','targets_approver')),
  ADD COLUMN first_viewed_at    TIMESTAMPTZ,      -- phát hiện duyệt cho có [Chốt 8.3]
  ADD COLUMN reminder_1_at      TIMESTAMPTZ,      -- 50% SLA
  ADD COLUMN reminder_2_at      TIMESTAMPTZ;      -- 80% SLA
-- status thêm giá trị 'late_ignored' cho TC27 (sửa CHECK hiện có)

-- v1.2 (D-18): lớp bảo vệ thứ hai, phòng khi side_effects bị bỏ qua do bug
CREATE UNIQUE INDEX ux_approvals_one_pending ON approvals(ticket_id) WHERE status = 'pending';
```

### 2.7. `audit_logs` (mở rộng)

```sql
ALTER TABLE audit_logs
  ADD COLUMN turn_id     VARCHAR(64),
  ADD COLUMN loop_seq    SMALLINT NOT NULL DEFAULT 0,          -- v1.2
  ADD COLUMN kb_version  CHAR(64),
  ADD COLUMN idempotency_key CHAR(64);   -- sha256(ticket_id|step|event|turn_id|loop_seq)  (v1.2)
CREATE UNIQUE INDEX ux_audit_idem ON audit_logs(idempotency_key) WHERE idempotency_key IS NOT NULL;
```

`goto()` ghi bằng `INSERT … ON CONFLICT (idempotency_key) DO NOTHING` **[Đề xuất D-14]**.

**Vì sao đổi khóa ở v1.2:** khóa cũ `sha256(ticket_id|step|turn_id)` làm hai sự kiện khác nhau của cùng một bước trong một lượt (ví dụ B11 `user_replied` rồi `action_built`) trùng khóa, nên bản ghi thứ hai bị bỏ qua âm thầm. Thêm `event` và `loop_seq` giữ được cả hai, mà vẫn chặn được bản ghi trùng thật khi node chạy lại.

### 2.8. `side_effects` (mới, v1.2) [Đề xuất D-18]

```sql
CREATE TABLE side_effects (
  effect_key  CHAR(64) PRIMARY KEY,          -- sha256(ticket_id|step|turn_id|loop_seq|kind|sub)
  ticket_id   VARCHAR(64) NOT NULL REFERENCES tickets(ticket_id),
  kind        VARCHAR(32) NOT NULL CHECK (kind IN (
      'notify_user','notify_approver','deadline_set','approval_create',
      'child_create','child_submit','escalation_create',
      'child_event')),                         -- v1.3 (D-31): cha chuyển câu trả lời xuống con
  step        VARCHAR(16) NOT NULL,
  turn_id     VARCHAR(64) NOT NULL,
  result_ref  VARCHAR(128),                  -- ví dụ approval_id, child ticket_id, notification_id
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_side_effects_ticket ON side_effects(ticket_id);
```

Dùng bởi `effects.once` (P1 mục 5.3). Không có ràng buộc append-only: đây là chỉ mục kỹ thuật, không phải bằng chứng kiểm toán.

### 2.9. `child_notices` (mới, v1.3) [Đề xuất D-31]

```sql
CREATE TABLE child_notices (
  notice_id        BIGSERIAL PRIMARY KEY,
  parent_ticket_id VARCHAR(64) NOT NULL REFERENCES tickets(ticket_id),
  child_ticket_id  VARCHAR(64) NOT NULL REFERENCES tickets(ticket_id),
  source_step      VARCHAR(16) NOT NULL,             -- B10, B11, B16, B18, B20
  kind             VARCHAR(16) NOT NULL CHECK (kind IN ('answer','question','result','rejection','escalation')),
  needs            VARCHAR(8)  NOT NULL CHECK (needs IN ('none','answer','confirm')),
  body             TEXT NOT NULL,                    -- đã qua privacy guard, như mọi tin gửi người dùng
  effect_key       CHAR(64) NOT NULL UNIQUE,         -- khóa effects.once của lần notify_user tạo ra dòng này
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_round  SMALLINT,
  delivered_at     TIMESTAMPTZ,
  CHECK ((delivered_at IS NULL) = (delivered_round IS NULL))
);
CREATE INDEX ix_child_notices_pending ON child_notices(parent_ticket_id) WHERE delivered_at IS NULL;
```

`notify_user` của ticket con ghi vào đây thay vì gửi (P1 mục 8.1). `parent_wait` đọc các dòng chưa gửi, gộp thành một tin, rồi đánh dấu `delivered_*` theo vòng.

### 2.10. `tickets` (mở rộng, v1.3) [Đề xuất D-30]

```sql
ALTER TABLE tickets ADD COLUMN is_parent BOOLEAN NOT NULL DEFAULT false;   -- ghi một lần ở B5
CREATE INDEX ix_tickets_leaf ON tickets(created_at) WHERE is_parent = false;
```

Ticket cha đóng với `close_reason = NULL`; CHECK `close_reason IN (8 giá trị)` hiện có vẫn giữ nguyên, vì Postgres cho NULL đi qua CHECK. Mọi truy vấn chỉ số M8/M9 và hàng đợi L2 lọc `is_parent = false`.

### 2.11. `escalations` (mở rộng, v1.2) [Đề xuất D-27]

```sql
ALTER TABLE escalations
  ADD COLUMN reason_detail VARCHAR(48);   -- ví dụ 'out_of_scope', 'intent_low_confidence',
                                          -- 'identity_unverifiable', 'screening_unavailable'
```

Mã thoát E0–E9 giữ nguyên **[Chốt]**. `reason_detail` chỉ để M9 tách các nguyên nhân khác nhau trong cùng một mã.

## 3. Role và trigger

Xem DDL đầy đủ ở `P6-auth-bao-mat.md` mục 6. Tóm tắt:

| Role | Dùng bởi | Quyền |
|---|---|---|
| `app_migrate` | Alembic | Owner schema |
| `app_rw` | backend, worker | CRUD bảng nghiệp vụ; chỉ SELECT + INSERT trên `audit_logs`, `security_events` |
| `app_monitor` | endpoint M9 | Chỉ SELECT trên bảng giám sát |

Trigger `forbid_mutation` trên `audit_logs` và `security_events` là lớp thứ hai, phòng khi ai đó chạy nhầm bằng role owner.

**Checkpoint LangGraph:** bảng do `checkpointer.setup()` tạo, chạy dưới `app_migrate` lúc migration. `app_rw` cần quyền CRUD trên các bảng này.

**Pool khóa (D-19):** khóa ticket dùng `pg_advisory_lock` cấp session trên một pool kết nối riêng cùng role `app_rw`. Không cần bảng hay quyền mới.

**Chốt khi hiện thực Phase 1a (26/09/2026):**

- **Ai tạo role:** script init của container Postgres (superuser, chạy một lần) tạo 3 role, mật khẩu lấy từ env, cho `app_migrate` làm owner schema. Alembic chạy bằng `app_migrate`, không dùng superuser. Downgrade không xoá role.
- **Chặn cả `TRUNCATE`:** thêm trigger cấp câu lệnh `BEFORE TRUNCATE` trên `audit_logs` và `security_events`. Trigger `forbid_mutation` cấp dòng không bắt được `TRUNCATE` **[Đề xuất, đã hiện thực]**.
- **`tickets`:** cột câu yêu cầu tên là `redacted_request` (chỉ lưu bản đã che, D-07), không phải `raw_request`. Đủ 20 cột có nguồn + `is_parent` = 21 cột.
- **`transaction_log.status`:** CHECK `{begun, undone, undo_failed}` — `begun` để phát hiện thực thi bị gián đoạn (B17 mục 8).
- **`audit_logs`:** thêm cột `raw_prob` (0..1) và `p_method` `{self_report, sampling_k5}` cho điểm log 4 (B12 mục 8, P8 fit calibrator); phần bổ sung khác của từng nhánh vào `detail JSONB`.
- **Index cho P9:** `audit_logs(step, created_at)`, `escalations(closed_at, exit_code)`, `llm_calls(created_at)`.
- **Nguồn sự thật của 17 bảng gốc:** `schema.sql` gốc đã mất; bảng "bảng → cột → nguồn" nằm ở `backend/app/db/README.md`, DDL thật là `backend/app/db/models.py` + migration `0001`.

## 4. Chính sách lưu trữ [Chốt 17.2, chi tiết hóa]

| Dữ liệu | Giữ | Cách xóa |
|---|---|---|
| Checkpoint + hội thoại | 90 ngày sau khi đóng ticket | Job đêm của worker, dùng role `app_migrate` |
| `llm_cache` runtime | 24 giờ | Job đêm xóa bản `expires_at < now()` |
| `llm_cache` eval | Đến khi xong thực nghiệm | Xóa tay sau khi nộp báo cáo |
| `sessions` | 30 ngày sau khi hết hạn | Job đêm |
| `security_events`, `audit_logs` | Lâu dài (append-only) | Không xóa trong phạm vi đồ án |
| `wait_deadlines` | 7 ngày sau `fired_at` | Job đêm |
| `side_effects` | Cùng vòng đời checkpoint (90 ngày sau khi đóng ticket) | Job đêm |
| `child_notices` | Cùng vòng đời hội thoại (90 ngày sau khi đóng ticket cha) — chứa nội dung tin nhắn | Job đêm |

## 5. Tiêu chí đạt

1. Migration chạy trên DB trống; `\dt` ra đúng 22 bảng (+ bảng checkpoint).
2. `INSERT` vào `security_events` với `event_type` lạ → lỗi CHECK.
3. `UPDATE`/`DELETE` trên `audit_logs`, `security_events` → lỗi (cả role `app_rw` lẫn trigger).
4. Ghi audit 2 lần cùng `(ticket_id, step, event, turn_id, loop_seq)` → đúng 1 dòng; hai `event` khác nhau cùng bước, cùng lượt → 2 dòng.
5. `users` không có cột nào chứa từ `password`.
6. Tạo phiếu `pending` thứ hai cho cùng ticket → lỗi UNIQUE (v1.2).
7. `effects.once` gọi 2 lần cùng khóa → hàm bên trong chạy đúng 1 lần, lần 2 trả cùng `result_ref` (v1.2).
8. `notify_user` của ticket con gọi 2 lần cùng khóa → đúng 1 dòng `child_notices` (UNIQUE `effect_key`) (v1.3).
9. Ticket cha đóng với `close_reason = NULL` → không lỗi CHECK; truy vấn escalation rate với `is_parent = false` không đếm cha (v1.3).

## 6. Việc cần làm ở `thiet-ke-database.md`

Khi nhóm duyệt D-04, D-05, D-11, D-14, D-18, D-27, D-30, D-31:

- Thêm 5 bảng và cột `tickets.is_parent`.
- Cập nhật `schema.sql` và `models.py`.
- Đổi tiêu đề "17 bảng" thành "22 bảng".
- Thêm mục "Vòng review thứ tư — bảo mật và vận hành" ghi lý do như trên.

## 7. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file (20 bảng) |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0 |
| 25/09/2026 | 1.2 | Thêm `side_effects` (D-18) → 21 bảng; khóa audit mới (D-14); UNIQUE phiếu `pending`; `escalations.reason_detail` (D-27) |
| 25/09/2026 | 1.3 | Thêm `child_notices` (D-31) → 22 bảng; `tickets.is_parent`, cha `close_reason = NULL` (D-30); `side_effects.kind` thêm `child_event` |
| 26/09/2026 | 1.4 | Ghi nhận các quyết định khi hiện thực Phase 1a (role, TRUNCATE, `redacted_request`, `begun`, `raw_prob`/`p_method`, index P9) |
| 26/09/2026 | 1.5 | `security_events.event_type` thêm `mfa_enrolled`, `mfa_reset` (migration 0002) |
