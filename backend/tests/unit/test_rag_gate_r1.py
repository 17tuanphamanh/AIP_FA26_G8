"""R1 — `GateMetrics` / `eval_cli` thêm 3 thứ MỚI mà không đổi gì cũ:

- `p_at_1`: tỉ lệ câu có đáp án mà tài liệu hạng 1 ∈ `expected_doc_ids`;
- `recall_at_threshold`: tỉ lệ câu có đáp án mà tài liệu đúng nằm trong top-5 VÀ `top_score ≥ RETRIEVAL_THRESHOLD` (bằng ngưỡng thì trúng);
- lượt chạy KHÔNG lọc intent (`evaluate_without_intent`, `search_once(use_intent=False)`), in thêm ở `eval_cli`.

`recall_at5` giữ nghĩa cũ (không xét ngưỡng); `decide()` — điều kiện cổng ingest — không đọc trường mới (test_rag_gate.py giữ nguyên, xanh).
"""

import dataclasses
from typing import Any

import pytest
from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.rag import eval_cli
from app.rag.ingest.gate import (
    EvalItem,
    GateMetrics,
    RetrievalSet,
    SearchPair,
    decide,
    evaluate,
    evaluate_without_intent,
    metrics,
    sweep,
)
from app.rag.models import RetrievalQuery

T = 0.6


def item(i: str, expected: list[str], intent: str = "vpn") -> EvalItem:
    return EvalItem(id=i, query=f"câu {i}", intent=intent, role="employee", expected_doc_ids=expected)


# 7 câu có đáp án + 2 âm tính. Bảng tay (T = 0,6):
#   câu  top-5          score  r@5  P@1  r@T
#   A    A,B            0.90    ✓    ✓    ✓
#   B    B,A            0.80    ✓    ✗    ✓      (đúng ở hạng 2)
#   C    A              0.40    ✓    ✓    ✗      (đúng nhưng dưới ngưỡng)
#   D    Z              0.90    ✗    ✗    ✗
#   F    Z,Y,A          0.30    ✓    ✗    ✗
#   G    A              0.60    ✓    ✓    ✓      (đúng bằng ngưỡng)
#   H    A              0.10    ✓    ✓    ✗
#   → r@5 = 6/7, P@1 = 4/7, r@T = 3/7
RESULTS: list[tuple[EvalItem, list[str], float]] = [
    (item("A", ["A"]), ["A", "B"], 0.90),
    (item("B", ["A"]), ["B", "A"], 0.80),
    (item("C", ["A"]), ["A"], 0.40),
    (item("D", ["A"]), ["Z"], 0.90),
    (item("F", ["A"]), ["Z", "Y", "A"], 0.30),
    (item("G", ["A"]), ["A"], 0.60),
    (item("H", ["A"]), ["A"], 0.10),
    (item("N1", []), ["A"], 0.70),
    (item("N2", []), [], 0.0),
]


def test_new_fields_by_hand() -> None:
    m = metrics(RESULTS, T)
    assert m.p_at_1 == pytest.approx(4 / 7)
    assert m.recall_at_threshold == pytest.approx(3 / 7)


def test_old_fields_keep_their_meaning() -> None:
    """`recall_at5` KHÔNG xét ngưỡng; FG, MRR, đếm giữ nguyên."""
    m = metrics(RESULTS, T)
    assert m.recall_at5 == pytest.approx(6 / 7)
    assert m.false_grounding_rate == pytest.approx(1 / 2)
    assert m.mrr == pytest.approx((1 + 1 / 2 + 1 + 0 + 1 / 3 + 1 + 1) / 7)
    assert (m.positives, m.negatives) == (7, 2)


def test_recall_at_threshold_is_inclusive_and_needs_both_conditions() -> None:
    one = [(item("P", ["A"]), ["A"], 0.6), (item("N", []), [], 0.0)]
    assert metrics(one, 0.6).recall_at_threshold == 1.0  # bằng ngưỡng → trúng
    assert metrics(one, 0.61).recall_at_threshold == 0.0  # dưới ngưỡng → trượt dù đúng tài liệu
    assert metrics(one, 0.61).recall_at5 == 1.0
    wrong = [(item("P", ["A"]), ["Z"], 0.99), (item("N", []), [], 0.0)]
    assert metrics(wrong, 0.6).recall_at_threshold == 0.0  # trên ngưỡng nhưng sai tài liệu


