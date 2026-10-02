# Kế hoạch giao việc M9 — Tầng Monitor (backend)

*Tạo 29/09/2026. Người làm: **Lưu Dương** (luồng A — dashboard) và **Tạ Duy Anh** (luồng B — cảnh báo), mỗi người dùng coding agent Claude Code. **Ai làm gì, thứ tự, chủ file, hợp đồng giữa hai người: `claude/ke-hoach-m9-chia-viec.md`** — file này là tham chiếu kỹ thuật chung. Người review + merge: **Tuấn Anh** (Claude chat hỗ trợ review). Nguồn đã chốt: `build/nen-tang/P9-monitor-M9.md` (v1.3), `huong-dan-xay-dung-he-thong-2.md` §16.3–16.5, §17.1, §17.5, §17.9; `build/02-cac-tang-he-thong.md` T5; `build/nen-tang/P8-danh-gia-M8.md` §6.2 (công thức chỉ số); `build/decisions.md` §1.4 (N3). Code đối chiếu: repo `dev-tuananh` tại commit **`5d0a990`** (Phase 3 đóng phần code, CI 36686745332 xanh; bản trước đối chiếu `3f33ab2`). Thay đổi do Phase 3 và việc phối hợp với Phase 4: mục 1.4.*

Ký hiệu: **[Chốt]** = đã có trong spec/code; **[Suy luận]** = rút ra từ spec/code; **[Đề xuất]** = mới, Tuấn Anh duyệt ở mục 10.

---

## 0. Tóm tắt một màn hình

| Mục | Nội dung |
|---|---|
| Ai làm | **Lưu Dương** (luồng A) + **Tạ Duy Anh** (luồng B), code qua coding agent; review chéo lẫn nhau trước. **Tuấn Anh review cuối** plan + PR theo checklist mục 9 |
| Làm gì | Toàn bộ **backend M9**: kết nối chỉ-đọc `app_monitor`, view SQL, truy vấn chỉ số (nghiệp vụ + AI/LLMOps), API dashboard + cảnh báo, bộ luật cảnh báo chạy trong worker, bổ sung `/api/health`, test hiệu năng, drift (Nên có) |
| Không làm | Giao diện (TV3 làm ở F5 bằng dữ liệu giả, M9 xong thì nối thật); mọi thứ trong `graph/`, `risk/`, `executor/`, `tools/`, `guard/`, `config/policy.json`, `docs/spec/`, `frontend/` |
| Vì sao giao được | M9 **chỉ đọc** bảng đã có đủ từ Phase 1a (22 bảng, role `app_monitor` đã GRANT) → làm **song song** với luồng chính của Tuấn Anh, ít đụng code của nhau **[Suy luận]** |
| Kéo sớm so với lịch | P9 §9 xếp view ở Phase 4, dashboard ở Phase 7. Làm sớm bằng **dữ liệu fixture** trong test; chỉ số mà nguồn chưa có node ghi → trả `null` + tên trong `unavailable` (mục 5.3), **không trả 0** |
| Số chặng | 8 gói kỹ thuật M9-0 … M9-7 (mục 7), chia thành luồng A (A0–A4) và luồng B (B0–B3). Mỗi chặng = 1 GitHub issue = 1 PR vào `dev-tuananh` |
| Ước lượng [Suy luận] | ~5–6 ngày khi hai người chạy song song (một người ~7 ngày) |

---

## 1. Hiện trạng repo (kiểm 29/09/2026 tại `3f33ab2`)

### 1.1. Đã có — dùng lại, không viết lại

| Thứ | Ở đâu | Ghi chú cho M9 |
|---|---|---|
| Role `app_monitor` (chỉ SELECT) | `docker/postgres/init-roles.sh`, migration `0001` (`MONITOR_TABLES`: `audit_logs, escalations, tickets, turns, spans, llm_calls, security_events, approvals, alerts`) | Đọc bảng khác (vd `policy_versions`, `side_effects`) → **permission denied** là đúng thiết kế. Cần thêm bảng nào thì ghi vào plan, Tuấn Anh duyệt |
| Test role | `backend/tests/integration/test_db_constraints.py` (`test_app_monitor_cannot_insert_audit_logs`, `..._can_select_monitor_tables`, `..._cannot_read_side_effects`); fixture `monitor` ở `integration/conftest.py` | Dùng fixture `monitor` cho mọi test truy vấn |
| Hợp đồng import `monitor-read-only` | `.importlinter` #2: `app.monitor` không import `app.graph`, `app.executor`, `app.tools` | M9-0 siết thêm (mục 4.2) |
| Writer cảnh báo M7 | `backend/app/audit/alerts.py` — `AlertWriter.raise_once(draft)`: `INSERT … ON CONFLICT (rule_id, subject, window_start) DO NOTHING` | **Đường ghi duy nhất** cho `alerts` **[Chốt P9 §1.1]**. M9 chỉ sinh `AlertDraft` |
| Kiểu cảnh báo | `backend/app/domain/alerts.py` — `AlertDraft`, `SYSTEM_SUBJECT = ""`, `bruteforce_alert()` | Luật 3 **phải** dùng `bruteforce_alert()` để ra đúng khóa (mục 6) |
| Bảng `alerts` | `db/models.py` `Alert`: `rule_id, subject (NOT NULL, không DEFAULT), severity, value, window_start, status ∈ {open, acked}, detail JSONB, acked_by, acked_at` | Không đổi schema |
| `/api/health` | `api/health.py` + `main._default_checks`: `db`, `qdrant`, `mock`, `ml` + `runtime`, `kb` | Còn thiếu **LLM** và **cache 10 giây** (M9-6) |
| Hàng đợi L2 | `GET /api/escalations/queue` (`api/escalations.py`, `db/escalations.py`) — lọc `is_parent=false`, sắp theo `priority` | **Giữ nguyên route** (TV3 đã nối thật). View `v_l2_queue` chỉ dùng cho số liệu dashboard |
| Quyền | `auth/permissions.py`: `dashboard:read:all`, `alert:read` (manager); `dashboard:read:own` (l1); `escalation:handle` (l1, l2) | Dùng `Depends(require(...))` như route khác |
| Worker | `app/worker.py` `schedule_jobs()` — APScheduler `AsyncIOScheduler(timezone="UTC")` | Thêm job M9 ở đây (mục 3.3) |
| Chỉ mục | `audit_logs(step, created_at)`, `escalations(closed_at, exit_code)`, `llm_calls(created_at)` | Kiểm lại `tickets(created_at) WHERE is_parent=false` — thiếu thì thêm trong migration M9-1 |
| `numpy` | nhóm phụ thuộc chính (`pyproject.toml`) | Dùng cho PSI, không cần thêm thư viện |

### 1.2. Chưa có — M9 làm

*(Cập nhật 01/10: A0 + B0 đã merge `1f0f489` — `monitor/` có `db.py`, `views.py`, `window.py`, `rules.py`, `evaluator.py`; đoạn dưới là hiện trạng lúc tạo file.)* `backend/app/monitor/` lúc đó **chỉ có `README.md` + `__init__.py`**. Chưa có: engine `app_monitor` trong app (settings chưa có DSN monitor; compose chưa truyền `PG_MONITOR_PASSWORD` cho backend/worker), view SQL, truy vấn chỉ số, route `/api/dashboard/*`, `/api/alerts`, luật cảnh báo, job worker.

### 1.3. Nguồn dữ liệu chưa được node nào ghi (vì luồng chính mới ở Phase 3)

| Nguồn | Phase tạo ra | M9 xử lý |
|---|---|---|
| Điểm log 4 (B12–B14: `decided_by`, `policy_decision`, `risk_level`, `matched_rule_id`, `calibrated_prob`) | Phase 4–6 | Cột đã có trong `audit_logs` → viết view + test bằng fixture |
| Phiếu duyệt thật, `first_viewed_at` (route xem phiếu `GET /api/approvals/{id}`), audit B16 `view_duration` + `decided_without_view` | Phase 4 (4b B15 thật, 4c xem phiếu + B16) | Luật 7 **pending** (skipped) tới khi 4c merge; test bằng fixture |
| Ghi đè L1 — `audit_logs` step `"OVERRIDE"` | **Đã có** từ 4d dừng 1 (`e510a6e`, 02/10): `domain/override.py` `OVERRIDE_STEP`/`OVERRIDE_EVENT`, mỗi người ghi đè một ticket tối đa một dòng | `override_count` **ready** — Dương nối nguồn (v1.15) |
| ~~B3 xuống LLM~~ — **đã có từ 3f**: audit điểm log 1 ghi ở step `B3` (và `B4` cho các ca E1) với `detail.layer`, `detail.model_version` | — | `b3_llm_rate` **ready** (mục 5.2). Nhưng Phase 3–4 **mọi** câu đều xuống LLM (nhánh model + `cascade_decide` là Phase 5) → tỉ lệ ≈ 100% → luật 13 để skipped tới Phase 5 (Q-M9-9) |
| Ticket nhiều ý (D-31) | Phase 5 | Chỉ số nhiều ý → `unavailable` |
| Span tool (bảng `spans`, `span_type='tool'`) — `tools/registry.py::_span` hiện **chỉ ghi log một dòng**, không ghi DB (kiểm 29/09) | Chưa xếp (Tuấn Anh quyết, Q-M9-4) | Luật 5 → pending, test bằng fixture |
| `policy_saved` | Phase 7 | Luật 11 test bằng fixture `security_events` |

