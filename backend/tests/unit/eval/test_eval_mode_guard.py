"""Q-T29-2 — `app.eval` chỉ import được khi `EVAL_MODE=true` (P8 §8:399). Chạy subprocess: cùng tiến trình thì `app.eval` đã
nằm trong `sys.modules` (conftest), `__init__` không chạy lại."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
BACKEND = REPO / "backend"


def _import_app_eval(eval_mode: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "EVAL_MODE"}
    env["PYTHONPATH"] = str(BACKEND)
    if eval_mode is not None:
        env["EVAL_MODE"] = eval_mode
    return subprocess.run(
        [sys.executable, "-c", "import app.eval"], cwd=REPO, env=env, capture_output=True, text=True, timeout=60, check=False
    )


@pytest.mark.parametrize("value", [None, "false", "", "1", "yes", "truee"], ids=["thieu", "false", "rong", "1", "yes", "truee"])
def test_import_refused_without_eval_mode(value: str | None) -> None:
    out = _import_app_eval(value)
    assert out.returncode != 0
    assert "ImportError" in out.stderr
    assert "EVAL_MODE=true" in out.stderr


@pytest.mark.parametrize("value", ["true", "TRUE", " true "])
def test_import_allowed_with_eval_mode(value: str) -> None:
    out = _import_app_eval(value)
    assert out.returncode == 0, out.stderr


def test_eval_mode_restored_after_conftest(eval_mode_before: str | None) -> None:
    """conftest trả env ngay sau lần import duy nhất."""
    assert os.environ.get("EVAL_MODE") == eval_mode_before
