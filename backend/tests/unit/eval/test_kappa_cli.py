"""G9 — `scripts/eval/kappa.py`: `parse_cells` (bảng ô → (id, nhãn)) + CLI trên bộ đọc GIẢ tiêm vào `main(argv, read=...)`.

Không file xlsx nào: đường dẫn A/B chỉ là tên trong `tmp_path`, bộ đọc giả trả danh sách (id, nhãn) dựng từ ma trận tính tay (E2, E5 ở
`test_stats_kappa.py`). Id tổng hợp chứa `SENTINEL`; mọi lần chạy CLI kiểm stdout + stderr không có id, không có nhãn.
"""

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from app.eval.stats import KAPPA_LABELS
from tests.unit.eval.eval_scripts import REPO, load_script

kp = load_script("kappa")

A, H, L = KAPPA_LABELS
FORBIDDEN = ("SENTINEL", "AUTO", "HITL", "ESCALATE")
HEADER = ["id", "Người gửi", "Thời điểm", "Người dùng nói", "Hành động", "Dữ kiện", "Nhãn", "Lý do", "Mơ hồ"]  # sheet thật, dòng 1

Rows = list[tuple[str, str]]


def from_matrix(m: list[list[int]], prefix: str = "S_SENTINEL_") -> tuple[Rows, Rows]:
    a: Rows = []
    b: Rows = []
    for i, row in enumerate(m):
        for j, count in enumerate(row):
            for _ in range(count):
                sid = f"{prefix}{len(a):02d}"
                a.append((sid, KAPPA_LABELS[i]))
                b.append((sid, KAPPA_LABELS[j]))
    return a, b


E5 = from_matrix([[2, 2, 0], [0, 3, 1], [0, 0, 2]])
E5_LINES = ["kappa: n=10 po=0.7000 pe=0.3400", "kappa=0.5455 kappa_w=0.6341 pabak=0.5500",
            "ket_qua=KHONG_DAT nguong=0.6 loc=khong"]  # fmt: skip


class Fake:
    """Bộ đọc giả: tên file → danh sách (id, nhãn); ghi lại sheet được hỏi."""

    def __init__(self, a: Rows, b: Rows) -> None:
        self.tables = {"A.xlsx": a, "B.xlsx": b}
        self.sheets: list[str] = []

    def __call__(self, path: Path, sheet: str) -> Rows:
        self.sheets.append(sheet)
        return list(self.tables[path.name])


def run(tmp_path: Path, capsys: pytest.CaptureFixture[str], rows: tuple[Rows, Rows] = E5, *extra: str,
        read: Any = None) -> tuple[int, str, str]:  # fmt: skip
    argv = [str(tmp_path / "A.xlsx"), str(tmp_path / "B.xlsx"), "--sheet", "Đợt 2", *extra]
    code = kp.main(argv) if read is False else kp.main(argv, read=read or Fake(*rows))
    out, err = capsys.readouterr()
    for word in FORBIDDEN:
        assert word not in out + err
    return code, out, err


def body(*rows: list[Any]) -> list[list[Any]]:
    return [HEADER, *rows]


def data_row(sid: str, label: str, said: str = "SENTINEL người dùng nói S_SENTINEL_x") -> list[Any]:
    return [sid, "SENTINEL_gui", None, said, "SENTINEL_hd", None, label, "Câu 1, SENTINEL: x", None]


COMMIT = ["Tôi cam kết SENTINEL", "SENTINEL_ky", None, None, None, None, "Đã gán độc lập SENTINEL", "SENTINEL_ten", None]


# ---- parse_cells -----------------------------------------------------------------------------------------------------


def test_parse_cells_real_layout() -> None:
    rows = body(data_row("S_SENTINEL_1", A), data_row(" TH_SENTINEL_2 ", f" {H} "), data_row("S_SENTINEL_3", L), [None] * 9,
                COMMIT)  # fmt: skip
    assert kp.parse_cells(rows) == [("S_SENTINEL_1", A), ("TH_SENTINEL_2", H), ("S_SENTINEL_3", L)]


def test_parse_cells_commit_row_skipped() -> None:
    """Dòng cam kết ngay sau dòng dữ liệu cuối (không dòng trống), có chữ ở cột Nhãn → bỏ."""
    rows = body(data_row("S_SENTINEL_1", A), data_row("S_SENTINEL_2", H), COMMIT, ["SENTINEL ghi chú", None, None, None, None, None, H])
    assert kp.parse_cells(rows) == [("S_SENTINEL_1", A), ("S_SENTINEL_2", H)]


@pytest.mark.parametrize("bad_id", ["X_SENTINEL_x", "", "s_SENTINEL_1", "S SENTINEL"])
def test_parse_cells_bad_id_between_red(bad_id: str) -> None:
    rows = body(data_row("S_SENTINEL_1", A), data_row(bad_id, H), data_row("S_SENTINEL_3", L))
    with pytest.raises(kp.InputError) as e:
        kp.parse_cells(rows)
    assert str(e.value) == "dòng #3: id sai dạng"