def test_p_at_1_uses_any_expected_doc_at_rank_one_only() -> None:
    rs = [(item("P", ["A", "B"]), ["B", "A"], 0.9), (item("Q", ["A", "B"]), ["Z", "A"], 0.9), (item("N", []), [], 0.0)]
    m = metrics(rs, T)
    assert m.p_at_1 == pytest.approx(1 / 2)


def test_no_positives_gives_zero_not_crash() -> None:
    m = metrics([(item("N", []), ["A"], 0.9)], T)
    assert (m.p_at_1, m.recall_at_threshold, m.recall_at5) == (0.0, 0.0, 0.0)


def test_old_positional_construction_still_works() -> None:
    m = GateMetrics(0.9, 0.0, 0.5, 8, 6)  # 5 đối số như mọi chỗ dựng cũ
    assert (m.p_at_1, m.recall_at_threshold) == (0.0, 0.0)


@pytest.mark.parametrize(("r", "fg"), [(0.80, 0.05), (0.799, 0.0), (1.0, 0.051), (0.9, 0.0)])
def test_ingest_gate_ignores_new_fields(r: float, fg: float) -> None:
    """Cổng ingest (b/c) chỉ đọc `recall_at5` + `false_grounding_rate`: đổi trường mới thế nào cũng không đổi quyết định."""
    base = GateMetrics(r, fg, 0.0, 8, 6)
    for p1, rt in [(0.0, 0.0), (1.0, 1.0), (0.3, 0.9)]:
        varied = dataclasses.replace(base, p_at_1=p1, recall_at_threshold=rt)
        assert decide(has_set=True, allow_unevaluated=False, new=varied, old=None).passed == \
            decide(has_set=True, allow_unevaluated=False, new=base, old=None).passed  # fmt: skip
        assert decide(has_set=True, allow_unevaluated=False, new=varied, old=base).passed == \
            decide(has_set=True, allow_unevaluated=False, new=base, old=base).passed  # fmt: skip


# ---- evaluate / evaluate_without_intent -----------------------------------------------------------------------------------


class FakeTop:
    """`Retriever` hẹp của cổng kiểm (D-23 hai bước nằm trong retrieve thật — ở đây trả sẵn)."""

    def __init__(self, table: dict[str, tuple[list[str], float]]) -> None:
        self.table = table

    async def top_docs(self, it: EvalItem, *, collection: str) -> tuple[list[str], float]:
        return self.table[it.id]


class FakeOnce:
    """`search_once` giả: ghi lại `use_intent` và `intent` của từng truy vấn."""

    def __init__(self, table: dict[str, tuple[list[str], float]]) -> None:
        self.table = table
        self.calls: list[tuple[str, str | None, bool, str]] = []

    async def search_once(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str, use_intent: bool
    ) -> tuple[list[ChunkRef], float]:
        doc_ids, score = self.table[q.text.removeprefix("câu ")]
        self.calls.append((q.text, q.intent, use_intent, ctx.role))
        chunks = [ChunkRef(chunk_id=f"{d}#0", doc_id=d, version=1, seq=0, title="T", heading_path="H", score=score, excerpt="x")
                  for d in doc_ids]  # fmt: skip
        return chunks, score


def rs_of(results: list[tuple[EvalItem, list[str], float]]) -> RetrievalSet:
    return RetrievalSet(version=1, kb_scope=["vpn"], items=[r[0] for r in results])


@pytest.mark.asyncio
async def test_evaluate_fills_new_fields_with_the_real_threshold() -> None:
    table = {it.id: (top, score) for it, top, score in RESULTS}
    m = await evaluate(rs_of(RESULTS), FakeTop(table), "kb_x", T)
    assert (m.recall_at5, round(m.p_at_1, 6), round(m.recall_at_threshold, 6)) == (
        pytest.approx(6 / 7), round(4 / 7, 6), round(3 / 7, 6),
    )  # fmt: skip


