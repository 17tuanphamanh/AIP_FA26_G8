"""Kịch bản node giả trên stack compose (2b-4): `StackScenario` (thẻ `[fake:<preset>]`, kết quả theo
state, điểm dừng `FAKE_NODE_DELAY`), `graph/wiring.fake_scenario`, compose truyền biến cho CẢ backend
lẫn worker. Fail-closed theo APP_ENV: `test_app_env.py`."""

import ast
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.domain.states import (
    S_CLARIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
)
from app.graph.fakes import (
    DEFAULT_OUTCOMES,
    PAUSABLE_NODES,
    PAUSE_POINTS,
    STACK_PRESETS,
    FakeScenario,
    StackScenario,
)
from app.graph.late_event import deliver_event
from app.graph.routing import ROUTES, WAIT_NODES
from app.graph.wiring import fake_scenario
from app.settings import Settings
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import SESSION

REPO = Path(__file__).resolve().parents[3]
NODES_DIR = REPO / "backend" / "app" / "graph" / "nodes"
WAIT_OF = {"approval": S_PENDING_APPROVAL, "clarify": S_CLARIFYING, "confirm": S_CONFIRMING,
           "kill_b06": S_PENDING_APPROVAL, "kill_b15": S_PENDING_APPROVAL}  # fmt: skip


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def _branches(node: str) -> set[str]:
    """Các giá trị `outcome == "…"` mà node giả thật sự rẽ nhánh (đọc AST, không chép tay). Node đã có bản thật: bản giả
    nằm ở `graph/nodes/fake/` (3-Q32 cách A) — `StackScenario` chỉ lái bản giả."""
    fake = NODES_DIR / "fake" / f"{node}.py"
    tree = ast.parse((fake if fake.exists() else NODES_DIR / f"{node}.py").read_text(encoding="utf-8"))
    found = {DEFAULT_OUTCOMES[node], "raise"}
    for cmp in ast.walk(tree):
        if isinstance(cmp, ast.Compare) and isinstance(cmp.left, ast.Name) and cmp.left.id == "outcome":
            found |= {c.value for c in cmp.comparators if isinstance(c, ast.Constant)}
    return found


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


async def _submit(h: GraphHarness, ticket: str, text: str) -> Any:
    h.tickets.register(ticket, h.clock.now())
    return await h.runner.submit(ticket, session_id=SESSION, redacted_request=text)


# ---- Preset hợp lệ ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(STACK_PRESETS))
def test_preset_outcomes_are_real_branches(name: str) -> None:
    preset = STACK_PRESETS[name]
    for node, seq in preset.outcomes.items():
        assert seq and set(seq) <= _branches(node), (name, node, seq)
    assert preset.pause_at is None or preset.pause_at in PAUSE_POINTS


def test_pause_points_exclude_real_and_wait_nodes() -> None:
    assert PAUSABLE_NODES <= set(ROUTES)
    assert not PAUSABLE_NODES & ({"b01_identity", "b20_audit"} | set(WAIT_NODES))


