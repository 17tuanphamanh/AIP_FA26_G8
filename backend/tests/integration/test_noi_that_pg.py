"""Nối thật mốc G (G10 + G11) trên Postgres 16 thật: factory ghi `llm_calls`, lượt eval, collector đọc audit/checkpoint chỉ-đọc.

- Factory: `eval_gateway` đi đúng đường `check_llm` + `open_llm` (cấu hình `real` từ biến giả); chỉ `OpenAICompatProvider` bị thay bằng
  ScriptedLLM (không mạng). Kiểm: dòng `llm_calls` có `prompt_full`, cache `eval`, trần chi (chung + riêng lượt), lượt eval idempotent và ĐÃ KẾT THÚC.
- Collector G11/G10: dựng audit + spans + llm_calls + checkpoint LangGraph như stack ghi, đọc lại bằng `open_reader` (phiên chỉ đọc).
Database riêng cho module (`fresh_database`).
"""

import asyncio
import importlib
import json
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar
from unittest import mock

import pytest
import pytest_asyncio
from alembic import command

with mock.patch.dict(os.environ, {"EVAL_MODE": "true"}):  # như tests/unit/eval/conftest.py: bật cờ đúng MỘT lần quanh import `app.eval`
    importlib.import_module("app.eval")

from app.core.clock import FakeClock
from app.core.errors import LLMBudgetExceeded, LLMUnavailable
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.messages import answer_msg
from app.domain.ticket_state import ChunkRef
from app.eval import llm_factory
from app.eval.dbread import open_reader
from app.eval.groundedness import collect as col
from app.eval.groundedness import report
from app.eval.groundedness.cli import EXIT_JUDGE_ERRORS, main
from app.eval.groundedness.models import load_answers
from app.eval.llm_factory import (
    EvalConfigError,
    ensure_eval_turn,
    eval_gateway,
    eval_usage,
)
from app.eval.predictions import load_predictions
from app.eval.prob_collect import CollectError, gather
from app.graph.checkpoint import open_postgres_saver
from app.llm.providers.scripted import Reply, ScriptedLLM
from app.llm.schemas import GroundednessOut
from app.settings import Settings, load_policy
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit._b2review import load_script
from tests.unit.eval.test_noi_that_unit import BLOCKS, FAKE_KEY, _prompt_full
from tests.unit.eval.test_noi_that_unit import settings as unit_settings
from tests.unit.eval.test_predictions import rec as prediction
from tests.unit.eval.test_predictions import write as write_predictions

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)  # thứ Tư 10:00 giờ VN — trong giờ hành chính
SATURDAY = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)
CONFIG = Path(__file__).resolve().parents[3] / "config"
VERDICT = Reply({"verdicts": [{"claim_id": 1, "verdict": "unsupported", "chunk_ids": []}]})
ESTIMATE = Reply({"prob_needs_human": 0.42, "factors": [], "rationale": "ổn"})
KEY = FAKE_KEY


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
        assert base_url and api_key.get_secret_value() == KEY  # nhận khoá thật từ Settings, chưa bao giờ in ra
        super().__init__(dict(self.SCRIPTS), name=name)

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.wiring.OpenAICompatProvider", FakeProvider)
    FakeProvider.SCRIPTS = {"eval_groundedness": [VERDICT, VERDICT, VERDICT], "b14_risk_estimate": lambda v: ESTIMATE}


async def count(engine: AsyncEngine, sql: str, **params: Any) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(sql), params)).scalar_one())


VARS = {"claims": "1. Ý một", "evidence": [{"anchor_chunk_id": "A", "title": "T", "heading_path": "H", "text": "x", "score": 1.0}]}


# ---- factory: llm_calls, cache eval, trần ---------------------------------------------------------------------------------------


