"""M9-B1 GĐ1: 7 luật theo sự kiện (2, 3, 9, 10, 11, 15, 16) — hàm thuần, dữ liệu giả, không DB.

Nguồn: file chia việc M9 mục 6 (B1, bảng nguồn đã kiểm); kế hoạch chung M9 mục 4.4, 6; chốt Q-M9-B1-1…9 ở #13.
Loader SQL + test Postgres của từng luật là GĐ2 (cần `v_leaf` của A1).
"""

import ast
import inspect
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.audit.alerts import check_alert
from app.domain.alerts import (
    BRUTEFORCE_RULE_ID,
    SUBJECT_MAX,
    AlertDraft,
    bruteforce_alert,
    bruteforce_subject,
)
from app.monitor import evaluator, rules
from app.monitor.queries import rules_data
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
BURST = timedelta(minutes=5)
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


def _auth(subject: str, at: datetime, rule_id: str = BRUTEFORCE_RULE_ID) -> ExistingAlert:
    """Dòng `alerts` auth/B01 đã ghi (cùng `bruteforce_alert` → rule_id `password_bruteforce`)."""
    return ExistingAlert(rule_id=rule_id, subject=subject, window_start=at)


@pytest.mark.parametrize("skew", [3 * MS, -3 * MS, timedelta(seconds=60), -timedelta(seconds=60)])
def test_bruteforce_auth_already_wrote_no_draft(skew: timedelta) -> None:
    """Auth ghi cảnh báo với `now` của auth, lệch vài ms so với occurred_at (hai lần gọi đồng hồ) → không thêm."""
    data = BruteforceData(locks=[_lock(T)], alerts=[_auth("u-1", T + skew)])
    assert password_bruteforce(data, CTX) == []


@pytest.mark.parametrize("skew", [timedelta(seconds=60) + US, -timedelta(seconds=60) - US])
def test_bruteforce_tolerance_boundary_just_outside(skew: timedelta) -> None:
    data = BruteforceData(locks=[_lock(T)], alerts=[_auth("u-1", T + skew)])
    assert len(password_bruteforce(data, CTX)) == 1


def test_bruteforce_missing_auth_row_draft_equals_shared_builder() -> None:
    """Không có cảnh báo khớp → đúng cảnh báo auth sẽ ghi, chỉ khác lock_start = occurred_at và source."""
    drafts = password_bruteforce(BruteforceData(locks=[_lock(T)], alerts=[]), CTX)
    assert drafts == [bruteforce_alert(user_id="u-1", username="an.nv", lock_start=T, source="m9_reconcile")]


def test_bruteforce_alert_of_other_subject_does_not_match() -> None:
    data = BruteforceData(locks=[_lock(T, "u-1"), _lock(T, "u-2")], alerts=[_auth("u-2", T + 3 * MS)])
    assert [d.subject for d in password_bruteforce(data, CTX)] == ["u-1"]


@pytest.mark.parametrize("other", ["refresh_reuse", "permission_denied_burst"])
def test_bruteforce_other_rule_id_same_subject_still_drafts(other: str) -> None:
    """Review #13: luật 3 tự kiểm rule_id. Cảnh báo luật khác (subject của luật 9/10 cũng là user_id) cùng người,
    lệch 3 ms không được che đợt khoá — kể cả khi loader GĐ2 quên lọc rule_id."""
    lock = _lock(T)
    assert len(password_bruteforce(BruteforceData([lock], [_auth("u-1", T + 3 * MS, rule_id=other)]), CTX)) == 1
    assert password_bruteforce(BruteforceData([lock], [_auth("u-1", T + 3 * MS)]), CTX) == []


def test_bruteforce_ghost_username_subject_matches_auth() -> None:
    """Username ma lưu "h:" + HMAC (Q-3e-14) — subject tính bằng CHÍNH `bruteforce_subject` như auth."""
    ghost = "h:" + "a" * 64
    subject = bruteforce_subject(None, ghost)
    assert len(subject) <= SUBJECT_MAX
    lock = _lock(T, user_id=None, username=ghost)
    assert password_bruteforce(BruteforceData([lock], [_auth(subject, T + 3 * MS)]), CTX) == []
    assert [d.subject for d in password_bruteforce(BruteforceData([lock], []), CTX)] == [subject]


