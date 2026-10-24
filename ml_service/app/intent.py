"""Model intent `intent-clf` (B3, gói 2 — D-53; `dac-ta-bat-2-model.md` 6.2) — phần THUẦN, không torch.

`INTENT_MODEL_DIR` không đặt → `/classify_intent` 503 `model_missing` như Phase 3 (Q-3a-13): B3 đi đường LLM. Có đặt →
`check_intent` kiểm thư mục TRƯỚC khi import torch (cùng khuôn `guard.check_guard`), sai bất kỳ → `IntentLoadError` →
ml-service không khởi động (fail-closed):
- dưới `ML_MODELS_ROOT`, không symlink, không mục lạ; không file pickle/mã (`.pt`, `.bin`, `.py`… — thư mục nạp là bản đã
  chuyển sang safetensors bằng `scripts/ml/convert_intent_pt.py`, `seed_42.pt` ở lại thư mục gốc);
- `INTENT_MODEL_SHA256` (SHA-256 `model.safetensors`) và `INTENT_MANIFEST_SHA256` bắt buộc; `MANIFEST.sha256` đúng tập file;
- `inference_config.json`: `labels` đúng 5 nhãn đúng thứ tự `LABELS`; `len(tags) = len(req_mask) = 23`, `req_mask` = 1 đúng ở
  các tag `B-REQ:*`/`I-REQ:*`; `mix_weights[2] == 0` (bộ nạp không làm lượt `p_filt`); `model_files == ["model.safetensors"]`;
- `thresholds.json`: `{nhãn: {"tau_lo", "tau_hi"}}` đủ 5 nhãn, trong [0, 1], `tau_lo ≤ tau_hi` (khoá `note` tuỳ chọn).

Điểm = điểm trộn của gói (`predict_proba` của `intent_inference.py`): `w0·sigmoid(seq) + w1·p_span`; `p_span[l]` = max theo token
có offset `b > a` và `_anchor` hợp lệ của P(`B-REQ:l`) + P(`I-REQ:l`). Điểm không hữu hạn → `ValueError` → `classify_failed`.
Phần torch (B3Model, nạp safetensors) ở `intent_model.py`.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from app.classify import model_missing
from app.guard import (
    FORBIDDEN_SUFFIXES,
    GuardLoadError,
    check_model_dirs,
    verify_manifest,
)
from app.models import INTENT_LABEL, Intent
from app.schemas import IntentOut
from app.settings import MlSettings

LABELS = ("account", "vpn", "software", "access", "out_of_scope")  # thứ tự của gói (inference_config `labels`)
N_TAGS = 23  # "O", B/I-REQ × 5, B/I-MEN × 5, B-CTX, I-CTX
WEIGHTS_FILE = "model.safetensors"
CONFIG_FILE = "inference_config.json"
THRESHOLDS_FILE = "thresholds.json"
TOKENIZER_DIR = "tokenizer"
ENCODER_DIR = "encoder_config"
REQUIRED_FILES = (WEIGHTS_FILE, CONFIG_FILE, THRESHOLDS_FILE)
REQUIRED_DIRS = (TOKENIZER_DIR, ENCODER_DIR)
THRESHOLDS_NOTE_KEY = "note"


class IntentLoadError(GuardLoadError):
    """Thư mục model intent sai/thiếu/lệch SHA — ml-service không khởi động (cùng họ lỗi thư mục model của nhóm)."""


@dataclass(frozen=True)
class IntentSpec:
    """Kết quả kiểm thư mục (trước torch) — `intent_model.load_intent` nạp theo đây."""

    dir: Path
    labels: tuple[str, ...]
    tags: tuple[str, ...]
    req_mask: tuple[float, ...]
    max_len: int
    dropout: float
    mix: tuple[float, float]
    tau_lo: dict[str, float]
    tau_hi: dict[str, float]
    version: str

    @property
    def b_req(self) -> tuple[int, ...]:
        return tuple(self.tags.index(f"B-REQ:{label}") for label in self.labels)

    @property
    def i_req(self) -> tuple[int, ...]:
        return tuple(self.tags.index(f"I-REQ:{label}") for label in self.labels)


def intent_missing() -> JSONResponse:
    return model_missing()


# ---- điểm -------------------------------------------------------------------------------------------------------------


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)  # x < 0: không tràn số
    return e / (1.0 + e)


def anchor(text: str, a: int, b: int) -> int:
    """`_anchor` của gói: ký tự không phải khoảng trắng đầu tiên trong [a, b), không có → -1."""
    c = a
    while c < b and text[c].isspace():
        c += 1
    return c if c < b else -1


def span_probs(
    text: str, tok_probs: Sequence[Sequence[float]], offsets: Sequence[tuple[int, int]],
    b_req: Sequence[int], i_req: Sequence[int],
) -> list[float]:  # fmt: skip
    """`_span_prob` của gói: token có offset `b > a` và `anchor ≥ 0` (bỏ token đặc biệt, token toàn khoảng trắng)."""
    ks = [t for t, (a, b) in enumerate(offsets) if b > a and anchor(text, a, b) >= 0]
    return [max((tok_probs[t][bi] + tok_probs[t][ii] for t in ks), default=0.0) for bi, ii in zip(b_req, i_req, strict=True)]


def classify_intent_sync(intent: Intent, text: str) -> IntentOut:
    raw = intent.scorer.score(text)
    n = len(intent.labels)
    if len(raw.seq_logits) != n or len(raw.tok_probs) != len(raw.offsets):
        raise RuntimeError(f"model trả {len(raw.seq_logits)} logit / {len(raw.tok_probs)} hàng tag cho {n} nhãn")
    p_span = span_probs(text, raw.tok_probs, raw.offsets, intent.b_req, intent.i_req)
    w_seq, w_span = intent.mix
    probs = [w_seq * sigmoid(s) + w_span * p for s, p in zip(raw.seq_logits, p_span, strict=True)]
    if not all(math.isfinite(p) for p in probs):  # NaN lọt vào JSON/audit là sai lặng lẽ — ném → classify_failed
        raise ValueError("điểm của model intent không hữu hạn")
    return IntentOut(
        probs=dict(zip(intent.labels, probs, strict=True)), tau_hi=dict(intent.tau_hi), tau_lo=dict(intent.tau_lo),
        truncated=raw.full_len > intent.max_len, model=INTENT_LABEL, version=intent.version,
    )  # fmt: skip


# ---- kiểm thư mục (trước torch) ---------------------------------------------------------------------------------------


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_config(raw: Any) -> tuple[tuple[str, ...], tuple[str, ...], tuple[float, ...], int, float, tuple[float, float]]:
    """`inference_config.json` → (labels, tags, req_mask, max_len, dropout, (w0, w1)). Sai → `IntentLoadError`."""
    if not isinstance(raw, dict):
        raise IntentLoadError(f"{CONFIG_FILE}: phải là object JSON")
    labels = raw.get("labels")
    if not isinstance(labels, list) or tuple(labels) != LABELS:
        raise IntentLoadError(f"{CONFIG_FILE}: labels phải đúng {list(LABELS)} (đúng thứ tự) — đang {labels!r}")
    tags, req_mask = raw.get("tags"), raw.get("req_mask")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags) or len(tags) != N_TAGS:
        raise IntentLoadError(f"{CONFIG_FILE}: tags phải là {N_TAGS} chuỗi")
    if len(set(tags)) != N_TAGS:
        raise IntentLoadError(f"{CONFIG_FILE}: tags bị trùng")
    if not isinstance(req_mask, list) or len(req_mask) != N_TAGS or not all(_number(v) for v in req_mask):
        raise IntentLoadError(f"{CONFIG_FILE}: req_mask phải là {N_TAGS} số (len(tags) = len(req_mask))")
    missing = [f"{p}-REQ:{label}" for label in LABELS for p in "BI" if f"{p}-REQ:{label}" not in tags]
    if missing:
        raise IntentLoadError(f"{CONFIG_FILE}: tags thiếu {missing}")
    want = [1.0 if t.startswith(("B-REQ:", "I-REQ:")) else 0.0 for t in tags]
    if [float(v) for v in req_mask] != want:
        raise IntentLoadError(f"{CONFIG_FILE}: req_mask phải = 1 đúng ở tag B-REQ/I-REQ, 0 ở tag khác")
    max_len, dropout, mix = raw.get("max_len"), raw.get("dropout", 0.0), raw.get("mix_weights")
    if not isinstance(max_len, int) or isinstance(max_len, bool) or max_len < 2:
        raise IntentLoadError(f"{CONFIG_FILE}: max_len phải là số nguyên ≥ 2")
    if not _number(dropout) or not 0 <= dropout < 1:
        raise IntentLoadError(f"{CONFIG_FILE}: dropout phải trong [0, 1)")
    if not isinstance(mix, list) or len(mix) != 3 or not all(_number(w) for w in mix):
        raise IntentLoadError(f"{CONFIG_FILE}: mix_weights phải là 3 số hữu hạn")
    if mix[2] != 0:
        raise IntentLoadError(f"{CONFIG_FILE}: mix_weights[2] = {mix[2]} ≠ 0 — bộ nạp không làm lượt p_filt, từ chối khởi động")
    if raw.get("model_files") != [WEIGHTS_FILE]:
        raise IntentLoadError(f"{CONFIG_FILE}: model_files phải đúng [{WEIGHTS_FILE!r}] (bản đã chuyển sang safetensors)")
    return tuple(labels), tuple(tags), tuple(float(v) for v in req_mask), max_len, float(dropout), (float(mix[0]), float(mix[1]))


def parse_thresholds(raw: Any) -> tuple[dict[str, float], dict[str, float]]:
    """`thresholds.json` → (tau_lo, tau_hi) theo `LABELS`. Sai → `IntentLoadError`."""
    if not isinstance(raw, dict):
        raise IntentLoadError(f"{THRESHOLDS_FILE}: phải là object JSON")
    note = raw.get(THRESHOLDS_NOTE_KEY)
    if note is not None and not isinstance(note, str):
        raise IntentLoadError(f"{THRESHOLDS_FILE}: {THRESHOLDS_NOTE_KEY} phải là chuỗi")
    keys = set(raw) - {THRESHOLDS_NOTE_KEY}
    if keys != set(LABELS):
        raise IntentLoadError(
            f"{THRESHOLDS_FILE}: phải đủ đúng 5 nhãn — thiếu {sorted(set(LABELS) - keys)}, thừa {sorted(keys - set(LABELS))}"
        )
    tau_lo: dict[str, float] = {}
    tau_hi: dict[str, float] = {}
    for label in LABELS:
        row = raw[label]
        if not isinstance(row, dict) or set(row) != {"tau_lo", "tau_hi"}:
            raise IntentLoadError(f"{THRESHOLDS_FILE}: {label} phải là {{\"tau_lo\", \"tau_hi\"}}")
        lo, hi = row["tau_lo"], row["tau_hi"]
        if not (_number(lo) and _number(hi) and 0 <= lo <= 1 and 0 <= hi <= 1):
            raise IntentLoadError(f"{THRESHOLDS_FILE}: {label} ngoài [0, 1]")
        if lo > hi:
            raise IntentLoadError(f"{THRESHOLDS_FILE}: {label} có tau_lo > tau_hi")
        tau_lo[label], tau_hi[label] = float(lo), float(hi)
    return tau_lo, tau_hi


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise IntentLoadError(f"{path} không phải JSON hợp lệ") from e


def check_intent(settings: MlSettings) -> IntentSpec | None:
    """`INTENT_MODEL_DIR` không đặt → None (/classify_intent 503 như Phase 3). Đặt mà sai → `IntentLoadError`."""
    d = settings.intent_model_dir
    if d is None:
        return None
    check_model_dirs(settings)  # gói 1 #5: dưới ML_MODELS_ROOT, không symlink (GuardLoadError — cùng họ lỗi)
    if not d.is_dir():
        raise IntentLoadError(f"INTENT_MODEL_DIR={d} không phải thư mục — từ chối khởi động")
    odd = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if not p.is_file() and not p.is_dir())
    if odd:
        raise IntentLoadError(f"{d}: có mục không phải file thường {odd} — từ chối khởi động")
    forbidden = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.suffix.lower() in FORBIDDEN_SUFFIXES)
    if forbidden:
        raise IntentLoadError(
            f"{d}: có file pickle/mã {forbidden} — chỉ nạp safetensors (scripts/ml/convert_intent_pt.py), không chạy mã"
        )
    missing = [n for n in REQUIRED_FILES if not (d / n).is_file()] + [n for n in REQUIRED_DIRS if not (d / n).is_dir()]
    if missing:
        raise IntentLoadError(f"{d}: thiếu {missing} — từ chối khởi động")
    if settings.intent_model_sha256 is None:
        raise IntentLoadError("INTENT_MODEL_SHA256 bắt buộc khi đặt INTENT_MODEL_DIR — từ chối khởi động")
    if settings.intent_manifest_sha256 is None:
        raise IntentLoadError("INTENT_MANIFEST_SHA256 bắt buộc khi đặt INTENT_MODEL_DIR — từ chối khởi động")
    hashes = verify_manifest(d, settings.intent_manifest_sha256, "INTENT_MANIFEST_SHA256", IntentLoadError)
    weights_sha = hashes[WEIGHTS_FILE]  # có trong manifest: file bắt buộc đã có, tập file khớp manifest
    if weights_sha != settings.intent_model_sha256:
        raise IntentLoadError(
            f"SHA-256 của {WEIGHTS_FILE} ({weights_sha[:12]}…) lệch INTENT_MODEL_SHA256 "
            f"({settings.intent_model_sha256[:12]}…) — từ chối khởi động"
        )
    labels, tags, req_mask, max_len, dropout, mix = parse_config(_read_json(d / CONFIG_FILE))
    tau_lo, tau_hi = parse_thresholds(_read_json(d / THRESHOLDS_FILE))
    return IntentSpec(
        dir=d, labels=labels, tags=tags, req_mask=req_mask, max_len=max_len, dropout=dropout, mix=mix,
        tau_lo=tau_lo, tau_hi=tau_hi, version=d.name,
    )  # fmt: skip
