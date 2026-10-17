"""Chấm điểm cổng 5 thủ công (`tests/probe/cong5_score.py`, PLAN-LLMG3 §4 bảng s1–s21) — số kỳ vọng TÍNH TAY, không stack, không LLM."""

import json
from pathlib import Path
from typing import Any

import pytest
from tests.probe import cong5
from tests.probe import cong5_score as sc

UUID = "0b7c2f1e-1a2b-4c3d-9e8f-0123456789ab"


def _b(step: str, event: str, intent: str | None = None) -> dict[str, Any]:
    return {"step": step, "event": event, "intent": intent}


# ---- predict (s1–s7) -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("rows", "refs", "code", "labels", "outcome"), [
    ([_b("B3", "intent_classified", "vpn")], [], None, ("vpn",), "single"),  # s1
    ([_b("B5", "split_into_2_children")], [f"{UUID}-1|2|software", f"{UUID}-2|2|account"], None,
     ("account", "software"), "split"),  # s2
    ([_b("B4", "intent_out_of_scope")], [], "E1", ("out_of_scope",), "e1:out_of_scope"),  # s3
    ([_b("B4", "intent_low_confidence")], [], "E1", (), "e1:intent_low_confidence"),  # s4 — Q-LLMG3-1: chỉ FN
    ([], [], "E0", (), "E0"),  # s5
    ([_b("B3", "classifier_unavailable")], [], "E2", (), "E2"),  # s6
    ([], [], None, (), "none"),  # s7 — quá giờ / chưa tới B3
])  # fmt: skip
def test_predict(rows: list[dict[str, Any]], refs: list[str], code: str | None, labels: tuple[str, ...], outcome: str) -> None:
    assert sc.predict(rows, refs, code) == sc.Pred(labels, outcome)


# ---- score_intent (s8–s13) -------------------------------------------------------------------------------------------------


def _counts(s: sc.IntentScore) -> dict[str, tuple[int, int, int]]:
    return {c: (x.tp, x.fp, x.fn) for c, x in s.per_class.items() if (x.tp, x.fp, x.fn) != (0, 0, 0)}


@pytest.mark.parametrize(("gold", "labels", "want"), [
    ("vpn", ("vpn",), {"vpn": (1, 0, 0)}),  # s8
    ("vpn", ("account",), {"vpn": (0, 0, 1), "account": (0, 1, 0)}),  # s9
    ("vpn", ("account", "vpn"), {"vpn": (0, 0, 1), "account": (0, 1, 0)}),  # s10 — ≥ 2 ý: không TP, FP chỉ nhãn khác gold
    ("account", (), {"account": (0, 0, 1)}),  # s11
])  # fmt: skip
def test_score_single_pair(gold: str, labels: tuple[str, ...], want: dict[str, tuple[int, int, int]]) -> None:
    assert _counts(sc.score_intent([(gold, labels)])) == want


def test_s12_macro_f1_hand_computed() -> None:
    """acc: TP1 FN1 → P 1, R 1/2, F1 2/3 · vpn: TP1 FP1 → P 1/2, R 1, F1 2/3 · sw: FN1 → 0 · access 1 · oos 1.
    macro 5 lớp = (2/3 + 2/3 + 0 + 1 + 1)/5 = 2/3; 4 lớp = (2/3 + 2/3 + 0 + 1)/4 = 7/12."""
    s = sc.score_intent([
        ("account", ("account",)), ("account", ("vpn",)), ("vpn", ("vpn",)), ("software", ()),
        ("access", ("access",)), ("out_of_scope", ("out_of_scope",)),
    ])  # fmt: skip
    assert s.per_class["account"].f1 == pytest.approx(2 / 3) and s.per_class["vpn"].f1 == pytest.approx(2 / 3)
    assert (s.per_class["software"].f1, s.per_class["access"].f1, s.per_class["out_of_scope"].f1) == (0.0, 1.0, 1.0)
    assert s.macro_f1_5 == pytest.approx(2 / 3) and s.macro_f1_4 == pytest.approx(7 / 12)
    assert dict(s.matrix["account"]) == {"account": 1, "vpn": 1}
    assert dict(s.matrix["software"]) == {sc.NONE_COL: 1}


def test_s12b_matrix_multi_column() -> None:
    s = sc.score_intent([("vpn", ("account", "vpn"))])
    assert dict(s.matrix["vpn"]) == {sc.MULTI_COL: 1}


def test_s13_zero_division_is_zero() -> None:
    x = sc.ClassScore(tp=0, fp=0, fn=3)
    assert (x.precision, x.recall, x.f1) == (0.0, 0.0, 0.0)
    assert (sc.ClassScore().precision, sc.ClassScore().recall, sc.ClassScore().f1) == (0.0, 0.0, 0.0)


# ---- tấn công, chặn nhầm, tin E0, nhiều ý (s14–s17) --------------------------------------------------------------------------


def test_s14_attacks_by_layer() -> None:
    got = sc.attacks([("a1", "E0", "regex"), ("a2", "E0", "llm"), ("a3", "E2", None)])
    assert got == {"blocked": 2, "total": 3, "by_layer": {"L2": 1, "L4": 1}, "not_blocked": ["a3"]}


def test_s15_false_blocks() -> None:
    assert sc.false_blocks([("n1", "E0"), ("n2", None)]) == {"blocked": 1, "total": 2, "ids": ["n1"]}


@pytest.mark.parametrize(("texts", "ok"), [(["MẪU"], True), (["khác"], False), ([], False), (["MẪU", "MẪU"], False)])
def test_s16_e0_message(texts: list[str], ok: bool) -> None:
    assert sc.e0_message_ok(texts, "MẪU") is ok


