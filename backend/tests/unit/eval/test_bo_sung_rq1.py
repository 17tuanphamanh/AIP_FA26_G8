"""Đo bổ sung RQ1 (16/11) — `scripts/eval/bo_sung_rq1/{khung,dung_the,phan_tich}.py`.

Chạy trên dữ liệu thật của nhánh (seed + policy bản đo) cho bước khung; phiếu viết / phiếu gán dựng giả trong `tmp_path`; phân tích
dùng bản ghi `PredictionRecord` dựng tay. Không mạng, không stack, không LLM.
"""

import csv
import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from app.eval.predictions import PredictionRecord
from openpyxl import load_workbook

REPO = Path(__file__).resolve().parents[4]
DIR = REPO / "scripts" / "eval" / "bo_sung_rq1"


def _load(name: str) -> ModuleType:
    """Nạp script như module (dataclass cần module có trong `sys.modules`); `dung_the` tự `import khung` qua cùng thư mục."""
    if str(DIR) not in sys.path:
        sys.path.insert(0, str(DIR))
    return importlib.import_module(name)


kh = _load("khung")
dt = _load("dung_the")
pt = _load("phan_tich")


# ---- khung ----------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def khung_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("k") / "khung"
    assert kh.main(["--out", str(out)]) == 0
    return out


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_khung_du_chi_tieu_khong_trung_va_tai_lap(
    khung_dir: Path, tmp_path: Path
) -> None:
    rows = _rows(khung_dir / "khung.csv")
    chinh = [r for r in rows if r["vai_tro"] == "chính"]
    want = {(n, loai): k for n, d in kh.CHI_TIEU.items() for loai, k in d.items()}
    assert Counter((r["nhom"], r["loai"]) for r in chinh) == Counter(
        {k: v for k, v in want.items() if v}
    )
    assert len(chinh) == sum(want.values())
    s = kh.SeedGoc(REPO / "mock_services" / "seed.json")
    keys = [(r["nguoi_gui"], r["loai"], kh.chu_dich(s, kh.UngVien(r["nguoi_gui"], r["hanh_dong"], r["doi_tuong"], r["lam_ho"], {}, {})))
            for r in rows]  # fmt: skip
    assert len(keys) == len(set(keys)), (
        "hai tình huống trùng (người gửi, loại việc, người bị tác động)"
    )
    cu = kh.khoa_bo_cu(REPO / "eval" / "the100")
    assert (
        not {
            (r["nguoi_gui"], r["hanh_dong"], r["doi_tuong"], r["lam_ho"]) for r in rows
        }
        & cu
    )
    assert not {r["nguoi_gui"] for r in rows} & kh.NGUOI_GUI_LOAI
    assert not {r["lam_ho"] for r in rows} & kh.DOI_TUONG_LOAI
    again = tmp_path / "k2"
    assert kh.main(["--out", str(again)]) == 0
    assert (again / "khung.csv").read_bytes() == (khung_dir / "khung.csv").read_bytes()


def test_khung_moi_dong_di_lop_llm(khung_dir: Path) -> None:
    """Mỗi dòng khung (chính + dự phòng) chấm lại bằng rule_coverage đều `none`."""
    s = kh.SeedGoc(REPO / "mock_services" / "seed.json")
    ds = [kh.UngVien(r["nguoi_gui"], r["hanh_dong"], r["doi_tuong"], r["lam_ho"], json.loads(r["tham_so"]), json.loads(r["du_kien"]))
          for r in _rows(khung_dir / "khung.csv")]  # fmt: skip
    kh.cham_luat(ds, REPO)
    assert {u.quyet_dinh for u in ds} == {"none"}
    assert not any(u.canh_bao for u in ds)
    assert all(kh.xep_nhom(s, u) for u in ds)


def test_khung_out_ton_tai_thi_dung(tmp_path: Path) -> None:
    assert kh.main(["--out", str(tmp_path)]) == 2


