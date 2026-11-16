"""Đối chiếu model intent với LLM — bước 3: tính số theo quy tắc ghi trước (`eval/doi-chieu-intent/GHI-TRUOC.md`).

  EVAL_MODE=true uv run python scripts/eval/doi_chieu_intent/phan_tich.py \
      eval/doi-chieu-intent/dau-vao.jsonl eval/doi-chieu-intent/model-ra.jsonl --out eval/doi-chieu-intent/

Ghi `ket-qua.json` và `ket-qua.md`. Không chọn ngưỡng, không đổi cấu hình theo kết quả. Không in chữ câu nào.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

from app.eval.stats import clopper_pearson_two_sided

LABELS = ("account", "vpn", "software", "access", "out_of_scope")
GOLD_LABELS = ("access", "account", "software", "vpn")
TAU = 0.75  # một ngưỡng của gói v3.1-seed42-st (MODELS.md 1.2) — chỉ dùng để đếm, nhãn chính là argmax


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def model_label(probs: Mapping[str, float]) -> str:
    if set(probs) != set(LABELS):
        raise ValueError(f"probs phải đủ đúng 5 nhãn {LABELS}, có {sorted(probs)}")
    top = max(probs.values())
    best = [k for k in LABELS if probs[k] == top]
    if len(best) != 1:
        raise ValueError(
            f"hoà điểm cao nhất giữa {best} — quy tắc ghi trước không xử lý, dừng để người xem"
        )
    return best[0]


def rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = clopper_pearson_two_sided(k, n) if n else (float("nan"), float("nan"))
    return {"k": k, "n": n, "ty_le": k / n if n else None, "ktc95": [lo, hi]}


def macro_f1(gold: Sequence[str], pred: Sequence[str]) -> float:
    """Trung bình F1 trên 4 nhãn có trong nhãn vàng; dự đoán out_of_scope tính là sai (giảm recall của lớp vàng)."""
    f1s = []
    for c in GOLD_LABELS:
        tp = sum(g == c and p == c for g, p in zip(gold, pred, strict=True))
        fp = sum(g != c and p == c for g, p in zip(gold, pred, strict=True))
        fn = sum(g == c and p != c for g, p in zip(gold, pred, strict=True))
        f1s.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return sum(f1s) / len(f1s)


def analyse(
    dau_vao: Sequence[Mapping[str, Any]],
    model_ra: Sequence[Mapping[str, Any]],
    dau_vao_sha: str,
) -> dict[str, Any]:
    dv_head, items = dau_vao[0], list(dau_vao[1:])
    mr_head, scored = model_ra[0], {r["id"]: r for r in model_ra[1:]}
    if dv_head.get("kind") != "header" or mr_head.get("kind") != "header":
        raise ValueError("thiếu dòng header")
    if mr_head["dau_vao_sha256"] != dau_vao_sha:
        raise ValueError("model-ra được chấm trên một dau-vao khác (sha lệch)")
    if set(scored) != {it["id"] for it in items} or len(scored) != len(items):
        raise ValueError("model-ra không khớp đủ các thẻ của dau-vao")
    versions = {(r["model"], r["version"]) for r in scored.values()}
    if len(versions) != 1:
        raise ValueError(f"nhiều phiên bản model trong một lượt: {sorted(versions)}")
    rows = []
    for it in items:
        s = scored[it["id"]]
        if s["text_sha256"] != it["text_sha256"]:
            raise ValueError(f"{it['id']}: sha câu lệch giữa dau-vao và model-ra")
        probs = {k: float(v) for k, v in s["probs"].items()}
        rows.append({
            "id": it["id"], "gold": it["gold_intent"], "llm_status": it["llm_status"], "llm": it["llm_intent"],
            "model": model_label(probs), "p_max": max(probs.values()),
            "n_tren_tau": sum(v >= TAU for v in probs.values()), "truncated": bool(s["truncated"]),
        })  # fmt: skip
    one = [r for r in rows if r["llm_status"] == "mot_la"]
    both = Counter((r["model"] == r["gold"], r["llm"] == r["gold"]) for r in one)
    model_name, version = next(iter(versions))
    return {
        "model": model_name, "version": version, "s1_run_id": dv_head["s1_run_id"], "app_commit": dv_head["app_commit"],
        "dau_vao_sha256": dau_vao_sha, "health": mr_head.get("health"),
        "n_the": len(rows), "trang_thai_llm": dict(Counter(r["llm_status"] for r in rows)),
        "Y_model_khop_vang_100": rate(sum(r["model"] == r["gold"] for r in rows), len(rows)),
        "Y_model_khop_vang_tap_chung": rate(sum(r["model"] == r["gold"] for r in one), len(one)),
        "X_model_khop_llm": rate(sum(r["model"] == r["llm"] for r in one), len(one)),
        "Z_llm_khop_vang": rate(sum(r["llm"] == r["gold"] for r in one), len(one)),
        "bang_cheo_tap_chung": {
            "ca_hai_dung": both[(True, True)], "chi_model_sai": both[(False, True)],
            "chi_llm_sai": both[(True, False)], "ca_hai_sai": both[(False, False)],
        },
        "macro_f1_model_100": macro_f1([r["gold"] for r in rows], [r["model"] for r in rows]),
        "model_du_doan": dict(Counter(r["model"] for r in rows)),
        "khong_nhan_nao_tren_tau": sum(r["n_tren_tau"] == 0 for r in rows),
        "tu_2_nhan_tren_tau": sum(r["n_tren_tau"] >= 2 for r in rows),
        "bi_cat_do_dai": sum(r["truncated"] for r in rows),
        "ca_lech": [r for r in rows if r["model"] != r["gold"] or (r["llm"] is not None and r["model"] != r["llm"])],
    }  # fmt: skip


def _pct(r: Mapping[str, Any]) -> str:
    lo, hi = r["ktc95"]
    return f"{r['k']}/{r['n']} = {100 * r['ty_le']:.1f}% (KTC 95% {100 * lo:.1f}–{100 * hi:.1f}%)".replace(
        ".", ","
    )


def bang_md(k: Mapping[str, Any]) -> str:
    c = k["bang_cheo_tap_chung"]
    lines = [
        "# Đối chiếu model intent với LLM trên 100 thẻ the100 — kết quả", "",
        (f"Model `{k['model']}` bản `{k['version']}`; intent LLM từ lượt S1 `{k['s1_run_id']}` (bản đo `{k['app_commit'][:7]}`); "
         f"đầu vào sha256 `{k['dau_vao_sha256'][:12]}…`. Quy tắc: `GHI-TRUOC.md`."), "",
        f"- Model khớp nhãn vàng, 100 thẻ: {_pct(k['Y_model_khop_vang_100'])}",
        f"- Model khớp nhãn vàng, tập chung {k['X_model_khop_llm']['n']} thẻ: {_pct(k['Y_model_khop_vang_tap_chung'])}",
        f"- Model khớp LLM, tập chung: {_pct(k['X_model_khop_llm'])}",
        f"- LLM khớp nhãn vàng, tập chung: {_pct(k['Z_llm_khop_vang'])}",
        (f"- Bảng chéo tập chung: cả hai đúng {c['ca_hai_dung']}, chỉ model sai {c['chi_model_sai']}, "
         f"chỉ LLM sai {c['chi_llm_sai']}, cả hai sai {c['ca_hai_sai']}"),
        f"- Macro-F1 của model trên 4 nhãn vàng, 100 thẻ: {k['macro_f1_model_100']:.4f}".replace(".", ","),
        (f"- Không nhãn nào ≥ 0,75: {k['khong_nhan_nao_tren_tau']}; từ 2 nhãn ≥ 0,75: {k['tu_2_nhan_tren_tau']}; "
         f"câu bị cắt độ dài: {k['bi_cat_do_dai']}"),
        f"- Trạng thái LLM của 100 thẻ: {k['trang_thai_llm']}", "",
        "## Các thẻ lệch", "", "| Thẻ | Nhãn vàng | LLM | Model | p cao nhất |", "|---|---|---|---|---|",
    ]  # fmt: skip
    for r in k["ca_lech"]:
        lines.append(
            f"| {r['id']} | {r['gold']} | {r['llm'] or '—'} | {r['model']} | {r['p_max']:.3f} |".replace(
                ".", ","
            )
        )
    if not k["ca_lech"]:
        lines.append("| — | | | | |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dau_vao", type=Path)
    ap.add_argument("model_ra", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    sha = hashlib.sha256(a.dau_vao.read_bytes()).hexdigest()
    k = analyse(read_jsonl(a.dau_vao), read_jsonl(a.model_ra), sha)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "ket-qua.json").write_text(
        json.dumps(k, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (a.out / "ket-qua.md").write_text(bang_md(k), encoding="utf-8")
    print(bang_md(k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
