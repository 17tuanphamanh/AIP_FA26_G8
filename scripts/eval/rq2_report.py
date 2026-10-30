"""RQ2 (Phase 11) — báo cáo offline từ thư mục run của `rq2_collect.py` (không DB, không mạng):

  EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/rq2_report.py results/rq2/<run_id> \\
      [--b5-csv <a.csv>,<b.csv> [--b5-col <cột>]] [--now 2026-11-01T00:00:00+07:00]

Ghi vào chính thư mục run: per_ticket.csv, tables.md, metrics.json, reliability_<cách>_<raw|cal>.png/.svg, manifest.json.
`--b5-csv`: các file 25 giá trị self_report của B5 (ngoài repo, KHÔNG commit) — chỉ mô tả độ phân giải (a). stdout chỉ có số đếm.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rq2_report.py", description="RQ2 — hiệu chỉnh kiểm tra chéo + chỉ số + hình")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--b5-csv", default=None, help="đường dẫn CSV B5, cách nhau bằng dấu phẩy")
    p.add_argument("--b5-col", default=None)
    p.add_argument("--now", default=None, help="ISO 8601 có múi giờ — vào version calibrator (tái lập)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if os.environ.get("EVAL_MODE", "").strip().lower() != "true":
        print("DỪNG: EVAL_MODE phải là true", file=sys.stderr)
        return 2
    from app.eval.rq2.report import describe_b5, write_report

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.utcoffset() is None:
        print("DỪNG: --now thiếu múi giờ", file=sys.stderr)
        return 2
    try:
        rows = [json.loads(line) for line in (args.run_dir / "collected.jsonl").read_text(encoding="utf-8").splitlines() if line]
        collect_manifest = json.loads((args.run_dir / "manifest_collect.json").read_text(encoding="utf-8"))
        b5 = describe_b5([Path(p) for p in args.b5_csv.split(",")], args.b5_col) if args.b5_csv else None
    except (OSError, ValueError) as e:
        print(f"LỖI: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    manifest = write_report(args.run_dir, rows, collect_manifest, now=now, b5=b5)
    rep = manifest["report"]
    print(f"rows={len(rows)} methods={','.join(rep['methods'])} figures={len(rep['figures'])} n_boot={rep['n_boot']} "
          f"b5_files={0 if b5 is None else len(b5)}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