@pytest.mark.asyncio
async def test_without_intent_run_never_filters_by_intent_and_reports_all_fields() -> None:
    table = {it.id: (top, score) for it, top, score in RESULTS}
    once = FakeOnce(table)
    m = await evaluate_without_intent(rs_of(RESULTS), once, "kb_x", T)
    assert len(once.calls) == len(RESULTS) and all(use_intent is False for _, _, use_intent, _ in once.calls)
    assert {role for *_, role in once.calls} == {"employee"}  # vẫn lọc QUYỀN theo vai trò câu kiểm tra
    assert m == metrics(RESULTS, T)  # cùng dữ liệu → cùng chỉ số như `metrics` trên kết quả tương ứng


@pytest.mark.asyncio
async def test_without_intent_run_can_differ_from_filtered_run() -> None:
    """Lọc intent làm đúng một câu (P) lọt top-1; bỏ lọc thì tài liệu đó tụt hạng → P@1 khác nhau giữa hai lượt."""
    res = [(item("P", ["A"]), ["A"], 0.9), (item("N", []), [], 0.0)]
    with_intent = await evaluate(rs_of(res), FakeTop({"P": (["A"], 0.9), "N": ([], 0.0)}), "kb_x", T)
    without = await evaluate_without_intent(rs_of(res), FakeOnce({"P": (["Z", "A"], 0.9), "N": ([], 0.0)}), "kb_x", T)
    assert (with_intent.p_at_1, without.p_at_1) == (1.0, 0.0)
    assert (with_intent.recall_at5, without.recall_at5) == (1.0, 1.0)


def test_sweep_computes_new_fields_at_each_threshold() -> None:
    pairs: dict[str, tuple[SearchPair, SearchPair]] = {
        it.id: ((top, score), (top, score)) for it, top, score in RESULTS
    }
    points = {p.threshold: p.metrics for p in sweep(rs_of(RESULTS), pairs, thresholds=[0.30, 0.85])}
    assert points[0.30].recall_at_threshold == pytest.approx(5 / 7)  # A,B,C,G và F(0.30 ≥ 0.30), không H(0.10)
    assert points[0.85].recall_at_threshold == pytest.approx(1 / 7)  # chỉ A
    assert points[0.30].recall_at5 == points[0.85].recall_at5 == pytest.approx(6 / 7)  # nghĩa cũ không phụ thuộc ngưỡng


# ---- eval_cli: dòng cũ giữ nguyên chữ, thêm dòng mới; CSV thêm cột ở CUỐI ---------------------------------------------------


def test_print_current_keeps_first_line_and_adds_new_metrics(capsys: pytest.CaptureFixture[str]) -> None:
    m = metrics(RESULTS, T)
    eval_cli._print_current(T, m)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        f"Recall@5 {m.recall_at5:.3f}  trả lời bừa {m.false_grounding_rate:.3f}  MRR {m.mrr:.3f}  "
        f"(câu có đáp án=7, câu âm tính=2, ngưỡng=0.60)"
    )  # fmt: skip
    assert "P@1 0.571" in lines[1] and "Recall@5 ở ngưỡng 0.429" in lines[1]


def test_print_without_intent_labels_the_run(capsys: pytest.CaptureFixture[str]) -> None:
    eval_cli._print_without_intent(metrics(RESULTS, T))
    out = capsys.readouterr().out
    assert out.startswith("Không lọc intent:") and "P@1 0.571" in out and "Recall@5 ở ngưỡng 0.429" in out