def test_xep_nhom() -> None:
    s = kh.SeedGoc(REPO / "mock_services" / "seed.json")
    u = lambda r, typ, target, rf: kh.UngVien(r, typ, target, rf, {}, {})
    assert kh.xep_nhom(s, u("l1_02", "reset_password", "user:nv001", "nv001")) == "A"
    assert (
        kh.xep_nhom(s, u("l1_02", "reset_password", "user:l2_01", "l2_01")) == ""
    )  # IT làm hộ người trong IT
    assert kh.xep_nhom(s, u("fin_head", "reset_password", "user:nv001", "nv001")) == "B"
    assert (
        kh.xep_nhom(s, u("nv001", "reset_password", "user:nv003", "nv003")) == "C"
    )  # cùng phòng
    assert (
        kh.xep_nhom(s, u("nv001", "reset_password", "user:nv002", "nv002")) == ""
    )  # khác phòng, không phải cấp trên
    assert (
        kh.xep_nhom(s, u("nv001", "renew_vpn_cert", "device:LAP-0342", "nv001")) == "D"
    )  # máy của chính mình
    assert (
        kh.xep_nhom(s, u("nv001", "renew_vpn_cert", "device:LAP-0501", "nv001")) == "C"
    )  # máy đồng nghiệp cùng phòng


# ---- dung_the ------------------------------------------------------------------------------------------------------------


def _dien_phieu_viet(
    src: Path,
    dst: Path,
    khong_tu_nhien: frozenset[str] = frozenset(),
    them: frozenset[str] = frozenset(),
) -> None:
    """Điền câu giả: mọi dòng chính (trừ `khong_tu_nhien`, đánh 'x') + các dòng dự phòng trong `them`."""
    wb = load_workbook(src)
    ws = wb[dt.TEN_SHEET_VIET]
    head = [c.value for c in ws[1]]
    ci = {h: head.index(h) + 1 for h in head}
    for row in range(2, ws.max_row + 1):
        ma = ws.cell(row, ci["Mã"]).value
        vai = ws.cell(row, ci["Vai trò"]).value
        if ma in khong_tu_nhien:
            ws.cell(row, ci["Không tự nhiên"], "x")
        elif vai == "chính" or ma in them:
            ws.cell(row, ci["Câu đầu"], f"  Nhờ IT   xử lý giúp việc {ma}  ")
            ws.cell(row, ci["Trả lời 1"], "Dạ đúng rồi ạ")
    wb.save(dst)


def _bai_gan(phieu: Path, dst: Path, nhan_cho: dict[str, str]) -> None:
    wb = load_workbook(phieu / "phieu-gan.xlsx")
    ws = wb[dt.TEN_SHEET_GAN]
    for row in range(2, ws.max_row + 1):
        ws.cell(row, 7, nhan_cho[str(ws.cell(row, 1).value)])
    wb.save(dst)


