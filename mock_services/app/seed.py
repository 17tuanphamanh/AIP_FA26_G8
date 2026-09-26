"""Lệnh quản trị seed của mock (dùng bởi `make seed`):

    python -m app.seed validate [đường_dẫn]   # kiểm schema + tham chiếu của seed.json
    python -m app.seed reset [url]            # POST /_admin/reset (mặc định http://127.0.0.1:8100)
    python -m app.seed hash                   # đọc mật khẩu từ stdin, in hash argon2id cho seed.json
"""

import sys
from pathlib import Path

import httpx
from argon2 import PasswordHasher

from app.state import SEED_PATH, load_seed

DEFAULT_URL = "http://127.0.0.1:8100"


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"validate", "reset", "hash"}:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "validate":
        path = Path(rest[0]) if rest else SEED_PATH
        seed = load_seed(path)
        print(f"seed hợp lệ: {path} — {len(seed.users)} người dùng, {len(seed.devices)} thiết bị")
        return 0
    if cmd == "reset":
        url = (rest[0] if rest else DEFAULT_URL).rstrip("/")
        resp = httpx.post(f"{url}/_admin/reset", timeout=10)
        resp.raise_for_status()
        print(f"mock đã nạp lại seed: {resp.json()}")
        return 0
    password = sys.stdin.readline().rstrip("\n")
    if not password:
        print("mật khẩu rỗng", file=sys.stderr)
        return 2
    print(PasswordHasher().hash(password))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
