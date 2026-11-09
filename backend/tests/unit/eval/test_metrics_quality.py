"""S5 T29 — chất lượng truy hồi và intent P8 §6.3 (P8:375, `app.eval.metrics`). Chỉ dữ liệu tổng hợp; số tính tay khớp 1e-9.

Bộ R (truy hồi, top k = 5) — cột: gold_doc_ids, doc_ids (theo hạng) → R@5, RR@5, nDCG@5
    1  {a}    a b c d e     → 1    1    1
    2  {a}    b c a d e     → 1    1/3  1/log2(4) = 0,5
    3  {a}    b c d e f a   → 0    0    0                    (a ở hạng 6, ngoài top 5)
    4  {a,b}  a x b y z     → 1    1    (1 + 1/log2 4) / (1 + 1/log2 3) = 1,5 / 1,6309297535714575 = 0,9197207891481876
    5  {a,b}  x a a y z     → 1/2  1/2  (1/log2 3) / 1,6309297535714575 = 0,38685280723454163  (a trùng: chỉ tính lần đầu)
    6  {a}    ()            → 0    0    0                    (b) truy hồi rỗng = trượt
    7  {a}    None          → ngoài mẫu                      (c) không tới B8 → n_no_retrieval = 1
    8  ()     a             → ngoài mẫu                      [Đề xuất E1] không có gold → n_no_gold = 1
  n = 6; Recall@5 = 3,5/6 = 0,58333…; MRR@5 = (1 + 1/3 + 1 + 1/2)/6 = 17/36; nDCG@5 = 2,806573…/6 = 0,4677622660637882

Bộ I (intent) — (gold_intent, intent): (vpn,vpn) (vpn,vpn) (vpn,account) (vpn,None) (account,account) (account,vpn)
(software,software) (None,vpn)
    vpn      TP 2, #pred 3, #gold 4 → F1 = 4/7
    account  TP 1, #pred 2, #gold 2 → 1/2
    software TP 1, #pred 1, #gold 1 → 1
    access   vắng cả gold lẫn pred → None (loại)
  n = 7 (lá gold None bị loại, n_no_gold = 1), n_pred_none = 1; macro-F1 = (4/7 + 1/2 + 1)/3 = 29/42
"""

import itertools
import math
from typing import Any

import pytest
from app.db.models import INTENTS
from app.eval.metrics import (
    TOP_K,
    first_hit_rank,
    intent_quality,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
    retrieval,
)
from app.eval.predictions import PredictionRecord
from app.rag.ingest.config import GATE_TOP_DOCS
from app.rag.ingest.gate import EvalItem
from app.rag.ingest.gate import metrics as gate_metrics
from tests.unit.eval.contract_v11 import V11

TOL = 1e-9
_ids = itertools.count()
_IDCG2 = 1 + 1 / math.log2(3)


def leaf(
    gold_docs: tuple[str, ...] = (),
    docs: tuple[str, ...] | None = None,
    *,
    intent: str | None = "vpn",
    gold_intent: str | None = "vpn",
) -> PredictionRecord:
    i = next(_ids)
    data: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": "hybrid", "split": "test",
        "scenario_id": f"S-{i}", "family": f"F-{i}", "ticket_id": f"T-{i}", "parent_ticket_id": None,
        "expected_route": "AUTO", "route": None, "decided_by": None,
        "raw_prob": None, "calibrated_prob": None, "p_method": None,
        "final_state": "S_RESOLVED", "exit_code": None, "close_reason": None, "resolution_path": None,
        "has_approval": False, "clarification_turns": 0,
        "intent": intent, "gold_intent": gold_intent, "doc_ids": docs, "gold_doc_ids": gold_docs,
        **V11,
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def set_r() -> list[PredictionRecord]:
    return [
        leaf(("a",), ("a", "b", "c", "d", "e")),
        leaf(("a",), ("b", "c", "a", "d", "e")),
        leaf(("a",), ("b", "c", "d", "e", "f", "a")),
        leaf(("a", "b"), ("a", "x", "b", "y", "z")),
        leaf(("a", "b"), ("x", "a", "a", "y", "z")),
        leaf(("a",), ()),
        leaf(("a",), None),
        leaf((), ("a",)),
    ]


# ---- hàm hạng ------------------------------------------------------------------------------------------------------------


def test_top_k_matches_gate() -> None:
    assert TOP_K == GATE_TOP_DOCS == 5


def test_first_hit_rank() -> None:
    assert first_hit_rank(("a",), ("a", "b")) == 1
    assert first_hit_rank(("a",), ("b", "c", "a")) == 3
    assert first_hit_rank(("a",), ("b", "c", "d", "e", "f", "a")) is None  # hạng 6
    assert first_hit_rank(("a",), ("x", "x", "a")) == 3  # hạng theo VỊ TRÍ (như gate) [Đề xuất E2]
    assert first_hit_rank(("a",), ()) is None


