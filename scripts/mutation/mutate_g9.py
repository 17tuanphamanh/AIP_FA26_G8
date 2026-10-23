"""Mutation tay G9 — (A) κ đồng thuận (`stats.py`: `cohen_kappa`, `weighted_kappa_linear`, `pabak`, `agreement`;
`scripts/eval/kappa.py`: `parse_cells`, ghép, lọc, đầu ra) + (B) hàm băm dùng chung (`dataset.py`: `scenario_files`, `file_sha256`,
`dataset_sha256`) + CI kiểm `eval/SPLIT.md` (`scripts/eval/check_split.py`); plan G9 mục Mutation. Khung giống `mutate_g1.py`: mỗi
đột biến áp lên file thật, chạy test eval, khôi phục trong `finally`, so md5 + `git diff --stat` + `git status --porcelain` trước/sau
(đột biến tắt kiểm "trong repo" của kappa.py không được để lại file mới trong repo).

Chốt N3 VIẾT LẠI ở đây, KHÔNG import `n3.py` (file đó nằm trong danh sách chặn đọc tới 25/10 — import = chạy code của file bị chặn):
(a) file đích còn chữ `MUTATION` → dừng; (b) mốc xanh một lần trước khi đột biến; (c) sau khi chạy: md5 khớp, `git diff --stat` khớp,
không file đích nào còn chữ `MUTATION`; (d) chuỗi gốc của các script đột biến nhắm CÙNG file (`OLD_SCRIPTS`) vẫn xuất hiện ĐÚNG 1 lần
trong file đó nếu có xuất hiện — đọc VĂN BẢN script bằng `ast` (không import → không chạy n3.py).

  uv run python scripts/mutation/mutate_g9.py
  uv run python scripts/mutation/mutate_g9.py --only M-G9-26
  uv run python scripts/mutation/mutate_g9.py --check-old    # chỉ chạy N3d

Chỉ unit (dữ liệu tổng hợp trong tmp_path, không Docker, không DB). Không chạy check_split trên dữ liệu thật. Không đọc `.env`.
"""

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
MARK = "MUTATION"


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, "-q", "-p", "no:cacheprovider"]


ST = "backend/app/eval/stats.py"
KP = "scripts/eval/kappa.py"
DS = "backend/app/eval/dataset.py"
CS = "scripts/eval/check_split.py"
UT = pt("backend/tests/unit/eval")
# N3d: file đích → script đột biến có chuỗi gốc nhắm file đó.
OLD_SCRIPTS: dict[str, tuple[str, ...]] = {
    ST: ("mutate_t29.py", "mutate_g9.py"),
    KP: ("mutate_g9.py",),
    DS: ("mutate_g2.py", "mutate_v11.py", "mutate_g9.py"),
    CS: ("mutate_g9.py",),
}


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ (không có "[…]" → mọi tham số của test đó đều tính)


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


def _off(rel: str, old: str, tag: str) -> tuple[str, str, str, int]:
    """`if <điều kiện>:` → `if False:` (giữ thụt lề)."""
    indent = old[: len(old) - len(old.lstrip())]
    return one(rel, old, f"{indent}if False:  # MUTATION {tag}\n")


def _swap(rel: str, old: str, new: str, tag: str) -> tuple[str, str, str, int]:
    return one(rel, old, new.rstrip("\n") + f"  # MUTATION {tag}\n")


# ---- stats.py — κ, κ_w, PABAK ----------------------------------------------------------------------------------------

_PE = "    pe = sum((w[i][j] * Fraction(row[i] * col[j], n * n) for i in range(k) for j in range(k)), Fraction(0))\n"
_EXACT = "    exact = (po - pe) / (1 - pe)\n"
_PE_ONE = "    if pe == 1:\n"
_PASS = '    return "DAT" if kappa.exact >= KAPPA_PASS else "KHONG_DAT"\n'
_UNDEF = '    if kappa.exact is None:\n        return "khong_xac_dinh"\n'
_LINEAR = "    w = [[1 - Fraction(abs(i - j), k - 1) for j in range(k)] for i in range(k)]\n"
_W_REASON = '    return _kappa(n, t, w, "mau_so_trong_so_bang_0")\n'
_PABAK = "    return (k * po - 1) / (k - 1)\n"
_EMPTY_AB = "    if not a:\n"
_LABEL_SET = "    if any(x not in idx for x in (*a, *b)):\n"
_LEN = "    if len(a) != len(b):\n"

