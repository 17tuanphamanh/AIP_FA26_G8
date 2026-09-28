"""b25 — lọc quyền truy hồi (thiết kế Phase 3 mục 6.5, 3-Q5; Q-3b-6 — cũng là c2 của 3c)."""

import ast
from pathlib import Path

import pytest
from app.domain.context import Role
from app.rag.filters import (
    allowed_sensitivity,
    base_filter,
    intent_filter,
    query_filter,
)
from qdrant_client.models import FieldCondition, MatchAny, MatchValue


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


# ---- 3c: intent_filter, query_filter (c2 mở rộng) -----------------------------------------------


def test_intent_filter_matches_intent_or_general() -> None:
    cond = intent_filter("vpn")
    assert cond.key == "request_type"
    assert cond.match == MatchAny(any=["vpn", "general"])


def test_query_filter_is_base_filter_plus_extra() -> None:
    extra = FieldCondition(key="doc_id", match=MatchValue(value="KB-VPN-001"))
    flt = query_filter("employee", extra)
    assert flt.must == [*base_filter("employee"), extra]


def test_query_filter_without_extra_equals_base_filter() -> None:
    assert query_filter("l1").must == base_filter("l1")


# ---- c36: `Filter(` chỉ được gọi ở rag/filters.py, trong toàn bộ backend/app/rag/** --------------


def _files_calling_filter(rag_dir: Path) -> dict[str, list[int]]:
    hits: dict[str, list[int]] = {}
    for path in sorted(rag_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Filter"
        ]
        if lines:
            hits[str(path.relative_to(rag_dir))] = lines
    return hits


def test_filter_constructor_called_only_in_filters_py() -> None:
    import app.rag

    rag_dir = Path(app.rag.__file__).parent
    files = sorted(p for p in rag_dir.rglob("*.py"))
    assert len(files) >= 10, "tập file quét app/rag/** rỗng bất thường"
    hits = _files_calling_filter(rag_dir)
    assert set(hits) == {"filters.py"}
    assert hits["filters.py"] != []
