"""Action, RequesterContext, TicketState: kiểu chặt, frozen, reducer hội thoại."""

import typing
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef, TicketState, append_capped
from pydantic import ValidationError

ACTION: dict[str, Any] = {
    "type": "reset_password",
    "target": "user:nv001",
    "requested_for": "nv001",
    "scope": "single_account",
    "privilege_level": "standard_user",
    "reversible": True,
    "reversibility": "full",
    "data_sensitivity": "medium",
    "params": {},
    "facts": {"target_is_self": True},
}

REQUESTER: dict[str, Any] = {
    "user_id": "nv001",
    "role": "employee",
    "department": "finance",
    "manager_id": "nv100",
    "employment_status": "active",
    "tenure_days": 400,
    "is_privileged_account": False,
    "captured_at": datetime(2026, 9, 25, tzinfo=UTC),
}


def test_action_is_frozen() -> None:
    action = Action(**ACTION)
    with pytest.raises(ValidationError):
        action.target = "user:admin"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "bad"),
    [("scope", "everything"), ("privilege_level", "root"), ("data_sensitivity", "secret")],
)
def test_action_rejects_unknown_literal(field: str, bad: str) -> None:
    with pytest.raises(ValidationError):
        Action(**{**ACTION, field: bad})


def test_action_requires_every_field() -> None:
    for missing in ACTION:
        with pytest.raises(ValidationError):
            Action(**{k: v for k, v in ACTION.items() if k != missing})


def test_requester_context_frozen_and_from_ad() -> None:
    ctx = RequesterContext(**REQUESTER)
    assert ctx.source == "ad"
    with pytest.raises(ValidationError):
        ctx.role = "l1"  # type: ignore[misc]


def test_requester_role_limited_to_four() -> None:
    with pytest.raises(ValidationError):
        RequesterContext(**{**REQUESTER, "role": "admin"})


def test_ticket_state_has_no_raw_request() -> None:
    # D-07: raw không vào state, chỉ redacted_request.
    fields = typing.get_type_hints(TicketState)
    assert "raw_request" not in fields
    assert "redacted_request" in fields


def test_chunk_excerpt_capped_600() -> None:
    base: dict[str, Any] = {"chunk_id": "c", "doc_id": "d", "version": 1, "seq": 0, "title": "t",
            "heading_path": "h", "score": 0.9}  # fmt: skip
    ChunkRef(**base, excerpt="x" * 600)
    with pytest.raises(ValidationError):
        ChunkRef(**base, excerpt="x" * 601)


def test_append_capped_keeps_last_n() -> None:
    reducer: Callable[[list[int], list[int]], list[int]] = append_capped(3)
    assert reducer([1, 2], [3]) == [1, 2, 3]
    assert reducer([1, 2, 3], [4, 5]) == [3, 4, 5]
    assert reducer([], []) == []


def test_append_capped_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        append_capped(0)