async def test_gateway_records_llm_call_with_prompt_full_and_eval_cache(db: PgUrls, rw: AsyncEngine) -> None:
    async with eval_gateway("f1", settings=cfg(db), clock=FakeClock(NOW)) as llm:
        out, meta = await llm.complete("strong", "eval_groundedness", VARS, GroundednessOut)
        again, meta2 = await llm.complete("strong", "eval_groundedness", VARS, GroundednessOut)
    assert out == again and (meta.cache_hit, meta2.cache_hit) == (False, True)
    async with rw.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT c.prompt_id, c.prompt_full, c.cost_usd, c.cache_hit, c.model, c.provider FROM llm_calls c "
            "JOIN spans s ON s.span_id = c.span_id JOIN turns u ON u.turn_id = s.turn_id WHERE u.ticket_id = 'eval-f1' ORDER BY c.call_id"
        ))).all()  # fmt: skip
        cache = (await conn.execute(text("SELECT mode, expires_at FROM llm_cache WHERE prompt_id = 'eval_groundedness'"))).all()
    assert [r[0] for r in rows] == ["eval_groundedness"] * 2 and [r[3] for r in rows] == [False, True]
    assert rows[0][1] and "Ý một" in rows[0][1] and rows[1][1]  # EVAL_MODE: prompt đầy đủ, kể cả lần trúng cache
    assert rows[0][2] > 0 and rows[1][2] == 0  # có chi phí thật theo bảng giá; trúng cache = 0
    assert [(r[0], r[1]) for r in cache] == [("eval", None)]  # mode eval, không hết hạn
    usage = await eval_usage(rw, "f1")
    assert usage["n"] == 2 and usage["cache_hits"] == 1 and usage["models"] == ["deepseek-v4-pro"]
    assert usage["prompts"] == ["eval_groundedness@1"] and len(usage["prompt_sha256"]) == 1
    assert usage["cost_usd"] == pytest.approx(rows[0][2])


async def test_eval_spend_counts_toward_the_shared_cap(db: PgUrls, rw: AsyncEngine) -> None:
    before = await count(rw, "SELECT coalesce(sum(cost_usd), 0) FROM llm_calls")  # 0 hoặc số cũ — chỉ so hiệu
    async with eval_gateway("cap1", settings=cfg(db), clock=FakeClock(NOW)) as llm:
        await llm.complete("strong", "eval_groundedness", {**VARS, "claims": "1. Ý khác cap1"}, GroundednessOut)
        reader = llm_factory.SqlLlmStore(rw)  # cùng nguồn trần chi của gateway
        assert await reader.spend_total() > before


async def test_run_cap_blocks_when_max_usd_is_tiny_and_allows_when_enough(db: PgUrls) -> None:
    async with eval_gateway("cap2", settings=cfg(db), clock=FakeClock(NOW), max_usd=1e-9) as llm:
        with pytest.raises((LLMUnavailable, LLMBudgetExceeded)):
            await llm.complete("strong", "eval_groundedness", {**VARS, "claims": "1. Ý cap2"}, GroundednessOut)
    async with eval_gateway("cap3", settings=cfg(db), clock=FakeClock(NOW), max_usd=1.0) as llm:
        out, _ = await llm.complete("strong", "eval_groundedness", {**VARS, "claims": "1. Ý cap3"}, GroundednessOut)
        assert out.verdicts[0].verdict == "unsupported"
    with pytest.raises(EvalConfigError):
        async with eval_gateway("cap4", settings=cfg(db), max_usd=0):
            pass


async def test_gateway_does_not_leak_key_into_db_rows(db: PgUrls, rw: AsyncEngine) -> None:
    async with eval_gateway("key1", settings=cfg(db), clock=FakeClock(NOW)) as llm:
        await llm.complete("strong", "eval_groundedness", {**VARS, "claims": "1. Ý key1"}, GroundednessOut)
    assert await count(rw, "SELECT count(*) FROM llm_calls WHERE prompt_full LIKE :k OR error LIKE :k", k=f"%{KEY[:12]}%") == 0


# ---- lượt eval ---------------------------------------------------------------------------------------------------------------------


