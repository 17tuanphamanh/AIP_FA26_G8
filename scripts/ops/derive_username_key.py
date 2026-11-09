"""Dẫn xuất `USERNAME_HMAC_KEY` cho worker từ `JWT_SIGNING_KEY` (A2 bn-a) — ghi THẲNG vào một file MỚI, không in khoá ra màn hình.

    PYTHONPATH=backend uv run python scripts/ops/derive_username_key.py --env-file .env --out <file-moi>
    # hoặc lấy JWT_SIGNING_KEY từ biến môi trường của shell (không có --env-file):
    PYTHONPATH=backend uv run python scripts/ops/derive_username_key.py --out <file-moi>

- Giá trị = `HMAC-SHA256(JWT_SIGNING_KEY, "auth-username-v1")` dạng 64 hex — ĐÚNG khoá backend đang dùng (`auth.username_hash.username_key`,
  một nguồn công thức) → username ma của dữ liệu hiện có không đổi khi worker chuyển sang `USERNAME_HMAC_KEY`.
- `--env-file`: đọc `JWT_SIGNING_KEY` bằng cùng bộ đọc dotenv mà `Settings` dùng (bỏ ngoặc như `.env`); không đọc biến nào khác ra ngoài.
- File đích: tạo MỚI với quyền 0600 (`O_EXCL`, `fchmod` theo fd) — đã có file (kể cả `.env`, kể cả symlink) thì dừng, không ghi đè; ghi dở
  thì xoá. Nội dung đúng một dòng `USERNAME_HMAC_KEY=<hex>` — nên đặt NGOÀI repo (vd `$TMPDIR`), chép vào `.env` rồi xoá file.
- Màn hình chỉ có đường dẫn đã ghi hoặc lý do lỗi — không khoá, không JWT. Mã thoát: 0 xong, 2 lỗi.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from app.auth.username_hash import username_key
from dotenv import dotenv_values

VAR = "JWT_SIGNING_KEY"


def _jwt(env_file: Path | None) -> str | None:
    if env_file is not None:
        value = dotenv_values(env_file).get(VAR)
    else:
        value = os.environ.get(VAR)
    return value or None  # rỗng = chưa đặt (như env_ignore_empty của Settings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="derive_username_key.py", description="Ghi USERNAME_HMAC_KEY vào một file mới")
    parser.add_argument("--out", required=True, type=Path, help="file MỚI sẽ được tạo (0600); đã tồn tại → dừng")
    parser.add_argument("--env-file", type=Path, default=None, help="đọc JWT_SIGNING_KEY từ file dotenv này thay vì biến môi trường")
    args = parser.parse_args(argv)
    if args.env_file is not None and not args.env_file.is_file():
        print(f"Lỗi: không thấy file {args.env_file}", file=sys.stderr)
        return 2
    jwt = _jwt(args.env_file)
    if jwt is None:
        print(f"Lỗi: {VAR} chưa đặt (biến môi trường hoặc --env-file) — không dẫn xuất được", file=sys.stderr)
        return 2
    line = f"USERNAME_HMAC_KEY={username_key(jwt.encode('utf-8')).hex()}\n"
    try:
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"Lỗi: {args.out} đã tồn tại — không ghi đè; chọn đường dẫn file mới", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Lỗi: không tạo được {args.out} ({type(e).__name__})", file=sys.stderr)
        return 2
    os.fchmod(fd, 0o600)  # theo fd, không theo đường dẫn (soát A2: tránh TOCTOU của chmod theo tên)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:  # ghi dở → xoá file cụt, không để lại nửa khoá
        args.out.unlink(missing_ok=True)
        print(f"Lỗi: ghi {args.out} không xong ({type(e).__name__}) — đã xoá file dở", file=sys.stderr)
        return 2
    print(f"Đã ghi USERNAME_HMAC_KEY vào {args.out} (quyền 0600) — chép dòng đó vào .env rồi xoá file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
