"""Q3 M6 (ĐP 09/11): cài phần mềm mà máy ĐÃ có sẵn → báo "đã có sẵn", không nói "Đã cài".

Bằng chứng (demo): "Cài phần mềm cho em" + "Zoom" → "Đã cài zoom phiên bản 6.1 lên máy LAP-0342" — máy đã có Zoom 6.1 từ trước, mock trả
`already_installed: true`, không cài gì → bot nói sai sự thật. Nay:
- `InstallResult.already_installed` (bool, mặc định False) đọc từ đầu ra tool; executor chuyển vào `outputs["already_installed"] = "true"`
  (chỉ khi True; `EXEC_OUTPUT_PATTERNS` chỉ nhận đúng "true").
- B18: `install_software` + cờ → mẫu "{phần mềm} đã có sẵn trên {máy} (phiên bản {v}), mình không cài lại. Nếu {phần mềm} không mở được,
  bạn chọn "Chưa ổn" để mình chuyển kỹ thuật viên."; audit `executed_ok` có `already_installed` (bool).
"""

from typing import Any

import pytest
from app.domain.messages import already_installed_text, result_text
from app.domain.states import S_CONFIRMING, S_EXECUTING
from app.domain.ticket_state import ExecutionResult
from app.graph.nodes import b17_execute
from app.risk.models import RuleVerdict
from app.tools.models import InstallResult
from tests.unit._t24 import action
from tests.unit.test_b17_t24 import Env, _requester

ZOOM = action("install_software")  # zoom lên LAP-0342 của nv001
ALREADY = ('Zoom đã có sẵn trên máy LAP-0342 (phiên bản 6.1), mình không cài lại. Nếu Zoom không mở được, bạn chọn "Chưa ổn" để '
           "mình chuyển kỹ thuật viên.")  # fmt: skip
NOW_ISO = "2026-09-29T03:00:00+00:00"
# Ca này chỉ kiểm tin B18 — luật kiểm lại ở B17 cho qua bằng verdict `allow` giả (khuôn test_b17_execute: monkeypatch `evaluate`).
ALLOW = RuleVerdict(matched=True, decision="allow", rule_id="R11", all_matched=["R11"], description="Cho phép")


def _install(**over: Any) -> InstallResult:
    return InstallResult.model_validate({"device_id": "LAP-0342", "name": "zoom", "version": "6.1", "installed_at": NOW_ISO,
                                         **over})  # fmt: skip


# ---- tool model + executor outputs ------------------------------------------------------------------------------------------


def test_install_result_reads_flag_default_false() -> None:
    assert _install(already_installed=True).already_installed is True
    assert _install(already_installed=False).already_installed is False
    assert _install().already_installed is False  # mock/AD cũ thiếu trường → coi là cài mới (như trước)


def test_executor_outputs_flag_only_when_true() -> None:
    env = Env()
    assert env.executor._outputs([_install(already_installed=True)]) == {"software": "zoom", "version": "6.1",
                                                                         "already_installed": "true"}  # fmt: skip
    assert env.executor._outputs([_install(already_installed=False)]) == {"software": "zoom", "version": "6.1"}


@pytest.mark.parametrize("value", ["true"])
def test_execution_result_keeps_true(value: str) -> None:
    res = ExecutionResult(success=True, steps_done=["install_software"], failed_step=None, rollback_status="none_needed",
                          rollback_details=[], action_plan_hash_matched=None, handoff_note=None,
                          outputs={"already_installed": value})  # fmt: skip
    assert res.outputs == {"already_installed": "true"}


@pytest.mark.parametrize("value", ["false", "True", "yes", "1", True])
def test_execution_result_drops_other_values(value: Any) -> None:  # validator "before" nhận cả giá trị không phải chuỗi
    res = ExecutionResult(success=True, steps_done=[], failed_step=None, rollback_status="none_needed", rollback_details=[],
                          action_plan_hash_matched=None, handoff_note=None, outputs={"already_installed": value})  # fmt: skip
    assert res.outputs == {}


# ---- mẫu ------------------------------------------------------------------------------------------------------------------------


def test_template_exact() -> None:
    assert already_installed_text(ZOOM, {"version": "6.1", "already_installed": "true"}) == ALREADY


def test_template_without_version_or_bad_ids() -> None:
    assert already_installed_text(ZOOM, {"already_installed": "true"}) == (
        'Zoom đã có sẵn trên máy LAP-0342, mình không cài lại. Nếu Zoom không mở được, bạn chọn "Chưa ổn" để mình chuyển kỹ thuật '
        "viên.")  # fmt: skip
    bad = action("install_software", params={"device_id": "lap 0342 ; x", "software_name": "<script>"})
    text = already_installed_text(bad, {"version": "6.1"})
    assert text.startswith("Phần mềm đã có sẵn trên máy của bạn (phiên bản 6.1)") and "<script>" not in text


