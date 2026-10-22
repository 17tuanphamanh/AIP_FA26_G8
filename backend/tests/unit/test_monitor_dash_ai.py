"""M9 A2 — phần thuần + tĩnh của `queries/ai.py`: hợp đồng mục 3 (`b2_llm_rate`, `b3_llm_rate`), cửa sổ, mốc ngày giờ VN,
`E2_LLM_REASONS` (Q-M9-A2-4) đối chiếu code graph, D-30 tĩnh (mọi truy vấn qua `v_leaf`)."""

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.domain.exit_codes import REASON_DETAILS
from app.monitor.metrics import E2_LLM_REASONS, METRIC_SOURCES
from app.monitor.queries import ai
from app.monitor.window import VN_TZ

REPO = Path(__file__).resolve().parents[3]
AI_SRC = REPO / "backend" / "app" / "monitor" / "queries" / "ai.py"
GRAPH_NODES = REPO / "backend" / "app" / "graph" / "nodes"
FRM = datetime(2030, 1, 1, tzinfo=UTC)
TO = datetime(2030, 1, 2, tzinfo=UTC)
LLM_ERRORS = {"LLMUnavailable", "LLMSchemaError", "LLMBudgetExceeded"}


@pytest.mark.parametrize("fn", [ai.b2_llm_rate, ai.b3_llm_rate, ai.multi_intent_first_stop_to_reply_s])
def test_contract_signatures(fn: Any) -> None:
    sig = inspect.signature(fn)
    assert inspect.iscoroutinefunction(fn)
    assert list(sig.parameters) == ["conn", "frm", "to"]
    assert sig.return_annotation == float | None


@pytest.mark.parametrize(
    "fn", [ai.ai_metrics, ai.b2_llm_rate, ai.b3_llm_rate, ai.cost_per_day, ai.multi_intent_first_stop_to_reply_s]
)
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (datetime(2030, 1, 1), TO),  # noqa: DTZ001 — cố ý naive
        (FRM, datetime(2030, 1, 2)),  # noqa: DTZ001
        (TO, FRM),
        (FRM, FRM),
    ],
)
@pytest.mark.asyncio
async def test_naive_or_inverted_window_rejected(fn: Any, frm: datetime, to: datetime) -> None:
    conn: Any = None  # kiểm cửa sổ trước khi chạm DB
    with pytest.raises(ValueError):
        await fn(conn, frm, to)


def test_queries_cover_ai_metrics() -> None:
    assert set(ai.QUERIES) == set(ai.AI_METRICS)
    for key, query in ai.QUERIES.items():
        assert (query is None) == (METRIC_SOURCES[key].status == "pending"), key


def test_day_starts_vn() -> None:
    vn_midnight = datetime(2030, 2, 1, 17, tzinfo=UTC)  # 2030-02-02 00:00 giờ VN
    assert ai.day_starts(vn_midnight, vn_midnight + timedelta(days=2)) == [
        vn_midnight, vn_midnight + timedelta(days=1),
    ]  # fmt: skip
    # 23:59 → 00:01 giờ VN: 2 ngày, ngày đầu bắt đầu từ 00:00 VN hôm trước
    assert ai.day_starts(vn_midnight - timedelta(minutes=1), vn_midnight + timedelta(minutes=1)) == [
        vn_midnight - timedelta(days=1), vn_midnight,
    ]  # fmt: skip
    assert ai.day_starts(FRM, TO) == [datetime(2029, 12, 31, 17, tzinfo=UTC), datetime(2030, 1, 1, 17, tzinfo=UTC)]