@pytest.mark.parametrize("path", ["b01_identity.py", "b20_audit.py"])
def test_real_nodes_never_read_fake_tag(path: str) -> None:
    """Q1: node thật B1/B20 không đọc thẻ, không đụng kịch bản giả."""
    source = (NODES_DIR / path).read_text(encoding="utf-8")
    names = {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
    assert not names & {"scenario", "FAKE_TAG", "StackScenario", "STACK_PRESETS"}
    assert "[fake:" not in source


def test_unknown_default_preset_refused() -> None:
    with pytest.raises(ValueError, match="FAKE_SCENARIO"):
        StackScenario("khong-co")


# ---- Thẻ chọn preset theo ticket -------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("preset", sorted(WAIT_OF))
async def test_tag_selects_preset(preset: str) -> None:
    h = GraphHarness(scenario=StackScenario("approval"))
    r = await _submit(h, "t1", f"[fake:{preset}] máy không vào VPN")
    assert r.status == WAIT_OF[preset]


@pytest.mark.asyncio
async def test_raise_preset_goes_e9() -> None:
    h = GraphHarness(scenario=StackScenario("approval"))
    r = await _submit(h, "t1", "[fake:raise] x")
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E9")
    assert h.audit.of("t1", "unhandled_exception")


@pytest.mark.asyncio
async def test_no_tag_uses_default_preset() -> None:
    h = GraphHarness(scenario=StackScenario("clarify"))
    assert (await _submit(h, "t1", "không thẻ")).status == S_CLARIFYING


@pytest.mark.asyncio
async def test_unknown_tag_goes_e9_not_default() -> None:
    h = GraphHarness(scenario=StackScenario("approval"))
    r = await _submit(h, "t1", "[fake:khong_co] x")
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E9")
    [row] = h.audit.of("t1", "unhandled_exception")
    assert "khong_co" in row["detail"]["exception"]


@pytest.mark.asyncio
async def test_plain_scenario_ignores_tag() -> None:
    """FAKE_SCENARIO không đặt → `FakeScenario` thường, thẻ trong câu không có tác dụng."""
    scenario = fake_scenario(_settings(app_env="dev"))
    assert type(scenario) is FakeScenario
    h = GraphHarness(scenario=scenario)
    assert (await _submit(h, "t1", "[fake:clarify] x")).status == S_PENDING_APPROVAL


def test_wiring_builds_stack_scenario() -> None:
    scenario = fake_scenario(_settings(app_env="dev", fake_scenario="confirm", fake_node_delay=7))
    assert isinstance(scenario, StackScenario)
    assert (scenario.default, scenario.delay) == ("confirm", 7)


# ---- Kết quả theo STATE, không theo bộ nhớ process -------------------------------------------


@pytest.mark.asyncio
async def test_clarify_sequence_survives_restart() -> None:
    """Hỏi → restart (process mới, StackScenario MỚI) → trả lời → đi tiếp, không hỏi lại."""
    h = GraphHarness(scenario=StackScenario("approval"))
    assert (await _submit(h, "t1", "[fake:clarify] x")).status == S_CLARIFYING
    h.scenario = StackScenario("approval")
    h.restart()
    r = await deliver_event(h.runner, "t1", S_CLARIFYING, {"kind": "user_reply", "text": "LAP-1"})
    assert r.status == S_PENDING_APPROVAL
    assert h.audit.events("t1").count(("B11", "asked")) == 1


# ---- Điểm dừng FAKE_NODE_DELAY ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("preset", "calls"), [
    ("kill_b06", [7.0]), ("kill_b15", [7.0]), ("approval", []), ("clarify", []), ("confirm", []),
])  # fmt: skip
async def test_delay_only_at_preset_pause_point(preset: str, calls: list[float]) -> None:
    sleeps = Sleeps()
    h = GraphHarness(scenario=StackScenario("approval", delay=7.0, sleep=sleeps))
    await _submit(h, "t1", f"[fake:{preset}] x")
    assert sleeps.calls == calls


@pytest.mark.asyncio
async def test_kill_b15_pauses_after_approval_created() -> None:
    seen: list[int] = []
    h = GraphHarness()

    async def sleep(_: float) -> None:
        seen.append(h.approvals.count("t1"))  # đang ngủ: phiếu đã có, chưa báo người duyệt

    h.scenario = StackScenario("approval", delay=1.0, sleep=sleep)
    h.restart()
    await _submit(h, "t1", "[fake:kill_b15] x")
    assert seen == [1]


@pytest.mark.asyncio
async def test_zero_delay_never_sleeps() -> None:
    sleeps = Sleeps()
    h = GraphHarness(scenario=StackScenario("approval", delay=0.0, sleep=sleeps))
    await _submit(h, "t1", "[fake:kill_b06] x")
    assert sleeps.calls == []


def test_negative_delay_refused() -> None:
    with pytest.raises(ValueError, match="FAKE_NODE_DELAY"):
        StackScenario("approval", delay=-1)


# ---- Compose: backend và worker thấy CÙNG kịch bản -------------------------------------------


@pytest.mark.parametrize("service", ["backend", "worker"])
def test_compose_passes_fake_vars_to_service(service: str) -> None:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    env = compose["services"][service]["environment"]
    assert env["FAKE_SCENARIO"] == "${FAKE_SCENARIO:-}"
    assert env["FAKE_NODE_DELAY"] == "${FAKE_NODE_DELAY:-}"