def test_result_text_unchanged_for_new_install() -> None:
    """Hàm cũ giữ nguyên: cài mới vẫn "Đã cài …"."""
    assert result_text(ZOOM, {"version": "6.1"}, ZOOM.facts, requester_id="nv001").startswith(
        "Đã cài Zoom phiên bản 6.1 lên máy LAP-0342.")


# ---- node B17/B18 ---------------------------------------------------------------------------------------------------------------


class StubExecutor:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs

    async def execute(self, ticket_id: str, turn_id: str, action: Any) -> ExecutionResult:
        return ExecutionResult(success=True, steps_done=["install_software"], failed_step=None, rollback_status="none_needed",
                               rollback_details=[], action_plan_hash_matched=None, handoff_note=None, outputs=self.outputs)  # fmt: skip


def _state() -> dict[str, Any]:
    return {
        "ticket_id": "t1", "turn_id": "T1", "status": S_EXECUTING, "intent": "software", "reasoning_loops": 1,
        "requester_context": _requester(), "intended_action": ZOOM, "ctx_flags": {"target_is_other": False},
        "redacted_request": "cài phần mềm cho em", "slots": {"action": "install_software", "software_name": "zoom",
                                                             "device_id": "LAP-0342"},
    }  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outputs", "already", "prefix"),
    [
        ({"software": "zoom", "version": "6.1", "already_installed": "true"}, True, ALREADY),
        ({"software": "zoom", "version": "6.1"}, False, "Đã cài Zoom phiên bản 6.1 lên máy LAP-0342."),
    ],
    ids=["da-co-san", "cai-moi"],
)  # fmt: skip
async def test_b18_message_and_audit(
    outputs: dict[str, str], already: bool, prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    monkeypatch.setattr(b17_execute, "evaluate", lambda action, ctx: ALLOW)
    env = Env()
    env.executor = StubExecutor(outputs)
    out = await env.node(_state())
    assert out.get("status") == S_CONFIRMING, env.h.audit.events("t1")
    [msg] = out["conversation"]
    assert (msg["kind"], msg["needs"]) == ("result", "confirm")
    assert msg["text"].startswith(prefix)
    assert "Đã cài" not in msg["text"] if already else True
    assert env.h.notifier.sent == [("t1", msg["text"], "confirm")]
    [row] = env.h.audit.of("t1", "executed_ok")
    assert row["detail"]["already_installed"] is already


@pytest.mark.asyncio
async def test_b18_real_executor_already_installed_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """PlanExecutor thật + hệ thống ghi giả trả `already_installed: true` (như mock) → tin "đã có sẵn"."""
    monkeypatch.setattr(b17_execute, "evaluate", lambda action, ctx: ALLOW)
    env = Env()
    env.writes.already_installed.add("zoom")
    out = await env.node(_state())
    assert out.get("status") == S_CONFIRMING, env.h.audit.events("t1")
    [msg] = out["conversation"]
    assert msg["text"].startswith("Zoom đã có sẵn trên máy LAP-0342 (phiên bản 6.1.0), mình không cài lại.")
    assert env.h.audit.of("t1", "executed_ok")[0]["detail"]["already_installed"] is True


# ---- chấm thử 11/11: tên hiển thị phần mềm là bảng HẰNG trong mã (không đọc tên hệ thống ngoài trả về — Q-T24-7) ----------------


@pytest.mark.parametrize(
    ("raw", "shown"),
    [("zoom", "Zoom"), ("adobe-acrobat-pro", "Adobe Acrobat Pro"), ("vscode", "Visual Studio Code"), ("7zip", "7-Zip"),
     ("notepad-plus", "notepad-plus"), ("Zoom Pro", "phần mềm"), ("", "phần mềm")],
)  # fmt: skip
def test_software_label(raw: str, shown: str) -> None:
    from app.domain.messages import software_label

    assert software_label(raw) == shown


def test_software_labels_cover_only_allowed_catalog_keys() -> None:
    """Bảng hằng chỉ gồm khoá hợp mẫu `SOFTWARE_NAME` và có trong danh mục mock (chép tay — test giữ hai bên khớp)."""
    import json
    from pathlib import Path

    from app.domain.action import SOFTWARE_NAME
    from app.domain.messages import SOFTWARE_LABELS

    seed = json.loads((Path(__file__).resolve().parents[3] / "mock_services" / "seed.json").read_text(encoding="utf-8"))
    catalog: dict[str, str] = {}

    def walk(o: object) -> None:
        if isinstance(o, dict):
            if "name" in o and "display_name" in o:
                catalog[str(o["name"])] = str(o["display_name"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(seed)
    for key in SOFTWARE_LABELS:
        assert SOFTWARE_NAME.fullmatch(key) and key in catalog, key