def test_day_starts_other_tz_and_dst() -> None:
    tokyo = ZoneInfo("Asia/Tokyo")
    assert ai.day_starts(FRM, TO, tokyo) == [datetime(2029, 12, 31, 15, tzinfo=UTC), datetime(2030, 1, 1, 15, tzinfo=UTC)]
    assert ai.day_starts(FRM, TO, tokyo) != ai.day_starts(FRM, TO, VN_TZ)
    berlin = ZoneInfo("Europe/Berlin")  # 2030-10-27 dài 25 giờ, 2030-03-31 dài 23 giờ
    for first in (datetime(2030, 10, 26, tzinfo=berlin), datetime(2030, 3, 30, tzinfo=berlin)):
        days = ai.day_starts(first, first + timedelta(days=3), berlin)
        local = [d.astimezone(berlin) for d in days]
        assert [d.date() for d in local] == [(first + timedelta(days=i)).date() for i in range(3)]
        assert all((d.hour, d.minute) == (0, 0) for d in local)


def test_day_starts_ninety_days_bounded() -> None:
    days = ai.day_starts(FRM, FRM + timedelta(days=90))
    assert len(days) <= 91
    assert days == sorted(set(days))


def test_e2_llm_reasons_constant() -> None:
    assert E2_LLM_REASONS == ("llm_unavailable", "llm_schema_error", "screening_unavailable")
    assert set(E2_LLM_REASONS) <= REASON_DETAILS
    # Phase 4b (tra người duyệt lỗi) và hết hạn lượt (lẫn nguồn) KHÔNG phải E2 do LLM (Q-M9-A2-4)
    assert not {"approver_lookup_error", "approver_sync_unavailable", "turn_budget_exceeded"} & set(E2_LLM_REASONS)


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return {n.id for n in nodes if isinstance(n, ast.Name)}


def _is_e2(value: ast.expr) -> bool:
    """`ExitCode.E2.value`."""
    return (
        isinstance(value, ast.Attribute) and value.attr == "value"
        and isinstance(value.value, ast.Attribute) and value.value.attr == "E2"
        and isinstance(value.value.value, ast.Name) and value.value.value.id == "ExitCode"
    )  # fmt: skip


def test_e2_llm_reasons_cover_graph_llm_handlers() -> None:
    """Mọi lời gọi trong khối `except` bắt lỗi LLM mà ra E2 phải mang `reason_detail` ∈ `E2_LLM_REASONS`, và hằng không
    thừa giá trị nào. Đọc mã nguồn (AST), không import `app.graph`."""
    found: list[tuple[str, str]] = []
    for path in sorted(GRAPH_NODES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.type is not None):
            if not _handler_names(handler) & LLM_ERRORS:
                continue
            for call in (n for stmt in handler.body for n in ast.walk(stmt) if isinstance(n, ast.Call)):
                kw = {k.arg: k.value for k in call.keywords if k.arg}
                reason = kw.get("escalation_reason_detail")
                if "exit_code" in kw and _is_e2(kw["exit_code"]) and isinstance(reason, ast.Constant):
                    found.append((path.name, str(reason.value)))
    assert len(found) >= 11, found  # b02 1, b03 2, b10 4, b11 2, clarify_wait 2 — quét rỗng thì đỏ
    assert {reason for _, reason in found} == set(E2_LLM_REASONS), found


def _functions(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def test_ai_functions_read_v_leaf() -> None:
    """D-30 ghim tĩnh lớp 2: mọi truy vấn trong `QUERIES` dùng `V_LEAF` trực tiếp hoặc qua hàm phụ của module có dùng."""
    funcs = _functions(ast.parse(AI_SRC.read_text(encoding="utf-8")))
    calls = {
        name: {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        for name, fn in funcs.items()
    }
    reads = {name for name, fn in funcs.items() if any(isinstance(n, ast.Name) and n.id == "V_LEAF" for n in ast.walk(fn))}
    while grown := {name for name in funcs if name not in reads and calls[name] & reads}:
        reads |= grown
    queries = {q.__name__ for q in ai.QUERIES.values() if q is not None}
    assert len(queries) == 13  # F12: + multi_intent_first_stop_to_reply_s
    assert queries <= reads, sorted(queries - reads)
