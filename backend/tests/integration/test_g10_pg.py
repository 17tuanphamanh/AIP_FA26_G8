"""G10 (thu `no_evidence`, script đo sau tag bf94df2 — P8 §10) trên Postgres 16 thật: factory ghi `llm_calls` + cache `eval`, lượt eval,
`open_reader` chỉ đọc, `gather` dựng with/cases như B12, CLI `collect-no-evidence` đầu-cuối với sampling_k5.

Port phần G10 của `test_noi_that_pg.py` (nhánh cloud/g-noi-that 4ad61fa) — bỏ G11. `OpenAICompatProvider` thay bằng ScriptedLLM (không mạng,
khoá giả). Database riêng cho module (`fresh_database`).
"""

import asyncio
import importlib
import json
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar, Final
from unittest import mock

import pytest
import pytest_asyncio
from alembic import command

with mock.patch.dict(os.environ, {"EVAL_MODE": "true"}):  # như tests/unit/eval/conftest.py: bật cờ đúng MỘT lần quanh import `app.eval`
    importlib.import_module("app.eval")

from app.core.clock import FakeClock
from app.core.errors import LLMBudgetExceeded, LLMUnavailable
from app.domain.action import Action
from app.eval import llm_factory
from app.eval.dbread import open_reader
from app.eval.llm_factory import (
    EvalConfigError,
    ensure_eval_turn,
    eval_gateway,
    eval_usage,
)
from app.eval.predictions import load_predictions
from app.eval.prob_collect import CollectError, gather
from app.graph.checkpoint import open_postgres_saver
from app.llm.providers.scripted import ScriptedLLM
from app.risk.estimator import LlmRiskEstimator
from app.risk.models import RiskContext
from app.settings import Settings
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit._b2review import load_script
from tests.unit.eval import _g10
from tests.unit.eval.test_g10_collect import FAKE_KEY
from tests.unit.eval.test_g10_collect import settings as unit_settings
from tests.unit.eval.test_predictions import rec as prediction
from tests.unit.eval.test_predictions import write as write_predictions

pytestmark = pytest.mark.asyncio

NOW = _g10.NOW  # thứ Tư 10:00 giờ VN — trong giờ hành chính
SATURDAY = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)
K5: Final = "sampling_k5"


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    yield engine
    await engine.dispose()


def cfg(db: PgUrls, **over: Any) -> Settings:
    return unit_settings(database_url=db.role("app_rw"), **over)


class FakeProvider(ScriptedLLM):
    """Thay `OpenAICompatProvider` (không mạng): cùng chữ ký dựng + `aclose`; kịch bản đặt ở `SCRIPTS`."""

    SCRIPTS: ClassVar[dict[str, Any]] = {}

    def __init__(self, name: str, *, base_url: str, api_key: Any, json_mode: str, extra_body: Any) -> None:
        assert base_url and api_key.get_secret_value() == FAKE_KEY  # nhận khoá từ Settings, chưa bao giờ in ra
        super().__init__(dict(self.SCRIPTS), name=name)

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.wiring.OpenAICompatProvider", FakeProvider)
    FakeProvider.SCRIPTS = {"b14_risk_vote": _g10.votes}


async def count(engine: AsyncEngine, sql: str, **params: Any) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(sql), params)).scalar_one())


def _case(cert: str = "expired") -> tuple[Action, RiskContext]:
    c = _g10.case("X-v1", cert=cert)
    return Action.model_validate(c["action"]), RiskContext.model_validate(c["ctx"])


# ---- factory: llm_calls, cache eval, trần ---------------------------------------------------------------------------------------


