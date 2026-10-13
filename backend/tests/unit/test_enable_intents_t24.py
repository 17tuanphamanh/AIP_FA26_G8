"""T24 bảng 7.5 — test-first: bật 4 intent (phase5 7.1 P1) — ca w2 (DỪNG 2: đã gỡ `CHO_DUNG2`/xfail), w3 (ghim).

- w2: `Settings(_env_file=None).enabled_intents == ["vpn", "account", "software", "access"]`; với mặc định đó các kiểm khởi động
  (`check_policy_config`, `check_intent_config`, `check_plans`, `check_approvers_config`) qua; `open_runtime` với settings mặc định chạy
  hết (không từ chối vì PLAN / roster / mẫu B18) và `NodeDeps.enabled_intents` nó dựng = 4 intent.
- w3: `NodeDeps` mặc định (harness test) vẫn `frozenset({"vpn"})` — test cũ không đổi hành vi.
"""

from pathlib import Path
from typing import Any

import pytest
from app.executor.plans import check_plans
from app.settings import (
    Settings,
    check_approvers_config,
    check_intent_config,
    check_policy_config,
    get_action_metadata,
    get_policy,
    get_slots,
    load_approvers,
)
from tests.fakes.graph import GraphHarness
from tests.unit.test_approvers_config import _deps_of, _runtime_settings

REPO = Path(__file__).resolve().parents[3]
FOUR = ["vpn", "account", "software", "access"]

@pytest.fixture
def _no_env_intents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLED_INTENTS", raising=False)


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


@pytest.mark.usefixtures("_no_env_intents")
def test_w2_default_enabled_intents_four_and_startup_checks() -> None:
    """w2 (M-T24-10): mặc định 4 intent; 4 kiểm khởi động xanh với mặc định đó."""
    settings = _settings()
    assert settings.enabled_intents == FOUR
    check_policy_config(get_policy(), get_slots(), get_action_metadata())
    check_intent_config(settings, get_slots(), get_action_metadata())
    check_plans(get_action_metadata().root, settings.enabled_intents)
    check_approvers_config(settings, load_approvers(REPO / "config" / "approvers.yaml"))


@pytest.mark.asyncio
@pytest.mark.usefixtures("_no_env_intents")
async def test_w2_open_runtime_default_settings_four_intents(monkeypatch: pytest.MonkeyPatch) -> None:
    """w2: `open_runtime` (saver in-memory, không DB — khuôn `test_approvers_config._deps_of`) với settings mặc định khởi động được;
    `NodeDeps.enabled_intents` = 4 intent."""
    deps = await _deps_of(monkeypatch, _runtime_settings())
    assert deps.enabled_intents == frozenset(FOUR)


def test_w3_node_deps_default_enabled_intents_vpn_only() -> None:
    """w3: `NodeDeps.enabled_intents` mặc định (harness) KHÔNG đổi — `{"vpn"}`."""
    assert GraphHarness().deps().enabled_intents == frozenset({"vpn"})
