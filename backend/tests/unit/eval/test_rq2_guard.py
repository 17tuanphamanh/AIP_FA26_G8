"""RQ2 — `app.eval.rq2` chỉ import được khi `EVAL_MODE=true` (chặn thừa hưởng từ `app/eval/__init__.py`); script dừng mã 2 khi thiếu
cờ / APP_ENV ngoài dev, test / LLM_CACHE_MODE ≠ eval. Subprocess: trong tiến trình test `app.eval` đã nằm trong `sys.modules`."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.unit.eval.eval_scripts import load_script

REPO = Path(__file__).resolve().parents[4]
MODULES = ["app.eval.rq2", "app.eval.rq2.source", "app.eval.rq2.logprob", "app.eval.rq2.report"]


def _import(module: str, eval_mode: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "EVAL_MODE"}
    env["PYTHONPATH"] = str(REPO / "backend")
    if eval_mode is not None:
        env["EVAL_MODE"] = eval_mode
    return subprocess.run([sys.executable, "-c", f"import {module}"], cwd=REPO, env=env, capture_output=True, text=True,
                          timeout=120, check=False)  # fmt: skip


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("value", [None, "false"], ids=["thieu", "false"])
def test_rq2_import_refused_without_eval_mode(module: str, value: str | None) -> None:
    out = _import(module, value)
    assert out.returncode != 0
    assert "ImportError" in out.stderr and "EVAL_MODE=true" in out.stderr


def test_rq2_import_allowed_with_eval_mode() -> None:
    out = _import("app.eval.rq2.collect", "true")
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize(
    ("env", "msg"),
    [
        ({"EVAL_MODE": None}, "EVAL_MODE"),
        ({"EVAL_MODE": "false"}, "EVAL_MODE"),
        ({"EVAL_MODE": "true", "APP_ENV": "staging", "LLM_CACHE_MODE": "eval"}, "APP_ENV"),
        ({"EVAL_MODE": "true", "APP_ENV": "prod", "LLM_CACHE_MODE": "eval"}, "APP_ENV"),
        ({"EVAL_MODE": "true", "APP_ENV": "dev", "LLM_CACHE_MODE": "default"}, "LLM_CACHE_MODE"),
    ],
    ids=["thieu", "false", "staging", "prod", "cache_default"],
)
def test_collect_script_stops(env: dict[str, str | None], msg: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                              capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    script = load_script("rq2_collect")
    code = script.main(["--s1-predictions", str(tmp_path / "khong-co.jsonl"), "--label", "t", "--out", str(tmp_path / "out")])
    assert code == 2
    assert msg in capsys.readouterr().err
    assert not (tmp_path / "out").exists()  # dừng trước mọi việc


def test_report_script_stops_without_eval_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("EVAL_MODE", raising=False)
    assert load_script("rq2_report").main([str(tmp_path)]) == 2
