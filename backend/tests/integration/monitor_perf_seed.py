"""Dựng dữ liệu HIỆU NĂNG cho M9 (A4, #11): 10.000 ticket lá + 200 cha, child_notices (F12)/audit/turns/spans/llm_calls/
approvals/escalations/alerts/security_events — đủ để đo "mỗi truy vấn dashboard < 2 giây" (P9 §8, [Chốt T5]).

Khác `monitor_seed.py` (A1, chèn từng dòng cho test tính tay): ở đây mỗi bảng MỘT câu `INSERT … SELECT
generate_series` → 10.000 lá chèn trong vài giây.

**Tất định tuyệt đối.** KHÔNG dùng `random()`, `now()`, `uuid`, `md5` hay `setseed`: mọi giá trị suy từ chỉ số `i`
của `generate_series` (thuộc tính phân loại qua `_mix` — xem chú thích ở đó) và mốc `BASE` cố định (năm 2030, cửa
sổ riêng vì `audit_logs` chỉ ghi thêm). Chạy lại trên DB trống ra ĐÚNG cùng dữ liệu (trừ khoá tự tăng
`log_id`/`alert_id`… do Postgres cấp theo thứ tự chèn).

Cách dùng (KHÔNG tự commit, như `monitor_seed.py`):

    from tests.integration.monitor_perf_seed import PERF_LEAVES, analyze, seed_perf
    async with rw.begin() as conn:          # role app_rw
        counts = await seed_perf(conn)
    with owner.begin() as conn:             # role app_migrate (ANALYZE cần chủ bảng)
        analyze(conn)

Nơi chạy và dọn dẹp — chỉ trên Postgres TẠM, không bao giờ trên stack dev (`mock_services/seed.json`, dữ liệu demo):
- **Test PG (S4, `test_monitor_perf_pg.py`)**: DB riêng của module qua `tests.integration.pg.fresh_database` trong
  container chung của bộ test — thoát context là `DROP DATABASE`.
- **Script đo ngoài repo (`measure_a4.py`, S3b)**: tự dựng một container Postgres 16 riêng bằng testcontainers
  (`with container:`), seed vào DB mặc định của container đó — thoát khối là container bị dừng và xoá cùng dữ liệu.
  Script KHÔNG dùng `fresh_database`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection

# Cửa sổ dữ liệu: 30 ngày của năm 2030 (cùng quy ước "cửa sổ riêng" của monitor_seed.py).
BASE = datetime(2030, 3, 1, tzinfo=UTC)
DAYS = 30
PERF_LEAVES = 10_000  # P9 §8: "10.000 ticket giả"
PERF_PARENTS = 200  # 2% — ticket cha KHÔNG được tính vào chỉ số nào (D-30)
CHILDREN_PER_PARENT = 2

REQUESTER = "perf-requester"
APPROVERS: tuple[str, ...] = ("perf-l1-a", "perf-l1-b", "perf-l1-c", "perf-l1-d")
MANAGER = "perf-manager"
_HASH = "0" * 64  # action_plan_hash giả (CHAR(64) NOT NULL)

# Bảng được seed, theo thứ tự chèn (FK): dùng cho ANALYZE và cho báo cáo số dòng.
TABLES: tuple[str, ...] = (
    "users", "tickets", "child_notices", "turns", "spans", "llm_calls", "audit_logs",
    "approvals", "escalations", "alerts", "security_events",
)  # fmt: skip


@dataclass(frozen=True)
class SeedCounts:
    """Số dòng mỗi bảng sau khi seed — in vào báo cáo hiệu năng để số đo có ngữ cảnh."""

    rows: dict[str, int]

    def line(self) -> str:
        return ", ".join(f"{t}={self.rows.get(t, 0)}" for t in TABLES)


# ---- SQL: mỗi bảng một câu, mọi giá trị suy từ `i` ------------------------------------------------
#
# Dấu `%` (phép chia lấy dư) viết MỘT lần trong nguồn: `text()` của SQLAlchemy tự escape thành `%%` cho psycopg
# (paramstyle pyformat), psycopg đổi lại thành `%` trước khi gửi Postgres. Viết sẵn `%%` thì Postgres nhận `%%` →
# "operator does not exist: integer %% integer" (lỗi lượt chạy thử S3a). Test: test_monitor_perf_seed.py.

# Trộn chỉ số cho thuộc tính PHÂN LOẠI (trạng thái, mã thoát, có phiếu, người duyệt, lý do escalation). Lấy thẳng
# `i % k` thì các `k` có ước chung (30, 20, 8, 4, 6) trùng nhịp nhau: vd E0 cần `i % 20 ∈ {16,17}` (chữ số cuối 6/7)
# còn ngày cuối cần `i % 30 = 29` (chữ số cuối 9) → 24 giờ cuối KHÔNG có E0, `TICKET_EXIT_SQL [E0, 24h]` đo trên
# tập rỗng. `((i · salt) mod P) mod k` với P nguyên tố > 10.000 và salt riêng từng thuộc tính → các thuộc tính gần
# như độc lập, vẫn TẤT ĐỊNH. Ngày/phút vẫn lấy từ `i` (rải đều 30 ngày).
_P = 10_007
SALT_STATE, SALT_CODE, SALT_APPROVAL, SALT_APPROVER, SALT_REASON = 7919, 6067, 5021, 3001, 2003
SALT_OVERRIDE = 1009  # ghi đè: `i % 20 = 0` cũ chỉ rơi vào ngày i % 30 ∈ {0, 10, 20} → 7 ngày cuối không có


def _mix(i: str, salt: int, k: int) -> str:
    """Biểu thức SQL `((i · salt) mod P) mod k` — `bigint` để `i · salt` không tràn int4 khi seed lớn."""
    return f"((({i})::bigint * {salt}) % {_P}) % {k}"


# `ts(i)` rải đều trên 30 ngày: ngày = i % 30, phút trong ngày = (i * 7) % 1440 (bước 7 phút → không dồn cục).
_TS = f"'{BASE.isoformat()}'::timestamptz + make_interval(days => (i % {DAYS})::int, mins => ((i * 7) % 1440)::int)"

_USERS = """
INSERT INTO users (user_id, username, role) VALUES
  (:req, 'perf.requester', 'employee'),
  (:m, 'perf.manager', 'manager'),
  ('perf-l1-a', 'perf.l1.a', 'l1'), ('perf-l1-b', 'perf.l1.b', 'l1'),
  ('perf-l1-c', 'perf.l1.c', 'l1'), ('perf-l1-d', 'perf.l1.d', 'l1')