def test_sweep_csv_old_columns_first_then_new(capsys: pytest.CaptureFixture[str]) -> None:
    pairs: dict[str, tuple[SearchPair, SearchPair]] = {it.id: ((top, s), (top, s)) for it, top, s in RESULTS}
    eval_cli._print_sweep(sweep(rs_of(RESULTS), pairs, thresholds=[0.6]), csv=True)
    header, row = capsys.readouterr().out.splitlines()
    assert header == "threshold,recall_at5,false_grounding_rate,mrr,positives,negatives,p_at_1,recall_at_threshold"
    cells: list[Any] = row.split(",")
    assert cells[:1] == ["0.6"] and cells[4:6] == ["7", "2"] and float(cells[6]) == pytest.approx(4 / 7)
    assert float(cells[7]) == pytest.approx(3 / 7)


# ---- eval_cli._run nối đủ ba dòng (composition root dùng bản giả) -----------------------------------------------------------


class FakeIndex:
    async def alias_target(self, alias: str) -> str | None:
        return "kb_x"


class FakeRetriever:
    """Vừa là `RagPort.retrieve` (lượt có lọc intent + D-23 của cổng ingest) vừa là `search_once` (lượt không lọc / sweep)."""

    def __init__(self) -> None:
        self.retrieves = 0
        self.once: list[tuple[str, bool]] = []

    def _chunks(self, score: float) -> list[ChunkRef]:
        return [ChunkRef(chunk_id="KB-VPN-001#0", doc_id="KB-VPN-001", version=1, seq=0, title="T", heading_path="H", score=score,
                         excerpt="x")]  # fmt: skip

    async def retrieve(self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str) -> Any:
        from app.rag.models import RetrievalResult

        self.retrieves += 1
        found = "vpn" in q.text
        return RetrievalResult(chunks=self._chunks(0.9) if found else [], top_score=0.9 if found else 0.0, kb_version="a" * 64,
                               intent_filter_fallback=False, fallback_tried=False, retries=0, query_truncated=False)  # fmt: skip

    async def search_once(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str, use_intent: bool
    ) -> tuple[list[ChunkRef], float]:
        self.once.append((q.text, use_intent))
        found = "vpn" in q.text
        return (self._chunks(0.9), 0.9) if found else ([], 0.0)


def _kb(tmp_path: Any) -> Any:
    import yaml

    kb = tmp_path / "kb"
    (kb / "eval").mkdir(parents=True)
    data = {"version": 1, "kb_scope": ["vpn"], "items": [
        {"id": "P1", "query": "vpn cổng nào", "intent": "vpn", "role": "employee", "expected_doc_ids": ["KB-VPN-001"]},
        {"id": "N1", "query": "máy in kẹt giấy", "intent": "out_of_scope", "role": "employee", "expected_doc_ids": []},
    ]}  # fmt: skip
    (kb / "eval" / "retrieval_set.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return kb


@pytest.mark.asyncio
async def test_run_prints_old_line_new_line_and_without_intent_line(tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
    r = FakeRetriever()
    deps = eval_cli.EvalDeps(retriever=r, index=FakeIndex(), threshold=T)  # type: ignore[arg-type]
    assert await eval_cli._run(deps, _kb(tmp_path), do_sweep=False, csv=False) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "collection=kb_x"
    assert lines[1].startswith("Recall@5 1.000  trả lời bừa 0.000  MRR 1.000  (câu có đáp án=1, câu âm tính=1, ngưỡng=0.60)")
    assert lines[2] == "  P@1 1.000  Recall@5 ở ngưỡng 1.000"
    assert lines[3].startswith("Không lọc intent: Recall@5 1.000") and "P@1 1.000" in lines[3]
    assert r.retrieves == 2 and sorted(r.once) == [("máy in kẹt giấy", False), ("vpn cổng nào", False)]  # chỉ lượt không lọc


@pytest.mark.asyncio
async def test_run_sweep_csv_has_new_columns(tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
    deps = eval_cli.EvalDeps(retriever=FakeRetriever(), index=FakeIndex(), threshold=T)  # type: ignore[arg-type]
    assert await eval_cli._run(deps, _kb(tmp_path), do_sweep=True, csv=True) == 0
    out = capsys.readouterr().out.splitlines()
    header = next(ln for ln in out if ln.startswith("threshold,"))
    assert header.endswith(",p_at_1,recall_at_threshold")
