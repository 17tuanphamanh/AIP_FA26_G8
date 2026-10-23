"""G9 — `scripts/eval/check_split.py` (CI kiểm mã băm `eval/SPLIT.md`) + hàm băm dùng chung của `app.eval.dataset`.

Chỉ kịch bản GIẢ trong `tmp_path` (nội dung, tên file, tên họ chứa `SENTINEL_`); SPLIT.md giả băm bằng công thức viết lại trong test
(`oracle_dataset_sha` — oracle độc lập với `dataset.py`). Mọi lần chạy script đều kiểm log không có `SENTINEL_` (tên file/họ) và không
có chuỗi 64 hex (sha).
"""

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.eval.dataset import dataset_sha256, file_sha256, load_scenarios, scenario_files
from tests.unit.eval.eval_scripts import load_script
from tests.unit.eval.fake_stack import SEED_USERS, real_scenario

cs = load_script("check_split")

SENTINEL = "SENTINEL_"
HEX64 = re.compile(r"[0-9a-f]{64}")
NAMES = ("SENTINEL_f0.yaml", "SENTINEL_f1.yaml", "SENTINEL_f2.yml", "SENTINEL_f3.yaml")
FAMILIES = {"SENTINEL_FAM_A": 1, "SENTINEL_FAM_B": 2}


def oracle_sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def oracle_dataset_sha(files: dict[str, str]) -> str:
    """Công thức `Dataset.sha256` viết lại: nối `"<tên>\\0<sha>\\n"` theo tên tăng dần rồi băm."""
    return hashlib.sha256("".join(f"{n}\0{s}\n" for n, s in sorted(files.items())).encode()).hexdigest()


def scen_dir(tmp_path: Path) -> Path:
    d = tmp_path / "scenarios"
    d.mkdir()
    for i, name in enumerate(NAMES):
        (d / name).write_text(f"id: SENTINEL_ID_{i}\nfamily: SENTINEL_FAM_{'AB'[i % 2]}\n", encoding="utf-8")
    return d


def hashes(d: Path) -> dict[str, str]:
    return {name: oracle_sha((d / name).read_bytes()) for name in NAMES}


def split_text(body: str) -> str:
    return f"# SPLIT — SENTINEL_tieu de\n\nGhi chú.\n\n```yaml\n{body}```\n\nHết.\n"


def write_split(tmp_path: Path, files: dict[str, str], *, families: dict[str, int] = FAMILIES, k: int = 2, locked: bool = True,
                dataset: str | None = None, **extra: Any) -> Path:  # fmt: skip
    data: dict[str, Any] = {
        "seed": 20260925, "k": k, "dataset_sha256": dataset or oracle_dataset_sha(files), "files": files,
        "families": families, "locked": locked, **extra,
    }  # fmt: skip
    p = tmp_path / "SPLIT.md"
    p.write_text(split_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False)), encoding="utf-8")
    return p