ON CONFLICT DO NOTHING
"""

# final_state theo s = mix(i, SALT_STATE) % 20: 2 NULL (đang chạy) · 10 S_RESOLVED · 4 S_ESCALATED · 2 S_BLOCKED ·
# 2 S_REJECTED. exit_code: S_BLOCKED → E0; S_ESCALATED → 8 mã chia đều theo mix(i, SALT_CODE) % 8; còn lại NULL.
_LEAVES = f"""
WITH g AS (SELECT i FROM generate_series(1, :n) AS s(i)),
m AS (SELECT i, {_mix("i", SALT_STATE, 20)} AS s FROM g),
d AS (
  SELECT i,
         CASE WHEN s < 2 THEN NULL
              WHEN s < 12 THEN 'S_RESOLVED'
              WHEN s < 16 THEN 'S_ESCALATED'
              WHEN s < 18 THEN 'S_BLOCKED'
              ELSE 'S_REJECTED' END AS fs,
         {_TS} AS created_at
  FROM m
)
INSERT INTO tickets (ticket_id, requester_id, requester_role, requester_dept, redacted_request, intent,
                     final_state, exit_code, resolution_path, block_reason, created_at, closed_at,
                     total_turns, is_parent)
SELECT 'perf-leaf-' || lpad(i::text, 5, '0'),
       :req, 'employee', 'dept-' || (i % 5)::text, 'yeu cau hieu nang so ' || i::text,
       (ARRAY['account','vpn','software','access'])[1 + i % 4],
       fs,
       CASE WHEN fs = 'S_BLOCKED' THEN 'E0'
            WHEN fs = 'S_ESCALATED'
                 THEN (ARRAY['E1','E2','E3','E6','E7','E9','E4','E5'])[1 + {_mix("i", SALT_CODE, 8)}]
            ELSE NULL END,
       CASE WHEN fs = 'S_RESOLVED' AND i % 3 = 0 THEN 'deflected'
            WHEN fs = 'S_RESOLVED' THEN 'auto'
            WHEN fs = 'S_ESCALATED' THEN 'escalated'
            WHEN fs = 'S_REJECTED' THEN 'rejected'
            ELSE NULL END,
       CASE WHEN fs = 'S_BLOCKED' THEN 'injection_detected' ELSE NULL END,
       created_at,
       CASE WHEN fs IS NULL THEN NULL ELSE created_at + make_interval(mins => (i % 120)::int) END,
       1 + i % 3, false