async def test_eval_turn_is_idempotent_ended_and_outside_rates(db: PgUrls, rw: AsyncEngine) -> None:
    first = await ensure_eval_turn(rw, "t1", NOW)
    again = await ensure_eval_turn(rw, "t1", NOW + timedelta(hours=1))
    await ensure_eval_turn(rw, "t2", NOW)
    assert first == again
    assert await count(rw, "SELECT count(*) FROM users WHERE user_id = 'svc-eval'") == 1
    assert await count(rw, "SELECT count(*) FROM tickets WHERE ticket_id LIKE 'eval-t%'") == 2
    assert await count(rw, "SELECT count(*) FROM turns WHERE ticket_id = 'eval-t1'") == 1
    async with rw.connect() as conn:
        t = (await conn.execute(text("SELECT final_state, exit_code, is_parent, requester_id, requester_role, created_at FROM tickets WHERE ticket_id = 'eval-t1'"))).one()
        u = (await conn.execute(text("SELECT ended_at, started_at, event_type FROM turns WHERE turn_id = 'eval-t1-t1'"))).one()
        role = (await conn.execute(text("SELECT role, employment_status FROM users WHERE user_id = 'svc-eval'"))).one()
    assert t[0] is None and t[1] is None and t[2] is False and t[3:5] == ("svc-eval", "employee") and t[5] == NOW  # idempotent: giữ giờ lần đầu
    assert u[0] is not None and u[0] == u[1] and u[2] == "submit"  # turn ĐÃ kết thúc: worker không recover lượt này
    assert role == ("employee", "active")
    assert await count(rw, "SELECT count(*) FROM turns WHERE ticket_id LIKE 'eval-%' AND ended_at IS NULL") == 0


# ---- dựng dữ liệu như stack ghi ------------------------------------------------------------------------------------------------------


async def put_state(db: PgUrls, thread: str, values: dict[str, Any]) -> None:
    async with open_postgres_saver(db.role("app_rw"), max_size=2) as saver:
        cp = empty_checkpoint()
        versions: dict[str, str | int | float] = {k: "1" for k in values}
        cp["channel_values"], cp["channel_versions"] = values, versions
        await saver.aput({"configurable": {"thread_id": thread, "checkpoint_ns": ""}}, cp, {"source": "loop", "step": 0, "parents": {}}, versions)


def chunk_refs() -> list[ChunkRef]:
    return [ChunkRef(chunk_id=c, doc_id=c.split("#")[0], version=1, seq=int(c.split("#")[1]), title=t, heading_path=h, score=0.9 - i / 10,
                     excerpt="trích") for i, (c, t, h, _) in enumerate(BLOCKS)]  # fmt: skip


RENDERED = "VPN dùng cổng 443.\n\n1. Mở ứng dụng\n2. Chọn Connect\n\nNguồn:\n- Cài đặt VPN › Windows › Bước 2"


async def seed_answer(
    db: PgUrls, ticket: str, *, event: str = "deflected_info_only", cited: tuple[str, ...] = ("KB-VPN-001#2",),
    prompt_full: str | None = "auto", errors: tuple[str | None, ...] = (None,), state: bool = True, b10: bool = True,
    created: datetime = NOW,
) -> None:  # fmt: skip
    engine = create_async_engine(db.role("app_rw"))
    try:
        async with engine.begin() as conn:
            await seed.leaf_ticket(conn, created_at=created, ticket_id=ticket)
            turn = await seed.turn(conn, ticket, started_at=created)
            await seed.audit_row(conn, ticket, step="B8", event="retrieved", created_at=created,
                                 detail={"chunk_ids": [b[0] for b in BLOCKS]})  # fmt: skip
            if b10:
                await seed.audit_row(conn, ticket, step="B10", event=event, created_at=created + timedelta(seconds=1),
                                     detail={"cited": list(cited), "citation": "ok"})  # fmt: skip
            for i, error in enumerate(errors):
                span = await seed.span(conn, turn, name="llm:b10_answer", started_at=created, duration_ms=50, span_type="llm")
                call = await seed.llm_call(conn, span, created_at=created + timedelta(seconds=i), prompt_id="b10_answer")
                full = _prompt_full("VPN dùng cổng nào?", BLOCKS) if prompt_full == "auto" else prompt_full
                await conn.execute(text("UPDATE llm_calls SET prompt_full = :p, error = :e WHERE call_id = :c"),
                                   {"p": full, "e": error, "c": call})  # fmt: skip
    finally:
        await engine.dispose()
    if state:
        cited_refs = [r for r in chunk_refs() if r.chunk_id in cited]
        await put_state(db, ticket, {"conversation": [answer_msg(RENDERED, "ref-1", cited_refs)], "retrieved": chunk_refs(), "kb_version": "v1"})


