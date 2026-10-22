"""G11 — CLI từ đầu đến cuối với người chấm giả (gateway thật + ScriptedLLM): judge → sample → agree, tái lập, mã thoát."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.eval.groundedness import report
from app.eval.groundedness.cli import EXIT_INPUT, EXIT_JUDGE_ERRORS, main
from app.eval.stats import SEED
from tests.unit.eval._g11 import answers_file, write_jsonl

FACTORY = "tests.unit.eval._g11:factory"
PROMPT_FILE = Path(__file__).resolve().parents[4] / "config" / "prompts" / "eval_groundedness.yaml"


def _judge(tmp: Path, answers: Path, name: str = "run", *extra: str) -> tuple[int, Path]:
    out = tmp / name
    code = main(["judge", "--answers", str(answers), "--out", str(out), "--llm-factory", FACTORY, *extra])
    return code, out


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def answers(tmp_path: Path) -> Path:
    path = tmp_path / "answers.jsonl"
    answers_file(path)
    return path


def test_judge_writes_results_summary_manifest(tmp_path: Path, answers: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _judge(tmp_path, answers, "run", "--commit", "abc1234")
    assert code == 0
    summary = json.loads((out / report.SUMMARY).read_text(encoding="utf-8"))
    # 6 ca yếu: 3 ý (1 supported A, 1 unsupported, 1 supported B); 6 ca vững: 1 ý supported → 12 ca, 24 ý, 6·2+6 = 18 supported
    assert (summary["n_judged"], summary["n_claims"], summary["n_supported"], summary["n_unsupported"]) == (12, 24, 18, 6)
    assert summary["n_families"] == 5  # W0, W1, S0, S1, S2
    assert summary["supported_rate"] == pytest.approx(18 / 24) and summary["citation_precision"] == 1.0  # 18 cặp dẫn, đều có ý supported
    assert (out / report.ERRORS).read_text(encoding="utf-8") == ""
    manifest = json.loads((out / report.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["answers_sha256"] == hashlib.sha256(answers.read_bytes()).hexdigest() and manifest["commit"] == "abc1234"
    assert manifest["run_id"] == f"g11-{manifest['answers_sha256'][:8]}-{SEED}" and manifest["n_rows"] == 12
    assert manifest["prompt"]["id"] == "eval_groundedness" and manifest["prompt"]["versions"] == ["1"]
    assert manifest["prompt"]["sha256"] == [hashlib.sha256(PROMPT_FILE.read_bytes()).hexdigest()]
    assert manifest["judge"]["models"] == ["scripted"] and manifest["llm_calls"]["n"] == 12
    assert manifest["stats"] == {"seed": SEED, "bootstrap_n": 2000, "level": 0.95} and len(manifest["limitations"]) == 4
    assert any("cùng model với người viết" in x and "cấu hình A" in x for x in manifest["limitations"])  # người chấm = model viết
    assert any("[Đề xuất 22/10]" in x and "[Chốt 17.4]" in x for x in manifest["limitations"])
    assert "n_judged" in capsys.readouterr().out


def test_two_runs_give_identical_results_and_summary(tmp_path: Path, answers: Path) -> None:
    _, a = _judge(tmp_path, answers, "a")
    _, b = _judge(tmp_path, answers, "b")
    for name in (report.RESULTS, report.SUMMARY, report.ERRORS):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_score_recomputes_the_same_summary(tmp_path: Path, answers: Path) -> None:
    _, out = _judge(tmp_path, answers)
    before = (out / report.SUMMARY).read_bytes()
    (out / report.SUMMARY).unlink()
    assert main(["score", "--run", str(out)]) == 0
    assert (out / report.SUMMARY).read_bytes() == before


def test_sample_is_blind_stratified_seeded_and_checks_answers_file(tmp_path: Path, answers: Path) -> None:
    _, out = _judge(tmp_path, answers)
    assert main(["sample", "--run", str(out), "--answers", str(answers), "--n", "6"]) == 0
    sample, key = _jsonl(out / report.REVIEW_SAMPLE), _jsonl(out / report.REVIEW_KEY)
    meta = json.loads((out / report.REVIEW_META).read_text(encoding="utf-8"))
    assert meta["mode"] == "stratified" and meta["n_answers"] == 6 and meta["seed"] == SEED
    assert len({r["scenario_id"] for r in sample}) == 6 and sum(r["scenario_id"].startswith("W") for r in sample) == 3 * 3  # 3 ca yếu × 3 ý
    assert all(set(r) == {"scenario_id", "claim_id", "claim", "cited_chunks", "human_supported", "note"} for r in sample)
    assert "llm_verdict" not in json.dumps(sample) and {"llm_verdict", "llm_chunk_ids"} <= set(key[0])
    first = (out / report.REVIEW_SAMPLE).read_bytes()
    assert main(["sample", "--run", str(out), "--answers", str(answers), "--n", "6"]) == 0
    assert (out / report.REVIEW_SAMPLE).read_bytes() == first  # cùng seed → cùng mẫu
    other = tmp_path / "other.jsonl"
    answers_file(other, n_weak=2, n_solid=2)
    assert main(["sample", "--run", str(out), "--answers", str(other)]) == EXIT_INPUT  # sai file → sha256 lệch manifest


def test_sample_random_flag(tmp_path: Path, answers: Path) -> None:
    _, out = _judge(tmp_path, answers)
    assert main(["sample", "--run", str(out), "--answers", str(answers), "--n", "4", "--random", "--seed", "3"]) == 0
    assert json.loads((out / report.REVIEW_META).read_text(encoding="utf-8"))["mode"] == "random"


def test_agree_end_to_end_with_filled_labels(tmp_path: Path, answers: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out = _judge(tmp_path, answers)
    main(["sample", "--run", str(out), "--answers", str(answers), "--n", "6"])
    sample = _jsonl(out / report.REVIEW_SAMPLE)
    key = {(r["scenario_id"], r["claim_id"]): r["llm_verdict"] for r in _jsonl(out / report.REVIEW_KEY)}
    flipped = 0
    for r in sample:  # người đồng ý với LLM, trừ MỘT ý LLM bảo "supported" mà người bảo không
        llm_pos = key[(r["scenario_id"], r["claim_id"])] == "supported"
        r["human_supported"] = llm_pos
        if llm_pos and not flipped:
            r["human_supported"], flipped = False, 1
    labels = tmp_path / "labels.jsonl"
    write_jsonl(labels, sample)
    assert main(["agree", "--run", str(out), "--labels", str(labels)]) == 0
    result = json.loads((out / report.AGREEMENT).read_text(encoding="utf-8"))
    assert result["n_claims"] == len(sample) and result["llm_supported_human_not"]["n_claims"] == 1
    assert result["confusion"]["llm_not_human_supported"] == 0 and 0 < result["kappa"] < 1
    # κ tính lại độc lập từ nhãn: LLM dương = supported
    pairs = [(key[(r["scenario_id"], r["claim_id"])] == "supported", r["human_supported"]) for r in sample]
    n = len(pairs)
    a = sum(x and y for x, y in pairs)
    b = sum(x and not y for x, y in pairs)
    c = sum(y and not x for x, y in pairs)
    d = n - a - b - c
    po, pe = (a + d) / n, ((a + b) * (a + c) + (c + d) * (b + d)) / n**2
    assert result["kappa"] == pytest.approx((po - pe) / (1 - pe), abs=1e-12) and result["agreement"] == pytest.approx(po)
    assert result["low_kappa"] is (result["kappa"] < 0.6) and result["kappa_threshold"] == 0.6
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["low_kappa"] is result["low_kappa"]
    summary = json.loads((out / report.SUMMARY).read_text(encoding="utf-8"))  # summary báo cả tỉ lệ khớp, κ và cờ
    assert summary["human_agreement"] == {k: result[k] for k in report.AGREEMENT_KEYS}
    assert summary["human_agreement"]["agreement"] == result["agreement"] and "low_kappa" in summary["human_agreement"]
    assert main(["score", "--run", str(out)]) == 0  # tính lại summary vẫn giữ khối human_agreement
    assert json.loads((out / report.SUMMARY).read_text(encoding="utf-8"))["human_agreement"] == summary["human_agreement"]
    assert main(["sample", "--run", str(out), "--answers", str(answers), "--n", "4"]) == 0  # mẫu mới → đồng thuận cũ không còn khớp
    assert not (out / report.AGREEMENT).exists()
    assert "human_agreement" not in json.loads((out / report.SUMMARY).read_text(encoding="utf-8"))
    main(["agree", "--run", str(out), "--labels", str(labels)])  # nhãn cũ không khớp mẫu mới → lỗi, không ghi
    assert not (out / report.AGREEMENT).exists()


def test_rejudging_into_same_dir_clears_stale_review_files(tmp_path: Path, answers: Path) -> None:
    _, out = _judge(tmp_path, answers)
    main(["sample", "--run", str(out), "--answers", str(answers), "--n", "4"])
    assert (out / report.REVIEW_KEY).exists()
    _judge(tmp_path, answers)  # cùng thư mục
    for name in (report.REVIEW_SAMPLE, report.REVIEW_KEY, report.REVIEW_META, report.AGREEMENT):
        assert not (out / name).exists(), name


def test_agree_rejects_unlabelled_sample(tmp_path: Path, answers: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out = _judge(tmp_path, answers)
    main(["sample", "--run", str(out), "--answers", str(answers), "--n", "4"])
    assert main(["agree", "--run", str(out), "--labels", str(out / report.REVIEW_SAMPLE)]) == EXIT_INPUT  # human_supported còn null
    assert "human_supported" in capsys.readouterr().err
    assert not (out / report.AGREEMENT).exists()


def test_judge_errors_exit_3_and_are_listed(tmp_path: Path, answers: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    records = answers_file(bad, n_weak=1, n_solid=1)
    records[0]["steps"] = [f"Bước {i}" for i in range(30)]  # > 24 ý
    write_jsonl(bad, records)
    code, out = _judge(tmp_path, bad)
    assert code == EXIT_JUDGE_ERRORS
    errors = _jsonl(out / report.ERRORS)
    assert [e["scenario_id"] for e in errors] == [records[0]["scenario_id"]] and errors[0]["error"].startswith("too_many_claims")
    summary = json.loads((out / report.SUMMARY).read_text(encoding="utf-8"))
    assert summary["n_errors"] == 1 and summary["n_judged"] == 1  # ca lỗi ngoài mẫu số


def test_input_errors_exit_2_with_message(tmp_path: Path, answers: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nope.jsonl"
    assert main(["judge", "--answers", str(missing), "--out", str(tmp_path / "o"), "--llm-factory", FACTORY]) == EXIT_INPUT
    assert main(["judge", "--answers", str(answers), "--out", str(tmp_path / "o"), "--llm-factory", "khongcodauhaichuaham"]) == EXIT_INPUT
    assert "--llm-factory" in capsys.readouterr().err
    assert main(["score", "--run", str(tmp_path / "chua-co")]) == EXIT_INPUT
