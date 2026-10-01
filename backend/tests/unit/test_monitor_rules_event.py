"""M9-B1 GĐ1: 7 luật theo sự kiện (2, 3, 9, 10, 11, 15, 16) — hàm thuần, dữ liệu giả, không DB.

Nguồn: file chia việc M9 mục 6 (B1, bảng nguồn đã kiểm); kế hoạch chung M9 mục 4.4, 6; chốt Q-M9-B1-1…9 ở #13.
Loader SQL + test Postgres của từng luật là GĐ2 (cần `v_leaf` của A1).
"""

import ast
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.audit.alerts import check_alert
from app.domain.alerts import (
    SUBJECT_MAX,
    AlertDraft,
    bruteforce_alert,
    bruteforce_subject,
)
from app.monitor import evaluator, rules
from app.monitor.rules import (
    LOOKBACK,
    REGISTRY,
    BruteforceData,
    ExistingAlert,
    FinalizeFailed,
    RuleContext,
    SecurityEvent,
    TicketExit,
    execution_failed,
    finalize_failed,
    injection_detected,
    password_bruteforce,
    permission_denied_burst,
    policy_saved,
    refresh_reuse,
)
from app.monitor.window import VN_TZ, bucket_start

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
CTX = RuleContext(now=NOW, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)
MS = timedelta(milliseconds=1)
US = timedelta(microseconds=1)


def ctx_at(now: datetime) -> RuleContext:
    return RuleContext(now=now, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)


def sec(event_id: int, at: datetime, user_id: str | None = "u-1", username: str | None = None,
        **detail: Any) -> SecurityEvent:  # fmt: skip
    return SecurityEvent(event_id=event_id, occurred_at=at, user_id=user_id, username=username, detail=detail)


def burst(user_id: str | None, last: datetime, n: int = 11, step: timedelta = timedelta(seconds=10),
          username: str | None = None, first_id: int = 0) -> list[SecurityEvent]:  # fmt: skip
    """`n` sự kiện `permission_denied` cách nhau `step`, sự kiện cuối ở `last`."""
    return [sec(first_id + i, last - (n - 1 - i) * step, user_id, username) for i in range(n)]


# ---- bảng chung: 7 luật, mỗi luật một cách dựng dữ liệu từ [(đối tượng, thời điểm)] ---------------


@dataclass(frozen=True)
class Case:
    rule_id: str
    fn: Callable[[Any, RuleContext], list[AlertDraft]]
    make: Callable[[list[tuple[str, datetime]]], Any]
    subject: Callable[[str], str] = lambda k: k
    window: Callable[[datetime], datetime] = lambda at: at  # thời điểm sự kiện → window_start kỳ vọng
    severity: str = "critical"


def _locks(evs: list[tuple[str, datetime]]) -> BruteforceData:
    return BruteforceData(
        locks=[sec(i, at, user_id=k, username=f"name-{k}", reason="threshold") for i, (k, at) in enumerate(evs)],
        alerts=[],
    )


def _bursts(evs: list[tuple[str, datetime]]) -> list[SecurityEvent]:
    return [e for i, (k, at) in enumerate(evs) for e in burst(k, at, first_id=100 * i)]


CASES = [
    Case("injection_detected", injection_detected,
         lambda evs: [TicketExit(k, at, at, "B2", "injection_detected") for k, at in evs]),
    Case("password_bruteforce", password_bruteforce, _locks),
    Case("refresh_reuse", refresh_reuse,
         lambda evs: [sec(i, at, user_id=k, revoked_sessions=2) for i, (k, at) in enumerate(evs)]),
    Case("permission_denied_burst", permission_denied_burst, _bursts,
         window=lambda at: bucket_start(at, 5), severity="warning"),
    Case("policy_saved", policy_saved,
         lambda evs: [sec(i, at, user_id=None, version=k) for i, (k, at) in enumerate(evs)], severity="info"),
    Case("finalize_failed", finalize_failed, lambda evs: [FinalizeFailed(k, at, "b20_audit") for k, at in evs]),
    Case("execution_failed", execution_failed,
         lambda evs: [TicketExit(k, at, at, "B17", "exec_interrupted") for k, at in evs]),
]  # fmt: skip
IDS = [c.rule_id for c in CASES]

