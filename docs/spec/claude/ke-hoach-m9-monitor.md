# Kế hoạch giao việc M9 — Tầng Monitor (backend)

*Tạo 29/09/2026. Người làm: **Lưu Dương** (luồng A — dashboard) và **Tạ Duy Anh** (luồng B — cảnh báo), mỗi người dùng coding agent Claude Code. **Ai làm gì, thứ tự, chủ file, hợp đồng giữa hai người: `claude/ke-hoach-m9-chia-viec.md`** — file này là tham chiếu kỹ thuật chung. Người review + merge: **Tuấn Anh** (Claude chat hỗ trợ review). Nguồn đã chốt: `build/nen-tang/P9-monitor-M9.md` (v1.3), `huong-dan-xay-dung-he-thong-2.md` §16.3–16.5, §17.1, §17.5, §17.9; `build/02-cac-tang-he-thong.md` T5; `build/nen-tang/P8-danh-gia-M8.md` §6.2 (công thức chỉ số); `build/decisions.md` §1.4 (N3). Code đối chiếu: repo `dev-tuananh` tại commit `3f33ab2` (Phase 3 chặng 3f, dừng 1).*

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

`backend/app/monitor/` hiện **chỉ có `README.md` + `__init__.py`**. Chưa có: engine `app_monitor` trong app (settings chưa có DSN monitor; compose chưa truyền `PG_MONITOR_PASSWORD` cho backend/worker), view SQL, truy vấn chỉ số, route `/api/dashboard/*`, `/api/alerts`, luật cảnh báo, job worker.

### 1.3. Nguồn dữ liệu chưa được node nào ghi (vì luồng chính mới ở Phase 3)

| Nguồn | Phase tạo ra | M9 xử lý |
|---|---|---|
| Điểm log 4 (B12–B14: `decided_by`, `policy_decision`, `risk_level`, `matched_rule_id`, `calibrated_prob`) | Phase 4–6 | Cột đã có trong `audit_logs` → viết view + test bằng fixture |
| Phiếu duyệt thật, `first_viewed_at` (route xem phiếu) | Phase 4 | Luật 7 test bằng fixture |
| Ghi đè L1 | Phase 4 | Chỉ số `override_count` → `unavailable` tới khi có event |
| B3 xuống LLM (đường LLM của model intent, D-32) | 3f/3g (đang làm) | Luật 13 → hỏi Tuấn Anh tên trường khi 3f commit |
| Ticket nhiều ý (D-31) | Phase 5 | Chỉ số nhiều ý → `unavailable` |
| Span tool (bảng `spans`, `span_type='tool'`) — `tools/registry.py::_span` hiện **chỉ ghi log một dòng**, không ghi DB (kiểm 29/09) | Chưa xếp (Tuấn Anh quyết, Q-M9-4) | Luật 5 → pending, test bằng fixture |
| `policy_saved` | Phase 7 | Luật 11 test bằng fixture `security_events` |

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
  rules.py       @rule(id, every) + hàm THUẦN (dữ liệu đã truy vấn, RuleContext) → list[AlertDraft]
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

### 4.2. Hợp đồng import (M9-0 siết thêm) [Đề xuất]

`.importlinter` #2 `monitor-read-only`: `app.monitor` không import `app.graph`, `app.executor`, `app.tools` (đã có) **+ `app.audit`, `app.approval`, `app.risk`, `app.api`, `app.guard`, `app.llm`, `app.rag`**. Thêm hợp đồng mới: `app.graph`, `app.risk`, `app.executor`, `app.approval` **không import `app.monitor`** (bất biến 4.1.4). Giá trị cấu hình M9 cần (vd `spend.cap_usd`) do worker đọc rồi truyền vào `RuleContext`.

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
| `escalation_rate_weighted` | Σ trọng số nhóm × tỉ lệ escalate của nhóm (70/20/10) + độ nhạy 60/30/10 và 80/15/5 | Nhóm theo Q-M9-1 | [Chốt N3 công thức] / [Đề xuất cách chia nhóm] |
| `deflection_rate` | #lá `resolution_path = 'deflected'` / #lá | `tickets` | [Chốt P8 §6.2] |
| `approval_expired_count` | #lá `exit_code = 'E6'` | `tickets` | [Chốt P9 §5] |
| `decided_by_distribution` | đếm theo `decided_by` | `v_decisions` | [Chốt P9 §5] |
| `top_matched_rules` | top 10 `matched_rule_id` | `v_decisions` | [Chốt P9 §5] |
| `override_count` | số lần L1 ghi đè | event Phase 4 | `unavailable` tới Phase 4 |
| `e1_split` | E1 tách `out_of_scope` / `intent_low_confidence` | `escalations.reason_detail` (agent grep xác nhận) | [Chốt D-27] |
| `e3_cases` | danh sách ca E3 (lỗ hổng KB): `ticket_id, intent, created_at, kb_version, request_excerpt` (≤ 200 ký tự) | `tickets`, `audit_logs` B9 | [Chốt P9 §5] |

