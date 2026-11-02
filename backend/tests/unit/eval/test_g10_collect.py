"""G10 — `prob_variants.py collect-no-evidence` (script đo sau tag bf94df2, không đổi hành vi — P8 §10) phần KHÔNG cần DB: guard factory,
chọn ca, kiểm `p_method` = sampling_k5 (manifest lượt, bản ghi), in số dự kiến, `--dry-run` (0 lời gọi, 0 file), dòng `error`.

DB (audit/checkpoint chỉ đọc, factory ghi `llm_calls`) ở `tests/integration/test_g10_pg.py`. ScriptedLLM, không mạng, không key thật.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from app.eval import dbread, llm_factory, prob_collect
from app.eval.llm_factory import (
    EvalConfigError,
    eval_gateway,
    eval_ids,
    open_port,
    resolve_factory,
)
from app.eval.prob_collect import Gathered, llm_records
from app.settings import Settings
from tests.unit._b2review import load_script
from tests.unit.eval import _g10
from tests.unit.eval.test_predictions import parse, rec
from tests.unit.eval.test_predictions import write as write_predictions

REPO = Path(__file__).resolve().parents[4]
FAKE_KEY = "sk-FAKE-g10-7c1d9e42a0b8f3-QQtop"
K5 = "sampling_k5"


def settings(**over: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test", "eval_mode": True, "llm_backend": "real", "fast_model": "deepseek-flash",
        "strong_model": "deepseek-v4-pro", "llm_api_key": FAKE_KEY, "llm_base_url": "https://llm.example.invalid",
        "database_url": "postgresql+psycopg://app_rw:pw@127.0.0.1:1/none",
    }  # fmt: skip
    return Settings(_env_file=None, **(values | over))  # type: ignore[call-arg]


async def _enter(**over: Any) -> None:
    async with eval_gateway("run-1", settings=settings(**over)):
        raise AssertionError("không được vào tới đây")


# ---- factory: guard (0 kết nối) ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "a b", "x/y", "ö", "a" * 49, "a;b", "'; DROP"])
def test_run_id_is_validated(bad: str) -> None:
    with pytest.raises(EvalConfigError):
        eval_ids(bad)


def test_eval_ids_are_stable() -> None:
    ids = eval_ids("g10-ab12cd34")
    assert (ids.ticket_id, ids.turn_id) == ("eval-g10-ab12cd34", "eval-g10-ab12cd34-t1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("over", "needle"),
    [({"eval_mode": False}, "EVAL_MODE"), ({"llm_backend": "scripted"}, "LLM_BACKEND=real")],
)
async def test_gateway_refuses_without_eval_mode_or_with_scripted_backend(over: dict[str, Any], needle: str) -> None:
    with pytest.raises(EvalConfigError, match=needle):
        await _enter(**over)


@pytest.mark.asyncio
async def test_gateway_refuses_nonzero_role_temperature(tmp_path: Path) -> None:
    config = tmp_path / "config"
    shutil.copytree(REPO / "config", config)
    raw = yaml.safe_load((config / "llm.yaml").read_text(encoding="utf-8"))
    raw["roles"]["strong"]["temperature"] = 0.3
    (config / "llm.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(EvalConfigError, match=r"temperature.*strong"):
        await _enter(config_dir=config)


@pytest.mark.asyncio
async def test_gateway_errors_never_contain_the_api_key_or_dsn() -> None:
    for over in ({"eval_mode": False}, {"llm_backend": "scripted"}, {"fast_model": None}, {"llm_base_url": None}):
        with pytest.raises(RuntimeError) as exc:
            await _enter(**over)
        assert FAKE_KEY not in str(exc.value) and "pw@" not in str(exc.value), over


def test_repo_roles_are_deterministic_so_real_config_passes_the_guard() -> None:
    raw = yaml.safe_load((REPO / "config" / "llm.yaml").read_text(encoding="utf-8"))
    assert {r: v["temperature"] for r, v in raw["roles"].items()} == {"fast": 0, "strong": 0}


# ---- factory: resolve / open_port --------------------------------------------------------------------------------------------


def test_resolve_factory_errors() -> None:
    for spec in ("khongcodauhaichuaham", ":fn", "mod:", "khong.co.module:fn", "tests.unit.eval._g10:khong_co"):
        with pytest.raises(ValueError, match="llm-factory"):
            resolve_factory(spec)
    assert resolve_factory("tests.unit.eval._g10:factory").__name__ == "factory"


@pytest.mark.asyncio
async def test_open_port_passes_run_id_and_optional_max_usd_and_enters_async_context() -> None:
    seen: list[tuple[str, float | None]] = []

    @asynccontextmanager
    async def fake(run_id: str, max_usd: float | None = None) -> Any:
        seen.append((run_id, max_usd))
        yield "PORT"

    llm_factory._TEST_FACTORY = fake  # type: ignore[attr-defined]
    try:
        async with open_port("app.eval.llm_factory:_TEST_FACTORY", "r1") as port:
            assert port == "PORT"
        async with open_port("app.eval.llm_factory:_TEST_FACTORY", "r2", max_usd=1.5):
            pass
    finally:
        del llm_factory._TEST_FACTORY  # type: ignore[attr-defined]
    assert seen == [("r1", None), ("r2", 1.5)]  # không truyền max_usd khi không đặt


@pytest.mark.asyncio
async def test_open_port_accepts_plain_port_factories() -> None:
    async with open_port("tests.unit.eval._g10:factory", "r1") as port:
        assert hasattr(port, "complete")


# ---- chọn ca -------------------------------------------------------------------------------------------------------------------


def test_llm_records_selects_labelled_llm_cases_sorted() -> None:
    records = [
        parse(rec(scenario_id="B-v1", ticket_id="T2")),
        parse(rec(scenario_id="A-v1", ticket_id="T1")),
        parse(rec(scenario_id="C-v1", ticket_id="T3", decided_by="rule", raw_prob=None, calibrated_prob=None, p_method=None, kb_gap=None)),
        parse(rec(scenario_id="D-v1", ticket_id="T4", expected_route=None)),
        parse(rec(scenario_id="E-v1", ticket_id="T5", route=None, decided_by=None, raw_prob=None, calibrated_prob=None, p_method=None, kb_gap=None)),
    ]  # fmt: skip
    chosen, skipped = llm_records(records)
    assert [r.scenario_id for r in chosen] == ["A-v1", "B-v1"] and dict(skipped) == {"unlabeled": 1}


# ---- CLI: kiểm trước khi gọi LLM ----------------------------------------------------------------------------------------------


@pytest.fixture
def pv(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_script("scripts/eval/prob_variants.py", monkeypatch)


class FakeReader:
    engine: Any = None


class Spy:
    def __init__(self, got: Gathered) -> None:
        self.got, self.opened, self.gathered, self.usage = got, 0, 0, 0


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    """DB giả: `open_reader` + `gather` + `eval_usage` thay bằng bản ghi nhận (import trong `_collect_run` lấy lúc gọi)."""
    s = Spy(Gathered(
        recorded=[_g10.with_row("A-v1", raw_prob=0.3), _g10.with_row("B-v1", raw_prob=0.7, kb_gap=True), _g10.with_row("C-v1")],
        cases=[_g10.case("A-v1"), _g10.case("B-v1"), _g10.case("C-v1", cert="revoked")],  # A ≠ C: không trúng cache gateway
        report={"n_predictions": 4, "n_llm_cases": 3, "n_gathered": 3, "n_kb_gap": 1, "skipped": {"unlabeled": 1}},
    ))  # fmt: skip

    @asynccontextmanager
    async def open_reader(_settings: Any = None) -> AsyncIterator[FakeReader]:
        s.opened += 1
        yield FakeReader()

    async def gather(_reader: Any, _records: Any, *, hours: Any, p_method: str) -> Gathered:
        assert p_method == K5
        s.gathered += 1
        return s.got

    async def eval_usage(_engine: Any, run_id: str) -> dict[str, Any]:
        s.usage += 1
        return {"n": -1, "run_id": run_id}

    monkeypatch.setattr(dbread, "open_reader", open_reader)
    monkeypatch.setattr(prob_collect, "gather", gather)
    monkeypatch.setattr(llm_factory, "eval_usage", eval_usage)
    return s


def run_dir(tmp_path: Path, *, prob_method: str = K5, mismatch: int = 0, p_method: str = K5) -> Path:
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    write_predictions(run / "predictions.jsonl", [
        rec(scenario_id="A-v1", ticket_id="TA", p_method=p_method), rec(scenario_id="B-v1", ticket_id="TB", p_method=K5),
        rec(scenario_id="C-v1", ticket_id="TC", p_method=K5), rec(scenario_id="D-v1", ticket_id="TD", expected_route=None),
    ])  # fmt: skip
    manifest = {"run_id": "0123456789ab", "strategy": "hybrid", "policy_sha256": "p" * 64, "git_commit": "bf94df2",
                "config": {"prob_method": prob_method}, "counts": {"p_method_mismatch": mismatch}}  # fmt: skip
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


def cli(pv: ModuleType, run: Path, out: Path, *extra: str) -> int:
    return int(pv.main(["collect-no-evidence", "--run", str(run), "--out", str(out), *extra]))


def test_p_method_option_only_accepts_sampling_k5(pv: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        pv.main(["collect-no-evidence", "--run", str(tmp_path), "--out", str(tmp_path / "o"), "--p-method", "self_report"])


@pytest.mark.parametrize(
    ("over", "needle"),
    [({"prob_method": "self_report"}, "config.prob_method"), ({"mismatch": 2}, "p_method_mismatch"),
     ({"p_method": "self_report"}, "predictions: 1 ca")],
)  # fmt: skip
def test_p_method_mismatch_stops_before_db_and_llm(
    pv: ModuleType, spy: Spy, tmp_path: Path, capsys: pytest.CaptureFixture[str], over: dict[str, Any], needle: str
) -> None:
    out = tmp_path / "out"
    assert cli(pv, run_dir(tmp_path, **over), out, "--llm-factory", "tests.unit.eval._g10:factory") == 2
    assert needle in capsys.readouterr().err
    assert (spy.opened, spy.gathered, spy.usage) == (0, 0, 0) and not out.exists()


def test_missing_run_manifest_stops(pv: ModuleType, spy: Spy, tmp_path: Path) -> None:
    run = run_dir(tmp_path)
    (run / "manifest.json").unlink()
    assert cli(pv, run, tmp_path / "out", "--dry-run") == 2 and spy.opened == 0


def test_factory_required_unless_dry_run(pv: ModuleType, spy: Spy, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(pv, run_dir(tmp_path), tmp_path / "out") == 2
    assert "--llm-factory" in capsys.readouterr().err and spy.opened == 0


def test_existing_output_stops_before_db(pv: ModuleType, spy: Spy, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "with.jsonl").write_text("cũ\n", encoding="utf-8")
    assert cli(pv, run_dir(tmp_path), out, "--llm-factory", "tests.unit.eval._g10:factory") == 2
    assert spy.opened == 0 and (out / "with.jsonl").read_text(encoding="utf-8") == "cũ\n"


def test_dry_run_prints_plan_reads_db_no_llm_no_files(
    pv: ModuleType, spy: Spy, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_port(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("--dry-run không được dựng factory")

    monkeypatch.setattr(llm_factory, "open_port", no_port)
    out = tmp_path / "out"
    assert cli(pv, run_dir(tmp_path), out, "--dry-run") == 0
    text = capsys.readouterr().out
    assert "3 ca đi lớp LLM; 1 ca kb_gap chép, không gọi; 2 ca gọi B14 trích đoạn rỗng × 5 phiếu = 10 lời gọi LLM" in text
    assert "--dry-run" in text and (spy.opened, spy.gathered, spy.usage) == (1, 1, 0) and not out.exists()


def test_real_run_calls_five_votes_per_non_kb_gap_case_and_writes_all(
    pv: ModuleType, spy: Spy, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    gw = _g10.gateway()
    monkeypatch.setattr(_g10, "factory", lambda run_id, **_: gw.client)
    out = tmp_path / "out"
    assert cli(pv, run_dir(tmp_path), out, "--llm-factory", "tests.unit.eval._g10:factory") == 0
    assert "= 10 lời gọi LLM" in capsys.readouterr().out
    calls = gw.llm.calls_for("b14_risk_vote")
    assert len(calls) == 10 and all(c.variables["evidence"] == [] for c in calls)  # 2 ca × 5 phiếu, trích đoạn rỗng; ca kb_gap không gọi
    without = [json.loads(x) for x in (out / "without.jsonl").read_text(encoding="utf-8").splitlines()]
    assert without == [{"scenario_id": "A-v1", "raw_prob": 0.6, "error": None}, {"scenario_id": "C-v1", "raw_prob": 0.6, "error": None}]
    by = {(r["scenario_id"], r["variant"]): r["raw_prob"]
          for r in map(json.loads, (out / "probs.jsonl").read_text(encoding="utf-8").splitlines())}  # fmt: skip
    assert by[("A-v1", "with_evidence")] == 0.3 and by[("A-v1", "no_evidence")] == 0.6 and by[("A-v1", "max")] == 0.6
    assert by[("B-v1", "no_evidence")] == 0.7  # kb_gap: chép
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["p_method"] == K5 and manifest["run_manifest"]["git_commit"] == "bf94df2" and manifest["llm_usage"]["n"] == -1
    assert any("P8 §10" in x for x in manifest["limitations"])
    assert FAKE_KEY not in json.dumps(manifest)


def test_llm_errors_become_error_rows_and_exit_3(pv: ModuleType, spy: Spy, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert cli(pv, run_dir(tmp_path), out, "--llm-factory", "tests.unit.eval._g10:failing_factory") == 3
    without = [json.loads(x) for x in (out / "without.jsonl").read_text(encoding="utf-8").splitlines()]
    assert without == [{"scenario_id": "A-v1", "raw_prob": None, "error": "LLMUnavailable"},
                       {"scenario_id": "C-v1", "raw_prob": None, "error": "LLMUnavailable"}]  # fmt: skip
    probs = [json.loads(x) for x in (out / "probs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(r["scenario_id"], r["variant"]) for r in probs} == {
        ("A-v1", "with_evidence"), ("B-v1", "with_evidence"), ("B-v1", "no_evidence"), ("B-v1", "max"), ("C-v1", "with_evidence")}
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["build"]["failed"] == {"LLMUnavailable": 2}


def test_collect_no_evidence_script_refuses_without_eval_mode(tmp_path: Path) -> None:
    """Không `EVAL_MODE=true` → script thoát mã 2, 0 kết nối (tiến trình con: trong pytest `app.eval` đã nạp qua conftest)."""
    env = {k: v for k, v in os.environ.items() if k != "EVAL_MODE"} | {"PYTHONPATH": str(REPO / "backend")}
    run = run_dir(tmp_path)
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "eval" / "prob_variants.py"), "collect-no-evidence", "--run", str(run),
         "--out", str(tmp_path / "o"), "--llm-factory", "a:b"],
        env=env, capture_output=True, text=True, cwd=REPO, check=False,
    )  # fmt: skip
    assert done.returncode == 2 and "EVAL_MODE=true" in done.stderr and not (tmp_path / "o").exists()
