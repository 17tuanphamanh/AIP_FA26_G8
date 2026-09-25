"""B01 unit: `RequesterContext.from_ad` — tenure_days đúng, model frozen; nhóm AD → role (P6 mục 3)."""

from datetime import UTC, date, datetime

import pytest
from app.core.errors import DomainError
from app.domain.context import RequesterContext, role_from_groups
from app.tools.models import AdUser
from pydantic import ValidationError
from tests.fakes.auth import FakeAdUser

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("groups", "role"),
    [
        (["IT-Users"], "employee"),
        (["IT-Users", "IT-L1"], "l1"),
        (["IT-Users", "IT-Manager"], "manager"),
        (["IT-Users", "IT-L2"], "l2"),
        (["IT-L1"], "l1"),
        (["IT-Users", "Finance-Share"], "employee"),  # nhóm lạ bị bỏ qua
        (["IT-Users", "IT-L1", "IT-L2"], None),  # > 1 nhóm đặc quyền → fail-closed
        (["IT-Users", "IT-L1", "IT-Manager"], None),
        ([], None),
        (["Finance-Share"], None),
    ],
)
def test_role_from_groups(groups: list[str], role: str | None) -> None:
    assert role_from_groups(groups) == role


def test_from_ad_tenure_days_and_frozen() -> None:
    user = FakeAdUser("nv003", "chau.hm", ["IT-Users"], "fin_head", department="finance",
                      employment_status="probation", hired_at=date(2026, 8, 17))  # fmt: skip
    ctx = RequesterContext.from_ad(user, now=NOW)
    assert ctx.tenure_days == 40
    assert (ctx.user_id, ctx.role, ctx.department, ctx.manager_id) == ("nv003", "employee", "finance", "fin_head")
    assert ctx.employment_status == "probation" and ctx.source == "ad" and ctx.captured_at == NOW
    with pytest.raises(ValidationError):
        ctx.role = "manager"  # type: ignore[misc]


def test_from_ad_accepts_tool_model_and_hired_today() -> None:
    raw = {
        "user_id": "it_mgr01", "username": "quan.tm", "full_name": "Q", "title": "Trưởng BP",
        "department": "it", "groups": ["IT-Users", "IT-Manager"], "manager_id": None,
        "employment_status": "active", "hired_at": "2026-09-26", "is_privileged_account": False,
        "account": {"account_type": "ad", "enabled": True, "locked": False, "lock_reason": None,
                    "password_last_set": "2026-09-01T00:00:00Z"},
    }  # fmt: skip
    ctx = RequesterContext.from_ad(AdUser.model_validate(raw), now=NOW)
    assert ctx.role == "manager" and ctx.tenure_days == 0


def test_from_ad_unmappable_groups_is_domain_error() -> None:
    with pytest.raises(DomainError):
        RequesterContext.from_ad(FakeAdUser("x", "x", ["IT-L1", "IT-L2"]), now=NOW)