FROM d
"""

# Ticket cha + gán cha cho 2 lá đầu mỗi cha (lá vẫn là lá — chỉ số phải đếm lá, không đếm cha: test "câu 2 ý").
_PARENTS = f"""
INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, intent, aggregate_status,
                     created_at, is_parent)
SELECT 'perf-parent-' || lpad(i::text, 4, '0'), :req, 'employee', 'cau nhieu y so ' || i::text,
       (ARRAY['account','vpn','software','access'])[1 + i % 4],
       (ARRAY['ALL_RESOLVED','PARTIALLY_ESCALATED','MIXED'])[1 + i % 3],
       {_TS}, true
FROM generate_series(1, :p) AS s(i)
"""

_LINK_CHILDREN = f"""
UPDATE tickets t
SET parent_ticket_id = 'perf-parent-' || lpad((((n - 1) / {CHILDREN_PER_PARENT}) + 1)::text, 4, '0')
FROM (SELECT ticket_id, row_number() OVER (ORDER BY ticket_id) AS n FROM tickets WHERE is_parent = false) r
WHERE t.ticket_id = r.ticket_id AND r.n <= :p * {CHILDREN_PER_PARENT}
"""

# F12: hộp thư con (`child_notices`) cho `multi_intent_first_stop_to_reply_s` — mỗi con 2 notice (vòng k = 1, 2), mốc theo
# `created_at` của CHA: tạo lúc cha + (k·300 + 10 + i % 50) s; cha gửi cả vòng CÙNG một lúc cha + (k·300 + 120) s (như
# `deliver_round`). Con thứ 10, 20, … chưa được gửi vòng 2 (hai cột NULL — CHECK `delivered_pair`).
_CHILD_NOTICES = """
WITH c AS (SELECT t.ticket_id, t.parent_ticket_id, p.created_at AS parent_at,
                  row_number() OVER (ORDER BY t.ticket_id) AS i
           FROM tickets t JOIN tickets p ON p.ticket_id = t.parent_ticket_id WHERE t.is_parent = false)
INSERT INTO child_notices (parent_ticket_id, child_ticket_id, source_step, kind, needs, body, effect_key, created_at,
                           delivered_round, delivered_at)
SELECT c.parent_ticket_id, c.ticket_id, 'B20',
       CASE WHEN r.k = 1 AND c.i % 2 = 0 THEN 'question' ELSE 'result' END,
       CASE WHEN r.k = 1 AND c.i % 2 = 0 THEN 'answer' ELSE 'none' END,
       'tin con so ' || c.i::text || '-' || r.k::text,
       rpad('perf-notice-' || c.i::text || '-' || r.k::text, 64, '0'),
       c.parent_at + make_interval(secs => (r.k * 300 + 10 + c.i % 50)::int),
       CASE WHEN r.k = 2 AND c.i % 10 = 0 THEN NULL ELSE r.k END,
       CASE WHEN r.k = 2 AND c.i % 10 = 0 THEN NULL
            ELSE c.parent_at + make_interval(secs => (r.k * 300 + 120)::int) END
FROM c CROSS JOIN generate_series(1, 2) AS r(k)
"""

# Một lượt (turn) mỗi lá; `leaf` CTE dùng lại cho mọi bảng con để số thứ tự `i` ổn định theo ticket_id.
_LEAF_CTE = """
leaf AS (SELECT ticket_id, created_at, row_number() OVER (ORDER BY ticket_id) AS i
         FROM tickets WHERE is_parent = false)