**Quyền:** `dashboard:read:all` → toàn bộ; `dashboard:read:own` (L1) → chỉ các chỉ số liên quan phiếu **giao cho mình** (Q-M9-5), trường không áp dụng → không trả; quyền khác → 403.

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
| `b2_llm_rate` | tỉ lệ lượt B2 có `layer_decided = 'llm'` (L4) | `audit_logs` step `B2`, trường sàng lọc trong `detail` (agent xác nhận đường JSON) |
| `intent_filter_fallback_rate` | tỉ lệ B8 `intent_filter_fallback = true` | `audit_logs` step `B8` (D-23) |
| `b3_llm_rate`, `intent_model_version` | tỉ lệ B3 xuống LLM; phiên bản model đang chạy | audit B3 (3f) | `unavailable` tới khi 3f commit |
| `multi_intent_*` | thời gian con đầu tiên dừng → cha gửi tin; tin/lượt (= 1) | Phase 5 | `unavailable` |

### 5.3. `unavailable`

`metrics.METRIC_SOURCES` ghi mỗi chỉ số ↔ (bảng, step, event) nguồn. Chỉ số có nguồn đánh dấu `pending` → `null` + tên trong `unavailable`. Test: mọi khóa trong response có mặt trong `METRIC_SOURCES` và ngược lại (quét không rỗng, ≥ số kỳ vọng).

---

## 6. Luật cảnh báo

P9 §6 có 14 luật + việc Phase 7 "luật cho `finalize_failed_permanent`". Kế hoạch này thêm luật 16 (E7) — xem Q-M9-3.

| # | `rule_id` | Điều kiện | Nguồn | `subject` | `window_start` | Chu kỳ | `severity` / người nhận (`detail.audience`) |
|---|---|---|---|---|---|---|---|
| 1 | `escalation_rate_high` | `escalation_rate_weighted` 7 ngày > 0,40 | 5.1 | `""` | đầu ngày đánh giá | ngày | warning / manager |
| 2 | `injection_detected` | mỗi lá `exit_code='E0'` | `tickets` + audit B2 `injection_detected` | `ticket_id` | thời điểm audit B2 chặn | 60 s | critical / manager |
| 3 | `password_bruteforce` | **đối soát**: mỗi `security_events.account_locked` có `detail.reason='threshold'` mà chưa có cảnh báo khớp (±60 s) | `security_events`, `alerts` | qua `bruteforce_subject()` | `occurred_at` (chỉ khi chưa có cảnh báo khớp) | 60 s | critical / manager |
| 4 | `e9_spike` | #E9 giờ qua > 3 × trung vị theo giờ 7 ngày, tối thiểu 3 ca | `tickets` | `""` | đầu giờ | 60 s | warning / dev |
| 5 | `breaker_open` | có span tool `error = circuit_open` (Q-M9-4) — **nguồn pending** (span tool chưa ghi DB) | `spans` | tên tool | thời điểm span `circuit_open` đầu tiên của đợt | 60 s | warning / ops |
| 6 | `e6_spike` | #E6 giờ qua > 3 × trung vị 7 ngày, tối thiểu 3 | `tickets` | `""` | đầu giờ | 60 s | warning / manager |
| 7 | `reflex_approval` | một L1 có ≥ 3 phiếu trong ngày với thời gian xem < 5 giây | `approvals` (`decided_at − first_viewed_at`) hoặc audit B16 `view_duration` (agent xác nhận) | `user_id` L1 | đầu ngày | ngày | warning / manager |
| 8 | `drift` | PSI > 0,2 ở bất kỳ phân bố nào (M9-7) | 5.x | tên phân bố | đầu tuần | tuần | warning / manager |
| 9 | `refresh_reuse` | mỗi `refresh_reuse_detected` | `security_events` (`detail` chỉ có `revoked_sessions`) | `user_id` (Q-M9-8) | `occurred_at` | 60 s | critical / manager |
| 10 | `permission_denied_burst` | > 10 `permission_denied` trong 5 phút trượt, một người | `security_events` | `user_id` | đầu khung 5 phút chứa sự kiện thứ 11 | 60 s | warning / manager |
| 11 | `policy_saved` | mỗi `policy_saved` | `security_events` | phiên bản policy | thời điểm lưu | 60 s | info / manager |
| 12 | `b2_degraded` | `b2_llm_rate` trong ngày > 0,30 | 5.2 | `""` | đầu ngày | ngày | warning / dev |
| 13 | `b3_degraded` | `b3_llm_rate` trong ngày > 0,30 (D-32) | 5.2 | `""` | đầu ngày | ngày | warning / dev |
| 14 | `llm_budget` | Σ `llm_calls.cost_usd` ≥ `warn_ratio` (0,8) × `cap_usd` (38) — `config/llm.yaml` `spend` | `llm_calls` | `""` | đầu ngày (Q-M9-6) | giờ | critical / dev + cả nhóm |
| 15 | `finalize_failed` | mỗi audit `finalize_failed_permanent` | `audit_logs` | `ticket_id` | thời điểm audit | 60 s | critical / dev |
| 16 | `execution_failed` **[Đề xuất]** | mỗi lá `exit_code='E7'` | `tickets` | `ticket_id` | thời điểm B17 lỗi (audit) | 60 s | critical / manager + ops |

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
5. Agent rebase lên `origin/dev-tuananh` (8.3), push nhánh của mình (`m9-luuduong` / `m9-duyanh`), mở PR vào `dev-tuananh`, mô tả PR theo mẫu (8.2), rồi **dừng**.
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