async def test_gateway_records_k5_votes_with_prompt_full_and_eval_cache(db: PgUrls, rw: AsyncEngine) -> None:
    act, ctx = _case()
    async with eval_gateway("f1", settings=cfg(db), clock=FakeClock(NOW)) as llm:
        est = LlmRiskEstimator(llm, p_method=K5, eval_mode=True)
        first = await est.estimate(act, ctx, [])
        again = await est.estimate(act, ctx, [])
    assert first.raw_prob == again.raw_prob == pytest.approx(0.6)
    async with rw.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT c.prompt_id, c.prompt_full, c.cache_hit FROM llm_calls c JOIN spans s ON s.span_id = c.span_id "
            "JOIN turns u ON u.turn_id = s.turn_id WHERE u.ticket_id = 'eval-f1' ORDER BY c.call_id"
        ))).all()  # fmt: skip
        modes = {r[0] for r in (await conn.execute(text("SELECT mode FROM llm_cache WHERE prompt_id = 'b14_risk_vote'"))).all()}
    assert [r[0] for r in rows] == ["b14_risk_vote"] * 10 and sum(r[2] for r in rows) == 5  # lần 2 trúng cache cả 5 phiếu
    assert all(r[1] for r in rows)  # EVAL_MODE: prompt đầy đủ
    assert modes == {"eval"}
    usage = await eval_usage(rw, "f1")
    assert usage["n"] == 10 and usage["cache_hits"] == 5 and usage["prompts"] == ["b14_risk_vote@1"]


async def test_run_cap_blocks_when_max_usd_is_tiny_and_allows_when_enough(db: PgUrls) -> None:
    act, ctx = _case("revoked")
    async with eval_gateway("cap2", settings=cfg(db), clock=FakeClock(NOW), max_usd=1e-9) as llm:
        with pytest.raises((LLMUnavailable, LLMBudgetExceeded)):
            await LlmRiskEstimator(llm, p_method=K5, eval_mode=True).estimate(act, ctx, [])
    act2, ctx2 = _case("none")
    async with eval_gateway("cap3", settings=cfg(db), clock=FakeClock(NOW), max_usd=1.0) as llm:
        assert (await LlmRiskEstimator(llm, p_method=K5, eval_mode=True).estimate(act2, ctx2, [])).raw_prob == pytest.approx(0.6)
    with pytest.raises(EvalConfigError):
        async with eval_gateway("cap4", settings=cfg(db), max_usd=0):
            pass


async def test_gateway_does_not_leak_key_into_db_rows(db: PgUrls, rw: AsyncEngine) -> None:
    act, ctx = _case("valid")
    async with eval_gateway("key1", settings=cfg(db), clock=FakeClock(NOW)) as llm:
        await LlmRiskEstimator(llm, p_method=K5, eval_mode=True).estimate(act, ctx, [])
    assert await count(rw, "SELECT count(*) FROM llm_calls WHERE prompt_full LIKE :k OR error LIKE :k", k=f"%{FAKE_KEY[:12]}%") == 0
    assert llm_factory.EVAL_USER_ID == "svc-eval"


async def test_eval_turn_is_idempotent_and_ended(db: PgUrls, rw: AsyncEngine) -> None:
    first = await ensure_eval_turn(rw, "t1", NOW)
    again = await ensure_eval_turn(rw, "t1", NOW + timedelta(hours=1))
    assert first == again
    assert await count(rw, "SELECT count(*) FROM turns WHERE ticket_id = 'eval-t1'") == 1
    assert await count(rw, "SELECT count(*) FROM turns WHERE ticket_id LIKE 'eval-%' AND ended_at IS NULL") == 0


async def test_reader_sessions_are_read_only(db: PgUrls) -> None:
    async with open_reader(cfg(db)) as reader:
        async with reader.engine.connect() as conn:
            with pytest.raises(DBAPIError, match="read-only"):
                await conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('x-ro', 'x.ro', 'employee')"))
        pool: Any = reader.saver.conn  # AsyncConnectionPool của checkpoint
        async with pool.connection() as pg_conn:
            with pytest.raises(Exception, match="read-only"):
                await pg_conn.execute("INSERT INTO users (user_id, username, role) VALUES ('x-ro2', 'x.ro2', 'employee')")
    assert await count(create_async_engine(db.role("app_rw")), "SELECT count(*) FROM users WHERE user_id LIKE 'x-ro%'") == 0


