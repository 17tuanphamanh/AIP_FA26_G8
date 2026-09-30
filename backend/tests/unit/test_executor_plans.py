"""h23, h24 (phase3 mục 11.7) + bảng tool ghi mục 11.4 — kiểm độc lập TỪ SPEC, không mạng (httpx.MockTransport).

h23: `PLAN` thiếu `action_type` có trong `action_metadata.yaml` → khởi động thất bại. `PLAN` đúng 11.4
(`renew_vpn_cert`/`reissue_vpn_access` → 1 bước, undo `revoke_vpn_cert`; `check_vpn_status` → rỗng, 3-Q31); mọi
`action_types` của `vpn` (slots.yaml) có trong `PLAN`; `open_runtime` (worker + backend) từ chối TRƯỚC khi đụng DB
(khuôn `test_config_files.py::test_q3h1_open_runtime_refuses_bad_policy_before_db`).
h24: tool ghi gọi ngoài B17 (`caller_step="B6"`…) → `ForbiddenToolCall`, 0 request ra ngoài (P5 mục 8 "Registry",
B17-B18 mục 0.3 "Tool ghi gọi ngoài B17 → lỗi ngay"). 3-Q37: nhãn `B17` chỉ dành cho tool ghi — `ad_get_user` gọi bằng
`B17` bị cấm, bằng `B17_RECHECK` thì được. Tool ghi 1 lần, timeout 5 s, KHÔNG retry [Chốt 17.3].
"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.domain.action import ActionMeta
from app.executor import plans as plans_module
from app.executor.plans import PLAN, Step, check_plans
from app.executor.wiring import build_write_registry
from app.settings import Settings, get_action_metadata, get_slots
from app.tools.breaker import BreakerBoard
from app.tools.registry import ForbiddenToolCall, ToolRegistry
from app.tools.specs import RECHECK_STEP, REGISTRY
from pydantic import SecretStr

AGENT = "a" * 43  # token_urlsafe(32) dài 43 ký tự — giá trị giả, không phải bí mật
EXECUTOR = "e" * 43
MOCK_URL = "http://mock.invalid"

# 3-Q38: ba hành động VPN Phase 3
VPN_ACTIONS = ("renew_vpn_cert", "reissue_vpn_access", "check_vpn_status")

# Bảng tool ghi 11.4: tool → (input, endpoint mock, body)
VPN_WRITES: dict[str, tuple[dict[str, str], str, dict[str, str]]] = {
    "renew_vpn_cert": ({"user_id": "nv001", "device_id": "LAP-0342"}, "/vpn/certs/nv001/renew",
                       {"device_id": "LAP-0342"}),
    "reissue_vpn_access": ({"user_id": "nv005", "device_id": "LAP-0610"}, "/vpn/access/nv005/reissue",
                           {"device_id": "LAP-0610"}),
    "revoke_vpn_cert": ({"user_id": "nv001", "serial": "VPN-2025-0342"}, "/vpn/certs/nv001/revoke",
                        {"serial": "VPN-2025-0342"}),
}  # fmt: skip

CERT = {"serial": "VPN-2026-9999", "device_id": "LAP-0342", "issued_at": "2026-09-29T09:00:00Z",
        "expires_at": "2027-09-29T09:00:00Z", "status": "valid", "days_to_expiry": 365}  # fmt: skip

AD_USER = {
    "user_id": "nv001", "username": "an.nv", "full_name": "Nguyễn Văn An", "title": "Kế toán viên",
    "department": "Finance", "groups": ["IT-Users"], "manager_id": "fin_head", "employment_status": "active",
    "hired_at": "2024-01-01", "is_privileged_account": False,
    "account": {"account_type": "ad", "enabled": True, "locked": False, "lock_reason": None,
                "password_last_set": "2026-01-01T00:00:00Z"},
}  # fmt: skip


def _without(missing: str) -> dict[str, tuple[Step, ...]]:
    return {k: tuple(v) for k, v in PLAN.items() if k != missing}


def _meta_copy() -> dict[str, dict[str, ActionMeta]]:
    return {intent: dict(actions) for intent, actions in get_action_metadata().root.items()}


# ---- h23: nội dung PLAN (11.4) ---------------------------------------------------------------------------------------


def test_h23_plan_is_exactly_spec_11_4() -> None:
    """h23 / 11.4: renew, reissue → 1 bước ghi, undo `revoke_vpn_cert`; `check_vpn_status` → [] (3-Q31)."""
    assert tuple(PLAN["renew_vpn_cert"]) == (Step("renew_vpn_cert", undo="revoke_vpn_cert"),)
    assert tuple(PLAN["reissue_vpn_access"]) == (Step("reissue_vpn_access", undo="revoke_vpn_cert"),)
    assert tuple(PLAN["check_vpn_status"]) == ()


def test_h23_plan_covers_every_vpn_action_type_in_slots_and_metadata() -> None:
    """h23 / 11.4: "Mọi `action_types` của intent `vpn` trong `slots.yaml` phải có trong `PLAN`" — và mọi action_type
    của `vpn` trong `action_metadata.yaml`."""
    in_slots = set(get_slots().intents["vpn"].action_types)
    in_meta = set(get_action_metadata().of("vpn"))
    assert in_slots == set(VPN_ACTIONS) and len(in_meta) >= 3  # quy ước 3.9: danh sách quét không rỗng
    assert in_slots <= set(PLAN)
    assert in_meta <= set(PLAN)


def test_h23_plan_steps_are_declared_write_tools_with_declared_undo() -> None:
    """h23 / 11.4 bảng tool ghi: mỗi bước là tool ghi đã khai báo (`kind=write`, `allowed_steps == {"B17"}`, timeout 5 s,
    retries 0), reversible `full`, `undo` đúng `undo_tool` của ToolSpec; tool hoàn tác cũng là tool ghi."""
    steps = [s for action in VPN_ACTIONS for s in PLAN[action]]
    assert len(steps) == 2
    for step in steps:
        spec = REGISTRY[step.tool]
        assert (spec.kind, spec.allowed_steps, spec.retries, spec.timeout_s) == ("write", {"B17"}, 0, 5.0), step
        assert spec.reversible == "full" and step.undo == spec.undo_tool == "revoke_vpn_cert", step
        undo = REGISTRY[step.undo]
        assert (undo.kind, undo.allowed_steps, undo.retries) == ("write", {"B17"}, 0)


# ---- h23: check_plans — cấu hình lệch → RuntimeError ------------------------------------------------------------------


def test_h23_check_plans_accepts_repo_config() -> None:
    """h23 đối chứng: PLAN thật + action_metadata.yaml thật + ENABLED_INTENTS mặc định → không ném."""
    check_plans(get_action_metadata().root, ["vpn"])
    check_plans(get_action_metadata().root, ["vpn"], plans=PLAN)


@pytest.mark.parametrize("missing", VPN_ACTIONS)
def test_h23_check_plans_refuses_plan_missing_action_type(missing: str) -> None:
    """h23: PLAN thiếu một action_type CÓ trong action_metadata.yaml → RuntimeError nêu tên action thiếu."""
    assert missing in get_action_metadata().of("vpn")
    with pytest.raises(RuntimeError, match=missing):
        check_plans(get_action_metadata().root, ["vpn"], plans=_without(missing))


def test_h23_check_plans_default_reads_module_plan_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """h23: `plans=None` → đọc `app.executor.plans.PLAN` lúc gọi (điều kiện để test `open_runtime` dưới có nghĩa)."""
    monkeypatch.setattr(plans_module, "PLAN", _without("check_vpn_status"))
    with pytest.raises(RuntimeError, match="check_vpn_status"):
        check_plans(get_action_metadata().root, ["vpn"])


def test_h23_metadata_action_without_plan_refuses() -> None:
    """h23 (nguyên văn): action_type có trong action_metadata (của intent bật) mà PLAN không có → RuntimeError."""
    meta = _meta_copy()
    meta["vpn"]["extra_vpn_action"] = meta["vpn"]["renew_vpn_cert"]
    with pytest.raises(RuntimeError, match="extra_vpn_action"):
        check_plans(meta, ["vpn"], plans=PLAN)


def test_h23_second_enabled_intent_without_plan_refuses() -> None:
    """h23 + B17 mục 13 "Hành động mới: thêm PLAN[type]… Thiếu PLAN phải là lỗi cấu hình khi khởi động"."""
    meta = _meta_copy()
    meta["account"] = {"unlock_account": ActionMeta(reversible=True, reversibility="full", data_sensitivity="low",
                                                    scope="single_account", privilege_level="standard_user",
                                                    procedure_doc="KB-ACC-001")}  # fmt: skip
    with pytest.raises(RuntimeError, match="unlock_account"):
        check_plans(meta, ["vpn", "account"], plans=PLAN)


@pytest.mark.parametrize(
    "bad",
    [
        Step("khong_co_tool"),
        Step("check_vpn_cert_expiry"),
        Step("renew_vpn_cert", undo="lock_account"),
        Step("renew_vpn_cert", undo=None),
    ],
    ids=["tool-chua-khai-bao", "tool-doc", "undo-lech-spec", "undo-thieu"],
)
def test_h23_plan_step_must_be_declared_write_tool_with_declared_undo(bad: Step) -> None:
    """h23 [Suy luận từ B17 mục 13 + 11.4 bảng tool ghi]: bước PLAN trỏ tới tool chưa khai báo / tool đọc / undo khác
    `undo_tool` của ToolSpec là cấu hình lệch → lỗi lúc khởi động, không để E9 lúc chạy."""
    plans = {**{k: tuple(v) for k, v in PLAN.items()}, "renew_vpn_cert": (bad,)}
    with pytest.raises(RuntimeError):
        check_plans(get_action_metadata().root, ["vpn"], plans=plans)


# ---- h23: open_runtime — không khởi động, trước DB --------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("can_execute", [False, True], ids=["worker", "backend"])
async def test_h23_open_runtime_refuses_plan_missing_action_before_db(
    monkeypatch: pytest.MonkeyPatch, can_execute: bool
) -> None:
    """h23 "Khởi động thất bại": `open_runtime` gọi `check_plans` TRƯỚC khi đụng DB — `database_url` trỏ cổng không có
    DB; lỗi phải là RuntimeError về PLAN (nêu `check_vpn_status`), không phải lỗi kết nối DB."""
    from app.db.session import create_engines
    from app.graph.wiring import open_runtime

    monkeypatch.setattr(plans_module, "PLAN", _without("check_vpn_status"))
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="dev", llm_backend="scripted", ml_service_token=SecretStr("t" * 32),
        database_url="postgresql+psycopg://x@127.0.0.1:1/khong_co",
    )
    engines = create_engines(settings)
    try:
        with pytest.raises(RuntimeError, match="check_vpn_status"):
            async with open_runtime(settings, engines, clock=None, can_execute=can_execute):  # type: ignore[arg-type]
                pass
    finally:
        await engines.dispose()


# ---- h24: tool ghi chỉ từ B17 -----------------------------------------------------------------------------------------


class Recorder:
    """Nơi NHẬN request (quy ước 3.9: đếm ở nơi nhận, không đếm bằng biến trong code được test)."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