- Nhánh làm: `m9-luuduong` (Dương), `m9-duyanh` (Duy Anh), cùng tạo từ `origin/dev-tuananh` mới nhất. Nhánh cũ `dev-luuduong`, `dev-duyanh` (khởi tạo) không dùng. Quy tắc hai người (chủ file, thứ tự merge, rebase sau mỗi merge): file chia việc mục 2, 4, 8.
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
| Q-M9-1 | Vận hành live không có nhãn gold — chia 3 nhóm N3 theo gì? | Theo điểm log 4: `allow`/`risk_level=low` hoặc không tới M5 (info, E0–E4) → thường ngày; `approval_required`/`medium` → cần duyệt; `deny`/`high` → nhạy cao. Trọng số 70/20/10 là hằng một chỗ (`monitor/metrics.py`) | Dùng lại dữ liệu đã log, không thêm nhãn; khi M8 có nhãn thì so hai cách |
| Q-M9-2 | "Ngày" theo múi giờ nào? | `Asia/Ho_Chi_Minh` cho mọi cửa sổ ngày/tuần; lưu và so sánh vẫn UTC; job ngày 02:00 giờ VN | Người đọc dashboard ở VN; một nguồn múi giờ |
| Q-M9-3 | Thêm luật 16 `execution_failed` (E7)? | **Có** | B20 bước 6 yêu cầu cảnh báo E0/E7/E9; 14 luật hiện có phủ E0 (luật 2), E9 (luật 4) nhưng **không phủ E7** — E7 có ưu tiên "rất cao" → thiếu là FN |
| Q-M9-4 | Luật 5 lấy "breaker mở" từ đâu (breaker nằm trong bộ nhớ tiến trình)? | Kiểm 29/09: `tools/registry.py::_span` **chỉ ghi log**, chưa ghi bảng `spans`. Duy Anh viết luật trên hợp đồng dự kiến (span `span_type='tool'`, `status='error'`, `attributes.error='circuit_open'`; "đợt" = chuỗi cách nhau < 60 s) + test fixture, để **pending**. Tuấn Anh cho registry ghi span tool khi tiện (ngoài phạm vi M9) | Không đụng `tools/` (cấm); luật sẵn sàng khi nguồn có |
| Q-M9-5 | `dashboard:read:own` của L1 là phiếu nào? | Phiếu có `approvals.approver_id = user_id` (giao cho mình), kể cả hết hạn | "Phần mình duyệt" gồm cả phiếu mình để hết hạn — đó là thứ L1 cần thấy |
| Q-M9-6 | Luật 14 báo lại bao lâu một lần khi đã vượt 80%? | Một lần mỗi ngày (`window_start` = đầu ngày), đánh giá mỗi giờ | Nhắc hằng ngày đủ; mỗi giờ thành nhiễu |
| Q-M9-8 | Luật 9 `refresh_reuse`: `subject` là gì? P9 ghi `token_family_id` nhưng `security_events.detail` chỉ có `revoked_sessions` (kiểm code 29/09) | `subject = user_id`, `window_start = occurred_at` → mỗi sự kiện một cảnh báo; **không** sửa auth để thêm trường | Không đụng `auth/`; mỗi lần dùng lại token đã là sự cố riêng, không cần gộp theo họ token |
| Q-M9-7 | `/api/health` kiểm LLM thế nào? | Không gọi LLM thật: báo `llm: scripted` / `real:configured` / `real:missing_pricing` / `spend_cap_reached` từ cấu hình gateway + trần chi; chỉ **báo**, không đổi mã 200/503 (như `kb`) | Ping LLM thật tốn tiền và ngân sách < 1 triệu đồng; health gọi mỗi 10 giây |

