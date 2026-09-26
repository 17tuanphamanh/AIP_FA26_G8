"""P5 mục 4, 6.1, 8 "Registry": khai báo kiểm lúc import; tool ghi chỉ từ B17; lỗi hệ thống ngoài là
giá trị (ToolResult), chỉ lỗi hợp đồng mới raise; breaker mở → "circuit_open" không chạm hệ thống."""

import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.settings import get_slots
from app.tools.breaker import BreakerBoard
from app.tools.models import LockoutList
from app.tools.registry import (
    CIRCUIT_OPEN,
    ForbiddenToolCall,
    ToolContractError,
    ToolRegistry,
    ToolResult,
)
from app.tools.specs import REGISTRY, SPECS, TOOL_MAP, ToolSpecError, validate_specs
from tests.unit._http_errors import status_error, timeout_error

REPO = Path(__file__).resolve().parents[3]

# Bảng P5 mục 4: 12 tool đọc và arg_slots [Đề xuất D-20]
READ_TABLE = {
    "check_account_status": {"target_user", "account_type"},
    "check_lockout_history": {"target_user"},
    "check_privilege_level": {"target_user", "account_type"},
    "check_device_registered": {"device_id"},
    "check_vpn_cert_expiry": {"device_id"},
    "check_last_connection": set(),
    "check_catalog_entry": {"software_name"},
    "check_license_available": {"software_name"},
    "check_installed_list": {"device_id"},
    "check_current_permissions": {"resource_path"},
    "check_resource_sensitivity": {"resource_path"},
    "check_manager_chain": set(),
}

INSTALL = {"device_id": "PC-0977", "software_name": "zoom"}
INSTALLED = {"device_id": "PC-0977", "name": "zoom", "version": "6.2", "installed_at": "2026-09-26T00:00:00Z"}
USER = {"user_id": "nv001", "full_name": "A", "title": "t", "department": "Finance",
        "employment_status": "active"}  # fmt: skip


class Handler:
    def __init__(self, *steps: Any) -> None:
        self.steps, self.calls = list(steps), 0

    async def __call__(self, inp: Any, timeout: float) -> Any:
        self.calls += 1
        step = self.steps[min(self.calls, len(self.steps)) - 1]
        if isinstance(step, BaseException):
            raise step
        return step


def _registry(clock: FakeClock, **handlers: Handler) -> ToolRegistry:
    return ToolRegistry(handlers, breakers=BreakerBoard(clock, 5, 60, 30), clock=clock)


# ---- Khai báo --------------------------------------------------------------------------------


def test_twelve_read_tools_with_spec_arg_slots() -> None:
    reads = {n: set(s.arg_slots) for n, s in REGISTRY.items() if s.kind == "read" and "B6" in s.allowed_steps}
    assert reads == READ_TABLE
    assert {t for tools in TOOL_MAP.values() for t in tools} == set(READ_TABLE)


def test_every_write_tool_only_b17_no_retry() -> None:
    writes = [s for s in REGISTRY.values() if s.kind == "write"]
    assert len(writes) == 13
    assert all(s.allowed_steps == {"B17"} and s.retries == 0 for s in writes)
    assert all(s.retries == 2 and s.timeout_s == 5 for s in REGISTRY.values() if s.kind == "read")


def test_undo_tools_are_declared_writes() -> None:
    assert REGISTRY["reset_password"].reversible == "partial"
    assert REGISTRY["reset_password"].undo_tool == "lock_account"
    assert REGISTRY["assign_paid_license"].undo_tool is None
    for s in REGISTRY.values():
        if s.undo_tool:
            assert REGISTRY[s.undo_tool].kind == "write"


def _spec(name: str) -> Any:
    return next(s for s in SPECS if s.name == name)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda: replace(_spec("reset_password"), allowed_steps=frozenset({"B6", "B17"})), "B17"),
        (lambda: replace(_spec("reset_password"), retries=2), "retry"),
        (lambda: replace(_spec("reset_password"), undo_tool="khong_co"), "undo_tool"),
        (lambda: replace(_spec("reset_password"), undo_tool=None), "undo_tool"),
        (lambda: replace(_spec("check_account_status"), reversible="full"), "reversible"),
        (lambda: replace(_spec("check_account_status"), allowed_steps=frozenset({"B6", "B17"})), "B17"),
        (lambda: replace(_spec("check_catalog_entry"), arg_slots=frozenset({"ngay_sinh"})), "TOOL_ARG_SLOTS"),
    ],
    ids=["write-not-b17", "write-retry", "undo-missing", "reversible-without-undo", "read-reversible",
         "read-b17", "arg-slot-unknown"],
)  # fmt: skip
def test_bad_declaration_rejected(change: Any, message: str) -> None:
    bad = change()
    specs = [bad if s.name == bad.name else s for s in SPECS]
    with pytest.raises(ToolSpecError, match=message):
        validate_specs(specs, get_slots().tool_arg_slots, TOOL_MAP)