def estimator_factory(run_id: str, **_: Any) -> Any:
    """`--llm-factory` của test pipeline G10: gateway thật + ScriptedLLM trả `b14_risk_estimate`."""
    from tests.fakes.llm import make_gateway

    return make_gateway({"b14_risk_estimate": lambda v: ESTIMATE}).client


def question(sid: str, ticket: str, family: str = "KB-VPN-001") -> col.Question:
    return col.Question(scenario_id=sid, family=family, ticket_id=ticket)


# ---- collector G11 ---------------------------------------------------------------------------------------------------------------------


async def test_collect_builds_answers_row_with_neighbour_chunks_and_family_from_input(db: PgUrls) -> None:
    await seed_answer(db, "col-ok")
    async with open_reader(cfg(db)) as reader:
        rows, rep = await col.collect(reader, [question("P001", "col-ok", family="Họ-từ-đầu-vào")])
    [row] = rows
    assert (row["scenario_id"], row["family"], row["cannot_answer"], row["citations"]) == ("P001", "Họ-từ-đầu-vào", False, ["KB-VPN-001#2"])
    assert row["answer"] == RENDERED and row["steps"] is None
    by_id = {c["chunk_id"]: c for c in row["chunks"]}
    assert by_id["KB-VPN-001#2"]["text"] == BLOCKS[0][3]  # chunk liền kề (đoạn ghép nhiều đoạn văn) còn nguyên
    assert by_id["KB-VPN-003#1"]["text"] == BLOCKS[1][3] and by_id["KB-VPN-001#2"]["title"] == "Cài đặt VPN"
    assert by_id["KB-VPN-001#2"]["doc_id"] == "KB-VPN-001" and by_id["KB-VPN-001#2"]["heading_path"] == "Windows › Bước 2"
    assert rep == {"n_questions": 1, "n_collected": 1, "n_families": 1, "n_cannot_answer": 0, "skipped": {}}


async def test_collect_cannot_answer_and_skips_are_counted_by_reason(db: PgUrls) -> None:
    await seed_answer(db, "col-cant", event="cannot_answer", prompt_full=None, state=False)
    await seed_answer(db, "col-inv", event="invalid_citation")
    await seed_answer(db, "col-nob10", b10=False)
    await seed_answer(db, "col-nopf", prompt_full=None)
    await seed_answer(db, "col-noerr", errors=("LLMUnavailable",))  # chỉ có lời gọi lỗi → không có prompt dùng được
    await seed_answer(db, "col-bad", prompt_full=_prompt_full("q", BLOCKS[1:]))  # thiếu khối của chunk được dẫn
    await seed_answer(db, "col-nostate", state=False)
    qs = [question(f"S{i}", t) for i, t in enumerate(["col-cant", "col-inv", "col-nob10", "col-nopf", "col-noerr", "col-bad", "col-nostate", "khong-co"])]
    async with open_reader(cfg(db)) as reader:
        rows, rep = await col.collect(reader, qs)
    assert [r["scenario_id"] for r in rows] == ["S0"] and rows[0]["cannot_answer"] is True and rows[0]["chunks"] == []
    assert rep["skipped"] == {"not_answered:invalid_citation": 1, "no_b10": 1, "no_prompt_full": 2, "evidence_parse_failed": 1,
                              "no_checkpoint": 1, "ticket_not_found": 1}  # fmt: skip
    assert col.has_system_skips(rep)


