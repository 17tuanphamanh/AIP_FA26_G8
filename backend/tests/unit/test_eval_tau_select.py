"""Gói 1 (D-52) — `scripts/eval/b2_tau_select.py`: chọn τ cho B2 `review` (quy tắc ghi trước).

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.5 (τ = giá trị NHỎ NHẤT của lưới 0,50…0,99,
0,995, 0,999, 0,9999 có cận trên một phía 95% của E1 thừa ≤ E_max = 15%; bootstrap theo nhóm, B = 2.000, seed 20261018,
mọi τ dùng chung một bộ mẫu; câu LLM chấm lỗi bỏ khỏi cả tử lẫn mẫu và báo số bỏ; không τ nào đạt → giữ `shadow`; báo kèm
lợi ích trên câu tấn công; ghi `{"tau_review","rule","e_max","date","data_sha256","judge_model"}`), 4.3, 9.3;
`PLAN-B2REVIEW.md` mục 4 #3 (prepare/score/select/mask-report; KHÔNG có cờ nhập `p_mal` từ nguồn ngoài; 4 hằng ghi cứng),
mục 8 (chữ ký `excess_e1`, `select_tau`, `record`, `prepare_rows`, `score_rows`, `cache_ok`).

Dữ liệu giả nhỏ tự dựng; `select_tau` chạy với hằng THẬT (B = 2.000) trên ≤ 120 dòng. Không torch: `score_rows` nhận hàm
chấm giả.
"""

import itertools
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from app.guard.mask_words import replace_masks
from tests.unit._b2review import item, load_script

SCRIPT = "scripts/eval/b2_tau_select.py"
SUBCOMMANDS = ("prepare", "score", "select", "mask-report")
# Cờ có thể đổi 4 hằng hay nhập p_mal ngoài — không subcommand nào được có.
FORBIDDEN_FLAG = re.compile(r"--(e[-_]?max|b|n[-_]?boot\w*|boot\w*|seed|grid|taus?|p[-_]?mal\w*|scores?|probs?)\b")


