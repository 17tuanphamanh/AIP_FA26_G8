"""Gói 1 (D-52) DỪNG 2 — nợ bảo mật #5 (gốc model) và #9 (SHA bắt buộc + `MANIFEST.sha256`) của ml-service.

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.7 (#5: `GUARD_MODEL_DIR`, `INTENT_MODEL_DIR` sau
`resolve()` nằm dưới gốc `ML_MODELS_ROOT` (mặc định `/ml_models`), mọi file trong thư mục cũng vậy; #9: `GUARD_MODEL_SHA256`
bắt buộc khi đặt `GUARD_MODEL_DIR`; `MANIFEST.sha256` liệt kê mọi file kèm SHA, `GUARD_MANIFEST_SHA256` ghim SHA của chính
manifest; đúng tập file (không thừa, không thiếu), cấm symlink, `..`, đường tuyệt đối; manifest không liệt kê chính nó),
mục 8; `PLAN-B2REVIEW.md` bảng 3.3 E, mục 8 (`MlSettings.ml_models_root`, `guard_manifest_sha256`,
`ml_classify_concurrency`; `app.guard.MANIFEST_FILE`, `parse_manifest`, `check_model_dirs`; lỗi → `GuardLoadError`).

Mỗi ca từ chối dựng thư mục ĐÚNG ở mọi điểm khác (SHA trọng số + manifest + SHA manifest khớp) để lỗi bắt được chính là lỗi
đang kiểm, không phải "thiếu SHA" (PLAN mục 2). Chạy: `uv run pytest ml_service/tests -o pythonpath=ml_service`.
"""

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.guard import GuardLoadError, check_guard
from app.loader import load_models
from app.lock import read_lock
from app.main import create_app
from app.settings import MlSettings
from fastapi.testclient import TestClient

pytestmark = pytest.mark.xfail(reason="gói 1 DỪNG 2 — chưa nối", strict=False)

WEIGHTS = b"trong-so-gia-cua-model"
MANIFEST = "MANIFEST.sha256"


def _g() -> Any:
    return importlib.import_module("app.guard")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_text(d: Path, *, extra_lines: tuple[str, ...] = (), skip: tuple[str, ...] = ()) -> str:
    lines = [f"{_sha(p.read_bytes())}  {p.relative_to(d).as_posix()}" for p in sorted(d.rglob("*"))
             if p.is_file() and not p.is_symlink() and p.name != MANIFEST and p.relative_to(d).as_posix() not in skip]  # fmt: skip
    return "\n".join([*lines, *extra_lines]) + "\n"


def _write_manifest(d: Path, text: str) -> str:
    (d / MANIFEST).write_text(text, encoding="utf-8")
    return _sha(text.encode("utf-8"))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "ml_models"
    r.mkdir()
    return r


@pytest.fixture
def guard_dir(root: Path) -> Path:
    d = root / "injection-clf" / "v3-seed123"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(WEIGHTS)
    (d / "config.json").write_text(json.dumps({"id2label": {"0": "BENIGN", "1": "INJECTION"}}))
    (d / "tokenizer.json").write_text("{}")
    (d / "tokenizer_config.json").write_text("{}")
    return d


def _settings(settings: MlSettings, root: Path, guard_dir: Path, manifest_sha: str | None, *,
              weights_sha: str | None = _sha(WEIGHTS), **over: Any) -> MlSettings:  # fmt: skip
    update = {"ml_models_root": root, "guard_model_dir": guard_dir, "guard_model_sha256": weights_sha,
              "guard_manifest_sha256": manifest_sha, **over}  # fmt: skip
    return settings.model_copy(update=update)


def _ok(settings: MlSettings, root: Path, guard_dir: Path) -> MlSettings:
    return _settings(settings, root, guard_dir, _write_manifest(guard_dir, _manifest_text(guard_dir)))


# ---- Settings mới ------------------------------------------------------------------------------------------------------------


def test_settings_defaults(token: str) -> None:
    s: Any = MlSettings(ml_service_token=token)
    assert (s.ml_classify_concurrency, s.ml_models_root, s.guard_manifest_sha256) == (1, Path("/ml_models"), None)
    assert _g().MANIFEST_FILE == MANIFEST


# ---- parse_manifest ---------------------------------------------------------------------------------------------------------


def test_parse_manifest_ok() -> None:
    a, b = "a" * 64, "b" * 64
    assert _g().parse_manifest(f"{a}  config.json\n{b}  sub/tokenizer.json\n") == {"config.json": a, "sub/tokenizer.json": b}


@pytest.mark.parametrize("text", [
    "abc  config.json\n",  # SHA sai dạng
    f"{'a' * 64} config.json\n",  # một dấu cách
    f"{'a' * 64}  ../ngoai.json\n",  # ..
    f"{'a' * 64}  sub/../../x.json\n",
    f"{'a' * 64}  /etc/passwd\n",  # đường tuyệt đối
    f"{'a' * 64}  {MANIFEST}\n",  # tự liệt kê mình
    f"{'a' * 64}  config.json\n{'b' * 64}  config.json\n",  # trùng
])  # fmt: skip
def test_parse_manifest_rejects(text: str) -> None:
    with pytest.raises(GuardLoadError):
        _g().parse_manifest(text)


# ---- check_guard: đúng hết → nhận ---------------------------------------------------------------------------------------------


def test_valid_dir_accepted(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    spec = check_guard(_ok(settings, root, guard_dir))
    assert spec is not None and spec.sha_checked is True and spec.version == "v3-seed123"


# ---- #9: thiếu SHA, thiếu SHA manifest, tập file lệch, SHA lệch ------------------------------------------------------------------


def test_missing_weights_sha_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir))
    with pytest.raises(GuardLoadError, match="GUARD_MODEL_SHA256"):
        check_guard(_settings(settings, root, guard_dir, sha, weights_sha=None))