"""

_TURNS = f"""
WITH {_LEAF_CTE}
INSERT INTO turns (turn_id, ticket_id, event_type, started_at, ended_at)
SELECT 'perf-turn-' || lpad(i::text, 5, '0'), ticket_id, 'submit', created_at,
       created_at + make_interval(secs => (20 + i % 100)::int)
FROM leaf
"""

# 5 span node (p95 theo bước) + 2 span llm (cha của llm_calls) mỗi lá.
_SPANS_NODE = f"""
WITH {_LEAF_CTE}
INSERT INTO spans (span_id, trace_id, turn_id, span_type, name, started_at, duration_ms, status, attributes)
SELECT 'pn-' || lpad(i::text, 5, '0') || '-' || k::text,
       'ptr-' || lpad(i::text, 5, '0'),
       'perf-turn-' || lpad(i::text, 5, '0'), 'node',
       (ARRAY['b02_screen','b03_classify','b08_retrieve','b13_decide','b17_execute'])[k],
       created_at + make_interval(secs => k),
       10 + ((i * 13 + k * 37) % 1500), 'ok', '{{}}'::jsonb
FROM leaf, generate_series(1, 5) AS s(k)
"""

_SPANS_LLM = f"""
WITH {_LEAF_CTE}
INSERT INTO spans (span_id, trace_id, turn_id, span_type, name, started_at, duration_ms, status, attributes)
SELECT 'pl-' || lpad(i::text, 5, '0') || '-' || k::text,
       'ptr-' || lpad(i::text, 5, '0'),
       'perf-turn-' || lpad(i::text, 5, '0'), 'llm',
       (ARRAY['b03_classify','b10_answer'])[k],
       created_at + make_interval(secs => 10 + k), 200 + ((i * 7 + k) % 900), 'ok', '{{}}'::jsonb
FROM leaf, generate_series(1, 2) AS s(k)
"""

# cache_hit 25%, used_fallback 10%, json_valid_first_try: 10% NULL (KHÔNG tính là lỗi), 15% false.
_LLM_CALLS = f"""
WITH {_LEAF_CTE}
INSERT INTO llm_calls (span_id, provider, model, model_version, prompt_id, prompt_version, tokens_in, tokens_out,
                       cost_usd, latency_ms, cache_hit, json_valid_first_try, used_fallback, created_at)
SELECT 'pl-' || lpad(i::text, 5, '0') || '-' || k::text, 'scripted', 'scripted', NULL,
       (ARRAY['b03_classify','b10_answer'])[k], '1',
       100 + (i % 400), 50 + (i % 200),
       0.0001 * (1 + (i % 9)), 200 + ((i * 11 + k) % 800),
       (i + k) % 4 = 0,
       CASE WHEN (i + k) % 10 = 0 THEN NULL ELSE (i + k) % 7 <> 0 END,
       (i + k) % 10 = 3,
       created_at + make_interval(secs => 10 + k)
FROM leaf, generate_series(1, 2) AS s(k)
"""

# ---- audit_logs: 8 điểm log, mỗi loại một câu ----------------------------------------------------

# B2 (điểm screening): layer_decided 4 giá trị chia đều; 10% dòng là `guard_unavailable` (mẫu số của b2_llm_rate).
_AUDIT_B2 = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, detail)
SELECT ticket_id, created_at + make_interval(secs => 2), 'perf-turn-' || lpad(i::text, 5, '0'), 0, 'B2',
       CASE WHEN i % 10 = 0 THEN 'guard_unavailable' ELSE 'screened' END,
       CASE WHEN i % 10 = 0 THEN '{{}}'::jsonb
            ELSE jsonb_build_object('screening', jsonb_build_object(
                 'layer_decided', (ARRAY['regex','clf','llm','rule'])[1 + i % 4])) END
FROM leaf
"""

# B3/B4 (điểm log 1): `layer` llm/model; `model_version` chỉ có ở dòng layer='model' (intent_model_version).
_AUDIT_B3 = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, intent, confidence, detail)
SELECT ticket_id, created_at + make_interval(secs => 3), 'perf-turn-' || lpad(i::text, 5, '0'), 0,
       CASE WHEN {_mix("i", SALT_STATE, 20)} BETWEEN 12 AND 15 THEN 'B4' ELSE 'B3' END,
       'classified',
       (ARRAY['account','vpn','software','access'])[1 + i % 4],
       0.5 + 0.004 * (i % 100),
       CASE WHEN i % 3 = 0
            THEN jsonb_build_object('layer', 'model', 'model_version', 'intent-clf-1.0.' || (i % 3)::text)
            ELSE jsonb_build_object('layer', 'llm') END
