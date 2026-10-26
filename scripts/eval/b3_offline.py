"""Số offline của B3 với gói `intent-clf` gốc (gói 1, D-53; `dac-ta-bat-2-model.md` 6.1) — Tuấn Anh chạy 19/10. Chỉ để đo.

  PYTHONPATH=backend uv run python scripts/eval/b3_offline.py export .verify/cong5/20261017-181019/ket-qua.json .verify/b2review/b3.jsonl
  PYTHONPATH=backend uv run python scripts/eval/b3_offline.py mask-prepare INTENT_VAL.jsonl .verify/b2review/b3-mask.jsonl
  uv run --group ml python scripts/eval/b3_offline.py score .verify/b2review/b3.jsonl .verify/b2review/b3-score.jsonl \
      --model-dir ml_models/intent-clf/v3.1-seed42 --pt-sha <64 hex> --code ml_models/intent-clf/intent_inference.py
  uv run python scripts/eval/b3_offline.py report .verify/b2review/b3.jsonl .verify/b2review/b3-score.jsonl [--f11 f11.csv]
  uv run python scripts/eval/b3_offline.py mask-report .verify/b2review/b3-mask.jsonl .verify/b2review/b3-mask-score.jsonl

- `export` (backend, cần stack, CHỈ SELECT như `tests/probe/cong5.py`): 45 câu intent + 10 câu nhiều ý của lượt 17/10; nhãn LLM
  = `cong5_score.predict` (audit B3/B4/B5 + `side_effects.child_create`); đầu vào model = `l0(redacted_request)` (như
  `b03_classify.py`).
- `score` (nhóm uv `ml`, tiến trình riêng): kiểm SHA-256 ĐẦY ĐỦ của `seed_42.pt` TRƯỚC mọi `torch.load`; torch ≥ 2.6 (mặc định
  `weights_only`); `device="cpu"` (autocast tắt — file gốc chỉ bật fp16 khi CUDA); nạp `intent_inference.py` từ `--code`. Đầu file
  kết quả ghi `pt_sha256` và `code_sha256` (biên bản ghi đúng mã đã chạy — Q-B2R-12). Điểm = `predict_proba` của gói (điểm trộn).
- `report`: chỉ model (ngưỡng 0,75) / chỉ LLM / cascade (c) mô phỏng (kèm % câu xuống LLM) / phủ quyết chéo mô phỏng (LLM sai bị
  chặn / LLM đúng bị chặn). `--f11`: bảng giao Duy Anh CHỈ 4 cột `id, intent_dung, intent_llm, diem_model` (D-43 — không có
  status, exit_code, outcome hay bất cứ gì từ B6 trở đi).
- `mask-prepare` + `score` + `mask-report` (tiêu chí ghi trước ở D-53): chèn PII giả → L1 thật → 3 bản `orig` (câu gốc, chỉ L0) /
  `keep` (giữ nhãn che) / `replace` (thay bằng bộ từ 4.3); báo macro-F1 trên câu có nhãn che và tỉ lệ dự đoán giữ nguyên so với
  bản `orig`.
Không chọn gì theo bảng này (trừ phép đo nhãn che có tiêu chí ghi trước). Không in chữ câu nào.
"""

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

LABELS = ("account", "vpn", "software", "access", "out_of_scope")
TAU_SINGLE = 0.75
# D-44 cấu hình (c) (`dac-ta-bat-2-model.md` 6.2): τ_hi = max(τ_hi P11, τ_lo P11, 0,75); τ_lo = min(τ_hi P11, τ_lo P11)
TAU_HI = {"account": 0.75, "vpn": 0.75, "software": 0.905, "access": 0.75, "out_of_scope": 0.82}
TAU_LO = {"account": 0.027, "vpn": 0.365, "software": 0.085, "access": 0.156, "out_of_scope": 0.372}
F11_COLUMNS = ["id", "intent_dung", "intent_llm", "diem_model"]
MIN_TORCH = (2, 6)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
B3_KINDS = ("intent", "multi")
VARIANTS = ("orig", "keep", "replace")
PT_FILE = "seed_42.pt"

