"""RQ4 (DA10) — `training/injection/fine_tune_v4.py`: phần không cần GPU (chuẩn bị dữ liệu, tách theo template, đóng gói).

Dữ liệu giả nhỏ tự dựng, không torch. Định dạng manifest phải qua đúng regex dòng của `ml_service/app/guard.py`.
"""

import csv
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "training" / "injection" / "fine_tune_v4.py"
MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  (\S(?:.*\S)?)$")  # nguyên văn guard._MANIFEST_LINE


@pytest.fixture(scope="module")
def ft() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fine_tune_v4", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fine_tune_v4"] = mod
    spec.loader.exec_module(mod)
    return mod


def ghi(path: Path, rows: list[dict[str, Any]], bom: bool = False) -> Path:
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def v3_rows(split: str, n_group: int, prefix: str) -> list[dict[str, Any]]:
    out = []
    for g in range(n_group):
        lab = g % 2
        for k in range(3):
            out.append({"id": f"{prefix}{g}_{k}", "text": f"{split} cau {g} {k}", "label": lab,
                        "label_name": "INJECTION" if lab else "BENIGN", "semantic_group_id": f"{prefix}G{g}",
                        "family_id": "A01" if lab else "B01", "split": split})  # fmt: skip
    return out


def rq4_rows(n_template: int) -> list[dict[str, Any]]:
    return [{"id": f"r{t}_{k}", "ho": "F1" if t % 2 else "N1", "template_id": f"T{t}", "cau": f"rq4 cau {t} {k}",
             "nhan": "tan_cong" if t % 2 else "binh_thuong"} for t in range(n_template) for k in range(2)]  # fmt: skip


def test_tach_theo_template_khong_ro_ri_va_tat_dinh(ft: ModuleType) -> None:
    rows = ft.tu_rq4(rq4_rows(10))
    tr, va = ft.tach_theo_template(rows, 0.2)
    gt, gv = {r["semantic_group_id"] for r in tr}, {r["semantic_group_id"] for r in va}
    assert not (gt & gv) and len(gv) == 2  # ceil(0,2 × 5) = 1 template mỗi nhãn
    assert {r["label"] for r in va} == {0, 1}
    assert ft.tach_theo_template(rows, 0.2) == (tr, va)  # cùng seed → cùng kết quả
    assert ft.tach_theo_template(rows, 0.0)[1] == []
    with pytest.raises(SystemExit):
        ft.tach_theo_template(rows, 1.0)


def test_tu_rq4_tu_choi(ft: ModuleType) -> None:
    ok = rq4_rows(1)
    with pytest.raises(SystemExit):
        ft.tu_rq4([{**ok[0], "nhan": "1"}])
    with pytest.raises(SystemExit):
        ft.tu_rq4([{**ok[0], "template_id": " "}])
    with pytest.raises(SystemExit):
        ft.tu_rq4([{k: v for k, v in ok[0].items() if k != "ho"}])
    r = ft.tu_rq4(ok)[0]
    assert (r["id"], r["semantic_group_id"], r["label"], r["label_name"]) == ("RQ4_r0_0", "RQ4_T0", 0, "BENIGN")


def test_kiem_tra_bat_trung(ft: ModuleType) -> None:
    a = ft.tu_v3(v3_rows("train", 2, "a"), "train")
    b = ft.tu_v3(v3_rows("validation", 2, "b"), "validation")
    assert ft.kiem_tra(a, b)["trung_text_train_val"] == 0
    with pytest.raises(SystemExit):  # cùng câu (khác hoa thường, khoảng trắng) ở cả hai phía
        ft.kiem_tra(a, [{**b[0], "text": "  " + a[0]["text"].upper()}])
    with pytest.raises(SystemExit):  # cùng nhóm ở cả hai phía
        ft.kiem_tra(a, [{**b[0], "semantic_group_id": a[0]["semantic_group_id"]}])
    with pytest.raises(SystemExit):
        ft.tu_v3(v3_rows("train", 1, "a"), "validation")


