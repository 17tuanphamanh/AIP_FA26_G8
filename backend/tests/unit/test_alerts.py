"""Cảnh báo (`domain/alerts.py`, `audit/alerts.py`): khoá chống trùng có người dùng (Q1), không lộ bí mật."""

from datetime import UTC, datetime

import pytest
from app.audit.alerts import check_alert
from app.domain.alerts import (
    SUBJECT_MAX,
    SYSTEM_SUBJECT,
    AlertDraft,
    bruteforce_alert,
    bruteforce_subject,
)

T = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)


def test_bruteforce_key_same_for_login_and_b1() -> None:
    login = bruteforce_alert(user_id="nv001", username="an.nv", lock_start=T, source="login")
    b1 = bruteforce_alert(user_id="nv001", username="an.nv", lock_start=T, source="B1", ticket_id="t")
    keys = {(a.rule_id, a.subject, a.window_start) for a in (login, b1)}
    assert keys == {("password_bruteforce", "nv001", T)}


def test_bruteforce_subject_for_unknown_and_long_usernames() -> None:
    assert bruteforce_subject("nv001", "an.nv") == "nv001"
    assert bruteforce_subject(None, "x.y") == "username:x.y"
    long_a, long_b = "a" * 100 + "1", "a" * 100 + "2"
    sa, sb = bruteforce_subject(None, long_a), bruteforce_subject(None, long_b)
    assert len(sa) <= SUBJECT_MAX and len(sb) <= SUBJECT_MAX and sa != sb  # không cắt cụt gây gộp


@pytest.mark.parametrize(
    ("draft", "message"),
    [
        (AlertDraft("", SYSTEM_SUBJECT, T, "warning"), "rule_id"),
        (AlertDraft("r", "x" * (SUBJECT_MAX + 1), T, "warning"), "subject"),
        (AlertDraft("r", SYSTEM_SUBJECT, T.replace(tzinfo=None), "warning"), "múi giờ"),
        (AlertDraft("r", SYSTEM_SUBJECT, T, "warning", detail={"password": "x"}), "nhạy cảm"),
        (AlertDraft("r", SYSTEM_SUBJECT, T, "warning", detail={"note": "eyJhbGciOi.eyJzdWIi.sig"}), "token"),
    ],
)
def test_check_alert_rejects(draft: AlertDraft, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_alert(draft)
