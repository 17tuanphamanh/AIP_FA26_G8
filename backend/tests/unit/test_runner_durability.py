"""Checkpoint lưu ĐỒNG BỘ (chốt DỪNG 2 — soát S12 NGHI-3; `graph/runner.DURABILITY`): khi một node bắt đầu chạy, không còn lần
lưu checkpoint nào của bước trước đang dở. Saver giả chậm (`aput` ngủ) để lộ khác biệt: với `"async"` mặc định của LangGraph,
node sau chạy trong lúc checkpoint bước trước còn đang lưu — process chết lúc đó thì recover chạy lại từ checkpoint cũ hơn.
Đo ở nơi nhận (saver), không đọc tham số truyền vào `ainvoke`. Cộng test tĩnh: MỌI lời gọi chạy graph trong `backend/app`
(`ainvoke`/`astream`/`invoke`/`stream`/`abatch`/`batch`) truyền `durability=DURABILITY` — đường `_divert_bound` (B20 sau khi bẻ
luồng) không đo được bằng saver chậm (soát lại DỪNG 2, R3).
"""

import ast
import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from app.domain.states import S_PENDING_APPROVAL
from app.graph import runner as runner_mod
from app.graph.checkpoint import make_serde
from app.graph.fakes import FakeScenario
from langgraph.checkpoint.memory import InMemorySaver
from tests.fakes.graph import GraphHarness

pytestmark = pytest.mark.asyncio


class SlowSaver(InMemorySaver):
    def __init__(self) -> None:
        super().__init__(serde=make_serde())
        self.in_flight = 0

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        self.in_flight += 1
        try:
            await asyncio.sleep(0.02)
            return await super().aput(config, checkpoint, metadata, new_versions)
        finally:
            self.in_flight -= 1


class Probe(FakeScenario):
    """Node giả gọi `pick` khi bắt đầu chạy — ghi lại số lần lưu checkpoint còn dở lúc đó."""

    def __init__(self, saver: SlowSaver) -> None:
        super().__init__()
        self.saver = saver
        self.seen: list[int] = []

    def pick(self, state: Mapping[str, Any], node: str) -> str:
        self.seen.append(self.saver.in_flight)
        return super().pick(state, node)


async def _run() -> list[int]:
    saver = SlowSaver()
    probe = Probe(saver)
    h = GraphHarness(saver=saver, scenario=probe)
    result = await h.submit("t1")
    assert result.status == S_PENDING_APPROVAL
    return probe.seen


async def test_runner_waits_for_checkpoint_before_next_node() -> None:
    seen = await _run()
    assert len(seen) >= 5 and set(seen) == {0}


async def test_probe_detects_async_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tự kiểm: cùng saver chậm, đặt lại `"async"` (mặc định LangGraph) → có node chạy khi checkpoint trước còn dở — test trên
    có răng."""
    monkeypatch.setattr(runner_mod, "DURABILITY", "async")
    assert max(await _run()) >= 1


APP = Path(__file__).resolve().parents[2] / "app"
RUN_METHODS = frozenset({"ainvoke", "astream", "invoke", "stream", "abatch", "batch"})


def _run_calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in RUN_METHODS]  # fmt: skip


def _has_sync_durability(call: ast.Call) -> bool:
    return any(k.arg == "durability" and isinstance(k.value, ast.Name) and k.value.id == "DURABILITY" for k in call.keywords)


async def test_every_graph_run_call_passes_durability() -> None:
    found: list[str] = []
    missing: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        for call in _run_calls(ast.parse(path.read_text(encoding="utf-8"))):
            where = f"{path.relative_to(APP)}:{call.lineno}"
            found.append(where)
            if not _has_sync_durability(call):
                missing.append(where)
    assert missing == []
    assert [f.split(":")[0] for f in found] == ["graph/runner.py", "graph/runner.py"]  # _invoke + _divert_bound — không rỗng
    assert runner_mod.DURABILITY == "sync"


@pytest.mark.parametrize(
    ("src", "ok"),
    [("g.ainvoke(x, cfg, durability=DURABILITY)", True), ("g.ainvoke(x, cfg)", False),
     ("g.ainvoke(x, cfg, durability='async')", False), ("g.astream(x, cfg)", False)],
    ids=["dung", "thieu", "chuoi-async", "astream-thieu"],
)  # fmt: skip
async def test_scanner_self_check(src: str, ok: bool) -> None:
    [call] = _run_calls(ast.parse(src))
    assert _has_sync_durability(call) is ok
