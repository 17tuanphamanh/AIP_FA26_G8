"""Luật N3 của script mutation (`scripts/mutation/n3.py`; PROGRESS "Việc treo" 15, PLAN-3h S16): file đích còn chữ `MUTATION`
→ dừng trước khi đột biến; mốc chưa đột biến đỏ → dừng; và mọi đột biến của `mutate_3g.py`/`mutate_3h.py` đều để lại dấu (không
có dấu thì lần chạy bị giết giữa chừng để lại đột biến mà (a) không thấy)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
MUT = REPO / "scripts" / "mutation"


def _load(name: str) -> ModuleType:
    if str(MUT) not in sys.path:
        sys.path.insert(0, str(MUT))  # mutate_3g/3h `import n3` như khi chạy script
    spec = importlib.util.spec_from_file_location(f"_mut_{name}", MUT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


n3 = _load("n3")
OK = [sys.executable, "-c", "pass"]
RED = [sys.executable, "-c", "raise SystemExit(1)"]


def _repo(tmp_path: Path, text: str) -> Path:
    (tmp_path / "a.py").write_text(text, encoding="utf-8")
    return tmp_path


def test_leftover_mark_stops_before_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, "x = 1  # MUTATION M-3h-9\n")
    assert n3.guard(repo, ["a.py"], [RED], {}) == 2  # dừng ở (a) — chưa chạy mốc (mốc đỏ cũng không được nhắc)
    out = capsys.readouterr().out
    assert "N3a" in out and "a.py" in out and "N3b" not in out


def test_red_baseline_stops(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert n3.guard(_repo(tmp_path, "x = 1\n"), ["a.py"], [OK, RED], {}) == 2
    assert "N3b" in capsys.readouterr().out


def test_clean_and_green_runs_each_distinct_command_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert n3.guard(_repo(tmp_path, "x = 1\n"), ["a.py"], [OK, list(OK), OK], {}) is None
    assert "1 lệnh, đều xanh" in capsys.readouterr().out


@pytest.mark.parametrize("script", ["mutate_3g", "mutate_3h"])
def test_every_mutation_leaves_the_mark(script: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [script])
    module = _load(script)
    for m in [*module.UNIT, *getattr(module, "E2E_MUTATIONS", []), *module.INTEGRATION]:
        texts = {rel: (REPO / rel).read_text(encoding="utf-8") for rel, *_ in m.edits}
        for rel, old, new, count in m.edits:
            assert texts[rel].count(old) == count, (m.name, rel)
            texts[rel] = texts[rel].replace(old, new)
        assert all(n3.MARK in t for t in texts.values()), m.name


def test_source_tree_has_no_leftover_mark() -> None:
    dirs = ("backend/app", "mock_services/app", "config", "backend/tests/stack", "backend/tests/fakes")  # mọi thư mục có file đích
    targets = [p for d in dirs for p in (REPO / d).rglob("*") if p.suffix in {".py", ".json", ".yaml"}]
    assert targets and not [str(p) for p in targets if n3.MARK in p.read_text(encoding="utf-8")]
