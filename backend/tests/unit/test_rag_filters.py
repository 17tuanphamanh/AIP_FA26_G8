"""b25 — lọc quyền truy hồi (thiết kế Phase 3 mục 6.5, 3-Q5; Q-3b-6 — cũng là c2 của 3c)."""

import pytest
from app.domain.context import Role
from app.rag.filters import allowed_sensitivity, base_filter
from qdrant_client.models import MatchAny, MatchValue


@pytest.mark.parametrize(("role", "expected"), [
    ("employee", ["public", "internal"]),
    ("l1", ["public", "internal", "restricted"]),
    ("l2", ["public", "internal", "restricted"]),
    ("manager", ["public", "internal", "restricted"]),
])  # fmt: skip
def test_allowed_sensitivity_per_role(role: Role, expected: list[str]) -> None:
    assert allowed_sensitivity(role) == expected


def test_every_domain_role_is_mapped() -> None:
    import typing

    assert set(typing.get_args(Role)) == {"employee", "l1", "l2", "manager"}


@pytest.mark.parametrize("role", ["", "admin", "EMPLOYEE", "khach"])
def test_unknown_role_gets_least(role: str) -> None:
    assert allowed_sensitivity(role) == ["public"]


def test_base_filter_has_enabled_and_sensitivity() -> None:
    conds = base_filter("employee")
    by_key = {c.key: c.match for c in conds}
    assert set(by_key) == {"enabled", "sensitivity"}
    assert by_key["enabled"] == MatchValue(value=True)
    assert by_key["sensitivity"] == MatchAny(any=["public", "internal"])


def test_allowed_list_is_a_copy() -> None:
    allowed_sensitivity("l1").append("secret")
    assert allowed_sensitivity("l1") == ["public", "internal", "restricted"]