# ---- kappa.py --------------------------------------------------------------------------------------------------------

_PAIR = "        res = agreement([a[i] for i in ids], [b[i] for i in ids])\n"
_MISS_EXTRA = "        if missing or extra:\n"
_DUP_ID = "        if rid in seen:\n"
_LAB = "        if lab not in KAPPA_LABELS:\n"
_READ = "        rows_a, rows_b = read(args.a, args.sheet), read(args.b, args.sheet)\n"
_CHI = "        keep = ids & set(listed)\n"
_UNKNOWN = "    if unknown:\n"
_BOTH = "    if bo is not None and chi is not None:\n"
_IN_REPO = "    if r.is_relative_to(REPO):\n"
_RESOLVE = "    r = p.expanduser().resolve()\n"
_EXISTS = "    if r.exists():\n"
_LECH = "    lech = [(i, a[i], b[i]) for i in ids if a[i] != b[i]]\n"
_JSON_K = '"kappa": res.kappa.value, "kappa_w"'
_COLS = "    id_col, label_col = cols[ID_HEADER], cols[LABEL_HEADER]\n"
_AFTER_LAST = "        if i > last:\n"
_BAD_BETWEEN = '        errors.append(f"dòng #{i + 2}: id sai dạng")\n'
_HEADER_ONE = "        if len(hits) != 1:\n"
_BLANK = "        if not any(row):\n"