EXPORT_SQL = """
SELECT coalesce(json_object_agg(t.id, json_build_object(
  'redacted_request', t.redacted_request, 'exit_code', t.exit_code,
  'audit', (SELECT coalesce(json_agg(json_build_object('step', a.step, 'event', a.event, 'intent', a.intent) ORDER BY a.log_id), '[]')
            FROM audit_logs a WHERE a.ticket_id = t.id AND a.step IN ('B3', 'B4', 'B5')),
  'children', (SELECT coalesce(json_agg(s.result_ref ORDER BY s.created_at), '[]') FROM side_effects s
               WHERE s.ticket_id = t.id AND s.kind = 'child_create')
)), '{{}}') FROM tickets t WHERE t.id IN ({ids})
"""


# ---- SHA, torch (trước mọi torch.load) -------------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def verify_sha(path: Path, expected: str) -> str:
    want = expected.strip().lower()
    if not SHA_RE.match(want):
        raise ValueError("SHA-256 phải đủ 64 ký tự hex (bản rút gọn không dùng được)")
    got = sha256_of(Path(path))
    if got != want:
        raise ValueError(f"SHA-256 của {Path(path).name} ({got[:12]}…) lệch giá trị đã cho ({want[:12]}…) — không nạp")
    return got


def require_torch(version: str) -> None:
    m = re.match(r"^(\d+)\.(\d+)", version)
    if m is None or (int(m.group(1)), int(m.group(2))) < MIN_TORCH:
        raise RuntimeError(f"cần torch ≥ {MIN_TORCH[0]}.{MIN_TORCH[1]} (torch.load mặc định weights_only) — đang {version}")


def load_checkpoint(path: Path, sha: str, *, loader: Callable[[], Any]) -> Any:
    """Kiểm SHA ĐẦY ĐỦ rồi mới gọi `loader` (hàm có `torch.load`). Lệch → ValueError, `loader` không chạy."""
    verify_sha(path, sha)
    return loader()


# ---- Bảng (thuần) ----------------------------------------------------------------------------------------------------


def _gold_set(gold: Any) -> frozenset[str]:
    if isinstance(gold, str):
        return frozenset([gold])
    return frozenset(str(g) for g in gold or ())


def model_labels(probs: Mapping[str, float], tau: float = TAU_SINGLE) -> frozenset[str]:
    """Như `IntentClassifier.decode`: nhãn có p ≥ τ; không nhãn nào → nhãn p lớn nhất."""
    picked = frozenset(lbl for lbl in LABELS if probs.get(lbl, 0.0) >= tau)
    return picked or frozenset([max(LABELS, key=lambda lbl: probs.get(lbl, 0.0))])


def cascade_c(probs: Mapping[str, float], llm: frozenset[str]) -> tuple[frozenset[str], bool]:
    """Cascade (c) mô phỏng: nhãn p ≥ τ_hi → có; ≤ τ_lo → không; giữa → hỏi LLM. Trả (nhãn, có xuống LLM)."""
    out, asked = set(), False
    for lbl in LABELS:
        p = probs.get(lbl, 0.0)
        if p >= TAU_HI[lbl]:
            out.add(lbl)
        elif p > TAU_LO[lbl]:
            asked = True
            if lbl in llm:
                out.add(lbl)
    return (frozenset(out) or llm), asked


def macro_f1(pairs: Sequence[tuple[frozenset[str], frozenset[str]]]) -> float:
    f1s = []
    for lbl in LABELS:
        tp = sum(1 for g, p in pairs if lbl in g and lbl in p)
        fp = sum(1 for g, p in pairs if lbl not in g and lbl in p)
        fn = sum(1 for g, p in pairs if lbl in g and lbl not in p)
        f1s.append(2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0)
    return sum(f1s) / len(f1s)


