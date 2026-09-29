"""`lineage` (P7; phase3 10.3; chốt Q-3g-3 3g): goto nhận `lineage=` → audit ghi CÙNG transaction, idempotent theo (ticket_id,
turn_id, step, prompt_id). Bản Postgres (chạy lại node trong cùng lượt → đúng 1 dòng): `integration/test_b10_pg.py`."""

from typing import Any

import pytest
from app.core.clock import FakeClock
from app.db.lineage import LINEAGE_COLUMNS, check_lineage_row, insert_once
from app.domain.states import S_CONFIRMING, S_RETRIEVING
from app.graph.context import RunContext, bind_run
from app.graph.goto import goto
from sqlalchemy.dialects import postgresql
from tests.fakes.graph import MemoryAudit, MemoryEffects, MemorySpans

ROW = {"ticket_id": "t1", "turn_id": "T1", "step": "B10", "created_at": FakeClock().now(), "prompt_id": "b10_answer"}


def test_lineage_columns_match_table() -> None:
    assert {"ticket_id", "turn_id", "step", "prompt_id", "prompt_version", "model", "kb_version", "commit_sha",
            "created_at"} <= LINEAGE_COLUMNS  # fmt: skip
    assert "lineage_id" not in LINEAGE_COLUMNS


@pytest.mark.parametrize("bad", [{**ROW, "question": "x"}, {**ROW, "turn_id": None}, {**ROW, "step": ""}])
def test_check_lineage_row_rejects_unknown_or_missing(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="lineage"):
        check_lineage_row(bad)


@pytest.mark.asyncio
async def test_insert_once_is_insert_select_where_not_exists() -> None:
    class Conn:
        sql = ""

        async def execute(self, stmt: Any) -> None:
            Conn.sql = str(stmt.compile(dialect=postgresql.dialect()))

    await insert_once(Conn(), ROW)  # type: ignore[arg-type]
    sql = " ".join(Conn.sql.split())
    assert sql.startswith("INSERT INTO lineage") and "WHERE NOT (EXISTS" in sql
    for key in ("ticket_id", "turn_id", "step", "prompt_id"):
        assert f"lineage.{key} IS NOT DISTINCT FROM" in sql


@pytest.mark.asyncio
async def test_goto_passes_lineage_with_context_fields_and_keeps_it_out_of_state() -> None:
    audit, clock = MemoryAudit(), FakeClock()
    run = RunContext(turn_id="T7", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                     clock=clock)  # fmt: skip
    state = {"ticket_id": "t1", "status": S_RETRIEVING}
    with bind_run(run):
        out = await goto(state, S_CONFIRMING, next_node="confirm_wait", step="B10", event="deflected_info_only",
                         lineage={"prompt_id": "b10_answer", "prompt_version": "1", "model": "m", "kb_version": "a" * 64})
        again = await goto(state, S_CONFIRMING, next_node="confirm_wait", step="B10", event="deflected_info_only",
                           lineage={"prompt_id": "b10_answer", "prompt_version": "1", "model": "m", "kb_version": "a" * 64})
    assert "lineage" not in out and out == again == {"status": S_CONFIRMING, "next": "confirm_wait"}
    assert audit.lineage == [{"prompt_id": "b10_answer", "prompt_version": "1", "model": "m", "kb_version": "a" * 64,
                              "ticket_id": "t1", "turn_id": "T7", "step": "B10", "created_at": clock.now()}]  # fmt: skip
    assert len(audit.rows) == 1


@pytest.mark.asyncio
async def test_goto_rejects_bad_lineage_before_writing_audit() -> None:
    audit = MemoryAudit()
    run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                     clock=FakeClock())  # fmt: skip
    with bind_run(run), pytest.raises(ValueError, match="cột lạ"):
        await goto({"ticket_id": "t1", "status": S_RETRIEVING}, S_CONFIRMING, next_node="confirm_wait", step="B10",
                   event="deflected_info_only", lineage={"answer_text": "không được lưu"})
    assert audit.rows == [] and audit.lineage == []