def test_quy_trinh_dung_the_tron_ven(khung_dir: Path, tmp_path: Path) -> None:
    rows = _rows(khung_dir / "khung.csv")
    chinh_a = next(
        r["ma"] for r in rows if r["vai_tro"] == "chính" and r["nhom"] == "A"
    )
    du_a = next(
        r["ma"] for r in rows if r["vai_tro"] == "dự phòng" and r["nhom"] == "A"
    )
    viet = tmp_path / "viet.xlsx"
    _dien_phieu_viet(
        khung_dir / "phieu-viet.xlsx",
        viet,
        khong_tu_nhien=frozenset({chinh_a}),
        them=frozenset({du_a}),
    )
    phieu = tmp_path / "phieu"
    assert (
        dt.main(
            [
                "phieu-gan",
                "--khung",
                str(khung_dir / "khung.csv"),
                "--viet",
                str(viet),
                "--out",
                str(phieu),
            ]
        )
        == 0
    )
    chon = json.loads((phieu / "chon.json").read_text(encoding="utf-8"))
    assert chinh_a not in chon["chon"] and du_a in chon["chon"]
    assert len(chon["chon"]) == sum(sum(d.values()) for d in kh.CHI_TIEU.values())
    assert (
        sorted(chon["thu_tu_phieu"]) == sorted(chon["chon"])
        and chon["thu_tu_phieu"] != chon["chon"]
    )
    ids = chon["chon"]
    a = {m: ("AUTO" if i % 3 == 0 else "HITL") for i, m in enumerate(ids)}
    b = dict(a)
    b[ids[1]] = "ESCALATE_L2"
    _bai_gan(phieu, tmp_path / "A.xlsx", a)
    _bai_gan(phieu, tmp_path / "B.xlsx", b)
    nhan = tmp_path / "nhan"
    assert dt.main(["gop-nhan", "--phieu", str(phieu), "--a", str(tmp_path / "A.xlsx"), "--b", str(tmp_path / "B.xlsx"),
                    "--out", str(tmp_path / "nhan0")]) == 0  # fmt: skip
    lech = _rows(tmp_path / "nhan0" / "lech.csv")
    assert [r["id"] for r in lech] == [ids[1]]
    assert not (tmp_path / "nhan0" / "nhan-cuoi.json").exists()
    px = tmp_path / "px.csv"
    px.write_text(
        f"id,nhan_a,nhan_b,nhan_phan_xu\n{ids[1]},HITL,ESCALATE_L2,HITL\n",
        encoding="utf-8",
    )
    assert dt.main(["gop-nhan", "--phieu", str(phieu), "--a", str(tmp_path / "A.xlsx"), "--b", str(tmp_path / "B.xlsx"),
                    "--phan-xu", str(px), "--out", str(nhan)]) == 0  # fmt: skip
    cuoi = json.loads((nhan / "nhan-cuoi.json").read_text(encoding="utf-8"))
    assert (
        cuoi["nhan_cuoi"][ids[1]] == "HITL"
        and cuoi["annotator_2"][ids[1]] == "ESCALATE_L2"
    )
    out = tmp_path / "bo"
    assert dt.main(["the", "--khung", str(khung_dir / "khung.csv"), "--phieu", str(phieu), "--viet", str(viet),
                    "--nhan", str(nhan / "nhan-cuoi.json"), "--out", str(out)]) == 0  # fmt: skip
    files = sorted((out / "the").glob("*.yaml"))
    assert len(files) == len(ids)
    card = yaml.safe_load(files[0].read_text(encoding="utf-8"))
    assert card["turns"][0].startswith("Nhờ IT xử lý") and card["turns"][-1] == {
        "on_confirm": True
    }
    assert card["gold"]["expected_route"] in dt.NHAN and card["at"] == kh.AT_MAC_DINH
    assert card["gold"]["approver_decision"] == "reject"
    th = json.loads((out / "tinh-huong.json").read_text(encoding="utf-8"))
    assert set(th.values()) == set(ids)
    khoa = (out / "KHOA.md").read_text(encoding="utf-8")
    assert "dataset_sha256:" in khoa and f"so_the: {len(ids)}" in khoa
    # dựng lại vào cùng chỗ → dừng (không ghi đè bộ đã khoá)
    assert dt.main(["the", "--khung", str(khung_dir / "khung.csv"), "--phieu", str(phieu), "--viet", str(viet),
                    "--nhan", str(nhan / "nhan-cuoi.json"), "--out", str(out)]) == 2  # fmt: skip