def _ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=CERT)


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, mock_url=MOCK_URL, svc_agent_token=SecretStr(AGENT), svc_executor_token=SecretStr(EXECUTOR)
    )


@asynccontextmanager
async def _write_registry(
    respond: Callable[[httpx.Request], httpx.Response],
) -> AsyncIterator[tuple[ToolRegistry, Recorder, FakeClock]]:
    rec, clock = Recorder(respond), FakeClock()
    registry, http = build_write_registry(_settings(), clock, transport=httpx.MockTransport(rec))
    try:
        yield registry, rec, clock
    finally:
        await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["B6", "B1", "B11", "B12", "B17_RECHECK", "B18", "b17", ""])
@pytest.mark.parametrize("tool", sorted(VPN_WRITES))
async def test_h24_write_tool_outside_b17_forbidden_zero_requests(tool: str, step: str) -> None:
    """h24: tool ghi gọi với `caller_step` khác "B17" (gồm "B6" của bảng) → `ForbiddenToolCall`; 0 request tới mock."""
    async with _write_registry(_ok) as (registry, rec, _):
        with pytest.raises(ForbiddenToolCall):
            await registry.call(tool, VPN_WRITES[tool][0], caller_step=step)
    assert rec.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", sorted(VPN_WRITES))
async def test_h24_control_write_tool_from_b17_one_post_with_executor_token(tool: str) -> None:
    """h24 đối chứng + 11.4 bảng tool ghi: từ "B17" → đúng 1 POST tới endpoint của bảng, body đúng, header
    `X-Service-Token` là token svc_executor (không phải svc_agent — D-03), timeout ≤ 5 s."""
    args, path, body = VPN_WRITES[tool]
    async with _write_registry(_ok) as (registry, rec, _):
        result = await registry.call(tool, args, caller_step="B17")
    assert result.error is None and result.data is not None and result.data.serial == CERT["serial"]
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert (req.method, req.url.path, json.loads(req.content)) == ("POST", path, body)
    assert req.headers["X-Service-Token"] == EXECUTOR
    assert req.headers["X-Service-Token"] != AGENT
    assert 0 < req.extensions["timeout"]["read"] <= 5.0


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", sorted(VPN_WRITES))
async def test_h24_write_500_one_request_no_retry_error_is_value(tool: str) -> None:
    """h24 / B17 0.3 "Không retry lệnh ghi" (P4 lời giao: tool ghi retries=0): 500 → đúng 1 request, không chờ backoff,
    `ToolResult.error` có "500", không raise (P5 6.1: lỗi hệ thống ngoài là giá trị)."""
    async with _write_registry(lambda _: httpx.Response(500, json={"detail": "boom"})) as (registry, rec, clock):
        result = await registry.call(tool, VPN_WRITES[tool][0], caller_step="B17")
    assert len(rec.requests) == 1 and clock.sleeps == []
    assert result.data is None and result.error is not None and "500" in result.error


