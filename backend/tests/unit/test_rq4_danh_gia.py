"""RQ4 (DA10) — `scripts/eval/rq4_danh_gia.py`: dữ liệu giả nhỏ tự dựng, không torch, không mạng, không LLM.

Quyết định sau L4 phải đi qua `after_judge` THẬT (`app.guard.b2_review`); 5b phải trùng `classifier_shortcut` chế độ `active`
khi ngưỡng = hằng của tag (0,90 / 0,10).
"""

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from app.guard import b2_review
from app.guard.injection import TAU_BLOCK, TAU_PASS

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "eval" / "rq4_danh_gia.py"


@pytest.fixture(scope="module")
def rq() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rq4_danh_gia", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rq4_danh_gia"] = mod
    spec.loader.exec_module(mod)
    return mod


def prep_row(i: str, label: str = "attack", regex: str | None = None, group: str = "t1") -> dict[str, Any]:
    return {"id": i, "label": label, "group": group, "ho": "F1", "text_l1": "x", "text_model": "x", "masks_replaced": 0,
            "regex_id": regex, "regex_group": "override" if regex else None, "regex_ms": 0.5}  # fmt: skip


def diem_row(i: str, p: float | None, err: str | None = None) -> dict[str, Any]:
    return {"id": i, "p_mal": p, "windows": 1 if p is not None else None, "error": err, "model_ms": 20.0}


def judge(i: str, attack: bool = False, category: str = "none", latency: float = 800.0) -> dict[str, Any]:
    return {"id": i, "is_attack": attack, "category": category, "error": None, "latency_ms": latency}


# ---- chỉ số và ngưỡng ------------------------------------------------------------------------------------------------


def test_auc_phan_vi(rq: ModuleType) -> None:
    assert rq.auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert rq.auc([0.5, 0.5], [0, 1]) == 0.5
    assert rq.phan_vi([1, 2, 3, 4], 0.95) == pytest.approx(3.85)


def test_tau_block_rang_buoc_chan_nham(rq: ModuleType) -> None:
    s = [i / 100 for i in range(29)] + [0.95] + [0.5 + 0.05 * i for i in range(10)]
    y = [0] * 30 + [1] * 10
    kq = rq.chon_tau_block(s, y, 1 / 30)
    assert kq["fpr_val"] <= 1 / 30 and kq["tau"] == 0.5  # 1/30 cho phép đúng 1 câu thường
    kq0 = rq.chon_tau_block(s, y, 0.0)
    assert kq0["fpr_val"] == 0 and kq0["tau"] > 0.95


def test_tau_pass(rq: ModuleType) -> None:
    kq = rq.chon_tau_pass([0.05, 0.1, 0.3, 0.6, 0.95], [0, 0, 1, 1, 1], tau_block=0.9, lot_toi_da=0)
    assert kq["tau_pass"] == 0.1 and kq["tan_cong_lot_val"] == 0


def test_cut_windows_khop_ml_service(rq: ModuleType) -> None:
    # ml_service/app/guard.py: thân 126, bước 94, tối đa 48
    for n, k in [(1, 1), (126, 1), (127, 2), (220, 2), (221, 3)]:
        assert len(rq.cut_windows(list(range(n)), -1, -2, 126, 94)) == k
    w = rq.cut_windows(list(range(300)), -1, -2, 126, 94)
    assert w[0][0] == -1 and w[0][-1] == -2 and w[-1][-2] == 299  # cửa sổ cuối phủ tới id cuối
    with pytest.raises(OverflowError):
        rq.cut_windows(list(range(126 + 94 * 48)), -1, -2, 126, 94)


# ---- quyết định theo từng phương án ----------------------------------------------------------------------------------


