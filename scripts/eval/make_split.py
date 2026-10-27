"""Sinh `eval/SPLIT.md` + CSV phần cho `offline.py` từ CÙNG một lần chia (P8 v1.5 §4.3; `app.eval.split.make_folds`).

Chạy SAU khi khoá nhãn, trên thư mục CHỈ chứa thẻ đo (bộ phát triển D1/D2 không được nằm trong đó — D-59):

  EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/make_split.py \\
      [--scenarios eval/scenarios] [--seed-file mock_services/seed.json] [--split eval/SPLIT.md] --csv <file.csv> [--locked]

Không ghi đè file đã có (`x`). Log CHỈ số đếm (số file, số kịch bản, số họ, cỡ từng phần) — không tên họ, không id, không sha.
Mã thoát: 0 xong; 2 dữ liệu không chia được hoặc file đầu ra đã có (dòng `LỖI: …`).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app.eval.dataset import DatasetError
from app.eval.predictions import CV_K
from app.eval.split import SplitError, build_split
from app.eval.stats import SEED

REPO = Path(__file__).resolve().parents[2]
OK, FAIL = 0, 2


def _write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Chia kiểm tra chéo theo họ → SPLIT.md + CSV (P8 §4.3)"
    )
    ap.add_argument("--scenarios", type=Path, default=REPO / "eval" / "scenarios")
    ap.add_argument(
        "--seed-file", type=Path, default=REPO / "mock_services" / "seed.json"
    )
    ap.add_argument("--split", type=Path, default=REPO / "eval" / "SPLIT.md")
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--k", type=int, default=CV_K)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument(
        "--locked", action="store_true", help="ghi locked: true (lượt khoá nhãn)"
    )
    args = ap.parse_args(argv)
    if args.split.exists() or args.csv.exists():
        print("LỖI: file đầu ra đã có — không ghi đè", file=sys.stderr)
        return FAIL
    try:
        result = build_split(
            args.scenarios, args.seed_file, k=args.k, seed=args.seed, locked=args.locked
        )
    except DatasetError as e:
        print(
            f"LỖI: nạp kịch bản: {len(e.issues)} lỗi (chạy harness --per-case để xem)",
            file=sys.stderr,
        )
        return FAIL
    except (SplitError, ValueError) as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return FAIL
    _write_new(args.split, result.split_md)
    _write_new(args.csv, result.csv)
    sizes = ", ".join(f"phần {i}: {n}" for i, n in result.fold_sizes.items())
    print(f"split: files={result.n_files} kich_ban={result.n_scenarios} ho={len(result.folds)} k={args.k} "
          f"locked={'true' if args.locked else 'false'} | {sizes}")  # fmt: skip
    return OK


if __name__ == "__main__":
    sys.exit(main())