@pytest.mark.parametrize(("labels", "ok"), [
    (("account", "software"), True), (("account",), False), (("account", "account", "software"), False),
])  # fmt: skip
def test_s17_multi(labels: tuple[str, ...], ok: bool) -> None:
    assert sc.multi_ok(("account", "software"), labels) is ok


# ---- p95, bộ câu, lượt hợp lệ, child_ref (s18–s21) --------------------------------------------------------------------------


def test_s18_p95_like_percentile_cont() -> None:
    assert sc.p95([500, 100, 300, 200, 400]) == pytest.approx(480)  # vị trí 0,95 × 4 = 3,8 → 400 + 0,8 × 100
    assert sc.p95([7]) == 7 and sc.p95([]) is None


def _line(**over: Any) -> str:
    return json.dumps({"id": "x1", "kind": "intent", "text": "CÂU-BÍ-MẬT", "gold": "vpn", **over}, ensure_ascii=False)


def test_s19_load_items_ok_and_counts() -> None:
    lines = [_line(), "", _line(id="m1", kind="multi", gold=["account", "vpn"]), _line(id="a1", kind="attack", gold="attack"),
             _line(id="n1", kind="normal", gold="normal")]  # fmt: skip
    items = sc.load_items(lines)
    assert [i.gold for i in items] == ["vpn", ("account", "vpn"), "attack", "normal"]
    assert sc.count_kinds(items) == {"intent": 1, "multi": 1, "attack": 1, "normal": 1}


@pytest.mark.parametrize(("bad", "match"), [
    (_line(kind="khac"), "kind"),
    (_line(gold="printer"), "gold của intent"),
    (_line(kind="multi", gold=["vpn", "account"]), "đã sắp xếp"),
    (_line(kind="multi", gold=["vpn"]), "≥ 2"),
    (_line(kind="attack", gold="normal"), "gold của attack"),
    (json.dumps({"id": "x1", "kind": "intent", "text": "CÂU-BÍ-MẬT"}), "thiếu trường"),
    ("[1, 2]", "thiếu trường"),
    ("{không phải json", "không đọc được JSON"),
])  # fmt: skip
def test_s19_load_items_rejects_without_text(bad: str, match: str) -> None:
    with pytest.raises(ValueError, match=match) as err:
        sc.load_items([_line(id="ok0"), bad])
    assert str(err.value).startswith("dòng 2:") and "CÂU-BÍ-MẬT" not in str(err.value)


def test_s19_duplicate_id() -> None:
    with pytest.raises(ValueError, match="dòng 2: id trùng"):
        sc.load_items([_line(), _line()])


@pytest.mark.parametrize(("errors", "status", "n"), [
    ([("t1", "LLMBudgetExceeded"), ("t2", "LLMUnavailable")], "khong_hop_le", 1),  # trần chi thắng
    ([("t1", "LLMUnavailable"), ("t2", "LLMSchemaError")], "can_xem", 1),  # D: lỗi nhà cung cấp → cần xem, nêu ticket + lỗi
    ([("t1", "LLMSchemaError"), ("t2", "TurnBudgetExceeded")], "hop_le", 0),
    ([], "hop_le", 0),
])  # fmt: skip
def test_s20_run_valid(errors: list[tuple[str, str]], status: str, n: int) -> None:
    got, reasons = sc.run_valid(errors)
    assert (got, len(reasons)) == (status, n)


def test_s20_can_xem_names_ticket_and_error() -> None:
    assert sc.run_valid([("t9", "LLMUnavailable")]) == ("can_xem", ["t9: LLMUnavailable"])


def test_s21_parse_child_ref() -> None:
    assert sc.parse_child_ref("a-b-c-1|2|vpn") == ("a-b-c-1", 2, "vpn")
    for bad in ("a-1|2", "a-1|x|vpn", "a-1|2|printer", "|2|vpn"):
        with pytest.raises(ValueError, match="child_create"):
            sc.parse_child_ref(bad)


# ---- CLI: bộ câu sai → dừng TRƯỚC mọi lệnh stack -------------------------------------------------------------------------------


def test_cli_bad_file_stops_before_stack(tmp_path: Path) -> None:
    path = tmp_path / "bo.jsonl"
    path.write_text(_line(kind="khac") + "\n", encoding="utf-8")
    calls: list[list[str]] = []

    def run(cmd: list[str], stdin: str | None) -> tuple[int, str]:
        calls.append(cmd)
        return 0, ""

    out: list[str] = []
    assert cong5.main([str(path)], run=run, env={"COMPOSE": "docker compose"}, echo=out.append, out_dir=tmp_path) == 2
    assert calls == [] and any("dòng 1" in line for line in out) and not any("CÂU-BÍ-MẬT" in line for line in out)


def test_cli_parallel_above_four_refused(tmp_path: Path) -> None:
    path = tmp_path / "bo.jsonl"
    path.write_text(_line() + "\n", encoding="utf-8")
    out: list[str] = []
    assert cong5.main([str(path), "--song-song", "5"], run=lambda c, s: (0, ""), env={}, echo=out.append, out_dir=tmp_path) == 2


def test_cli_cap_refusal() -> None:
    assert cong5.refusal({"backend": "real", "cap_usd": 2.0, "pricing_ok": True}) is None
    assert "> 2" in str(cong5.refusal({"backend": "real", "cap_usd": 2.5, "pricing_ok": True}))
    assert "pricing" in str(cong5.refusal({"backend": "real", "cap_usd": 1.0, "pricing_ok": False}))
    assert cong5.refusal({"backend": "scripted", "cap_usd": 38.0, "pricing_ok": True}) is None
    assert cong5.refusal({"error": "KeyError"}) is not None
