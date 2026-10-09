"""T22a P9 — `scripts/rule_coverage.py` (phase5-thiet-ke-chi-tiet.md mục 4.6; bảng 4.7 r1–r4; đột biến M-T22a-11 mục 4.8).

Viết TỪ ĐẶC TẢ, trước code. Script nạp bằng `importlib` như `test_mutation_n3.py`; gọi `main(argv) -> int`, đọc stdout bằng
`capsys`. Không mạng, không stack.

Bảng in (4.6 "In ra"): `họ | số kịch bản | allow | approval_required | deny | none (→ LLM) | lỗi`, rồi dòng tổng, rồi danh sách
lỗi/cảnh báo. Bộ đọc bảng dưới đây chỉ giả định: mỗi họ một dòng, ô đầu là tên họ (dòng tổng bắt đầu bằng "Tổng"/"Total"),
6 ô số theo đúng thứ tự cột của spec; phân cách `|` hoặc khoảng trắng.
"""

import csv
import importlib.util
import re
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "rule_coverage.py"
MAU = REPO / "eval" / "scenarios" / "_mau"
SEED = REPO / "mock_services" / "seed.json"
TONG = "__TONG__"

CSV_COLUMNS = ["id", "family", "rule_decision", "matched_rule_id", "all_matched", "expected_route"]  # 4.6 --csv


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_rule_coverage_t22a", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    rc = _script().main(argv)
    return rc, unicodedata.normalize("NFC", capsys.readouterr().out)


def _rows(out: str) -> dict[str, list[int]]:
    """{họ: [số kịch bản, allow, approval_required, deny, none, lỗi]}; dòng tổng dưới khoá `TONG`."""
    rows: dict[str, list[int]] = {}
    for line in out.splitlines():
        toks = [t for t in re.split(r"[|\s]+", line.strip()) if t]
        if len(toks) < 7:
            continue
        key = toks[0].rstrip(":")
        nums = [t for t in toks[1:] if t.isdigit()]
        rest = [t for t in toks[1:] if not t.isdigit()]
        if key.lower().startswith(("tổng", "total")):
            key = TONG
        elif rest:
            continue
        if len(nums) == 6:
            rows[key] = [int(n) for n in nums]
    return rows


def _bang_tong(out: str) -> str:
    """Phần bảng tổng: mọi dòng tới hết dòng tổng (4.6: bảng → dòng tổng → danh sách lỗi/cảnh báo)."""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        toks = [t for t in re.split(r"[|\s]+", line.strip()) if t]
        if toks and toks[0].lower().startswith(("tổng", "total")):
            return "\n".join(lines[: i + 1])
    raise AssertionError(f"không thấy dòng tổng trong stdout:\n{out}")


