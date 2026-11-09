"""Chuyển gói `intent-clf` (`seed_42.pt`, state_dict fp16) sang thư mục nạp được của ml-service (gói 2, D-53;
`dac-ta-bat-2-model.md` 6.2 mục 1). Tuấn Anh chạy MỘT lần, nhóm uv `ml`:

  PYTHONPATH=ml_service uv run --group ml python scripts/ml/convert_intent_pt.py \\
      ml_models/intent-clf/v3.1-seed42 ml_models/intent-clf/v3.1-seed42-st

1. Kiểm SHA-256 ĐẦY ĐỦ của `seed_42.pt` (`--sha`, mặc định bản Duy Anh gửi — D-44) TRƯỚC mọi `torch.load`; lệch → dừng.
2. `torch.load(..., weights_only=True)` (tường minh; torch ≥ 2.6) → state_dict PHẲNG khoá chuỗi → tensor; khác → dừng.
3. Lưu `model.safetensors` FP32 vào thư mục MỚI (đích đã có → dừng; thư mục gốc giữ nguyên). Chép `inference_config.json`
   (`model_files` = ["model.safetensors"]), `encoder_config/`, `tokenizer/` (có symlink / file pickle, mã → dừng).
4. Ghi `thresholds.json` `{nhãn: {"tau_lo", "tau_hi"}}` = `thresholds` của inference_config cho cả hai (gói chỉ có một ngưỡng
   — chưa có 2 ngưỡng riêng; khoá `note` ghi lại) và `MANIFEST.sha256` (cùng định dạng `make_manifest.py`).
5. Tự kiểm bằng CHÍNH bộ nạp của ml-service (`check_intent` + `load_intent`), chấm 3 câu đối chiếu; lệch > 0,01 → thoát 1.
6. In `INTENT_MODEL_DIR` (đường trong container), `INTENT_MODEL_SHA256`, `INTENT_MANIFEST_SHA256` — không phải bí mật.

Thoát: 0 xong; 1 tự kiểm/đối chiếu trượt (thư mục đã ghi — xem lại rồi xoá tay); 2 đầu vào sai (chưa ghi gì).
"""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from make_manifest import (  # scripts/ml/ — cùng thư mục (sys.path[0])
    MANIFEST_FILE,
    build_manifest,
)

