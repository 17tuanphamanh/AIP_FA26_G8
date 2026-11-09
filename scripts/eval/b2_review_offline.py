"""Cổng 5 phần B2 ở chế độ `review`, tính OFFLINE từ lượt 17/10 (gói 1, D-52; `dac-ta-bat-2-model.md` 9.2) — Tuấn Anh chạy.

  PYTHONPATH=backend uv run python scripts/eval/b2_review_offline.py export .verify/cong5/20261017-181019/ket-qua.json \
      .verify/b2review/cong5-b2.jsonl                                   # cần stack đang chạy; CHỈ SELECT
  PYTHONPATH=ml_service uv run --group ml python scripts/eval/b2_tau_select.py score .verify/b2review/cong5-b2.jsonl \
      .verify/b2review/cong5-b2-pmal.jsonl --model-dir … --model-sha …
  PYTHONPATH=backend uv run python scripts/eval/b2_review_offline.py decide .verify/b2review/cong5-b2.jsonl \
      .verify/b2review/cong5-b2-pmal.jsonl --tau 0.9 [--recall-category [--category-file …]]

- `export`: 45 câu B2 (15 tấn công + 30 thường) theo `rows` của `ket-qua.json`; đọc Postgres qua `Shell.sql` như
  `tests/probe/cong5.py` (cùng chốt an toàn `gate3.open_ctx`; chỉ SELECT — dòng của lượt 17/10 không tạo lại được):
  `tickets.redacted_request`, `exit_code`, audit B2 (`event` → `b2_event`, `detail.screening` → `screening`). Văn bản đầu vào model = `replace_masks`
  của bản đã che (4.3). Phán quyết LLM chấm của lượt gốc chỉ suy được từ kết quả (chặn ở L4 → `is_attack` true; qua L4 → false;
  `category` của câu đã qua KHÔNG được ghi — mục 2).
- `decide`: áp `guard.b2_review.after_judge` (bảng 4.2) với τ truyền vào; câu khớp regex ở lượt gốc giữ E0; câu không có phán
  quyết L4 (E2…) giữ kết quả gốc. In tiêu chí chính + phụ kèm cận Clopper-Pearson (`cong5_score.b2_criteria`).
- `--recall-category` (mặc định TẮT; D-52 03:25 luật đo 1): gọi lại DeepSeek ĐÚNG 1 lần (prompt v1, không dự phòng — lỗi thì ghi
  lỗi) cho các câu đã qua L4, chỉ lấy `category`, giữ `is_attack` gốc, báo tỉ lệ khớp `is_attack`. Kết quả lưu ở `--category-file`
  kèm giờ, nhãn "đo bổ sung"; file có rồi → đọc, KHÔNG gọi lần hai. Khoá DeepSeek đọc từ biến môi trường (`LLM_API_KEY`), không
  in, không ghi file. LLM nhận bản đã che CHƯA thay nhãn (như lúc chạy).
Không in chữ câu nào.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

B2_KINDS = ("attack", "normal")
DEFAULT_CATEGORY_FILE = Path(".verify/b2review/category-do-bo-sung.json")
LABEL_EXTRA = "đo bổ sung"
SUSPECTED = "injection_suspected"

DB_SQL = """
SELECT coalesce(json_object_agg(t.id, json_build_object(
  'redacted_request', t.redacted_request, 'exit_code', t.exit_code,
  'b2_event', (SELECT a.event FROM audit_logs a WHERE a.ticket_id = t.id AND a.step = 'B2' ORDER BY a.log_id DESC LIMIT 1),
  'screening', (SELECT a.detail->'screening' FROM audit_logs a WHERE a.ticket_id = t.id AND a.step = 'B2'
                ORDER BY a.log_id DESC LIMIT 1)
)), '{{}}') FROM tickets t WHERE t.id IN ({ids})
"""


def _llm_is_attack(event: str | None, layer: str | None) -> bool | None:
    """Phán quyết L4 của lượt gốc, suy từ kết quả: chặn ở L4 → True; qua L4 → False; không qua L4 (regex, E2…) → None."""
    if layer != "llm":
        return None
    if event == "injection_detected":
        return True
    if event == "screened":
        return False
    return None


def build_rows(ket_qua: Mapping[str, Any], db: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    from app.guard.mask_words import replace_masks
    from app.guard.patterns import load_privacy_patterns

    patterns = load_privacy_patterns(HERE.parents[1] / "config" / "privacy_patterns.json")  # không đọc file env
    out: list[dict[str, Any]] = []
    for r in ket_qua.get("rows") or []:
        if r.get("kind") not in B2_KINDS:
            continue
        ticket = r.get("ticket")
        d = db.get(str(ticket)) or {}
        screening = d.get("screening") or {}
        layer = screening.get("layer_decided")
        text = str(d.get("redacted_request") or "")
        text_model, n = replace_masks(text, patterns) if text else ("", 0)
        out.append({
            "id": r["id"], "kind": r["kind"], "label": r["kind"], "group": r["id"], "ticket": ticket,
            "text_model": text_model, "text_llm": text, "masks_replaced": n,
            "exit_code_17": d.get("exit_code", r.get("exit_code")), "layer_17": layer,
            "llm_is_attack_17": _llm_is_attack(d.get("b2_event"), layer),
        })  # fmt: skip
    return out


def decide_rows(rows: Sequence[Mapping[str, Any]], pmal: Mapping[str, tuple[float | None, str | None]], *, tau: float,
                categories: Mapping[str, str] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    from app.guard.b2_review import after_judge

    out: list[dict[str, Any]] = []
    for r in rows:
        p, err = pmal.get(str(r["id"]), (None, None))
        attack17 = r.get("llm_is_attack_17")
        if r.get("layer_17") == "regex":
            outcome, layer = "E0", "regex"
        elif attack17 is None:
            outcome, layer = str(r.get("exit_code_17")), r.get("layer_17")  # không có phán quyết L4 — giữ kết quả gốc
        else:
            category = (categories or {}).get(str(r["id"]), "other" if attack17 else "none")
            v = after_judge("review", p_mal=p, ml_error=err, is_attack=bool(attack17), category=category, tau=tau)
            outcome, layer = v.outcome, v.layer
        out.append({**r, "p_mal": p, "ml_error": err, "outcome": outcome, "layer": layer,
                    "reason_detail": SUSPECTED if outcome == "E1" else None})  # fmt: skip
    return out


def load_or_call(path: Path, ids: Sequence[str], call: Callable[[list[str]], dict[str, Any]]) -> dict[str, Any]:
    """File có rồi → đọc, KHÔNG gọi. Chưa có → gọi đúng 1 lần, ghi kèm nhãn "đo bổ sung" và giờ."""
    if path.exists():
        return dict(json.loads(path.read_text(encoding="utf-8")))
    started = datetime.now(UTC).isoformat()
    rows = call(list(ids))
    data = {"nhan": LABEL_EXTRA, "gio_bat_dau": started, "gio_xong": datetime.now(UTC).isoformat(), "rows": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def match_rate(original: Mapping[str, bool], again: Mapping[str, bool]) -> float:
    common = [k for k in original if k in again]
    return sum(original[k] == again[k] for k in common) / len(common) if common else 0.0


def criteria(decided: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from tests.probe.cong5_score import b2_criteria

    def triples(kind: str) -> list[tuple[str, str | None, str | None]]:
        return [(str(r["id"]), r["outcome"], r["reason_detail"]) for r in decided if r["kind"] == kind]

    return b2_criteria(triples("attack"), triples("normal"))


# ---- CLI ---------------------------------------------------------------------------------------------------------------


def _cmd_export(args: argparse.Namespace, env: Mapping[str, str], echo: Callable[[str], None]) -> int:
    from b2_tau_select import require_verify_dir, write_jsonl
    from tests.stack import gate3
    from tests.stack.gate2 import StackError, q, subprocess_run

    try:
        require_verify_dir(Path(args.output))
    except ValueError as exc:
        echo(f"DỪNG: {exc}")
        return 2
    raw = Path(args.ket_qua).read_bytes()
    kq = json.loads(raw)
    tickets = [str(r["ticket"]) for r in kq.get("rows") or [] if r.get("kind") in B2_KINDS and r.get("ticket")]
    echo(f"ket-qua.json sha256 {hashlib.sha256(raw).hexdigest()} · {len(tickets)} ticket B2")
    opened = gate3.open_ctx(["preflight"], ["preflight"], run=subprocess_run, env=env, echo=echo, name="b2review",
                            require_scripted=False)  # fmt: skip
    if isinstance(opened, int):
        return opened
    _, shell, _, _ = opened
    try:
        db = dict(shell.sql(DB_SQL.format(ids=", ".join(q(t) for t in tickets))) or {})
    except StackError as exc:
        echo(f"DỪNG: {exc}")
        return 2
    rows = build_rows(kq, db)
    missing = [r["id"] for r in rows if not r["text_model"]]
    write_jsonl(Path(args.output), {"ket_qua_sha256": hashlib.sha256(raw).hexdigest(), "nguon": "lượt 17/10"}, rows)
    echo(f"export: {len(rows)} câu · thiếu văn bản {missing} · có nhãn che {sum(1 for r in rows if r['masks_replaced'])}")
    return 0


def _recall(rows: Sequence[Mapping[str, Any]], env: Mapping[str, str], echo: Callable[[str], None]) -> Callable[[list[str]], dict[str, Any]]:
    def call(ids: list[str]) -> dict[str, Any]:
        from _judge_runtime import DEEPSEEK, build_judge, load_target

        target = load_target(DEEPSEEK, env)
        judge = build_judge(target, env, max_usd=0.5)
        by = {str(r["id"]): r for r in rows}

        async def go() -> dict[str, Any]:
            try:
                return {i: await judge.one(str(by[i]["text_llm"])) for i in ids}
            finally:
                await judge.aclose()

        echo(f"--recall-category: gọi DeepSeek {len(ids)} lần (đo bổ sung)")
        return asyncio.run(go())

    return call


def _cmd_decide(args: argparse.Namespace, env: Mapping[str, str], echo: Callable[[str], None]) -> int:
    from _judge_runtime import TargetError
    from b2_tau_select import read_jsonl

    _, rows = read_jsonl(Path(args.rows))
    pmeta, prows = read_jsonl(Path(args.pmal))
    pmal = {str(p["id"]): (p.get("p_mal"), p.get("error")) for p in prows}
    categories: dict[str, str] | None = None
    if args.recall_category:
        passed = [str(r["id"]) for r in rows if r.get("llm_is_attack_17") is False]
        try:
            data = load_or_call(Path(args.category_file), passed, _recall(rows, env, echo))
        except TargetError as exc:
            echo(f"DỪNG: {exc}")
            return 2
        got = data["rows"]
        categories = {i: str(v["category"]) for i, v in got.items() if not v.get("error") and v.get("category")}
        again = {i: bool(v["is_attack"]) for i, v in got.items() if not v.get("error") and v.get("is_attack") is not None}
        errors = sorted(i for i, v in got.items() if v.get("error"))
        echo(f"đo bổ sung ({data['nhan']}, {data['gio_bat_dau']}): {len(got)} câu · lỗi {errors} · khớp is_attack "
             f"{match_rate(dict.fromkeys(passed, False), again):.4f} · category ≠ none: "
             f"{sorted(i for i, c in categories.items() if c != 'none')}")  # fmt: skip
    no_score = sorted(str(r["id"]) for r in rows if str(r["id"]) not in pmal)
    if no_score:
        echo(f"CẢNH BÁO: {len(no_score)} câu không có trong file p_mal (coi như model không chấm): {no_score}")
    decided = decide_rows(rows, pmal, tau=args.tau, categories=categories)
    res = criteria(decided)
    echo(f"τ = {args.tau} · model {pmeta.get('model_version')} · category của câu đã qua: "
         f"{'đo bổ sung' if categories is not None else 'không biết (coi là none)'}")  # fmt: skip
    for name in ("main", "secondary"):
        c = res[name]
        echo(f"{name}: tấn công {c['attack_hit']}/{c['attack_n']} (cận dưới 95% {c['attack_lo']:.4f}) · câu thường "
             f"{c['normal_hit']}/{c['normal_n']} (cận trên 95% {c['normal_hi']:.4f}) · đạt {c['pass']}"
             + (f" · {c['note']}" if "note" in c else ""))  # fmt: skip
    echo("E1 nghi: " + str(sorted(str(r["id"]) for r in decided if r["outcome"] == "E1")))
    return 0


def main(argv: Sequence[str], *, env: Mapping[str, str] = os.environ, echo: Callable[[str], None] = print) -> int:
    p = argparse.ArgumentParser(prog="b2_review_offline")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("ket_qua")
    e.add_argument("output")
    d = sub.add_parser("decide")
    d.add_argument("rows")
    d.add_argument("pmal")
    d.add_argument("--tau", type=float, required=True)
    d.add_argument("--recall-category", action="store_true")
    d.add_argument("--category-file", default=str(DEFAULT_CATEGORY_FILE))
    try:
        args = p.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)
    if args.cmd == "export":
        return _cmd_export(args, env, echo)
    return _cmd_decide(args, env, echo)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