def _block(pairs: Sequence[tuple[frozenset[str], frozenset[str]]]) -> dict[str, Any]:
    return {"n": len(pairs), "macro_f1": macro_f1(pairs) if pairs else None,
            "exact": sum(g == p for g, p in pairs) / len(pairs) if pairs else None}  # fmt: skip


def tables(rows: Sequence[Mapping[str, Any]], *, tau: float = TAU_SINGLE) -> dict[str, Any]:
    """`rows`: `{id, kind, gold, llm_labels, probs}`."""
    m, llm, cas, asked = [], [], [], 0
    veto_wrong = veto_right = 0
    for r in rows:
        g, lab, probs = _gold_set(r["gold"]), frozenset(r.get("llm_labels") or ()), r["probs"]
        m.append((g, model_labels(probs, tau)))
        llm.append((g, lab))
        c, a = cascade_c(probs, lab)
        cas.append((g, c))
        asked += a
        vetoed = any(probs.get(lbl, 0.0) <= TAU_LO[lbl] for lbl in lab)  # model "chắc không" ở nhãn LLM chọn
        if vetoed:
            veto_wrong += lab != g
            veto_right += lab == g
    return {
        "model_only": _block(m), "llm_only": _block(llm),
        "cascade_c": {**_block(cas), "to_llm_rate": asked / len(rows) if rows else None},
        "cross_veto": {"llm_wrong_blocked": veto_wrong, "llm_right_blocked": veto_right,
                       "llm_wrong": sum(g != p for g, p in llm)},
    }  # fmt: skip


def f11_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bảng giao Duy Anh (F11) — D-43: CHỈ 4 cột."""
    out = []
    for r in rows:
        probs = r.get("probs") or {}
        out.append({
            "id": r["id"], "intent_dung": "+".join(sorted(_gold_set(r["gold"]))),
            "intent_llm": "+".join(sorted(r.get("llm_labels") or ())),
            "diem_model": json.dumps({lbl: round(float(probs.get(lbl, 0.0)), 6) for lbl in LABELS}),
        })  # fmt: skip
    return out


def mask_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`rows`: `{id, gold, variant ∈ orig|keep|replace, has_mask, probs | pred}` → macro-F1 trên câu có nhãn che + tỉ lệ giữ nguyên."""
    by: dict[str, dict[str, Mapping[str, Any]]] = {}
    for r in rows:
        by.setdefault(str(r["id"]), {})[str(r["variant"])] = r

    def pred(r: Mapping[str, Any]) -> frozenset[str]:
        return frozenset(r["pred"]) if "pred" in r else model_labels(r["probs"])

    out: dict[str, Any] = {}
    for v in ("keep", "replace"):
        masked = [x for x in by.values() if v in x and x[v].get("has_mask", True)]
        pairs = [(_gold_set(x[v]["gold"]), pred(x[v])) for x in masked]
        same = [pred(x[v]) == pred(x["orig"]) for x in masked if "orig" in x]
        out[f"macro_f1_{v}"] = macro_f1(pairs) if pairs else None
        out[f"kept_rate_{v}"] = sum(same) / len(same) if same else None
        out[f"n_{v}"] = len(pairs)
    return out


# ---- I/O -------------------------------------------------------------------------------------------------------------


