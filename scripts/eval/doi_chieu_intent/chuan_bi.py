"""Đối chiếu model intent với LLM trên 100 thẻ `eval/the100` — bước 1: dựng đầu vào. Chỉ để đo, không đổi hệ thống.

Đầu vào model là đúng chuỗi B3 gửi `/classify_intent` ở bản đo: `l0(redacted_request)` (`b03_classify.py`), trong đó
`redacted_request` là câu đầu của thẻ sau `RegexPrivacyGuard.redact_text`. Script phải chạy với mã che CỦA BẢN ĐO
(`bf94df2`), vì bản nộp đã siết luật che (D-89) — LLM ở lượt S1 nhìn thấy câu che theo luật cũ:

  git worktree add --detach ../wt-bf94 bf94df2
  PYTHONPATH=../wt-bf94/backend uv run python scripts/eval/doi_chieu_intent/chuan_bi.py \
      --app-root ../wt-bf94 --s1 <goi-ket-qua>/s1 --out eval/doi-chieu-intent/dau-vao.jsonl

Intent của LLM lấy từ `predictions.jsonl` lượt S1 (`95b5a579ec7e`, chiến lược hybrid, gói kết quả của Dương). Thẻ không có
intent LLM giữ trong file với `llm_status` nói lý do. Không in chữ câu ra màn hình.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

EXPECT_COMMIT = "bf94df2"
S1_RUN_ID = "95b5a579ec7e"
COMPANY_DOMAINS = (
    "congty-abc.vn",
)  # mặc định settings ở bf94df2; không câu đầu nào của the100 có "@"
STATUS = ("mot_la", "dung_o_b2", "tach_nhieu_y", "khong_chay")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load_cards(cards_dir: Path, expect_n: int = 100) -> list[dict[str, Any]]:
    cards = [
        yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in sorted(cards_dir.glob("*.yaml"))
    ]
    if len(cards) != expect_n:
        raise ValueError(f"{cards_dir}: cần {expect_n} thẻ, có {len(cards)}")
    for c in cards:
        if not isinstance(c["turns"][0], str):
            raise TypeError(f"{c['id']}: lượt đầu phải là câu của người dùng")
        if len(c["gold"]["intents"]) != 1:
            raise ValueError(f"{c['id']}: khung này chỉ cho thẻ một ý")
    return cards


def llm_view(
    predictions: Path, outcomes: Path, run_id: str = S1_RUN_ID
) -> dict[str, tuple[str, str | None]]:
    """scenario_id → (llm_status, intent LLM). Thẻ không có dòng trong predictions xét theo outcomes."""
    preds = [
        json.loads(line)
        for line in predictions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs = {p["run_id"] for p in preds}
    if runs != {run_id}:
        raise ValueError(f"predictions không phải lượt {run_id}: {sorted(runs)}")
    view: dict[str, tuple[str, str | None]] = {}
    for p in preds:
        if p["scenario_id"] in view:
            raise ValueError(
                f"{p['scenario_id']}: nhiều lá — khung này chỉ cho thẻ một lá"
            )
        view[p["scenario_id"]] = (
            ("mot_la", p["intent"]) if p["intent"] else ("dung_o_b2", None)
        )
    for line in outcomes.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        sid = o["scenario_id"]
        if sid in view and view[sid][0] != "khong_chay":
            continue
        view[sid] = (
            ("tach_nhieu_y", None)
            if o["outcome"] == "multi_leaf"
            else ("khong_chay", None)
        )
    return view


def build_rows(
    cards: Sequence[Mapping[str, Any]],
    redact: Callable[[str], str],
    view: Mapping[str, tuple[str, str | None]],
) -> list[dict[str, Any]]:
    rows = []
    for c in cards:
        text = redact(c["turns"][0])
        status, intent = view.get(c["id"], ("khong_chay", None))
        rows.append({
            "id": c["id"], "family": c["family"], "text": text, "text_sha256": sha256_text(text),
            "gold_intent": c["gold"]["intents"][0], "llm_status": status, "llm_intent": intent,
        })  # fmt: skip
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--app-root",
        type=Path,
        required=True,
        help="bản checkout bf94df2 (đã đặt PYTHONPATH=<nó>/backend)",
    )
    ap.add_argument(
        "--s1",
        type=Path,
        required=True,
        help="thư mục lượt chạy có predictions.jsonl, outcomes.jsonl (đợt 1: s1 của gói kết quả)",
    )
    ap.add_argument("--run-id", default=S1_RUN_ID, help="đợt 2: run_id lượt đo bổ sung")
    ap.add_argument(
        "--cards",
        type=Path,
        help="mặc định <app-root>/eval/the100; đợt 2: thẻ bộ mới đã khoá",
    )
    ap.add_argument("--expect-n", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    head = subprocess.run(
        ["git", "-C", str(a.app_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    if not head.stdout.startswith(EXPECT_COMMIT):
        raise SystemExit(f"--app-root phải ở {EXPECT_COMMIT}, đang ở {head.stdout[:7]}")
    from app.guard.normalize import l0
    from app.guard.patterns import privacy_patterns
    from app.guard.privacy import RegexPrivacyGuard

    if (
        not Path(sys.modules["app"].__file__ or "")
        .resolve()
        .is_relative_to(a.app_root.resolve())
    ):
        raise SystemExit(
            "gói `app` không lấy từ --app-root — đặt PYTHONPATH=<app-root>/backend"
        )
    guard = RegexPrivacyGuard(privacy_patterns(a.app_root / "config"), COMPANY_DOMAINS)

    def redact(text: str) -> str:
        return l0(guard.redact_text(text).text)  # như B3: l0(redacted_request)

    cards = load_cards(a.cards or a.app_root / "eval" / "the100", a.expect_n)
    view = llm_view(a.s1 / "predictions.jsonl", a.s1 / "outcomes.jsonl", a.run_id)
    rows = build_rows(cards, redact, view)
    header = {
        "kind": "header", "app_commit": head.stdout.strip(), "s1_run_id": a.run_id,
        "s1_predictions_sha256": sha256_file(a.s1 / "predictions.jsonl"),
        "s1_outcomes_sha256": sha256_file(a.s1 / "outcomes.jsonl"), "n": len(rows),
    }  # fmt: skip
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8") as f:
        for r in [header, *rows]:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    count = {s: sum(r["llm_status"] == s for r in rows) for s in STATUS}
    print(
        f"{len(rows)} thẻ → {a.out} (sha256 {sha256_file(a.out)[:12]}…); trạng thái LLM: {count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