---

## 11. Phối hợp

| Với | Việc | Khi |
|---|---|---|
| Dương ↔ Duy Anh | Chủ file, hợp đồng hàm, thứ tự merge, review chéo, cổng chéo | File chia việc mục 2–9 |
| TV3 (frontend F5) | M9-3 mở PR → gửi TV3 `openapi.json` phần `/api/dashboard/*`, `/api/alerts*` để thay kiểu viết tay trong `contracts-tam.ts`, xóa handler MSW `dashboard`, `alerts` | Sau merge M9-3 |
| Tuấn Anh (Phase 3–4) | Khi luồng chính thêm event/trường mà M9 đang `unavailable` (điểm log 4, ghi đè, B3 LLM, nhiều ý) → Tuấn Anh ghi vào issue epic; chỉ số → Dương, luật → Duy Anh mở chặng nhỏ "nối nguồn" | Theo phase |
| Tuấn Anh (spec) | Mục "Spec cần sửa" trong PR → Tuấn Anh/Claude chat cập nhật `P9-monitor-M9.md` (mục 5.1 "Chốt khi hiện thực") | Sau mỗi merge |

---

## 12. Chuẩn bị máy (Dương làm ở A0; Duy Anh ở B0 — Duy Anh đã dựng stack ở cổng 2 nên chỉ cần từ bước 3, nhánh `m9-duyanh`)

1. Cài: Git, Docker (Linux/WSL 2 hoặc colima trên Mac), `uv`, `gitleaks`, `gh`, Claude Code.
2. `git clone https://github.com/17tuanphamanh/AIP_FA26_G8.git && cd AIP_FA26_G8`
3. `git fetch origin && git switch -c m9-luuduong origin/dev-tuananh` (Duy Anh: `m9-duyanh`)
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
Tôi là <Lưu Dương | Tạ Duy Anh>, làm trên nhánh <m9-luuduong | m9-duyanh>; Tuấn Anh review và merge.
Luật: không đọc/in .env; không --no-verify; không nới sandbox; chỉ sửa file trong bảng mục 2 (ngoài bảng thì dừng và hỏi); không sửa docs/spec/; M9 chỉ đọc (engine app_monitor, không fallback app_rw); mọi đếm ticket qua v_leaf; lệnh cần Docker thì báo tôi chạy; stage đích danh; không commit/push khi tôi chưa bảo; commit tiếng Việt không dấu, không dòng AI.
Bước 1: lập plan (Plan Mode, chưa code): file tạo/sửa, test (gồm ca ranh giới), mutation dự kiến (đột biến → test nào đỏ, assert nào), câu hỏi Q-M9-x-… kèm đề xuất. Trình bày plan dạng markdown để tôi dán vào issue. Chưa code tới khi tôi báo "Duyệt".
```

**Khi Tuấn Anh đã duyệt plan:**
```
Plan <M9-x> đã duyệt. Chốt: <dán các chốt từ issue>. Làm: code → make lint → unit → mutation logic (báo từng kết quả). Lệnh cần Docker (make test, mutation SQL) thì đưa tôi từng lệnh. Chưa commit.
```

**Khi test xanh, chuẩn bị PR:**
```
make test xanh (<số> passed). Rebase lên origin/dev-tuananh (git fetch origin && git rebase origin/dev-tuananh), kiểm alembic heads = 1, chạy lại make lint. Stage đích danh (kiểm không có .env*, __pycache__, .pyc, settings.local.json), commit, push nhánh của tôi. Soạn mô tả PR theo mẫu mục 8.2 để tôi mở PR vào dev-tuananh (nhánh của tôi: m9-luuduong hoặc m9-duyanh). Rồi DỪNG.
```

---

## 14. Nhật ký thay đổi

| Ngày | Thay đổi |
|---|---|
| 29/09/2026 | **v1.1** — chia cho hai người: Lưu Dương (luồng A) + Tạ Duy Anh (luồng B), chi tiết ở `claude/ke-hoach-m9-chia-viec.md`; mục 7.0 ánh xạ gói → chặng; kiểm lại nguồn: span tool chưa ghi DB (luật 5 pending, Q-M9-4 sửa), `refresh_reuse_detected` không có `token_family_id` (Q-M9-8 mới), `lock_start` của auth ≠ `occurred_at` (luật 3 đối soát ±60 s); migration chỉ Dương viết |
| 29/09/2026 | v1.0 — Tạo file: kiểm repo tại `3f33ab2`, 8 chặng M9-0…M9-7, định nghĩa chỉ số, 16 luật (thêm luật 15 theo việc Phase 7 đã ghi, đề xuất luật 16 cho E7), ranh giới file, quy trình PR, câu hỏi Q-M9-1…7 |
