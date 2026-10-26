"""G9 — CI kiểm mã băm `eval/SPLIT.md` (P8 v1.4 §4.3: SPLIT.md = họ → phần 1..k, seed, sha256 từng file; "CI kiểm sau khoá nhãn").

SPLIT.md do phiên git sinh lúc khoá nhãn; script này CHỈ kiểm. SPLIT.md có đúng MỘT khối ```yaml:

    seed: <int>
    k: <int ≥ 2>
    dataset_sha256: <64 hex>
    files: {<tên file kịch bản>: <64 hex>}
    families: {<họ>: <phần 1..k>}
    locked: <bool>

Băm lại `eval/scenarios/*.yaml|*.yml` (cấp 1) bằng ĐÚNG hàm của `Dataset.sha256` (`app.eval.dataset.scenario_files`, `file_sha256`,
`dataset_sha256` — không viết lại công thức).

Mã thoát:
- 0: khớp; hoặc chưa có SPLIT.md (cảnh báo — trước khoá nhãn); hoặc `locked: false` mà dữ liệu lệch (cảnh báo).
- 1: `locked: true` mà dữ liệu lệch — file thiếu/thừa so với `files`, sha một file lệch, `dataset_sha256` lệch so với băm lại.
- 2: SPLIT.md sai cấu trúc — đỏ CẢ KHI `locked: false` (G9-Q4): không đúng 1 khối yaml, YAML lỗi, khoá trùng (vd một họ ghi ở 2 phần),
  khoá lạ/thiếu/sai kiểu, phần ngoài 1..k, phần rỗng (G9-Q5), `dataset_sha256` không khớp chính `files` của SPLIT.md.
Không so tập họ với `family` của kịch bản (G9-Q5): sha từng file đã khoá nội dung.

Log CHỈ số đếm và vị trí `file #i/N` / `họ #i/M` (thứ tự tên tăng dần) — không tên file, không tên họ, không sha.

  EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/check_split.py [--split eval/SPLIT.md] [--scenarios eval/scenarios]
"""

import argparse
import re
import sys
from collections.abc import Hashable, Sequence
from pathlib import Path
from typing import Annotated, Any

import yaml
from app.eval.dataset import dataset_sha256, file_sha256, scenario_files
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

REPO = Path(__file__).resolve().parents[2]
OK, DATA_MISMATCH, BAD_SPLIT = 0, 1, 2

Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
FileName = Annotated[str, StringConstraints(pattern=r"^[^/\\\x00]+$")]
Family = Annotated[str, StringConstraints(min_length=1)]

_BLOCK = re.compile(r"^```ya?ml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


class Split(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    seed: int
    k: int = Field(ge=2)
    dataset_sha256: Sha
    files: dict[FileName, Sha] = Field(min_length=1)
    families: dict[Family, int] = Field(min_length=1)
    locked: bool


class BadSplit(ValueError):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader từ chối khoá trùng trong mapping (mặc định PyYAML giữ khoá SAU, nuốt mất "họ ghi ở 2 phần")."""


def _mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Hashable] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if isinstance(key, Hashable):
            if key in seen:
                raise BadSplit(f"khoá trùng trong khối yaml (dòng {key_node.start_mark.line + 1})")
            seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse_split(text: str) -> Split:
    blocks = _BLOCK.findall(text)
    if len(blocks) != 1:
        raise BadSplit(f"cần đúng 1 khối ```yaml, thấy {len(blocks)}")
    try:
        data = yaml.load(blocks[0], Loader=_UniqueKeyLoader)  # SafeLoader con — chỉ thêm kiểm khoá trùng
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise BadSplit("YAML lỗi" + (f" dòng {mark.line + 1}" if mark is not None else "")) from None
    try:
        split = Split.model_validate(data)
    except ValidationError as e:
        # Chỉ tên trường cấp 1: loc sâu hơn chứa tên file / tên họ.
        where = sorted({str(err["loc"][0]) if err["loc"] else "<gốc>" for err in e.errors(include_url=False, include_input=False)})
        raise BadSplit(f"sai cấu trúc ({', '.join(where)})") from None
    fams = sorted(split.families)
    out = [i for i, f in enumerate(fams, start=1) if not 1 <= split.families[f] <= split.k]
    if out:
        raise BadSplit(f"{len(out)} họ có phần ngoài 1..{split.k}: " + ", ".join(f"họ #{i}/{len(fams)}" for i in out))
    empty = sorted(set(range(1, split.k + 1)) - set(split.families.values()))
    if empty:
        raise BadSplit(f"phần rỗng (không họ nào): {', '.join(map(str, empty))}")
    if dataset_sha256(split.files.items()) != split.dataset_sha256:
        raise BadSplit("dataset_sha256 không khớp chính danh sách files của SPLIT.md")
    return split


def check(split_path: Path, scenarios: Path) -> int:
    if not split_path.is_file():
        print("CẢNH BÁO: chưa có SPLIT.md — bỏ qua kiểm mã băm (trước khoá nhãn)", file=sys.stderr)
        print("split: chua_co")
        return OK
    try:
        split = parse_split(split_path.read_text(encoding="utf-8"))
    except (BadSplit, UnicodeDecodeError) as e:
        print(f"LỖI: SPLIT.md: {e}", file=sys.stderr)
        print("KẾT QUẢ: ĐỎ (SPLIT.md sai cấu trúc)")
        return BAD_SPLIT
    current = {p.name: file_sha256(p.read_bytes()) for p in scenario_files(scenarios)} if scenarios.is_dir() else {}
    names = sorted(current)
    n = len(names)
    lech = [i for i, name in enumerate(names, start=1) if name in split.files and split.files[name] != current[name]]
    thua = [i for i, name in enumerate(names, start=1) if name not in split.files]
    thieu = len(set(split.files) - set(current))
    ds_ok = dataset_sha256(current.items()) == split.dataset_sha256
    khop = n - len(lech) - len(thua)
    print(f"split: files={n} khop={khop} lech={len(lech)} thieu={thieu} thua={len(thua)} "
          f"dataset_sha={'khop' if ds_ok else 'lech'} ho={len(split.families)} k={split.k} "
          f"locked={'true' if split.locked else 'false'}")  # fmt: skip
    level = "LỖI" if split.locked else "CẢNH BÁO"
    problems = [f"file #{i}/{n}: sha lệch" for i in lech] + [f"file #{i}/{n}: không có trong SPLIT.md (thừa)" for i in thua]
    if thieu:
        problems.append(f"{thieu} file trong SPLIT.md không còn trong thư mục kịch bản (thiếu)")
    if not ds_ok:
        problems.append("dataset_sha256 lệch so với băm lại")
    for p in problems:
        print(f"{level}: {p}", file=sys.stderr)
    if not problems:
        print("KẾT QUẢ: ĐẠT")
        return OK
    if split.locked:
        print("KẾT QUẢ: ĐỎ (dữ liệu đổi sau khoá nhãn)")
        return DATA_MISMATCH
    print("KẾT QUẢ: CẢNH BÁO (locked: false)")
    return OK


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kiểm mã băm eval/SPLIT.md (G9)")
    ap.add_argument("--split", type=Path, default=REPO / "eval" / "SPLIT.md")
    ap.add_argument("--scenarios", type=Path, default=REPO / "eval" / "scenarios")
    args = ap.parse_args(argv)
    return check(args.split, args.scenarios)


if __name__ == "__main__":
    sys.exit(main())
