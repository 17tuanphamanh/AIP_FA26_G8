"""Đợt 1b (GHI-TRUOC.md mục 7): dựng đầu vào 45 câu intent của cổng 5 từ lượt `.verify/cong5/20261017-181019`.

Chuỗi đưa model = `l0(redacted_request)` lấy từ `tickets.csv` của lượt đó (đúng chuỗi B3 nhận lúc chạy); nhãn LLM là cột
`labels` của `ket-qua.json` (do `cong5_score.predict` ghi lúc chạy, cũng là nguồn của macro-F1 0,9399). Chạy với `l0` của bản đo:

  PYTHONPATH=../wt-bf94/backend uv run python scripts/eval/doi_chieu_intent/chuan_bi_cong5.py \
      --luot .verify/cong5/20261017-181019 --out eval/doi-chieu-intent/dau-vao-cong5.jsonl
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

LUOT = "cong5-20261017-181019"


def build_rows(
    ket_qua: Mapping[str, Any],
    tickets: Mapping[str, Mapping[str, str]],
    norm: Callable[[str], str],
) -> list[dict[str, Any]]:
    rows = []
    for r in ket_qua["rows"]:
        if r.get("kind") != "intent":
            continue
        text = norm(tickets[r["ticket"]]["redacted_request"] or "")
        labs = list(r.get("labels") or [])
        status, llm = (
            ("mot_la", labs[0])
            if len(labs) == 1
            else ("khong_nhan" if not labs else "nhieu_nhan", None)
        )
        rows.append({
            "id": r["id"], "family": r["id"].rsplit("-", 1)[0], "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "gold_intent": r["gold"],
            "llm_status": status, "llm_intent": llm,
        })  # fmt: skip
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--luot",
        type=Path,
        required=True,
        help="thư mục lượt cổng 5 (ket-qua.json, tickets.csv)",
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    from app.guard.normalize import l0

    csv.field_size_limit(10**8)
    kq_bytes = (a.luot / "ket-qua.json").read_bytes()
    with (a.luot / "tickets.csv").open(encoding="utf-8", newline="") as f:
        tickets = {t["ticket_id"]: t for t in csv.DictReader(f)}
    rows = build_rows(json.loads(kq_bytes), tickets, l0)
    head = {
        "kind": "header", "app_commit": "bf94df2(l0)", "s1_run_id": LUOT, "n": len(rows),
        "ket_qua_sha256": hashlib.sha256(kq_bytes).hexdigest(),
        "tickets_sha256": hashlib.sha256((a.luot / "tickets.csv").read_bytes()).hexdigest(),
    }  # fmt: skip
    with a.out.open("w", encoding="utf-8") as f:
        for x in [head, *rows]:
            f.write(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{len(rows)} câu → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