MUT_A: list[Mutation] = [
    Mutation("M-G9-1 pe = Σ p_A² (bỏ biên của B)",
             [_swap(ST, _PE, _PE.replace("row[i] * col[j]", "row[i] * row[j]"), "M-G9-1")], UT, ["test_kappa_hand[E5]"]),
    Mutation("M-G9-2 κ = po − pe (bỏ chia 1 − pe)",
             [_swap(ST, _EXACT, "    exact = po - pe", "M-G9-2")], UT, ["test_kappa_hand[E3]", "test_kappa_hand[E5]"]),
    Mutation("M-G9-3 bỏ nhánh pe = 1 (chia cho 0)",
             [_off(ST, _PE_ONE, "M-G9-3")], UT, ["test_kappa_pe_one_null", "test_kappa_hand[E2]", "test_cli_null_kappa"]),
    Mutation("M-G9-4 ngưỡng > thay ≥",
             [_swap(ST, _PASS, _PASS.replace(">=", ">"), "M-G9-4")], UT, ["test_verdict_boundary_06", "test_kappa_hand[E6]"]),
    Mutation("M-G9-5 κ null → KHONG_DAT",
             [one(ST, _UNDEF, '    if kappa.exact is None:\n        return "KHONG_DAT"  # MUTATION M-G9-5\n')], UT,
             ["test_verdict_undefined", "test_kappa_hand[E2]", "test_cli_null_kappa"]),
    Mutation("M-G9-6 κ_w không trọng số (w = đơn vị)",
             [_swap(ST, _LINEAR, "    w = [[Fraction(int(i == j)) for j in range(k)] for i in range(k)]", "M-G9-6")], UT,
             ["test_kappa_hand[E4]", "test_kappa_hand[E5]"]),
    Mutation("M-G9-7 κ_w trọng số bậc hai",
             [_swap(ST, _LINEAR, _LINEAR.replace("Fraction(abs(i - j), k - 1)", "Fraction(abs(i - j), k - 1) ** 2"), "M-G9-7")], UT,
             ["test_kappa_hand[E4]"]),
    Mutation("M-G9-8 κ_w null ghi lý do của κ",
             [_swap(ST, _W_REASON, '    return _kappa(n, t, w, "pe_bang_1")', "M-G9-8")], UT,
             ["test_kappa_pe_one_null", "test_kappa_hand[E2]", "test_cli_null_kappa"]),
    Mutation("M-G9-9 PABAK dùng k = 2",
             [_swap(ST, _PABAK, "    return (2 * po - 1) / (2 - 1)", "M-G9-9")], UT, ["test_kappa_hand", "test_cli_hand_e5"]),
    Mutation("M-G9-10 n = 0 không báo lỗi",
             [_off(ST, _EMPTY_AB, "M-G9-10")], UT, ["test_kappa_empty"]),
    Mutation("M-G9-11 nhãn ngoài tập không báo lỗi (hàm thuần)",
             [_off(ST, _LABEL_SET, "M-G9-11")], UT, ["test_kappa_bad_label"]),
    Mutation("M-G9-41 độ dài khác nhau không báo lỗi riêng",
             [_off(ST, _LEN, "M-G9-41")], UT, ["test_kappa_len_mismatch"]),
    Mutation("M-G9-12 CLI ghép theo vị trí dòng thay id",
             [_swap(KP, _PAIR, "        res = agreement([lab for _, lab in rows_a], [lab for _, lab in rows_b])", "M-G9-12")], UT,
             ["test_cli_row_order"]),
    Mutation("M-G9-13 lấy giao id, không báo thiếu/thừa",
             [_off(KP, _MISS_EXTRA, "M-G9-13")], UT, ["test_cli_missing_extra_id"]),
    Mutation("M-G9-14 bỏ kiểm id trùng",
             [_off(KP, _DUP_ID, "M-G9-14")], UT, ["test_cli_duplicate_id"]),
    Mutation("M-G9-15 CLI bỏ kiểm nhãn (nhãn trống/sai lọt xuống hàm thuần)",
             [_off(KP, _LAB, "M-G9-15")], UT, ["test_cli_bad_label"]),
    Mutation("M-G9-16 không truyền --sheet xuống bộ đọc",
             [_swap(KP, _READ, _READ.replace("args.sheet", '"Đợt 1"'), "M-G9-16")], UT, ["test_cli_sheet"]),
    Mutation("M-G9-17 --chi làm như --bo",
             [_swap(KP, _CHI, "        keep = ids - set(listed)", "M-G9-17")], UT, ["test_cli_filter_chi"]),
    Mutation("M-G9-18 id lọc không có trong file → không lỗi",
             [_off(KP, _UNKNOWN, "M-G9-18")], UT, ["test_cli_filter_unknown_id"]),
    Mutation("M-G9-19 --bo + --chi cùng lúc không lỗi",
             [_off(KP, _BOTH, "M-G9-19")], UT, ["test_cli_bo_chi_exclusive"]),
    Mutation("M-G9-20 bỏ kiểm đầu ra nằm trong repo",
             [_off(KP, _IN_REPO, "M-G9-20")], UT, ["test_cli_output_in_repo_refused", "test_cli_output_in_repo_refused_symlink"]),
    Mutation("M-G9-21 kiểm repo không theo symlink",
             [_swap(KP, _RESOLVE, "    r = p.expanduser().absolute()", "M-G9-21")], UT, ["test_cli_output_in_repo_refused_symlink"]),
    Mutation("M-G9-42 bỏ kiểm file đã tồn tại",
             [_off(KP, _EXISTS, "M-G9-42")], UT, ["test_cli_output_exists_refused"]),
    Mutation("M-G9-22 stdout in các ca lệch",
             [one(KP, _LECH, _LECH + "    print(lech)  # MUTATION M-G9-22\n")], UT,
             ["test_cli_stdout_no_ids_labels", "test_cli_hand_e5"]),
    Mutation("M-G9-23 --json làm tròn κ 4 chữ số",
             [one(KP, _JSON_K, '"kappa": round(res.kappa.value or 0.0, 4), "MUTATION": "M-G9-23", "kappa_w"')], UT,
             ["test_cli_json_full_precision"]),
    Mutation("M-G9-43 id lấy ở cột 4 cố định (cột Người dùng nói)",
             [_swap(KP, _COLS, "    id_col, label_col = 3, cols[LABEL_HEADER]", "M-G9-43")], UT,
             ["test_parse_cells_real_layout", "test_parse_cells_columns_moved"]),
    Mutation("M-G9-44 không bỏ dòng cam kết sau dòng dữ liệu cuối",
             [_off(KP, _AFTER_LAST, "M-G9-44")], UT, ["test_parse_cells_real_layout", "test_parse_cells_commit_row_skipped"]),
    Mutation("M-G9-45 dòng id sai dạng ở giữa không lỗi",
             [_swap(KP, _BAD_BETWEEN, "        pass", "M-G9-45")], UT, ["test_parse_cells_bad_id_between_red"]),
    Mutation("M-G9-46 tiêu đề trùng không lỗi",
             [_swap(KP, _HEADER_ONE, "        if not hits:", "M-G9-46")], UT, ["test_parse_cells_header_red"]),
    Mutation("M-G9-47 dòng trống ở giữa → lỗi",
             [_off(KP, _BLANK, "M-G9-47")], UT, ["test_parse_cells_blank_row_between_skipped"]),
]  # fmt: skip

