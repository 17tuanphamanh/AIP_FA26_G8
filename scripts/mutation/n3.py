"""Luật N3 cho script mutation (PROGRESS "Việc treo" 15, chốt 3h) — chạy TRƯỚC khi áp đột biến đầu tiên:

(a) File đích còn chữ `MUTATION` → DỪNG. Khôi phục chỉ nằm trong `finally`: SIGKILL/SIGTERM giữa chừng để lại đột biến trong
    working tree (vd tắt output guard rồi `make up` dựng image từ đó); lần chạy sau lấy md5 bản đã đột biến làm mốc "trước" nên
    không phát hiện. Mọi chuỗi thay của đột biến đều mang chữ `MUTATION` (file không có chú thích — JSON — thì chèn vào một giá
    trị chuỗi).
(b) Chạy mốc xanh MỘT lần cho mỗi lệnh test khác nhau → đỏ thì DỪNG. Không có mốc xanh, test đỏ sẵn bị tính là "giết được".

Dùng chung: `mutate_3g.py`, `mutate_3h.py`. Không đọc `.env`.
"""

import shlex
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

MARK = "MUTATION"


def leftover_marks(repo: Path, files: Iterable[str]) -> list[str]:
    return [rel for rel in sorted(set(files)) if MARK in (repo / rel).read_text(encoding="utf-8")]


def guard(repo: Path, files: Iterable[str], cmds: Iterable[Sequence[str]], env: Mapping[str, str]) -> int | None:
    """None = được chạy; 2 = dừng (đã in lý do)."""
    marked = leftover_marks(repo, files)
    if marked:
        print(f"DỪNG (N3a): file đích còn chữ {MARK!r} — đột biến sót của lần chạy trước? {marked}")
        print("  kiểm `git diff` các file trên, khôi phục bằng tay rồi chạy lại (script KHÔNG tự sửa)")
        return 2
    seen: list[tuple[str, ...]] = []
    for cmd in cmds:
        key = tuple(cmd)
        if key in seen:
            continue
        seen.append(key)
        print(f"mốc xanh (chưa đột biến): {shlex.join(cmd)}")
        out = subprocess.run(list(cmd), cwd=repo, env=dict(env), capture_output=True, text=True, timeout=1800, check=False)
        if out.returncode != 0:
            print(f"DỪNG (N3b): mốc đỏ trước khi đột biến (mã {out.returncode}) — sửa test đỏ sẵn trước")
            print("  " + "\n  ".join((out.stdout + out.stderr).strip().splitlines()[-15:]))
            return 2
    print(f"mốc xanh: {len(seen)} lệnh, đều xanh")
    return None
