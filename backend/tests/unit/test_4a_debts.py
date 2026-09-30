"""Phase 4 chặng 4a DỪNG 2 — nợ kỹ thuật (phase4 mục 4.1, 4.5): P1 CI, P4 `GIT_SHA` → `lineage.commit_sha` (4a-5, 4a-6),
P7 `FAKE_*` rỗng = không đặt (4a-7). HMAC (4a-1…4a-4): `test_auth_username_hash.py`; `make verify` (4a-8): `test_verify_script.py`.
"""

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from app.core.clock import FakeClock
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b12_assess
from app.settings import Settings
from tests.fakes.graph import GraphHarness
from tests.fakes.llm import make_gateway

REPO = Path(__file__).resolve().parents[3]
SHA = "0123456789abcdef0123456789abcdef01234567"


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]  # _env_file: tham số riêng của pydantic-settings


# ---- P1: CI ghim runner + action Node 24 -----------------------------------------------------------------------------


def test_p1_ci_pins_ubuntu_2404_and_node24_action_majors() -> None:
    ci = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    job = ci["jobs"]["lint-test"]
    assert job["runs-on"] == "ubuntu-24.04"
    uses = sorted(step["uses"] for step in job["steps"] if "uses" in step)
    assert uses == ["actions/cache@v5", "actions/checkout@v5", "astral-sh/setup-uv@v7"]


# ---- 4a-5: Settings.app_git_sha --------------------------------------------------------------------------------------


def test_4a5_app_git_sha_accepts_only_40_lower_hex(caplog: pytest.LogCaptureFixture) -> None:
    assert _settings(app_git_sha=SHA).app_git_sha == SHA
    assert _settings().app_git_sha is None
    caplog.set_level(logging.WARNING)
    for bad in ("", "abc", SHA + "0", SHA.upper(), SHA[:-1] + "g"):
        caplog.clear()
        assert _settings(app_git_sha=bad).app_git_sha is None, bad
        if bad:  # sai dạng → 1 dòng WARNING, KHÔNG in giá trị; rỗng (cây bẩn) → im lặng
            assert [r.levelno for r in caplog.records] == [logging.WARNING]
            assert bad not in caplog.text
        else:
            assert caplog.records == []


def test_4a5_app_git_sha_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_GIT_SHA", SHA)
    assert _settings().app_git_sha == SHA
    monkeypatch.setenv("APP_GIT_SHA", "")  # build từ cây bẩn: ENV rỗng → như không đặt
    assert _settings().app_git_sha is None


# ---- 4a-6: lineage.commit_sha lấy từ Settings qua NodeDeps -----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("sha", [SHA, None], ids=["co", "khong"])
async def test_4a6_b12_lineage_commit_sha_from_deps(sha: str | None) -> None:
    from tests.unit.test_b12_assess import _state  # dựng state B12 chuẩn (R20 allow)

    h = GraphHarness(clock=FakeClock(), llm=make_gateway({}).client)
    deps = h.deps()
    deps.commit_sha = sha
    ctx = RunContext(turn_id="T1", trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=h.spans, clock=h.clock,
                     txlog=h.txlog)  # fmt: skip
    with bind_run(ctx):
        await b12_assess.make(deps)(_state())
    [lin] = h.audit.lineage
    assert lin["commit_sha"] == sha


def test_4a6_b10_lineage_carries_commit_sha_from_deps() -> None:
    src = (REPO / "backend" / "app" / "graph" / "nodes" / "b10_route.py").read_text(encoding="utf-8")
    assert '"commit_sha": deps.commit_sha' in src
    b12 = (REPO / "backend" / "app" / "graph" / "nodes" / "b12_assess.py").read_text(encoding="utf-8")
    assert '"commit_sha": deps.commit_sha' in b12 and '"commit_sha": None' not in b12


@pytest.mark.asyncio
async def test_4a6_wiring_passes_app_git_sha_to_node_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.session import create_engines
    from app.graph import wiring
    from langgraph.checkpoint.memory import InMemorySaver
    from pydantic import SecretStr

    @asynccontextmanager
    async def memory_saver(*_: Any, **__: Any) -> AsyncIterator[InMemorySaver]:
        yield InMemorySaver()

    captured: list[Any] = []
    real_select = wiring.select_nodes
    monkeypatch.setattr(wiring, "open_postgres_saver", memory_saver)
    def spy_select(settings: Settings, deps: Any) -> Any:
        captured.append(deps)
        return real_select(settings, deps)

    monkeypatch.setattr(wiring, "select_nodes", spy_select)
    settings = _settings(
        app_env="dev", llm_backend="scripted", ml_service_token=SecretStr("t" * 32),
        database_url="postgresql+psycopg://x@127.0.0.1:1/khong_co", app_git_sha=SHA,
    )
    engines = create_engines(settings)
    try:
        async with wiring.open_runtime(settings, engines, FakeClock(), can_execute=False):
            pass
    finally:
        await engines.dispose()
    [deps] = captured
    assert deps.commit_sha == SHA


def test_4a6_dockerfile_sets_git_sha_after_dependency_layers() -> None:
    lines = (REPO / "backend" / "Dockerfile").read_text(encoding="utf-8").splitlines()
    idx = {key: next(i for i, line in enumerate(lines) if line.startswith(key))
           for key in ("RUN --mount=type=cache", "COPY backend/app", 'ARG GIT_SHA=""', "ENV APP_GIT_SHA=$GIT_SHA")}  # fmt: skip
    assert idx["RUN --mount=type=cache"] < idx["COPY backend/app"] < idx['ARG GIT_SHA=""'] < idx["ENV APP_GIT_SHA=$GIT_SHA"]


def test_4a6_makefile_git_sha_only_for_clean_tracked_tree() -> None:
    mk = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^GIT_SHA := \$\(shell test -z .*--untracked-files=no.*git rev-parse HEAD", mk, re.MULTILINE)
    assert "BUILD_BACKEND := $(COMPOSE) build --build-arg GIT_SHA=$(GIT_SHA) backend" in mk
    assert "$(COMPOSE) build backend" not in mk  # mọi lần build backend đều mang GIT_SHA


# ---- 4a-7: FAKE_* rỗng = không đặt (P7 — đã có sẵn nhờ env_ignore_empty) ---------------------------------------------


def test_4a7_empty_fake_env_vars_mean_unset_and_real_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.graph import wiring

    monkeypatch.setenv("FAKE_SCENARIO", "")
    monkeypatch.setenv("FAKE_NODE_DELAY", "")
    settings = _settings()
    assert (settings.fake_scenario, settings.fake_node_delay) == (None, None)
    monkeypatch.setattr(wiring, "real_nodes", lambda deps: {"chon": "that"})
    monkeypatch.setattr(wiring, "fake_nodes", lambda deps: {"chon": "gia"})
    assert wiring.select_nodes(settings, cast(Any, None)) == {"chon": "that"}
    monkeypatch.setenv("FAKE_SCENARIO", "approval")  # đối chứng: đặt → node giả (gate2)
    assert wiring.select_nodes(_settings(app_env="dev"), cast(Any, None)) == {"chon": "gia"}