def test_regex_va_model_mot_minh(rq: ModuleType) -> None:
    ng = {"tau_block": 0.7}
    assert rq.quyet_dinh("regex", prep_row("a", regex="OVR-01"), None, None, None, b2_review)["nhan_du_doan"] == "tan_cong"
    q = rq.quyet_dinh("model:v3", prep_row("a"), diem_row("a", 0.69), None, ng, b2_review)
    assert (q["nhan_du_doan"], q["so_loi_goi_llm"], q["tang_quyet_dinh"]) == ("binh_thuong", 0, "")
    q = rq.quyet_dinh("model:pg2", prep_row("a"), diem_row("a", None, "too_many_windows"), None, ng, b2_review)
    assert q["nhan_du_doan"] == "tan_cong"
    with pytest.raises(SystemExit):
        rq.quyet_dinh("model:v3", prep_row("a"), diem_row("a", None, "RuntimeError"), None, ng, b2_review)


def test_chi_llm_dung_after_judge(rq: ModuleType) -> None:
    r = prep_row("a", regex="OVR-01")  # chỉ-LLM: không có regex, câu khớp regex vẫn hỏi LLM
    q = rq.quyet_dinh("llm", r, None, judge("a", category="prompt_leak"), None, b2_review)
    assert (q["ket_cuc"], q["so_loi_goi_llm"], q["thoi_gian_ms"]) == ("E0", 1, 800.0)
    assert rq.quyet_dinh("llm", r, None, judge("a"), None, b2_review)["nhan_du_doan"] == "binh_thuong"


@pytest.mark.parametrize(
    ("regex", "p", "err", "attack", "cat", "ket", "tang"),
    [
        ("OVR-01", 0.0, None, False, "none", "E0", "regex"),
        (None, 0.1, None, True, "override", "E0", "llm"),
        (None, 0.1, None, False, "other", "E0", "llm"),  # category ≠ none → E0 (#3)
        (None, 0.9999, None, False, "none", "E1", "model"),  # biên p = τ → E1
        (None, None, "too_many_windows", False, "none", "E1", "model"),
        (None, 0.5, None, False, "none", "pass", "llm"),
        (None, None, "model_missing", False, "none", "pass", "llm"),
    ],
)
def test_tang5a_review(rq: ModuleType, regex: Any, p: Any, err: Any, attack: bool, cat: str, ket: str, tang: str) -> None:
    ng = {"tau_review": 0.9999}
    r, d = prep_row("a", regex=regex), diem_row("a", p, err)
    j = None if regex else judge("a", attack, cat)
    q = rq.quyet_dinh("tang5a:v3", r, d, j, ng, b2_review)
    assert (q["ket_cuc"], q["tang_quyet_dinh"]) == (ket, tang)
    assert q["nhan_du_doan"] == ("binh_thuong" if ket == "pass" else "tan_cong")
    assert q["so_loi_goi_llm"] == (0 if regex else 1)
    assert q["thoi_gian_ms"] == (0.5 if regex else 0.5 + 20.0 + 800.0)


def test_tang5b_trung_classifier_shortcut_active(rq: ModuleType) -> None:
    ng = {"tau_pass": TAU_PASS, "tau_block": TAU_BLOCK}
    for k in range(101):
        p = k / 100
        r, d = prep_row("a"), diem_row("a", p)
        short = b2_review.classifier_shortcut("active", p)
        need = rq.can_llm("tang5b:v3", r, d, ng)
        assert need == (short is None)
        q = rq.quyet_dinh("tang5b:v3", r, d, judge("a") if need else None, ng, b2_review)
        if short is not None:
            assert q["ket_cuc"] == short.outcome and q["so_loi_goi_llm"] == 0 and q["tang_quyet_dinh"] == "model"
        else:
            assert q["so_loi_goi_llm"] == 1 and q["tang_quyet_dinh"] == "llm"


def test_tang5b_model_loi_xuong_llm_khong_mo_cua(rq: ModuleType) -> None:
    ng = {"tau_pass": 0.1, "tau_block": 0.9}
    r, d = prep_row("a"), diem_row("a", None, "classify_failed")
    assert rq.can_llm("tang5b:v4", r, d, ng)
    with pytest.raises(SystemExit):  # thiếu kết quả LLM → dừng, không tự cho qua
        rq.quyet_dinh("tang5b:v4", r, d, None, ng, b2_review)


