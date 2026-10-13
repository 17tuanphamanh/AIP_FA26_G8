"""Hàm dùng chung cho test T20a (phase5 5.1.6) — không phải file test (tên bắt đầu `_`, pytest không gom).

- `Env`: registry THẬT (`tests/fakes/identity.fake_directory`) trên AD giả đọc seed (`ad_get_user`) + `SeedVpn` (máy, cert, kết nối) +
  `SeedTools` (AD đọc, phần mềm, file) — cùng `mock_services/seed.json`, cùng FakeClock.
- `Env.diagnose(module, requester, slots)`: chạy `module.calls(...)` qua registry (bước B6), dựng `diag` theo quy ước TQ-2
  (`{t: None for t in module.TOOLS} | {r.tool: r.data}` — 404 → None, rỗng → RootModel rỗng, không gọi → None), rồi
  `module.infer_<intent>(...)`; `check_facts` trên kết quả.
- `rc(user_id)`: bản chụp B1 của người gửi từ AD seed (như `test_b15_prepare_approval._rc`).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.facts import check_facts
from app.tools.models import AdUser
from app.tools.registry import ToolRegistry, ToolResult
from tests.fakes.ad_seed import seed_ad_records
from tests.fakes.identity import FakeAd, fake_directory
from tests.fakes.seed_tools import SeedTools
from tests.fakes.vpn import SeedVpn

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN — trong giờ hành chính


def rc(user_id: str, at: datetime = NOW) -> RequesterContext:
    [rec] = seed_ad_records(at, [user_id])
    return RequesterContext.from_ad(AdUser.model_validate(rec), at)


@dataclass
class Env:
    clock: FakeClock = field(default_factory=lambda: FakeClock(NOW))
    tools: SeedTools = field(init=False)
    vpn: SeedVpn = field(init=False)
    ad: FakeAd = field(init=False)

    def __post_init__(self) -> None:
        self.tools = SeedTools(self.clock)
        self.vpn = SeedVpn(self.clock)
        self.ad = FakeAd(*seed_ad_records(self.clock.now()))

    def directory(self) -> ToolRegistry:
        """Mỗi lần gọi = registry + breaker mới (như một process)."""
        return fake_directory(self.ad, self.clock, {**self.vpn.handlers(), **self.tools.handlers()})

    async def run_calls(
        self, calls: Iterable[tuple[str, Mapping[str, Any]]], *, step: str = "B6"
    ) -> list[ToolResult]:
        directory = self.directory()
        return [await directory.call(tool, dict(args), caller_step=step) for tool, args in calls]

    async def diagnose(
        self, module: ModuleType, requester: str, slots: Mapping[str, str]
    ) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any], dict[str, str], dict[str, Any]]:
        """(calls, diag, slots_suy_ra, facts) — đúng đường B6 (calls → registry → diag TQ-2 → infer)."""
        calls = [(t, dict(a)) for t, a in module.calls(requester, dict(slots))]
        results = await self.run_calls(calls)
        assert all(r.error is None for r in results), [r.error for r in results]
        diag: dict[str, Any] = {t: None for t in module.TOOLS} | {r.tool: r.data for r in results}
        infer = getattr(module, f"infer_{module.__name__.rsplit('.', 1)[-1]}")  # infer_account / infer_software / infer_access
        inferred, facts = infer(diag, requester_id=requester, slots=dict(slots))
        check_facts(facts)  # đúng key, đúng kiểu, đúng tập giá trị (P2)
        return calls, diag, dict(inferred), dict(facts)