@pytest.mark.asyncio
async def test_h24_write_timeout_one_request_no_retry() -> None:
    """h24 / B17 0.3: timeout ghi → 1 request, không retry, lỗi là giá trị."""

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("hết giờ", request=request)

    async with _write_registry(timeout) as (registry, rec, clock):
        result = await registry.call("renew_vpn_cert", VPN_WRITES["renew_vpn_cert"][0], caller_step="B17")
    assert len(rec.requests) == 1 and clock.sleeps == []
    assert result.data is None and result.error is not None


def test_h24_write_registry_requires_executor_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """h24 / 11.4: registry ghi chỉ dựng khi có `SVC_EXECUTOR_TOKEN` — thiếu → RuntimeError, không lùi về token agent."""
    monkeypatch.delenv("SVC_EXECUTOR_TOKEN", raising=False)
    settings = Settings(_env_file=None, mock_url=MOCK_URL, svc_agent_token=SecretStr(AGENT))  # type: ignore[call-arg]
    assert settings.svc_executor_token is None
    with pytest.raises(RuntimeError):
        build_write_registry(settings, FakeClock())


# ---- h24 / 3-Q37: nhãn B17 chỉ dành cho tool ghi -------------------------------------------------------------------


def test_h24_q37_step_labels_declared() -> None:
    """3-Q37: `ad_get_user.allowed_steps = {B1, B11, B17_RECHECK}`; không tool đọc nào khai báo `B17`; tool ghi VPN
    chỉ `{"B17"}`."""
    assert RECHECK_STEP == "B17_RECHECK"
    assert REGISTRY["ad_get_user"].allowed_steps == {"B1", "B11", "B17_RECHECK"}
    reads = [s for s in REGISTRY.values() if s.kind == "read"]
    assert len(reads) >= 13 and not [s.name for s in reads if "B17" in s.allowed_steps]
    for tool in VPN_WRITES:
        assert REGISTRY[tool].kind == "write" and REGISTRY[tool].allowed_steps == {"B17"}


@pytest.mark.asyncio
async def test_h24_q37_ad_get_user_b17_forbidden_b17_recheck_allowed() -> None:
    """3-Q37: B17 đọc lại AD bằng `caller_step="B17_RECHECK"`; gọi bằng "B17" → `ForbiddenToolCall`, handler không chạy."""
    clock = FakeClock()
    calls: list[str] = []

    async def handler(inp: Any, timeout: float) -> Any:
        calls.append(inp.user_id)
        return AD_USER

    reg = ToolRegistry({"ad_get_user": handler}, breakers=BreakerBoard(clock, 5, 60, 30), clock=clock)
    with pytest.raises(ForbiddenToolCall):
        await reg.call("ad_get_user", {"user_id": "nv001"}, caller_step="B17")
    assert calls == []
    user, err, _ = await reg.call("ad_get_user", {"user_id": "nv001"}, caller_step=RECHECK_STEP)
    assert err is None and user.employment_status == "active" and calls == ["nv001"]
