"""Đo bổ sung RQ1 (16/11/2026) — bước 2–4: phiếu gán nhãn → gộp nhãn → dựng thẻ YAML. Chỉ đọc/ghi file, không mạng, không stack.

  # 2. Từ phiếu viết đã điền → phiếu gán nhãn mù (thứ tự xáo trộn, không có tên người viết)
  (bước 3, 4 import app.eval → cần EVAL_MODE=true trước lệnh, như mọi script eval)
  uv run python scripts/eval/bo_sung_rq1/dung_the.py phieu-gan --khung K/khung.csv --viet viet.xlsx --out <thư mục MỚI>
  # 3. Hai bài gán → κ + danh sách ca lệch (để phân xử) → nhãn cuối khi có file phân xử
  uv run python scripts/eval/bo_sung_rq1/dung_the.py gop-nhan --phieu P/ --a A.xlsx --b B.xlsx [--phan-xu px.csv] --out <thư mục MỚI>
  # 4. Dựng thẻ vào eval/bo-sung-rq1/the/ + tinh-huong.json + KHOA.md (mã băm), rồi tự kiểm bằng rule_coverage + dataset loader
  uv run python scripts/eval/bo_sung_rq1/dung_the.py the --khung K/khung.csv --phieu P/ --nhan N/nhan-cuoi.json --out eval/bo-sung-rq1

Quy tắc ghi trước: `eval/bo-sung-rq1/GHI-TRUOC.md`. Mã thoát: 0 xong; 2 dừng (dữ liệu thiếu/sai — không ghi gì).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import khung as kh

NHAN = ("AUTO", "HITL", "ESCALATE_L2")
TEN_SHEET_VIET = "Viết thẻ"
TEN_SHEET_GAN = "Gán nhãn"
HAT_GIONG_XAO = 20261117
TEXT_MAX = 4000
# Thứ tự slot cho `on_question_about` (harness gửi câu trả lời THEO THỨ TỰ lần hỏi, slot chỉ để đọc — G2-Q19).
SLOT_THEO_LOAI: Mapping[str, tuple[str, ...]] = {
    "account": ("account_type", "action", "target_corrected"),
    "access": ("resource_path", "permission_level", "duration"),
    "vpn": ("device_id", "action", "target_corrected"),
    "software": ("software_name", "device_id", "action"),
}
TAI_LIEU = {"reset_password": "KB-ACC-001", "unlock_account": "KB-ACC-002", "view_permissions": "KB-ACS-005",
            "grant_permission": "KB-ACS-001", "extend_permission": "KB-ACS-003", "install_software": "KB-SW-001",
            "renew_vpn_cert": "KB-VPN-004", "reissue_vpn_access": "KB-VPN-004"}  # = procedure_doc ở action_metadata.yaml  # fmt: skip


class Dung(Exception):
    """Dừng có lý do (mã 2)."""


def sach(text: object) -> str:
    """Chuẩn hoá ô chữ: NFC, gộp khoảng trắng, bỏ đầu/cuối. Ô rỗng → ""."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text))).strip()