# Lúc 07:52:30 — không trùng biên khung 5 phút, cũ hơn 60 s (luật 3), trong 24 giờ.
T = NOW - timedelta(minutes=7, seconds=30)


def _ok(case: Case, drafts: list[AlertDraft]) -> None:
    for d in drafts:
        assert d.rule_id == case.rule_id
        assert d.severity == case.severity
        assert len(d.subject) <= SUBJECT_MAX
        check_alert(d)  # chính bộ kiểm writer M7 dùng — detail không mang khoá nhạy cảm
        assert "audience" not in d.detail  # Q-M9-B1-9: người nhận chỉ nằm trong RuleSpec


def test_registry_every_and_audience_of_b1_rules() -> None:
    """Bảng gán người nhận (kế hoạch chung M9 mục 6, cột người nhận) — chép vào mô tả PR."""
    expected = {
        "injection_detected": ("manager",),
        "password_bruteforce": ("manager",),
        "refresh_reuse": ("manager",),
        "permission_denied_burst": ("manager",),
        "policy_saved": ("manager",),
        "finalize_failed": ("dev",),
        "execution_failed": ("manager", "ops"),
    }
    assert {r: REGISTRY[r].audience for r in expected} == expected
    assert {REGISTRY[r].every for r in expected} == {"minute"}
    assert all(REGISTRY[c.rule_id].fn is c.fn for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_one_event_one_draft_window_from_db(case: Case) -> None:
    drafts = case.fn(case.make([("t-1", T)]), CTX)
    assert len(drafts) == 1
    assert drafts[0].subject == case.subject("t-1")
    assert drafts[0].window_start == case.window(T)  # thời điểm của sự kiện, KHÔNG phải ctx.now
    assert drafts[0].window_start != NOW
    _ok(case, drafts)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_no_event_no_draft(case: Case) -> None:
    assert case.fn(case.make([]), CTX) == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_lookback_24h_boundary_inclusive(case: Case) -> None:
    edge = NOW - LOOKBACK
    assert len(case.fn(case.make([("t-1", edge)]), CTX)) == 1
    assert case.fn(case.make([("t-1", edge - US)]), CTX) == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_two_subjects_same_window_two_drafts(case: Case) -> None:
    """Khoá cũ `(rule_id, cửa sổ)` gộp hai người/ticket làm một = bỏ sót sự cố an ninh (P9 mục 6)."""
    drafts = case.fn(case.make([("t-1", T), ("t-2", T)]), CTX)
    assert len(drafts) == 2
    assert {d.subject for d in drafts} == {case.subject("t-1"), case.subject("t-2")}
    assert {d.window_start for d in drafts} == {case.window(T)}
    _ok(case, drafts)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_catch_up_after_worker_down_1h(case: Case) -> None:
    """Worker chết 1 giờ: lần chạy đầu sau đó vẫn bắt mọi sự kiện trong giờ đã lỡ (lookback 24 giờ)."""
    evs = [("t-1", NOW - timedelta(minutes=59)), ("t-2", NOW - timedelta(minutes=30)), ("t-3", NOW - timedelta(minutes=1))]
    drafts = case.fn(case.make(evs), CTX)
    assert sorted((d.subject, d.window_start) for d in drafts) == sorted(
        (case.subject(k), case.window(at)) for k, at in evs
    )


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_rerun_later_gives_same_keys(case: Case) -> None:
    """Chạy lại ở nhịp sau (ctx.now +60 s, +10 phút) ra ĐÚNG khoá cũ → ON CONFLICT giữ một dòng."""
    data = case.make([("t-1", T), ("t-2", T - timedelta(hours=3))])
    keys = [{(d.subject, d.window_start) for d in case.fn(data, ctx_at(NOW + dt))} for dt in (
        timedelta(0), timedelta(seconds=60), timedelta(minutes=10)
    )]  # fmt: skip
    assert keys[0] == keys[1] == keys[2]
    assert len(keys[0]) == 2


# ---- luật 2, 16: khoá theo dòng audit sớm nhất của ticket ----------------------------------------


@pytest.mark.parametrize("fn", [injection_detected, execution_failed])
def test_ticket_exit_window_is_first_row_even_if_outside_lookback(fn: Callable[..., list[AlertDraft]]) -> None:
    """Dòng E0/E7 đầu đã quá 24 giờ nhưng ticket còn dòng mới trong 24 giờ → vẫn ra khoá cũ (first_at)."""
    first, last = NOW - LOOKBACK - timedelta(hours=1), NOW - timedelta(hours=1)
    drafts = fn([TicketExit("t-1", first, last, "B17", "exec_interrupted")], CTX)
    assert [d.window_start for d in drafts] == [first]
    assert fn([TicketExit("t-1", first, first, "B17", "exec_interrupted")], CTX) == []


def test_injection_detected_detail_step_and_reason_no_event() -> None:
    """Q-M9-B1-1: mọi E0 — B2 (S_BLOCKED) và B11/B19 `injection_in_reply`; detail ghi step + reason_detail."""
    drafts = injection_detected([
        TicketExit("t-b2", T, T, "B2", "injection_detected"),
        TicketExit("t-b11", T, T, "B11", "injection_in_reply"),
        TicketExit("t-b19", T, T, "B19", "injection_in_reply"),
    ], CTX)  # fmt: skip
    assert [dict(d.detail) for d in drafts] == [
        {"ticket_id": "t-b2", "step": "B2", "reason_detail": "injection_detected"},
        {"ticket_id": "t-b11", "step": "B11", "reason_detail": "injection_in_reply"},
        {"ticket_id": "t-b19", "step": "B19", "reason_detail": "injection_in_reply"},
    ]


@pytest.mark.parametrize("reason", ["exec_interrupted", "execution_interrupted", "exec_failed", None])
def test_execution_failed_any_reason_detail(reason: str | None) -> None:
    drafts = execution_failed([TicketExit("t-1", T, T, "B17", reason)], CTX)
    assert len(drafts) == 1 and drafts[0].detail["reason_detail"] == reason


# ---- luật 3: đối soát ±60 s, chờ 60 s ------------------------------------------------------------


def _lock(at: datetime, user_id: str | None = "u-1", username: str = "an.nv") -> SecurityEvent:
    return sec(1, at, user_id=user_id, username=username, reason="threshold")


@pytest.mark.parametrize("skew", [3 * MS, -3 * MS, timedelta(seconds=60), -timedelta(seconds=60)])
def test_bruteforce_auth_already_wrote_no_draft(skew: timedelta) -> None:
    """Auth ghi cảnh báo với `now` của auth, lệch vài ms so với occurred_at (hai lần gọi đồng hồ) → không thêm."""
    data = BruteforceData(locks=[_lock(T)], alerts=[ExistingAlert("u-1", T + skew)])
    assert password_bruteforce(data, CTX) == []


@pytest.mark.parametrize("skew", [timedelta(seconds=60) + US, -timedelta(seconds=60) - US])
def test_bruteforce_tolerance_boundary_just_outside(skew: timedelta) -> None:
    data = BruteforceData(locks=[_lock(T)], alerts=[ExistingAlert("u-1", T + skew)])
    assert len(password_bruteforce(data, CTX)) == 1


def test_bruteforce_missing_auth_row_draft_equals_shared_builder() -> None:
    """Không có cảnh báo khớp → đúng cảnh báo auth sẽ ghi, chỉ khác lock_start = occurred_at và source."""
    drafts = password_bruteforce(BruteforceData(locks=[_lock(T)], alerts=[]), CTX)
    assert drafts == [bruteforce_alert(user_id="u-1", username="an.nv", lock_start=T, source="m9_reconcile")]


def test_bruteforce_alert_of_other_subject_does_not_match() -> None:
    data = BruteforceData(locks=[_lock(T, "u-1"), _lock(T, "u-2")], alerts=[ExistingAlert("u-2", T + 3 * MS)])
    assert [d.subject for d in password_bruteforce(data, CTX)] == ["u-1"]


def test_bruteforce_ghost_username_subject_matches_auth() -> None:
    """Username ma lưu "h:" + HMAC (Q-3e-14) — subject tính bằng CHÍNH `bruteforce_subject` như auth."""
    ghost = "h:" + "a" * 64
    subject = bruteforce_subject(None, ghost)
    assert len(subject) <= SUBJECT_MAX
    lock = _lock(T, user_id=None, username=ghost)
    assert password_bruteforce(BruteforceData([lock], [ExistingAlert(subject, T + 3 * MS)]), CTX) == []
    assert [d.subject for d in password_bruteforce(BruteforceData([lock], []), CTX)] == [subject]


def test_bruteforce_waits_60s_before_reconciling() -> None:
    """Q-M9-B1-3: auth ghi sự kiện rồi mới ghi cảnh báo (hai transaction) — chỉ đối soát sự kiện cũ hơn 60 s."""
    assert password_bruteforce(BruteforceData([_lock(NOW - timedelta(seconds=59))], []), CTX) == []
    assert len(password_bruteforce(BruteforceData([_lock(NOW - timedelta(seconds=60))], []), CTX)) == 1


# ---- luật 9 ---------------------------------------------------------------------------------------


def test_refresh_reuse_detail_and_missing_user() -> None:
    drafts = refresh_reuse([sec(7, T, user_id="u-1", revoked_sessions=3)], CTX)
    assert dict(drafts[0].detail) == {"event_id": 7, "revoked_sessions": 3}
    odd = refresh_reuse([sec(8, T, user_id=None, revoked_sessions="nhiều")], CTX)  # sai kiểu → bỏ, không ép kiểu
    assert odd[0].subject == "event:8"
    assert dict(odd[0].detail) == {"event_id": 8}


def test_refresh_reuse_same_user_two_events_two_drafts() -> None:
    drafts = refresh_reuse([sec(1, T), sec(2, T + MS)], CTX)
    assert [d.window_start for d in drafts] == [T, T + MS]


# ---- luật 10: > 10 trong cửa sổ trượt đóng [t − 5 phút, t] -----------------------------------------


def test_permission_denied_ten_events_no_draft() -> None:
    assert permission_denied_burst(burst("u-1", T, n=10), CTX) == []


def test_permission_denied_eleventh_event_sets_window() -> None:
    """Sự kiện thứ 11 ở 08:00:10 (khung 08:00) dù đợt bắt đầu từ khung trước → window = khung của sự kiện thứ 11."""
    last = datetime(2026, 10, 1, 7, 50, 10, tzinfo=UTC)
    drafts = permission_denied_burst(burst("u-1", last, n=11, step=timedelta(seconds=20)), CTX)
    assert [(d.subject, d.window_start, d.value) for d in drafts] == [("u-1", datetime(2026, 10, 1, 7, 50, tzinfo=UTC), 11.0)]
    assert dict(drafts[0].detail) == {"count": 11, "threshold": 10}


def test_permission_denied_closed_window_boundary() -> None:
    """Q-M9-B1-2: 11 sự kiện trải ĐÚNG 5 phút → báo; 5 phút + 1 µs → không."""
    exact = burst("u-1", T, n=11, step=timedelta(seconds=30))
    assert len(permission_denied_burst(exact, CTX)) == 1
    over = [*exact[:-1], sec(99, T + US)]
    assert permission_denied_burst(over, CTX) == []


def test_permission_denied_many_events_one_bucket_one_draft() -> None:
    assert len(permission_denied_burst(burst("u-1", T, n=22, step=timedelta(seconds=5)), CTX)) == 1


def test_permission_denied_two_users_interleaved_two_drafts() -> None:
    """Hai người, mỗi người 11 lần, xen kẽ trong cùng khung → 2 cảnh báo (subject không được rỗng)."""
    events = burst("u-1", T) + burst("u-2", T + MS, first_id=50)
    assert sorted(d.subject for d in permission_denied_burst(events, CTX)) == ["u-1", "u-2"]


def test_permission_denied_without_user_id_uses_username_subject() -> None:
    """Đăng nhập có nhóm AD không ánh xạ được role: chỉ có username_attempted (auth/service.py)."""
    assert [d.subject for d in permission_denied_burst(burst(None, T, username="an.nv"), CTX)] == ["username:an.nv"]
    ghost = "h:" + "b" * 64
    drafts = permission_denied_burst(burst(None, T, username=ghost), CTX)
    assert [d.subject for d in drafts] == [bruteforce_subject(None, ghost)]
    assert len(drafts[0].subject) <= SUBJECT_MAX


def test_permission_denied_history_before_lookback_counts_but_trigger_must_be_inside() -> None:
    edge = NOW - LOOKBACK
    inside = burst("u-1", edge + timedelta(seconds=10), step=timedelta(seconds=20))  # 10 sự kiện trước mốc 24 giờ
    assert len(permission_denied_burst(inside, CTX)) == 1
    outside = burst("u-1", edge - US, step=timedelta(seconds=20))
    assert permission_denied_burst(outside, CTX) == []


# ---- luật 11 ---------------------------------------------------------------------------------------


def test_policy_saved_subject_version_fallback_and_length() -> None:
    long_version = "v" * 100
    drafts = policy_saved([
        sec(1, T, user_id="u-1", version="2026-10-01.3"),
        sec(2, T, user_id="u-1"),  # thiếu version
        sec(3, T, user_id="u-1", version=""),  # rỗng
        sec(4, T, user_id="u-1", version=True),  # sai kiểu
        sec(5, T, user_id="u-1", version=long_version),
        sec(6, T, user_id="u-1", version=12),
    ], CTX)  # fmt: skip
    subjects = [d.subject for d in drafts]
    assert subjects[:4] == ["2026-10-01.3", "event:2", "event:3", "event:4"]
    assert subjects[4].startswith("version#") and len(subjects[4]) <= SUBJECT_MAX
    assert subjects[5] == "12"


def test_policy_saved_two_saves_never_merged() -> None:
    drafts = policy_saved([sec(1, T, version="3"), sec(2, T, version="4"), sec(3, T + MS, version="4")], CTX)
    assert len(drafts) == 3


# ---- luật 15 ---------------------------------------------------------------------------------------


def test_finalize_failed_detail_and_parent_ticket_not_filtered() -> None:
    """Q-M9-B1-4: không lọc v_leaf — luật nhận cả ticket cha (loader không JOIN v_leaf), mỗi dòng một cảnh báo."""
    drafts = finalize_failed([FinalizeFailed("parent-1", T, "b20_audit"), FinalizeFailed("parent-1", T + MS, None)], CTX)
    assert [(d.subject, d.window_start, dict(d.detail)) for d in drafts] == [
        ("parent-1", T, {"ticket_id": "parent-1", "node": "b20_audit"}),
        ("parent-1", T + MS, {"ticket_id": "parent-1", "node": None}),
    ]


# ---- review #12 mục 3: message của exception không mang dữ liệu ----------------------------------

# Tên được phép xuất hiện trong message: định danh luật/hằng do code đặt, không phải dữ liệu đọc từ DB.
_ALLOWED_NAMES = {"rule_id", "every", "audience", "HOURS_7D", "SUBJECT_MAX"}
# Hàm phân tích chuỗi in nguyên giá trị đầu vào khi lỗi (`int("abc")` → "invalid literal … 'abc'").
_PARSERS = {"int", "float", "Decimal", "loads", "fromisoformat", "strptime", "UUID"}
# Miễn tường minh: đầu vào đã kiểm là số nguyên trước khi `float(...)` (B0) — không có chuỗi nào từ DB đi qua.
_NUMERIC_ONLY = {"hourly_median"}


def _message_ok(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return node.id in _ALLOWED_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in _ALLOWED_NAMES
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
        return True  # một số đếm, không phải giá trị
    if isinstance(node, ast.JoinedStr):
        return all(_message_ok(v.value) if isinstance(v, ast.FormattedValue) else True for v in node.values)
    return False


@pytest.mark.parametrize("module", [rules, evaluator])
def test_error_messages_carry_no_data(module: Any) -> None:
    """`evaluate` ghi `log.exception` (cả traceback) khi luật/loader lỗi — message chỉ được mang tên luật/hằng.
    GĐ2 thêm `queries/rules_data.py` vào danh sách."""
    tree = ast.parse(inspect.getsource(module))
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)]
    assert raises  # quét không rỗng
    bad = [n.lineno for n in raises for a in [*n.exc.args, *(k.value for k in n.exc.keywords)] if not _message_ok(a)]  # type: ignore[union-attr]
    assert bad == []
    scanned = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name not in _NUMERIC_ONLY]
    parsers = [
        c.lineno for f in scanned for c in ast.walk(f)
        if isinstance(c, ast.Call)
        and ((isinstance(c.func, ast.Name) and c.func.id in _PARSERS)
             or (isinstance(c.func, ast.Attribute) and c.func.attr in _PARSERS))
    ]  # fmt: skip
    assert parsers == []
