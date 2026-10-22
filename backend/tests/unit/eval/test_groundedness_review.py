"""G11 — mẫu người soát (seed, phân tầng, mù) + nhãn người + độ đồng thuận."""

import json
from pathlib import Path
from typing import Any

import pytest
from app.eval.groundedness.review import (
    LOW_KAPPA,
    agreement,
    draw_sample,
    is_low_kappa,
    key_rows,
    load_key,
    load_labels,
    review_rows,
)
from tests.unit.eval._g11 import claim, judged, row, write_jsonl


def _pool(n_weak: int, n_solid: int) -> list:  # type: ignore[type-arg]
    weak = [judged(f"W{i:02d}-v1", (claim(1, "supported", "a"), claim(2, "unsupported")), ("a",)) for i in range(n_weak)]
    solid = [judged(f"S{i:02d}-v1", (claim(1, "supported", "a"), claim(2, "supported", "a")), ("a",)) for i in range(n_solid)]
    return weak + solid


def _ids(sample: list) -> list[str]:  # type: ignore[type-arg]
    return [a.scenario_id for a in sample]


def test_same_seed_same_sample_and_output_sorted() -> None:
    pool = _pool(20, 20)
    a, meta = draw_sample(pool, n=10, seed=5)
    b, _ = draw_sample(list(reversed(pool)), n=10, seed=5)  # thứ tự đầu vào không ảnh hưởng
    assert _ids(a) == _ids(b) == sorted(_ids(a)) and len(set(_ids(a))) == 10
    assert meta["scenario_ids"] == _ids(a) and meta["n_claims"] == 20 and meta["mode"] == "stratified" and meta["seed"] == 5


def test_seed_changes_the_sample() -> None:
    pool = _pool(20, 20)
    assert len({tuple(_ids(draw_sample(pool, n=10, seed=s)[0])) for s in range(1, 8)}) > 1


def test_default_seed_is_p8_seed() -> None:
    from app.eval.stats import SEED

    assert draw_sample(_pool(5, 5), n=4)[1]["seed"] == SEED == 20260925


def test_stratified_is_half_weak_half_solid() -> None:
    sample, meta = draw_sample(_pool(20, 20), n=10, seed=1)
    assert sum(a.scenario_id.startswith("W") for a in sample) == 5 and sum(a.scenario_id.startswith("S") for a in sample) == 5
    assert (meta["n_pool_weak"], meta["n_pool_solid"]) == (20, 20)


def test_partial_counts_as_weak_stratum() -> None:
    part = [judged(f"P{i}-v1", (claim(1, "partial", "a"),), ("a",)) for i in range(4)]
    solid = [judged(f"S{i}-v1", (claim(1, "supported", "a"),), ("a",)) for i in range(4)]
    sample, meta = draw_sample(part + solid, n=4, seed=3)
    assert meta["n_pool_weak"] == 4 and sum(a.scenario_id.startswith("P") for a in sample) == 2


@pytest.mark.parametrize(("n_weak", "n_solid", "weak_taken", "solid_taken"), [(1, 10, 1, 5), (10, 1, 5, 1), (0, 10, 0, 6), (10, 0, 6, 0)])
def test_stratified_shortfall_is_filled_from_the_other_stratum(n_weak: int, n_solid: int, weak_taken: int, solid_taken: int) -> None:
    sample, _ = draw_sample(_pool(n_weak, n_solid), n=6, seed=2)
    assert len(sample) == 6
    assert sum(a.scenario_id.startswith("W") for a in sample) == weak_taken
    assert sum(a.scenario_id.startswith("S") for a in sample) == solid_taken


def test_random_mode_and_n_larger_than_pool() -> None:
    pool = _pool(3, 3)
    sample, meta = draw_sample(pool, n=4, seed=1, stratify=False)
    assert len(sample) == 4 and meta["mode"] == "random" and "n_pool_weak" not in meta
    everything, meta_all = draw_sample(pool, n=30, seed=1)
    assert _ids(everything) == sorted(a.scenario_id for a in pool) and meta_all["n_answers"] == 6