def test_missing_manifest_sha_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    _write_manifest(guard_dir, _manifest_text(guard_dir))
    with pytest.raises(GuardLoadError, match="GUARD_MANIFEST_SHA256"):
        check_guard(_settings(settings, root, guard_dir, None))


def test_missing_manifest_file_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    sha = _sha(_manifest_text(guard_dir).encode())
    with pytest.raises(GuardLoadError, match=MANIFEST):
        check_guard(_settings(settings, root, guard_dir, sha))


def test_manifest_sha_mismatch_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    _write_manifest(guard_dir, _manifest_text(guard_dir))
    with pytest.raises(GuardLoadError):
        check_guard(_settings(settings, root, guard_dir, "0" * 64))


def test_manifest_missing_a_file_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    """Thư mục có `tokenizer.json` mà manifest không liệt kê → thừa file."""
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir, skip=("tokenizer.json",)))
    with pytest.raises(GuardLoadError, match="tokenizer.json"):
        check_guard(_settings(settings, root, guard_dir, sha))


def test_extra_file_in_dir_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir))
    (guard_dir / "README.md").write_text("them sau")
    with pytest.raises(GuardLoadError, match="README.md"):
        check_guard(_settings(settings, root, guard_dir, sha))


def test_manifest_lists_absent_file_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir, extra_lines=(f"{'c' * 64}  vocab.txt",)))
    with pytest.raises(GuardLoadError, match="vocab.txt"):
        check_guard(_settings(settings, root, guard_dir, sha))


def test_one_file_sha_wrong_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir))
    (guard_dir / "tokenizer.json").write_text('{"doi": true}')  # đổi sau khi lập manifest
    with pytest.raises(GuardLoadError, match="tokenizer.json"):
        check_guard(_settings(settings, root, guard_dir, sha))


@pytest.mark.parametrize("line", [f"{'a' * 64}  ../ngoai.json", f"{'a' * 64}  /tmp/x.json", f"{'a' * 64}  {MANIFEST}"])
def test_bad_manifest_line_refused(settings: MlSettings, root: Path, guard_dir: Path, line: str) -> None:
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir, extra_lines=(line,)))
    with pytest.raises(GuardLoadError):
        check_guard(_settings(settings, root, guard_dir, sha))


def test_symlink_inside_dir_refused(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    (guard_dir / "link.json").symlink_to(guard_dir / "config.json")  # trỏ trong thư mục vẫn cấm
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir, extra_lines=(f"{_sha(b'{}')}  link.json",)))
    with pytest.raises(GuardLoadError, match="link.json"):
        check_guard(_settings(settings, root, guard_dir, sha))


# ---- #5: thư mục / file ngoài gốc model ------------------------------------------------------------------------------------------


def test_symlink_pointing_outside_root_refused(settings: MlSettings, root: Path, guard_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "ngoai.json"
    outside.write_text("{}")
    (guard_dir / "ngoai.json").symlink_to(outside)
    sha = _write_manifest(guard_dir, _manifest_text(guard_dir, extra_lines=(f"{_sha(b'{}')}  ngoai.json",)))
    with pytest.raises(GuardLoadError):
        check_guard(_settings(settings, root, guard_dir, sha))


def test_guard_dir_outside_root_refused(settings: MlSettings, root: Path, tmp_path: Path) -> None:
    d = tmp_path / "noi-khac" / "v3-seed123"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(WEIGHTS)
    (d / "config.json").write_text(json.dumps({"id2label": {"0": "BENIGN", "1": "INJECTION"}}))
    (d / "tokenizer.json").write_text("{}")
    (d / "tokenizer_config.json").write_text("{}")
    s = _settings(settings, root, d, _write_manifest(d, _manifest_text(d)))
    with pytest.raises(GuardLoadError):
        check_guard(s)
    with pytest.raises(GuardLoadError):
        _g().check_model_dirs(s)


def test_guard_dir_escaping_with_dotdot_refused(settings: MlSettings, root: Path, tmp_path: Path) -> None:
    (tmp_path / "noi-khac").mkdir()
    s = settings.model_copy(update={"ml_models_root": root, "guard_model_dir": root / ".." / "noi-khac"})
    with pytest.raises(GuardLoadError):
        _g().check_model_dirs(s)


def test_intent_dir_outside_root_refused(settings: MlSettings, root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "intent-ngoai"
    outside.mkdir()
    s = settings.model_copy(update={"ml_models_root": root, "intent_model_dir": outside})
    with pytest.raises(GuardLoadError):
        _g().check_model_dirs(s)


def test_dirs_inside_root_accepted(settings: MlSettings, root: Path, guard_dir: Path) -> None:
    intent = root / "intent-clf" / "v3.1-seed42"
    intent.mkdir(parents=True)
    s = settings.model_copy(update={"ml_models_root": root, "guard_model_dir": guard_dir, "intent_model_dir": intent})
    _g().check_model_dirs(s)  # không ném


def test_intent_outside_root_blocks_startup_before_torch(settings: MlSettings, root: Path, tmp_path: Path) -> None:
    """Loader THẬT (như `test_sha_mismatch_blocks_startup_before_torch`): từ chối khởi động trước khi đụng torch."""
    for ref in read_lock(settings.models_lock).values():
        (settings.models_dir / ref.dirname).mkdir(parents=True)
    outside = tmp_path / "intent-ngoai"
    outside.mkdir()
    s = settings.model_copy(update={"ml_models_root": root, "intent_model_dir": outside})
    with pytest.raises(GuardLoadError), TestClient(create_app(s, loader=load_models)):
        pass