def test_duplicate_and_bad_tool_map_rejected() -> None:
    with pytest.raises(ToolSpecError, match="trùng"):
        validate_specs([*SPECS, SPECS[0]], get_slots().tool_arg_slots, TOOL_MAP)
    with pytest.raises(ToolSpecError, match="TOOL_MAP"):
        validate_specs(SPECS, get_slots().tool_arg_slots, {"vpn": ("reset_password",)})


def test_import_fails_when_slots_config_disagrees(tmp_path: Path) -> None:
    """P5 mục 8: arg_slots ngoài TOOL_ARG_SLOTS → **import** lỗi (không đợi tới runtime)."""
    (tmp_path / "policy.json").write_text((REPO / "config" / "policy.json").read_text())
    (tmp_path / "slots.yaml").write_text("tool_arg_slots: [target_user, account_type, device_id]\n")
    env = {**os.environ, "CONFIG_DIR": str(tmp_path), "APP_ENV_FILE": "", "PYTHONPATH": str(REPO / "backend")}
    proc = subprocess.run([sys.executable, "-c", "import app.tools.specs"], env=env, capture_output=True,
                          text=True, cwd=tmp_path, check=False)  # fmt: skip
    assert proc.returncode != 0
    assert "TOOL_ARG_SLOTS" in proc.stderr


# ---- Gọi -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_tool_from_b6_forbidden() -> None:
    h = Handler({})
    reg = _registry(FakeClock(), reset_password=h)
    with pytest.raises(ForbiddenToolCall):
        await reg.call("reset_password", {"user_id": "nv001"}, caller_step="B6")
    assert h.calls == 0
    assert issubclass(ForbiddenToolCall, ToolContractError)


@pytest.mark.asyncio
async def test_read_tool_from_b17_or_unknown_step_forbidden() -> None:
    reg = _registry(FakeClock(), check_last_connection=Handler([]))
    for step in ("B17", "B20", ""):
        with pytest.raises(ForbiddenToolCall):
            await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step=step)


@pytest.mark.asyncio
async def test_unknown_tool_bad_input_missing_handler_are_contract_errors() -> None:
    h = Handler([])
    reg = _registry(FakeClock(), check_last_connection=h)
    with pytest.raises(ToolContractError, match="chưa khai báo"):
        await reg.call("khong_co", {}, caller_step="B6")
    with pytest.raises(ToolContractError, match="input"):
        await reg.call("check_last_connection", {"user_id": "nv001", "la": 1}, caller_step="B6")
    with pytest.raises(ToolContractError, match="handler"):
        await reg.call("check_lockout_history", {"user_id": "nv001"}, caller_step="B6")
    assert h.calls == 0


def test_handler_for_undeclared_tool_rejected() -> None:
    with pytest.raises(ToolSpecError):
        _registry(FakeClock(), khong_co=Handler([]))


@pytest.mark.asyncio
async def test_read_success_returns_validated_model_and_unpacks() -> None:
    reg = _registry(FakeClock(), check_manager_chain=Handler([USER]))
    result = await reg.call("check_manager_chain", {"user_id": "nv001"}, caller_step="B6")
    assert isinstance(result, ToolResult) and result.error is None and not result.empty
    data, err, attempts = result
    assert data.root[0].user_id == "nv001" and err is None and attempts == 0


@pytest.mark.asyncio
async def test_404_and_empty_list_are_empty_not_errors() -> None:
    reg = _registry(FakeClock(), check_catalog_entry=Handler(status_error(404)),
                    check_lockout_history=Handler([]))  # fmt: skip
    missing = await reg.call("check_catalog_entry", {"software_name": "utorrent"}, caller_step="B6")
    assert (missing.data, missing.error, missing.empty) == (None, None, True)
    empty = await reg.call("check_lockout_history", {"user_id": "nv002"}, caller_step="B11")
    assert empty.error is None and empty.empty and empty.data == LockoutList([])


@pytest.mark.asyncio
async def test_system_error_after_retry_is_a_value() -> None:
    clock, h = FakeClock(), Handler(status_error(500))
    reg = _registry(clock, check_last_connection=h)
    result = await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
    assert result.data is None and result.error is not None and not result.empty
    assert result.attempts == 3 and h.calls == 3 and clock.sleeps == [1, 2]


