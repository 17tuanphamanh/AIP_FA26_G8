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
STA = "backend/app/eval/stats.py"
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


# ---- S3: metrics.py §6.2 ------------------------------------------------------------------------------------------------

_AUTOMATED = "    return r.final_state == RESOLVED_STATE and not r.has_approval and r.exit_code is None\n"
_BY_GROUP = "    by_group = {g: [r for r in records if n3_group(r.expected_route) == g] for g in GROUPS}\n"
_MIX_CONST = 'check_mix({"routine": 0.7, "approval": 0.2, "sensitive": 0.1})  # P8:399, N3\n'
_WEIGHTED = "    value = None if missing else sum(frozen[g] * rates[g].k / rates[g].n for g in present)\n"
_DEFLECT = "        deflection=Rate(sum(1 for r in leaves if r.resolution_path == DEFLECTED_PATH), n),\n"
_ONE_TURN = "r.clarification_turns == 0 and r.close_reason == ONE_TURN_CLOSE_REASON), n),\n"
_LEAVES = "    leaves = list(records)  # P8:342 — mọi lá, gồm lá không tới M5 (Q7)\n"
_MIX_SUM = "    if abs(sum(mix.values()) - 1.0) > MIX_TOL:\n"
_MIX_NEG = "    if any(not math.isfinite(w) or w < 0 for w in mix.values()):\n"
_MIX_KEYS = "    if set(mix) != set(GROUPS):\n"
_MIX_COPY = "    return MappingProxyType({g: float(mix[g]) for g in GROUPS})\n"
_ESCALATED = "    return r.exit_code is not None\n"

S3: list[Mutation] = [
    Mutation("M-T29-33 automation bỏ điều kiện không phiếu duyệt",
             [_swap(_AUTOMATED, _AUTOMATED.replace(" and not r.has_approval", ""), "M-T29-33")],
             UT, ["test_automation_hand"]),
    Mutation("M-T29-34 automation bỏ điều kiện không exit_code",
             [_swap(_AUTOMATED, _AUTOMATED.replace(" and r.exit_code is None", ""), "M-T29-34")],
             UT, ["test_automation_hand"]),
    Mutation("M-T29-35 nhóm theo route thay expected_route",
             [_swap(_BY_GROUP, _BY_GROUP.replace("n3_group(r.expected_route)", "n3_group(r.route)"), "M-T29-35")],
             UT, ["test_group_by_gold_not_pred", "test_escalation_weighted_hand"]),
    Mutation("M-T29-36 đổi trọng số approval 0,2 ↔ sensitive 0,1",
             [one(MET, _MIX_CONST, 'check_mix({"routine": 0.7, "approval": 0.1, "sensitive": 0.2})  # MUTATION M-T29-36\n')],
             UT, ["test_escalation_weighted_hand", "test_mix_defaults"]),
    Mutation("M-T29-37 nhóm rỗng → chuẩn hoá lại thay vì None",
             [_swap(_WEIGHTED, "    value = (sum(frozen[g] * rates[g].k / rates[g].n for g in present)"
                               " / sum(frozen[g] for g in present)) if present else None\n", "M-T29-37")],
             UT, ["test_weighted_empty_group"]),
    Mutation("M-T29-38 deflection: mẫu số = lá có route",
             [_swap(_DEFLECT, _DEFLECT.replace("), n),", "), len([r for r in leaves if r.route is not None])),"),
                    "M-T29-38")],
             UT, ["test_deflection_hand"]),
    Mutation("M-T29-39 giải quyết một lượt: == 0 → <= 1",
             [one(MET, _ONE_TURN, _ONE_TURN.replace("== 0", "<= 1").rstrip("\n") + "  # MUTATION M-T29-39\n")],
             UT, ["test_one_turn_requires_both"]),
    Mutation("M-T29-40 giải quyết một lượt: bỏ điều kiện close_reason",
             [one(MET, _ONE_TURN, "r.clarification_turns == 0), n),  # MUTATION M-T29-40\n")],
             UT, ["test_one_turn_requires_both"]),
    Mutation("M-T29-41 loại lá không tới M5 khỏi mẫu số §6.2",
             [_swap(_LEAVES, "    leaves = [r for r in records if r.route is not None]\n", "M-T29-41")],
             UT, ["test_no_action_cases_in_denominator", "test_automation_hand"]),
    Mutation("M-T29-42 mix: bỏ kiểm tổng = 1",
             [_swap(_MIX_SUM, "    if False:\n", "M-T29-42")],
             UT, ["test_mix_validation[tong-0.9]", "test_mix_validation[tong-1.1]"]),
    # ---- bổ sung (ngoài danh sách tối thiểu S3) ----
    Mutation("M-T29-43 escalation thô bỏ E0",
             [_swap(_ESCALATED, '    return r.exit_code not in (None, "E0")\n', "M-T29-43")],
             UT, ["test_escalation_raw_hand"]),
    Mutation("M-T29-44 mix: bỏ kiểm trọng số âm / không hữu hạn",
             [_swap(_MIX_NEG, "    if False:\n", "M-T29-44")],
             UT, ["test_mix_validation[am]"]),
    Mutation("M-T29-45 mix: bỏ kiểm đủ đúng 3 nhóm",
             [_swap(_MIX_KEYS, "    if False:\n", "M-T29-45")],
             UT, ["test_mix_validation[thieu-nhom]", "test_mix_validation[thua-nhom]"]),
    Mutation("M-T29-46 mix: giữ tham chiếu dict của người gọi",
             [_swap(_MIX_COPY, "    return MappingProxyType(mix)\n", "M-T29-46")],
             UT, ["test_mix_frozen"]),
]  # fmt: skip


