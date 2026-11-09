"""Sinh `MANIFEST.sha256` cho thư mục model của nhóm (gói 1, D-52; phase5 §6.5 #9; `dac-ta-bat-2-model.md` 4.7).

  uv run python scripts/ml/make_manifest.py ml_models/injection-clf/v3-seed123

Mỗi dòng `<sha256>  <đường/tương/đối>` như `sha256sum` (hai dấu cách, `/`), sắp theo đường dẫn; KHÔNG liệt kê chính
`MANIFEST.sha256`. Có symlink → từ chối (ml-service cũng cấm). Ghi file vào thư mục rồi in SHA-256 của chính manifest
(→ `GUARD_MANIFEST_SHA256`) và của `model.safetensors` nếu có (→ `GUARD_MODEL_SHA256`). Cả hai không phải bí mật.
ml-service kiểm lúc khởi động: đúng SHA manifest, đúng tập file, đúng SHA từng file (`ml_service/app/guard.py`).
"""

import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

MANIFEST_FILE = "MANIFEST.sha256"  # khớp `ml_service/app/guard.py` MANIFEST_FILE
WEIGHTS_FILE = "model.safetensors"


def _sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def build_manifest(model_dir: Path) -> str:
    d = Path(model_dir)
    links = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_symlink())
    if links:
        raise ValueError(f"{d}: có symlink {links} — ml-service từ chối symlink, bỏ đi rồi chạy lại")
    rels = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())
    lines = [f"{_sha(d / rel)}  {rel}" for rel in rels if rel != MANIFEST_FILE]
    if not lines:
        raise ValueError(f"{d}: không có file nào")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1 or not Path(argv[0]).is_dir():
        print("dùng: uv run python scripts/ml/make_manifest.py <thư mục model>")
        return 2
    d = Path(argv[0])
    try:
        text = build_manifest(d)
    except ValueError as exc:
        print(f"DỪNG: {exc}")
        return 2
    data = text.encode("utf-8")
    (d / MANIFEST_FILE).write_bytes(data)
    print(f"đã ghi {d / MANIFEST_FILE} ({len(text.splitlines())} file)")
    print(f"GUARD_MANIFEST_SHA256={hashlib.sha256(data).hexdigest()}")
    if (d / WEIGHTS_FILE).is_file():
        print(f"GUARD_MODEL_SHA256={_sha(d / WEIGHTS_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