def test_bruteforce_waits_60s_before_reconciling() -> None:
    """Q-M9-B1-3: auth ghi sự kiện rồi mới ghi cảnh báo (hai transaction) — chỉ đối soát sự kiện cũ hơn 60 s."""
    assert password_bruteforce(BruteforceData([_lock(NOW - timedelta(seconds=59))], []), CTX) == []
    assert len(password_bruteforce(BruteforceData([_lock(NOW - timedelta(seconds=60))], []), CTX)) == 1


@pytest.mark.parametrize("at", [0, 1, 3], ids=["dau", "giua", "cuoi"])
def test_bruteforce_several_alerts_same_subject_any_one_matches(at: int) -> None:
    """Tra theo subject giữ MỌI cảnh báo của subject (nhiều đợt khoá/ngày): một cái khớp ±60 s là đủ. Review #24: cảnh
    báo khớp ở đầu / giữa / cuối danh sách — dict chỉ giữ cảnh báo cuối hoặc chỉ giữ cảnh báo đầu đều đỏ."""
    far = [_auth("u-1", T - timedelta(hours=k)) for k in (1, 2, 3)]
    assert len(password_bruteforce(BruteforceData([_lock(T)], far), CTX)) == 1
    alerts = list(far)
    alerts.insert(at, _auth("u-1", T + 3 * MS))
    assert password_bruteforce(BruteforceData([_lock(T)], alerts), CTX) == []


def test_bruteforce_many_locks_many_alerts_fast() -> None:
    """Review #20 mục 3: bản cũ duyệt khoá × cảnh báo. Đo 02/10 trên máy dev: 20k × 20k bản cũ 13,5 s, bản dict 0,06 s
    → ngưỡng 1 s (bản cũ chậm hơn ngưỡng ~13 lần). Mỗi khoá/cảnh báo một subject riêng, không cái nào khớp → bản cũ phải
    duyệt hết `alerts` cho mỗi khoá. Chạy tối đa 3 lần, dừng khi có một lần đạt (như test 50k)."""
    n = 20_000
    locks = [sec(i, T - timedelta(seconds=i % 3000), user_id=f"u-{i}", reason="threshold") for i in range(n)]
    alerts = [_auth(f"x-{i}", T) for i in range(n)]
    timings: list[float] = []
    drafts: list[AlertDraft] = []
    for _ in range(3):
        start = time.perf_counter()
        drafts = password_bruteforce(BruteforceData(locks, alerts), CTX)
        timings.append(time.perf_counter() - start)
        if timings[-1] < 1.0:
            break
    assert timings[-1] < 1.0, timings
    assert len(drafts) == n  # nhanh không phải vì bỏ việc


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
    """Sự kiện thứ 11 ở 07:50:10 (khung 07:50) dù đợt bắt đầu từ khung trước (07:46:50) → window = khung của sự kiện
    thứ 11."""
    last = datetime(2026, 10, 1, 7, 50, 10, tzinfo=UTC)
    drafts = permission_denied_burst(burst("u-1", last, n=11, step=timedelta(seconds=20)), CTX)
    assert [(d.subject, d.window_start, d.value) for d in drafts] == [("u-1", datetime(2026, 10, 1, 7, 50, tzinfo=UTC), 11.0)]
    assert dict(drafts[0].detail) == {"count": 11, "threshold": 10}


def test_permission_denied_closed_window_boundary() -> None:
    """Q-M9-B1-2: 11 sự kiện trải ĐÚNG 5 phút → báo; 5 phút + 1 µs → không."""
    exact = burst("u-1", T, n=11, step=timedelta(seconds=30))
    drafts = permission_denied_burst(exact, CTX)
    assert len(drafts) == 1
    assert drafts[0].value == 11 and drafts[0].detail["count"] == 11  # sự kiện đúng t − 5 phút được ĐẾM
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


def test_permission_denied_shuffled_input_same_result() -> None:
    """(a) Loader không hứa thứ tự: một đợt cố định, đưa vào đã sắp hay xáo trộn đều ra cùng kết quả."""
    ordered = burst("u-1", T, n=15)
    shuffled = list(ordered)
    random.Random(13).shuffle(shuffled)
    assert shuffled != ordered
    expected = [(d.subject, d.window_start, d.value) for d in permission_denied_burst(ordered, CTX)]
    assert [(d.subject, d.window_start, d.value) for d in permission_denied_burst(shuffled, CTX)] == expected
    assert expected == [("u-1", bucket_start(T, 5), 11)]


