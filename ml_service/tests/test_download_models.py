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


# ---- --tokenizer-only (make tokenizer, 3b Q-3b-11) — không mạng ---------------------------------------


def test_tokenizer_target_from_lock(tmp_path: Path) -> None:
    repo, rev, target = dm.tokenizer_target(lock(), tmp_path)
    assert (repo, rev) == ("BAAI/bge-m3", SHA)
    assert target == tmp_path / f"BAAI/bge-m3@{SHA}"


def _write_lock(tmp_path: Path) -> Path:
    import json

    path = tmp_path / "models.lock.json"
    path.write_text(json.dumps(lock()), encoding="utf-8")
    return path


def test_tokenizer_only_downloads_three_files(tmp_path: Path) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    out = tmp_path / "_tokenizer"
    code = dm.tokenizer_only(out, lock_path=_write_lock(tmp_path), download=lambda *a, **k: calls.append((a, k)))
    assert code == 0
    assert calls == [(("BAAI/bge-m3",), {"revision": SHA, "local_dir": out / f"BAAI/bge-m3@{SHA}",
                                        "allow_patterns": dm.TOKENIZER_FILES})]  # fmt: skip
    assert dm.TOKENIZER_FILES == ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]


def test_tokenizer_only_skips_when_present(tmp_path: Path) -> None:
    out = tmp_path / "_tokenizer"
    target = out / f"BAAI/bge-m3@{SHA}"
    target.mkdir(parents=True)
    (target / "tokenizer.json").write_text("{}", encoding="utf-8")
    code = dm.tokenizer_only(out, lock_path=_write_lock(tmp_path), download=lambda *a, **k: pytest.fail("tải lại"))
    assert code == 0


def test_tokenizer_only_needs_lock(tmp_path: Path) -> None:
    missing = tmp_path / "khong-co.json"
    assert dm.tokenizer_only(tmp_path, lock_path=missing, download=lambda *a, **k: pytest.fail("tải")) == 1
    assert not missing.exists()  # không tự tạo lock