### 1.4. Thay đổi từ Phase 3 và phối hợp Phase 4 (cập nhật 30/09/2026, code `5d0a990`)

| Chủ đề | Sự thật trong code | Hệ quả cho M9 |
|---|---|---|
| B2 thật (3e) | Câu tấn công → `S_BLOCKED`, `exit_code='E0'`, `block_reason='injection_detected'`, audit step `B2` event `injection_detected` | Luật 2 và cổng B chạy trên B2 thật, **không** dùng thẻ `[fake:…]` |
| B3 thật (3f) | Điểm log 1 ở step `B3`; các ca E1 ghi step `B4` với event `intent_out_of_scope`, `multi_intent_not_enabled`, `intent_low_confidence`, `intent_not_enabled`; `detail.layer`, `detail.model_version` | `b3_llm_rate` ready; `e1_split` tách **4** lý do (không chỉ 2 của D-27) — agent xác nhận `escalations.reason_detail` tương ứng |
| E7 (3h) | Hai `reason_detail`: `exec_interrupted` (`graph/nodes/b17_execute.py`) và `execution_interrupted` (`graph/runner.py`, `graph/boundary.py`); có `transaction_log` `begun` → luôn E7, không E9 | Luật 16 đếm mọi E7; luật 4 (`e9_spike`) tự nhiên không đếm các ca này |
| Runner recover (3h, M-3h-35) | Node còn dở lấy theo `_pending(snap)`; audit B20 `finalize_failed_permanent` **giữ nguyên** | Luật 15 không đổi |
| Cờ node giả | `FAKE_NODE_DELAY` mà thiếu `FAKE_SCENARIO` → backend/worker **từ chối khởi động**; `FAKE_SCENARIO` bật → **toàn bộ** node giả (B2/B3 thật không chạy) | gate2 cần `FAKE_SCENARIO` (+ `FAKE_NODE_DELAY`) bật; gate3 và **cổng B của M9** cần **cả hai tắt** |
| Phase 4 — migration | **Không có** (spec phase4 v0.5 mục 0.2 bỏ `0008_approvals_inbox_idx`); head hiện tại `0007` | Migration M9 = `0008_monitor_views` (`down_revision = "0007"`); sau mỗi rebase `alembic heads` = 1 (Dương) |
| Phase 4 — worker | **Không sửa `worker.py`** (spec phase4 mục 0.2). Nhắc duyệt 50/80% (4c) nằm trong `WorkerJobs.scan_deadlines` (`graph/worker_jobs.py`, chu kỳ 15 s sẵn có); truy vấn ở `SqlDeadlineStore` (`db/runtime.py`) | `worker.py` thuộc riêng Duy Anh, không xung đột với Phase 4 |
| Phase 4 — settings (4a) | Khóa HMAC cho username đăng nhập không có trong `users` (Q-3e-14): `security_events.username_attempted` = `"h:" + HMAC` | Luật 3 đối soát và luật 10 dùng **đúng giá trị auth truyền cho `bruteforce_alert` / ghi vào `security_events`** sau 4a; test lại ca username ma sau khi rebase qua 4a |
| Phase 4 — xem phiếu (4c, `aac90b1`) | `approvals.first_viewed_at` là **một cột chung** cho phiếu (lần xem đầu của người chính **hoặc** dự phòng sau nhắc 2; manager xem không ghi). `decided_at` có ở cả 3 nhánh (approved/rejected/timeout, kể cả worker đóng timeout). Audit B16 có `detail.decided_without_view`, `decided_as ∈ {primary, backup}`. Việc treo 28 của Phase 4: chưa sửa schema | Luật 7 lấy nguồn từ audit B16, ca mơ hồ tính là "< 5 giây" (mục 6). Hết pending khi 4c merge |
| Phase 4 — ghi đè (4d) | 1 dòng `audit_logs` step `"OVERRIDE"`, event `override_recorded`, cột `original_decision` / `override_decision` / `overrider_id`, `detail.reason_code`; không đổi `tickets` | `override_count` hết pending sau 4d |
| Phase 4 — 4b, fixture | R17/R18/R19 đòi máy của chính người gửi: máy người khác / không tồn tại → **E5, 0 phiếu** (không còn HITL) | Fixture M9 không giả định "ngoài giờ → HITL" |
| Phase 4 — 4d `audit_check` | Công cụ kiểm audit của 4d đọc DB bằng `MONITOR_DATABASE_URL` (role `app_monitor`) nếu có, không thì `app_rw` trong giao dịch READ ONLY; chỉ đọc `audit_logs`, `tickets` | Migration M9 **chỉ thêm** GRANT, không REVOKE quyền SELECT sẵn có của `app_monitor` (nhất là `audit_logs`, `tickets`) |
| Phase 4 — 4 cột `audit_logs` chưa ghi (Việc treo 31) | `confidence`, `query`, `success`, `action_plan_hash_matched` có trong schema nhưng **chưa từng được ghi**; dữ liệu thật ở `detail.confidence`, `detail.query`, `detail.success`, `detail.action_plan_hash_matched` | M9 **không đọc** 4 cột này (đọc ra NULL = số sai im lặng); cần thì đọc từ `detail`. Quyết lại sau Phase 4 |
| Phase 4 — 4b (B15 thật, sau DỪNG 2) | R17/R18/R19 đòi "máy của chính người gửi": máy người khác / máy không tồn tại → **E5 `llm_layer_disabled`, 0 phiếu** (trước đây ra HITL). `reason_detail` mới: `no_valid_approver` (E5), `approval_target_unverified` (E5), `approver_no_longer_valid` (E5), `approver_lookup_error` (E2), `approver_sync_unavailable` (E2). Audit B15 `queued` (điểm log 5) có cột `approver_id`, `deadline`, `conflict_detected`; `detail`: `choice_reason` ∈ {`normal`, `conflict`, `no_valid_l1`}, `backup_approver_id`, `conflict_type`, `sla_minutes`, `recovered`. Seed mock 17 người (thêm `l1_lead`; `l1_01` báo cáo `l1_lead`) | Tỉ lệ HITL giảm, E5 tăng ở các ca R17–R19 — **đúng thiết kế, không phải lỗi**; fixture test của A1/A2 không được giả định "ngoài giờ → HITL". E2 do tra người duyệt lỗi **không** tính vào `e2_llm_count`. Dữ liệu điểm log 5 sẵn cho chỉ số xung đột lợi ích sau này (chưa nằm trong 5.1) |

---

## 2. Ranh giới — file được sửa