FROM leaf
"""

_AUDIT_B8 = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, query, top_score, detail)
SELECT ticket_id, created_at + make_interval(secs => 4), 'perf-turn-' || lpad(i::text, 5, '0'), 0, 'B8',
       'retrieved', 'truy van ' || i::text, 0.3 + 0.006 * (i % 100),
       jsonb_build_object('intent_filter_fallback', CASE WHEN i % 8 = 0 THEN 'true' ELSE 'false' END)
FROM leaf
"""

# Điểm log 4 (B13/B14) — nhóm N3 của escalation_rate_weighted, decided_by_distribution, top_matched_rules.
# Tổ hợp NHẤT QUÁN theo `decided_by`: `rule` → có `matched_rule_id`, KHÔNG xác suất / `p_method`; `llm` → KHÔNG
# `matched_rule_id`, có `calibrated_prob`, `raw_prob` ∈ [0, 1] và `p_method` thuộc CHECK `ck_audit_logs_p_method`
# (`self_report` | `sampling_k5` — đọc từ models/migration 0001, không suy từ code risk). Bản trước ghi `'platt'` cho
# mọi dòng → CheckViolation ở lượt (c) lần 2. `matched_rule_id` theo `(i / 2) % 20` để đủ R01…R20 (dòng rule là i chẵn).
_AUDIT_POINT4 = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, decided_by, policy_decision,
                        risk_level, matched_rule_id, calibrated_prob, raw_prob, p_method, detail)
SELECT ticket_id, created_at + make_interval(secs => 5), 'perf-turn-' || lpad(i::text, 5, '0'), 0, 'B13/B14',
       'decided',
       CASE WHEN i % 2 = 0 THEN 'rule' ELSE 'llm' END,
       (ARRAY['allow','approval_required','deny'])[1 + i % 3],
       (ARRAY['low','medium','high'])[1 + i % 3],
       CASE WHEN i % 2 = 0 THEN 'R' || lpad((1 + (i / 2) % 20)::text, 2, '0') ELSE NULL END,
       CASE WHEN i % 2 = 0 THEN NULL ELSE 0.5 + 0.004 * (i % 100) END,
       CASE WHEN i % 2 = 0 THEN NULL ELSE 0.45 + 0.005 * (i % 100) END,
       CASE WHEN i % 2 = 0 THEN NULL ELSE (ARRAY['self_report','sampling_k5'])[1 + (i / 2) % 2] END,
       '{{}}'::jsonb
FROM leaf
"""

# B9 (kb_version cho e3_cases) — chỉ lá E3 cần, nhưng ghi cho mọi lá như luồng thật (B8/B9 luôn chạy).
_AUDIT_B9 = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, kb_version, detail)
SELECT ticket_id, created_at + make_interval(secs => 6), 'perf-turn-' || lpad(i::text, 5, '0'), 0, 'B9',
       'grounded', NULL, jsonb_build_object('relevance', 0.01 * (i % 100))
FROM leaf
"""

# B20 (điểm log 8): dòng MANG exit_code — nguồn của TICKET_EXIT_SQL (luật 2/4/6/16, chạy mỗi 60 giây).
_AUDIT_B20 = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, final_state, exit_code,
                        block_reason, close_reason, detail)
SELECT l.ticket_id, l.created_at + make_interval(secs => 30), 'perf-turn-' || lpad(l.i::text, 5, '0'), 0, 'B20',
       'finalized', t.final_state, t.exit_code, t.block_reason,
       CASE WHEN t.final_state = 'S_RESOLVED' THEN 'resolved_user_confirmed'
            WHEN t.final_state = 'S_BLOCKED' THEN 'blocked_injection_detected'
            WHEN t.final_state = 'S_REJECTED' THEN 'rejected_by_approver' ELSE NULL END,
       CASE WHEN t.exit_code IS NULL THEN '{{}}'::jsonb
            ELSE jsonb_build_object('escalation_reason_detail',
                 (ARRAY['out_of_scope','intent_low_confidence','llm_unavailable','no_grounding'])[1 + l.i % 4]) END
