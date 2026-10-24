"""Model chặn tấn công `injection-clf` (B2 L3) — phần THUẦN, không torch (ML-GAN phần 1, PLAN-ml-gan mục 1).

Cắt cửa sổ: model train ở max_length 128, không tiền xử lý. Tokenize KHÔNG cắt, KHÔNG thêm token đặc biệt, rồi TỰ cắt
trên danh sách id: thân 126 id, bước 94 (chồng 32), thêm cls/sep → ≤ 128 id; cửa sổ cuối phủ tới id cuối. Không dùng
`stride`/`return_overflowing_tokens` của tokenizer: với tokenizers 0.23.2 thư viện chỉ phủ 128/252 token của văn bản thử
(ML-KIEM, `.verify/ml-kiem/bao-cao.md` mục 3) — câu tấn công ở cuối văn bản dài sẽ không được chấm.

Điểm = max trên mọi cửa sổ của softmax ở lớp INJECTION (P4 mục 4: một cửa sổ độc là đủ). Trần `MAX_WINDOWS` = 48
(≈ 4.544 id; câu người dùng ≤ 4.000 ký tự ước ~43 cửa sổ): vượt → `TooManyWindows` → 422, không chấm một phần, không cắt
âm thầm.

`check_guard` chạy TRƯỚC khi import torch: đủ 4 file; không có file pickle/mã (.bin, .pt, .py… — `training_args.bin`
không bao giờ được đọc); `id2label` của config.json có đúng một nhãn "INJECTION". Sai bất kỳ → `GuardLoadError` → ml-service
không khởi động (fail-closed).

Phase 5 gói 1 (D-52, phase5 §6.5 #5, #9; `dac-ta-bat-2-model.md` 4.7):
- #5 `check_model_dirs`: `GUARD_MODEL_DIR`, `INTENT_MODEL_DIR` và mọi mục trong đó, sau `resolve()`, nằm dưới `ML_MODELS_ROOT`.
- #9: `GUARD_MODEL_SHA256` và `GUARD_MANIFEST_SHA256` BẮT BUỘC khi đặt `GUARD_MODEL_DIR`. `MANIFEST.sha256` (định dạng
  `sha256sum`: `<64 hex>  <đường/tương/đối>`, không liệt kê chính nó — sinh bằng `scripts/ml/make_manifest.py`) phải đúng SHA
  ghim, liệt kê ĐÚNG tập file của thư mục (không thừa, không thiếu) và đúng SHA từng file; cấm symlink, `..`, đường tuyệt đối.
"""

import hashlib
import json
import logging
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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
MANIFEST_FILE = "MANIFEST.sha256"  # gói 1 (#9)
_MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  (\S(?:.*\S)?)$")


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
    scores = [softmax(row)[guard.injection_index] for row in rows]
    if not all(math.isfinite(s) for s in scores):  # gói 1 (#10): max() bỏ qua NaN không đứng đầu → p bị hạ lặng lẽ; ném → classify_failed
        raise ValueError("điểm của model không hữu hạn")
    p_malicious = max(scores)
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


def parse_manifest(text: str) -> dict[str, str]:
    """`MANIFEST.sha256` → {đường tương đối: sha256}. Sai dạng, `..`, đường tuyệt đối, trùng, tự liệt kê → `GuardLoadError`."""
    out: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        m = _MANIFEST_LINE.match(line)
        if m is None:
            raise GuardLoadError(f"{MANIFEST_FILE} dòng {n}: phải là `<sha256 64 hex>  <đường/tương/đối>` (như sha256sum)")
        sha, rel = m.groups()
        path = PurePosixPath(rel)
        if path.is_absolute() or "\\" in rel or ".." in path.parts or rel.startswith(("/", "~")) or ":" in path.parts[0]:
            raise GuardLoadError(f"{MANIFEST_FILE} dòng {n}: đường dẫn phải tương đối, không có `..`")
        rel = path.as_posix()
        if rel == MANIFEST_FILE:
            raise GuardLoadError(f"{MANIFEST_FILE} dòng {n}: manifest không được liệt kê chính nó")
        if rel in out:
            raise GuardLoadError(f"{MANIFEST_FILE} dòng {n}: {rel} trùng")
        out[rel] = sha
    if not out:
        raise GuardLoadError(f"{MANIFEST_FILE} rỗng")
    return out


def _under(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def check_model_dirs(settings: MlSettings) -> None:
    """#5: thư mục model của nhóm và MỌI mục trong đó (kể cả đích symlink) nằm dưới `ML_MODELS_ROOT` sau `resolve()`."""
    root = settings.ml_models_root
    for name, d in (("GUARD_MODEL_DIR", settings.guard_model_dir), ("INTENT_MODEL_DIR", settings.intent_model_dir)):
        if d is None:
            continue
        if not _under(d, root):
            raise GuardLoadError(f"{name}={d} không nằm dưới ML_MODELS_ROOT={root} — từ chối khởi động")
        if d.is_dir():
            links = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_symlink())
            if links:  # rglob không đi vào symlink thư mục → cấm hẳn symlink (cả thư mục intent chưa có manifest)
                raise GuardLoadError(f"{name}: có symlink {links} — từ chối khởi động")
            outside = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if not _under(p, root))
            if outside:
                raise GuardLoadError(f"{name}: {outside} trỏ ra ngoài ML_MODELS_ROOT — từ chối khởi động")