# ---- dựng dữ liệu như stack ghi ---------------------------------------------------------------------------------------------------


async def put_state(db: PgUrls, thread: str, values: dict[str, Any]) -> None:
    async with open_postgres_saver(db.role("app_rw"), max_size=2) as saver:
        cp = empty_checkpoint()
        versions: dict[str, str | int | float] = {k: "1" for k in values}
        cp["channel_values"], cp["channel_versions"] = values, versions
        await saver.aput({"configurable": {"thread_id": thread, "checkpoint_ns": ""}}, cp, {"source": "loop", "step": 0, "parents": {}}, versions)


async def seed_risk(
    db: PgUrls, ticket: str, *, raw_prob: float = 0.4, p_method: str = K5, kb_gap: bool | None = False,
    when: datetime = NOW, flags: dict[str, bool] | None = None, act: Action | None = None, state: bool = True,
) -> None:  # fmt: skip
    engine = create_async_engine(db.role("app_rw"))
    try:
        async with engine.begin() as conn:
            await seed.leaf_ticket(conn, created_at=when, ticket_id=ticket)
            detail: dict[str, Any] = {"route": "HITL", "strategy": "hybrid"}
            if kb_gap is not None:
                detail["kb_gap"] = kb_gap
            await seed.audit_row(conn, ticket, step="B13/B14", event="risk_decided", created_at=when, decided_by="llm",
                                 raw_prob=raw_prob, calibrated_prob=raw_prob, p_method=p_method, detail=detail)  # fmt: skip
    finally:
        await engine.dispose()
    if state:
        await put_state(db, ticket, {"intended_action": act or _g10.action(), "requester_context": _g10.requester(),
                                     "ctx_flags": flags or {}})  # fmt: skip


def run_dir(tmp_path: Path, rows: list[dict[str, Any]], *, prob_method: str = K5) -> Path:
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    write_predictions(run / "predictions.jsonl", rows)
    (run / "manifest.json").write_text(json.dumps({"run_id": "0123456789ab", "strategy": "hybrid", "config": {"prob_method": prob_method},
                                                   "counts": {"p_method_mismatch": 0}}), encoding="utf-8")  # fmt: skip
    return run


def pred(sid: str, ticket: str, raw: float, **over: Any) -> dict[str, Any]:
    return prediction(scenario_id=sid, family=sid.split("-")[0], ticket_id=ticket, raw_prob=raw, p_method=K5, **over)


# ---- G10: gather ------------------------------------------------------------------------------------------------------------------


async def test_gather_builds_with_rows_and_cases_exactly_like_b12(db: PgUrls, tmp_path: Path) -> None:
    await seed_risk(db, "g10-a", raw_prob=0.31, kb_gap=False)
    await seed_risk(db, "g10-b", raw_prob=0.77, kb_gap=True, when=SATURDAY, flags={"target_is_other": True}, act=_g10.action("nv002"))
    run = run_dir(tmp_path, [pred("A-v1", "g10-a", 0.31, expected_route="AUTO"), pred("B-v1", "g10-b", 0.77, expected_route="HITL")])
    async with open_reader(cfg(db)) as reader:
        got = await gather(reader, load_predictions(run / "predictions.jsonl"), hours=_g10.HOURS, p_method=K5)
    assert got.recorded == [
        {"scenario_id": "A-v1", "family": "A", "split": "test", "gold_route": "AUTO", "raw_prob": 0.31, "kb_gap": False},
        {"scenario_id": "B-v1", "family": "B", "split": "test", "gold_route": "HITL", "raw_prob": 0.77, "kb_gap": True},
    ]  # fmt: skip
    a, b = got.cases
    assert a["ctx"]["within_business_hours"] is True and a["ctx"]["target_is_other"] is False
    assert b["ctx"]["within_business_hours"] is False and b["ctx"]["target_is_other"] is True
    assert Action.model_validate(a["action"]) == _g10.action() and a["ctx"]["requester"]["user_id"] == "nv001"
    assert got.report["n_gathered"] == 2 and got.report["n_kb_gap"] == 1 and got.report["skipped"] == {}