PT_FILE = "seed_42.pt"
PT_SHA256 = "3efd3bd0437d93b5f5e41eefa19a99dae9e73830e99b4fe5323ae00f45c46db9"  # D-44: Duy Anh gửi 10/10
WEIGHTS_FILE = "model.safetensors"
CONFIG_FILE = "inference_config.json"
THRESHOLDS_FILE = "thresholds.json"
COPY_DIRS = ("tokenizer", "encoder_config")
FORBIDDEN_SUFFIXES = frozenset({".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".py"})  # khớp ml_service/app/guard.py
MIN_TORCH = (2, 6)
TOLERANCE = 0.01
# Điểm đối chiếu (gói gốc, CPU) — nhãn `vpn` phải cao nhất và lệch ≤ TOLERANCE.
REFERENCE = (
    ("VPN công ty dùng cổng nào?", "vpn", 0.973),
    ("gia hạn VPN cho máy LAP-0501", "vpn", 0.986),
    ("vpn không vào được", "vpn", 0.985),
)
NOTE = "D-53: gói intent chỉ có một ngưỡng (thresholds của inference_config) — tau_lo = tau_hi, chưa có 2 ngưỡng riêng"


class Stop(Exception):
    """Đầu vào sai — dừng, chưa ghi gì (thoát 2)."""


def sha256_of(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def check_source(src: Path, dst: Path) -> dict[str, Any]:
    if dst.exists():
        raise Stop(f"{dst} đã có — không ghi đè; chọn thư mục mới")
    pt = src / PT_FILE
    if not pt.is_file() or pt.is_symlink():
        raise Stop(f"{src}: thiếu {PT_FILE} (file thường)")
    try:
        config = json.loads((src / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Stop(f"{src / CONFIG_FILE}: đọc không được hoặc không phải JSON") from e
    if not isinstance(config, dict) or config.get("model_files") != [PT_FILE]:
        raise Stop(f"{CONFIG_FILE}: model_files phải đúng [{PT_FILE!r}] (file sẽ kiểm SHA)")
    for name in COPY_DIRS:
        d = src / name
        if not d.is_dir() or d.is_symlink():
            raise Stop(f"{src}: thiếu thư mục {name}/")
        links = sorted(p.relative_to(src).as_posix() for p in d.rglob("*") if p.is_symlink())
        bad = sorted(p.relative_to(src).as_posix() for p in d.rglob("*") if p.suffix.lower() in FORBIDDEN_SUFFIXES)
        if links or bad:
            raise Stop(f"{name}/: có symlink {links} / file pickle, mã {bad} — ml-service sẽ từ chối")
    return config


def thresholds_from(config: dict[str, Any]) -> dict[str, Any]:
    labels, taus = config.get("labels"), config.get("thresholds")
    if not isinstance(labels, list) or not isinstance(taus, list) or len(taus) != len(labels):
        raise Stop(f"{CONFIG_FILE}: thresholds phải là list cùng độ dài labels")
    if not all(isinstance(t, int | float) and not isinstance(t, bool) and 0 <= t <= 1 for t in taus):
        raise Stop(f"{CONFIG_FILE}: thresholds phải là số trong [0, 1]")
    return {**{label: {"tau_lo": float(t), "tau_hi": float(t)} for label, t in zip(labels, taus, strict=True)}, "note": NOTE}


def load_pt(pt: Path, expected_sha: str, *, echo: Callable[[str], None]) -> dict[str, Any]:
    """SHA ĐẦY ĐỦ trước, `torch.load(weights_only=True)` sau — lệch SHA thì không mở file bằng torch."""
    actual = sha256_of(pt)
    if actual != expected_sha:
        raise Stop(f"SHA-256 của {PT_FILE} = {actual} ≠ {expected_sha} — không nạp")
    echo(f"{PT_FILE}: SHA-256 khớp {actual}")
    import torch

    if tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2]) < MIN_TORCH:
        raise Stop(f"cần torch ≥ {MIN_TORCH[0]}.{MIN_TORCH[1]} — đang {torch.__version__}")
    try:
        state = torch.load(pt, map_location="cpu", weights_only=True)  # tường minh: không unpickle đối tượng tuỳ ý
    except Exception as e:  # noqa: BLE001 — pickle có đối tượng lạ / file hỏng: dừng, không thử cách nạp khác
        raise Stop(f"{PT_FILE}: torch.load(weights_only=True) từ chối — {type(e).__name__}") from None
    if not isinstance(state, dict) or not state:
        raise Stop(f"{PT_FILE}: phải là state_dict PHẲNG (dict khoá chuỗi → tensor)")
    odd = sorted(str(k) for k, v in state.items() if not isinstance(k, str) or not isinstance(v, torch.Tensor))
    if odd:
        raise Stop(f"{PT_FILE}: mục không phải tensor {odd[:5]} — không phải state_dict phẳng")
    not_float = sorted(k for k, v in state.items() if not v.is_floating_point())
    if not_float:
        raise Stop(f"{PT_FILE}: tensor không phải số thực {not_float[:5]}")
    # clone: safetensors từ chối tensor dùng chung bộ nhớ; float32: bộ nạp dựng trên meta + assign=True giữ đúng dtype này
    return {k: v.detach().to(torch.float32).contiguous().clone() for k, v in state.items()}


def write_package(src: Path, out: Path, config: dict[str, Any], state: dict[str, Any], source_sha: str) -> None:
    from safetensors.torch import save_file

    out.mkdir(parents=True)
    save_file(state, str(out / WEIGHTS_FILE), metadata={"source": PT_FILE, "source_sha256": source_sha, "dtype": "float32"})
    (out / CONFIG_FILE).write_text(
        json.dumps({**config, "model_files": [WEIGHTS_FILE]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in COPY_DIRS:
        shutil.copytree(src / name, out / name, symlinks=False)
    (out / THRESHOLDS_FILE).write_text(
        json.dumps(thresholds_from(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / MANIFEST_FILE).write_bytes(build_manifest(out).encode("utf-8"))


def self_check(dst: Path, root: Path, model_sha: str, manifest_sha: str, *, echo: Callable[[str], None]) -> bool:
    """Nạp bằng chính bộ nạp của ml-service (PYTHONPATH=ml_service) rồi chấm câu đối chiếu."""
    from app.intent import check_intent, classify_intent_sync
    from app.intent_model import load_intent
    from app.settings import MlSettings

    settings = MlSettings(  # token chỉ để dựng MlSettings, không dùng ở đâu
        ml_service_token=secrets.token_urlsafe(32), ml_models_root=root, intent_model_dir=dst,
        intent_model_sha256=model_sha, intent_manifest_sha256=manifest_sha,
    )  # fmt: skip
    spec = check_intent(settings)
    if spec is None:
        raise RuntimeError("check_intent trả None")
    intent = load_intent(spec)
    ok = True
    for text, label, expected in REFERENCE:
        probs = classify_intent_sync(intent, text).probs
        top = max(probs, key=lambda k: probs[k])
        diff = abs(probs[label] - expected)
        good = top == label and diff <= TOLERANCE
        ok &= good
        echo(f"  {'OK  ' if good else 'LỆCH'} {label} = {probs[label]:.3f} (đối chiếu {expected:.3f}, lệch {diff:.3f}; cao nhất {top})")
    return ok


def main(argv: Sequence[str], *, echo: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="seed_42.pt → thư mục safetensors cho ml-service (D-53)")
    ap.add_argument("src", type=Path, help="thư mục gói gốc (có seed_42.pt) — giữ nguyên")
    ap.add_argument("dst", type=Path, help="thư mục MỚI, vd ml_models/intent-clf/v3.1-seed42-st")
    ap.add_argument("--sha", default=PT_SHA256, help="SHA-256 đầy đủ của seed_42.pt (mặc định bản D-44)")
    ap.add_argument("--root", type=Path, default=None, help="gốc ML_MODELS_ROOT trên máy (mặc định: cha của cha dst)")
    ap.add_argument("--no-reference", action="store_true", help="bỏ chấm câu đối chiếu (chỉ cho model giả trong test)")
    args = ap.parse_args(argv)
    src, dst = args.src, args.dst
    root = args.root if args.root is not None else dst.resolve().parent.parent
    try:
        config = check_source(src, dst)
        thresholds_from(config)  # sai ngưỡng → dừng TRƯỚC khi nạp torch
        state = load_pt(src / PT_FILE, args.sha.lower(), echo=echo)
        tmp = dst.with_name(f".{dst.name}.tmp-{os.getpid()}")
        if tmp.exists():
            raise Stop(f"{tmp} đã có — xoá tay rồi chạy lại")
    except Stop as e:
        echo(f"DỪNG: {e}")
        return 2
    write_package(src, tmp, config, state, args.sha.lower())
    tmp.rename(dst)
    model_sha = sha256_of(dst / WEIGHTS_FILE)
    manifest_sha = hashlib.sha256((dst / MANIFEST_FILE).read_bytes()).hexdigest()
    echo(f"đã ghi {dst} ({len(state)} tensor fp32)")
    try:
        if args.no_reference:
            from app.intent import check_intent
            from app.settings import MlSettings

            check_intent(MlSettings(
                ml_service_token=secrets.token_urlsafe(32), ml_models_root=root, intent_model_dir=dst,
                intent_model_sha256=model_sha, intent_manifest_sha256=manifest_sha,
            ))  # fmt: skip
            ok = True
        else:
            echo("tự kiểm bằng bộ nạp ml-service + 3 câu đối chiếu:")
            ok = self_check(dst, root, model_sha, manifest_sha, echo=echo)
    except Exception as e:  # noqa: BLE001 — báo rồi thoát 1, thư mục đã ghi để xem lại
        echo(f"DỪNG: tự kiểm trượt — {type(e).__name__}: {e}")
        return 1
    rel = dst.resolve().relative_to(root.resolve()).as_posix() if dst.resolve().is_relative_to(root.resolve()) else None
    echo(f"INTENT_MODEL_DIR=/ml_models/{rel}" if rel else f"(dst ngoài --root {root}: tự đặt INTENT_MODEL_DIR)")
    echo(f"INTENT_MODEL_SHA256={model_sha}")
    echo(f"INTENT_MANIFEST_SHA256={manifest_sha}")
    if not ok:
        echo(f"DỪNG: câu đối chiếu lệch > {TOLERANCE} — báo lại, chưa dùng thư mục này")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