def run(split: Path, scenarios: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cs.main(["--split", str(split), "--scenarios", str(scenarios)])
    out, err = capsys.readouterr()
    assert SENTINEL not in out + err
    assert not HEX64.search(out + err)
    return code, out, err


@pytest.fixture
def locked_split(tmp_path: Path) -> tuple[Path, Path]:
    d = scen_dir(tmp_path)
    return write_split(tmp_path, hashes(d)), d


# ---- hàm băm dùng chung (dataset.py) ---------------------------------------------------------------------------------


def test_dataset_sha_shared_equals_load(tmp_path: Path) -> None:
    d = tmp_path / "s"
    d.mkdir()
    for i, name in enumerate(("SENTINEL_b.yaml", "SENTINEL_a.yml")):
        (d / name).write_text(yaml.safe_dump(real_scenario(f"SENTINEL_ID_{i}"), allow_unicode=True), encoding="utf-8")
    shared = dataset_sha256((p.name, file_sha256(p.read_bytes())) for p in scenario_files(d))
    assert shared == load_scenarios(d, users=SEED_USERS).sha256
    assert shared == oracle_dataset_sha({p.name: oracle_sha(p.read_bytes()) for p in d.iterdir()})


def test_dataset_sha_pinned() -> None:
    pairs = {"SENTINEL_a.yaml": "1" * 64, "SENTINEL_b.yml": "2" * 64}
    assert dataset_sha256(pairs.items()) == oracle_dataset_sha(pairs)
    assert file_sha256(b"SENTINEL_x") == oracle_sha(b"SENTINEL_x")


def test_dataset_sha_order_independent() -> None:
    a, b = ("SENTINEL_a.yaml", "1" * 64), ("SENTINEL_b.yaml", "2" * 64)
    assert dataset_sha256([b, a]) == dataset_sha256([a, b])


def test_scenario_files_top_level(tmp_path: Path) -> None:
    d = scen_dir(tmp_path)
    (d / "sub").mkdir()
    (d / "sub" / "SENTINEL_x.yaml").write_text("x: 1\n")
    (d / "SENTINEL_x.txt").write_text("x: 1\n")
    (d / ".yaml").write_text("x: 1\n")
    assert [p.name for p in scenario_files(d)] == sorted(NAMES)


# ---- check_split: khớp / lệch ----------------------------------------------------------------------------------------


def test_split_ok(locked_split: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(*locked_split, capsys)
    assert code == 0
    assert "split: files=4 khop=4 lech=0 thieu=0 thua=0 dataset_sha=khop ho=2 k=2 locked=true" in out
    assert "KẾT QUẢ: ĐẠT" in out and err == ""


def test_split_sha_mismatch_red(locked_split: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    split, d = locked_split
    p = d / NAMES[1]
    p.write_bytes(p.read_bytes() + b"\n")  # 1 byte khác
    code, out, err = run(split, d, capsys)
    assert code == 1
    assert "khop=3 lech=1 thieu=0 thua=0 dataset_sha=lech" in out
    assert "LỖI: file #2/4: sha lệch" in err
    assert "LỖI: dataset_sha256 lệch so với băm lại" in err
    assert "KẾT QUẢ: ĐỎ" in out


def test_split_missing_file_red(locked_split: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    split, d = locked_split
    (d / NAMES[0]).unlink()
    code, out, err = run(split, d, capsys)
    assert code == 1
    assert "files=3 khop=3 lech=0 thieu=1 thua=0 dataset_sha=lech" in out
    assert "LỖI: 1 file trong SPLIT.md không còn trong thư mục kịch bản (thiếu)" in err


def test_split_extra_file_red(locked_split: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    split, d = locked_split
    (d / "SENTINEL_f9.yaml").write_text("id: SENTINEL_ID_9\n")
    code, out, err = run(split, d, capsys)
    assert code == 1
    assert "files=5 khop=4 lech=0 thieu=0 thua=1 dataset_sha=lech" in out
    assert "LỖI: file #5/5: không có trong SPLIT.md (thừa)" in err


def test_split_scenarios_dir_missing_red(locked_split: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    split, _ = locked_split
    code, out, _err = run(split, tmp_path / "khong-co", capsys)
    assert code == 1
    assert "files=0 khop=0 lech=0 thieu=4 thua=0 dataset_sha=lech" in out


def test_split_top_level_only(locked_split: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    split, d = locked_split
    (d / "sub").mkdir()
    (d / "sub" / "SENTINEL_x.yaml").write_text("id: SENTINEL_ID_x\n")
    (d / "SENTINEL_x.txt").write_text("id: SENTINEL_ID_x\n")
    code, out, _err = run(split, d, capsys)
    assert code == 0 and "files=4 khop=4" in out


@pytest.mark.parametrize("change", ["sha", "thieu", "thua"])
def test_split_unlocked_warns(tmp_path: Path, change: str, capsys: pytest.CaptureFixture[str]) -> None:
    d = scen_dir(tmp_path)
    split = write_split(tmp_path, hashes(d), locked=False)
    if change == "sha":
        (d / NAMES[2]).write_text("id: SENTINEL_ID_khac\n")
    elif change == "thieu":
        (d / NAMES[2]).unlink()
    else:
        (d / "SENTINEL_f9.yaml").write_text("id: SENTINEL_ID_9\n")
    code, out, err = run(split, d, capsys)
    assert code == 0
    assert "locked=false" in out and "KẾT QUẢ: CẢNH BÁO" in out
    assert "CẢNH BÁO:" in err and "LỖI" not in err


def test_split_absent_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = scen_dir(tmp_path)
    code, out, err = run(tmp_path / "SPLIT.md", d, capsys)
    assert code == 0
    assert "split: chua_co" in out and "CẢNH BÁO: chưa có SPLIT.md" in err


# ---- check_split: cấu trúc (đỏ mã 2, cả khi locked false) -------------------------------------------------------------


def test_split_family_two_parts_red(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = scen_dir(tmp_path)
    files = hashes(d)
    body = yaml.safe_dump({"seed": 1, "k": 2, "dataset_sha256": oracle_dataset_sha(files), "files": files}, sort_keys=False)
    body += "families:\n  SENTINEL_FAM_A: 1\n  SENTINEL_FAM_B: 2\n  SENTINEL_FAM_A: 2\nlocked: false\n"
    split = tmp_path / "SPLIT.md"
    split.write_text(split_text(body), encoding="utf-8")
    code, out, err = run(split, d, capsys)
    assert code == 2
    assert "khoá trùng" in err and "KẾT QUẢ: ĐỎ (SPLIT.md sai cấu trúc)" in out


@pytest.mark.parametrize("locked", [True, False])
@pytest.mark.parametrize("part", [0, 3])
def test_split_part_out_of_range(tmp_path: Path, part: int, locked: bool, capsys: pytest.CaptureFixture[str]) -> None:
    d = scen_dir(tmp_path)
    split = write_split(tmp_path, hashes(d), families={**FAMILIES, "SENTINEL_FAM_C": part}, locked=locked)
    code, _out, err = run(split, d, capsys)
    assert code == 2
    assert "1 họ có phần ngoài 1..2: họ #3/3" in err


def test_split_empty_part_red(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = scen_dir(tmp_path)
    split = write_split(tmp_path, hashes(d), k=3, locked=False)
    code, _out, err = run(split, d, capsys)
    assert code == 2
    assert "phần rỗng (không họ nào): 3" in err


def test_split_self_inconsistent_red(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = scen_dir(tmp_path)
    split = write_split(tmp_path, hashes(d), dataset="0" * 64, locked=False)
    code, _out, err = run(split, d, capsys)
    assert code == 2
    assert "dataset_sha256 không khớp chính danh sách files" in err


def _bad(tmp_path: Path, files: dict[str, str], kind: str) -> Path:
    if kind == "extra_key":
        return write_split(tmp_path, files, fold_note="SENTINEL_x")
    if kind == "sha_not_hex":
        return write_split(tmp_path, {**files, NAMES[0]: "Z" * 64})
    if kind == "subdir_name":
        return write_split(tmp_path, {**files, "sub/SENTINEL_x.yaml": "a" * 64})
    if kind == "k_one":
        return write_split(tmp_path, files, families={"SENTINEL_FAM_A": 1}, k=1)
    if kind == "locked_str":
        return write_split(tmp_path, files, locked="yes")  # type: ignore[arg-type]
    good = write_split(tmp_path, files).read_text(encoding="utf-8")
    if kind == "missing_key":
        good = good.replace("locked: true\n", "")
    elif kind == "no_block":
        good = good.replace("```yaml", "```text")
    elif kind == "two_blocks":
        good += "\n```yaml\nseed: 1\n```\n"
    elif kind == "yaml_error":
        good = good.replace("seed: 20260925", "seed: [1")
    elif kind == "not_mapping":
        good = split_text("- 1\n- 2\n")
    good_path = tmp_path / "SPLIT.md"
    good_path.write_text(good, encoding="utf-8")
    return good_path


@pytest.mark.parametrize("kind", ["extra_key", "sha_not_hex", "subdir_name", "k_one", "locked_str", "missing_key", "no_block",
                                  "two_blocks", "yaml_error", "not_mapping"])  # fmt: skip
def test_split_bad_structure(tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]) -> None:
    d = scen_dir(tmp_path)
    code, out, err = run(_bad(tmp_path, hashes(d), kind), d, capsys)
    assert code == 2
    assert err.startswith("LỖI: SPLIT.md: ") and "KẾT QUẢ: ĐỎ (SPLIT.md sai cấu trúc)" in out


def test_split_log_no_names_sha(locked_split: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    """Đủ các loại dòng log cùng lúc: sha lệch + thừa + thiếu + dataset lệch — `run` kiểm không tên file/họ, không sha."""
    split, d = locked_split
    (d / NAMES[0]).write_text("id: SENTINEL_ID_khac\n")
    (d / NAMES[1]).unlink()
    (d / "SENTINEL_f9.yaml").write_text("id: SENTINEL_ID_9\n")
    code, out, err = run(split, d, capsys)
    assert code == 1
    assert "lech=1 thieu=1 thua=1" in out
    assert all(name not in out + err for name in (*NAMES, "SENTINEL_f9.yaml", *FAMILIES))
