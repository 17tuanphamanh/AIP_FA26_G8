"""`scripts/download_models.py` (make models) — phần logic không cần mạng: dựng kế hoạch từ lock, lọc file.

Script nằm ngoài package `app` (chạy bằng `uv run --with huggingface_hub`) nên nạp theo đường dẫn.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from app.lock import REQUIRED

SHA = "0123456789abcdef0123456789abcdef01234567"
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "download_models.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("download_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["download_models"] = module
    spec.loader.exec_module(module)
    return module


dm = _load()


def lock(**over: dict[str, object]) -> dict[str, dict[str, object]]:
    base: dict[str, dict[str, object]] = {k: {"repo": r, "revision": SHA} for k, r in dm.REPOS.items()}
    return {**base, **over}


def test_script_and_service_agree_on_models() -> None:
    assert tuple(dm.REPOS) == REQUIRED  # cùng tập mục mà ml-service đọc (app/lock.py)
    assert dm.LOCK == Path(__file__).resolve().parents[1] / "models.lock.json"


def test_first_run_pins_current_sha() -> None:
    seen: list[str] = []

    def resolve(repo: str) -> str:
        seen.append(repo)
        return SHA

    assert dm.plan(None, resolve) == lock()
    assert seen == list(dm.REPOS.values())


def test_existing_lock_used_without_resolving() -> None:
    other = "f" * 40
    got = dm.plan(lock(rerank={"repo": dm.REPOS["rerank"], "revision": other}), lambda _: pytest.fail())
    assert got["rerank"]["revision"] == other and got["embed"]["revision"] == SHA


@pytest.mark.parametrize(
    "bad",
    [
        {"embed": {"repo": "BAAI/khac", "revision": SHA}},
        {"embed": {"repo": "BAAI/bge-m3", "revision": None}},
        {"embed": {"repo": "BAAI/bge-m3", "revision": "main"}},
        {"them": {"repo": "x", "revision": SHA}},
    ],
)
def test_mismatched_lock_stops(bad: dict[str, dict[str, object]]) -> None:
    with pytest.raises(dm.LockMismatch):
        dm.plan(lock(**bad), lambda _: SHA)


def test_resolved_revision_must_be_sha() -> None:
    with pytest.raises(dm.LockMismatch):
        dm.plan(None, lambda _: "main")


def test_ignore_patterns_skip_unused_weights() -> None:
    both = dm.ignore_patterns(["model.safetensors", "pytorch_model.bin", "tokenizer.json"])
    assert "pytorch_model.bin" in both and "onnx/*" in both and "colbert_linear.pt" in both
    assert "pytorch_model.bin" not in dm.ignore_patterns(["pytorch_model.bin", "config.json"])