def test_chuan_bi_cli(ft: ModuleType, tmp_path: Path) -> None:
    tr = ghi(tmp_path / "train.csv", v3_rows("train", 4, "a"), bom=True)
    va = ghi(tmp_path / "validation.csv", v3_rows("validation", 2, "b"), bom=True)
    rq = ghi(tmp_path / "rq4.csv", rq4_rows(10))
    out = tmp_path / "out"
    ft.main(["chuan-bi", "--v3-train", str(tr), "--v3-val", str(va), "--rq4-train", str(rq), "--ti-le-val", "0.2",
             "--ra", str(out)])  # fmt: skip
    meta = json.loads((out / "chuan_bi.json").read_text(encoding="utf-8"))
    assert meta["train"] == {"v3_train": 12, "rq4_train": 16} and meta["validation"] == {"v3_validation": 6, "rq4_train": 4}
    chung = ft.doc_csv(out / "val_chung_rq4.csv")
    assert list(chung[0]) == ft.RQ4_COLS and len(chung) == 10
    assert {r["nhan"] for r in chung} == {"tan_cong", "binh_thuong"}

    out2 = tmp_path / "v3only"
    ft.main(["chuan-bi", "--v3-train", str(tr), "--v3-val", str(va), "--khong-rq4", "--ra", str(out2)])
    assert json.loads((out2 / "chuan_bi.json").read_text(encoding="utf-8"))["train"] == {"v3_train": 12}
    with pytest.raises(SystemExit):
        ft.main(["chuan-bi", "--v3-train", str(tr), "--v3-val", str(va), "--ra", str(out2)])


def test_chon_max_length(ft: ModuleType) -> None:
    assert ft.chon_max_length([10] * 99 + [65]) == (128, pytest.approx(10 + 0.01 * 55, abs=1))
    assert ft.chon_max_length([200] * 10)[0] == 256
    assert ft.chon_max_length([999])[0] == 256


def test_dong_goi_va_manifest(ft: ModuleType, tmp_path: Path) -> None:
    src = tmp_path / "final_model"
    src.mkdir()
    for f in ("model.safetensors", "tokenizer.json", "tokenizer_config.json", "training_args.bin"):
        (src / f).write_bytes(f.encode())
    (src / "config.json").write_text(json.dumps({"id2label": {"0": "BENIGN", "1": "INJECTION"}}), encoding="utf-8")
    ng = tmp_path / "n.json"
    ng.write_text('{"tau_block": 0.9}', encoding="utf-8")
    dst = tmp_path / "v4-seed123"
    kq = ft.dong_goi(src, dst, ng, {"seed": 123})
    assert kq["bo_file"] == ["training_args.bin"] and not (dst / "training_args.bin").exists()
    lines = (dst / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    listed = {MANIFEST_LINE.match(x).group(2) for x in lines}  # type: ignore[union-attr]
    present = {p.name for p in dst.iterdir() if p.name != "MANIFEST.sha256"}
    assert listed == present and "thresholds.json" in listed and "model_card.md" in listed
    assert all(MANIFEST_LINE.match(x).group(1) == ft.sha256_file(dst / MANIFEST_LINE.match(x).group(2)) for x in lines)  # type: ignore[union-attr]
    assert kq["manifest_sha256"] == ft.sha256_file(dst / "MANIFEST.sha256")
    with pytest.raises(SystemExit):  # không ghi đè thư mục đã giao
        ft.dong_goi(src, dst, None, {})
    (src / "config.json").write_text(json.dumps({"id2label": {"0": "INJECTION", "1": "BENIGN"}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        ft.dong_goi(src, tmp_path / "x", None, {})


def test_notebook_kaggle_nhung_dung_script(ft: ModuleType) -> None:
    nb = json.loads((SCRIPT.parent / "fine_tune_v4_kaggle.ipynb").read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    embedded = [c for c in cells if c.startswith("%%writefile /kaggle/working/fine_tune_v4.py\n")]
    assert len(embedded) == 1
    body = embedded[0].split("\n", 1)[1].rstrip("\n") + "\n"
    script = SCRIPT.read_text(encoding="utf-8")
    assert body == script, "notebook nhúng script cũ — sinh lại notebook từ training/injection/fine_tune_v4.py"
    assert any(f'EXPECTED_SHA = "{ft.sha256_file(SCRIPT)}"' in c for c in cells)
    lines = [ln for c in cells for ln in c.splitlines()]
    assert not any("test.csv" in ln and "read" in ln.lower() for ln in lines)  # không dòng nào đọc test.csv
    assert any("test.csv" in ln and "assert not" in ln for ln in lines)  # có chặn khi thấy test.csv
