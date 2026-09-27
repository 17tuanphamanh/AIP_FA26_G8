"""Lock model + fail-closed lúc khởi động (thiết kế 3a mục 4.4 bước 1, Q-3a-14)."""

import json
import re
import sys
from pathlib import Path

import pytest
from app.loader import load_models
from app.lock import DEFAULT_LOCK, LockError, main, model_dirs, read_lock
from app.main import create_app
from app.settings import MlSettings
from fastapi.testclient import TestClient

SHA = "0123456789abcdef0123456789abcdef01234567"


def write_lock(path: Path, embed_rev: object = SHA, rerank_rev: object = SHA) -> Path:
    path.write_text(json.dumps({
        "embed": {"repo": "BAAI/bge-m3", "revision": embed_rev},
        "rerank": {"repo": "BAAI/bge-reranker-v2-m3", "revision": rerank_rev},
    }), encoding="utf-8")  # fmt: skip
    return path


def test_repo_lock_pins_40_hex_revisions() -> None:
    """Q-3a-14: lock trong repo phải có SHA thật (người chạy `make models` trước commit 3a)."""
    raw = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
    assert set(raw) == {"embed", "rerank"}
    assert raw["embed"]["repo"] == "BAAI/bge-m3"
    assert raw["rerank"]["repo"] == "BAAI/bge-reranker-v2-m3"
    for key in ("embed", "rerank"):
        assert re.fullmatch(r"[0-9a-f]{40}", raw[key]["revision"]), f"{key}.revision không phải SHA"


@pytest.mark.parametrize("bad", [None, "main", "abc1234", SHA.upper(), SHA + "0"])
def test_revision_must_be_40_hex(tmp_path: Path, bad: object) -> None:
    with pytest.raises(LockError, match="make models"):
        read_lock(write_lock(tmp_path / "lock.json", rerank_rev=bad))


def test_missing_lock_mentions_make_models(tmp_path: Path) -> None:
    with pytest.raises(LockError, match="make models"):
        read_lock(tmp_path / "khong-co.json")


def test_model_dirs_layout_repo_at_revision(tmp_path: Path) -> None:
    lock = write_lock(tmp_path / "lock.json")
    (tmp_path / "m" / f"BAAI/bge-m3@{SHA}").mkdir(parents=True)
    with pytest.raises(LockError, match=r"rerank: .*bge-reranker-v2-m3@"):
        model_dirs(tmp_path / "m", lock)
    (tmp_path / "m" / f"BAAI/bge-reranker-v2-m3@{SHA}").mkdir(parents=True)
    assert model_dirs(tmp_path / "m", lock)["embed"] == tmp_path / "m" / f"BAAI/bge-m3@{SHA}"


def test_real_loader_refuses_before_importing_torch(
    tmp_path: Path, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch → ImportError nếu loader chạm tới
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    settings = MlSettings(ml_service_token=token, models_dir=tmp_path / "models",
                          models_lock=write_lock(tmp_path / "lock.json"))  # fmt: skip
    with pytest.raises(LockError, match="make models"):
        load_models(settings)
    with pytest.raises(LockError, match="make models"), TestClient(create_app(settings)):
        pass  # service không lên


def test_lock_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lock", str(tmp_path / "trong")]) == 1
    assert "make models" in capsys.readouterr().err