def _check_manifest(d: Path, settings: MlSettings) -> dict[str, str]:
    """#9: SHA bắt buộc, manifest đúng SHA ghim, đúng tập file, đúng SHA từng file. Trả {file: sha256 thật}."""
    if settings.guard_model_sha256 is None:
        raise GuardLoadError("GUARD_MODEL_SHA256 bắt buộc khi đặt GUARD_MODEL_DIR — từ chối khởi động")
    if settings.guard_manifest_sha256 is None:
        raise GuardLoadError("GUARD_MANIFEST_SHA256 bắt buộc khi đặt GUARD_MODEL_DIR — từ chối khởi động")
    return verify_manifest(d, settings.guard_manifest_sha256, "GUARD_MANIFEST_SHA256")


def verify_manifest(
    d: Path, pinned: str, var: str, error: type[GuardLoadError] = GuardLoadError
) -> dict[str, str]:
    """Manifest đúng SHA ghim (`var`), đúng tập file, đúng SHA từng file — dùng chung cho guard và intent (gói 2, D-53)."""
    manifest = d / MANIFEST_FILE
    if not manifest.is_file():
        raise error(f"{d}: thiếu {MANIFEST_FILE} — sinh bằng scripts/ml/make_manifest.py")
    raw = manifest.read_bytes()
    actual_manifest = hashlib.sha256(raw).hexdigest()
    if actual_manifest != pinned:
        raise error(
            f"SHA-256 của {MANIFEST_FILE} ({actual_manifest[:12]}…) lệch {var} ({pinned[:12]}…) — từ chối khởi động"
        )
    try:
        listed = parse_manifest(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise error(f"{MANIFEST_FILE} không phải UTF-8") from None
    except GuardLoadError as e:
        raise error(str(e)) from None
    present = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()} - {MANIFEST_FILE}
    extra, missing = sorted(present - set(listed)), sorted(set(listed) - present)
    if extra or missing:
        raise error(f"{d}: tập file lệch {MANIFEST_FILE} — thừa {extra}, thiếu {missing} — từ chối khởi động")
    hashes = {rel: sha256_file(d / rel) for rel in sorted(listed)}
    wrong = sorted(rel for rel, sha in hashes.items() if sha != listed[rel])
    if wrong:
        raise error(f"{d}: SHA-256 lệch {MANIFEST_FILE} ở {wrong} — từ chối khởi động")
    return hashes


def check_guard(settings: MlSettings) -> GuardSpec | None:
    """`GUARD_MODEL_DIR` không đặt → None (/classify 503 như Phase 3). Đặt mà sai → `GuardLoadError`."""
    d = settings.guard_model_dir
    if d is None:
        return None
    if not _under(d, settings.ml_models_root):  # gói 1 #5
        raise GuardLoadError(f"GUARD_MODEL_DIR={d} không nằm dưới ML_MODELS_ROOT={settings.ml_models_root} — từ chối khởi động")
    if not d.is_dir():
        raise GuardLoadError(f"GUARD_MODEL_DIR={d} không phải thư mục — từ chối khởi động")
    links = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_symlink())
    if links:  # gói 1 #9: cấm symlink, kể cả trỏ trong thư mục
        raise GuardLoadError(f"{d}: có symlink {links} — từ chối khởi động")
    odd = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if not p.is_file() and not p.is_dir())
    if odd:  # gói 1 #9: FIFO/socket/thiết bị không được lọt khỏi so sánh tập file
        raise GuardLoadError(f"{d}: có mục không phải file thường {odd} — từ chối khởi động")
    check_model_dirs(settings)
    forbidden = sorted(p.name for p in d.rglob("*") if p.suffix.lower() in FORBIDDEN_SUFFIXES)
    if forbidden:
        raise GuardLoadError(
            f"{d}: có file pickle/mã {forbidden} — chỉ nạp safetensors, không chạy mã; bỏ file đó khỏi thư mục"
        )
    missing = [name for name in REQUIRED_FILES if not (d / name).is_file()]
    if missing:
        raise GuardLoadError(f"{d}: thiếu {missing} — từ chối khởi động")
    hashes = _check_manifest(d, settings)  # gói 1 #9 — băm mỗi file MỘT lần (trọng số ~1,1 GB)
    expected = settings.guard_model_sha256
    if expected is not None:
        actual = hashes[WEIGHTS_FILE]
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
    return GuardSpec(dir=d, injection_index=injection_index(id2label), version=d.name, sha_checked=True)