async def test_gather_skips_incomplete_cases_by_reason_and_never_guesses(db: PgUrls, tmp_path: Path) -> None:
    await seed_risk(db, "g10-nogap", kb_gap=None)
    await seed_risk(db, "g10-mismatch", raw_prob=0.9)
    await seed_risk(db, "g10-nostate", state=False)
    run = run_dir(tmp_path, [
        pred("N-v1", "g10-nogap", 0.4), pred("M-v1", "g10-mismatch", 0.4), pred("S-v1", "g10-nostate", 0.4),
        pred("X-v1", "g10-nolog", 0.4), pred("U-v1", "g10-unl", 0.4, expected_route=None),
    ])  # fmt: skip
    async with open_reader(cfg(db)) as reader:
        got = await gather(reader, load_predictions(run / "predictions.jsonl"), hours=_g10.HOURS, p_method=K5)
    assert got.recorded == [] and got.report["skipped"] == {"no_kb_gap": 1, "raw_prob_mismatch": 1, "no_state": 1, "no_log4": 1, "unlabeled": 1}


async def test_gather_refuses_audit_p_method_other_than_sampling_k5(db: PgUrls, tmp_path: Path) -> None:
    await seed_risk(db, "g10-pm", p_method="self_report")
    run = run_dir(tmp_path, [pred("P-v1", "g10-pm", 0.4)])
    async with open_reader(cfg(db)) as reader:
        with pytest.raises(CollectError, match="p_method"):
            await gather(reader, load_predictions(run / "predictions.jsonl"), hours=_g10.HOURS, p_method=K5)


# ---- G10: CLI đầu-cuối ------------------------------------------------------------------------------------------------------------


def estimator_factory(run_id: str, **_: Any) -> Any:
    """`--llm-factory` của test pipeline: gateway thật (bộ nhớ) + ScriptedLLM trả `b14_risk_vote`."""
    return _g10.gateway().client


async def test_collect_no_evidence_pipeline_end_to_end(db: PgUrls, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for t, p, gap in (("pipe-a", 0.30, False), ("pipe-b", 0.70, True)):
        await seed_risk(db, t, raw_prob=p, kb_gap=gap)
    run = run_dir(tmp_path, [pred("PA-v1", "pipe-a", 0.30, expected_route="AUTO"), pred("PB-v1", "pipe-b", 0.70, expected_route="HITL")])
    monkeypatch.setenv("DATABASE_URL", db.role("app_rw"))
    pv: ModuleType = load_script("scripts/eval/prob_variants.py", monkeypatch)
    dry = await asyncio.to_thread(pv.main, ["collect-no-evidence", "--run", str(run), "--out", str(tmp_path / "dry"), "--dry-run"])
    assert dry == 0 and not (tmp_path / "dry").exists()
    out = tmp_path / "out"
    args = ["collect-no-evidence", "--run", str(run), "--out", str(out), "--llm-factory", "tests.integration.test_g10_pg:estimator_factory"]
    assert await asyncio.to_thread(pv.main, args) == 0
    by = {(r["scenario_id"], r["variant"]): r["raw_prob"]
          for r in map(json.loads, (out / "probs.jsonl").read_text(encoding="utf-8").splitlines())}  # fmt: skip
    assert by[("PA-v1", "with_evidence")] == 0.30 and by[("PA-v1", "no_evidence")] == pytest.approx(0.6)
    assert by[("PA-v1", "max")] == pytest.approx(0.6)
    assert by[("PB-v1", "with_evidence")] == 0.70 and by[("PB-v1", "no_evidence")] == 0.70  # kb_gap: chép, không gọi lại
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["p_method"] == K5 and manifest["build"]["n_copied_kb_gap"] == 1 and manifest["gathered"]["n_kb_gap"] == 1
    assert [json.loads(x)["scenario_id"] for x in (out / "without.jsonl").read_text(encoding="utf-8").splitlines()] == ["PA-v1"]
