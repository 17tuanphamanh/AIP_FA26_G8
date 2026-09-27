"""b23, b24 — bộ kiểm tra truy hồi và cổng kiểm của ingest (3-Q15; PLAN-3b mục 7.1, Q-3b-4, Q-3b-13)."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from app.rag.ingest.gate import (
    EvalItem,
    GateMetrics,
    decide,
    load_retrieval_set,
    metrics,
)
from tests.fakes.kb import FIXTURE_KB

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
