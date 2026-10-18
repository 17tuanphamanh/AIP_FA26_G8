"""Gói 1 (D-52) DỪNG 2 — `scripts/ml/make_manifest.py`: sinh `MANIFEST.sha256` cho thư mục model chặn tấn công (nợ #9).

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.7 #9 (mỗi dòng `sha256  đường/tương/đối` như
`sha256sum`, không liệt kê chính nó; cấm symlink); `PLAN-B2REVIEW.md` bảng 3.3 E, mục 8 (`build_manifest(dir) -> str` dòng
sắp xếp, không có `MANIFEST.sha256`, symlink → ValueError; `main(argv) -> int` ghi file, in sha256 của manifest). Script nạp
bằng importlib; không import `ml_service`.
"""

import hashlib
from pathlib import Path
from types import ModuleType

import pytest
from tests.unit._b2review import load_script

FILES = {"model.safetensors": b"trong-so", "config.json": b"{}", "tokenizer.json": b'{"a": 1}',
         "tokenizer_config.json": b"{ }", "sub/special_tokens_map.json": b"[]"}  # fmt: skip


@pytest.fixture
def mm(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_script("scripts/ml/make_manifest.py", monkeypatch)


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    d = tmp_path / "injection-clf" / "v3-seed123"
    for rel, data in FILES.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)
    return d


def _want() -> list[str]:
    return [f"{hashlib.sha256(data).hexdigest()}  {rel}" for rel, data in sorted(FILES.items())]


def test_build_manifest_sha256sum_format_sorted(mm: ModuleType, model_dir: Path) -> None:
    text = mm.build_manifest(model_dir)
    assert text.splitlines() == _want()
    assert text.endswith("\n")


def test_build_manifest_excludes_itself(mm: ModuleType, model_dir: Path) -> None:
    (model_dir / "MANIFEST.sha256").write_text("cu\n", encoding="utf-8")
    assert mm.build_manifest(model_dir).splitlines() == _want()


def test_build_manifest_symlink_refused(mm: ModuleType, model_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "ngoai.json"
    outside.write_text("{}", encoding="utf-8")
    (model_dir / "link.json").symlink_to(outside)
    with pytest.raises(ValueError):
        mm.build_manifest(model_dir)


def test_main_writes_manifest_and_prints_its_sha(mm: ModuleType, model_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    expected = mm.build_manifest(model_dir)
    assert mm.main([str(model_dir)]) == 0
    written = (model_dir / "MANIFEST.sha256").read_bytes()
    assert written.decode("utf-8") == expected
    assert hashlib.sha256(written).hexdigest() in capsys.readouterr().out
    assert mm.build_manifest(model_dir) == expected  # chạy lại sau khi ghi: không tự liệt kê mình