def test_parse_cells_blank_row_between_skipped() -> None:
    rows = body(data_row("S_SENTINEL_1", A), [None, "", "  "], [], data_row("S_SENTINEL_3", L))
    assert kp.parse_cells(rows) == [("S_SENTINEL_1", A), ("S_SENTINEL_3", L)]


def test_parse_cells_columns_moved() -> None:
    rows = [["Nhãn", "Người dùng nói", " id "], [H, "SENTINEL nói", "S_SENTINEL_1"], [A, "SENTINEL nói", "TH_SENTINEL_2"]]
    assert kp.parse_cells(rows) == [("S_SENTINEL_1", H), ("TH_SENTINEL_2", A)]


def test_parse_cells_short_rows() -> None:
    """Dòng ngắn hơn tiêu đề (ô cuối trống) → nhãn rỗng, để `index_rows` báo lỗi."""
    assert kp.parse_cells(body(["S_SENTINEL_1"])) == [("S_SENTINEL_1", "")]


@pytest.mark.parametrize("header", [
    ["Mã", "Nhãn"], ["id", "Nhan"], ["id", "id", "Nhãn"], ["id", "Nhãn", "Nhãn"], [],
])  # fmt: skip
def test_parse_cells_header_red(header: list[str]) -> None:
    with pytest.raises(kp.InputError, match="tiêu đề"):
        kp.parse_cells([header, ["S_SENTINEL_1", A]])


def test_parse_cells_empty_sheet() -> None:
    with pytest.raises(kp.InputError, match="sheet rỗng"):
        kp.parse_cells([])


def test_read_rows_pending(tmp_path: Path) -> None:
    with pytest.raises(kp.XlsxReaderPending):
        kp.read_rows(tmp_path / "A.xlsx", "Đợt 2")


# ---- CLI -------------------------------------------------------------------------------------------------------------