FROM leaf l JOIN tickets t USING (ticket_id)
WHERE t.final_state IS NOT NULL
"""

# OVERRIDE (4d) — 5% lá (mix(i, SALT_OVERRIDE) % 20 = 0, rải đủ 30 ngày), mỗi lá 1 dòng (override_count).
_AUDIT_OVERRIDE = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, original_decision,
                        override_decision, overrider_id, idempotency_key, detail)
SELECT ticket_id, created_at + make_interval(mins => 90), 'perf-turn-' || lpad(i::text, 5, '0'), 0, 'OVERRIDE',
       'override_recorded', 'approval_required', 'allow', 'perf-l1-a',
       lpad(('9' || lpad(i::text, 5, '0')), 64, '0'), '{{}}'::jsonb
FROM leaf WHERE {_mix("i", SALT_OVERRIDE, 20)} = 0
"""

# B16 (điểm log 6) — chỉ lá có phiếu duyệt (luật 7 reflex đọc step B16).
_AUDIT_B16 = f"""
WITH {_LEAF_CTE}
INSERT INTO audit_logs (ticket_id, created_at, turn_id, loop_seq, step, event, approval_result,
                        response_time_seconds, detail)
SELECT ticket_id, created_at + make_interval(mins => 45), 'perf-turn-' || lpad(i::text, 5, '0'), 0, 'B16',
       'approval_decided', (ARRAY['approved','rejected','timeout'])[1 + i % 3], 60 + (i % 3000),
       jsonb_build_object('view_seconds', 5 + (i % 50))
FROM leaf WHERE {_mix("i", SALT_APPROVAL, 7)} = 0
"""

# ---- approvals / escalations / alerts / security_events ------------------------------------------

# ~14% lá có phiếu (mix(i, SALT_APPROVAL) % 7 = 0 — CÙNG điều kiện với _AUDIT_B16), mỗi lá đúng 1 phiếu → không
# phạm `ux_approvals_one_pending`. Người duyệt theo mix(i, SALT_APPROVER) % 4.
_APPROVALS = f"""
WITH {_LEAF_CTE}
INSERT INTO approvals (ticket_id, approver_id, backup_approver_id, deadline, action_plan_hash, conflict_detected,
                       status, note, decided_by, decided_at, created_at, reminder_2_at)
SELECT ticket_id,
       (ARRAY['perf-l1-a','perf-l1-b','perf-l1-c','perf-l1-d'])[1 + {_mix("i", SALT_APPROVER, 4)}], NULL,
       created_at + make_interval(hours => 4), '{_HASH}', false,
       (ARRAY['approved','rejected','timeout'])[1 + i % 3],
       CASE WHEN i % 3 = 1 THEN 'tu choi vi khong du dieu kien' ELSE NULL END,
       CASE WHEN i % 3 = 2 THEN NULL
            ELSE (ARRAY['perf-l1-a','perf-l1-b','perf-l1-c','perf-l1-d'])[1 + {_mix("i", SALT_APPROVER, 4)}] END,
       CASE WHEN i % 3 = 2 THEN NULL ELSE created_at + make_interval(mins => 45) END,
       created_at + make_interval(mins => 1),
       created_at + make_interval(hours => 3)
FROM leaf WHERE {_mix("i", SALT_APPROVAL, 7)} = 0
"""

_ESCALATIONS = f"""
WITH {_LEAF_CTE}
INSERT INTO escalations (ticket_id, exit_code, priority, reason_detail, handoff_note, is_deny_case, assigned_to,
                         created_at)
SELECT l.ticket_id, t.exit_code, p.rank,
       (ARRAY['out_of_scope','intent_low_confidence','llm_unavailable','no_grounding',
              'intent_not_enabled','multi_intent_not_enabled'])[1 + {_mix("l.i", SALT_REASON, 6)}],
       jsonb_build_object('summary', 'tom tat ' || l.i::text, 'tried', '[]'::jsonb,
                          'context', '{{}}'::jsonb, 'next', 'L2 kiem tra'),
       false,
       CASE WHEN l.i % 2 = 0 THEN :m ELSE NULL END,
       l.created_at + make_interval(secs => 40)
FROM leaf l JOIN tickets t USING (ticket_id) JOIN exit_code_priority p ON p.exit_code = t.exit_code
WHERE t.exit_code IS NOT NULL
"""