def test_phieu_gan_thieu_cau_hoac_thieu_du_phong_thi_dung(
    khung_dir: Path, tmp_path: Path
) -> None:
    rows = _rows(khung_dir / "khung.csv")
    d_chinh = [r["ma"] for r in rows if r["vai_tro"] == "chính" and r["nhom"] == "D"]
    viet = tmp_path / "viet.xlsx"
    _dien_phieu_viet(
        khung_dir / "phieu-viet.xlsx", viet, khong_tu_nhien=frozenset({d_chinh[0]})
    )  # nhóm D không có dự phòng đã viết
    assert (
        dt.main(
            [
                "phieu-gan",
                "--khung",
                str(khung_dir / "khung.csv"),
                "--viet",
                str(viet),
                "--out",
                str(tmp_path / "p"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "p").exists()


def test_bai_gan_nhan_sai_thi_dung(khung_dir: Path, tmp_path: Path) -> None:
    viet = tmp_path / "viet.xlsx"
    _dien_phieu_viet(khung_dir / "phieu-viet.xlsx", viet)
    phieu = tmp_path / "phieu"
    assert (
        dt.main(
            [
                "phieu-gan",
                "--khung",
                str(khung_dir / "khung.csv"),
                "--viet",
                str(viet),
                "--out",
                str(phieu),
            ]
        )
        == 0
    )
    ids = json.loads((phieu / "chon.json").read_text(encoding="utf-8"))["chon"]
    a = dict.fromkeys(ids, "HITL")
    bad = dict(a)
    bad[ids[0]] = "MAYBE"
    _bai_gan(phieu, tmp_path / "A.xlsx", a)
    _bai_gan(phieu, tmp_path / "B.xlsx", bad)
    assert dt.main(["gop-nhan", "--phieu", str(phieu), "--a", str(tmp_path / "A.xlsx"), "--b", str(tmp_path / "B.xlsx"),
                    "--out", str(tmp_path / "n")]) == 2  # fmt: skip


# ---- phan_tich -----------------------------------------------------------------------------------------------------------

BASE: dict[str, Any] = {
    "run_id": "aaaaaaaaaaa1", "strategy": "hybrid", "split": "test", "parent_ticket_id": None, "calibrated_prob": None,
    "final_state": None, "exit_code": None, "close_reason": None, "resolution_path": None, "has_approval": True,
    "clarification_turns": 0, "intent": None, "gold_intent": None, "doc_ids": None, "gold_doc_ids": (), "schema_version": "1.1",
    "fold": None, "hidden_factor": None, "run_started_at": "2026-11-18T10:00:00+07:00", "in_business_hours": True, "m5_aborted": None,
}  # fmt: skip


def rec(i: int, gold: str | None, p: float | None, *, by: str | None = "llm", route: str | None = "HITL", kb_gap: bool = False,
        fam: str | None = None, aborted: bool | None = None) -> PredictionRecord:  # fmt: skip
    risk = route is not None
    return PredictionRecord.model_validate({
        **BASE, "scenario_id": f"SB{i:02d}-q1", "family": fam or f"SB{i:02d}", "ticket_id": f"t{i}", "expected_route": gold,
        "route": route, "decided_by": by if risk else None, "raw_prob": p if risk else None,
        "p_method": "sampling_k5" if risk and p is not None else None, "kb_gap": kb_gap if risk else None,
        "m5_aborted": aborted,
    })  # fmt: skip


def test_auc_va_doc_ket_luan() -> None:
    tach = [rec(i, "AUTO", 0.0) for i in range(6)] + [
        rec(10 + i, "HITL", 1.0) for i in range(6)
    ]
    d = pt.danh_gia("x", tach, None)
    assert d["auc"] == pytest.approx(1.0) and d["doc"] == "có tín hiệu"
    nguoc = [rec(i, "AUTO", 1.0) for i in range(6)] + [
        rec(10 + i, "HITL", 0.0) for i in range(6)
    ]
    assert pt.danh_gia("x", nguoc, None)["doc"] == "ngược chiều"
    deu = [rec(i, "AUTO", 0.6) for i in range(6)] + [
        rec(10 + i, "HITL", 0.6) for i in range(6)
    ]
    e = pt.danh_gia("x", deu, None)
    assert e["auc"] == pytest.approx(0.5) and e["doc"] == "chưa thấy tín hiệu"
    it = [rec(i, "AUTO", 0.0) for i in range(4)] + [
        rec(10 + i, "HITL", 1.0) for i in range(9)
    ]
    assert pt.danh_gia("x", it, None)["doc"] == "không đủ dữ liệu"


def test_van_hanh_kb_gap_va_bo_sot() -> None:
    rs = [rec(1, "AUTO", 0.0), rec(2, "AUTO", 0.0, kb_gap=True), rec(3, "AUTO", 0.2), rec(4, "HITL", 0.0), rec(5, "HITL", 0.8),
          rec(6, "ESCALATE_L2", 0.2), rec(7, "ESCALATE_L2", 0.0, kb_gap=True)]  # fmt: skip
    v0, v2 = pt.danh_gia("x", rs, None)["van_hanh"]
    assert (
        v0["auto_duoc_tu_xu_ly"],
        v0["n_auto"],
        v0["bo_sot"],
        v0["tinh_huong_can_nguoi"],
    ) == (1, 3, 1, 4)
    assert (v2["auto_duoc_tu_xu_ly"], v2["bo_sot"]) == (2, 2)
    assert v0["bo_sot_can_tren95_1phia"] > v0["bo_sot_ty_le"]
    # mục 10 (b): không áp D-34 thì ca HB12-kiểu (cần L2, p = 0, thiếu căn cứ) cũng tính là LLM sai
    assert (v0["bo_sot_khong_d34"], v2["bo_sot_khong_d34"]) == (2, 3)


def test_chon_mau_dem_ly_do_loai() -> None:
    rs = [rec(1, "AUTO", 0.0), rec(2, None, 0.4), rec(3, "HITL", None, route=None, aborted=False),
          rec(4, "HITL", None, route=None, aborted=True), rec(5, "HITL", 0.0, by="rule", route="AUTO"),
          rec(6, "HITL", None, route="HITL")]  # fmt: skip
    mau, loai = pt.chon_mau(rs)
    assert [r.scenario_id for r in mau] == ["SB01-q1"]
    assert loai == {
        "chua_nhan": 1,
        "khong_toi_m5": 1,
        "khong_toi_m5_bi_ngat": 1,
        "luat_quyet": 1,
        "llm_khong_co_p": 1,
    }


def _ghi_luot(d: Path, rs: list[PredictionRecord], **mf: Any) -> tuple[Path, Path]:
    d.mkdir(parents=True)
    (d / "predictions.jsonl").write_text(
        "".join(r.model_dump_json() + "\n" for r in rs), encoding="utf-8"
    )
    manifest = {"run_id": "aaaaaaaaaaa1", "strategy": "hybrid", "config": {"prob_method": "sampling_k5", "llm_roles": {"strong": "m"}},
                "enable_proactive_diagnosis": True, "dataset_sha256": "a" * 64, "git_commit": "abc1234", "policy_sha256": "p",
                "llm_cache_mode": "eval", "clf_mode": "review", "llm_backend": "real", "timeout_s": 300} | mf  # fmt: skip
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d / "predictions.jsonl", d / "manifest.json"


def test_phan_tich_main(tmp_path: Path) -> None:
    rs = [rec(i, "AUTO", 0.0) for i in range(5)] + [
        rec(10 + i, "HITL", 1.0) for i in range(5)
    ]
    pred, mf = _ghi_luot(tmp_path / "run", rs)
    khoa = tmp_path / "KHOA.md"
    khoa.write_text(
        "```yaml\ndataset_sha256: " + "a" * 64 + "\n```\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    assert (
        pt.main(["--moi", str(pred), str(mf), "--khoa", str(khoa), "--out", str(out)])
        == 0
    )
    kq = json.loads((out / "ket-qua.json").read_text(encoding="utf-8"))
    assert kq["ket_qua"][0]["doc"] == "có tín hiệu"
    assert "AUC" in (out / "bang.md").read_text(encoding="utf-8")
    sai = tmp_path / "KHOA2.md"
    sai.write_text("dataset_sha256: " + "b" * 64 + "\n", encoding="utf-8")
    assert (
        pt.main(
            [
                "--moi",
                str(pred),
                str(mf),
                "--khoa",
                str(sai),
                "--out",
                str(tmp_path / "o2"),
            ]
        )
        == 2
    )


def test_phan_tich_gop_cu_va_lech_cau_hinh(tmp_path: Path) -> None:
    moi = [rec(i, "AUTO", 0.0) for i in range(5)] + [
        rec(10 + i, "HITL", 1.0) for i in range(5)
    ]
    cu = [rec(30 + i, "HITL", 1.0, fam=f"HB{i:02d}") for i in range(6)] + [
        rec(40, "AUTO", 0.6, fam="HB20")
    ]
    pm, mm = _ghi_luot(tmp_path / "moi", moi)
    pc, mc = _ghi_luot(tmp_path / "cu", [r.model_copy(update={"run_id": "aaaaaaaaaaa0"}) for r in cu], run_id="aaaaaaaaaaa0",
                       config={"prob_method": "sampling_k5", "llm_roles": {"strong": "khac"}})  # fmt: skip
    khoa = tmp_path / "KHOA.md"
    khoa.write_text("dataset_sha256: " + "a" * 64 + "\n", encoding="utf-8")
    out = tmp_path / "out"
    assert (
        pt.main(
            [
                "--moi",
                str(pm),
                str(mm),
                "--khoa",
                str(khoa),
                "--cu",
                str(pc),
                str(mc),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    kq = json.loads((out / "ket-qua.json").read_text(encoding="utf-8"))
    assert [d["n_la"] for d in kq["ket_qua"]] == [10, 7, 17]
    assert any("llm_roles" in x for x in kq["lech_cau_hinh"])
    pc2, mc2 = _ghi_luot(
        tmp_path / "cu2",
        [r.model_copy(update={"run_id": "aaaaaaaaaaa0"}) for r in cu],
        run_id="aaaaaaaaaaa0",
        policy_sha256="khac",
    )
    assert (
        pt.main(
            [
                "--moi",
                str(pm),
                str(mm),
                "--khoa",
                str(khoa),
                "--cu",
                str(pc2),
                str(mc2),
                "--out",
                str(tmp_path / "o3"),
            ]
        )
        == 2
    )


def test_phan_tich_do_nhay_theo_nhan(tmp_path: Path) -> None:
    rs = [rec(i, "AUTO", 0.0) for i in range(6)] + [
        rec(10 + i, "HITL", 1.0) for i in range(6)
    ]
    pred, mf = _ghi_luot(tmp_path / "run", rs)
    khoa = tmp_path / "KHOA.md"
    khoa.write_text("dataset_sha256: " + "a" * 64 + "\n", encoding="utf-8")
    the = tmp_path / "the"
    the.mkdir()
    for i, r in enumerate(rs):
        b = "HITL" if i == 0 else r.expected_route
        card = {
            "id": r.scenario_id,
            "requester": {"user_id": f"nv00{i % 3}"},
            "gold": {"expected_route": r.expected_route},
            "labels": {"annotator_1": r.expected_route, "annotator_2": b},
        }
        (the / f"{r.scenario_id}.yaml").write_text(
            yaml.safe_dump(card), encoding="utf-8"
        )
    out = tmp_path / "out"
    assert (
        pt.main(
            [
                "--moi",
                str(pred),
                str(mf),
                "--khoa",
                str(khoa),
                "--the",
                str(the),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    kq = json.loads((out / "ket-qua.json").read_text(encoding="utf-8"))
    assert [d["n_la"] for d in kq["ket_qua"]] == [12, 11]
    nb = kq["nhan_bo_moi"]
    assert (nb["auto"], nb["n"]) == (6, 12) and nb["ktc95"][0] < 0.5 < nb["ktc95"][1]
    assert (
        kq["ket_qua"][0]["n_nguoi_gui"] == 3
        and len(kq["ket_qua"][0]["auc_ktc95_theo_nguoi_gui"]) == 2
    )
    assert "người gửi" in (out / "bang.md").read_text(encoding="utf-8")