def test_only_judged_answers_with_claims_are_eligible() -> None:
    pool = _pool(2, 2) + [
        judged("X-v1", (), (), status="cannot_answer"), judged("E-v1", (), (), status="error", error="LLMSchemaError"),
        judged("Z-v1", (), (), status="no_claims"),
    ]  # fmt: skip
    sample, meta = draw_sample(pool, n=30, seed=1)
    assert meta["n_pool"] == 4 and not {"X-v1", "E-v1", "Z-v1"} & set(_ids(sample))


def test_n_must_be_positive() -> None:
    with pytest.raises(ValueError):
        draw_sample(_pool(2, 2), n=0)


# ---- bản soát mù ---------------------------------------------------------------------------------------------------------


def test_review_sample_is_blind_and_complete() -> None:
    a = judged("TC04-v1", (claim(1, "supported", "A", text="Ý một"), claim(2, "unsupported", text="Ý hai")), ("A", "B"))
    rows = {"TC04-v1": row("TC04-v1", "x", ("A", "B"), chunks=("A", "B", "C"))}
    out = review_rows([a], rows)
    assert [(r["scenario_id"], r["claim_id"], r["claim"]) for r in out] == [("TC04-v1", 1, "Ý một"), ("TC04-v1", 2, "Ý hai")]
    assert all([c["chunk_id"] for c in r["cited_chunks"]] == ["A", "B"] for r in out)  # chỉ đoạn được dẫn, kèm chữ
    assert out[0]["cited_chunks"][0]["text"] == "văn bản của A"
    assert all(r["human_supported"] is None and r["note"] is None for r in out)
    blob = json.dumps(out, ensure_ascii=False)
    for leak in ("supported\"", "unsupported", "verdict", "llm_", "partial"):
        assert leak not in blob.replace("human_supported", ""), leak
    assert set(out[0]) == {"scenario_id", "claim_id", "claim", "cited_chunks", "human_supported", "note"}


def test_review_rows_unknown_scenario_is_error() -> None:
    with pytest.raises(ValueError, match="scenario_id"):
        review_rows([judged("Q-v1", (claim(1, "supported", "A"),), ("A",))], {})


def test_key_rows_carry_llm_verdicts() -> None:
    a = judged("K-v1", (claim(1, "supported", "A"), claim(2, "partial", "A")), ("A",))
    assert key_rows([a]) == [
        {"scenario_id": "K-v1", "claim_id": 1, "llm_verdict": "supported", "llm_chunk_ids": ["A"]},
        {"scenario_id": "K-v1", "claim_id": 2, "llm_verdict": "partial", "llm_chunk_ids": ["A"]},
    ]  # fmt: skip


# ---- nhãn người ----------------------------------------------------------------------------------------------------------