def _mau(name: str) -> dict[str, Any]:
    data = yaml.safe_load((MAU / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _ghi(folder: Path, data: dict[str, Any]) -> Path:
    path = folder / f"{data['id']}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ---- r1 — 3 kịch bản mẫu --------------------------------------------------------------------------------------------------


def test_r1_ba_kich_ban_mau_l1_none_r01_allow_r12_deny(capsys: pytest.CaptureFixture[str]) -> None:
    """r1 (4.7): `eval/scenarios/_mau` → họ L1 → none, R01 → allow, R12 → deny; tổng "none" = 1; dữ kiện mẫu khớp seed
    (không cảnh báo), không lỗi → thoát 0."""
    rc, out = _run([str(MAU)], capsys)
    rows = _rows(out)
    #                  [n, allow, approval_required, deny, none, lỗi]
    assert rows.get("L1") == [1, 0, 0, 0, 1, 0], out
    assert rows.get("R01") == [1, 1, 0, 0, 0, 0], out
    assert rows.get("R12") == [1, 0, 0, 1, 0, 0], out
    assert rows.get(TONG) == [3, 1, 0, 1, 1, 0], out
    assert rows[TONG][4] == 1
    assert "CẢNH BÁO" not in out
    assert rc == 0


def test_r1b_approval_required_khong_bi_dem_vao_none(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """r1 + M-T22a-11 (mục 4.8: "đếm approval_required vào none" phải đỏ ở r1): 3 mẫu không có ca approval_required nên
    thêm một kịch bản R07 (nv001 xin `read` `finance/Q3` — seed: high, Finance) — cột approval_required = 1, none vẫn = 1."""
    for name in ("T22A-L1", "T22A-R01", "T22A-R12"):
        _ghi(tmp_path, _mau(name))
    r07 = _mau("T22A-L1")
    r07.update(id="T22A-R07", family="R07", source="goc")
    r07["gold"]["action"]["target"] = "folder:finance/Q3"
    r07["gold"]["facts"]["resource_sensitivity"] = "high"
    r07["gold"]["expected_route"] = "HITL"
    _ghi(tmp_path, r07)
    rc, out = _run([str(tmp_path), "--seed", str(SEED)], capsys)
    rows = _rows(out)
    assert rows.get("R07") == [1, 0, 1, 0, 0, 0], out
    assert rows.get(TONG) == [4, 1, 1, 1, 1, 0], out
    assert "CẢNH BÁO" not in out
    assert rc == 0


# ---- r2 — lỗi kịch bản → thoát 1, không dừng cả lượt ------------------------------------------------------------------


def _loi_fact_sai_kieu(d: dict[str, Any]) -> None:
    d["gold"]["facts"]["target_is_service_account"] = "no"  # bool → chuỗi


def _loi_fact_ngoai_tap(d: dict[str, Any]) -> None:
    d["gold"]["facts"]["target_user_status"] = "on_leave"


def _loi_fact_la(d: dict[str, Any]) -> None:
    d["gold"]["facts"]["user_says_ok"] = True


def _loi_requester_khong_co(d: dict[str, Any]) -> None:
    d["requester"] = {"user_id": "nv999", "role": "employee", "dept": "Finance", "tenure_days": 10}


@pytest.mark.parametrize(
    "hong",
    [
        pytest.param(_loi_fact_sai_kieu, id="r2-fact-sai-kieu"),
        pytest.param(_loi_fact_ngoai_tap, id="r2-fact-ngoai-tap-gia-tri"),
        pytest.param(_loi_fact_la, id="r2-fact-ngoai-FACT_KEYS"),
        pytest.param(_loi_requester_khong_co, id="r2-requester-khong-co-trong-seed"),
    ],
)
def test_r2_loi_kich_ban_thoat_1(hong: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """r2 (4.6 bước 2–3): fact sai kiểu / ngoài tập / sai key (`check_facts`), người gửi không có trong seed → LỖI kịch bản
    (in id), các kịch bản khác vẫn chạy, thoát 1."""
    _ghi(tmp_path, _mau("T22A-R01"))
    bad = _mau("T22A-R01")
    bad.update(id="T22A-LOI", family="LOI")
    hong(bad)
    _ghi(tmp_path, bad)
    rc, out = _run([str(tmp_path), "--seed", str(SEED)], capsys)
    rows = _rows(out)
    assert "T22A-LOI" in out
    assert rows.get("R01") == [1, 1, 0, 0, 0, 0], out  # không dừng cả lượt
    assert rows.get("LOI", [None])[-1] == 1, out
    assert rows.get(TONG, [None])[-1] == 1, out
    assert rc == 1


# ---- r3 — fact lệch seed → cảnh báo, thoát 0 ------------------------------------------------------------------------------


def test_r3_fact_lech_seed_canh_bao_thoat_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """r3 (4.6 bước 4): `target_account_privilege: admin` cho nv001 (seed: standard_user) → dòng
    `CẢNH BÁO <id>: <fact> kịch bản=<x> seed=<y>`, kịch bản vẫn chạy (R04 → approval_required), thoát 0."""
    lech = _mau("T22A-R01")
    lech.update(id="T22A-LECH", family="LECH")
    lech["gold"]["facts"]["target_account_privilege"] = "admin"
    _ghi(tmp_path, lech)
    rc, out = _run([str(tmp_path), "--seed", str(SEED)], capsys)
    assert "CẢNH BÁO" in out
    assert "CẢNH BÁO T22A-LECH: target_account_privilege kịch bản=admin seed=standard_user" in out, out
    assert _rows(out).get("LECH") == [1, 0, 1, 0, 0, 0], out
    assert rc == 0


# ---- r4 — không in expected_route ở bảng tổng; --csv ghi đủ cột -----------------------------------------------------------


def test_r4_bang_tong_khong_in_expected_route(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """r4 (4.6 "In ra", bất biến 4.9 (6)): phần bảng tổng của stdout không chứa `expected_route` (kể cả khi có --csv);
    CSV ghi từng kịch bản với cột `id, family, rule_decision, matched_rule_id, all_matched, expected_route`."""
    out_csv = tmp_path / "out.csv"
    rc, out = _run([str(MAU), "--seed", str(SEED), "--csv", str(out_csv)], capsys)
    assert "expected_route" not in _bang_tong(out)
    assert rc == 0
    with out_csv.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == CSV_COLUMNS
        got = {r["id"]: r for r in reader}
    assert set(got) == {"T22A-L1", "T22A-R01", "T22A-R12"}
    assert {i: (r["family"], r["rule_decision"]) for i, r in got.items()} == {
        "T22A-L1": ("L1", "none"), "T22A-R01": ("R01", "allow"), "T22A-R12": ("R12", "deny"),
    }  # fmt: skip
    assert (got["T22A-R01"]["matched_rule_id"], got["T22A-R12"]["matched_rule_id"]) == ("R01", "R12")
    assert {i: r["expected_route"] for i, r in got.items()} == {
        "T22A-L1": "AUTO", "T22A-R01": "AUTO", "T22A-R12": "ESCALATE_L2",
    }  # fmt: skip


# ---- Q-T22a-1 (PLAN-T22a mục 9): ca chờ DỪNG 2 — GỠ HẾT ở DỪNG 2 ------------------------------------------------------------
# `rule_coverage.py` là stub tới DỪNG 2 (P9) và r1/r3/r4 còn cần R01–R15 (P8) → đánh dấu ở MỘT chỗ dưới. strict + raises như
# `test_policy_rules_all.py`. Không đổi kỳ vọng.
CHO_DUNG2: frozenset[str] = frozenset({
    "test_r1_ba_kich_ban_mau_l1_none_r01_allow_r12_deny",
    "test_r1b_approval_required_khong_bi_dem_vao_none",
    *(f"test_r2_loi_kich_ban_thoat_1[{i}]" for i in (
        "r2-fact-sai-kieu", "r2-fact-ngoai-tap-gia-tri", "r2-fact-ngoai-FACT_KEYS", "r2-requester-khong-co-trong-seed",
    )),
    "test_r3_fact_lech_seed_canh_bao_thoat_0",
    "test_r4_bang_tong_khong_in_expected_route",
})  # fmt: skip


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.name in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError),
                                              reason="chờ DỪNG 2: rule_coverage (P9) + R01–R15 (P8)"))  # fmt: skip