def test_permission_denied_burst_across_bucket_boundary_two_drafts() -> None:
    """(c) Đợt vắt qua ranh giới khung 5 phút → 2 cảnh báo (báo thừa, chấp nhận — docstring luật 10). 12 sự kiện cách
    10 s, cả đợt TRƯỚC ctx.now (08:00): thứ 11 ở 07:54:55 (khung 07:50), thứ 12 ở 07:55:05 (khung 07:55)."""
    events = burst("u-1", datetime(2026, 10, 1, 7, 55, 5, tzinfo=UTC), n=12, step=timedelta(seconds=10))
    drafts = permission_denied_burst(events, CTX)
    assert [(d.window_start, d.value) for d in drafts] == [
        (datetime(2026, 10, 1, 7, 50, tzinfo=UTC), 11),
        (datetime(2026, 10, 1, 7, 55, tzinfo=UTC), 12),
    ]


def _at(*offsets: timedelta, user_id: str = "u-1", first_id: int = 0) -> list[SecurityEvent]:
    return [sec(first_id + i, T + o, user_id) for i, o in enumerate(offsets)]


@pytest.mark.parametrize(("at_t", "expected"), [(2, []), (3, [11]), (5, [13])], ids=["duoi", "bang", "vuot"])
def test_permission_denied_ties_and_exact_edges(at_t: int, expected: list[int]) -> None:
    """(e) Một sự kiện ĐÚNG t − 5 phút, 7 sự kiện giữa, `at_t` sự kiện TRÙNG thời điểm t: tổng 10 → không báo;
    11 → value 11; 13 → value 13 (đếm cả sự kiện trùng t đứng SAU sự kiện kích hoạt). Hai đối tượng → 2 draft."""
    offsets = [-BURST, *(-timedelta(seconds=30 * k) for k in range(1, 8)), *([timedelta(0)] * at_t)]
    one = permission_denied_burst(_at(*offsets), CTX)
    assert [d.value for d in one] == expected
    assert all(d.window_start == bucket_start(T, 5) for d in one)
    two = permission_denied_burst(_at(*offsets) + _at(*offsets, user_id="u-2", first_id=100), CTX)
    assert sorted((d.subject, d.value) for d in two) == [(u, v) for u in ("u-1", "u-2") for v in expected]


def test_permission_denied_counts_events_before_lookback() -> None:
    """(g) Loader GĐ2 đọc lùi thêm 5 phút: 3 sự kiện đầu TRƯỚC mốc now − 24h vẫn được ĐẾM; sự kiện thứ 11 sau mốc →
    1 draft, value 11. Lọc 24 giờ trước khi đếm sẽ chỉ còn 8 → bỏ sót."""
    edge = NOW - LOOKBACK
    before = [edge - timedelta(seconds=s) for s in (90, 60, 30)]
    after = [edge + timedelta(seconds=10 + 20 * k) for k in range(8)]  # thứ 11 ở edge + 150 s
    drafts = permission_denied_burst([sec(i, t) for i, t in enumerate(before + after)], CTX)
    assert [(d.window_start, d.value) for d in drafts] == [(bucket_start(after[-1], 5), 11)]


def _reference_burst(data: list[SecurityEvent], ctx: RuleContext) -> list[tuple[str, datetime, int]]:
    """Bản vét cạn viết thẳng từ định nghĩa — không bisect, không gọi luật (chỉ `bruteforce_subject`, `bucket_start`):
    mỗi đối tượng, mỗi sự kiện t: đếm trên MỌI sự kiện được truyền vào số x có t − 5′ ≤ x ≤ t; kích hoạt khi đếm ≥ 11
    VÀ t ≥ now − 24h; khử trùng theo (subject, khung), giữ lần kích hoạt sớm nhất."""
    by: dict[str, list[datetime]] = {}
    for e in data:
        by.setdefault(bruteforce_subject(e.user_id, e.username or ""), []).append(e.occurred_at)
    out: list[tuple[str, datetime, int]] = []
    for subject, times in by.items():
        first: dict[datetime, tuple[datetime, int]] = {}  # khung → (t kích hoạt sớm nhất, số đếm)
        for t in times:
            count = sum(1 for x in times if t - BURST <= x <= t)
            if count < 11 or t < ctx.now - LOOKBACK:
                continue
            bucket = bucket_start(t, 5)
            if bucket not in first or t < first[bucket][0]:
                first[bucket] = (t, count)
        out.extend((subject, bucket, count) for bucket, (_, count) in sorted(first.items()))
    return out