# ---- dataset.py — hàm băm dùng chung ---------------------------------------------------------------------------------

_SORTED = "    for name, sha in sorted(pairs):\n"
_LINE = '        h.update(f"{name}\\0{sha}\\n".encode())\n'

# ---- check_split.py --------------------------------------------------------------------------------------------------

_LOCKED = "    if split.locked:\n"
_THIEU = "    thieu = len(set(split.files) - set(current))\n"
_THUA = "    thua = [i for i, name in enumerate(names, start=1) if name not in split.files]\n"
_DS_OK = "    ds_ok = dataset_sha256(current.items()) == split.dataset_sha256\n"
_UNLOCKED = '    print("KẾT QUẢ: CẢNH BÁO (locked: false)")\n    return OK\n'
_ABSENT = '        print("split: chua_co")\n        return OK\n'
_DUP = "            if key in seen:\n"
_RANGE = "    if out:\n"
_EMPTY = "    if empty:\n"
_SELF = "    if dataset_sha256(split.files.items()) != split.dataset_sha256:\n"
_PROBLEMS = '    problems = [f"file #{i}/{n}: sha lệch" for i in lech]'
_CURRENT = "    current = {p.name: file_sha256(p.read_bytes()) for p in scenario_files(scenarios)} if scenarios.is_dir() else {}\n"
_CONFIG = '    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)\n'
_WHERE = '        where = sorted({str(err["loc"][0]) if err["loc"] else "<gốc>" for err in e.errors(include_url=False, include_input=False)})\n'

_RED = ["test_split_sha_mismatch_red", "test_split_missing_file_red", "test_split_extra_file_red"]

