"""b23, b24 — bộ kiểm tra truy hồi và cổng kiểm của ingest (3-Q15; PLAN-3b mục 7.1, Q-3b-4, Q-3b-13).

c29, c30 (3c, mục 1 Q-3c-7/15, mục 7) — `RetrieveGateAdapter` và `sweep()`: ở cuối file.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from app.rag.ingest.gate import (
    SWEEP_THRESHOLDS,
    EvalItem,
    GateMetrics,
    RetrievalSet,
    RetrieveGateAdapter,
    decide,
    gate_intent,
    load_retrieval_set,
    metrics,
    sweep,
)
from app.rag.models import IngestMlError, RetrievalResult, RetrievalSystemError
from tests.fakes.kb import FIXTURE_KB
from tests.fakes.rag import FakeRag

GOOD: dict[str, Any] = {
    "version": 1,
    "kb_scope": ["vpn"],
    "items": [
        {"id": "P1", "query": "vpn cổng nào", "intent": "vpn", "role": "employee", "expected_doc_ids": ["KB-VPN-001"]},
        {"id": "N1", "query": "máy in kẹt giấy", "intent": "out_of_scope", "role": "employee",
         "expected_doc_ids": [], "near_topic": False},
    ],
}  # fmt: skip


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    kb = tmp_path / "kb"
    (kb / "eval").mkdir(parents=True)
    (kb / "eval" / "retrieval_set.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return kb


def test_fixture_set_loads() -> None:
    rs, issues = load_retrieval_set(FIXTURE_KB)
    assert issues == [] and rs is not None
    pos = [i for i in rs.items if i.expected_doc_ids]
    neg = [i for i in rs.items if not i.expected_doc_ids]
    assert (len(pos), len(neg)) == (8, 6)
    assert sum(1 for i in neg if i.near_topic) >= 3
    assert [i.id for i in pos if i.expected_doc_ids == ["KB-VPN-004"]]  # b17 cần câu chỉ có 004
    assert [(i.role, i.expected_doc_ids) for i in pos if "KB-VPN-007" in i.expected_doc_ids] == [("l1", ["KB-VPN-007"])]


def test_missing_set_is_branch_a(tmp_path: Path) -> None:
    assert load_retrieval_set(tmp_path) == (None, [])


def _bad(**change: Any) -> dict[str, Any]:
    data = {**GOOD, "items": [dict(i) for i in GOOD["items"]]}
    for k, v in change.items():
        if k.startswith("item0_"):
            data["items"][0][k[6:]] = v
        else:
            data[k] = v
    return data


@pytest.mark.parametrize("data", [
    _bad(them=1),
    _bad(item0_mau="x"),
    _bad(item0_role="admin"),
    _bad(items=[GOOD["items"][0], {**GOOD["items"][1], "id": "P1"}]),
    _bad(items=[GOOD["items"][0]]),
    _bad(items=[GOOD["items"][1]]),
    _bad(kb_scope=["printer"]),
    _bad(item0_query=""),
], ids=["truong-la", "truong-la-trong-cau", "role-la", "id-trung", "thieu-cau-am", "thieu-cau-duong", "scope-la",
        "query-rong"])  # fmt: skip
def test_b23_bad_retrieval_set(tmp_path: Path, data: dict[str, Any]) -> None:
    rs, issues = load_retrieval_set(_write(tmp_path, data))
    assert rs is None and issues
    assert all(str(i).startswith("kb/eval/retrieval_set.yaml: ") for i in issues)


# ---- b24: chỉ số và quyết định -------------------------------------------------------------------


def _item(i: str, expected: list[str]) -> EvalItem:
    return EvalItem(id=i, query="q", intent="vpn", role="employee", expected_doc_ids=expected)


def test_b24_metrics_by_hand() -> None:
    results = [
        (_item("P1", ["A"]), ["A", "B"], 0.9),  # hạng 1
        (_item("P2", ["C", "D"]), ["B", "D", "C"], 0.8),  # hạng 2 (doc đúng đầu tiên)
        (_item("P3", ["E"]), ["A", "B", "C", "D", "F"], 0.7),  # trượt
        (_item("P4", ["F"]), ["A", "B", "C", "D", "X", "F"], 0.7),  # hạng 6 → ngoài top-5
        (_item("N1", []), ["A"], 0.6),  # = ngưỡng → trả lời bừa
        (_item("N2", []), ["A"], 0.59),
        (_item("N3", []), [], 0.0),
        (_item("N4", []), ["B"], 0.95),
    ]
    m = metrics(results, threshold=0.6)
    assert (m.positives, m.negatives) == (4, 4)
    assert m.recall_at5 == pytest.approx(2 / 4)
    assert m.false_grounding_rate == pytest.approx(2 / 4)
    assert m.mrr == pytest.approx((1 + 1 / 2) / 4)


def _m(r: float, fg: float) -> GateMetrics:
    return GateMetrics(r, fg, 0.0, 8, 6)


def test_b24_branch_a() -> None:
    ok = decide(has_set=False, allow_unevaluated=True, new=None, old=None)
    assert (ok.passed, ok.branch, ok.eval_status) == (True, "a", "unevaluated")
    no = decide(has_set=False, allow_unevaluated=False, new=None, old=None)
    assert (no.passed, no.branch) == (False, "a")


@pytest.mark.parametrize(("r", "fg", "passed"), [
    (0.80, 0.05, True), (0.80, 0.0, True), (0.799, 0.0, False), (1.0, 0.051, False), (6 / 8, 0.0, False),
    (7 / 8, 1 / 20, True),
])  # fmt: skip
def test_b24_branch_b_boundaries(r: float, fg: float, passed: bool) -> None:
    d = decide(has_set=True, allow_unevaluated=False, new=_m(r, fg), old=None)
    assert (d.branch, d.passed, d.eval_status) == ("b", passed, "evaluated")


@pytest.mark.parametrize(("old", "new", "passed"), [
    ((0.85, 0.0), (0.80, 0.0), True),  # tụt đúng 0,05
    ((0.85, 0.0), (0.799, 0.0), False),  # tụt 0,05 + 0,001
    ((1.0, 0.0), (0.875, 0.0), False),  # b17: tắt KB-VPN-004
    ((0.9, 0.10), (0.9, 0.15), True),  # FG tăng đúng 0,05
    ((0.9, 0.10), (0.9, 0.151), False),
    ((0.5, 0.3), (0.5, 0.3), True),  # bản cũ tệ: (c) chỉ so tương đối
])  # fmt: skip
def test_b24_branch_c_boundaries(old: tuple[float, float], new: tuple[float, float], passed: bool) -> None:
    d = decide(has_set=True, allow_unevaluated=True, new=_m(*new), old=_m(*old))
    assert (d.branch, d.passed) == ("c", passed)


# ---- c29: RetrieveGateAdapter (3c) ----------------------------------------------------------------


def _good_result(top_score: float = 0.9) -> RetrievalResult:
    return RetrievalResult(chunks=[], top_score=top_score, kb_version="a" * 64, intent_filter_fallback=False,
                           fallback_tried=False, retries=0, query_truncated=False)  # fmt: skip


@pytest.mark.asyncio
async def test_c29_retrieval_system_error_becomes_ingest_ml_error() -> None:
    rag = FakeRag(error=RetrievalSystemError("search", 2, detail="ConnectError"))
    adapter = RetrieveGateAdapter(rag)
    item = EvalItem(id="P1", query="vpn lỗi", intent="vpn", role="employee", expected_doc_ids=["D1"])
    with pytest.raises(IngestMlError):
        await adapter.top_docs(item, collection="kb_x")


@pytest.mark.asyncio
async def test_c29_intent_mapped_via_gate_intent_q_3c_7() -> None:
    assert gate_intent("out_of_scope") is None and gate_intent("vpn") == "vpn"
    rag = FakeRag(result=_good_result())
    adapter = RetrieveGateAdapter(rag)
    oos = EvalItem(id="N1", query="máy in kẹt giấy", intent="out_of_scope", role="employee", expected_doc_ids=[])
    await adapter.top_docs(oos, collection="kb_x")
    assert rag.retrieve_calls[-1][0].intent is None
    vpn = EvalItem(id="P1", query="vpn lỗi", intent="vpn", role="employee", expected_doc_ids=["D1"])
    await adapter.top_docs(vpn, collection="kb_x")
    assert rag.retrieve_calls[-1][0].intent == "vpn"


@pytest.mark.asyncio
async def test_c29_role_of_item_becomes_ctx_role() -> None:
    rag = FakeRag(result=_good_result())
    adapter = RetrieveGateAdapter(rag)
    item = EvalItem(id="P1", query="x", intent="vpn", role="l1", expected_doc_ids=["D1"])
    await adapter.top_docs(item, collection="kb_x")
    assert rag.retrieve_calls[-1][1].role == "l1"


@pytest.mark.asyncio
async def test_c29_returns_doc_ids_capped_at_5_and_top_score() -> None:
    from app.domain.ticket_state import ChunkRef

    chunks = [
        ChunkRef(chunk_id=f"c{i}", doc_id=f"D{i}", version=1, seq=0, title="T", heading_path="H",
                 score=0.9 - i * 0.01, excerpt="x")
        for i in range(7)
    ]
    rag = FakeRag(result=RetrievalResult(chunks=chunks, top_score=0.9, kb_version="a" * 64,
                                         intent_filter_fallback=False, fallback_tried=False, retries=0,
                                         query_truncated=False))  # fmt: skip
    adapter = RetrieveGateAdapter(rag)
    item = EvalItem(id="P1", query="x", intent="vpn", role="employee", expected_doc_ids=["D0"])
    docs, score = await adapter.top_docs(item, collection="kb_x")
    assert len(docs) == 5  # GATE_TOP_DOCS — an toàn dù Retriever cấu hình top_n khác
    assert docs[0] == "D0" and score == 0.9


# ---- c30: sweep() (3c, Q-3c-15) — hàm thuần, kết quả tay ------------------------------------------


def test_c30_sweep_thresholds_are_13_points_030_to_090() -> None:
    assert len(SWEEP_THRESHOLDS) == 13
    assert SWEEP_THRESHOLDS[0] == 0.30 and SWEEP_THRESHOLDS[-1] == 0.90
    assert SWEEP_THRESHOLDS == tuple(round(0.30 + 0.05 * i, 2) for i in range(13))


def test_c30_sweep_simulates_d23_per_threshold_matching_hand_math() -> None:
    rs = RetrievalSet(version=1, kb_scope=["vpn"], items=[
        EvalItem(id="P1", query="q1", intent="vpn", role="employee", expected_doc_ids=["D1"]),
        EvalItem(id="P2", query="q2", intent="vpn", role="employee", expected_doc_ids=["D2"]),
        EvalItem(id="N1", query="q3", intent="vpn", role="employee", expected_doc_ids=[]),
    ])  # fmt: skip
    pairs = {
        # P1: first thấp (0.40), alt cao (0.80) — D-23 "cứu" được câu này ở ngưỡng vừa.
        "P1": ((["D1"], 0.40), (["D1"], 0.80)),
        # P2: first đã cao (0.85) — không cần D-23 (alt cố tình sai để lộ nếu bị chọn nhầm).
        "P2": ((["D2"], 0.85), (["D9"], 0.20)),
        # N1: first thấp (0.35), alt CAO hơn (0.65) — D-23 làm câu âm tính "trả lời bừa" hơn ở ngưỡng vừa.
        "N1": ((["D9"], 0.35), (["D9"], 0.65)),
    }
    # T = 0,50: P1.first(0,40) < T → alt(0,80) ≥ T → dùng alt; P2.first(0,85) ≥ T → dùng first;
    #           N1.first(0,35) < T → alt(0,65) ≥ T → dùng alt (0,65 ≥ 0,50 → trả lời bừa).
    [p50] = sweep(rs, pairs, thresholds=[0.50])
    assert p50.metrics.false_grounding_rate == pytest.approx(1.0)  # tay tính: N1 dùng alt 0,65 ≥ 0,50
    assert p50.metrics.recall_at5 == pytest.approx(1.0)  # cả 2 câu dương đều có doc đúng trong danh sách trả về

    # T = 0,90: mọi first/alt đều < 0,90 → luôn dùng first (đúng luật D-23 thật: không đạt cũng trả first,
    # KHÔNG BAO GIỜ trả alt khi alt cũng dưới ngưỡng) — "E3 oan": P1 đáng lẽ có D1 đúng nhưng điểm chỉ 0,40.
    # `Recall@5` ở đây đo việc doc đúng có nằm trong top hay không, KHÔNG tự trừ khi điểm dưới ngưỡng (đó là
    # việc của `false_grounding_rate` phía âm tính và của quyết định E3 thật ở node — không phải của hàm này).
    [p90] = sweep(rs, pairs, thresholds=[0.90])
    assert p90.metrics.false_grounding_rate == pytest.approx(0.0)  # tay tính: N1 dùng first 0,35 < 0,90
    assert p90.metrics.recall_at5 == pytest.approx(1.0)


def test_c30_sweep_never_uses_alt_when_alt_also_below_threshold() -> None:
    """`else first` — kể cả khi first cũng dưới T, vẫn KHÔNG trả alt (đúng D-23 thật, không phải "trả cái lớn hơn")."""
    rs = RetrievalSet(version=1, kb_scope=["vpn"], items=[
        EvalItem(id="P1", query="q1", intent="vpn", role="employee", expected_doc_ids=["D1"]),
        EvalItem(id="N1", query="q2", intent="vpn", role="employee", expected_doc_ids=[]),
    ])  # fmt: skip
    pairs = {"P1": ((["D1"], 0.10), (["D_KHAC"], 0.05)), "N1": ((["D9"], 0.10), (["D9"], 0.05))}
    [p] = sweep(rs, pairs, thresholds=[0.50])
    assert p.metrics.recall_at5 == pytest.approx(1.0)  # dùng first (D1) — nếu lỡ dùng alt sẽ mất D1