# ---- S4: stats.py — bootstrap theo họ ---------------------------------------------------------------------------------

_DRAW = "        v = statistic(_take(units, rng.integers(0, k, size=k)))  # đơn vị lấy mẫu = họ\n"
_SORT_FAM = "    names = sorted(groups)\n"
_RNG = "    return np.random.default_rng(seed)\n"
_ALPHA = "    alpha = (1.0 - level) / 2.0\n"
_PAIR_B = "        b = statistic(_take(units_b, idx))\n"
_NONE_SKIP = "        if v is None:\n            undefined += 1\n        else:\n            values.append(v)\n"
_POINT = "    point = statistic(_take(units, np.arange(k)))\n"
_INTERVAL = "    lo, hi = _interval(values, level)\n"
_SAME_FAM = "    if names_a != names_b:\n"
_NBOOT = "    if isinstance(n_boot, bool) or not isinstance(n_boot, Integral) or n_boot < 1:\n"
_ZERO = "    contains_zero = lo <= 0.0 <= hi if lo is not None and hi is not None else None\n"


def _st(old: str, new: str, tag: str) -> tuple[str, str, str, int]:
    return one(STA, old, new.rstrip("\n") + f"  # MUTATION {tag}\n")


S4: list[Mutation] = [
    Mutation("M-T29-47 lấy mẫu theo lá thay vì theo họ",
             [_st(_DRAW, "        v = statistic(_take([[r] for u in units for r in u], rng.integers(0, sum(map(len, units)),"
                         " size=sum(map(len, units)))))\n", "M-T29-47")],
             UT, ["test_bootstrap_resamples_families"]),
    Mutation("M-T29-48 bỏ sắp xếp tên họ (giữ thứ tự đầu vào)",
             [_st(_SORT_FAM, "    names = list(groups)\n", "M-T29-48")],
             UT, ["test_bootstrap_input_order_invariant", "test_paired_input_order_invariant"]),
    Mutation("M-T29-49 bỏ seed (RNG ngẫu nhiên theo hệ thống)",
             [_st(_RNG, "    return np.random.default_rng()\n", "M-T29-49")],
             UT, ["test_bootstrap_deterministic_seed", "test_defaults"]),
    Mutation("M-T29-50 seed cố định khác, bỏ qua tham số",
             [_st(_RNG, "    return np.random.default_rng(12345)\n", "M-T29-50")],
             UT, ["test_bootstrap_deterministic_seed"]),
    Mutation("M-T29-51 phân vị 5/95 thay vì 2,5/97,5",
             [_st(_ALPHA, "    alpha = 1.0 - level\n", "M-T29-51")],
             UT, ["test_percentile_hand"]),
    Mutation("M-T29-52 paired dùng 2 dãy họ độc lập",
             [_st(_PAIR_B, "        b = statistic(_take(units_b, rng.integers(0, k, size=k)))\n", "M-T29-52")],
             UT, ["test_paired_same_family_sequence"]),
    Mutation("M-T29-53 lần None coi là 0 thay vì bỏ",
             [one(STA, _NONE_SKIP, "        values.append(0.0 if v is None else v)  # MUTATION M-T29-53\n")],
             UT, ["test_bootstrap_undefined_counted"]),
    Mutation("M-T29-54 point = trung bình các lần rút thay vì dữ liệu gốc",
             [_st(_POINT, "    point: float | None = None\n", "M-T29-54"),
              one(STA, _INTERVAL, _INTERVAL + "    point = float(np.mean(values)) if values else None  # MUTATION M-T29-54\n")],
             UT, ["test_point_is_on_original_data"]),
    Mutation("M-T29-55 paired bỏ kiểm tập họ A = B",
             [_st(_SAME_FAM, "    if False:\n", "M-T29-55")],
             UT, ["test_paired_family_mismatch"]),
    # ---- bổ sung (ngoài danh sách tối thiểu S4) ----
    Mutation("M-T29-56 bỏ kiểm n_boot ≥ 1",
             [_st(_NBOOT, "    if isinstance(n_boot, bool) or not isinstance(n_boot, Integral):\n", "M-T29-56")],
             UT, ["test_bad_args_raise[kwargs0-n_boot]", "test_bad_args_raise[kwargs1-n_boot]"]),
    Mutation("M-T29-57 contains_zero dùng bất đẳng thức chặt",
             [_st(_ZERO, "    contains_zero = lo < 0.0 < hi if lo is not None and hi is not None else None\n", "M-T29-57")],
             UT, ["test_paired_identical_zero_width"]),
]  # fmt: skip

ALL = S1 + S2 + S3 + S4
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