async def test_collect_uses_the_last_successful_b10_answer_call(db: PgUrls) -> None:
    other = [(b[0], b[1], b[2], "NỘI DUNG CŨ") if i == 0 else b for i, b in enumerate(BLOCKS)]
    engine = create_async_engine(db.role("app_rw"))
    await seed_answer(db, "col-multi", prompt_full=_prompt_full("q", other), errors=(None,))
    try:
        async with engine.begin() as conn:  # lời gọi 2 (mới nhất, đúng) rồi lời gọi 3 (lỗi, bị bỏ)
            turn = str((await conn.execute(text("SELECT turn_id FROM turns WHERE ticket_id = 'col-multi'"))).scalar_one())
            for err, full in ((None, _prompt_full("q", BLOCKS)), ("LLMUnavailable", _prompt_full("q", other))):
                span = await seed.span(conn, turn, name="llm:b10_answer", started_at=NOW, duration_ms=5, span_type="llm")
                call = await seed.llm_call(conn, span, created_at=NOW + timedelta(minutes=5), prompt_id="b10_answer")
                await conn.execute(text("UPDATE llm_calls SET prompt_full = :p, error = :e WHERE call_id = :c"), {"p": full, "e": err, "c": call})
    finally:
        await engine.dispose()
    async with open_reader(cfg(db)) as reader:
        rows, _ = await col.collect(reader, [question("M1", "col-multi")])
    assert {c["chunk_id"]: c["text"] for c in rows[0]["chunks"]}["KB-VPN-001#2"] == BLOCKS[0][3]


async def test_collect_window_filters_by_ticket_created_at(db: PgUrls) -> None:
    await seed_answer(db, "col-win", created=NOW)
    async with open_reader(cfg(db)) as reader:
        inside, _ = await col.collect(reader, [question("W", "col-win")], since=NOW, until=NOW + timedelta(seconds=1))
        before, rep1 = await col.collect(reader, [question("W", "col-win")], until=NOW)
        after, rep2 = await col.collect(reader, [question("W", "col-win")], since=NOW + timedelta(seconds=1))
    assert len(inside) == 1 and not before and not after
    assert rep1["skipped"] == rep2["skipped"] == {"out_of_window": 1}


async def test_reader_sessions_are_read_only(db: PgUrls) -> None:
    async with open_reader(cfg(db)) as reader:
        async with reader.engine.connect() as conn:
            with pytest.raises(DBAPIError, match="read-only"):
                await conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('x-ro', 'x.ro', 'employee')"))
        pool: Any = reader.saver.conn  # AsyncConnectionPool của checkpoint
        async with pool.connection() as pg_conn:  # cả pool của checkpoint
            with pytest.raises(Exception, match="read-only"):
                await pg_conn.execute("INSERT INTO users (user_id, username, role) VALUES ('x-ro2', 'x.ro2', 'employee')")
    assert await count(create_async_engine(db.role("app_rw")), "SELECT count(*) FROM users WHERE user_id LIKE 'x-ro%'") == 0