@pytest.fixture
def ts(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_script(SCRIPT, monkeypatch)


# ---- 4 hằng ghi cứng -------------------------------------------------------------------------------------------------------


def test_constants_hard_coded(ts: ModuleType) -> None:
    assert (ts.E_MAX, ts.B, ts.SEED) == (0.15, 2000, 20261018)
    grid = list(ts.GRID)
    assert len(grid) == 53
    assert grid[:50] == pytest.approx([0.50 + 0.01 * k for k in range(50)])
    assert grid[49] == pytest.approx(0.99) and grid[-3:] == pytest.approx([0.995, 0.999, 0.9999])
    assert all(x < y for x, y in itertools.pairwise(grid))


def _rc(ts: ModuleType, argv: list[str]) -> int:
    """`main(argv)` trả mã hoặc để argparse ném `SystemExit` — mục 8 không ghim, nhận cả hai."""
    try:
        return int(ts.main(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2


def _help(ts: ModuleType, argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    _rc(ts, [*argv, "--help"])  # mã thoát của --help không ghim (main có thể đổi SystemExit thành mã riêng)
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert "usage" in text.lower(), f"{argv}: không in trợ giúp argparse"
    return text


def test_cli_has_no_flag_changing_constants_or_importing_pmal(ts: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    texts = [_help(ts, [], capsys)] + [_help(ts, [sub], capsys) for sub in SUBCOMMANDS]
    for sub, text in zip(("<gốc>", *SUBCOMMANDS), texts, strict=True):
        flags = set(re.findall(r"--[\w-]+", text)) - {"--help"}
        bad = sorted(f for f in flags if FORBIDDEN_FLAG.fullmatch(f))
        assert bad == [], f"{sub}: {bad}"


@pytest.mark.parametrize("flag", ["--e-max", "--e_max", "--b", "--seed", "--grid", "--tau", "--pmal", "--p-mal", "--p_mal"])
def test_select_rejects_unknown_flags(ts: ModuleType, tmp_path: Path, flag: str) -> None:
    pmal, judge = tmp_path / "p.jsonl", tmp_path / "j.jsonl"
    pmal.write_text("", encoding="utf-8")
    judge.write_text("", encoding="utf-8")
    assert _rc(ts, ["select", str(pmal), str(judge), flag, "0.5"]) == 2  # argparse: đối số lạ


def test_score_rejects_external_pmal_flag(ts: ModuleType, tmp_path: Path) -> None:
    prep = tmp_path / "prep.jsonl"
    prep.write_text("", encoding="utf-8")
    argv = ["score", str(prep), str(tmp_path / "out.jsonl"), "--model-dir", str(tmp_path), "--model-sha", "0" * 64,
            "--p-mal", str(prep)]  # fmt: skip
    assert _rc(ts, argv) == 2


# ---- excess_e1 ----------------------------------------------------------------------------------------------------------


def _r(id: str, p: float | None, judge_no: bool | None, *, label: str = "normal", group: str | None = None) -> dict[str, Any]:
    return {"id": id, "group": group or f"g-{id}", "label": label, "p_mal": p, "judge_no": judge_no}


def test_excess_e1_definition_and_boundary(ts: ModuleType) -> None:
    rows = [
        _r("n1", 0.95, True), _r("n2", 0.95, False), _r("n3", 0.85, True), _r("n4", 0.5, True),
        _r("n5", 0.99, None),  # judge lỗi → bỏ khỏi tử và mẫu
        _r("a1", 0.99, True, label="attack"),  # câu tấn công không vào E1 thừa
    ]
    assert ts.excess_e1(rows, 0.90) == pytest.approx(1 / 4)
    assert ts.excess_e1(rows, 0.85) == pytest.approx(2 / 4)  # p = τ tính là ≥ τ
    assert ts.excess_e1(rows, 0.96) == pytest.approx(0.0)


# ---- select_tau ------------------------------------------------------------------------------------------------------------


def _attacks(n: int = 10, caught_by_model_only: int = 4) -> list[dict[str, Any]]:
    return [_r(f"a{i}", 0.999 if i < caught_by_model_only else 0.2, i < caught_by_model_only, label="attack")
            for i in range(n)]  # fmt: skip


def test_select_tau_smallest_grid_value_meeting_rule(ts: ModuleType) -> None:
    """30/100 câu thường p = 0,705 và LLM nói không → τ ≤ 0,70 vượt E_max; τ = 0,71 là nhỏ nhất đạt."""
    normals = [_r(f"n{i}", 0.705 if i < 30 else 0.1, True) for i in range(100)]
    sel = ts.select_tau(normals + _attacks())
    assert sel["tau_review"] == pytest.approx(0.71)
    upper = sel["upper"]
    assert len(upper) == 53
    chosen = [t for t in upper if t == pytest.approx(0.71)]
    assert chosen and upper[chosen[0]] <= ts.E_MAX
    assert all(ub > ts.E_MAX for t, ub in upper.items() if t < 0.705)  # mọi τ nhỏ hơn đều trượt
    assert (sel["n_normal"], sel["n_attack"], sel["dropped"]) == (100, 10, 0)


def test_select_tau_all_pass_picks_grid_min(ts: ModuleType) -> None:
    normals = [_r(f"n{i}", 0.1, True) for i in range(40)]
    assert ts.select_tau(normals + _attacks())["tau_review"] == pytest.approx(0.50)


def test_select_tau_none_when_no_tau_meets_rule(ts: ModuleType) -> None:
    normals = [_r(f"n{i}", 0.99999 if i % 2 else 0.1, True) for i in range(40)]  # 50% vượt cả 0,9999
    sel = ts.select_tau(normals + _attacks())
    assert sel["tau_review"] is None


def test_select_tau_judge_errors_dropped_and_counted(ts: ModuleType) -> None:
    normals = [_r(f"n{i}", 0.1, True) for i in range(40)]
    broken = [_r(f"e{i}", 0.999, None) for i in range(25)]  # nếu không bỏ, E1 thừa ở mọi τ ≈ 38%
    sel = ts.select_tau(normals + broken + _attacks())
    assert sel["dropped"] == 25 and sel["n_normal"] == 40
    assert sel["tau_review"] == pytest.approx(0.50)


def test_select_tau_bootstrap_by_group(ts: ModuleType) -> None:
    """Một nhóm duy nhất: lấy mẫu lại theo nhóm luôn ra đúng tập cũ → cận trên = điểm (10%) ≤ 15% → τ = 0,50. Lấy mẫu theo
    câu (sai quy tắc) thì cận trên 1/10 với n = 10 vượt 15% → τ sẽ > 0,95."""
    normals = [_r(f"n{i}", 0.95 if i == 0 else 0.1, True, group="mot-nhom") for i in range(10)]
    sel = ts.select_tau(normals + _attacks())
    assert sel["tau_review"] == pytest.approx(0.50)


def test_select_tau_deterministic(ts: ModuleType) -> None:
    normals = [_r(f"n{i}", 0.6 + (i % 40) / 100, i % 3 != 0, group=f"g{i // 4}") for i in range(120)]
    rows = normals + _attacks()
    assert ts.select_tau(rows) == ts.select_tau(rows)


def test_select_tau_benefit_on_attacks(ts: ModuleType) -> None:
    """Lợi ích = P(p ≥ τ và LLM nói không | câu tấn công) — 4/10 câu tấn công chỉ model bắt."""
    normals = [_r(f"n{i}", 0.1, True) for i in range(40)]
    sel = ts.select_tau(normals + _attacks(10, 4))
    assert sel["tau_review"] == pytest.approx(0.50)
    assert sel["benefit"] == pytest.approx(0.4)  # tại τ đã chọn


# ---- record ----------------------------------------------------------------------------------------------------------------


def test_record_exact_keys(ts: ModuleType) -> None:
    sel = ts.select_tau([_r(f"n{i}", 0.1, True) for i in range(20)] + _attacks())
    rec = ts.record(sel, data_sha256="a" * 64, judge_model="deepseek-flash", date="2026-10-19")
    assert set(rec) == {"tau_review", "rule", "e_max", "date", "data_sha256", "judge_model"}
    assert rec["tau_review"] == sel["tau_review"] and rec["e_max"] == 0.15
    assert (rec["data_sha256"], rec["judge_model"], rec["date"]) == ("a" * 64, "deepseek-flash", "2026-10-19")
    assert isinstance(rec["rule"], str) and rec["rule"]
    json.dumps(rec)  # ghi được ra thresholds.json


# ---- prepare_rows (L1 + thay nhãn che; variants) ----------------------------------------------------------------------------


def test_prepare_rows_l1_then_replace(ts: ModuleType) -> None:
    rows = ts.prepare_rows([
        item("v1", "VPN lỗi, liên hệ tôi qua abc.xyz@gmail.com", "normal", "g1"),
        item("v2", "vpn khong vao duoc", "attack", "g2"),
    ])  # fmt: skip
    by = {r["id"]: r for r in rows}
    assert set(by) == {"v1", "v2"}
    assert {"id", "group", "label", "text_model", "masks_replaced", "has_mask", "no_diacritics"} <= set(by["v1"])
    assert by["v1"]["text_model"] == "VPN lỗi, liên hệ tôi qua địa chỉ email"
    assert (by["v1"]["masks_replaced"], by["v1"]["has_mask"], by["v1"]["no_diacritics"]) == (1, True, False)
    assert (by["v1"]["group"], by["v1"]["label"]) == ("g1", "normal")
    assert by["v2"]["text_model"] == "vpn khong vao duoc"
    assert (by["v2"]["masks_replaced"], by["v2"]["has_mask"], by["v2"]["no_diacritics"]) == (0, False, True)


def test_prepare_rows_pii_variants(ts: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """4.3 / Q-B2R-7: `orig` = có PII giả, qua L0 chưa L1; `masked` = L1; `replaced` = L1 + thay nhãn che."""
    pf = load_script("scripts/eval/_pii_fake.py", monkeypatch)
    items = [item(f"v{i}", "VPN không vào được, báo lỗi 809", "normal", f"g{i}") for i in range(6)]
    rows = ts.prepare_rows(items, pii_variants=True, seed=ts.SEED)
    assert len(rows) == 18
    for it in items:
        mine = {r["variant"]: r for r in rows if r["id"] == it["id"]}
        assert set(mine) == {"orig", "masked", "replaced"}
        orig, masked, replaced = mine["orig"]["text_model"], mine["masked"]["text_model"], mine["replaced"]["text_model"]
        assert orig == pf.l0_only(pf.insert_pii(it["text"], seed=ts.SEED, item_id=it["id"]))
        assert masked == pf.redact(orig).text and masked != orig
        assert (replaced, mine["replaced"]["masks_replaced"]) == replace_masks(masked)
    assert ts.prepare_rows(items, pii_variants=True, seed=ts.SEED) == rows  # tất định


# ---- score_rows, cache_ok ---------------------------------------------------------------------------------------------------


def test_score_rows_uses_text_model_and_records_errors(ts: ModuleType) -> None:
    seen: list[str] = []

    def classify(text: str) -> tuple[float, int]:
        seen.append(text)
        if "hỏng" in text:
            raise RuntimeError("model hỏng")
        return 0.25, 3

    rows = [{"id": "v1", "variant": "replaced", "text_model": "câu một", "group": "g", "label": "normal"},
            {"id": "v2", "variant": "replaced", "text_model": "câu hỏng", "group": "g", "label": "attack"}]  # fmt: skip
    out = ts.score_rows(rows, classify)
    assert seen == ["câu một", "câu hỏng"]
    assert out[0] == {"id": "v1", "variant": "replaced", "p_mal": 0.25, "windows": 3, "error": None}
    assert out[1] == {"id": "v2", "variant": "replaced", "p_mal": None, "windows": None, "error": "RuntimeError"}


def test_cache_ok_by_prep_sha(ts: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "pmal.jsonl"
    header = {"prep_sha256": "a" * 64, "model_version": "v3-seed123", "model_sha256": "b" * 64}
    out.write_text(json.dumps(header) + "\n" + json.dumps({"id": "v1", "p_mal": 0.1}) + "\n", encoding="utf-8")
    assert ts.cache_ok(out, "a" * 64) is True
    assert ts.cache_ok(out, "c" * 64) is False
    assert ts.cache_ok(tmp_path / "chua-co.jsonl", "a" * 64) is False