def test_recall_multi_gold() -> None:
    # Recall chuẩn |gold ∩ top5| / |gold| (M3) — KHÔNG phải hit@5.
    assert recall_at_k(("a", "b"), ("a", "x", "b", "y", "z")) == 1.0
    assert recall_at_k(("a", "b"), ("x", "a", "a", "y", "z")) == 0.5
    assert recall_at_k(("a", "b", "c", "d"), ("a", "x", "y", "z", "w")) == 0.25
    assert recall_at_k(("a", "a"), ("a",)) == 1.0  # gold trùng khử bằng set
    assert recall_at_k(("a",), ("b", "c", "d", "e", "f", "a")) == 0.0  # ngoài top 5


def test_mrr_cut_at_5() -> None:
    assert reciprocal_rank_at_k(("a",), ("b", "c", "d", "e", "a")) == pytest.approx(0.2, abs=1e-12)
    assert reciprocal_rank_at_k(("a",), ("b", "c", "d", "e", "f", "a")) == 0.0  # hạng 6 → 0, không phải 1/6
    assert reciprocal_rank_at_k(("a", "b"), ("x", "b", "a")) == 0.5  # tài liệu đúng ĐẦU TIÊN


def test_ndcg_hand() -> None:
    assert ndcg_at_k(("a",), ("a", "b", "c", "d", "e")) == 1.0
    assert ndcg_at_k(("a",), ("b", "c", "a", "d", "e")) == pytest.approx(0.5, abs=TOL)  # 1/log2(4)
    assert ndcg_at_k(("a",), ("b", "a")) == pytest.approx(1 / math.log2(3), abs=TOL)
    assert ndcg_at_k(("a", "b"), ("a", "x", "b", "y", "z")) == pytest.approx(0.9197207891481876, abs=TOL)
    assert ndcg_at_k(("a",), ("b", "c", "d", "e", "f", "a")) == 0.0
    assert ndcg_at_k(("a",), ()) == 0.0


def test_ndcg_idcg_cut() -> None:
    # 6 tài liệu đúng, top 5 đều đúng → DCG = IDCG cắt ở min(6, 5) = 5 → 1,0. Không cắt → IDCG thêm 1/log2(7) → < 1.
    gold = ("a", "b", "c", "d", "e", "f")
    assert ndcg_at_k(gold, ("a", "b", "c", "d", "e")) == pytest.approx(1.0, abs=TOL)
    assert ndcg_at_k(gold, ("a", "b", "c", "d", "e", "f")) == pytest.approx(1.0, abs=TOL)


def test_ndcg_duplicate_first_only() -> None:
    # x a a y z, gold {a,b}: a hạng 2 → 1/log2 3; a lặp ở hạng 3 → 0 (chỉ tính lần đầu). Tính 2 lần → + 1/log2 4.
    assert ndcg_at_k(("a", "b"), ("x", "a", "a", "y", "z")) == pytest.approx(0.38685280723454163, abs=TOL)
    assert ndcg_at_k(("a",), ("a", "a")) == pytest.approx(1.0, abs=TOL)


def test_rank_functions_empty_gold_raise() -> None:
    for fn in (recall_at_k, reciprocal_rank_at_k, ndcg_at_k):
        with pytest.raises(ValueError, match="gold"):
            fn((), ("a",))


# ---- retrieval(records) --------------------------------------------------------------------------------------------------


def test_retrieval_hand() -> None:
    m = retrieval(set_r())
    assert (m.n, m.n_no_retrieval, m.n_no_gold) == (6, 1, 1)
    assert m.recall5.n == m.mrr5.n == m.ndcg5.n == 6
    assert m.recall5.value == pytest.approx(3.5 / 6, abs=TOL)
    assert m.mrr5.value == pytest.approx(17 / 36, abs=TOL)
    assert m.ndcg5.value == pytest.approx(0.4677622660637882, abs=TOL)
    assert m.ndcg5.value == pytest.approx((1 + 0.5 + 1.5 / _IDCG2 + (1 / math.log2(3)) / _IDCG2) / 6, abs=TOL)


def test_empty_retrieved_is_miss() -> None:
    # (b) có gold mà doc_ids == () → trượt (0), VẪN trong mẫu.
    m = retrieval([leaf(("a",), ("a",)), leaf(("a",), ())])
    assert (m.n, m.n_no_retrieval) == (2, 0)
    assert m.recall5.value == m.mrr5.value == m.ndcg5.value == 0.5


def test_no_retrieval_excluded() -> None:
    # (c) doc_ids None (không tới B8) → ngoài mẫu, đếm n_no_retrieval; không coi là 0.
    m = retrieval([leaf(("a",), ("a",)), leaf(("a",), None)])
    assert (m.n, m.n_no_retrieval) == (1, 1)
    assert m.recall5.value == m.mrr5.value == m.ndcg5.value == 1.0


def test_no_gold_raises() -> None:
    # (a) không lá nào có gold_doc_ids → ValueError.
    with pytest.raises(ValueError, match="gold_doc_ids"):
        retrieval([leaf((), ("a",)), leaf((), None)])
    with pytest.raises(ValueError, match="rỗng"):
        retrieval([])