MUT_B: list[Mutation] = [
    Mutation("M-G9-24 dataset_sha256 bỏ sắp theo tên",
             [_swap(DS, _SORTED, "    for name, sha in pairs:", "M-G9-24")], UT, ["test_dataset_sha_order_independent"]),
    Mutation("M-G9-25 dataset_sha256 bỏ \\0 giữa tên và sha",
             [_swap(DS, _LINE, '        h.update(f"{name}{sha}\\n".encode())', "M-G9-25")], UT,
             ["test_dataset_sha_pinned", "test_dataset_sha_shared_equals_load", "test_split_ok"]),
    Mutation("M-G9-26 locked true mà lệch → mã 0",
             [_off(CS, _LOCKED, "M-G9-26")], UT, [*_RED, "test_split_scenarios_dir_missing_red", "test_split_log_no_names_sha"]),
    Mutation("M-G9-27 không đếm file thiếu",
             [_swap(CS, _THIEU, "    thieu = 0", "M-G9-27")], UT, ["test_split_missing_file_red", "test_split_log_no_names_sha"]),
    Mutation("M-G9-28 không đếm file thừa",
             [_swap(CS, _THUA, "    thua: list[int] = []", "M-G9-28")], UT, ["test_split_extra_file_red", "test_split_log_no_names_sha"]),
    Mutation("M-G9-29 bỏ so dataset_sha256 với băm lại",
             [_swap(CS, _DS_OK, "    ds_ok = True", "M-G9-29")], UT, _RED),
    Mutation("M-G9-30 locked false mà lệch vẫn mã 1",
             [one(CS, _UNLOCKED, _UNLOCKED.replace("return OK", "return DATA_MISMATCH  # MUTATION M-G9-30"))], UT,
             ["test_split_unlocked_warns"]),
    Mutation("M-G9-31 chưa có SPLIT.md → mã 2",
             [one(CS, _ABSENT, _ABSENT.replace("return OK", "return BAD_SPLIT  # MUTATION M-G9-31"))], UT, ["test_split_absent_ok"]),
    Mutation("M-G9-32 loader nhận khoá trùng (họ ở 2 phần lọt)",
             [_off(CS, _DUP, "M-G9-32")], UT, ["test_split_family_two_parts_red"]),
    Mutation("M-G9-33 bỏ kiểm phần ∈ 1..k",
             [_off(CS, _RANGE, "M-G9-33")], UT, ["test_split_part_out_of_range"]),
    Mutation("M-G9-34 log in tên file thay #i/N",
             [one(CS, _PROBLEMS, '    problems = [f"{names[i - 1]}: sha lệch MUTATION M-G9-34" for i in lech]')], UT,
             ["test_split_sha_mismatch_red", "test_split_log_no_names_sha"]),
    Mutation("M-G9-35 băm đệ quy (rglob) thay scenario_files",
             [_swap(CS, _CURRENT, "    current = {p.name: file_sha256(p.read_bytes()) for p in sorted(q for q in scenarios.rglob('*') "
                                  "if q.is_file())} if scenarios.is_dir() else {}", "M-G9-35")], UT, ["test_split_top_level_only"]),
    Mutation("M-G9-36 bỏ kiểm phần rỗng",
             [_off(CS, _EMPTY, "M-G9-36")], UT, ["test_split_empty_part_red"]),
    Mutation("M-G9-37 bỏ kiểm SPLIT.md tự mâu thuẫn",
             [_off(CS, _SELF, "M-G9-37")], UT, ["test_split_self_inconsistent_red"]),
    Mutation("M-G9-38 SPLIT nhận khoá lạ",
             [_swap(CS, _CONFIG, _CONFIG.replace('extra="forbid"', 'extra="ignore"'), "M-G9-38")], UT,
             ["test_split_bad_structure[extra_key]"]),
    Mutation("M-G9-39 lỗi cấu trúc in đủ loc (lộ tên file)",
             [_swap(CS, _WHERE, _WHERE.replace('str(err["loc"][0]) if err["loc"] else "<gốc>"', '".".join(map(str, err["loc"]))'),
                    "M-G9-39")], UT, ["test_split_bad_structure[sha_not_hex]", "test_split_bad_structure[subdir_name]"]),
]  # fmt: skip

MUTATIONS_ALL = MUT_A + MUT_B
MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    at = sys.argv.index("--only") + 1
    prefix = sys.argv[at] if at < len(sys.argv) else ""
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix + " ")]


def test_env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def git_status() -> str:
    """Kể cả file chưa theo dõi — bắt file mới mà đột biến làm test ghi vào repo."""
    cmd = ["git", "status", "--porcelain", "--untracked-files=all"]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=False).stdout


def marked(files: list[str]) -> list[str]:
    return [rel for rel in files if MARK in (REPO / rel).read_text(encoding="utf-8")]