# `alerts`: 2.000 dòng, `(rule_id, subject, window_start)` không trùng (subject = ticket lá thứ i).
_ALERTS = f"""
WITH {_LEAF_CTE}
INSERT INTO alerts (rule_id, subject, severity, value, window_start, status, detail, created_at)
SELECT (ARRAY['injection_detected','execution_failed','password_bruteforce','refresh_reuse',
              'permission_denied_burst'])[1 + i % 5],
       ticket_id,
       (ARRAY['low','medium','high','critical'])[1 + i % 4],
       1.0 * (i % 50),
       created_at + make_interval(secs => 50), 'open',
       jsonb_build_object('count', i % 10, 'threshold', 5),
       created_at + make_interval(secs => 55)
FROM leaf WHERE i % 5 = 0
"""

_SECURITY_EVENTS = f"""
INSERT INTO security_events (occurred_at, event_type, user_id, username_attempted, ip_prefix, route, detail)
SELECT {_TS},
       (ARRAY['login_failed','account_locked','permission_denied','refresh_reuse_detected',
              'injection_detected'])[1 + i % 5],
       CASE WHEN i % 3 = 0 THEN :req ELSE NULL END,
       'perf.user.' || (i % 50)::text, '10.0.' || (i % 255)::text, '/api/auth/login',
       jsonb_build_object('reason', CASE WHEN i % 5 = 1 THEN 'threshold' ELSE 'other' END)
FROM generate_series(1, :e) AS s(i)
"""

_STEPS: tuple[tuple[str, str], ...] = (
    ("users", _USERS),
    ("tickets (lá)", _LEAVES),
    ("tickets (cha)", _PARENTS),
    ("gán cha cho lá", _LINK_CHILDREN),
    ("child_notices", _CHILD_NOTICES),
    ("turns", _TURNS),
    ("spans (node)", _SPANS_NODE),
    ("spans (llm)", _SPANS_LLM),
    ("llm_calls", _LLM_CALLS),
    ("audit B2", _AUDIT_B2),
    ("audit B3/B4", _AUDIT_B3),
    ("audit B8", _AUDIT_B8),
    ("audit điểm 4", _AUDIT_POINT4),
    ("audit B9", _AUDIT_B9),
    ("audit B20 (exit_code)", _AUDIT_B20),
    ("audit OVERRIDE", _AUDIT_OVERRIDE),
    ("audit B16", _AUDIT_B16),
    ("approvals", _APPROVALS),
    ("escalations", _ESCALATIONS),
    ("alerts", _ALERTS),
    ("security_events", _SECURITY_EVENTS),
)


async def seed_perf(
    conn: AsyncConnection,
    *,
    leaves: int = PERF_LEAVES,
    parents: int = PERF_PARENTS,
    security_events: int = 5_000,
    log: bool = False,
) -> SeedCounts:
    """Chèn toàn bộ dữ liệu hiệu năng trên connection **app_rw**; KHÔNG commit (test/script tự commit).

    `leaves` nhỏ hơn để thử nhanh (vd 200). `log=True` in từng bước ra stdout (script đo dùng)."""
    params = {"n": leaves, "p": parents, "e": security_events, "req": REQUESTER, "m": MANAGER}
    for name, sql in _STEPS:
        result = await conn.execute(text(sql), params)
        if log:
            print(f"  seed {name}: {result.rowcount} dòng")
    rows: dict[str, int] = {}
    for table in TABLES:
        count = await conn.execute(text(f"SELECT count(*) FROM {table}"))  # tên bảng từ hằng TABLES
        rows[table] = int(count.scalar_one())
    return SeedCounts(rows)


def analyze(conn: Connection) -> None:
    """`ANALYZE` các bảng vừa seed — PHẢI chạy bằng **app_migrate** (chủ bảng); app_rw chỉ nhận WARNING
    "skipping" và kế hoạch truy vấn sẽ dựa trên thống kê rỗng → số đo vô nghĩa."""
    for table in TABLES:
        conn.execute(text(f"ANALYZE {table}"))  # tên bảng từ hằng TABLES