def _read(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from b2_tau_select import read_jsonl

    return read_jsonl(path)


def _write(path: Path, meta: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> None:
    from b2_tau_select import write_jsonl

    write_jsonl(path, meta, rows)


def _cmd_export(args: argparse.Namespace, env: Mapping[str, str], echo: Callable[[str], None]) -> int:
    from app.guard.normalize import l0
    from b2_tau_select import require_verify_dir
    from tests.probe.cong5_score import predict
    from tests.stack import gate3
    from tests.stack.gate2 import StackError, q, subprocess_run

    try:
        require_verify_dir(Path(args.output))
    except ValueError as exc:
        echo(f"DỪNG: {exc}")
        return 2
    raw = Path(args.ket_qua).read_bytes()
    kq = json.loads(raw)
    items = [r for r in kq.get("rows") or [] if r.get("kind") in B3_KINDS and r.get("ticket")]
    opened = gate3.open_ctx(["preflight"], ["preflight"], run=subprocess_run, env=env, echo=echo, name="b3offline",
                            require_scripted=False)  # fmt: skip
    if isinstance(opened, int):
        return opened
    _, shell, _, _ = opened
    try:
        db = dict(shell.sql(EXPORT_SQL.format(ids=", ".join(q(str(r["ticket"])) for r in items))) or {})
    except StackError as exc:
        echo(f"DỪNG: {exc}")
        return 2
    rows = []
    for r in items:
        d = db.get(str(r["ticket"])) or {}
        p = predict(list(d.get("audit") or []), list(d.get("children") or []), d.get("exit_code"))
        rows.append({"id": r["id"], "kind": r["kind"], "gold": r["gold"], "llm_labels": list(p.labels),
                     "text_model": l0(str(d.get("redacted_request") or ""))})  # fmt: skip
    _write(Path(args.output), {"ket_qua_sha256": hashlib.sha256(raw).hexdigest(), "nguon": "lượt 17/10"}, rows)
    echo(f"export: {len(rows)} câu ({sum(r['kind'] == 'intent' for r in rows)} intent, {sum(r['kind'] == 'multi' for r in rows)} nhiều ý)")
    return 0


def _cmd_mask_prepare(args: argparse.Namespace, echo: Callable[[str], None]) -> int:
    from _pii_fake import insert_pii, l0_only, redact
    from app.guard.mask_words import replace_masks
    from app.guard.patterns import load_privacy_patterns
    from b2_judge_compare import flags
    from b2_tau_select import require_verify_dir

    try:
        require_verify_dir(Path(args.output))
    except ValueError as exc:
        echo(f"DỪNG: {exc}")
        return 2
    patterns = load_privacy_patterns(HERE.parents[1] / "config" / "privacy_patterns.json")  # không đọc file env
    raw = Path(args.input).read_bytes()
    out = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        it = json.loads(line)
        iid = str(it["id"])
        gold = it.get("labels", it.get("label"))
        masked = redact(insert_pii(str(it["text"]), seed=20261018, item_id=iid)).text
        has = flags(masked)["has_mask"]
        for variant, text in (("orig", l0_only(str(it["text"]))), ("keep", masked), ("replace", replace_masks(masked, patterns)[0])):
            out.append({"id": iid, "gold": gold, "variant": variant, "has_mask": has, "text_model": text})
    _write(Path(args.output), {"input_sha256": hashlib.sha256(raw).hexdigest()}, out)
    echo(f"mask-prepare: {len(out) // 3} câu × 3 bản → {args.output}")
    return 0


def _cmd_score(args: argparse.Namespace, echo: Callable[[str], None]) -> int:
    model_dir, code = Path(args.model_dir), Path(args.code)
    pt = model_dir / PT_FILE
    code_sha = sha256_of(code)
    cfg_path = model_dir / "inference_config.json"
    try:
        model_files = json.loads(cfg_path.read_text(encoding="utf-8")).get("model_files")
    except (OSError, ValueError):
        model_files = None
    if model_files != [PT_FILE]:  # mã gốc torch.load theo danh sách này — chỉ cho đúng file đã kiểm SHA
        echo(f"DỪNG: {cfg_path.name}: model_files phải đúng [{PT_FILE!r}] (file đã kiểm SHA)")
        return 2
    cfg_sha = sha256_of(cfg_path)

    def loader() -> Any:
        import torch

        require_torch(torch.__version__)
        spec = importlib.util.spec_from_file_location("_intent_inference_goc", code)
        if spec is None or spec.loader is None:
            raise RuntimeError("không nạp được --code")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.IntentClassifier(str(model_dir), device="cpu"), torch.__version__

    try:
        clf, torch_version = load_checkpoint(pt, args.pt_sha, loader=loader)
    except (ValueError, RuntimeError) as exc:
        echo(f"DỪNG: {exc}")
        return 2
    meta, rows = _read(Path(args.rows))
    probs, _ = clf.predict_proba([r["text_model"] for r in rows])
    scored = [{**{k: v for k, v in r.items() if k != "text_model"}, "probs": dict(zip(clf.labels, map(float, p), strict=True))}
              for r, p in zip(rows, probs, strict=True)]  # fmt: skip
    pt_sha = args.pt_sha.strip().lower()
    _write(Path(args.output), {"pt_sha256": pt_sha, "code_sha256": code_sha, "config_sha256": cfg_sha, "torch": torch_version,
                               "device": "cpu",
                               "rows_meta": meta}, scored)  # fmt: skip
    echo(f"score: {len(scored)} câu · pt_sha256 {pt_sha} · code_sha256 {code_sha} · config_sha256 {cfg_sha} · torch {torch_version} · cpu")
    return 0


def _cmd_report(args: argparse.Namespace, echo: Callable[[str], None]) -> int:
    meta, rows = _read(Path(args.score))
    res = tables(rows)
    echo(f"pt_sha256 {meta.get('pt_sha256')} · code_sha256 {meta.get('code_sha256')}")
    for k, v in res.items():
        echo(f"{k}: {v}")
    if args.f11:
        with Path(args.f11).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=F11_COLUMNS)
            w.writeheader()
            w.writerows(f11_rows(rows))
        echo(f"F11: {args.f11} (4 cột {F11_COLUMNS})")
    return 0


def _cmd_mask_report(args: argparse.Namespace, echo: Callable[[str], None]) -> int:
    meta, rows = _read(Path(args.score))
    echo(f"pt_sha256 {meta.get('pt_sha256')} · code_sha256 {meta.get('code_sha256')}")
    res = mask_report(rows)
    echo(json.dumps(res, ensure_ascii=False))
    if res["macro_f1_keep"] is not None and res["macro_f1_replace"] is not None:
        gain = res["macro_f1_replace"] - res["macro_f1_keep"]
        echo(f"bản thay hơn {gain * 100:.2f} điểm macro-F1 — tiêu chí D-53: ≥ 2 điểm thì bật bước thay ở B3 → {'ĐẠT' if gain >= 0.02 else 'KHÔNG ĐẠT'}")
    return 0


def main(argv: Sequence[str], *, env: Mapping[str, str] = os.environ, echo: Callable[[str], None] = print) -> int:
    p = argparse.ArgumentParser(prog="b3_offline")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("ket_qua")
    e.add_argument("output")
    mp = sub.add_parser("mask-prepare")
    mp.add_argument("input")
    mp.add_argument("output")
    s = sub.add_parser("score")
    s.add_argument("rows")
    s.add_argument("output")
    s.add_argument("--model-dir", required=True)
    s.add_argument("--pt-sha", required=True)
    s.add_argument("--code", required=True)
    r = sub.add_parser("report")
    r.add_argument("rows")
    r.add_argument("score")
    r.add_argument("--f11")
    mr = sub.add_parser("mask-report")
    mr.add_argument("rows")
    mr.add_argument("score")
    try:
        args = p.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)
    if args.cmd == "export":
        return _cmd_export(args, env, echo)
    cmds: dict[str, Callable[[argparse.Namespace, Callable[[str], None]], int]] = {
        "mask-prepare": _cmd_mask_prepare, "score": _cmd_score, "report": _cmd_report, "mask-report": _cmd_mask_report,
    }  # fmt: skip
    return cmds[args.cmd](args, echo)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