def test_llm_loi_thi_dung(rq: ModuleType) -> None:
    j = {"id": "a", "is_attack": None, "category": None, "error": "LLMUnavailable", "latency_ms": 9000}
    with pytest.raises(SystemExit):
        rq.quyet_dinh("tang5a:v3", prep_row("a"), diem_row("a", 0.2), j, {"tau_review": 0.9}, b2_review)


def test_can_llm_khop_so_loi_goi(rq: ModuleType) -> None:
    ng = {"tau_pass": 0.2, "tau_block": 0.8, "tau_review": 0.9}
    for pa in ("llm", "tang5a:v3", "tang5b:v3"):
        for regex in (None, "OVR-01"):
            for p in (0.1, 0.5, 0.95, None):
                r, d = prep_row("a", regex=regex), diem_row("a", p, None if p is not None else "x")
                need = rq.can_llm(pa, r, d, ng)
                q = rq.quyet_dinh(pa, r, d, judge("a") if need else None, ng, b2_review)
                assert q["so_loi_goi_llm"] == int(need)


def test_phuong_an_la(rq: ModuleType) -> None:
    for pa in ("tang5a:pg2", "model:v5", "xyz"):
        with pytest.raises(SystemExit):
            rq.model_cua(pa)


# ---- D-52 (b2_tau_select nguyên văn) ---------------------------------------------------------------------------------


def test_rows_d52(rq: ModuleType) -> None:
    prep = [prep_row("a", "normal", regex="OVR-01"), prep_row("b", "normal"), prep_row("c", "attack")]
    diem = [diem_row("a", 0.99), diem_row("b", 0.95), diem_row("c", None, "too_many_windows")]
    llm = [judge("b"), {"id": "c", "is_attack": None, "category": None, "error": "LLMUnavailable", "latency_ms": 1}]
    rows = {r["id"]: r for r in rq.rows_d52(prep, diem, llm)}
    assert rows["a"]["judge_no"] is False and rows["a"]["regex_hit"]
    assert rows["b"]["judge_no"] is True and rows["b"]["group"] == "t1"
    assert rows["c"]["judge_no"] is None and rows["c"]["ml_error"] == "too_many_windows"


# ---- chuẩn bị, CSV, đầu cuối -----------------------------------------------------------------------------------------


def test_chuan_bi_rows(rq: ModuleType) -> None:
    class Hit:
        id, group = "OVR-01", "override"

    items = [{"id": "1", "cau": "A <SĐT_1>", "nhan": "tan_cong", "template_id": "t1", "ho": "F1"},
             {"id": "2", "cau": "b", "nhan": "binh_thuong", "template_id": "n1", "ho": "N1"}]  # fmt: skip
    rows = rq.chuan_bi_rows(items, redact=str.upper, replace=lambda t: (t.replace("<SĐT_1>", "số điện thoại"), 1),
                            match=lambda t: Hit() if t.startswith("A") else None)  # fmt: skip
    assert rows[0]["text_l1"] == "A <SĐT_1>" and rows[0]["text_model"] == "A số điện thoại"
    assert (rows[0]["regex_id"], rows[1]["regex_id"]) == ("OVR-01", None)
    assert rows[0]["label"] == "attack" and rows[1]["group"] == "n1" and rows[1]["regex_ms"] >= 0


def test_doc_csv_tu_choi(rq: ModuleType, tmp_path: Path) -> None:
    def ghi(rows: list[dict[str, str]]) -> Path:
        p = tmp_path / "x.csv"
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        return p

    ok = {"id": "1", "ho": "F1", "template_id": "t", "cau": "c", "nhan": "tan_cong", "nguoi_viet": "X"}
    assert len(rq.doc_csv(ghi([ok]))) == 1  # cột thừa nguoi_viet được nhận
    for bad in ([{**ok, "nhan": "1"}], [ok, ok], [{**ok, "template_id": ""}]):
        with pytest.raises(SystemExit):
            rq.doc_csv(ghi(bad))