def test_cli_hand_e5(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(tmp_path, capsys)
    assert code == 0 and err == ""
    assert out.splitlines() == E5_LINES


def test_cli_null_kappa(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(tmp_path, capsys, from_matrix([[0, 0, 0], [0, 3, 0], [0, 0, 0]]))
    assert code == 0
    assert out.splitlines() == ["kappa: n=3 po=1.0000 pe=1.0000",
                                "kappa=null kappa_w=null pabak=1.0000 ly_do_kappa=pe_bang_1 ly_do_kappa_w=mau_so_trong_so_bang_0",
                                "ket_qua=khong_xac_dinh nguong=0.6 loc=khong"]  # fmt: skip


def test_cli_row_order(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = E5
    code, out, _ = run(tmp_path, capsys, (a, b[::-1]))
    assert code == 0 and out.splitlines() == E5_LINES


def test_cli_sheet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake(*E5)
    assert run(tmp_path, capsys, read=fake)[0] == 0
    assert fake.sheets == ["Đợt 2", "Đợt 2"]


def test_cli_reader_pending(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(tmp_path, capsys, read=False)
    assert code == 2 and out == ""
    assert "LỖI: chưa có bộ đọc xlsx" in err


def test_cli_missing_extra_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = E5
    code, out, err = run(tmp_path, capsys, (a, [*b[1:], ("S_SENTINEL_99", H)]))
    assert code == 2 and out == ""
    assert "file B thiếu 1 id so với file A, thừa 1 id" in err


def test_cli_duplicate_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = E5
    code, _, err = run(tmp_path, capsys, (a, [*b, b[3]]))
    assert code == 2
    assert "file B: id trùng (dòng dữ liệu #4 và #11)" in err


@pytest.mark.parametrize("bad", ["", "auto", "ESCALATE", "SENTINEL_NHAN"])
def test_cli_bad_label(tmp_path: Path, capsys: pytest.CaptureFixture[str], bad: str) -> None:
    a, b = E5
    code, _, err = run(tmp_path, capsys, (a, [*b[:5], (b[5][0], bad), *b[6:]]))
    assert code == 2
    assert "file B dòng dữ liệu #6: nhãn ngoài 3 lớp" in err


def test_cli_bad_id_from_reader(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = E5
    code, _, err = run(tmp_path, capsys, ([("X_SENTINEL_x", A), *a[1:]], b))
    assert code == 2 and "file A dòng dữ liệu #1: id sai dạng" in err


def test_cli_filter_bo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Bỏ 1 ca AUTO/AUTO của E5 → bảng [[1,2,0],[0,3,1],[0,0,2]]: κ = 25/52, κ_w = 4/7, PABAK = 1/2."""
    code, out, _ = run(tmp_path, capsys, E5, "--bo", "S_SENTINEL_00")
    assert code == 0
    assert out.splitlines() == ["kappa: n=9 po=0.6667 pe=0.3580", "kappa=0.4808 kappa_w=0.5714 pabak=0.5000",
                                "ket_qua=KHONG_DAT nguong=0.6 loc=bo:1"]  # fmt: skip


def test_cli_filter_chi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Chỉ 4 ca hàng AUTO của E5 → [[2,2,0],0,0]: po = 1/2, pe = 1/2, κ = 0, κ_w = 0, PABAK = 1/4."""
    ids = ",".join(f"S_SENTINEL_{i:02d}" for i in range(4))
    code, out, _ = run(tmp_path, capsys, E5, "--chi", f" {ids} ,")
    assert code == 0
    assert out.splitlines() == ["kappa: n=4 po=0.5000 pe=0.5000", "kappa=0.0000 kappa_w=0.0000 pabak=0.2500",
                                "ket_qua=KHONG_DAT nguong=0.6 loc=chi:4"]  # fmt: skip


@pytest.mark.parametrize("flag", ["--bo", "--chi"])
def test_cli_filter_unknown_id(tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str) -> None:
    code, out, err = run(tmp_path, capsys, E5, flag, "S_SENTINEL_01,S_SENTINEL_77")
    assert code == 2 and out == ""
    assert f"LỖI: {flag}: 1 id không có trong file (phần tử #2)" in err


def test_cli_filter_empty_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(tmp_path, capsys, E5, "--bo", " , ")
    assert code == 2 and "--bo: danh sách id rỗng" in err


def test_cli_bo_chi_exclusive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(tmp_path, capsys, E5, "--bo", "S_SENTINEL_01", "--chi", "S_SENTINEL_02")
    assert code == 2 and out == ""
    assert "--bo và --chi: chỉ dùng một trong hai" in err


def test_cli_empty_after_filter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ids = ",".join(sid for sid, _ in E5[0])
    code, _, err = run(tmp_path, capsys, E5, "--bo", ids)
    assert code == 2 and "n = 0 sau khi lọc" in err


# Đích trong repo nằm dưới thư mục KHÔNG tồn tại: nếu kiểm "trong repo" bị đột biến tắt, lệnh ghi hỏng thay vì tạo file trong repo.
NO_DIR = "g9_khong_co_thu_muc"


@pytest.mark.parametrize("flag", ["--json", "--lech"])
def test_cli_output_in_repo_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str) -> None:
    target = REPO / NO_DIR / f"ra{flag[1:]}.out"
    code, out, err = run(tmp_path, capsys, E5, flag, str(target))
    assert code == 2 and out == ""
    assert f"{flag}: đường dẫn nằm trong repo" in err
    assert not (REPO / NO_DIR).exists()


def test_cli_output_in_repo_refused_symlink(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    link = tmp_path / "link"
    link.symlink_to(REPO / "backend", target_is_directory=True)
    code, _, err = run(tmp_path, capsys, E5, "--lech", str(link / NO_DIR / "lech.csv"))
    assert code == 2 and "--lech: đường dẫn nằm trong repo" in err
    assert not (REPO / "backend" / NO_DIR).exists()


def test_cli_output_exists_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = tmp_path / "cu.json"
    old.write_text("{}")
    code, _, err = run(tmp_path, capsys, E5, "--json", str(old))
    assert code == 2 and "--json: file đã tồn tại" in err
    assert old.read_text() == "{}"


def test_cli_output_same_path_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = str(tmp_path / "ra.out")
    code, _, err = run(tmp_path, capsys, E5, "--json", p, "--lech", p)
    assert code == 2 and "trùng đường dẫn" in err


def test_cli_json_full_precision(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_path = tmp_path / "ra" / "kappa.json"
    out_path.parent.mkdir()
    code, out, _ = run(tmp_path, capsys, E5, "--json", str(out_path))
    assert code == 0 and out.splitlines() == E5_LINES
    text = out_path.read_text(encoding="utf-8")
    for word in FORBIDDEN:
        assert word not in text
    data = json.loads(text)
    assert data["kappa"] == 6 / 11 and data["kappa_w"] == 26 / 41 and data["pabak"] == 0.55
    assert data["exact"] == {"po": "7/10", "pe": "17/50", "kappa": "6/11", "kappa_w": "26/41", "pabak": "11/20"}
    assert data["chi_tiet"]["kappa_w"]["po_exact"] == "17/20" and data["chi_tiet"]["kappa_w"]["pe_exact"] == "59/100"
    assert (data["n"], data["ket_qua"], data["nguong"], data["sheet"], data["loc"], data["so_lech"]) == (
        10, "KHONG_DAT", "3/5", "Đợt 2", "khong", 3)
    assert data["files_sha256"] == {"a": None, "b": None}  # bộ đọc giả: không có file


def test_cli_lech_content(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_path = tmp_path / "lech.csv"
    code, out, _ = run(tmp_path, capsys, E5, "--lech", str(out_path))
    assert code == 0 and out.splitlines() == E5_LINES
    with out_path.open(encoding="utf-8", newline="") as f:
        assert list(csv.reader(f)) == [["id", "nhan_a", "nhan_b"], ["S_SENTINEL_02", A, H], ["S_SENTINEL_03", A, H],
                                       ["S_SENTINEL_07", H, L]]  # fmt: skip


def test_cli_stdout_no_ids_labels(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Có ca lệch + ghi --lech: stdout vẫn chỉ 3 dòng tổng hợp (`run` kiểm không id, không nhãn)."""
    code, out, err = run(tmp_path, capsys, E5, "--lech", str(tmp_path / "lech.csv"), "--json", str(tmp_path / "k.json"))
    assert code == 0 and err == ""
    assert len(out.splitlines()) == 3
