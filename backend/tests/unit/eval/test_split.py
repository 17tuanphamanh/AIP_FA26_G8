"""P8 v1.5 §4.3 / §9 — `app.eval.split.make_folds` + `scripts/eval/make_split.py`.

Kịch bản GIẢ trong `tmp_path` (`fake_stack.real_scenario`). SPLIT.md sinh ra phải qua đúng `check_split.py` (G9) và CSV phải qua đúng
`offline.load_folds` — hai đầu ra từ CÙNG một lần chia.
"""

import random
from pathlib import Path

import pytest
import yaml
from app.eval.dataset import Scenario, load_scenarios
from app.eval.offline import load_folds
from app.eval.split import (
    DEV_ID,
    SplitError,
    build_split,
    family_profiles,
    folds_csv,
    make_folds,
)
from tests.unit.eval.eval_scripts import load_script
from tests.unit.eval.fake_stack import SEED_USERS, real_scenario, write_seed

cs = load_script("check_split")
ms = load_script("make_split")

# 18 họ như bộ thẻ đo: nhãn và intent trộn, có họ L2 hiếm.
PLAN = [
    ("HITL", "access"), ("HITL", "access"), ("HITL", "account"), ("HITL", "account"), ("HITL", "vpn"), ("HITL", "software"),
    ("AUTO", "access"), ("AUTO", "account"), ("AUTO", "vpn"), ("AUTO", "vpn"), ("AUTO", "software"), ("AUTO", "account"),
    ("ESCALATE_L2", "access"), ("ESCALATE_L2", "account"), ("ESCALATE_L2", "vpn"), ("ESCALATE_L2", "access"),
    ("ESCALATE_L2", "software"), ("HITL", "access"),
]  # fmt: skip


def scen(sid: str, family: str, route: str | None, intent: str = "vpn") -> Scenario:
    return Scenario.model_validate(
        real_scenario(sid, family=family, expected_route=route, intents=(intent,))
    )


def eighteen(per_family: int = 4) -> list[Scenario]:
    out = []
    for f, (route, intent) in enumerate(PLAN, start=1):
        for q in range(1, per_family + 1):
            out.append(scen(f"HB{f:02d}-q{q}", f"HB{f:02d}", route, intent))
    return out


def write_dir(tmp_path: Path, scenarios: list[Scenario]) -> Path:
    d = tmp_path / "scenarios"
    d.mkdir()
    for s in scenarios:
        (d / f"{s.id}.yaml").write_text(
            yaml.safe_dump(s.model_dump(mode="json"), allow_unicode=True),
            encoding="utf-8",
        )
    return d


# ---- make_folds ------------------------------------------------------------------------------------------------------


def test_every_family_in_exactly_one_fold_and_all_folds_used() -> None:
    sc = eighteen()
    folds = make_folds(sc, k=5, seed=20260925)
    assert set(folds) == {s.family for s in sc}
    assert set(folds.values()) == {1, 2, 3, 4, 5}
    by_fold: dict[int, set[str]] = {}
    for s in sc:  # mọi kịch bản của một họ cùng một phần
        by_fold.setdefault(folds[s.family], set()).add(s.family)
    assert sum(len(v) for v in by_fold.values()) == 18


def test_family_counts_per_fold_differ_by_at_most_one() -> None:
    counts = list(
        __import__("collections").Counter(make_folds(eighteen(), k=5).values()).values()
    )
    assert max(counts) - min(counts) <= 1


def test_rare_label_spread_across_folds() -> None:
    folds = make_folds(eighteen(), k=5)
    l2 = [
        f"HB{i:02d}" for i, (r, _) in enumerate(PLAN, start=1) if r == "ESCALATE_L2"
    ]  # 5 họ L2
    assert len({folds[f] for f in l2}) == 5


def test_same_seed_same_result_regardless_of_input_order() -> None:
    sc = eighteen()
    shuffled = sc[:]
    random.Random(1).shuffle(shuffled)
    assert make_folds(sc, seed=7) == make_folds(shuffled, seed=7)


def test_different_seed_changes_assignment() -> None:
    sc = eighteen()
    assert make_folds(sc, seed=1) != make_folds(sc, seed=2)


def test_unlabelled_scenario_is_rejected_with_count_only() -> None:
    sc = eighteen() + [scen("HB19-q1", "HB19", None)]
    with pytest.raises(SplitError, match=r"^1 kịch bản chưa nhãn") as e:
        make_folds(sc)
    assert "HB19" not in str(e.value)


def test_dev_set_d1_d2_is_rejected() -> None:
    assert DEV_ID.match("HB03-v7") and not DEV_ID.match("HB03-q7")
    with pytest.raises(SplitError, match="D-59"):
        make_folds(eighteen() + [scen("HB03-v1", "HB03", "HITL")])


