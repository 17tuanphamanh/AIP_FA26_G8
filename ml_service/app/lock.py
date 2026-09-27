"""`models.lock.json` — model nào, ở revision HF nào (3-Q19). Một nguồn cho cả ml-service lẫn `make up`.

Model nằm ở `MODELS_DIR/<repo>@<revision>` (ví dụ `models/BAAI/bge-m3@<sha>`), do `make models` tải trên
máy (`scripts/download_models.py`) rồi mount read-only vào container. Revision phải là SHA commit đủ
40 hex — nhánh (`main`) trôi theo thời gian, vector giữa hai lần ingest sẽ lệch.

`python -m app.lock [MODELS_DIR]` (PYTHONPATH=ml_service): kiểm lock + thư mục model, thiếu → thoát 1.
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from app.settings import DEFAULT_LOCK

REQUIRED = ("embed", "rerank")
REVISION = re.compile(r"^[0-9a-f]{40}$")
HINT = "chạy `make models` trên máy (tải model về MODELS_DIR, mặc định ./models)"


class LockError(Exception):
    """Lock thiếu/sai hoặc thiếu thư mục model — ml-service không khởi động."""


@dataclass(frozen=True)
class ModelRef:
    repo: str
    revision: str

    @property
    def dirname(self) -> str:
        return f"{self.repo}@{self.revision}"

    @property
    def short(self) -> str:
        return self.revision[:7]


def read_lock(path: Path = DEFAULT_LOCK) -> dict[str, ModelRef]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise LockError(f"không có {path} — {HINT}") from e
    except ValueError as e:
        raise LockError(f"{path} không phải JSON hợp lệ") from e
    refs: dict[str, ModelRef] = {}
    for key in REQUIRED:
        entry = raw.get(key) if isinstance(raw, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("repo"), str):
            raise LockError(f"{path}: thiếu mục {key!r}")
        revision = entry.get("revision")
        if not isinstance(revision, str) or not REVISION.match(revision):
            raise LockError(f"{path}: {key}.revision phải là SHA 40 hex (đang là {revision!r}) — {HINT}")
        refs[key] = ModelRef(entry["repo"], revision)
    return refs


def model_dirs(models_dir: Path, lock: Path = DEFAULT_LOCK) -> dict[str, Path]:
    """Thư mục từng model theo lock; thiếu thư mục nào → `LockError`."""
    dirs = {key: models_dir / ref.dirname for key, ref in read_lock(lock).items()}
    missing = [f"{key}: {path}" for key, path in dirs.items() if not path.is_dir()]
    if missing:
        raise LockError(f"thiếu thư mục model ({'; '.join(missing)}) — {HINT}")
    return dirs


def main(argv: list[str]) -> int:
    models_dir = Path(argv[1]) if len(argv) > 1 else Path("models")
    try:
        model_dirs(models_dir)
    except LockError as e:
        print(f"ml-service: {e}", file=sys.stderr)
        return 1
    print(f"ml-service: đủ model trong {models_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