def test_all_no_retrieval_none() -> None:
    # Có gold nhưng mọi lá đều chưa tới B8 → mẫu số 0 → None, không trả 0 giả.
    m = retrieval([leaf(("a",), None), leaf(("b",), None)])
    assert (m.n, m.n_no_retrieval) == (0, 2)
    assert m.recall5.value is None and m.mrr5.value is None and m.ndcg5.value is None


def test_rank_matches_gate() -> None:
    # Q3: dữ liệu 1-gold → Recall@5 và MRR của metrics.py = gate.metrics() (code Phase 3 giữ nguyên).
    cases: list[tuple[list[str], list[str]]] = [
        (["a"], ["a", "b", "c", "d", "e"]),  # hạng 1
        (["a"], ["b", "c", "a", "d", "e"]),  # hạng 3
        (["a"], ["b", "c", "d", "e", "f", "a"]),  # hạng 6 → trượt
        (["a"], ["x", "x", "a", "y", "z"]),  # trùng đứng trước — hạng theo vị trí
        (["b"], []),  # truy hồi rỗng
        (["c"], ["c"]),
        ([], ["a", "b"]),  # câu âm tính: gate loại khỏi recall/MRR; metrics.py: n_no_gold
    ]
    items = [EvalItem(id=f"Q{i}", query="q", intent="vpn", role="employee", expected_doc_ids=gold) for i, (gold, _) in
             enumerate(cases)]  # fmt: skip
    g = gate_metrics([(item, top, 0.0) for item, (_, top) in zip(items, cases, strict=True)], threshold=0.5)
    m = retrieval([leaf(tuple(gold), tuple(top)) for gold, top in cases])
    assert m.n == g.positives == 6
    assert m.recall5.value == pytest.approx(g.recall_at5, abs=1e-12)
    assert m.mrr5.value == pytest.approx(g.mrr, abs=1e-12)


# ---- intent macro-F1 -----------------------------------------------------------------------------------------------------


def set_i() -> list[PredictionRecord]:
    pairs = [("vpn", "vpn"), ("vpn", "vpn"), ("vpn", "account"), ("vpn", None), ("account", "account"),
             ("account", "vpn"), ("software", "software"), (None, "vpn")]  # fmt: skip
    return [leaf(intent=pred, gold_intent=gold) for gold, pred in pairs]


def test_intent_macro_f1_hand() -> None:
    m = intent_quality(set_i())
    assert (m.n, m.n_no_gold, m.n_pred_none) == (7, 1, 1)
    assert m.f1_by_class["vpn"] == pytest.approx(4 / 7, abs=TOL)
    assert m.f1_by_class["account"] == pytest.approx(0.5, abs=TOL)
    assert m.f1_by_class["software"] == pytest.approx(1.0, abs=TOL)
    assert m.f1_by_class["access"] is None
    assert m.macro_f1 == pytest.approx(29 / 42, abs=TOL)


def test_intent_pred_none_is_wrong() -> None:
    # Pred None = đoán sai: cộng #gold của vpn (FN), không cộng #pred lớp nào → vpn: TP 1, #pred 1, #gold 2 → 2·1/(1 + 2).
    # Loại lá pred None (đột biến) → TP 1, #pred 1, #gold 1 → 1.
    m = intent_quality([leaf(intent="vpn", gold_intent="vpn"), leaf(intent=None, gold_intent="vpn")])
    assert (m.n, m.n_pred_none) == (2, 1)
    assert m.f1_by_class["vpn"] == pytest.approx(2 / 3, abs=TOL)
    assert m.macro_f1 == pytest.approx(2 / 3, abs=TOL)


def test_intent_gold_none_excluded() -> None:
    # Lá gold_intent None bị loại cả hai phía: pred "account" của nó không tạo #pred cho account → account vắng (None).
    m = intent_quality([leaf(intent="vpn", gold_intent="vpn"), leaf(intent="account", gold_intent=None)])
    assert (m.n, m.n_no_gold) == (1, 1)
    assert m.f1_by_class["account"] is None
    assert m.macro_f1 == 1.0
    with pytest.raises(ValueError, match="gold_intent"):
        intent_quality([leaf(intent="vpn", gold_intent=None)])


def test_intent_absent_class_excluded() -> None:
    # access, software vắng cả gold lẫn pred → None, không vào trung bình; account chỉ có pred (FP) → F1 = 0, VẪN vào trung bình.
    m = intent_quality([leaf(intent="vpn", gold_intent="vpn"), leaf(intent="account", gold_intent="vpn")])
    assert set(m.f1_by_class) == set(INTENTS)
    assert m.f1_by_class["access"] is None and m.f1_by_class["software"] is None
    assert m.f1_by_class["account"] == 0.0
    assert m.f1_by_class["vpn"] == pytest.approx(2 / 3, abs=TOL)
    assert m.macro_f1 == pytest.approx((2 / 3 + 0) / 2, abs=TOL)