@pytest.mark.parametrize("seed", range(30))
def test_permission_denied_matches_brute_force_reference(seed: int) -> None:
    """(d) Dữ liệu ngẫu nhiên, seed cố định: 3 đối tượng (một không user_id), thời điểm làm tròn giây (nhiều sự kiện
    trùng), cụm quanh mốc now − 24h và sau ctx.now, cụm dày quanh ngưỡng — so TOÀN BỘ (subject, khung, value)."""
    rng = random.Random(seed)
    who = [("u-1", None), ("u-2", None), (None, "an.nv")]
    centers = [NOW - LOOKBACK - timedelta(minutes=2), NOW + timedelta(minutes=1)]
    centers += [NOW - timedelta(seconds=rng.randint(0, 24 * 3600)) for _ in range(6)]
    data: list[SecurityEvent] = []
    for c in centers:
        user_id, username = rng.choice(who)
        for _ in range(rng.randint(6, 24)):
            data.append(sec(len(data), c + timedelta(seconds=rng.randint(0, 400)), user_id=user_id, username=username))
    rng.shuffle(data)
    got = [(d.subject, d.window_start, d.value) for d in permission_denied_burst(data, CTX)]
    assert got == _reference_burst(data, CTX)


def test_permission_denied_50k_one_subject_under_5s() -> None:
    """(f) Review #13: bản O(n²) cũ ~116 s cho 50k (hàm đồng bộ → treo event loop worker). Chạy tối đa 3 lần, dừng
    ngay khi có một lần < 5 s (Q-M9-B1-10; nới 1 s → 5 s theo review #20 — vẫn cách bản cũ ~23 lần, tránh flaky trên CI).
    Đồng hồ chỉ dùng trong test — luật không đọc đồng hồ."""
    n = 50_000
    data = [sec(i, NOW - i * (LOOKBACK / n)) for i in range(n)]
    timings: list[float] = []
    drafts: list[AlertDraft] = []
    for _ in range(3):
        start = time.perf_counter()
        drafts = permission_denied_burst(data, CTX)
        timings.append(time.perf_counter() - start)
        if timings[-1] < 5.0:
            break
    assert timings[-1] < 5.0, timings
    assert drafts  # đợt dày suốt 24 giờ → có cảnh báo (nhanh không phải vì không làm gì)


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


@pytest.mark.parametrize(("module", "min_async"), [(rules, 0), (evaluator, 0), (rules_data, 15)])
def test_error_messages_carry_no_data(module: Any, min_async: int) -> None:
    """`evaluate` ghi `log.exception` (cả traceback) khi luật/loader lỗi — message chỉ được mang tên luật/hằng.
    GĐ2 (Q-M9-B1-17): thêm `queries/rules_data.py`; quét cả `async def` (loader là async — chỉ quét `def` thì loader
    lọt). `rules_data` không có `raise` → "quét không rỗng" của nó là ≥ 15 hàm async (7 loader B1 + 3 loader B2 phút +
    5 loader B2 giờ/ngày)."""
    tree = ast.parse(inspect.getsource(module))
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)]
    if module is not rules_data:
        assert raises  # quét không rỗng
    bad = [n.lineno for n in raises for a in [*n.exc.args, *(k.value for k in n.exc.keywords)] if not _message_ok(a)]  # type: ignore[union-attr]
    assert bad == []
    scanned = [
        f for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef) and f.name not in _NUMERIC_ONLY
    ]  # fmt: skip
    assert len([f for f in scanned if isinstance(f, ast.AsyncFunctionDef)]) >= min_async
    parsers = [
        c.lineno for f in scanned for c in ast.walk(f)
        if isinstance(c, ast.Call)
        and ((isinstance(c.func, ast.Name) and c.func.id in _PARSERS)
             or (isinstance(c.func, ast.Attribute) and c.func.attr in _PARSERS))
    ]  # fmt: skip
    assert parsers == []
