"""Đo bổ sung RQ1 (16/11/2026) — bước 6: phân tích. Lớp LLM có tách được ca tự xử lý được (nhãn AUTO) với ca cần người (HITL,
ESCALATE_L2) không? Đọc `predictions.jsonl` + `manifest.json` của lượt harness; KHÔNG hiệu chỉnh, KHÔNG gọi LLM, KHÔNG đọc DB.

  EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/bo_sung_rq1/phan_tich.py \
      --moi RUN/predictions.jsonl RUN/manifest.json --khoa eval/bo-sung-rq1/KHOA.md \
      [--cu S1/predictions.jsonl S1/manifest.json] --out <thư mục MỚI ngoài repo>

Phép đo ghi trước ở `eval/bo-sung-rq1/GHI-TRUOC.md` mục 5–6:
- Mẫu = lá đã nhãn, có route, `decided_by = llm`, có `raw_prob` (p "cần người" = tỉ lệ phiếu của 5 lần hỏi, sampling_k5). Lá bị loại
  được đếm theo lý do, không đoán.
- CHÍNH: AUC của p thô, dương = nhãn khác AUTO; KTC 95% bootstrap theo họ (bộ mới: họ = tình huống), 2.000 lần, hạt giống 20260925.
  Đọc: cận dưới > 0,5 → "có tín hiệu"; cận trên < 0,5 → "ngược chiều"; còn lại → "chưa thấy tín hiệu". Một lớp < 5 lá → "không đủ dữ
  liệu" (không đọc AUC).
- PHỤ: bảng p × nhãn; điểm vận hành KHÔNG hiệu chỉnh "tự xử lý khi p ≤ c và không thiếu căn cứ (kb_gap)" với c ∈ {0; 0,2}: số ca AUTO
  được tự xử lý và số tình huống cần người bị tự xử lý (bỏ sót) kèm Clopper–Pearson; gộp với lượt S1 cũ (`--cu`) và báo riêng từng bộ.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

from app.eval.predictions import PredictionRecord, load_predictions
from app.eval.stats import (
    BOOTSTRAP_N,
    SEED,
    clopper_pearson_two_sided,
    family_bootstrap_ci,
)
from app.risk.decision_math import auc, clopper_pearson_upper

PROB_METHOD = "sampling_k5"
MIN_MOI_LOP = 5  # GHI-TRUOC mục 5: dưới 5 lá ở một lớp → không đọc AUC
NGUONG_VAN_HANH = (0.0, 0.2)
MUC_P = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


class Dung(Exception):
    pass


@dataclass(frozen=True)
class Luot:
    ten: str
    records: tuple[PredictionRecord, ...]
    manifest: Mapping[str, Any]
    sha_pred: str


def doc_luot(ten: str, pred: Path, mf: Path) -> Luot:
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    records = tuple(load_predictions(pred))
    if manifest.get("strategy") != "hybrid":
        raise Dung(f"{ten}: manifest strategy ≠ hybrid")
    if (manifest.get("config") or {}).get("prob_method") != PROB_METHOD:
        raise Dung(f"{ten}: prob_method ≠ {PROB_METHOD}")
    if manifest.get("enable_proactive_diagnosis") is not True:
        raise Dung(f"{ten}: lượt phải bật chẩn đoán chủ động như S1")
    if any(r.run_id != manifest.get("run_id") for r in records):
        raise Dung(f"{ten}: run_id trong predictions khác manifest")
    return Luot(ten, records, manifest, hashlib.sha256(pred.read_bytes()).hexdigest())


def doc_khoa(path: Path) -> str:
    m = re.search(
        r"^dataset_sha256:\s*([0-9a-f]{64})\s*$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if m is None:
        raise Dung("KHOA.md: không thấy dataset_sha256")
    return m.group(1)


def kiem_cung_cau_hinh(moi: Luot, cu: Luot) -> list[str]:
    """Khác biệt cấu hình giữa lượt mới và S1 cũ — báo là LỆCH (không dừng, trừ policy). Policy khác → dừng: lớp LLM chỉ nhận ca không
    luật nào khớp, đổi luật là đổi mẫu."""
    if moi.manifest.get("policy_sha256") != cu.manifest.get("policy_sha256"):
        raise Dung("policy_sha256 lượt mới khác S1 cũ — không cùng bộ luật")
    lech = []
    for key in ("llm_cache_mode", "clf_mode", "llm_backend", "timeout_s"):
        if moi.manifest.get(key) != cu.manifest.get(key):
            lech.append(
                f"{key}: mới={moi.manifest.get(key)!r} cũ={cu.manifest.get(key)!r}"
            )
    if (moi.manifest.get("config") or {}).get("llm_roles") != (
        cu.manifest.get("config") or {}
    ).get("llm_roles"):
        lech.append("config.llm_roles khác (model LLM theo vai)")
    return lech


def chon_mau(
    records: Sequence[PredictionRecord],
) -> tuple[list[PredictionRecord], Counter[str]]:
    loai: Counter[str] = Counter()
    mau: list[PredictionRecord] = []
    for r in records:
        if r.expected_route is None:
            loai["chua_nhan"] += 1
        elif r.route is None:
            loai["khong_toi_m5_bi_ngat" if r.m5_aborted else "khong_toi_m5"] += 1
        elif r.decided_by != "llm":
            loai["luat_quyet"] += 1
        elif r.raw_prob is None:
            loai["llm_khong_co_p"] += 1
        elif r.p_method != PROB_METHOD:
            raise Dung(f"{r.scenario_id}: p_method ≠ {PROB_METHOD}")
        else:
            mau.append(r)
    return mau, loai


def can_nguoi(r: PredictionRecord) -> bool:
    return r.expected_route != "AUTO"


def auc_or_none(rs: Sequence[PredictionRecord]) -> float | None:
    y = [can_nguoi(r) for r in rs]
    if all(y) or not any(y):
        return None
    return auc([float(r.raw_prob) for r in rs if r.raw_prob is not None], y)


def doc_ket_luan(lo: float | None, hi: float | None, n_pos: int, n_neg: int) -> str:
    if n_pos < MIN_MOI_LOP or n_neg < MIN_MOI_LOP:
        return "không đủ dữ liệu"
    if lo is None or hi is None:
        return "không xác định"
    if lo > 0.5:
        return "có tín hiệu"
    if hi < 0.5:
        return "ngược chiều"
    return "chưa thấy tín hiệu"


def nhan_khop_tu_dau(the_dir: Path) -> dict[str, bool]:
    """{scenario_id: hai người gán khớp ngay từ đầu} — đọc `labels` của thẻ đã khoá (GHI-TRUOC mục 6, độ nhạy theo nhãn)."""
    import yaml

    out: dict[str, bool] = {}
    for path in sorted(the_dir.glob("*.yaml")):
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        lab = d.get("labels") or {}
        out[str(d["id"])] = lab.get("annotator_1") is not None and lab.get(
            "annotator_1"
        ) == lab.get("annotator_2")
    return out


def muc_p(p: float) -> float:
    return min(MUC_P, key=lambda m: abs(m - p))


def danh_gia(
    ten: str, rs: Sequence[PredictionRecord], tinh_huong: Mapping[str, str] | None
) -> dict[str, Any]:
    n_pos = sum(can_nguoi(r) for r in rs)
    n_neg = len(rs) - n_pos
    ci = (
        family_bootstrap_ci(rs, auc_or_none, n_boot=BOOTSTRAP_N, seed=SEED)
        if rs
        else None
    )
    out: dict[str, Any] = {
        "bo": ten, "n_la": len(rs), "n_can_nguoi": n_pos, "n_auto": n_neg, "n_ho": len({r.family for r in rs}),
        "auc": ci.point if ci else None, "auc_ktc95": [ci.lo, ci.hi] if ci else [None, None],
        "bootstrap": {"n_boot": BOOTSTRAP_N, "seed": SEED, "n_dung": ci.n_used if ci else 0, "n_khong_xac_dinh": ci.n_undefined if ci else 0},
        "doc": doc_ket_luan(ci.lo if ci else None, ci.hi if ci else None, n_pos, n_neg),
    }  # fmt: skip
    bang = Counter(
        (muc_p(float(r.raw_prob)), r.expected_route)
        for r in rs
        if r.raw_prob is not None
    )
    out["bang_p"] = [
        {"p": m, **{g: bang[(m, g)] for g in ("AUTO", "HITL", "ESCALATE_L2")}}
        for m in MUC_P
    ]
    key = (
        (lambda r: tinh_huong.get(r.scenario_id, r.family))
        if tinh_huong
        else (lambda r: r.family)
    )
    van_hanh = []
    for c in NGUONG_VAN_HANH:
        tu_dong = [
            r
            for r in rs
            if r.raw_prob is not None and r.raw_prob <= c + 1e-9 and not r.kb_gap
        ]
        auto_dung = sum(1 for r in tu_dong if not can_nguoi(r))
        units: dict[str, list[PredictionRecord]] = {}
        for r in rs:
            units.setdefault(key(r), []).append(r)
        th_can = [u for u in units.values() if any(can_nguoi(r) for r in u)]
        bo_sot = sum(1 for u in th_can if any(can_nguoi(r) and r in tu_dong for r in u))
        lo_a, hi_a = (
            clopper_pearson_two_sided(auto_dung, n_neg) if n_neg else (None, None)
        )
        van_hanh.append({
            "nguong_p": c, "auto_duoc_tu_xu_ly": auto_dung, "n_auto": n_neg, "ty_le_auto": auto_dung / n_neg if n_neg else None,
            "auto_ktc95": [lo_a, hi_a], "tinh_huong_can_nguoi": len(th_can), "bo_sot": bo_sot,
            "bo_sot_ty_le": bo_sot / len(th_can) if th_can else None,
            "bo_sot_can_tren95_1phia": clopper_pearson_upper(bo_sot, len(th_can)) if th_can else None,
        })  # fmt: skip
    out["van_hanh"] = van_hanh
    return out


def bang_md(kq: Mapping[str, Any]) -> str:
    m = kq["luot_moi"]
    nguon = (
        f"Lượt mới: run `{m['run_id']}`, dataset `{m['dataset_sha256'][:12]}…`, commit `{str(m['git_commit'])[:7]}`, "
        f"predictions sha256 `{m['predictions_sha256'][:12]}…`."
    )
    lines = [
        "# Đo bổ sung RQ1 — lớp LLM có tách ca tự xử lý được với ca cần người không",
        "",
        nguon,
        "",
    ]
    if kq.get("lech_cau_hinh"):
        lines += [
            "**Lệch cấu hình so với S1 cũ:** " + "; ".join(kq["lech_cau_hinh"]),
            "",
        ]
    lines += [
        "| Bộ | Lá | Cần người | AUTO | Họ | AUC | KTC 95% | Đọc |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for d in kq["ket_qua"]:
        lo, hi = d["auc_ktc95"]
        f = lambda x: "—" if x is None else f"{x:.3f}".replace(".", ",")
        lines.append(
            f"| {d['bo']} | {d['n_la']} | {d['n_can_nguoi']} | {d['n_auto']} | {d['n_ho']} | {f(d['auc'])} | [{f(lo)}; {f(hi)}] | {d['doc']} |"
        )
    lines += [
        "",
        "Lá bị loại (bộ mới): "
        + (", ".join(f"{k} {v}" for k, v in sorted(kq["loai_moi"].items())) or "0"),
        "",
    ]
    for d in kq["ket_qua"]:
        lines += [
            f"## {d['bo']}",
            "",
            "| p thô | AUTO | HITL | ESCALATE_L2 |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {r['p']:.1f} | {r['AUTO']} | {r['HITL']} | {r['ESCALATE_L2']} |".replace(
                ".", ","
            )
            for r in d["bang_p"]
        ]
        lines += ["", "| Tự xử lý khi p ≤ | AUTO được tự xử lý | Tình huống cần người bị tự xử lý | Cận trên 95% một phía |",
                  "|---|---|---|---|"]  # fmt: skip
        for v in d["van_hanh"]:
            ct = (
                "—"
                if v["bo_sot_can_tren95_1phia"] is None
                else f"{v['bo_sot_can_tren95_1phia']:.3f}".replace(".", ",")
            )
            lines.append(
                f"| {v['nguong_p']:.1f} | {v['auto_duoc_tu_xu_ly']}/{v['n_auto']} | {v['bo_sot']}/{v['tinh_huong_can_nguoi']} | {ct} |".replace(
                    "0.", "0,"
                )
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Đo bổ sung RQ1 — phân tích AUC lớp LLM")
    ap.add_argument(
        "--moi", nargs=2, type=Path, required=True, metavar=("PREDICTIONS", "MANIFEST")
    )
    ap.add_argument("--khoa", type=Path, required=True)
    ap.add_argument("--tinh-huong", type=Path, default=None)
    ap.add_argument(
        "--the",
        type=Path,
        default=None,
        help="thư mục thẻ đã khoá — để tính độ nhạy theo nhãn (khớp từ đầu)",
    )
    ap.add_argument(
        "--cu", nargs=2, type=Path, default=None, metavar=("PREDICTIONS", "MANIFEST")
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.out.exists():
            raise Dung("--out đã tồn tại — cần thư mục mới")
        moi = doc_luot("mới", *a.moi)
        if moi.manifest.get("dataset_sha256") != doc_khoa(a.khoa):
            raise Dung(
                "dataset_sha256 của lượt khác KHOA.md — lượt không chạy trên bộ đã khoá"
            )
        th = (
            json.loads(a.tinh_huong.read_text(encoding="utf-8"))
            if a.tinh_huong
            else None
        )
        mau_moi, loai_moi = chon_mau(moi.records)
        ket = [danh_gia("Bộ mới (chính)", mau_moi, th)]
        if a.the is not None:
            khop = nhan_khop_tu_dau(a.the)
            thieu = {r.scenario_id for r in mau_moi} - khop.keys()
            if thieu:
                raise Dung(f"--the: thiếu {len(thieu)} thẻ của lượt")
            ket.append(
                danh_gia(
                    "Bộ mới — nhãn khớp từ đầu (độ nhạy)",
                    [r for r in mau_moi if khop[r.scenario_id]],
                    th,
                )
            )
        lech: list[str] = []
        luot_cu = None
        if a.cu:
            cu = doc_luot("cũ", *a.cu)
            lech = kiem_cung_cau_hinh(moi, cu)
            mau_cu, loai_cu = chon_mau(cu.records)
            if {r.family for r in mau_cu} & {r.family for r in mau_moi}:
                raise Dung("họ trùng giữa bộ mới và bộ cũ")
            ket += [
                danh_gia("S1 cũ (tham khảo)", mau_cu, None),
                danh_gia("Gộp mới + cũ (phụ)", [*mau_moi, *mau_cu], th),
            ]
            luot_cu = {
                "run_id": cu.manifest.get("run_id"),
                "predictions_sha256": cu.sha_pred,
                "loai": dict(loai_cu),
            }
        kq = {"luot_moi": {"run_id": moi.manifest.get("run_id"), "dataset_sha256": moi.manifest.get("dataset_sha256"),
                           "git_commit": moi.manifest.get("git_commit"), "predictions_sha256": moi.sha_pred,
                           "llm_roles": (moi.manifest.get("config") or {}).get("llm_roles")},
              "luot_cu": luot_cu, "lech_cau_hinh": lech, "loai_moi": dict(loai_moi), "ket_qua": ket}  # fmt: skip
        a.out.mkdir(parents=True)
        (a.out / "ket-qua.json").write_text(
            json.dumps(kq, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (a.out / "bang.md").write_text(bang_md(kq), encoding="utf-8")
        with (a.out / "chi-tiet.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                (
                    "bo",
                    "scenario_id",
                    "family",
                    "expected_route",
                    "raw_prob",
                    "kb_gap",
                    "route",
                )
            )
            for r in mau_moi:
                w.writerow(
                    (
                        "moi",
                        r.scenario_id,
                        r.family,
                        r.expected_route,
                        r.raw_prob,
                        r.kb_gap,
                        r.route,
                    )
                )
        d = ket[0]
        lo, hi = d["auc_ktc95"]
        print(f"bộ mới: {d['n_la']} lá ({d['n_can_nguoi']} cần người / {d['n_auto']} AUTO) · AUC "
              f"{d['auc'] if d['auc'] is None else round(d['auc'], 3)} [{lo if lo is None else round(lo, 3)}; {hi if hi is None else round(hi, 3)}] → {d['doc']}")  # fmt: skip
        print(
            "loại: "
            + (", ".join(f"{k} {v}" for k, v in sorted(loai_moi.items())) or "0")
        )
        if lech:
            print("LỆCH CẤU HÌNH: " + "; ".join(lech))
    except (Dung, ValueError) as e:
        print(f"DỪNG: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