def test_dau_cuoi_cli(rq: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prep = [prep_row(f"a{i}", "attack", regex="OVR-01" if i == 0 else None) for i in range(10)]
    prep += [prep_row(f"n{i}", "normal", group=f"n{i % 3}") for i in range(30)]
    scores = {r["id"]: (0.3 + 0.07 * i if r["label"] == "attack" else 0.01 * i) for i, r in enumerate(prep)}
    P, D = tmp_path / "p.jsonl", tmp_path / "d.jsonl"
    rq.write_jsonl(P, {"input_sha256": "x"}, prep)
    rq.write_jsonl(D, {"model": "v3", "prep_sha256": rq.sha256_file(P)}, [diem_row(i, s) for i, s in scores.items()])
    N = tmp_path / "n.json"
    rq.main(["chon-nguong", "--kieu", "hai-nguong", "--prep", str(P), "--diem", str(D), "--ra", str(N)])
    ng = json.loads(N.read_text(encoding="utf-8"))
    assert ng["tau_pass"] < ng["tau_block"] and "tieu_chi" in ng and ng["validation"]["prep_sha256"] == rq.sha256_file(P)

    K = tmp_path / "kq.csv"
    rq.main(["ghep", "--phuong-an", "model:v3", "--prep", str(P), "--diem", str(D), "--nguong", str(N), "--ra", str(K)])
    with K.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == rq.COT_RA and len(rows) == 40
    assert json.loads(K.with_suffix(".manifest.json").read_text(encoding="utf-8"))["ket_qua"]["sha256"] == rq.sha256_file(K)

    ids = tmp_path / "ids.txt"
    rq.main(["can-llm", "--phuong-an", "tang5b:v3", "--prep", str(P), "--diem", str(D), "--nguong", str(N), "--ra", str(ids)])
    need = ids.read_text(encoding="utf-8").split()
    L = tmp_path / "l.jsonl"
    rq.write_jsonl(L, {"phuong_an": "tang5b:v3"}, [judge(i) for i in need])
    rq.main(["ghep", "--phuong-an", "tang5b:v3", "--prep", str(P), "--diem", str(D), "--llm", str(L), "--nguong", str(N),
             "--ra", str(K)])  # fmt: skip
    with K.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert sum(int(r["so_loi_goi_llm"]) for r in rows) == len(need)
    assert {r["tang_quyet_dinh"] for r in rows} <= {"regex", "model", "llm"}
    s = rq.tong_hop(rows, {r["id"]: r["label"] for r in prep})
    assert s["so_cau"] == 40 and 0 <= s["recall"] <= 1 and not math.isnan(s["p95_ms"])

    L2 = tmp_path / "l2.jsonl"  # file LLM của lượt khác → từ chối (mỗi phương án gọi riêng)
    rq.write_jsonl(L2, {"phuong_an": "llm"}, [])
    with pytest.raises(SystemExit):
        rq.main(["ghep", "--phuong-an", "tang5b:v3", "--prep", str(P), "--diem", str(D), "--llm", str(L2), "--nguong",
                 str(N), "--ra", str(K)])  # fmt: skip


def test_goi_llm_dry_run_khong_goi_mang(rq: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    P = tmp_path / "p.jsonl"
    rq.write_jsonl(P, {}, [prep_row("a", regex="OVR-01"), prep_row("b"), prep_row("c")])
    rq.main(["goi-llm", str(P), str(tmp_path / "o.jsonl"), "--phuong-an", "tang5a:v3", "--max-calls", "5", "--max-usd", "0",
             "--dry-run"])  # fmt: skip
    assert "cần 2" in capsys.readouterr().out and not (tmp_path / "o.jsonl").exists()
