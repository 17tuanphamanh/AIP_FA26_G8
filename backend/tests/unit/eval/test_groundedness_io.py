"""G11 — hợp đồng đầu vào `answers.jsonl` / `results.jsonl` và chặn `EVAL_MODE`."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from app.eval.groundedness.models import (
    AnswerRow,
    JudgedAnswer,
    dump_jsonl,
    load_answers,
    load_results,
    sha256_file,
)
from tests.unit.eval._g11 import chunk, claim, judged, row, write_jsonl

REPO = Path(__file__).resolve().parents[4]


def _rec(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"scenario_id": "TC04-v1", "answer": "VPN dùng cổng 443.", "citations": ["A"], "chunks": [chunk("A")]}
    return base | over


def test_load_answers_minimal_record(tmp_path: Path) -> None:
    path = tmp_path / "answers.jsonl"
    write_jsonl(path, [_rec(), _rec(scenario_id="TC05-v2", steps=["Mở", "Chọn"], cannot_answer=False, family="TC05")])
    rows = load_answers(path)
    assert [r.scenario_id for r in rows] == ["TC04-v1", "TC05-v2"] and rows[1].steps == ("Mở", "Chọn")
    assert rows[0].cannot_answer is False and rows[0].steps is None and rows[0].chunks[0].chunk_id == "A"


def test_family_defaults_to_scenario_prefix_without_variant_suffix() -> None:
    assert row("HB01-v3").family_name == "HB01" and row("TC04-v12").family_name == "TC04"
    assert row("TC04").family_name == "TC04" and row("X-v1", family="Họ-khác").family_name == "Họ-khác"


def test_citations_are_deduplicated_in_order() -> None:
    assert row(citations=("B", "A", "B", "A")).citations == ("B", "A")


@pytest.mark.parametrize(
    ("record", "field"),
    [
        (_rec(extra=1), "extra"),
        (_rec(citations=["A", ""]), "citations"),
        (_rec(chunks=[chunk("A"), chunk("A")]), "(gốc)"),
        (_rec(chunks=[{"chunk_id": "", "text": "x"}]), "chunks"),
        (_rec(scenario_id=""), "scenario_id"),
        ({k: v for k, v in _rec().items() if k != "answer"}, "answer"),
        (_rec(cannot_answer="no"), "cannot_answer"),
    ],
)
def test_bad_record_names_line_and_field_but_not_values(tmp_path: Path, record: dict[str, Any], field: str) -> None:
    path = tmp_path / "answers.jsonl"
    write_jsonl(path, [_rec(scenario_id="OK-v1"), record])
    with pytest.raises(ValueError) as exc:
        load_answers(path)
    assert "dòng 2" in str(exc.value) and field in str(exc.value) and "VPN dùng cổng 443" not in str(exc.value)


def test_duplicate_scenario_id_empty_file_and_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "answers.jsonl"
    write_jsonl(path, [_rec(), _rec()])
    with pytest.raises(ValueError, match="trùng"):
        load_answers(path)
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="không có dòng"):
        load_answers(path)
    path.write_text("{hỏng\n", encoding="utf-8")
    with pytest.raises(ValueError, match="không phải JSON"):
        load_answers(path)


def test_results_roundtrip_is_lossless_and_deterministic(tmp_path: Path) -> None:
    answers = [
        judged("F1-v1", (claim(1, "supported", "a", text="Ý có dấu"), claim(2, "partial", "b")), ("a", "b", "x"), invalid=("x",)),
        judged("F2-v1", (), (), status="error", error="LLMSchemaError"),
        judged("F2-v2", (claim(1, "unsupported"),), (), flags=("no_citation",)),
    ]  # fmt: skip
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    dump_jsonl(a, answers)
    dump_jsonl(b, answers)
    assert a.read_bytes() == b.read_bytes() and "Ý có dấu" in a.read_text(encoding="utf-8")  # không escape unicode
    assert load_results(a) == answers
    assert sha256_file(a) == sha256_file(b)


def test_results_reject_error_status_mismatch_and_duplicates(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        JudgedAnswer.model_validate({"scenario_id": "A", "family": "A", "status": "error"})
    with pytest.raises(ValueError):
        JudgedAnswer.model_validate({"scenario_id": "A", "family": "A", "status": "judged", "error": "x"})
    path = tmp_path / "r.jsonl"
    ok = judged("A-v1", (claim(1, "supported", "a"),), ("a",))
    dump_jsonl(path, [ok, ok])
    with pytest.raises(ValueError, match="trùng"):
        load_results(path)
    path.write_text('{"scenario_id": "A", "bogus": 1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="sai hợp đồng"):
        load_results(path)


def test_models_are_frozen_and_strict() -> None:
    r = row()
    with pytest.raises(ValueError):
        r.scenario_id = "x"  # type: ignore[misc]
    with pytest.raises(ValueError):
        AnswerRow.model_validate({**r.model_dump(), "unknown": 1})


def test_package_refuses_import_without_eval_mode() -> None:
    env = {k: v for k, v in os.environ.items() if k != "EVAL_MODE"}
    env["PYTHONPATH"] = str(REPO / "backend")
    done = subprocess.run(
        [sys.executable, "-c", "import app.eval.groundedness"], env=env, capture_output=True, text=True, cwd=REPO, check=False
    )  # fmt: skip
    assert done.returncode != 0 and "EVAL_MODE" in done.stderr
    env["EVAL_MODE"] = "true"
    ok = subprocess.run([sys.executable, "-c", "import app.eval.groundedness.cli"], env=env, capture_output=True, text=True, cwd=REPO, check=False)
    assert ok.returncode == 0, ok.stderr