@pytest.mark.asyncio
async def test_breaker_opens_after_5_failures_6th_call_never_reaches_system() -> None:
    clock = FakeClock()
    h = Handler(status_error(500))
    reg = _registry(clock, check_last_connection=h, ad_get_user=Handler(status_error(503)))
    for _ in range(5):
        assert (await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")).error
    calls = h.calls
    sixth = await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
    assert sixth.error == CIRCUIT_OPEN and sixth.attempts == 0 and h.calls == calls
    # breaker theo target_system: vpn mở không làm ad bị chặn
    ad = await reg.call("ad_get_user", {"user_id": "nv001"}, caller_step="B1")
    assert ad.error != CIRCUIT_OPEN


@pytest.mark.asyncio
async def test_half_open_probe_success_closes() -> None:
    clock = FakeClock()
    h = Handler(*[status_error(500)] * 15, [])
    reg = _registry(clock, check_last_connection=h)
    for _ in range(5):
        await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
    clock.advance(timedelta(seconds=30))
    probe = await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
    assert probe.error is None and probe.empty
    again = await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
    assert again.error is None


@pytest.mark.asyncio
async def test_bad_output_and_other_4xx_raise_without_tripping_breaker() -> None:
    clock = FakeClock()
    reg = _registry(clock, check_catalog_entry=Handler({"name": "zoom"}),
                    check_license_available=Handler(status_error(400)))  # fmt: skip
    for _ in range(6):
        with pytest.raises(ToolContractError, match="output"):
            await reg.call("check_catalog_entry", {"software_name": "zoom"}, caller_step="B6")
        with pytest.raises(ToolContractError, match="HTTP 400"):
            await reg.call("check_license_available", {"software_name": "zoom"}, caller_step="B6")
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_write_called_once_no_retry() -> None:
    clock = FakeClock()
    h500, htimeout, h409 = Handler(status_error(500)), Handler(timeout_error()), Handler(status_error(409))
    reg = _registry(clock, unlock_account=h500, reset_password=htimeout, assign_paid_license=h409)
    args = {"user_id": "nv001", "account_type": "email"}
    r500 = await reg.call("unlock_account", args, caller_step="B17")
    rto = await reg.call("reset_password", args, caller_step="B17")
    r409 = await reg.call("assign_paid_license", {"software_name": "ms-project", "user_id": "nv001"},
                          caller_step="B17")  # fmt: skip
    assert (h500.calls, htimeout.calls, h409.calls) == (1, 1, 1)
    assert all(r.error and r.attempts == 0 for r in (r500, rto, r409))
    assert "409" in (r409.error or "") and clock.sleeps == []


@pytest.mark.asyncio
async def test_write_business_failures_do_not_open_breaker() -> None:
    clock = FakeClock()
    h409 = Handler(status_error(409))
    reg = _registry(clock, assign_paid_license=h409)
    args = {"software_name": "ms-project", "user_id": "nv001"}
    for _ in range(7):
        result = await reg.call("assign_paid_license", args, caller_step="B17")
        assert result.error != CIRCUIT_OPEN
    assert h409.calls == 7


@pytest.mark.asyncio
async def test_write_409_is_neutral_does_not_reset_failure_streak() -> None:
    """P5 6.1 bản 1.4: 404/409 của tool ghi "không tính vào breaker" — không đếm lỗi, cũng không xoá
    chuỗi lỗi liên tiếp của hệ thống đó."""
    clock = FakeClock()
    h = Handler(*[status_error(503)] * 4, status_error(409), status_error(503), INSTALLED)
    reg = _registry(clock, install_software=h)
    results = [await reg.call("install_software", INSTALL, caller_step="B17") for _ in range(6)]
    assert "409" in (results[4].error or "")
    seventh = await reg.call("install_software", INSTALL, caller_step="B17")  # 4 lỗi + 409 + 1 lỗi = 5
    assert seventh.error == CIRCUIT_OPEN and h.calls == 6


@pytest.mark.asyncio
async def test_write_409_as_half_open_probe_closes_breaker() -> None:
    clock = FakeClock()
    h = Handler(*[status_error(503)] * 5, status_error(409), INSTALLED)
    reg = _registry(clock, install_software=h)
    for _ in range(5):
        await reg.call("install_software", INSTALL, caller_step="B17")
    clock.advance(timedelta(seconds=30))
    probe = await reg.call("install_software", INSTALL, caller_step="B17")
    assert "409" in (probe.error or "")
    after = await reg.call("install_software", INSTALL, caller_step="B17")
    assert after.error is None and h.calls == 7  # hệ thống đã trả lời → đóng, không kẹt half-open


@pytest.mark.asyncio
async def test_unexpected_exception_propagates_and_counts_as_failure() -> None:
    clock = FakeClock()
    reg = _registry(clock, check_last_connection=Handler(RuntimeError("bug")))
    for _ in range(5):
        with pytest.raises(RuntimeError):
            await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
    result = await reg.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
    assert result.error == CIRCUIT_OPEN
