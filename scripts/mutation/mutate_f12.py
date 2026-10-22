"""Mutation tay F12 (#45) — nhóm N3 của lá (E5 `llm_high_risk` → sensitive), `multi_intent_first_stop_to_reply_s` (vòng đầu,
trung vị), nguồn pending riêng của `messages_per_turn`, E1 `split_span_invalid`, migration 0011 (GRANT cột, view, downgrade).
Khung giống `mutate_g1.py`: mỗi đột biến áp lên file thật, chạy test, khôi phục trong `finally`, so md5 + `git diff --stat`.

Chốt N3 VIẾT LẠI ở đây, KHÔNG import `n3.py` (file đó nằm trong danh sách chặn đọc tới 25/10 — import = chạy code của file bị chặn):
(a) file đích còn chữ `MUTATION` → dừng; (b) mốc xanh một lần trước khi đột biến; (c) sau khi chạy: md5 khớp, `git diff --stat` khớp,
không file đích nào còn chữ `MUTATION`; (d) chuỗi gốc của đột biến cũ (`mutate_a4.py`) và của file này vẫn xuất hiện ĐÚNG 1 lần trong
mỗi file đích nếu có xuất hiện — đọc VĂN BẢN script bằng `ast` (không import).

  uv run python scripts/mutation/mutate_f12.py --unit              # 5 đột biến, unit — không cần Docker
  uv run python scripts/mutation/mutate_f12.py --pg                # 12 đột biến, integration — CẦN Docker (testcontainers)
  uv run python scripts/mutation/mutate_f12.py --pg --only M-F12-4 # chỉ các mã này
  uv run python scripts/mutation/mutate_f12.py --check-old         # chỉ chạy N3d

Mọi lệnh pytest chạy `--tb=no`; script chỉ in node id của test đỏ (không in thông điệp, không traceback). Không đọc `.env`.
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
    return ["uv", "run", "pytest", *args, "-q", "--tb=no", "-p", "no:cacheprovider"]


BUS = "backend/app/monitor/queries/business.py"
AI = "backend/app/monitor/queries/ai.py"
MET = "backend/app/monitor/metrics.py"
MIG = "backend/app/db/alembic/versions/0011_monitor_child_notices.py"
UT = pt(
    "backend/tests/unit/test_monitor_dash_metrics.py", "backend/tests/unit/test_monitor_dash_ai.py",
    "backend/tests/unit/test_monitor_dash_business.py",
)  # fmt: skip
PG_BUS = pt("backend/tests/integration/test_monitor_dash_business_pg.py")
PG_AI = pt("backend/tests/integration/test_monitor_dash_ai_pg.py")
PG_MIG = pt("backend/tests/integration/test_monitor_child_notices_pg.py")
OLD_SCRIPTS = ("mutate_a4.py", "mutate_f12.py")


class Mutation(NamedTuple):
    name: str
    mode: str  # "unit" | "pg"
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ (không có "[…]" → mọi tham số của test đó đều tính)


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


def _swap(rel: str, old: str, new: str, tag: str) -> tuple[str, str, str, int]:
    return one(rel, old, new.rstrip("\n") + f"  # MUTATION {tag}\n")


# ---- N3 của lá (business.py `_LEAF_N3_SEV_SQL`) ------------------------------------------------------------------------

_N3_HEAD = "    \"CASE WHEN t.exit_code = 'E5' AND (SELECT e.reason_detail FROM escalations e WHERE e.ticket_id = t.ticket_id \"\n"
_N3_MID = "    \"AND e.exit_code = 'E5' ORDER BY e.created_at DESC, e.escalation_id DESC LIMIT 1) \"\n"
_N3_THEN = '    "= ANY(CAST(:e5_sensitive AS text[])) THEN 3 "\n'
_N3_USE = '        f"SELECT t.exit_code, {_LEAF_N3_SEV_SQL} AS sev "\n'

# ---- first_stop (ai.py) ------------------------------------------------------------------------------------------------

_FS_HAVING = '        "GROUP BY t.parent_ticket_id HAVING min(t.created_at) >= :frm AND min(t.created_at) < :to), "\n'
_FS_R1 = '        f"r1 AS (SELECT n.parent_ticket_id AS p, min(n.delivered_round) AS r FROM {V_CHILD_NOTICES} n "\n'
_FS_R1_WHERE = '        "JOIN par ON par.p = n.parent_ticket_id WHERE n.delivered_round IS NOT NULL GROUP BY n.parent_ticket_id), "\n'
_FS_ROUND = '        f"FROM {V_CHILD_NOTICES} n JOIN r1 ON r1.p = n.parent_ticket_id AND n.delivered_round = r1.r "\n'
_FS_MEDIAN = '        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY per.s) FROM per"\n'

# ---- metrics.py --------------------------------------------------------------------------------------------------------

_E5 = 'E5_SENSITIVE_REASONS: tuple[str, ...] = ("llm_high_risk",)\n'
_FIRST = '    "multi_intent_first_stop_to_reply_s": _ready("child_notices", "tickets"),  # F12: v_child_notices (0011) → v_leaf\n'
_PER_TURN = '    "multi_intent_messages_per_turn": _pending("d30_parent_turns", "turns", "tickets"),\n'
_E1 = '    "out_of_scope", "multi_intent_not_enabled", "intent_low_confidence", "intent_not_enabled", "split_span_invalid",\n'

# ---- migration 0011 ----------------------------------------------------------------------------------------------------

_GRANT = "    op.execute(f\"GRANT SELECT ({', '.join(NOTICE_COLUMNS)}) ON child_notices TO {MONITOR_ROLE}\")\n"
_VIEW = 'VIEW_SQL = f"SELECT {_cols(\'n\', NOTICE_COLUMNS)} FROM child_notices n JOIN v_leaf c ON c.ticket_id = n.child_ticket_id"\n'
_REVOKE = "    op.execute(f\"REVOKE SELECT ({', '.join(NOTICE_COLUMNS)}) ON child_notices FROM {MONITOR_ROLE}\")\n"

_N3_TEST = "test_weighted_e5_llm_high_risk_sensitive"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-F12-1 bỏ quy tắc E5 (luôn ELSE)", "pg",
             [_swap(BUS, _N3_THEN, '    "= ANY(CAST(:e5_sensitive AS text[])) AND FALSE THEN 3 "', "M-F12-1")], PG_BUS,
             [_N3_TEST]),
    Mutation("M-F12-2 mọi E5 → sensitive (bỏ điều kiện reason)", "pg",
             [one(BUS, _N3_HEAD + _N3_MID + _N3_THEN,
                  "    \"CASE WHEN t.exit_code = 'E5' AND CAST(:e5_sensitive AS text[]) IS NOT NULL THEN 3 \"  # MUTATION M-F12-2\n")],
             PG_BUS, [_N3_TEST]),
    Mutation("M-F12-3 bỏ t.exit_code = 'E5' (mã khác có dòng E5 llm_high_risk)", "pg",
             [_swap(BUS, _N3_HEAD, _N3_HEAD.replace("t.exit_code = 'E5' AND ", "TRUE AND "), "M-F12-3")], PG_BUS,
             [_N3_TEST]),
    Mutation("M-F12-4 dòng E5 mới nhất → bất kỳ dòng nào", "pg",
             [one(BUS, _N3_HEAD + _N3_MID + _N3_THEN,
                  "    \"CASE WHEN t.exit_code = 'E5' AND EXISTS (SELECT 1 FROM escalations e WHERE e.ticket_id = t.ticket_id \"\n"
                  "    \"AND e.exit_code = 'E5' AND e.reason_detail = ANY(CAST(:e5_sensitive AS text[]))) THEN 3 \"  # MUTATION M-F12-4\n")],
             PG_BUS, [_N3_TEST]),
    Mutation("M-F12-5 hằng E5 sai lý do (llm_layer_disabled)", "unit",
             [_swap(MET, _E5, _E5.replace("llm_high_risk", "llm_layer_disabled"), "M-F12-5")], UT,
             ["test_e5_sensitive_reasons_constant"]),
    Mutation("M-F12-5pg hằng E5 sai lý do (llm_layer_disabled)", "pg",
             [_swap(MET, _E5, _E5.replace("llm_high_risk", "llm_layer_disabled"), "M-F12-5pg")], PG_BUS,
             [_N3_TEST]),
    Mutation("M-F12-6 first_stop bỏ lọc vòng đầu", "pg",
             [_swap(AI, _FS_ROUND, _FS_ROUND.replace("AND n.delivered_round = r1.r", "AND (n.delivered_round = r1.r OR TRUE)"),
                    "M-F12-6")], PG_AI, ["test_first_stop_odd_median"]),
    Mutation("M-F12-7 vòng đầu → vòng cuối (max)", "pg",
             [_swap(AI, _FS_R1, _FS_R1.replace("min(n.delivered_round)", "max(n.delivered_round)"), "M-F12-7")], PG_AI,
             ["test_first_stop_odd_median"]),
    Mutation("M-F12-8 trung vị → trung bình", "pg",
             [_swap(AI, _FS_MEDIAN, _FS_MEDIAN.replace("percentile_cont(0.5) WITHIN GROUP (ORDER BY per.s)", "avg(per.s)"),
                    "M-F12-8")], PG_AI, ["test_first_stop_odd_median"]),
    Mutation("M-F12-9 cửa sổ theo created_at của notice thay vì con", "pg",
             [_swap(AI, _FS_HAVING, '        "GROUP BY t.parent_ticket_id HAVING TRUE), "', "M-F12-9"),
              _swap(AI, _FS_R1_WHERE, _FS_R1_WHERE.replace(
                  "IS NOT NULL GROUP BY", "IS NOT NULL AND n.created_at >= :frm AND n.created_at < :to GROUP BY"), "M-F12-9")],
             PG_AI, ["test_first_stop_window_by_children"]),
    Mutation("M-F12-10 first_stop về pending", "unit",
             [_swap(MET, _FIRST, '    "multi_intent_first_stop_to_reply_s": _pending("phase5_multi_intent", "child_notices", "tickets"),',
                    "M-F12-10")], UT, ["test_multi_intent_sources_split", "test_queries_cover_ai_metrics"]),
    Mutation("M-F12-11 messages_per_turn thành ready", "unit",
             [_swap(MET, _PER_TURN, '    "multi_intent_messages_per_turn": _ready("turns", "tickets"),', "M-F12-11")], UT,
             ["test_multi_intent_sources_split", "test_is_pending_values", "test_queries_cover_ai_metrics"]),
    Mutation("M-F12-12 E1 bỏ split_span_invalid", "unit",
             [_swap(MET, _E1, _E1.replace(' "split_span_invalid",', ""), "M-F12-12")], UT,
             ["test_e1_reasons_cover_graph_children", "test_e1_reasons_verbatim_reason_detail"]),
    Mutation("M-F12-12b escalation_rate_weighted tự viết CASE, không dùng _LEAF_N3_SEV_SQL", "unit",
             [_swap(BUS, _N3_USE,
                    '        f"SELECT t.exit_code, CASE WHEN TRUE THEN COALESCE((SELECT max({_SEVERITY_SQL}) FROM {V_DECISIONS} d '
                    'WHERE d.ticket_id = t.ticket_id), 1) END AS sev "', "M-F12-12b")], UT,
             ["test_leaf_n3_single_source"]),
    Mutation("M-F12-13 GRANT thêm cột body", "pg",
             [_swap(MIG, _GRANT, _GRANT.replace("', '.join(NOTICE_COLUMNS)", "', '.join((*NOTICE_COLUMNS, 'body'))"),
                    "M-F12-13")], PG_MIG, ["test_app_monitor_cannot_read_body"]),
    Mutation("M-F12-14 view bỏ JOIN v_leaf", "pg",
             [_swap(MIG, _VIEW, _VIEW.replace(" JOIN v_leaf c ON c.ticket_id = n.child_ticket_id", ""), "M-F12-14")], PG_MIG,
             ["test_view_columns_and_d30"]),
    Mutation("M-F12-15 downgrade không REVOKE", "pg",
             [_swap(MIG, _REVOKE, "    pass", "M-F12-15")], PG_MIG, ["test_migration_0011_up_down_up"]),
]  # fmt: skip


def _selected() -> list[Mutation]:
    mode = "pg" if "--pg" in sys.argv else "unit"
    only = sys.argv[sys.argv.index("--only") + 1 :] if "--only" in sys.argv else []
    only = [o for o in only if not o.startswith("--")]
    return [m for m in MUTATIONS_ALL if m.mode == mode and (not only or m.name.split()[0] in only)]


MUTATIONS = _selected()


def test_env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


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


def _targets() -> list[str]:
    return sorted({rel for m in MUTATIONS_ALL for rel, *_ in m.edits})


def check_old() -> list[str]:
    """N3d: chuỗi của các script đột biến có mặt trong file đích thì phải đúng 1 lần (mọi edit dùng `one`)."""
    bad: list[str] = []
    for rel in _targets():
        text = (REPO / rel).read_text(encoding="utf-8")
        for name in OLD_SCRIPTS:
            for s in sorted(_line_strings(REPO / "scripts/mutation" / name)):
                if text.count(s) > 1:
                    bad.append(f"{name} → {rel}: {s.strip()[:60]!r} ×{text.count(s)}")
    return bad


def _node_ids(stdout: str) -> list[str]:
    """Chỉ node id của test đỏ (phần trước " - " của dòng FAILED) — không lấy thông điệp."""
    return sorted(set(re.findall(r"^FAILED (\S+?::\w+(?:\[.*?\])?)(?: - |$)", stdout, re.MULTILINE)))


def guard(files: list[str], cmds: list[list[str]], env: dict[str, str]) -> int | None:
    """N3 (viết lại, không import n3): (a) không file đích nào còn dấu `MUTATION`; (d) chuỗi gốc cũ đúng 1 lần; (b) mốc xanh."""
    left = marked(files)
    if left:
        print(f"DỪNG (N3a): file đích còn chữ {MARK!r} {left} — khôi phục tay trước")
        return 2
    dup = check_old()
    if dup:
        print("DỪNG (N3d): chuỗi gốc đột biến xuất hiện > 1 lần:")
        print("    " + "\n    ".join(dup))
        return 2
    print(f"N3d: chuỗi gốc của {', '.join(OLD_SCRIPTS)} — không chuỗi nào lặp trong {len(_targets())} file đích")
    for cmd in {tuple(c): c for c in cmds}.values():
        out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        if out.returncode != 0:
            print(f"DỪNG (N3b): mốc chưa xanh — {' '.join(cmd)}")
            for f in _node_ids(out.stdout) or ["(không đọc được node id — mã thoát " + str(out.returncode) + ")"]:
                print(f"    {f}")
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
        n = sum(len(_line_strings(REPO / "scripts/mutation" / s)) for s in OLD_SCRIPTS)
        print(f"N3d: {n} hằng chuỗi nhiều dòng trong {len(OLD_SCRIPTS)} script, {len(_targets())} file đích")
        for d in dup:
            print(f"    LẶP {d}")
        print("N3d: ĐẠT" if not dup else "N3d: KHÔNG ĐẠT")
        return 1 if dup else 0
    if not MUTATIONS:
        print("DỪNG: không có đột biến nào khớp chế độ/`--only`")
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
        failed = _node_ids(out.stdout)
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in m.expect if not _hit(e, failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        bad += bool(missing)
        print(f"{m.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing} (mã thoát {out.returncode})")
    after = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 sau    {after[rel]}  {rel}")
    assert after == before, "md5 khác sau khôi phục!"
    print("md5 sau khôi phục: khớp")
    assert git_diff_stat() == diff_before, "git diff --stat khác lúc đầu!"
    print("git diff --stat: khớp lúc đầu")
    assert not marked(files), f"còn chữ {MARK!r} trong file đích sau khôi phục!"
    print(f"không còn chữ {MARK!r} trong file đích")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
