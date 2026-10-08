"""Model chặn tấn công `injection-clf` (B2 L3) — phần THUẦN, không torch (ML-GAN phần 1, PLAN-ml-gan mục 1).

Cắt cửa sổ: model train ở max_length 128, không tiền xử lý. Tokenize KHÔNG cắt, KHÔNG thêm token đặc biệt, rồi TỰ cắt
trên danh sách id: thân 126 id, bước 94 (chồng 32), thêm cls/sep → ≤ 128 id; cửa sổ cuối phủ tới id cuối. Không dùng
`stride`/`return_overflowing_tokens` của tokenizer: với tokenizers 0.23.2 thư viện chỉ phủ 128/252 token của văn bản thử
(ML-KIEM, `.verify/ml-kiem/bao-cao.md` mục 3) — câu tấn công ở cuối văn bản dài sẽ không được chấm.

Điểm = max trên mọi cửa sổ của softmax ở lớp INJECTION (P4 mục 4: một cửa sổ độc là đủ). Trần `MAX_WINDOWS` = 48
(≈ 4.544 id; câu người dùng ≤ 4.000 ký tự ước ~43 cửa sổ): vượt → `TooManyWindows` → 422, không chấm một phần, không cắt
âm thầm.

`check_guard` chạy TRƯỚC khi import torch: đủ 4 file; không có file pickle/mã (.bin, .pt, .py… — `training_args.bin`
không bao giờ được đọc); SHA-256 của `model.safetensors` khi `GUARD_MODEL_SHA256` đặt; `id2label` của config.json có đúng
một nhãn "INJECTION". Sai bất kỳ → `GuardLoadError` → ml-service không khởi động (fail-closed).
"""

import hashlib
import json
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models import GUARD_LABEL, Guard
from app.schemas import ClassifyOut
from app.settings import MlSettings

log = logging.getLogger(__name__)

WINDOW_BODY = 126  # max_length 128 của model − cls − sep
WINDOW_STEP = 94  # chồng 32 id giữa hai cửa sổ liền nhau
MAX_WINDOWS = 48  # chốt 7b PLAN-ml-gan
INJECTION_LABEL = "INJECTION"
WEIGHTS_FILE = "model.safetensors"
REQUIRED_FILES = (WEIGHTS_FILE, "config.json", "tokenizer.json", "tokenizer_config.json")
FORBIDDEN_SUFFIXES = frozenset({".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".py"})


class GuardLoadError(Exception):
    """Thư mục model chặn tấn công sai/thiếu/lệch SHA — ml-service không khởi động."""


class TooManyWindows(Exception):
    def __init__(self, count: int) -> None:
        super().__init__(f"{count} cửa sổ > {MAX_WINDOWS}")
        self.count = count


@dataclass(frozen=True)
class GuardSpec:
    """Kết quả kiểm thư mục (trước torch) — `loader` nạp theo đây."""

    dir: Path
    injection_index: int
    version: str
    sha_checked: bool


def window_count(n: int) -> int:
    return 1 if n <= WINDOW_BODY else 1 + math.ceil((n - WINDOW_BODY) / WINDOW_STEP)


def windows(ids: Sequence[int], cls_id: int, sep_id: int) -> list[list[int]]:
    count = window_count(len(ids))
    if count > MAX_WINDOWS:
        raise TooManyWindows(count)
    return [[cls_id, *ids[k * WINDOW_STEP : k * WINDOW_STEP + WINDOW_BODY], sep_id] for k in range(count)]


def softmax(row: Sequence[float]) -> list[float]:
    top = max(row)
    exps = [math.exp(x - top) for x in row]
    total = sum(exps)
    return [e / total for e in exps]


def classify_sync(guard: Guard, text: str) -> ClassifyOut:
    ids = list(guard.tokenizer(text, add_special_tokens=False)["input_ids"])
    wins = windows(ids, guard.cls_id, guard.sep_id)
    rows = guard.scorer.logits(wins)
    if len(rows) != len(wins):
        raise RuntimeError(f"model trả {len(rows)} hàng logit cho {len(wins)} cửa sổ")
    p_malicious = max(softmax(row)[guard.injection_index] for row in rows)
    return ClassifyOut(p_malicious=p_malicious, windows=len(wins), model=GUARD_LABEL, version=guard.version)


def injection_index(id2label: Mapping[Any, Any]) -> int:
    """Vị trí lớp INJECTION theo `id2label` của config.json — đúng một nhãn, khoá 0..n-1, ≥ 2 lớp."""
    try:
        labels = {int(k): v for k, v in id2label.items()}
    except (TypeError, ValueError) as e:
        raise GuardLoadError("config.json: khoá của id2label phải là số") from e
    if len(labels) < 2 or sorted(labels) != list(range(len(labels))):
        raise GuardLoadError(f"config.json: id2label phải có ≥ 2 lớp đánh số 0..n-1 (đang {sorted(labels)})")
    hits = [i for i, name in labels.items() if name == INJECTION_LABEL]
    if len(hits) != 1:
        raise GuardLoadError(
            f"config.json: id2label phải có đúng một nhãn {INJECTION_LABEL!r} (đang {list(labels.values())})"
        )
    return hits[0]


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def check_guard(settings: MlSettings) -> GuardSpec | None:
    """`GUARD_MODEL_DIR` không đặt → None (/classify 503 như Phase 3). Đặt mà sai → `GuardLoadError`."""
    d = settings.guard_model_dir
    if d is None:
        return None
    if not d.is_dir():
        raise GuardLoadError(f"GUARD_MODEL_DIR={d} không phải thư mục — từ chối khởi động")
    forbidden = sorted(p.name for p in d.rglob("*") if p.suffix.lower() in FORBIDDEN_SUFFIXES)
    if forbidden:
        raise GuardLoadError(
            f"{d}: có file pickle/mã {forbidden} — chỉ nạp safetensors, không chạy mã; bỏ file đó khỏi thư mục"
        )
    missing = [name for name in REQUIRED_FILES if not (d / name).is_file()]
    if missing:
        raise GuardLoadError(f"{d}: thiếu {missing} — từ chối khởi động")
    expected = settings.guard_model_sha256
    if expected is None:
        log.warning("GUARD_MODEL_SHA256 chưa đặt — KHÔNG kiểm SHA-256 của %s", WEIGHTS_FILE)
    else:
        actual = sha256_file(d / WEIGHTS_FILE)
        if actual != expected:
            raise GuardLoadError(
                f"SHA-256 của {WEIGHTS_FILE} ({actual[:12]}…) lệch GUARD_MODEL_SHA256 ({expected[:12]}…) "
                "— từ chối khởi động"
            )
    try:
        config = json.loads((d / "config.json").read_text(encoding="utf-8"))
    except ValueError as e:
        raise GuardLoadError(f"{d / 'config.json'} không phải JSON hợp lệ") from e
    id2label = config.get("id2label") if isinstance(config, dict) else None
    if not isinstance(id2label, dict):
        raise GuardLoadError(f"{d / 'config.json'}: thiếu id2label")
    return GuardSpec(
        dir=d, injection_index=injection_index(id2label), version=d.name, sha_checked=expected is not None
    )