def _label_file(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    path = tmp_path / "labels.jsonl"
    write_jsonl(path, records)
    return path


def test_load_labels_accepts_filled_review_sample(tmp_path: Path) -> None:
    path = _label_file(tmp_path, [
        {"scenario_id": "A-v1", "claim_id": 1, "claim": "x", "cited_chunks": [], "human_supported": True, "note": None},
        {"scenario_id": "A-v1", "claim_id": 2, "human_supported": False, "note": "sai số"},
    ])  # fmt: skip
    assert load_labels(path) == {("A-v1", 1): True, ("A-v1", 2): False}


@pytest.mark.parametrize(
    "record",
    [
        {"scenario_id": "A-v1", "claim_id": 1, "human_supported": None},
        {"scenario_id": "A-v1", "claim_id": 1, "human_supported": "true"},
        {"scenario_id": "A-v1", "claim_id": 1, "human_supported": 1},
        {"scenario_id": "A-v1", "claim_id": 1},
        {"scenario_id": "A-v1", "claim_id": True, "human_supported": True},
        {"scenario_id": "A-v1", "claim_id": "1", "human_supported": True},
        {"claim_id": 1, "human_supported": True},
    ],
)
def test_load_labels_rejects_unlabelled_or_malformed(tmp_path: Path, record: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        load_labels(_label_file(tmp_path, [record]))


def test_load_labels_rejects_duplicates_and_bad_json(tmp_path: Path) -> None:
    rec = {"scenario_id": "A-v1", "claim_id": 1, "human_supported": True}
    with pytest.raises(ValueError, match="trùng"):
        load_labels(_label_file(tmp_path, [rec, rec]))
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{không phải json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_labels(bad)


def test_load_key_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "k.jsonl"
    write_jsonl(path, key_rows([judged("K-v1", (claim(1, "supported", "A"),), ("A",))]))
    assert load_key(path) == {("K-v1", 1): "supported"}


# ---- đồng thuận ----------------------------------------------------------------------------------------------------------


def _scenario() -> tuple[dict, dict]:  # type: ignore[type-arg]
    """a=4 (cả hai dương), b=2 (LLM dương/người âm), c=1 (LLM âm/người dương), d=3 (cả hai âm) trên 5 ca."""
    layout = {
        "S1": [("supported", True)],
        "S2": [("supported", True), ("supported", False)],
        "S3": [("supported", True), ("supported", False), ("unsupported", True)],
        "S4": [("partial", False), ("unsupported", False)],
        "S5": [("supported", True), ("unsupported", False)],
    }
    key, labels = {}, {}
    for sid, items in layout.items():
        for i, (verdict, human) in enumerate(items, 1):
            key[(sid, i)], labels[(sid, i)] = verdict, human
    return key, labels


def test_agreement_hand_computed_kappa_and_confusion() -> None:
    key, labels = _scenario()
    r = agreement(key, labels, n_boot=200)
    # a=4 b=2 c=1 d=3, n=10 → po=0,7; pe=((6·5)+(4·5))/100=0,5 → κ=0,4
    assert (r["n_claims"], r["n_answers"]) == (10, 5)
    assert r["agreement"] == pytest.approx(0.7, abs=1e-12) and r["kappa"] == pytest.approx(0.4, abs=1e-12)
    assert r["confusion"] == {"llm_supported_human_supported": 4, "llm_supported_human_not": 2,
                              "llm_not_human_supported": 1, "llm_not_human_not": 3}  # fmt: skip
    assert r["llm_supported_rate_on_sample"] == pytest.approx(0.6) and r["human_supported_rate_on_sample"] == pytest.approx(0.5)


def test_agreement_reports_inflation_cases() -> None:
    key, labels = _scenario()
    r = agreement(key, labels, n_boot=50)
    infl = r["llm_supported_human_not"]
    assert (infl["n_claims"], infl["n_answers"]) == (2, 2) and infl["share_of_llm_supported"] == pytest.approx(2 / 6)
    assert [(i["scenario_id"], i["claim_id"]) for i in infl["items"]] == [("S2", 2), ("S3", 2)]
    assert r["llm_not_human_supported"]["n_claims"] == 1 and r["llm_not_human_supported"]["items"][0]["scenario_id"] == "S3"


def test_partial_is_negative_for_agreement() -> None:
    r = agreement({("A", 1): "partial", ("A", 2): "supported"}, {("A", 1): False, ("A", 2): True}, n_boot=10)
    assert r["confusion"]["llm_not_human_not"] == 1 and r["confusion"]["llm_supported_human_supported"] == 1
    r2 = agreement({("A", 1): "partial"}, {("A", 1): True}, n_boot=10)
    assert r2["confusion"]["llm_not_human_supported"] == 1


def test_kappa_ci_is_deterministic_and_resamples_answers() -> None:
    key, labels = _scenario()
    r1, r2 = agreement(key, labels, n_boot=300), agreement(key, labels, n_boot=300)
    assert r1 == r2 and r1["kappa_ci"]["unit"] == "answer" and r1["kappa_ci"]["n_used"] + r1["kappa_ci"]["n_undefined"] == 300
    assert r1["kappa_ci"]["lo"] <= r1["kappa"] <= r1["kappa_ci"]["hi"] or r1["kappa_ci"]["lo"] is None
    assert agreement(key, labels, n_boot=300, seed=1)["kappa_ci"] != r1["kappa_ci"]


def test_perfect_agreement_has_kappa_one_and_one_class_has_undefined_kappa() -> None:
    both = {("A", 1): "supported", ("A", 2): "unsupported"}
    perfect = agreement(both, {("A", 1): True, ("A", 2): False}, n_boot=10)
    assert perfect["kappa"] == 1.0 and perfect["agreement"] == 1.0
    one_class = agreement({("A", 1): "supported", ("B", 1): "supported"}, {("A", 1): True, ("B", 1): True}, n_boot=10)
    assert one_class["kappa"] is None and "pe = 1" in one_class["kappa_undefined_reason"] and one_class["agreement"] == 1.0


def test_agreement_rejects_missing_extra_and_empty() -> None:
    key, labels = _scenario()
    short = dict(labels)
    del short[("S5", 2)]
    with pytest.raises(ValueError, match="thiếu 1"):
        agreement(key, short, n_boot=10)
    extra = {**labels, ("ZZ", 1): True}
    with pytest.raises(ValueError, match="thừa 1"):
        agreement(key, extra, n_boot=10)
    with pytest.raises(ValueError, match="rỗng"):
        agreement({}, {}, n_boot=10)


# ---- low_kappa (P8 v1.5 6.3.1) -------------------------------------------------------------------------------------------


def _cells(a: int, b: int, c: int, d: int) -> tuple[dict, dict]:  # type: ignore[type-arg]
    """Mẫu với đúng a/b/c/d (mỗi ý một ca)."""
    key, labels, i = {}, {}, 0
    for count, verdict, human in ((a, "supported", True), (b, "supported", False), (c, "unsupported", True), (d, "unsupported", False)):
        for _ in range(count):
            i += 1
            key[(f"C{i:02d}", 1)], labels[(f"C{i:02d}", 1)] = verdict, human
    return key, labels


def test_low_kappa_flag_and_threshold_reported() -> None:
    assert LOW_KAPPA == 0.6
    low = agreement(*_cells(4, 2, 1, 3), n_boot=20)  # κ = 0,4
    assert low["kappa"] == pytest.approx(0.4) and low["low_kappa"] is True and low["kappa_threshold"] == 0.6
    assert low["agreement"] == pytest.approx(0.7)  # báo cả tỉ lệ khớp lẫn κ
    high = agreement(*_cells(5, 1, 0, 4), n_boot=20)  # po = 0,9; pe = 0,5 → κ = 0,8
    assert high["kappa"] == pytest.approx(0.8) and high["low_kappa"] is False


def test_low_kappa_boundary_is_exclusive_and_exact() -> None:
    """κ đúng 0,6 (a=4 b=1 c=1 d=4: po = 0,8; pe = 0,5) KHÔNG cờ; chỉ < 0,6 mới cờ. So số hữu tỉ, không lệch do sai số nổi."""
    assert agreement(*_cells(4, 1, 1, 4), n_boot=10)["low_kappa"] is False
    assert is_low_kappa(4, 1, 1, 4) is False and is_low_kappa(3, 1, 1, 4) is True and is_low_kappa(4, 2, 1, 3) is True


def test_low_kappa_flagged_when_kappa_undefined() -> None:
    """Một lớp duy nhất → κ không xác định → vẫn cờ: độ tin cậy không được chứng minh thì không báo là ổn."""
    r = agreement(*_cells(6, 0, 0, 0), n_boot=10)
    assert r["kappa"] is None and r["low_kappa"] is True and r["agreement"] == 1.0
