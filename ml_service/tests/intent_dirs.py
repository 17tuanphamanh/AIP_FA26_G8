"""Dựng thư mục `intent-clf` (bản safetensors, gói 2 — D-53) cho test: đúng ở MỌI điểm (SHA trọng số + manifest + SHA
manifest khớp, config và ngưỡng hợp lệ) để ca từ chối bắt được đúng lỗi đang kiểm. Không torch: trọng số là byte tuỳ ý
(`check_intent` không mở file trọng số); test cần torch truyền byte safetensors thật."""

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.settings import MlSettings
from tests.conftest import INTENT_LABELS, INTENT_TAGS

MANIFEST = "MANIFEST.sha256"
VERSION = "v3.1-seed42-st"
REQ_MASK = [1.0 if t.startswith(("B-REQ:", "I-REQ:")) else 0.0 for t in INTENT_TAGS]
CONFIG: dict[str, Any] = {
    "model_name": "FacebookAI/xlm-roberta-base", "labels": list(INTENT_LABELS), "tags": list(INTENT_TAGS),
    "req_mask": REQ_MASK, "max_len": 160, "dropout": 0.1, "model_files": ["model.safetensors"],
    "mix_weights": [0.4, 0.6, 0.0], "thresholds": [0.75] * 5, "span_lambda": 4.0,
}  # fmt: skip
THRESHOLDS: dict[str, Any] = {
    **{label: {"tau_lo": 0.75, "tau_hi": 0.75} for label in INTENT_LABELS}, "note": "chưa có 2 ngưỡng riêng",
}  # fmt: skip


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_text(d: Path) -> str:
    rels = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and p.name != MANIFEST)
    return "".join(f"{sha((d / rel).read_bytes())}  {rel}\n" for rel in rels)


def write_manifest(d: Path) -> str:
    text = manifest_text(d).encode("utf-8")
    (d / MANIFEST).write_bytes(text)
    return sha(text)


def config(**over: Any) -> dict[str, Any]:
    return {**copy.deepcopy(CONFIG), **over}


def write_intent_dir(
    root: Path, weights: bytes = b"trong-so-intent-gia", *, cfg: Mapping[str, Any] | None = None,
    thresholds: Mapping[str, Any] | None = None, tokenizer: Mapping[str, bytes] | None = None,
    encoder: Mapping[str, bytes] | None = None, name: str = VERSION,
) -> tuple[Path, str, str]:  # fmt: skip
    """→ (thư mục, INTENT_MODEL_SHA256, INTENT_MANIFEST_SHA256)."""
    d = root / "intent-clf" / name
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(weights)
    (d / "inference_config.json").write_text(json.dumps(CONFIG if cfg is None else cfg), encoding="utf-8")
    (d / "thresholds.json").write_text(json.dumps(THRESHOLDS if thresholds is None else thresholds), encoding="utf-8")
    for sub, files in (("tokenizer", tokenizer or {"tokenizer.json": b"{}"}),
                       ("encoder_config", encoder or {"config.json": b"{}"})):  # fmt: skip
        (d / sub).mkdir()
        for rel, data in files.items():
            (d / sub / rel).write_bytes(data)
    return d, sha(weights), write_manifest(d)


def intent_settings(settings: MlSettings, root: Path, d: Path, weights_sha: str | None, manifest_sha: str | None,
                    **over: Any) -> MlSettings:  # fmt: skip
    update = {"ml_models_root": root, "intent_model_dir": d, "intent_model_sha256": weights_sha,
              "intent_manifest_sha256": manifest_sha, **over}  # fmt: skip
    return settings.model_copy(update=update)
