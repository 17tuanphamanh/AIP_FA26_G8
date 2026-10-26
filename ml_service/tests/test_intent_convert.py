"""Gói 2 (D-53; `dac-ta-bat-2-model.md` 6.2 mục 1) — `scripts/ml/convert_intent_pt.py`: `seed_42.pt` → thư mục safetensors FP32.

Marker `ml_torch` (cần torch, gói giả nhỏ, không mạng). Kiểm: SHA ĐẦY ĐỦ trước `torch.load`; `weights_only=True` chặn pickle lạ;
thư mục đích MỚI (có rồi → dừng), gốc giữ nguyên; `model_files` = ["model.safetensors"]; `thresholds.json` từ `thresholds` của
config (tau_lo = tau_hi); manifest + 2 SHA in ra nạp được bằng chính `check_intent` / `load_intent`.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("safetensors")

from app.intent import check_intent, classify_intent_sync
from app.intent_model import load_intent
from app.settings import MlSettings
from tests.conftest import INTENT_LABELS
from tests.intent_dirs import intent_settings
from tests.intent_torch import write_source_package
from tests.test_intent_model import reference_probs

pytestmark = pytest.mark.ml_torch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "ml"
FLAG: list[str] = []


def _converter() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # make_manifest cùng thư mục
    try:
        spec = importlib.util.spec_from_file_location("_convert_intent_pt", SCRIPTS / "convert_intent_pt.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


class _Evil:
    def __reduce__(self) -> tuple[Any, tuple[str]]:
        return (FLAG.append, ("đã chạy mã trong pickle",))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(d: Path) -> dict[str, str]:
    return {p.relative_to(d).as_posix(): _sha(p) for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    FLAG.clear()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "ml_models"
    r.mkdir()
    return r


def _run(argv: list[str]) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = _converter().main(argv, echo=lines.append)
    return code, lines


def _printed(lines: list[str], name: str) -> str:
    [line] = [x for x in lines if x.startswith(f"{name}=")]
    return line.split("=", 1)[1]


def test_default_sha_is_d44_pin() -> None:
    assert _converter().PT_SHA256 == "3efd3bd0437d93b5f5e41eefa19a99dae9e73830e99b4fe5323ae00f45c46db9"


def test_convert_then_load(settings: MlSettings, root: Path) -> None:
    src, dst = root / "intent-clf" / "v3.1-seed42", root / "intent-clf" / "v3.1-seed42-st"
    state = write_source_package(src)
    before = _tree(src)
    code, lines = _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt"), "--no-reference"])
    assert code == 0, lines
    assert _tree(src) == before  # thư mục gốc giữ nguyên
    files = set(_tree(dst))
    assert {"model.safetensors", "inference_config.json", "thresholds.json", "MANIFEST.sha256"} <= files
    assert not any(f.endswith(".pt") for f in files)
    assert {f.split("/")[0] for f in files if "/" in f} == {"tokenizer", "encoder_config"}
    cfg_src = json.loads((src / "inference_config.json").read_text(encoding="utf-8"))
    cfg_dst = json.loads((dst / "inference_config.json").read_text(encoding="utf-8"))
    assert cfg_dst == {**cfg_src, "model_files": ["model.safetensors"]}
    thr = json.loads((dst / "thresholds.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in thr.items() if k != "note"} == {label: {"tau_lo": 0.75, "tau_hi": 0.75} for label in INTENT_LABELS}
    assert "chưa có 2 ngưỡng riêng" in thr["note"]
    from safetensors.torch import load_file

    out = load_file(str(dst / "model.safetensors"))
    assert set(out) == set(state) and all(v.dtype == torch.float32 for v in out.values())
    assert all(torch.equal(out[k], state[k].half().float()) for k in state)  # fp16 gốc → fp32 không đổi giá trị
    assert _printed(lines, "INTENT_MODEL_DIR") == "/ml_models/intent-clf/v3.1-seed42-st"
    wsha, msha = _printed(lines, "INTENT_MODEL_SHA256"), _printed(lines, "INTENT_MANIFEST_SHA256")
    assert wsha == _sha(dst / "model.safetensors") and msha == _sha(dst / "MANIFEST.sha256")
    spec = check_intent(intent_settings(settings, root, dst, wsha, msha))
    assert spec is not None
    text = "vpn không vào được"
    assert classify_intent_sync(load_intent(spec), text).probs == pytest.approx(reference_probs(dst, text), abs=1e-5)


def test_self_check_reports_reference_mismatch(root: Path) -> None:
    """Không `--no-reference`: tự nạp bằng bộ nạp ml-service, chấm 3 câu đối chiếu; model giả lệch → thoát 1, vẫn in SHA."""
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)
    code, lines = _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt")])
    assert code == 1
    assert sum("LỆCH" in x or "OK" in x for x in lines) == 3
    assert _printed(lines, "INTENT_MODEL_SHA256") == _sha(dst / "model.safetensors")


def test_sha_mismatch_stops_before_torch_load(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)

    def boom(*a: Any, **kw: Any) -> None:
        raise AssertionError("torch.load trước khi kiểm SHA")

    monkeypatch.setattr(torch, "load", boom)
    code, lines = _run([str(src), str(dst), "--sha", "0" * 64])
    assert code == 2 and "SHA-256" in lines[-1]
    assert not dst.exists()


def test_weights_only_blocks_pickled_code(root: Path) -> None:
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)
    torch.save({"enc.x": torch.zeros(1), "bay": _Evil()}, src / "seed_42.pt")
    code, lines = _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt"), "--no-reference"])
    assert code == 2 and "weights_only" in lines[-1]
    assert FLAG == [] and not dst.exists()


def test_weights_only_passed_explicitly(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)
    seen: list[dict[str, Any]] = []
    real = torch.load

    def spy(*a: Any, **kw: Any) -> Any:
        seen.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(torch, "load", spy)
    assert _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt"), "--no-reference"])[0] == 0
    assert [kw.get("weights_only") for kw in seen] == [True]


def test_existing_dst_refused(root: Path) -> None:
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)
    dst.mkdir()
    (dst / "giu.txt").write_text("không được đè")
    code, lines = _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt"), "--no-reference"])
    assert code == 2 and "đã có" in lines[-1]
    assert [p.name for p in dst.iterdir()] == ["giu.txt"]


def test_not_flat_state_dict_refused(root: Path) -> None:
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)
    torch.save({"state_dict": {"enc.x": torch.zeros(1)}}, src / "seed_42.pt")
    code, lines = _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt"), "--no-reference"])
    assert code == 2 and "phẳng" in lines[-1] and not dst.exists()


def test_model_files_must_be_seed_42(root: Path) -> None:
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)
    cfg = json.loads((src / "inference_config.json").read_text(encoding="utf-8"))
    (src / "inference_config.json").write_text(json.dumps({**cfg, "model_files": ["seed_7.pt"]}), encoding="utf-8")
    code, lines = _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt"), "--no-reference"])
    assert code == 2 and "model_files" in lines[-1] and not dst.exists()


def test_code_file_in_tokenizer_refused(root: Path) -> None:
    src, dst = root / "intent-clf" / "goc", root / "intent-clf" / "st"
    write_source_package(src)
    (src / "tokenizer" / "tokenization_x.py").write_text("print(1)")
    code, lines = _run([str(src), str(dst), "--sha", _sha(src / "seed_42.pt"), "--no-reference"])
    assert code == 2 and "tokenization_x.py" in lines[-1] and not dst.exists()