def _docstrings(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _line_strings(path: Path) -> set[str]:
    """Hằng chuỗi có xuống dòng và có chữ (bỏ docstring, bỏ mảnh của f-string) — ứng viên chuỗi gốc của đột biến."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values)
    return {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and "\n" in n.value and n.value.strip()
    }


def check_old() -> list[str]:
    """N3d: chuỗi của các script đột biến có mặt trong file đích thì phải đúng 1 lần (mọi edit dùng `one`)."""
    bad: list[str] = []
    for target, scripts in OLD_SCRIPTS.items():
        text = (REPO / target).read_text(encoding="utf-8")
        for name in scripts:
            for s in sorted(_line_strings(REPO / "scripts/mutation" / name)):
                if text.count(s) > 1:
                    bad.append(f"{target} ← {name}: {s.strip()[:60]!r} ×{text.count(s)}")
    return bad


def guard(files: list[str], cmds: list[list[str]], env: dict[str, str]) -> int | None:
    """N3 (viết lại, không import n3): (a) không file đích nào còn dấu `MUTATION`; (d) chuỗi gốc cũ đúng 1 lần; (b) mốc xanh."""
    left = marked(files)
    if left:
        print(f"DỪNG (N3a): file đích còn chữ {MARK!r} {left} — khôi phục tay trước")
        return 2
    dup = check_old()
    if dup:
        print("DỪNG (N3d): chuỗi gốc đột biến xuất hiện > 1 lần trong file đích:")
        print("    " + "\n    ".join(dup))
        return 2
    print("N3d: " + "; ".join(f"{t} ← {', '.join(s)}" for t, s in OLD_SCRIPTS.items()) + " — không chuỗi nào lặp")
    for cmd in {tuple(c): c for c in cmds}.values():
        out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        if out.returncode != 0:
            print(f"DỪNG (N3b): mốc chưa xanh — {' '.join(cmd)}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
            return 2
    print("mốc xanh: " + " | ".join(" ".join(c) for c in {tuple(c): c for c in cmds}.values()))
    return None


def _hit(test: str, failed: list[str]) -> bool:
    if "[" in test:
        return any(f.endswith("::" + test) for f in failed)
    return any(f.endswith("::" + test) or ("::" + test + "[") in f for f in failed)


def main() -> int:
    if "--check-old" in sys.argv:
        dup = check_old()
        for target, scripts in OLD_SCRIPTS.items():
            text = (REPO / target).read_text(encoding="utf-8")
            n = sum(len(_line_strings(REPO / "scripts/mutation" / s)) for s in scripts)
            present = {s for name in scripts for s in _line_strings(REPO / "scripts/mutation" / name) if s in text}
            print(f"N3d: {target}: {n} hằng chuỗi nhiều dòng trong {len(scripts)} script; {len(present)} có mặt")
        for d in dup:
            print(f"    LẶP {d}")
        print("N3d: ĐẠT" if not dup else "N3d: KHÔNG ĐẠT")
        return 1 if dup else 0
    if not MUTATIONS:
        print("DỪNG: không có đột biến nào khớp `--only` (mã: " + ", ".join(m.name.split(" ")[0] for m in MUTATIONS_ALL) + ")")
        return 2
    env = test_env()
    files = sorted({rel for m in MUTATIONS for rel, *_ in m.edits})
    stop = guard(files, [m.cmd for m in MUTATIONS], env)
    if stop is not None:
        return stop
    before = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 trước  {before[rel]}  {rel}")
    diff_before = git_diff_stat()
    status_before = git_status()
    bad = 0
    for m in MUTATIONS:
        originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel, *_ in m.edits}
        mutated = dict(originals)
        wrong = [f"{rel}: {mutated[rel].count(old)}/{n}" for rel, old, _, n in m.edits if mutated[rel].count(old) != n]
        if wrong:
            print(f"!! {m.name}: chuỗi gốc không khớp số lần {wrong} — bỏ qua")
            bad += 1
            continue
        for rel, old, new, _ in m.edits:
            mutated[rel] = mutated[rel].replace(old, new)
        unmarked = [rel for rel, text in mutated.items() if MARK not in text]
        if unmarked:
            print(f"!! {m.name}: file đột biến thiếu chữ {MARK!r} {unmarked} — bỏ qua (N3a không bắt được nếu bị giết)")
            bad += 1
            continue
        try:
            for rel, text in mutated.items():
                (REPO / rel).write_text(text, encoding="utf-8")
            out = subprocess.run(m.cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        finally:
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?::\w+(?:\[.*?\])?)(?: - |$)", out.stdout, re.MULTILINE)))
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in m.expect if not _hit(e, failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        bad += bool(missing)
        print(f"{m.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
    after = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 sau    {after[rel]}  {rel}")
    assert after == before, "md5 khác sau khôi phục!"
    print("md5 sau khôi phục: khớp")
    assert git_diff_stat() == diff_before, "git diff --stat khác lúc đầu!"
    print("git diff --stat: khớp lúc đầu")
    assert git_status() == status_before, "git status --porcelain khác lúc đầu (file mới trong repo?)"
    print("git status --porcelain (kể cả file chưa theo dõi): khớp lúc đầu")
    assert not marked(files), f"còn chữ {MARK!r} trong file đích sau khôi phục!"
    print(f"không còn chữ {MARK!r} trong file đích")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