| Được tạo mới | Được sửa (diff nhỏ, một khối riêng) | Cấm đụng |
|---|---|---|
| `backend/app/monitor/**` | `backend/app/settings.py` (1–2 trường DSN monitor) | `backend/app/graph/**`, `risk/**`, `executor/**`, `tools/**`, `guard/**`, `llm/**`, `rag/**` |
| `backend/app/api/dashboard.py`, `backend/app/api/alerts.py` | `backend/app/db/session.py` (thêm engine `monitor`) | `config/policy.json`, `config/prompts/**` |
| Migration mới trong `backend/app/db/alembic/versions/` (chỉ view + index + GRANT) | `backend/app/main.py` (include router, gắn state) | `docs/spec/**` (spec do Tuấn Anh/Claude chat sửa) |
| `backend/tests/**/test_monitor_*.py`, `test_dashboard_*.py`, `test_alerts_*.py` | `backend/app/worker.py` (đăng ký job) | `frontend/**` (TV3) |
| | `backend/app/audit/alerts.py` (thêm hàm `ack`) | Migration đã có (`0001`–`0007`…) |
| | `docker-compose.yml` (env monitor cho backend, worker), `.env.example`, `.importlinter` (hợp đồng #2) | `.env` (không đọc, không in) |

Đụng file ngoài bảng → **dừng, ghi vào plan, hỏi Tuấn Anh**. Năm file "được sửa" ở cột giữa cũng là file Tuấn Anh đang sửa ở Phase 3 → giữ diff nhỏ, đặt ở khối riêng có chú thích `# M9`, rebase thường xuyên (mục 8.3).

---

## 3. Kiến trúc code M9 [Đề xuất, theo P9 §2–§3]

### 3.1. Cây thư mục

```
backend/app/monitor/
  __init__.py
  db.py          engine chỉ-đọc: dựng từ settings.monitor_database_url; THIẾU → không dựng (fail-closed, mục 4.1)
  views.py       tên view + hằng (V_LEAF, V_DECISIONS, V_L2_QUEUE) — một nguồn cho SQL
  window.py      cửa sổ thời gian thuần: đầu ngày/giờ/tuần theo múi giờ (Q-M9-2), trung vị 7 ngày
  queries/
    business.py  chỉ số dashboard nghiệp vụ (mục 5.1) — SQLAlchemy Core, chỉ SELECT
    ai.py        chỉ số AI/LLMOps (mục 5.2)
    rules_data.py  dữ liệu luật cần (đếm theo cửa sổ, sự kiện mới) — tách khỏi hàm luật
  metrics.py     dataclass kết quả + danh mục chỉ số ↔ nguồn (METRIC_SOURCES) để dựng `unavailable`
  rules.py       @rule(rule_id, every, *, audience=...) + hàm THUẦN (dữ liệu đã truy vấn, RuleContext) → list[AlertDraft]
  evaluator.py   chạy các luật đến hạn: đọc qua queries (engine monitor) → trả list[AlertDraft]; KHÔNG ghi
  drift.py       PSI (numpy) — chặng M9-7
backend/app/api/dashboard.py   GET /api/dashboard/business, /api/dashboard/ai (response_model khai báo)
backend/app/api/alerts.py      GET /api/alerts, POST /api/alerts/{id}/ack
backend/app/audit/alerts.py    + ack(alert_id, user_id) — M7 ghi, không phải M9
```

### 3.2. Luồng dữ liệu

```
(tầng nghiệp vụ ghi)  audit_logs · escalations · tickets · turns · spans · llm_calls · security_events · approvals
                                  │  chỉ SELECT, role app_monitor
                                  ▼
                   monitor/queries/*  ──►  api/dashboard.py  ──► TV3 (F5)
                                  │
                   monitor/evaluator.py ──► list[AlertDraft]   (thuần, không ghi)
                                  │
        worker.py (job 60 s / giờ / ngày / tuần) ──► audit.AlertWriter.raise_once ──► alerts (role app_rw)
                                                                                     │
                                         api/alerts.py (đọc qua monitor, ack qua audit) ◄┘
```

Không có mũi tên nào từ `monitor` về `graph`, `risk`, `executor`, `tools`, `approval` **[Chốt 17.9.2]**. Việc "ghi" duy nhất (tạo cảnh báo, ack) nằm ở `app.audit` (M7) và được **worker/route** gọi, không phải `app.monitor` gọi.

### 3.3. Lịch job trong worker [Đề xuất]

| Job | Chu kỳ | Luật |
|---|---|---|
| `monitor_rules_minute` | 60 giây (`max_instances=1`, `coalesce=True` như job cũ) | 2, 3, 4, 5, 6, 9, 10, 11, 15, 16 |
| `monitor_rules_hourly` | mỗi giờ | 14 |
| `monitor_rules_daily` | 02:00 giờ Việt Nam (Q-M9-2) | 1, 7, 12, 13 |
| `monitor_rules_weekly` | thứ Hai 02:00 (M9-7) | 8 |

Một luật lỗi (exception) **không** được làm hỏng luật khác trong cùng job: bắt theo từng luật, `log.exception` tên luật (không log dữ liệu), chạy tiếp. Job lỗi cả khối không được làm chết worker.

---

## 4. Luật bắt buộc

### 4.1. Chỉ đọc — ép bằng máy, không bằng lời hứa [Chốt 17.9.1]

1. Mọi truy vấn M9 chạy trên **engine `app_monitor`**. Thiếu `monitor_database_url` → route dashboard/alerts trả **503 `monitor_unavailable`**, job M9 không chạy (log một dòng cảnh báo). **Cấm rơi về engine `app_rw`** — rơi về là mất rào chỉ-đọc mà không ai biết.
2. `app.monitor` không `INSERT/UPDATE/DELETE`, không gọi `goto()`, không gọi API ghi, không đổi `policy.json`, không đổi ngưỡng.
3. Cảnh báo chỉ **báo người**. Không luật nào tự đổi hành vi hệ thống (vd luật 1 vượt 40% → không đổi `THRESHOLD_LOW/HIGH`).
4. M9 **không là nguồn dữ liệu cho M5**: không module nào ngoài `api`/`worker` import `app.monitor`.

### 4.2. Hợp đồng import (M9-0 siết thêm) [Chốt A0, 30/09/2026]

`.importlinter` #2 `monitor-read-only`: `app.monitor` không import `app.graph`, `app.executor`, `app.tools` (đã có) **+ `app.audit`, `app.approval`, `app.risk`, `app.api`, `app.guard`, `app.llm`, `app.rag`**.

Hợp đồng mới `monitor-only-api-worker` (bất biến 4.1.4 — chỉ `app.api` và `app.worker` được import `app.monitor`): nguồn **liệt kê tường minh mọi package/module cấp một của `app` trừ `api`, `monitor`, `main`, `worker`** — hiện là `app.approval`, `app.audit`, `app.auth`, `app.core`, `app.db`, `app.domain`, `app.eval`, `app.executor`, `app.graph`, `app.guard`, `app.llm`, `app.ml`, `app.notify`, `app.rag`, `app.risk`, `app.tools`, `app.settings`, `app.heartbeat`. Kèm test unit (kiểu `test_write_adapters_listed.py`): quét `backend/app/`, mọi package/module cấp một ngoài 4 cái được miễn phải có trong danh sách nguồn — thêm package mới mà quên khai báo → test đỏ; danh sách quét phải không rỗng. Bản đề xuất trước (chỉ chặn `graph`, `risk`, `executor`, `approval`) để hở `audit`, `auth`, `guard`, `tools`… — lệch bất biến 4.1.4 (Q-M9-A0-2).

Giá trị cấu hình M9 cần (vd `spend.cap_usd`) do worker đọc rồi truyền vào `RuleContext`.

### 4.3. Chỉ số [Chốt D-30]

- **Mọi chỉ số và mọi luật đếm ticket** đi qua `v_leaf` (`is_parent = false`). Test integration "câu 2 ý" là test bắt buộc.
- Nguồn chưa có node ghi → `null` + tên chỉ số trong mảng `unavailable` của response. **Không trả 0** (0 = "đã đo, không có ca" — sai sự thật, và che mất lỗ hổng).
- Tỉ lệ có mẫu số 0 → `null`, không chia cho 0, không trả 0.

### 4.4. Cảnh báo — ưu tiên không bỏ sót (FN) [Chốt nguyên tắc dự án]

1. Luật theo sự kiện (2, 3, 9, 11, 15, 16) quét lại **24 giờ gần nhất** mỗi lần chạy, không chỉ "từ lần trước". Worker chết 1 giờ vẫn không mất cảnh báo; chạy lại không sinh trùng nhờ khóa `(rule_id, subject, window_start)`.
2. `subject` luôn tường minh (`SYSTEM_SUBJECT` cho luật tổng hợp) — cột không có DEFAULT **[Chốt 2b-1]**.
3. `window_start` của luật theo sự kiện = **thời điểm sự kiện lấy từ DB**, không phải giờ chạy luật (chạy lại phải ra đúng khóa cũ).
4. Nghi ngờ giữa "báo thừa một lần" và "có thể bỏ sót" → chọn báo thừa, ghi lý do trong docstring.
5. `detail` của cảnh báo: chỉ id, số đếm, tên luật, ngưỡng — **không** văn bản yêu cầu, không token, không username thô khi không cần (`check_detail` đã chặn khóa nhạy cảm).

### 4.5. API

- `response_model` Pydantic khai báo cho mọi route mới (để TV3 sinh kiểu tự động — Nợ API #3 ở kế hoạch frontend).
- Thứ tự kiểm như route cũ: quyền → tài nguyên → 404/409. `POST /api/alerts/{id}/ack`: không có quyền → 403; không tồn tại → 404; đã ack → 409 (không ghi đè `acked_by` cũ).
- Tham số `from`/`to`: bắt buộc có múi giờ, `from < to`, khoảng ≤ 90 ngày → sai thì 422. Mặc định 7 ngày gần nhất.
- Không trả `redacted_request` dài: danh sách ca E3 cắt 200 ký tự, chỉ cho `dashboard:read:all`.

### 4.6. Quy trình (giống luồng chính)

Không đọc/in `.env`; không `--no-verify`; không nới sandbox; commit tiếng Việt không dấu, không dòng AI (hook `commit-msg` chặn); stage đích danh từng file; không commit/push khi chưa được bảo; không sửa `docs/spec/` (spec cần sửa thì ghi vào mô tả PR mục "Spec cần sửa"); test không gọi LLM thật.

---

## 5. Định nghĩa chỉ số

Cửa sổ `[from, to)`, tính trên ticket lá có `created_at` trong cửa sổ, trừ khi ghi khác.

### 5.1. Dashboard nghiệp vụ (`GET /api/dashboard/business`)

| Chỉ số | Công thức | Nguồn | Trạng thái |
|---|---|---|---|
| `automation_rate` | #lá `final_state = S_RESOLVED` **và** không có dòng `approvals` **và** không có dòng `escalations` / #lá | `tickets`, `approvals`, `escalations` | [Chốt P8 §6.2] |
| `escalation_rate_raw` | #lá có `exit_code` / #lá | `tickets` | [Chốt P8 §6.2] |
| `escalation_rate_weighted` | Σ trọng số nhóm × tỉ lệ escalate của nhóm (70/20/10) + độ nhạy 60/30/10 và 80/15/5. Nhóm 0 lá → `by_group = None`, trọng số chuẩn hoá lại trên các nhóm có lá; `None` chỉ khi cửa sổ 0 lá (Q-M9-A1-3) | Nhóm theo Q-M9-1; lá nhiều dòng điểm log 4 → nhóm nhạy nhất (Q-M9-A1-4) | [Chốt N3 công thức] / [Đề xuất cách chia nhóm] |
| `deflection_rate` | #lá `resolution_path = 'deflected'` / #lá | `tickets` | [Chốt P8 §6.2] |
| `approval_expired_count` | #lá `exit_code = 'E6'` | `tickets` | [Chốt P9 §5] |
| `decided_by_distribution` | đếm theo `decided_by` | `v_decisions` | [Chốt P9 §5] |
| `top_matched_rules` | top 10 `matched_rule_id` | `v_decisions` | [Chốt P9 §5] |
| `override_count` | số dòng `audit_logs` `step='OVERRIDE'`, `event='override_recorded'` của lá có `created_at` **của lá** trong cửa sổ — cùng lứa ticket với các chỉ số khác, **không** lọc theo thời điểm ghi đè (ghi đè muộn làm số kỳ cũ tăng thêm: chấp nhận). Một lá có thể nhiều dòng — mỗi người ghi đè một dòng; ghi đè không đổi `tickets` | `audit_logs` (4d, `e510a6e`) | **ready** từ 02/10 |
| `e1_split` | E1 tách 4 lý do theo **đúng giá trị `escalations.reason_detail`** (không đặt tên khác): `out_of_scope`, `multi_intent_not_enabled`, `intent_low_confidence`, `intent_not_enabled`; lý do khác → `other` (tổng = số E1). `intent_out_of_scope` là tên **event audit**, không phải `reason_detail` (Q-M9-A1-2b) | `escalations.reason_detail` (agent grep xác nhận) | [Chốt D-27, mở rộng theo 3f] |
| `e3_cases` | danh sách ca E3 (lỗ hổng KB): `ticket_id, intent, created_at, kb_version, request_excerpt` (≤ 200 ký tự) | `tickets`, `audit_logs` B9; `kb_version` = dòng audit gần nhất của lá có giá trị khác null, không có → `null` (Q-M9-A1-5) | [Chốt P9 §5] |

**Quy ước chung 5.1 (chốt 01/10 sau soát A1):** (a) mẫu số các **tỉ lệ theo kết cục ticket** (automation, escalation thô + trọng số, deflection) và `tokens_per_ticket` chỉ tính lá **đã kết thúc** (`final_state IS NOT NULL`); chỉ số theo lời gọi LLM / dòng audit / span ở 5.2 **không** lọc `final_state` (mỗi dòng đã có kết quả lúc ghi; lọc thì luật 12/13 đếm thiếu — Q-M9-A2-7) — ticket đang chạy dở chưa có `exit_code`, tính vào sẽ kéo tỉ lệ escalate xuống (luật 1 bỏ sót); (b) `automation_rate` theo đúng P8 §6.2, **gồm** ca deflected (đã tự giải quyết, không người) — trùng phần với `deflection_rate` là có chủ đích; (c) điểm log 4 = dòng `audit_logs` `step='B13/B14'` (cột `decided_by`, `policy_decision`, `risk_level`, `matched_rule_id`); bản kiểm lại ở B17 chỉ nằm trong `detail`, **không** đếm; (d) `decided_by_distribution`, `top_matched_rules` đếm **1 dòng / lá** — dòng nhạy nhất (Q-M9-A1-4), hòa thì dòng mới nhất; `decided_by` ở đây là cột của `audit_logs` (`rule`/`llm`), không phải `approvals.decided_by`; (e) 3 view tạo `WITH (security_invoker = true)` + GRANT SELECT `exit_code_priority` cho `app_monitor` — view không nâng quyền, REVOKE bảng gốc có hiệu lực; liệt kê cột tường minh (không `SELECT *`).

**Quyền:** `dashboard:read:all` → toàn bộ; `dashboard:read:own` (L1) → chỉ các chỉ số liên quan phiếu **giao cho mình** (Q-M9-5), trường không áp dụng → không trả (không trả 0, không trả `null`) — L1 nhận đúng 3 khóa liệt kê trong plan A1 (Q-M9-A1-6); quyền khác → 403.

### 5.2. Dashboard AI/LLMOps (`GET /api/dashboard/ai`, chỉ `dashboard:read:all`)

| Chỉ số | Công thức | Nguồn |
|---|---|---|
| `tokens_per_ticket` | Σ(`tokens_in` + `tokens_out`) / #lá có lời gọi LLM | `llm_calls → spans → turns → v_leaf` |
| `cost_per_day` | Σ `cost_usd` theo ngày (múi giờ Q-M9-2) | `llm_calls` |
| `latency_p95_by_step` | `percentile_cont(0.95)` của `duration_ms` theo `name`, `span_type='node'` | `spans` |
| `cache_hit_rate` | tỉ lệ `cache_hit = true` | `llm_calls` |
| `json_invalid_first_try_rate` | tỉ lệ `json_valid_first_try = false` trên dòng không NULL | `llm_calls` |
| `fallback_rate` | tỉ lệ `used_fallback = true` | `llm_calls` |
| `e2_llm_count` | #lá `exit_code='E2'` có `escalations.reason_detail` thuộc tập lý do LLM (agent liệt kê từ code, vd `llm_unavailable`, hằng một chỗ) | `tickets`, `escalations` |
| `e9_count` | #lá `exit_code = 'E9'` | `tickets` |
| `b2_llm_rate` | tỉ lệ lượt B2 **xuống L4**: tử = dòng có `layer_decided = 'llm'` **hoặc** `event = 'guard_unavailable'` (L4 được gọi rồi lỗi); mẫu = dòng có `layer_decided` khác NULL **hoặc** `guard_unavailable`; dòng `turn_budget_exceeded` ở ngoài cả hai (Q-M9-A2-5 — loại `guard_unavailable` thì LLM sập làm số tụt về 0, luật 12 im lặng) | `audit_logs` step `B2`, `detail->'screening'->>'layer_decided'` |
| `intent_filter_fallback_rate` | tỉ lệ B8 `intent_filter_fallback = true` | `audit_logs` step `B8` (D-23) |
| `b3_llm_rate`, `intent_model_version` | tỉ lệ dòng điểm log 1 có `detail.layer = 'llm'` trên mọi dòng điểm log 1 có `detail.layer` khác NULL — **đếm cả step `B3` và `B4`** (các ca E1 ghi ở `B4`); `intent_model_version` = `detail.model_version` gần nhất khác NULL (NULL khi ml-service `model_missing`) | `audit_logs` step `B3`, `B4` (`graph/nodes/b03_classify.py`) | **ready** từ 3f. Phase 3–4 giá trị ≈ 1,0 là đúng thực tế, không phải lỗi |
| `multi_intent_*` | thời gian con đầu tiên dừng → cha gửi tin; tin/lượt (= 1) | Phase 5 | `unavailable` |

**Phạm vi 5.2 (chốt 02/10, Q-M9-A2-3):** mọi chỉ số 5.2 nối về `v_leaf` (`llm_calls → spans → turns → v_leaf`; dòng audit theo `ticket_id`). `cost_per_day` vì vậy là chi phí của ticket lá, **không** phải tổng chi mà luật 14 đọc (toàn bảng `llm_calls`). Phase 3–4 hai số bằng nhau (chưa có ticket cha thật). `e2_llm_count` dùng `E2_LLM_REASONS = {llm_unavailable, llm_schema_error, screening_unavailable}`. `intent_filter_fallback_rate` so chuỗi `= 'true'`, không ép kiểu JSON. Khóa response: 14 (gồm `multi_intent_first_stop_to_reply_s`, `multi_intent_messages_per_turn` — pending).

### 5.3. `unavailable`

`metrics.METRIC_SOURCES` ghi mỗi chỉ số ↔ (bảng, step, event) nguồn. Chỉ số có nguồn đánh dấu `pending` → `null` + tên trong `unavailable`. Test: mọi khóa trong response có mặt trong `METRIC_SOURCES` và ngược lại (quét không rỗng, ≥ số kỳ vọng).

---

## 6. Luật cảnh báo

P9 §6 có 14 luật + việc Phase 7 "luật cho `finalize_failed_permanent`". Kế hoạch này thêm luật 16 (E7) — xem Q-M9-3.

| # | `rule_id` | Điều kiện | Nguồn | `subject` | `window_start` | Chu kỳ | `severity` / người nhận (tham số `audience` của `@rule`, không ghi `detail`) |
|---|---|---|---|---|---|---|---|
| 1 | `escalation_rate_high` | `escalation_rate_weighted` 7 ngày VN trọn `[d0 − 7 ngày, d0)`, `d0 = day_start(now)` (Q-M9-B2-1) > 0,40 | 5.1 | `""` | đầu ngày đánh giá | ngày | warning / manager |
| 2 | `injection_detected` | **mỗi lá `exit_code='E0'`** — B2 thật (`S_BLOCKED`) và B11/B19 `injection_in_reply` (`S_ESCALATED` E0) (Q-M9-B1-1) | `tickets` + `audit_logs` | `ticket_id` | `created_at` nhỏ nhất của `audit_logs` có `exit_code='E0'` của ticket (không lọc step) | 60 s | critical / manager |
| 3 | `password_bruteforce` | **đối soát**: mỗi `security_events.account_locked` có `detail.reason='threshold'` mà chưa có cảnh báo khớp (±60 s); chỉ xét sự kiện có `occurred_at ≤ now − 60 s` (Q-M9-B1-3) | `security_events`, `alerts` | qua `bruteforce_subject()` | `occurred_at` (chỉ khi chưa có cảnh báo khớp) | 60 s | critical / manager |
| 4 | `e9_spike` | #E9 giờ qua > 3 × trung vị theo giờ 7 ngày, tối thiểu 3 ca | `tickets` | `""` | đầu giờ | 60 s | warning / dev |
| 5 | `breaker_open` | có span tool `error = circuit_open` (Q-M9-4) — **nguồn pending** (span tool chưa ghi DB) | `spans` | tên tool | thời điểm span `circuit_open` đầu tiên của đợt | 60 s | warning / ops |
| 6 | `e6_spike` | #E6 giờ qua > 3 × trung vị 7 ngày, tối thiểu 3 | `tickets` | `""` | đầu giờ | 60 s | warning / manager |
| 7 | `reflex_approval` | một L1 có ≥ 3 phiếu trong ngày bị tính "xem < 5 giây" — xem cột nguồn | audit B16 (`detail.decided_without_view`, `decided_as`, `view_duration`) + `approvals.reminder_2_at`; **không** dùng `first_viewed_at` làm nguồn chính (cột chung chính/dự phòng — Việc treo 28 Phase 4). Phiếu tính "< 5 giây" khi không xem, xem < 5 giây, hoặc không xác định được người xem (`decided_as='primary'` và đã nhắc 2); bỏ nhánh `timeout`. Lọc quyết định của người bằng **cột `approval_result IN ('approved','rejected')`**, không lọc theo `event` (4d dừng 2: ca duyệt mà kế hoạch đã đổi ghi step `B16`, event `action_plan_changed_since_approval`, `approval_result='approved'` — lọc `event='approved'` thì bỏ sót) | `user_id` người quyết | đầu ngày | ngày | warning / manager — 4c đã merge (`b457e6e`) → **hết pending**, làm ở B2 |
| 8 | `drift` | PSI > 0,2 ở bất kỳ phân bố nào (M9-7) | 5.x | tên phân bố | đầu tuần | tuần | warning / manager |
| 9 | `refresh_reuse` | mỗi `refresh_reuse_detected` | `security_events` (`detail` chỉ có `revoked_sessions`) | `user_id` (Q-M9-8) | `occurred_at` | 60 s | critical / manager |
| 10 | `permission_denied_burst` | > 10 `permission_denied` trong 5 phút trượt, một người | `security_events` | `user_id`; không có → `username:<…>` qua `bruteforce_subject()` | đầu khung 5 phút chứa sự kiện thứ 11 | 60 s | warning / manager |
| 11 | `policy_saved` | mỗi `policy_saved` | `security_events` | `detail.version`; không có → `event:<id>` | thời điểm lưu | 60 s | info / manager |
| 12 | `b2_degraded` | `b2_llm_rate` của **ngày VN hôm trước** `[d0 − 1 ngày, d0)` (Q-M9-B2-1) > 0,30 | 5.2 | `""` | đầu ngày | ngày | warning / dev — **skipped tới khi có `injection-clf`** (Phase 5, `is_pending("b2_classifier")`; Q-M9-A2-8: Phase 3–4 L3 luôn `model_missing` → số ≈ 1,0, luật sẽ nổ mỗi ngày) |
| 13 | `b3_degraded` | `b3_llm_rate` của **ngày VN hôm trước** `[d0 − 1 ngày, d0)` (Q-M9-B2-1) > 0,30 (D-32) | 5.2 | `""` | đầu ngày | ngày | warning / dev — **skipped tới Phase 5** (Q-M9-9) |
| 14 | `llm_budget` | Σ `llm_calls.cost_usd` ≥ `warn_ratio` (0,8) × `cap_usd` (38) — `config/llm.yaml` `spend` | `llm_calls` | `""` | đầu ngày (Q-M9-6) | giờ | critical / dev, manager, ops ("cả nhóm" = cả 3 giá trị `Audience`) |
| 15 | `finalize_failed` | mỗi audit `finalize_failed_permanent` | `audit_logs` | `ticket_id` | thời điểm audit | 60 s | critical / dev |
| 16 | `execution_failed` **[Chốt Q-M9-3]** | mỗi lá `exit_code='E7'` — gồm mọi `reason_detail`: `exec_interrupted` (node B17, lượt API) và `execution_interrupted` (runner/boundary, worker recover) và các lỗi thực thi khác; ticket có `transaction_log` `begun` **luôn** ra E7, không E9 (Q-3h-10) | `tickets` + `audit_logs` | `ticket_id` | `created_at` nhỏ nhất của dòng `audit_logs` có `exit_code='E7'` của ticket (không lọc theo step — hai đường ghi khác step) | 60 s | critical / manager + ops; `detail` kèm `reason_detail` |

**Luật 3 — không viết lại cơ chế cũ.** Auth đã ghi cảnh báo lúc khóa, B1 ghi lại cùng khóa **[Chốt 2b-1]**. Luật 3 của M9 chỉ là **lưới an toàn**. Kiểm code 29/09: auth ghi cảnh báo với `lock_start = now` của auth, còn `security_events.occurred_at` lấy từ **một lần gọi đồng hồ khác** → hai giá trị lệch nhau (vài micro/mili giây) **[Chốt, kiểm code]**. Vì vậy **không** dựng khóa từ `occurred_at` rồi trông vào `ON CONFLICT` (sẽ ra khóa khác → cảnh báo trùng). Cách làm: với mỗi `account_locked` (threshold) trong 24 giờ, tìm dòng `alerts` có `rule_id='password_bruteforce'`, `subject = bruteforce_subject(user_id, username)` và `|window_start − occurred_at| ≤ 60 s`; có → bỏ qua; không có → draft `bruteforce_alert(..., lock_start=occurred_at, source="m9_reconcile")`. Test bắt buộc: auth đã ghi (lệch vài ms) → M9 chạy → vẫn **1** dòng; xóa dòng của auth trong test → M9 tạo đúng 1 dòng.

**Trung vị 7 ngày (luật 4, 6):** đếm theo từng giờ trong 168 giờ trước giờ đang xét (giờ không có ca = 0), lấy trung vị; điều kiện `count > 3 × median AND count ≥ 3`. Test ranh giới: đúng bằng ngưỡng → không báo; hơn 1 → báo.

**Hàm luật thuần:** `(data, ctx: RuleContext) -> list[AlertDraft]`, không I/O. `RuleContext` gồm `now` (từ `Clock` của app — một nguồn đồng hồ), `tz`, `cap_usd`, `warn_ratio`, trọng số N3. Test unit mỗi luật: **vượt**, **không vượt**, **đúng bằng ngưỡng**, và với luật theo sự kiện: **hai đối tượng cùng cửa sổ → 2 draft** (khóa cũ từng gộp thành 1 = FN).

---

## 7. Các chặng (mỗi chặng = 1 issue = 1 PR)

| Chặng | Nội dung | Phụ thuộc | Ước lượng [Suy luận] | Model agent |
|---|---|---|---|---|
| **M9-0** Chuẩn bị + kết nối chỉ-đọc | Máy + nhánh; `settings.monitor_database_url`; `Engines.monitor` (None khi thiếu); compose/.env.example; siết `.importlinter` (4.2); 503 fail-closed; khung package | — | 0,5 ngày | Opus |
| **M9-1** View + chỉ số nghiệp vụ | Migration: `v_leaf`, `v_decisions`, `v_l2_queue` + GRANT SELECT `app_monitor` + chỉ mục thiếu; `queries/business.py`; `metrics.py` + `METRIC_SOURCES`; test D-30 | M9-0 | 1 ngày | Opus |
| **M9-2** Chỉ số AI/LLMOps | `queries/ai.py` (5.2); p95 bằng SQL; `unavailable` cho nguồn chưa có | M9-1 | 1 ngày | Opus/Sonnet |
| **M9-3** API dashboard + cảnh báo | `api/dashboard.py`, `api/alerts.py`, `audit.alerts.ack`; quyền all/own; `response_model`; gửi TV3 schema | M9-1, M9-2 | 1 ngày | Opus |
| **M9-4** Khung luật + luật theo sự kiện | `rules.py` (`@rule`, registry), `evaluator.py`, `RuleContext`, `window.py`; job 60 s trong worker; luật 2, 3, 9, 10, 11, 15, 16 | M9-1 | 1 ngày | Opus |
| **M9-5** Luật tổng hợp | Luật 1, 4, 5, 6, 7, 12, 13, 14; job giờ/ngày; test ranh giới "luật 1 vượt → `policy_versions` không đổi, đúng 1 dòng `alerts`" | M9-4, M9-2 | 1,5 ngày | Opus |
| **M9-6** Health + hiệu năng + nghiệm thu | `/api/health` thêm `llm` (không gọi LLM thật — Q-M9-7) + cache 10 giây; test 10.000 ticket < 2 giây/truy vấn; chạy bảng nghiệm thu P9 §8 | M9-3, M9-5 | 0,5–1 ngày | Opus/Sonnet |
| **M9-7** Drift (Nên có) | `drift.py` PSI (numpy); luật 8; job tuần; test PSI tính tay | M9-5 | 0,5–1 ngày | Sonnet |

### 7.0. Ánh xạ gói kỹ thuật → chặng của từng người

| Gói | Chặng | Người |
|---|---|---|
| M9-0 (+ `window.py`, `views.py`) | A0 | Lưu Dương |
| M9-1 | A1 | Lưu Dương |
| M9-2 | A2 | Lưu Dương |
| M9-3 | A3 | Lưu Dương |
| M9-6 | A4 | Lưu Dương |
| Phần thuần của M9-4 (`rules.py`, `evaluator.py`, tiện ích trung vị) | B0 | Tạ Duy Anh |
| M9-4 (7 luật sự kiện + job 60 s) | B1 | Tạ Duy Anh |
| M9-5 | B2 | Tạ Duy Anh |
| M9-7 | B3 | Tạ Duy Anh |

Thẻ việc chi tiết từng chặng, thứ tự merge, hợp đồng hàm: `claude/ke-hoach-m9-chia-viec.md` mục 3–6. Bảng "Đạt khi" dưới đây giữ theo gói M9-x.

### 7.1. Đạt khi — từng chặng

| Chặng | Đạt khi |
|---|---|
| Mọi chặng | `make lint` xanh (ruff, mypy, import-linter, gitleaks); `make test` xanh; không file ngoài bảng mục 2 và không file thuộc chủ khác (file chia việc mục 2); PR có "Input/Output", "Spec cần sửa", danh sách test mới |
| M9-0 | Thiếu DSN monitor → `GET /api/dashboard/business` = 503 (test), **không** dùng engine `app_rw` (test kiểm `current_user` = `app_monitor` khi có DSN); import-linter đỏ khi thêm thử `from app.audit import alerts` vào `app.monitor` (thử rồi hoàn nguyên) |
| M9-1 | Test "câu 2 ý" (1 cha + 2 con): mọi đếm ra 2, không 3; `app_monitor` SELECT được 3 view; `INSERT` vào view/bảng dưới `app_monitor` → permission denied; migration up/down sạch, `alembic heads` = 1 |
| M9-2 | Mỗi chỉ số có test dữ liệu tính tay; mẫu số 0 → `null`; chỉ số `pending` nằm trong `unavailable`; test quét `METRIC_SOURCES` ↔ khóa response khớp, không rỗng |
| M9-3 | Manager 200 toàn bộ; L1 200 phần của mình (fixture 2 L1: không thấy số của người kia); L2/nhân viên 403; ack: 200 → 409 lần 2 (`acked_by` giữ người đầu) → 404 id lạ; `openapi.json` có schema các route mới |
| M9-4 | Mỗi luật ≥ 3 test (vượt / không / bằng ngưỡng) + test 2 đối tượng → 2 draft; chạy job 2 lần → không sinh trùng; một luật ném lỗi → luật khác vẫn chạy; luật 3 đối soát không sinh dòng thứ 2 |
| M9-5 | Như M9-4 cho 8 luật; test ranh giới luật 1 (`policy_versions` không đổi, đúng 1 dòng `alerts`); trung vị với giờ trống = 0 |
| M9-6 | `/api/health` có `llm`; gọi 2 lần trong 10 giây → kiểm phụ thuộc chỉ 1 lần; 10.000 ticket giả: mỗi truy vấn dashboard < 2 giây (in thời gian đo); bảng nghiệm thu P9 §8 đủ dòng |
| M9-7 | PSI trên 2 phân bố tính tay khớp (sai số 1e-6); bin rỗng xử lý bằng epsilon cố định có ghi lý do; luật 8 test vượt/không |

**Mutation (theo mục 6 của `claude/ngu-canh-phien-review.md`):** bắt buộc cho M9-0 (rơi về `app_rw`), M9-1 (bỏ lọc `is_parent`), M9-3 (bỏ kiểm own/all, ack ghi đè), M9-4 (bỏ `subject`, `window_start` = giờ chạy, lookback 60 s thay 24 h, luật 3 tự dựng khóa). Agent nói trước test nào đỏ ở assert nào → chạy → hoàn nguyên. Mutation cần Docker → người làm chặng tự chạy.

---

## 8. Quy trình làm việc cho người làm (Dương / Duy Anh) + agent

### 8.1. Vòng một chặng

1. **Mở phiên Claude Code mới** cho chặng (mỗi chặng một phiên), dán lời mở ở mục 13.
2. Agent đọc issue + tài liệu → **lập plan** (Plan Mode, chưa code): file tạo/sửa, test, mutation dự kiến, câu hỏi `Q-M9-x-…`.
3. Người làm **dán plan vào comment của issue** → báo Tuấn Anh (và người kia nếu plan đụng hợp đồng hàm). Tuấn Anh (có Claude chat hỗ trợ) trả lời "Duyệt" hoặc sửa, chốt câu hỏi ngay trong issue.
4. Agent code → `make lint` → unit → mutation logic → người làm chạy `make test` và mutation cần Docker.
5. Agent rebase lên `origin/dev-tuananh` (8.3), push nhánh của mình (`dev-luuduong` / `dev-duyanh`), mở PR vào `dev-tuananh`, mô tả PR theo mẫu (8.2), rồi **dừng**.
6. CI xanh → người kia review chéo ("Peer OK") → Tuấn Anh review theo mục 9 → merge đúng thứ tự (file chia việc mục 4). Có yêu cầu sửa → quay lại bước 4 **cùng phiên**.
7. Merge xong → đóng issue, tick ô trong issue epic, mở phiên mới cho chặng sau.

### 8.2. Mẫu mô tả PR

```
Closes #<số issue>
## Làm gì (input → output)
## File tạo / sửa (đối chiếu bảng mục 2)
## Test mới + kết quả (make lint, make test: số passed)
## Mutation: mã | đột biến | test đỏ ở đâu
## Câu hỏi đã chốt trong issue
## Spec cần sửa (Tuấn Anh cập nhật docs/spec)
## Chưa làm / để chặng sau
```

### 8.3. Git

- Nhánh làm: `dev-luuduong` (Dương), `dev-duyanh` (Duy Anh) — **chốt 01/10/2026**: dùng lại hai nhánh sẵn có thay cho `m9-*` dự kiến trước. Đầu mỗi chặng đưa nhánh về `origin/dev-tuananh` (`git fetch origin && git reset --hard origin/dev-tuananh`, chỉ khi không còn thay đổi chưa commit). **Giao hàng bằng PR vào `dev-tuananh`** (A0/B0 đã đẩy thẳng nhánh — từ A1/B1 dùng PR). Quy tắc hai người (chủ file, thứ tự merge, rebase sau mỗi merge): file chia việc mục 2, 4, 8.
- **Trước mỗi PR:** `git fetch origin && git rebase origin/dev-tuananh`. Xung đột ở `settings.py`, `main.py`, `worker.py`, `docker-compose.yml`, `.env.example` → giữ cả hai phía, chạy lại `make test`.
- **Migration:** chỉ **Dương** viết migration M9. File M9 đặt `down_revision` = head hiện tại của `dev-tuananh`. Sau mỗi rebase: `uv run alembic heads` phải ra **đúng 1 head**; ra 2 → sửa `down_revision` trỏ vào head mới của Tuấn Anh. Không đổi số của migration đã merge.
- Commit tiếng Việt không dấu, tác giả là chính người làm, không dòng AI. Không force-push lên `dev-tuananh`.

### 8.4. Khi kẹt

Hỏi trong comment issue, **kèm**: đã đọc mục nào của file này / P9, đã thử gì, 2 phương án + đánh đổi. Mâu thuẫn trong spec → dừng, ghi vào issue, không tự chọn một bên **[Chốt CLAUDE.md]**.

---

## 9. Checklist review cho Tuấn Anh (~15–20 phút mỗi PR)

1. `git diff --stat origin/dev-tuananh...` → không file ngoài bảng mục 2.
2. `grep -rn "insert\|update(\|delete(\|goto\|\.execute(text" backend/app/monitor` → không lệnh ghi; SQL thô chỉ `SELECT`/`CREATE VIEW` trong migration.
3. Engine dùng trong route/job M9 là `engines.monitor`; không nhánh nào rơi về `engines.main`.
4. Mọi đếm ticket đi qua `v_leaf` (grep `FROM tickets` trong `monitor/` → rỗng, trừ định nghĩa view).
5. Luật mới: `subject` tường minh; `window_start` lấy từ DB; lookback 24 giờ cho luật sự kiện; test 2 đối tượng → 2 draft.
6. Chỉ số chưa có nguồn nằm trong `unavailable`, không trả 0.
7. `.importlinter` không bị nới; `make lint` xanh trong CI.
8. Migration: `alembic heads` = 1; chỉ view/index/GRANT.
9. Chạy tay 1 ca "Đạt khi" của chặng (hoặc xem output người làm dán).

Người review không phải người làm → đúng nguyên tắc cổng **[Chốt]**.

---

## 10. Câu hỏi cần Tuấn Anh chốt (mặc định = đề xuất; không trả lời thì agent làm theo mặc định)

| Mã | Câu hỏi | Đề xuất mặc định | Lý do |
|---|---|---|---|
| Q-M9-1 | Vận hành live không có nhãn gold — chia 3 nhóm N3 theo gì? | Theo điểm log 4: `allow`/`risk_level=low` hoặc không tới M5 (info, E0–E4) → thường ngày; `approval_required`/`medium` → cần duyệt; `deny`/`high` → nhạy cao. Trọng số 70/20/10 là hằng một chỗ (`monitor/metrics.py`). `decision` và `risk_level` lệch nhau, hoặc lá có nhiều dòng điểm log 4 → lấy nhóm **nhạy nhất** (Q-M9-A1-4) | Dùng lại dữ liệu đã log, không thêm nhãn; khi M8 có nhãn thì so hai cách |
| Q-M9-2 | "Ngày" theo múi giờ nào? | `Asia/Ho_Chi_Minh` cho mọi cửa sổ ngày/tuần; lưu và so sánh vẫn UTC; job ngày 02:00 giờ VN | Người đọc dashboard ở VN; một nguồn múi giờ |
| Q-M9-3 | Thêm luật 16 `execution_failed` (E7)? | **Có** | B20 bước 6 yêu cầu cảnh báo E0/E7/E9; 14 luật hiện có phủ E0 (luật 2), E9 (luật 4) nhưng **không phủ E7** — E7 có ưu tiên "rất cao" → thiếu là FN |
| Q-M9-4 | Luật 5 lấy "breaker mở" từ đâu (breaker nằm trong bộ nhớ tiến trình)? | Kiểm 29/09: `tools/registry.py::_span` **chỉ ghi log**, chưa ghi bảng `spans`. Duy Anh viết luật trên hợp đồng dự kiến (span `span_type='tool'`, `status='error'`, `attributes.error='circuit_open'`; "đợt" = chuỗi cách nhau < 60 s) + test fixture, để **pending**. Tuấn Anh cho registry ghi span tool khi tiện (ngoài phạm vi M9) | Không đụng `tools/` (cấm); luật sẵn sàng khi nguồn có |
| Q-M9-5 | `dashboard:read:own` của L1 là phiếu nào? | Phiếu có `approvals.approver_id = user_id` (giao cho mình), kể cả hết hạn | "Phần mình duyệt" gồm cả phiếu mình để hết hạn — đó là thứ L1 cần thấy |
| Q-M9-6 | Luật 14 báo lại bao lâu một lần khi đã vượt 80%? | Một lần mỗi ngày (`window_start` = đầu ngày), đánh giá mỗi giờ | Nhắc hằng ngày đủ; mỗi giờ thành nhiễu |
| Q-M9-9 | Luật 13: nguồn có từ 3f nhưng Phase 3–4 **mọi** câu B3 đều xuống LLM (chưa có cascade model → LLM, Phase 5) → `b3_llm_rate` ≈ 1,0 → luật báo mỗi ngày | Luật 13 **skipped** với lý do `cascade_not_enabled` tới Phase 5: `METRIC_SOURCES` có khóa `b3_cascade` trạng thái `pending`, luật kiểm `is_pending("b3_cascade")`. Chỉ số `b3_llm_rate` trên dashboard vẫn hiện (ready) | Cảnh báo báo mỗi ngày một điều đã biết = nhiễu, làm người ta bỏ qua cảnh báo thật. Không phải FN: chưa có model để "xuống cấp" |
| Q-M9-8 | Luật 9 `refresh_reuse`: `subject` là gì? P9 ghi `token_family_id` nhưng `security_events.detail` chỉ có `revoked_sessions` (kiểm code 29/09) | `subject = user_id`, `window_start = occurred_at` → mỗi sự kiện một cảnh báo; **không** sửa auth để thêm trường | Không đụng `auth/`; mỗi lần dùng lại token đã là sự cố riêng, không cần gộp theo họ token |
| Q-M9-7 | `/api/health` kiểm LLM thế nào? | Không gọi LLM thật: báo `llm: scripted` / `real:configured` / `real:missing_pricing` / `spend_cap_reached` từ cấu hình gateway + trần chi; chỉ **báo**, không đổi mã 200/503 (như `kb`) | Ping LLM thật tốn tiền và ngân sách < 1 triệu đồng; health gọi mỗi 10 giây |
| Q-M9-B2-1 | Luật chạy ở job ngày (1, 12, 13) gọi chỉ số với cửa sổ nào? Job chạy 02:00 giờ VN | Cửa sổ dữ liệu **kết thúc ở `d0 = day_start(ctx.now)`**: luật 12/13 `[d0 − 1 ngày, d0)`, luật 1 `[d0 − 7 ngày, d0)`. `window_start` (khóa chống trùng) vẫn là `d0`. Mốc ngày lấy bằng `window.day_start` | `[d0, now)` chỉ có 2 giờ sau nửa đêm → gần như không có lá → chỉ số `None` → luật không bao giờ nổ (bỏ sót). Trọn ngày còn cho kết quả không đổi khi chạy lại |

---

## 11. Phối hợp

| Với | Việc | Khi |
|---|---|---|
| Dương ↔ Duy Anh | Chủ file, hợp đồng hàm, thứ tự merge, review chéo, cổng chéo | File chia việc mục 2–9 |
| TV3 (frontend F5) | M9-3 mở PR → gửi TV3 `openapi.json` phần `/api/dashboard/*`, `/api/alerts*` để thay kiểu viết tay trong `contracts-tam.ts`, xóa handler MSW `dashboard`, `alerts` | Sau merge M9-3 |
| Tuấn Anh (Phase 3–4) | Khi luồng chính thêm event/trường mà M9 đang `unavailable` (điểm log 4, ghi đè, B3 LLM, nhiều ý) → Tuấn Anh ghi vào issue epic; chỉ số → Dương, luật → Duy Anh mở chặng nhỏ "nối nguồn" | Theo phase |
| Tuấn Anh (spec) | Mục "Spec cần sửa" trong PR → Tuấn Anh/Claude chat cập nhật `P9-monitor-M9.md` (mục 5.1 "Chốt khi hiện thực") | Sau mỗi merge |

---

## 12. Chuẩn bị máy (Dương làm ở A0; Duy Anh ở B0 — Duy Anh đã dựng stack ở cổng 2 nên chỉ cần từ bước 3, nhánh `dev-duyanh`)

1. Cài: Git, Docker (Linux/WSL 2 hoặc colima trên Mac), `uv`, `gitleaks`, `gh`, Claude Code.
2. `git clone https://github.com/17tuanphamanh/AIP_FA26_G8.git && cd AIP_FA26_G8`
3. `git fetch origin && git switch dev-luuduong && git reset --hard origin/dev-tuananh` (Duy Anh: `dev-duyanh`)
4. `git config core.hooksPath .githooks` (không bật = hook không gác).
5. Tạo `.env` **riêng** từ `.env.example` (sinh bí mật ngẫu nhiên; `APP_ENV=dev`, `LLM_BACKEND=scripted`). **Không** xin `.env` của Tuấn Anh qua chat.
6. `uv sync` → `make up` → `make seed` → `make test` xanh **trước khi** sửa gì (ghi số test vào comment issue M9-0 làm mốc).
7. Mở `claude` ở thư mục repo một lần, đồng ý *trust* để hook và quyền trong `.claude/` chạy.
8. Đọc: file này, `docs/spec/build/nen-tang/P9-monitor-M9.md`, `docs/spec/CLAUDE.md`, `CLAUDE.md` gốc repo.

---

## 13. Lời mở phiên cho agent

**Lời mở phiên chặng riêng cho từng người (có luật chủ file, hợp đồng): file chia việc mục 12 — dùng bản đó.** Khối dưới là bản chung cũ, giữ để tham khảo.

**Mở phiên chặng (thay `<M9-x>` và `<số issue>`):**
```
Đọc CLAUDE.md, docs/spec/CLAUDE.md, rồi docs/spec/claude/ke-hoach-m9-monitor.md (đọc hết, đặc biệt mục 2, 4, 6, 7, 10) và docs/spec/build/nen-tang/P9-monitor-M9.md. Việc của phiên này: chặng <M9-x>, GitHub issue #<số issue> (đọc bằng: gh issue view <số issue>).
Tôi là <Lưu Dương | Tạ Duy Anh>, làm trên nhánh <dev-luuduong | dev-duyanh>; Tuấn Anh review và merge.
Luật: không đọc/in .env; không --no-verify; không nới sandbox; chỉ sửa file trong bảng mục 2 (ngoài bảng thì dừng và hỏi); không sửa docs/spec/; M9 chỉ đọc (engine app_monitor, không fallback app_rw); mọi đếm ticket qua v_leaf; lệnh cần Docker thì báo tôi chạy; stage đích danh; không commit/push khi tôi chưa bảo; commit tiếng Việt không dấu, không dòng AI.
Bước 1: lập plan (Plan Mode, chưa code): file tạo/sửa, test (gồm ca ranh giới), mutation dự kiến (đột biến → test nào đỏ, assert nào), câu hỏi Q-M9-x-… kèm đề xuất. Trình bày plan dạng markdown để tôi dán vào issue. Chưa code tới khi tôi báo "Duyệt".
```

**Khi Tuấn Anh đã duyệt plan:**
```
Plan <M9-x> đã duyệt. Chốt: <dán các chốt từ issue>. Làm: code → make lint → unit → mutation logic (báo từng kết quả). Lệnh cần Docker (make test, mutation SQL) thì đưa tôi từng lệnh. Chưa commit.
```

**Khi test xanh, chuẩn bị PR:**
```
make test xanh (<số> passed). Rebase lên origin/dev-tuananh (git fetch origin && git rebase origin/dev-tuananh), kiểm alembic heads = 1, chạy lại make lint. Stage đích danh (kiểm không có .env*, __pycache__, .pyc, settings.local.json), commit, push nhánh của tôi. Soạn mô tả PR theo mẫu mục 8.2 để tôi mở PR vào dev-tuananh (nhánh của tôi: dev-luuduong hoặc dev-duyanh). Rồi DỪNG.
```

---

## 14. Nhật ký thay đổi

| Ngày | Thay đổi |
|---|---|
| 02/10/2026 | **v1.17** — Q-M9-B2-1: luật ngày (1, 12, 13) đo trên ngày VN trọn kết thúc ở `day_start(now)` (job chạy 02:00 VN, cửa sổ `[đầu ngày, now)` gần như rỗng); D5 của PR #24 đạt trên stack (`fe51980` + `87dce5b`: `nháp=7 ghi=7 trùng=0 lỗi=0 luật_lỗi=0`); review PR #26 (A2) ghi ở file chia việc; luật 7 lọc theo cột `approval_result` (tin Phase 4, 4d dừng 2) |
| 02/10/2026 | **v1.16** — `override_count` chốt cửa sổ theo `created_at` của lá; Q-M9-A3-1: `/api/alerts` không ẩn theo `audience` (file chia việc, thẻ A3) |
| 02/10/2026 | **v1.15** — 4d dừng 1 đã merge (`e510a6e`): nguồn ghi đè có thật → `override_count` ready (Dương lật `PENDING_SOURCES`, viết truy vấn + test); review PR #24 (B1 GĐ2) ghi ở file chia việc |
| 02/10/2026 | **v1.14** — chốt plan A2 (#9): 5.2 mọi chỉ số qua `v_leaf` (D-30, bất biến 13); `b2_llm_rate` tính cả `guard_unavailable`; `E2_LLM_REASONS` gồm `screening_unavailable`; 5.1(a) chỉ áp cho tỉ lệ theo kết cục ticket; luật 12 skipped tới Phase 5 (`b2_classifier`); **việc treo Phase 5:** lời gọi LLM và dòng B2/B3 của ticket cha bị loại khỏi chỉ số 5.2 → `cost_per_day` < tổng chi luật 14 — cần quyết phạm vi D-30 khi bật nhiều ý |
| 01/10/2026 | **v1.13** — soát song song (3 agent): quy ước chung 5.1 (mẫu số chỉ lá đã kết thúc, `automation_rate` gồm deflected, điểm log 4 = step `B13/B14`, đếm 1 dòng/lá, view `security_invoker`); luật 7 hết pending (4c merge); bảng mục 6: `audience` thay `detail.audience`, luật 3 chờ 60 s, luật 10/11 subject dự phòng, luật 14 = dev/manager/ops |
| 01/10/2026 | **v1.12** — tin Phase 4 (4d): `audit_check` đọc qua `app_monitor` → M9 không REVOKE SELECT `audit_logs`/`tickets`; 4 cột `audit_logs` (`confidence`, `query`, `success`, `action_plan_hash_matched`) chưa ghi → đọc từ `detail` (Việc treo 31) |
| 01/10/2026 | **v1.11** — Q-M9-A1-2b: khóa `e1_split` = giá trị `reason_detail` nguyên văn (`out_of_scope`, không phải tên event `intent_out_of_scope`); không ánh xạ tên |
| 01/10/2026 | **v1.10** — tin Phase 4 sau 4c: Phase 4 (cả 4d) không có migration, migration sau Phase 4 nối sau M9; mục 1.4 thêm chi tiết dòng `OVERRIDE` (4d) và lưu ý fixture R17–R19 → E5 |
| 01/10/2026 | **v1.9** — chốt plan A1 (#8): migration M9 `0008_monitor_views` trỏ `0007` (Phase 4 không có migration); `weighted` chuẩn hoá lại khi nhóm 0 lá; lá nhiều dòng điểm log 4 → nhóm nhạy nhất; `e1_split` 4 lý do + `other`; `kb_version` dòng gần nhất khác null; L1 own 3 khóa |
| 01/10/2026 | **v1.8** — luật 7 theo 4c: `first_viewed_at` là cột chung chính/dự phòng → nguồn chính là audit B16; ca mơ hồ tính là < 5 giây (ưu tiên không bỏ sót) |
| 01/10/2026 | **v1.7** — mục 1.4: Phase 4 không sửa `worker.py` (nhắc duyệt trong `WorkerJobs.scan_deadlines`) |
| 01/10/2026 | **v1.6** — chốt plan B1: luật 2 mọi E0; luật 15 không lọc lá; người nhận khai báo trong `@rule(..., audience=...)` thay cho `detail.audience` (cột người nhận ở bảng mục 6 là nguồn cho tham số này) |
| 01/10/2026 | **v1.5** — nhánh làm việc chốt là `dev-luuduong`, `dev-duyanh` (thay `m9-*`); từ A1/B1 giao bằng PR vào `dev-tuananh` |
| 01/10/2026 | **v1.4** — theo tin Phase 4: `override_count` từ step `OVERRIDE` (4d); `first_viewed_at` NULL tới 4c; 4b đổi số liệu (R17–R19 → E5 `llm_layer_disabled`, 5 `reason_detail` mới, điểm log 5 có cột mới, seed 17 người) |
| 30/09/2026 | **v1.3** — đối chiếu lại code tại `5d0a990` (Phase 3 đóng): `b3_llm_rate` ready (đếm step B3 + B4, `detail.layer`), luật 13 skipped tới Phase 5 (Q-M9-9 mới); luật 2 nguồn B2 thật; luật 16 gồm `exec_interrupted` + `execution_interrupted`, window từ `audit_logs.exit_code`; luật 7 pending tới 4c, `decided_without_view` tính là < 5 s; mục 1.4 phối hợp Phase 4 |
| 30/09/2026 | **v1.2** — chốt plan A0 (issue #7): mục 4.2 hợp đồng `monitor-only-api-worker` liệt kê mọi package trừ `api`/`monitor`/`main`/`worker` + test chống quên (Q-M9-A0-2); body 503 = `{"detail": "monitor_unavailable"}` (Q-M9-A0-1) |
| 29/09/2026 | **v1.1** — chia cho hai người: Lưu Dương (luồng A) + Tạ Duy Anh (luồng B), chi tiết ở `claude/ke-hoach-m9-chia-viec.md`; mục 7.0 ánh xạ gói → chặng; kiểm lại nguồn: span tool chưa ghi DB (luật 5 pending, Q-M9-4 sửa), `refresh_reuse_detected` không có `token_family_id` (Q-M9-8 mới), `lock_start` của auth ≠ `occurred_at` (luật 3 đối soát ±60 s); migration chỉ Dương viết |
| 29/09/2026 | v1.0 — Tạo file: kiểm repo tại `3f33ab2`, 8 chặng M9-0…M9-7, định nghĩa chỉ số, 16 luật (thêm luật 15 theo việc Phase 7 đã ghi, đề xuất luật 16 cho E7), ranh giới file, quy trình PR, câu hỏi Q-M9-1…7 |