def test_fewer_families_than_k_is_rejected() -> None:
    with pytest.raises(SplitError, match="ít hơn k"):
        make_folds([scen(f"F{i}-q1", f"F{i}", "AUTO") for i in range(4)], k=5)


def test_representative_label_majority_then_stricter_on_tie() -> None:
    sc = [
        scen("A-q1", "A", "AUTO"),
        scen("A-q2", "A", "AUTO"),
        scen("A-q3", "A", "HITL"),  # đa số AUTO
        scen("B-q1", "B", "AUTO"),
        scen("B-q2", "B", "HITL"),  # hoà → HITL
        scen("C-q1", "C", "HITL"),
        scen("C-q2", "C", "ESCALATE_L2"),  # hoà → ESCALATE_L2
    ]
    p = family_profiles(sc)
    assert (p["A"].label, p["B"].label, p["C"].label) == ("AUTO", "HITL", "ESCALATE_L2")


def test_family_intent_majority_then_alphabetical_on_tie() -> None:
    sc = [scen("A-q1", "A", "AUTO", "vpn"), scen("A-q2", "A", "AUTO", "vpn"), scen("A-q3", "A", "AUTO", "access"),
          scen("B-q1", "B", "AUTO", "vpn"), scen("B-q2", "B", "AUTO", "access")]  # fmt: skip
    p = family_profiles(sc)
    assert (p["A"].intent, p["B"].intent) == ("vpn", "access")


# ---- hai đầu ra từ cùng một lần chia ----------------------------------------------------------------------------------


def test_build_split_outputs_pass_check_split_and_load_folds(tmp_path: Path) -> None:
    sc = eighteen()
    d = write_dir(tmp_path, sc)
    seed_file = write_seed(tmp_path / "seed.json", SEED_USERS)
    res = build_split(d, seed_file, locked=True)
    assert res.folds == make_folds(load_scenarios(d, users=SEED_USERS).scenarios)
    split_path = tmp_path / "SPLIT.md"
    split_path.write_text(res.split_md, encoding="utf-8")
    parsed = cs.parse_split(res.split_md)
    assert (
        parsed.families == dict(res.folds)
        and parsed.k == 5
        and parsed.locked is True
        and parsed.seed == 20260925
    )
    assert parsed.dataset_sha256 == load_scenarios(d, users=SEED_USERS).sha256
    assert cs.check(split_path, d) == 0
    csv_path = tmp_path / "folds.csv"
    csv_path.write_text(res.csv, encoding="utf-8")
    loaded, _ = load_folds(csv_path)
    assert loaded == dict(res.folds)
    assert sum(res.fold_sizes.values()) == res.n_scenarios == 72


def test_outputs_carry_no_labels(tmp_path: Path) -> None:
    d = write_dir(tmp_path, eighteen())
    res = build_split(d, write_seed(tmp_path / "seed.json", SEED_USERS))
    for text in (res.split_md, folds_csv(res.folds)):
        for word in ("AUTO", "HITL", "ESCALATE_L2"):
            assert word not in text


def test_cli_writes_both_files_refuses_overwrite_and_logs_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = write_dir(tmp_path, eighteen())
    seed_file = write_seed(tmp_path / "seed.json", SEED_USERS)
    split_path, csv_path = tmp_path / "SPLIT.md", tmp_path / "folds.csv"
    argv = [
        "--scenarios",
        str(d),
        "--seed-file",
        str(seed_file),
        "--split",
        str(split_path),
        "--csv",
        str(csv_path),
        "--locked",
    ]
    assert ms.main(argv) == 0
    out = capsys.readouterr()
    assert "ho=18" in out.out and "HB0" not in out.out + out.err
    assert cs.parse_split(split_path.read_text(encoding="utf-8")).locked is True
    assert (
        load_folds(csv_path)[0]
        == cs.parse_split(split_path.read_text(encoding="utf-8")).families
    )
    assert ms.main(argv) == 2  # không ghi đè


def test_cli_unlabelled_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = write_dir(tmp_path, eighteen() + [scen("HB19-q1", "HB19", None)])
    seed_file = write_seed(tmp_path / "seed.json", SEED_USERS)
    argv = [
        "--scenarios",
        str(d),
        "--seed-file",
        str(seed_file),
        "--split",
        str(tmp_path / "S.md"),
        "--csv",
        str(tmp_path / "f.csv"),
    ]
    assert ms.main(argv) == 2
    assert "chưa nhãn" in capsys.readouterr().err
    assert not (tmp_path / "S.md").exists() and not (tmp_path / "f.csv").exists()
