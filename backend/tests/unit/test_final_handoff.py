"""Hàm thuần của M7 cho B20: `summarize_final` / `resolution_path` (Q-A), `build_handoff` (B20 4.2, Q-D),
mẫu `config/escalation_templates.yaml` (đủ E0–E9, không rỗng)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.audit.final import resolution_path, summarize_final
from app.audit.handoff import build_handoff, is_deny_case
from app.domain.exit_codes import ExitCode
from app.domain.states import S_BLOCKED, S_ESCALATED, S_REJECTED, S_RESOLVED
from app.graph.fakes import FAKE_ACTION, fake_requester, fake_risk
from app.settings import (
    get_escalation_templates,
    get_settings,
    load_escalation_templates,
)
from pydantic import ValidationError

T0 = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)
TEMPLATES = get_escalation_templates()


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"status": S_ESCALATED, "need_type": "info"}, "escalated"),  # E8 sau deflect vẫn escalated
        ({"status": S_ESCALATED, "approval_result": "approved"}, "escalated"),
        ({"status": S_REJECTED}, "rejected"),
        ({"status": S_BLOCKED}, None),
        ({"status": S_RESOLVED, "need_type": "info"}, "deflected"),
        ({"status": S_RESOLVED, "approval_result": "approved"}, "approved"),
        ({"status": S_RESOLVED, "need_type": "action"}, "auto"),
        ({"status": S_RESOLVED, "is_parent": True}, None),  # D-30
        ({"status": S_ESCALATED, "is_parent": True}, None),
    ],
)
def test_resolution_path_table(state: dict[str, Any], expected: str | None) -> None:
    assert resolution_path(state) == expected


def test_resolution_path_rejects_non_terminal_state() -> None:
    with pytest.raises(ValueError, match="trạng thái kết thúc"):
        resolution_path({"status": "S_ASSESSING"})


def test_summarize_final() -> None:
    state = {"status": S_RESOLVED, "close_reason": "resolved_auto_timeout_48h", "intent": "vpn",
             "slots": {"device_id": "LAP-1"}, "need_type": "action"}  # fmt: skip
    s = summarize_final(state, created_at=T0, total_turns=3, now=T0 + timedelta(hours=49))
    assert (s.final_state, s.resolution_path, s.auto_closed, s.total_turns) == (
        S_RESOLVED, "auto", True, 3)
    assert s.total_duration_seconds == 49 * 3600 and s.closed_at == T0 + timedelta(hours=49)
    assert s.slots == {"device_id": "LAP-1"} and s.intent == "vpn"


def test_handoff_four_parts_from_state() -> None:
    state = {
        "exit_code": "E5", "redacted_request": "Cấp quyền [REDACTED] thư mục Finance",
        "requester_context": fake_requester("nv001", T0), "intent": "access",
        "intent_confidence": 0.91, "diagnostics": {"check_folder_acl": {}},
        "intended_action": FAKE_ACTION, "risk": fake_risk("ESCALATE_L2"),
        "escalation_reason_detail": "rule_deny",
    }  # fmt: skip
    note = build_handoff(state, TEMPLATES)
    assert note.request == "Cấp quyền [REDACTED] thư mục Finance"
    assert "access" in note.done_so_far and "check_folder_acl" in note.done_so_far
    assert "vpn_reset_session" in note.done_so_far  # Action nằm ở phần (2), không ở (1)
    assert note.why_escalated.startswith("E5") and "rule_deny" in note.why_escalated
    assert "luật FAKE" in note.why_escalated
    assert note.next_for_l2.endswith(TEMPLATES.deny_warning)


def test_handoff_minimal_state_is_never_empty() -> None:
    note = build_handoff({"exit_code": "E2"}, TEMPLATES)
    assert note.request == "(không có nội dung yêu cầu)"
    assert note.done_so_far == "Chưa thực hiện bước xử lý nào."
    assert TEMPLATES.deny_warning not in note.next_for_l2


def test_only_e5_is_deny_case() -> None:
    assert [c.value for c in ExitCode if is_deny_case(c.value)] == ["E5"]


def test_templates_file_covers_every_code() -> None:
    for code in ExitCode:
        t = TEMPLATES.of(code.value)
        assert t.user_message.strip() and t.next_for_l2.strip()


@pytest.mark.parametrize("breakage", ["drop_E3", "empty_message", "extra_key"])
def test_templates_schema_rejects(tmp_path: Path, breakage: str) -> None:
    source = get_settings().config_dir / "escalation_templates.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if breakage == "drop_E3":
        del data["codes"]["E3"]
    elif breakage == "empty_message":
        data["codes"]["E7"]["user_message"] = ""
    else:
        data["codes"]["E1"]["tone"] = "x"
    broken = tmp_path / "t.yaml"
    broken.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_escalation_templates(broken)
