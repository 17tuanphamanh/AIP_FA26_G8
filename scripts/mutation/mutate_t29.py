"""Mutation tay T29 (plan T29 mục 5; hợp đồng duyệt #32 ngày 13/10) — mỗi chặng thêm khối đột biến của mình. Mỗi đột biến áp
lên file thật, chạy test eval, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau (file còn untracked thì chỉ md5 có
tác dụng). Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_t29.py
  uv run python scripts/mutation/mutate_t29.py --only M-T29-7

Chỉ unit (hàm thuần, không DB/stack). Không đọc `.env`.
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import n3  # scripts/mutation/n3.py — cùng thư mục (sys.path[0] khi chạy script)

REPO = Path(__file__).resolve().parents[2]


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, "-q", "-p", "no:cacheprovider"]


INIT = "backend/app/eval/__init__.py"
PRED = "backend/app/eval/predictions.py"
CONF = "backend/tests/unit/eval/conftest.py"
MET = "backend/app/eval/metrics.py"
# Thư mục eval TRƯỚC file cô lập: conftest eval được nạp lúc thu thập, trước khi test cô lập chạy.
UT = pt("backend/tests/unit/eval", "backend/tests/unit/test_eval_mode_isolation.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- S1: hợp đồng predictions.jsonl + chặn EVAL_MODE -----------------------------------------------------------------

_CLASS = 'class PredictionRecord(BaseModel, frozen=True, extra="forbid", strict=True, hide_input_in_errors=True):\n'
_GUARD = 'if os.environ.get("EVAL_MODE", "").strip().lower() != "true":\n'
_PROB = "Prob = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]\n"
_RUN_ID = 'RunId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]'
_STRATEGY = 'Strategy = Literal["manual", "full_auto", "rule_only", "llm_only", "hybrid", "hybrid_guarded"]\n'
_INVARIANT = "        if self.route is None and any(getattr(self, f) is not None for f in _RISK_FIELDS):\n"
_ENUM = "        if v is not None and v not in _DB_ENUMS[name]:\n"
_EMPTY = "    if not lines:\n"
_BLANK = "        if not line.strip():\n"
_MIXED = "        if len({getattr(r, field) for r in records}) > 1:\n"
_PARENT = "        if r.parent_ticket_id is not None:\n"
_DUP_T = "        if r.ticket_id in tickets:\n"
_DUP_S = "        if r.scenario_id in scenarios:\n"
_CONF_ENV = 'with mock.patch.dict(os.environ, {"EVAL_MODE": "true"}):\n    importlib.import_module("app.eval")\n'


def _class(new: str, tag: str) -> tuple[str, str, str, int]:
    return one(PRED, _CLASS, f"class PredictionRecord({new}):  # MUTATION {tag}\n")


def _off(rel: str, old: str, tag: str) -> tuple[str, str, str, int]:
    """`if <điều kiện>:` → `if False:` (giữ thụt lề)."""
    indent = old[: len(old) - len(old.lstrip())]
    return one(rel, old, f"{indent}if False:  # MUTATION {tag}\n")


GUARD = "test_import_refused_without_eval_mode"
S1: list[Mutation] = [
    Mutation("M-T29-1 bỏ extra=\"forbid\"",
             [_class('BaseModel, frozen=True, strict=True, hide_input_in_errors=True', "M-T29-1")],
             UT, ["test_extra_field_rejected"]),
    Mutation("M-T29-2 bỏ frozen=True",
             [_class('BaseModel, extra="forbid", strict=True, hide_input_in_errors=True', "M-T29-2")],
             UT, ["test_frozen"]),
    Mutation("M-T29-3 bỏ strict=True",
             [_class('BaseModel, frozen=True, extra="forbid", hide_input_in_errors=True', "M-T29-3")],
             UT, ["test_clarification_turns_strict[1]", "test_has_approval_strict[true]"]),
    Mutation("M-T29-4 bỏ hide_input_in_errors",
             [_class('BaseModel, frozen=True, extra="forbid", strict=True', "M-T29-4")],
             UT, ["test_error_does_not_echo_input"]),
    Mutation("M-T29-5 bỏ bất biến route None ⇒ 4 trường rủi ro None",
             [_off(PRED, _INVARIANT, "M-T29-5")],
             UT, ["test_route_none_requires_null_risk_fields"]),
    Mutation("M-T29-6 bỏ khoảng [0, 1] của xác suất",
             [one(PRED, _PROB, "Prob = Annotated[float, Field(allow_inf_nan=False)]  # MUTATION M-T29-6\n")],
             UT, ["test_prob_out_of_range"]),
    Mutation("M-T29-7 bỏ kiểm tập giá trị DB",
             [_off(PRED, _ENUM, "M-T29-7")],
             UT, ["test_db_enum_rejected", "test_load_invalid_field_reports_field_not_value"]),
    Mutation("M-T29-8 run_id nhận > 12 ký tự",
             [one(PRED, _RUN_ID, 'RunId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12,}$")]  # MUTATION M-T29-8')],
             UT, ["test_run_id_pattern[0123456789abc]"]),
    Mutation("M-T29-9 Strategy thiếu hybrid_guarded",
             [one(PRED, _STRATEGY,
                  'Strategy = Literal["manual", "full_auto", "rule_only", "llm_only", "hybrid"]  # MUTATION M-T29-9\n')],
             UT, ["test_strategy_matches_settings"]),
    Mutation("M-T29-10 load: bỏ kiểm file rỗng",
             [_off(PRED, _EMPTY, "M-T29-10")],
             UT, ["test_load_empty_file"]),
    Mutation("M-T29-11 load: bỏ kiểm dòng trống",
             [_off(PRED, _BLANK, "M-T29-11")],
             UT, ["test_load_blank_line"]),
    Mutation("M-T29-12 load: bỏ kiểm 1 run_id / strategy / split",
             [_off(PRED, _MIXED, "M-T29-12")],
             UT, ["test_load_rejects_mixed[run_id-ba9876543210]", "test_load_rejects_mixed[strategy-rule_only]",
                  "test_load_rejects_mixed[split-calibration]"]),
    Mutation("M-T29-13 load: nhận lá kịch bản nhiều ý (Q-T29-1)",
             [_off(PRED, _PARENT, "M-T29-13")],
             UT, ["test_load_rejects_multi_intent_leaf"]),
    Mutation("M-T29-14 load: bỏ kiểm trùng ticket_id",
             [_off(PRED, _DUP_T, "M-T29-14")],
             UT, ["test_load_rejects_duplicate_ticket_id"]),
    Mutation("M-T29-15 load: bỏ kiểm trùng scenario_id",
             [_off(PRED, _DUP_S, "M-T29-15")],
             UT, ["test_load_rejects_duplicate_scenario_id"]),
    Mutation("M-T29-16 bỏ chặn EVAL_MODE",
             [_off(INIT, _GUARD, "M-T29-16")],
             UT, [f"{GUARD}[{i}]" for i in ("thieu", "false", "rong", "1", "yes", "truee")]),
    Mutation("M-T29-17 chặn EVAL_MODE lỏng như bool của Settings",
             [one(INIT, _GUARD,
                  'if os.environ.get("EVAL_MODE", "").strip().lower() not in ("true", "1", "yes"):  # MUTATION M-T29-17\n')],
             UT, [f"{GUARD}[1]", f"{GUARD}[yes]"]),
    Mutation("M-T29-18 conftest không trả env sau khi import",
             [one(CONF, _CONF_ENV, 'mock.patch.dict(os.environ, {"EVAL_MODE": "true"}).start()  # MUTATION M-T29-18\n'
                                   'importlib.import_module("app.eval")\n')],
             UT, ["test_eval_mode_restored_after_conftest", "test_eval_mode_not_visible_outside_eval_tests"]),
]  # fmt: skip


# ---- S2: metrics.py §6.1 ------------------------------------------------------------------------------------------------

_PAIRS = "    return [(r.expected_route, r.route) for r in records if r.route is not None]\n"
_FNR = '    fnr = Rate(sum(1 for pred in need if pred == "AUTO"), len(need))\n'
_CP = "    upper = clopper_pearson_upper(fnr.k, fnr.n) if fnr.n else None\n"
_FPR = '    fpr = Rate(sum(1 for pred in auto if pred != "AUTO"), len(auto))\n'
_CONF_ADD = "        counts[gold][pred] += 1\n"
_F1_ZERO = "            out[c] = 0.0\n"
_PRESENT = "    present = [v for v in per_class.values() if v is not None]\n"
_COST = "    return Mean(float(sum(cost.costs[gold][pred] for gold, pred in pairs)), len(pairs))\n"
_LLM = '    llm = [r for r in records if r.decided_by == "llm"]\n'
_Y = '    labels = np.array([r.expected_route != "AUTO" for r, _ in rows], dtype=bool)\n'
_WHICH = '    return r.raw_prob if which == "raw" else r.calibrated_prob\n'
_MIX = "    if len(methods) > 1:\n"
_M5_BY = "    m5 = [r for r in records if r.route is not None]\n"
_REQ = "    if len(records) == 0:\n"


def _swap(old: str, new: str, tag: str) -> tuple[str, str, str, int]:
    return one(MET, old, new.rstrip("\n") + f"  # MUTATION {tag}\n")


S2: list[Mutation] = [
    Mutation("M-T29-19 FNR: pred == AUTO → pred != AUTO",
             [_swap(_FNR, _FNR.replace('pred == "AUTO"', 'pred != "AUTO"'), "M-T29-19")],
             UT, ["test_fnr_hand", "test_fnr_zero_of_60"]),
    Mutation("M-T29-20 bỏ lọc route None (§6.1 tính cả lá không tới M5)",
             [_swap(_PAIRS, "    return [(r.expected_route, r.route) for r in records]  # type: ignore[misc]\n", "M-T29-20")],
             UT, ["test_fnr_excludes_route_none", "test_mean_route_cost_excludes_route_none"]),
    Mutation("M-T29-21 CP truyền (n, k)",
             [_swap(_CP, "    upper = clopper_pearson_upper(fnr.n, fnr.k) if fnr.n else None\n", "M-T29-21")],
             UT, ["test_fnr_hand", "test_fnr_zero_of_60"]),
    Mutation("M-T29-22 FPR: mẫu số = mọi ca tới M5",
             [_swap(_FPR, _FPR.replace("len(auto))", "len(pairs))"), "M-T29-22")],
             UT, ["test_fpr_hand"]),
    Mutation("M-T29-23 ma trận chuyển vị [pred][gold]",
             [_swap(_CONF_ADD, "        counts[pred][gold] += 1\n", "M-T29-23")],
             UT, ["test_confusion_orientation"]),
    Mutation("M-T29-24 macro-F1 gộp lớp vắng (tính 0)",
             [_swap(_PRESENT, "    present = [v if v is not None else 0.0 for v in per_class.values()]\n", "M-T29-24")],
             UT, ["test_macro_f1_absent_class"]),
    Mutation("M-T29-25 F1 lớp 0/0 → loại thay vì 0",
             [_swap(_F1_ZERO, "            out[c] = None\n", "M-T29-25")],
             UT, ["test_macro_f1_zero_division"]),
    Mutation("M-T29-26 chi phí cost[pred][gold]",
             [_swap(_COST, _COST.replace("cost.costs[gold][pred]", "cost.costs[pred][gold]"), "M-T29-26")],
             UT, ["test_mean_route_cost_asymmetric", "test_mean_route_cost_hand"]),
    Mutation("M-T29-27 ECE/Brier bỏ lọc decided_by = llm",
             [_swap(_LLM, "    llm = list(records)\n", "M-T29-27")],
             UT, ["test_ece_brier_llm_only"]),
    Mutation("M-T29-28 y = gold == AUTO",
             [_swap(_Y, _Y.replace('!= "AUTO"', '== "AUTO"'), "M-T29-28")],
             UT, ["test_ece_brier_llm_only", "test_raw_vs_calibrated"]),
    Mutation("M-T29-29 dùng raw thay calibrated",
             [_swap(_WHICH, "    return r.raw_prob\n", "M-T29-29")],
             UT, ["test_raw_vs_calibrated"]),
    Mutation("M-T29-30 bỏ chặn trộn p_method",
             [_swap(_MIX, "    if False:\n", "M-T29-30")],
             UT, ["test_mixed_p_method_rejected"]),
    Mutation("M-T29-31 decided_by: mẫu số = mọi lá",
             [_swap(_M5_BY, "    m5 = list(records)\n", "M-T29-31")],
             UT, ["test_decided_by_distribution_hand"]),
    Mutation("M-T29-32 bỏ kiểm danh sách rỗng",
             [_swap(_REQ, "    if False:\n", "M-T29-32")],
             UT, ["test_empty_records_raises"]),
]  # fmt: skip

ALL = S1 + S2
MUTATIONS = ALL
if "--only" in sys.argv:
    at = sys.argv.index("--only") + 1
    prefix = sys.argv[at] if at < len(sys.argv) else ""
    MUTATIONS = [m for m in ALL if m.name.startswith(prefix + " ")]


def test_env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(test: str, failed: list[str]) -> bool:
    if "[" in test:
        return any(f.endswith("::" + test) for f in failed)
    return any(f.endswith("::" + test) or ("::" + test + "[") in f for f in failed)


def main() -> int:
    if not MUTATIONS:  # `--only` sai tên → không đột biến nào chạy; trả 0 là "xanh rỗng"
        print(f"DỪNG: không có đột biến nào khớp `--only` (mã: M-T29-1 … M-T29-{len(ALL)})")
        return 2
    env = test_env()
    files = sorted({rel for m in MUTATIONS for rel, *_ in m.edits})
    stop = n3.guard(REPO, files, [m.cmd for m in MUTATIONS], env)  # N3: không dấu sót, mốc xanh
    if stop is not None:
        return stop
    before = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 trước  {before[rel]}  {rel}")
    diff_before = git_diff_stat()
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
        unmarked = [rel for rel, text in mutated.items() if n3.MARK not in text]
        if unmarked:
            print(f"!! {m.name}: file đột biến thiếu chữ {n3.MARK!r} {unmarked} — bỏ qua (N3a không bắt được nếu bị giết)")
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
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