async def test_collect_cli_end_to_end_then_judge(db: PgUrls, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await seed_answer(db, "cli-ok")
    await seed_answer(db, "cli-nopf", prompt_full=None)
    monkeypatch.setenv("DATABASE_URL", db.role("app_rw"))
    qfile = tmp_path / "q.jsonl"
    qfile.write_text("".join(json.dumps(r) + "\n" for r in (
        {"scenario_id": "P001", "family": "DOC-A", "ticket_id": "cli-ok"}, {"scenario_id": "P002", "family": "DOC-B", "ticket_id": "cli-nopf"},
    )), encoding="utf-8")  # fmt: skip
    out = tmp_path / "collected"
    assert await asyncio.to_thread(main, ["collect", "--questions", str(qfile), "--out", str(out)]) == EXIT_JUDGE_ERRORS  # có ca bỏ vì lỗi hệ thống
    rep = json.loads((out / "collect_report.json").read_text(encoding="utf-8"))
    assert rep["skipped"] == {"no_prompt_full": 1} and rep["n_collected"] == 1 and rep["n_families"] == 1
    rows = load_answers(out / "answers.jsonl")  # đúng hợp đồng G11 (family bắt buộc, chunk_id duy nhất…)
    assert [(r.scenario_id, r.family, r.citations) for r in rows] == [("P001", "DOC-A", ("KB-VPN-001#2",))]
    judged = tmp_path / "judged"
    judge_args = ["judge", "--answers", str(out / "answers.jsonl"), "--out", str(judged), "--llm-factory", "tests.unit.eval._g11:factory"]
    assert await asyncio.to_thread(main, judge_args) == 0
    assert json.loads((judged / report.SUMMARY).read_text(encoding="utf-8"))["n_judged"] == 1
    assert await asyncio.to_thread(main, ["collect", "--questions", str(qfile), "--out", str(out)]) == 2  # không ghi đè


# ---- G10: collector + pipeline -------------------------------------------------------------------------------------------------------


def action(requested_for: str = "nv001") -> Action:
    return Action(type="renew_vpn_cert", target="device:LAP-0342", requested_for=requested_for, scope="single_device",
                  privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="low",
                  params={"device_id": "LAP-0342"},
                  facts={"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired"})  # fmt: skip


def requester() -> RequesterContext:
    return RequesterContext(user_id="nv001", role="employee", department="finance", manager_id="ql007", employment_status="active",
                            tenure_days=400, is_privileged_account=False, captured_at=NOW)  # fmt: skip


async def seed_risk(
    db: PgUrls, ticket: str, *, raw_prob: float = 0.4, p_method: str = "self_report", kb_gap: bool | None = False,
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
        await put_state(db, ticket, {"intended_action": act or action(), "requester_context": requester(), "ctx_flags": flags or {}})


def predictions(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    write_predictions(run / "predictions.jsonl", rows)
    return run


HOURS = load_policy(CONFIG / "policy.json").business_hours


async def test_gather_builds_with_rows_and_cases_exactly_like_b12(db: PgUrls, tmp_path: Path) -> None:
    await seed_risk(db, "g10-a", raw_prob=0.31, kb_gap=False)
    await seed_risk(db, "g10-b", raw_prob=0.77, kb_gap=True, when=SATURDAY, flags={"target_is_other": True}, act=action("nv002"))
    path = predictions(tmp_path, [
        prediction(scenario_id="A-v1", family="A", ticket_id="g10-a", raw_prob=0.31, expected_route="AUTO"),
        prediction(scenario_id="B-v1", family="B", ticket_id="g10-b", raw_prob=0.77, expected_route="HITL"),
    ])  # fmt: skip
    async with open_reader(cfg(db)) as reader:
        got = await gather(reader, load_predictions(path / "predictions.jsonl"), hours=HOURS, p_method="self_report")
    assert got.recorded == [
        {"scenario_id": "A-v1", "family": "A", "split": "test", "gold_route": "AUTO", "raw_prob": 0.31, "kb_gap": False},
        {"scenario_id": "B-v1", "family": "B", "split": "test", "gold_route": "HITL", "raw_prob": 0.77, "kb_gap": True},
    ]  # fmt: skip
    a, b = got.cases
    assert a["ctx"]["within_business_hours"] is True and a["ctx"]["target_is_other"] is False
    assert b["ctx"]["within_business_hours"] is False and b["ctx"]["target_is_other"] is True  # thứ Bảy; cờ + requested_for khác người gửi
    assert Action.model_validate(a["action"]) == action() and a["ctx"]["requester"]["user_id"] == "nv001"
    assert got.report["n_gathered"] == 2 and got.report["n_kb_gap"] == 1 and got.report["skipped"] == {}


async def test_gather_target_is_other_comes_from_ctx_flags_alone(db: PgUrls, tmp_path: Path) -> None:
    await seed_risk(db, "g10-flag", flags={"target_is_other": True})  # requested_for == người gửi, chỉ có cờ B6
    await seed_risk(db, "g10-noflag")
    path = predictions(tmp_path, [prediction(scenario_id="F-v1", family="F", ticket_id="g10-flag", raw_prob=0.4),
                                  prediction(scenario_id="G-v1", family="G", ticket_id="g10-noflag", raw_prob=0.4)])  # fmt: skip
    async with open_reader(cfg(db)) as reader:
        got = await gather(reader, load_predictions(path / "predictions.jsonl"), hours=HOURS, p_method="self_report")
    assert [c["ctx"]["target_is_other"] for c in got.cases] == [True, False]


async def test_gather_skips_incomplete_cases_by_reason_and_never_guesses(db: PgUrls, tmp_path: Path) -> None:
    await seed_risk(db, "g10-nogap", kb_gap=None)
    await seed_risk(db, "g10-mismatch", raw_prob=0.9)
    await seed_risk(db, "g10-nostate", state=False)
    path = predictions(tmp_path, [
        prediction(scenario_id="N-v1", family="N", ticket_id="g10-nogap", raw_prob=0.4),
        prediction(scenario_id="M-v1", family="M", ticket_id="g10-mismatch", raw_prob=0.4),
        prediction(scenario_id="S-v1", family="S", ticket_id="g10-nostate", raw_prob=0.4),
        prediction(scenario_id="X-v1", family="X", ticket_id="g10-nolog", raw_prob=0.4),
        prediction(scenario_id="U-v1", family="U", ticket_id="g10-unl", raw_prob=0.4, expected_route=None),
    ])  # fmt: skip
    async with open_reader(cfg(db)) as reader:
        got = await gather(reader, load_predictions(path / "predictions.jsonl"), hours=HOURS, p_method="self_report")
    assert got.recorded == [] and got.report["skipped"] == {"no_kb_gap": 1, "raw_prob_mismatch": 1, "no_state": 1, "no_log4": 1, "unlabeled": 1}


async def test_gather_refuses_a_different_p_method(db: PgUrls, tmp_path: Path) -> None:
    await seed_risk(db, "g10-pm", p_method="sampling_k5")
    path = predictions(tmp_path, [prediction(scenario_id="P-v1", family="P", ticket_id="g10-pm", raw_prob=0.4, p_method="sampling_k5")])
    async with open_reader(cfg(db)) as reader:
        with pytest.raises(CollectError, match="p_method"):
            await gather(reader, load_predictions(path / "predictions.jsonl"), hours=HOURS, p_method="self_report")


async def test_collect_no_evidence_pipeline_end_to_end(db: PgUrls, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for t, p, gap in (("pipe-a", 0.30, False), ("pipe-b", 0.70, True)):
        await seed_risk(db, t, raw_prob=p, kb_gap=gap)
    run = predictions(tmp_path, [
        prediction(scenario_id="PA-v1", family="PA", ticket_id="pipe-a", raw_prob=0.30, split="test", expected_route="AUTO"),
        prediction(scenario_id="PB-v1", family="PB", ticket_id="pipe-b", raw_prob=0.70, split="test", expected_route="HITL"),
    ])  # fmt: skip
    monkeypatch.setenv("DATABASE_URL", db.role("app_rw"))
    pv: ModuleType = load_script("scripts/eval/prob_variants.py", monkeypatch)
    out = tmp_path / "out"
    args = ["collect-no-evidence", "--run", str(run), "--out", str(out), "--p-method", "self_report",
            "--llm-factory", "tests.integration.test_noi_that_pg:estimator_factory"]  # fmt: skip
    code = await asyncio.to_thread(pv.main, args)
    assert code == 0
    probs = [json.loads(line) for line in (out / "probs.jsonl").read_text(encoding="utf-8").splitlines()]
    by = {(r["scenario_id"], r["variant"]): r["raw_prob"] for r in probs}
    assert by[("PA-v1", "with_evidence")] == 0.30 and by[("PA-v1", "no_evidence")] == pytest.approx(0.42)
    assert by[("PA-v1", "max")] == pytest.approx(0.42)
    assert by[("PB-v1", "with_evidence")] == 0.70 and by[("PB-v1", "no_evidence")] == 0.70  # kb_gap: chép, không gọi lại
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["p_method"] == "self_report" and manifest["build"]["n_copied_kb_gap"] == 1 and manifest["gathered"]["n_kb_gap"] == 1
    for name in ("with.jsonl", "cases.jsonl", "without.jsonl", "probs.jsonl", "manifest.json"):
        assert (out / name).exists(), name
    assert [json.loads(x)["scenario_id"] for x in (out / "without.jsonl").read_text(encoding="utf-8").splitlines()] == ["PA-v1"]
