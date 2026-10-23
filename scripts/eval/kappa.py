"""G9 — κ đồng thuận giữa 2 người gán nhãn CÙNG một đợt (Tuấn Anh chốt 23/10). Công thức: docstring `app.eval.stats` (khớp script
của phiên D): po, pe = Σ_c p_A(c)·p_B(c), κ Cohen 3 lớp = (po − pe)/(1 − pe) — ĐẠT khi κ ≥ 0,6; κ trọng số tuyến tính (tham khảo,
AUTO < HITL < ESCALATE_L2, w_ij = 1 − |i−j|/(k−1)); PABAK = (k·po − 1)/(k − 1), k = 3. Mẫu số 0 → null kèm lý do, kết luận
`khong_xac_dinh`.

"Gộp" KHÔNG cộng đợt 1 + đợt 2: gộp = chạy trên sheet đợt 2 đủ 66 dòng (17 tình huống đợt 1 đã được gán lại trong đợt 2). Không có
cờ cộng đợt.

  EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/kappa.py A.xlsx B.xlsx --sheet "Đợt 2" \
      [--bo S1,TH2 | --chi S1,TH2] [--json <ngoài repo>] [--lech <ngoài repo>]

Ba lớp:
- `load_cells(path, sheet)`: nạp ô của sheet từ xlsx — CHỜ G9-Q1 (openpyxl vào nhóm dev hay đọc bằng stdlib), hiện ném
  `XlsxReaderPending`.
- `parse_cells(rows)` (thuần): dòng 1 = tiêu đề; cột tìm theo tiêu đề `id` và `Nhãn` (so chính xác sau strip; thiếu/trùng → lỗi).
  Dòng dữ liệu = ô id khớp `ID_RE`. Dòng có nội dung mà id sai dạng: SAU dòng dữ liệu cuối → bỏ (dòng cam kết của người gán — có chữ
  ở cả cột Nhãn); GIỮA các dòng dữ liệu → lỗi. Dòng trống hoàn toàn → bỏ. `read_rows = parse_cells ∘ load_cells`.
- `main(argv, read=read_rows)`: ghép 2 danh sách (id, nhãn) THEO ID, lọc, tính, in. Test tiêm bộ đọc giả.

Lỗi (stderr `LỖI: …`, mã 2) — không bỏ qua: id sai dạng, id trùng, nhãn ngoài 3 lớp/trống, thiếu/thừa id giữa 2 file, id trong
`--bo`/`--chi` không có trong file, dùng cả `--bo` và `--chi`, n = 0, `--json`/`--lech` nằm trong repo (theo symlink), đã tồn tại
(không ghi đè) hoặc trùng nhau. Thông điệp chỉ có vị trí và số đếm — không id, không nhãn.

stdout (mã 0, kể cả KHONG_DAT): 3 dòng chỉ số tổng hợp, không id, không nhãn. `--json`: đủ chữ số (float + phân số dạng chuỗi) để
phiên D đối chiếu. `--lech`: CSV `id,nhan_a,nhan_b` các ca lệch, sắp theo id.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.eval.stats import KAPPA_LABELS, KAPPA_PASS, Agreement, Kappa, agreement

REPO = Path(__file__).resolve().parents[2]
ID_RE = re.compile(r"^(S|TH)[A-Za-z0-9._-]*$")
ID_HEADER, LABEL_HEADER = "id", "Nhãn"

type Rows = list[tuple[str, str]]
type Reader = Callable[[Path, str], Rows]


class InputError(ValueError):
    pass


class XlsxReaderPending(InputError):
    pass


def _cell(v: object) -> str:
    return "" if v is None else str(v).strip()


def _at(row: list[str], col: int) -> str:
    return row[col] if col < len(row) else ""


def parse_cells(rows: Sequence[Sequence[object]]) -> Rows:
    """Bảng ô (dòng 1 = tiêu đề) → [(id, nhãn)] theo thứ tự dòng. Vị trí lỗi `dòng #r` = số hàng trong sheet (tiêu đề = 1)."""
    if not rows:
        raise InputError("sheet rỗng (không có dòng tiêu đề)")
    header = [_cell(v) for v in rows[0]]
    cols: dict[str, int] = {}
    for name in (ID_HEADER, LABEL_HEADER):
        hits = [i for i, h in enumerate(header) if h == name]
        if len(hits) != 1:
            raise InputError(f"tiêu đề {name!r}: cần đúng 1 cột, thấy {len(hits)}")
        cols[name] = hits[0]
    id_col, label_col = cols[ID_HEADER], cols[LABEL_HEADER]
    body = [[_cell(v) for v in r] for r in rows[1:]]
    data = [i for i, row in enumerate(body) if ID_RE.match(_at(row, id_col))]
    last = data[-1] if data else -1
    out: Rows = []
    errors: list[str] = []
    for i, row in enumerate(body):
        if not any(row):
            continue
        if ID_RE.match(_at(row, id_col)):
            out.append((_at(row, id_col), _at(row, label_col)))
            continue
        if i > last:
            continue  # dòng cam kết sau dòng dữ liệu cuối
        errors.append(f"dòng #{i + 2}: id sai dạng")
    if errors:
        raise InputError("; ".join(errors))
    return out


def load_cells(path: Path, sheet: str) -> list[list[object]]:
    """Nạp ô của `sheet` (giá trị đã tính, như `data_only=True` của kiem_d6). CHỜ G9-Q1."""
    raise XlsxReaderPending("chưa có bộ đọc xlsx (chờ Tuấn Anh chốt openpyxl hay stdlib — G9-Q1)")


def read_rows(path: Path, sheet: str) -> Rows:
    return parse_cells(load_cells(path, sheet))


def index_rows(rows: Rows, who: str) -> dict[str, str]:
    """[(id, nhãn)] → {id: nhãn}; id sai dạng, id trùng, nhãn ngoài 3 lớp → lỗi (gom hết)."""
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    errors: list[str] = []
    for i, (raw_id, raw_label) in enumerate(rows, start=1):
        rid, lab = raw_id.strip(), raw_label.strip()
        if not ID_RE.match(rid):
            errors.append(f"file {who} dòng dữ liệu #{i}: id sai dạng")
            continue
        if lab not in KAPPA_LABELS:
            errors.append(f"file {who} dòng dữ liệu #{i}: nhãn ngoài 3 lớp")
        if rid in seen:
            errors.append(f"file {who}: id trùng (dòng dữ liệu #{seen[rid]} và #{i})")
            continue
        seen[rid] = i
        out[rid] = lab
    if errors:
        raise InputError("; ".join(errors))
    return out


def _id_list(raw: str, flag: str) -> list[str]:
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    if not ids:
        raise InputError(f"{flag}: danh sách id rỗng")
    return ids


def select_ids(ids: set[str], bo: str | None, chi: str | None) -> tuple[set[str], str]:
    """Lọc tập id chung: `--bo` bỏ, `--chi` chỉ giữ. Trả (tập còn lại, mô tả lọc cho stdout — chỉ số đếm)."""
    if bo is not None and chi is not None:
        raise InputError("--bo và --chi: chỉ dùng một trong hai")
    if bo is None and chi is None:
        return ids, "khong"
    flag, listed = ("--bo", _id_list(bo, "--bo")) if bo is not None else ("--chi", _id_list(chi or "", "--chi"))
    unknown = [i for i, x in enumerate(listed, start=1) if x not in ids]
    if unknown:
        raise InputError(f"{flag}: {len(unknown)} id không có trong file (phần tử " + ", ".join(f"#{i}" for i in unknown) + ")")
    if bo is not None:
        keep = ids - set(listed)
    else:
        keep = ids & set(listed)
    return keep, f"{flag[2:]}:{len(set(listed))}"


def _output_path(p: Path | None, flag: str) -> Path | None:
    if p is None:
        return None
    r = p.expanduser().resolve()
    if r.is_relative_to(REPO):
        raise InputError(f"{flag}: đường dẫn nằm trong repo — từ chối (ghi ra ngoài repo)")
    if r.exists():
        raise InputError(f"{flag}: file đã tồn tại — không ghi đè")
    return r


def _f(x: Fraction | None) -> str:
    return "null" if x is None else f"{float(x):.4f}"


def _s(x: Fraction | None) -> str | None:
    return None if x is None else str(x)


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _kappa_json(k: Kappa) -> dict[str, Any]:
    return {"value": k.value, "exact": _s(k.exact), "po": float(k.po), "po_exact": _s(k.po), "pe": float(k.pe),
            "pe_exact": _s(k.pe), "ly_do": k.reason}  # fmt: skip


def summary(res: Agreement, loc: str) -> list[str]:
    reasons = "".join(f" ly_do_{name}={k.reason}" for name, k in (("kappa", res.kappa), ("kappa_w", res.kappa_w)) if k.reason)
    return [
        f"kappa: n={res.n} po={_f(res.po)} pe={_f(res.pe)}",
        f"kappa={_f(res.kappa.exact)} kappa_w={_f(res.kappa_w.exact)} pabak={_f(res.pabak)}{reasons}",
        f"ket_qua={res.verdict} nguong={float(KAPPA_PASS)} loc={loc}",
    ]


def main(argv: Sequence[str] | None = None, read: Reader = read_rows) -> int:
    ap = argparse.ArgumentParser(description="κ đồng thuận 2 người gán nhãn (G9)")
    ap.add_argument("a", type=Path, help="xlsx người gán A")
    ap.add_argument("b", type=Path, help="xlsx người gán B")
    ap.add_argument("--sheet", required=True, help='tên sheet, vd "Đợt 2"')
    ap.add_argument("--bo", help="bỏ các id (phân cách bằng dấu phẩy)")
    ap.add_argument("--chi", help="chỉ giữ các id (phân cách bằng dấu phẩy)")
    ap.add_argument("--json", type=Path, help="ghi chỉ số đủ chữ số (ngoài repo)")
    ap.add_argument("--lech", type=Path, help="ghi id + 2 nhãn của các ca lệch (ngoài repo)")
    args = ap.parse_args(argv)
    try:
        json_out, lech_out = _output_path(args.json, "--json"), _output_path(args.lech, "--lech")
        if json_out is not None and json_out == lech_out:
            raise InputError("--json và --lech: trùng đường dẫn")
        rows_a, rows_b = read(args.a, args.sheet), read(args.b, args.sheet)
        a, b = index_rows(rows_a, "A"), index_rows(rows_b, "B")
        missing, extra = len(a.keys() - b.keys()), len(b.keys() - a.keys())
        if missing or extra:
            raise InputError(f"file B thiếu {missing} id so với file A, thừa {extra} id")
        keep, loc = select_ids(set(a), args.bo, args.chi)
        if not keep:
            raise InputError("n = 0 sau khi lọc")
        ids = sorted(keep)
        res = agreement([a[i] for i in ids], [b[i] for i in ids])
    except InputError as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 2
    lech = [(i, a[i], b[i]) for i in ids if a[i] != b[i]]
    for line in summary(res, loc):
        print(line)
    if json_out is not None:
        data = {
            "n": res.n, "po": float(res.po), "pe": float(res.pe), "kappa": res.kappa.value, "kappa_w": res.kappa_w.value,
            "pabak": float(res.pabak), "ket_qua": res.verdict, "nguong": str(KAPPA_PASS),
            "exact": {"po": _s(res.po), "pe": _s(res.pe), "kappa": _s(res.kappa.exact), "kappa_w": _s(res.kappa_w.exact),
                      "pabak": _s(res.pabak)},
            "chi_tiet": {"kappa": _kappa_json(res.kappa), "kappa_w": _kappa_json(res.kappa_w)},
            "sheet": args.sheet, "loc": loc, "so_lech": len(lech),
            "files_sha256": {"a": _sha(args.a), "b": _sha(args.b)},
        }  # fmt: skip
        with json_out.open("x", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    if lech_out is not None:
        with lech_out.open("x", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "nhan_a", "nhan_b"])
            w.writerows(lech)
    return 0


if __name__ == "__main__":
    sys.exit(main())