def doc_khung(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or set(kh.COT_KHUNG) - set(rows[0]):
        raise Dung("khung.csv: thiếu cột")
    return {r["ma"]: r for r in rows}


def doc_phieu_viet(path: Path) -> dict[str, dict[str, Any]]:
    """{mã: {cau_dau, tra_loi: [..], khong_tu_nhien: bool}} từ sheet "Viết thẻ" (cột theo tên tiêu đề, không theo vị trí)."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    if TEN_SHEET_VIET not in wb.sheetnames:
        raise Dung(f"phiếu viết: không có sheet '{TEN_SHEET_VIET}'")
    rows = list(wb[TEN_SHEET_VIET].iter_rows(values_only=True))
    head = [sach(h) for h in rows[0]]
    need = ("Mã", "Câu đầu", "Trả lời 1", "Trả lời 2", "Trả lời 3", "Không tự nhiên")
    if any(h not in head for h in need):
        raise Dung("phiếu viết: thiếu cột tiêu đề")
    idx = {h: head.index(h) for h in need}
    out: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        ma = sach(row[idx["Mã"]] if idx["Mã"] < len(row) else None)
        if not ma:
            continue
        if ma in out:
            raise Dung(f"phiếu viết: mã {ma} lặp")
        cell = {k: sach(row[i] if i < len(row) else None) for k, i in idx.items()}
        out[ma] = {"cau_dau": cell["Câu đầu"], "tra_loi": [t for t in (cell["Trả lời 1"], cell["Trả lời 2"], cell["Trả lời 3"]) if t],
                   "khong_tu_nhien": cell["Không tự nhiên"].lower() in ("x", "có", "co", "1", "yes")}  # fmt: skip
    return out


def chon(
    khung: Mapping[str, Mapping[str, str]], viet: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Mã tình huống vào bộ (GHI-TRUOC mục 3): mỗi nhóm lấy đủ chỉ tiêu — dòng chính không đánh dấu "không tự nhiên", thiếu thì lấy
    dòng dự phòng CÙNG NHÓM theo thứ tự mã đã viết câu. Dòng được chọn phải có câu đầu; thiếu chỉ tiêu → dừng."""
    chosen: list[str] = []
    for nhom in sorted(kh.CHI_TIEU):
        can = sum(kh.CHI_TIEU[nhom].values())
        chinh = [
            m
            for m, r in sorted(khung.items())
            if r["vai_tro"] == "chính" and r["nhom"] == nhom
        ]
        du = [
            m
            for m, r in sorted(khung.items())
            if r["vai_tro"] == "dự phòng" and r["nhom"] == nhom
        ]
        lay = [m for m in chinh if m in viet and not viet[m]["khong_tu_nhien"]]
        for m in lay:
            if not viet[m]["cau_dau"]:
                raise Dung(f"{m}: chưa có câu đầu (hoặc đánh 'x' ở 'Không tự nhiên')")
        for m in du:
            if len(lay) >= can:
                break
            if m in viet and viet[m]["cau_dau"] and not viet[m]["khong_tu_nhien"]:
                lay.append(m)
        if len(lay) < can:
            raise Dung(
                f"nhóm {nhom}: mới có {len(lay)}/{can} tình huống viết xong — viết thêm dòng dự phòng cùng nhóm"
            )
        chosen += lay[:can]
    for m in chosen:
        for t in (viet[m]["cau_dau"], *viet[m]["tra_loi"]):
            if len(t) > TEXT_MAX:
                raise Dung(f"{m}: câu dài quá {TEXT_MAX} ký tự")
    return chosen


def nguoi_dung_noi(v: Mapping[str, Any]) -> str:
    parts = [f"Câu đầu: {v['cau_dau']}"] + [
        f"Nếu được hỏi lại ({i}): {t}" for i, t in enumerate(v["tra_loi"], 1)
    ]
    return "\n".join(parts)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---- bước 2 ---------------------------------------------------------------------------------------------------------------


def phieu_gan(khung_p: Path, viet_p: Path, out: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.worksheet import Worksheet

    khung, viet = doc_khung(khung_p), doc_phieu_viet(viet_p)
    chosen = chon(khung, viet)
    s = kh.SeedGoc(REPO / "mock_services" / "seed.json")
    order = list(chosen)
    random.Random(HAT_GIONG_XAO).shuffle(order)
    out.mkdir(parents=True)
    wb = Workbook()
    hd = wb.active
    assert isinstance(hd, Worksheet)  # Workbook() mới luôn có đúng 1 sheet thường
    hd.title = "Hướng dẫn"
    for i, t in enumerate(
        (
            "Phiếu gán nhãn — đo bổ sung RQ1. Đọc eval/bo-sung-rq1/HUONG-DAN-GAN.md trước khi gán.",
            "Nhãn: AUTO / HITL / ESCALATE_L2 (chọn trong ô). Lý do: 'Câu <số>, <dấu hiệu>: <dữ kiện cụ thể>' — câu 1 → ESCALATE_L2, câu 2 → HITL, câu 3 → AUTO.",
            "Tự gán, không dùng AI, không trao đổi với người gán kia trước khi cả hai nộp, không mở repo/tài liệu luật.",
        ),
        start=1,
    ):
        hd.cell(i, 1, t).alignment = Alignment(wrap_text=True)
    hd.column_dimensions["A"].width = 120
    ws = wb.create_sheet(TEN_SHEET_GAN)
    head = (
        "id",
        "Người gửi",
        "Thời điểm",
        "Người dùng nói",
        "Hành động",
        "Dữ kiện",
        "Nhãn",
        "Lý do",
        "Mơ hồ",
    )
    for j, h in enumerate(head, 1):
        ws.cell(1, j, h).font = Font(bold=True)
    dv = DataValidation(
        type="list",
        formula1='"AUTO,HITL,ESCALATE_L2"',
        allow_blank=True,
        showErrorMessage=True,
    )
    ws.add_data_validation(dv)
    for i, m in enumerate(order, 2):
        r = khung[m]
        vals = (
            m,
            s.ten(r["nguoi_gui"]),
            "Thứ Tư 18/11, 10:00 (trong giờ hành chính)",
            nguoi_dung_noi(viet[m]),
            r["viec"],
            r["du_kien_chu"],
        )
        for j, v in enumerate(vals, 1):
            ws.cell(i, j, v).alignment = Alignment(wrap_text=True, vertical="top")
        dv.add(ws.cell(i, 7))
    for col, w in zip("ABCDEFGHI", (8, 34, 22, 55, 45, 50, 15, 45, 25), strict=True):
        ws.column_dimensions[col].width = w
    wb.save(out / "phieu-gan.xlsx")
    (out / "chon.json").write_text(json.dumps({"chon": chosen, "thu_tu_phieu": order, "khung_sha256": sha256_file(khung_p),
                                               "viet_sha256": sha256_file(viet_p)}, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")  # fmt: skip
    dem = Counter(khung[m]["nhom"] for m in chosen)
    print(
        f"tình huống: {len(chosen)} · "
        + " · ".join(f"{k} {v}" for k, v in sorted(dem.items()))
    )
    print(
        f"dự phòng dùng: {sum(1 for m in chosen if khung[m]['vai_tro'] == 'dự phòng')}"
    )
    print(f"phieu-gan.xlsx sha256 {sha256_file(out / 'phieu-gan.xlsx')}")


# ---- bước 3 ---------------------------------------------------------------------------------------------------------------


def doc_bai_gan(path: Path, ids: Sequence[str]) -> dict[str, str]:
    """{id: nhãn} từ sheet "Gán nhãn". Thiếu/thừa id, nhãn ngoài tập, ô nhãn trống → dừng."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    if TEN_SHEET_GAN not in wb.sheetnames:
        raise Dung(f"{path.name}: không có sheet '{TEN_SHEET_GAN}'")
    rows = list(wb[TEN_SHEET_GAN].iter_rows(values_only=True))
    head = [sach(h) for h in rows[0]]
    if "id" not in head or "Nhãn" not in head:
        raise Dung(f"{path.name}: thiếu cột id / Nhãn")
    i_id, i_nhan = head.index("id"), head.index("Nhãn")
    got: dict[str, str] = {}
    for row in rows[1:]:
        rid = sach(row[i_id] if i_id < len(row) else None)
        if not rid:
            continue
        nhan = sach(row[i_nhan] if i_nhan < len(row) else None).upper()
        if nhan not in NHAN:
            raise Dung(
                f"{path.name}: {rid} nhãn trống hoặc ngoài AUTO/HITL/ESCALATE_L2"
            )
        if rid in got:
            raise Dung(f"{path.name}: {rid} lặp")
        got[rid] = nhan
    if set(got) != set(ids):
        raise Dung(
            f"{path.name}: thiếu {len(set(ids) - set(got))} id, thừa {len(set(got) - set(ids))} id so với phiếu phát"
        )
    return got


def gop_nhan(
    phieu: Path, a_p: Path, b_p: Path, phan_xu: Path | None, out: Path
) -> None:
    from app.eval.stats import agreement

    meta = json.loads((phieu / "chon.json").read_text(encoding="utf-8"))
    ids = list(meta["chon"])
    a, b = doc_bai_gan(a_p, ids), doc_bai_gan(b_p, ids)
    ag = agreement([a[i] for i in ids], [b[i] for i in ids])
    k = ag.kappa
    lech = sorted(i for i in ids if a[i] != b[i])
    out.mkdir(parents=True)
    with (out / "lech.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("id", "nhan_a", "nhan_b", "nhan_phan_xu"))
        for i in lech:
            w.writerow((i, a[i], b[i], ""))
    ket: dict[str, Any] = {"n": len(ids), "kappa": float(k.value) if k.value is not None else None, "dong_y_tho": float(ag.po), "pabak": float(ag.pabak), "ket_luan": str(ag.verdict),
           "so_ca_lech": len(lech), "a_sha256": sha256_file(a_p), "b_sha256": sha256_file(b_p)}  # fmt: skip
    if phan_xu is not None:
        with phan_xu.open(encoding="utf-8", newline="") as fh:
            px = {
                sach(r["id"]): sach(r["nhan_phan_xu"]).upper()
                for r in csv.DictReader(fh)
            }
        thieu = [i for i in lech if px.get(i) not in NHAN]
        if thieu:
            raise Dung(f"phân xử: {len(thieu)} ca lệch chưa có nhãn hợp lệ")
        cuoi = {i: (a[i] if a[i] == b[i] else px[i]) for i in ids}
        ket |= {"phan_xu_sha256": sha256_file(phan_xu), "nhan_cuoi": cuoi, "annotator_1": a, "annotator_2": b,
                "dem": dict(sorted(Counter(cuoi.values()).items()))}  # fmt: skip
        (out / "nhan-cuoi.json").write_text(
            json.dumps(ket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (out / "kappa.json").write_text(json.dumps({k2: v for k2, v in ket.items() if k2 not in ("nhan_cuoi", "annotator_1", "annotator_2")},
                                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")  # fmt: skip
    print(f"κ = {ket['kappa']:.3f} · đồng ý thô {ket['dong_y_tho']:.3f} · n {len(ids)} · lệch {len(lech)}" if ket["kappa"] is not None
          else f"κ không xác định · n {len(ids)} · lệch {len(lech)}")  # fmt: skip
    if phan_xu is not None:
        print("nhãn cuối: " + " · ".join(f"{k2} {v}" for k2, v in ket["dem"].items()))


# ---- bước 4 ---------------------------------------------------------------------------------------------------------------


def dung_mot_the(
    r: Mapping[str, str], v: Mapping[str, Any], nhan: str, a: str, b: str
) -> dict[str, Any]:
    ma, loai = r["ma"], r["loai"]
    turns: list[Any] = [v["cau_dau"]]
    slots = SLOT_THEO_LOAI[loai]
    turns += [
        {"on_question_about": slots[min(i, len(slots) - 1)], "reply": t}
        for i, t in enumerate(v["tra_loi"])
    ]
    turns.append({"on_confirm": True})
    nguoi = kh.SeedGoc(REPO / "mock_services" / "seed.json").users[r["nguoi_gui"]]
    return {
        "id": f"{ma}-q1", "family": ma, "source": "bo_sung_rq1",
        "requester": {"user_id": r["nguoi_gui"], "role": "employee", "dept": str(nguoi["department"]).lower(),
                      "tenure_days": int(nguoi["hired_days_ago"])},
        "at": r["at"], "faults": [], "turns": turns,
        "gold": {"intents": [kh.INTENT[loai]], "need_type": "action", "expected_route": nhan, "expected_exit": None,
                 "approver_decision": "reject", "gold_doc_ids": [TAI_LIEU[r["hanh_dong"]]],
                 "action": {"type": r["hanh_dong"], "target": r["doi_tuong"], "requested_for": r["lam_ho"], "params": json.loads(r["tham_so"])},
                 "facts": json.loads(r["du_kien"])},
        "labels": {"annotator_1": a, "annotator_2": b},
    }  # fmt: skip


def kiem_the(thu_muc: Path) -> list[str]:
    """Tự kiểm sau khi dựng: (1) rule_coverage — mọi thẻ `none` (đi lớp LLM), 0 lỗi, 0 cảnh báo lệch seed; (2) dataset loader của
    harness nạp đủ, đủ nhãn. Trả danh sách lỗi (rỗng = đạt)."""
    import rule_coverage as rc
    from app.eval.dataset import load_scenarios, load_seed_users

    loi: list[str] = []
    policy = rc.load_policy(REPO / "config" / "policy.json")
    meta = rc.load_action_metadata(REPO / "config" / "action_metadata.yaml")
    cfg = rc.Config(
        rules=policy.rules,
        hours=policy.business_hours,
        metadata=meta.root,
        intents=rc.intents_of_actions(meta),
    )
    seed = rc.Seed(REPO / "mock_services" / "seed.json")
    for path in sorted(thu_muc.glob("*.yaml")):
        res = rc.evaluate_scenario(path, seed, cfg)
        if res.decision != "none":
            loi.append(f"{path.name}: rule_coverage = {res.decision} {res.rule_id}")
        loi += [f"{path.name}: {w}" for w in res.warnings]
    ds = load_scenarios(
        thu_muc, users=load_seed_users(REPO / "mock_services" / "seed.json")
    )
    if any(not sc.labelled for sc in ds.scenarios):
        loi.append("có thẻ chưa nhãn")
    return loi


def dung_bo_the(
    khung_p: Path, phieu: Path, nhan_p: Path, viet_p: Path, out: Path
) -> None:
    from app.eval.dataset import dataset_sha256, file_sha256

    khung = doc_khung(khung_p)
    meta = json.loads((phieu / "chon.json").read_text(encoding="utf-8"))
    if meta["khung_sha256"] != sha256_file(khung_p) or meta[
        "viet_sha256"
    ] != sha256_file(viet_p):
        raise Dung(
            "khung.csv hoặc phiếu viết khác bản đã dùng để phát phiếu gán (chon.json)"
        )
    viet = doc_phieu_viet(viet_p)
    nhan = json.loads(nhan_p.read_text(encoding="utf-8"))
    ids = list(meta["chon"])
    if set(nhan["nhan_cuoi"]) != set(ids):
        raise Dung("nhan-cuoi.json không khớp danh sách tình huống")
    the_dir = out / "the"
    if the_dir.exists():
        raise Dung(f"{the_dir} đã có — không ghi đè bộ đã khoá")
    the_dir.mkdir(parents=True)
    tinh_huong: dict[str, str] = {}
    for m in sorted(ids):
        card = dung_mot_the(
            khung[m],
            viet[m],
            nhan["nhan_cuoi"][m],
            nhan["annotator_1"][m],
            nhan["annotator_2"][m],
        )
        (the_dir / f"{m}-q1.yaml").write_text(
            yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=1000),
            encoding="utf-8",
        )
        tinh_huong[f"{m}-q1"] = m
    loi = kiem_the(the_dir)
    pairs = [
        (p.name, file_sha256(p.read_bytes())) for p in sorted(the_dir.glob("*.yaml"))
    ]
    (out / "tinh-huong.json").write_text(
        json.dumps(tinh_huong, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = ["# KHOÁ bộ thẻ đo bổ sung RQ1", "", "Sinh bởi `scripts/eval/bo_sung_rq1/dung_the.py the`. Không sửa tay — sửa thẻ thì dựng lại và commit lại.",
             "", "```yaml", f"dataset_sha256: {dataset_sha256(pairs)}", f"so_the: {len(pairs)}",
             f"nhan: {json.dumps(dict(sorted(Counter(nhan['nhan_cuoi'].values()).items())), ensure_ascii=False)}",
             f"kappa: {nhan.get('kappa')}", f"khung_sha256: {meta['khung_sha256']}", f"viet_sha256: {meta['viet_sha256']}",
             f"nhan_sha256: {sha256_file(nhan_p)}", f"tinh_huong_sha256: {sha256_file(out / 'tinh-huong.json')}", "files:"]  # fmt: skip
    lines += [f"  {name}: {sha}" for name, sha in pairs]
    lines += ["```", ""]
    (out / "KHOA.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"thẻ: {len(pairs)} · dataset_sha256 {dataset_sha256(pairs)}")
    if loi:
        print(f"KIỂM: {len(loi)} lỗi — KHÔNG được chạy bộ này:")
        for x in loi:
            print("  " + x)
        raise Dung("tự kiểm không đạt")
    print(
        "KIỂM: rule_coverage 100% đi lớp LLM, 0 cảnh báo seed; dataset loader nạp đủ, đủ nhãn"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Đo bổ sung RQ1 — phiếu gán, gộp nhãn, dựng thẻ"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("phieu-gan")
    p1.add_argument("--khung", type=Path, required=True)
    p1.add_argument("--viet", type=Path, required=True)
    p1.add_argument("--out", type=Path, required=True)
    p2 = sub.add_parser("gop-nhan")
    p2.add_argument("--phieu", type=Path, required=True)
    p2.add_argument("--a", type=Path, required=True)
    p2.add_argument("--b", type=Path, required=True)
    p2.add_argument("--phan-xu", type=Path, default=None)
    p2.add_argument("--out", type=Path, required=True)
    p3 = sub.add_parser("the")
    p3.add_argument("--khung", type=Path, required=True)
    p3.add_argument("--phieu", type=Path, required=True)
    p3.add_argument("--viet", type=Path, required=True)
    p3.add_argument("--nhan", type=Path, required=True)
    p3.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("phieu-gan", "gop-nhan") and a.out.exists():
            raise Dung("--out đã tồn tại — cần thư mục mới")
        if a.cmd == "phieu-gan":
            phieu_gan(a.khung, a.viet, a.out)
        elif a.cmd == "gop-nhan":
            gop_nhan(a.phieu, a.a, a.b, a.phan_xu, a.out)
        else:
            dung_bo_the(a.khung, a.phieu, a.nhan, a.viet, a.out)
    except Dung as e:
        print(f"DỪNG: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
