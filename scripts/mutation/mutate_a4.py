"""Mutation chặng M9 A4 (#11, PR #38): `/api/health` (llm, monitor, cache 10 s), engine monitor read-only, bộ quét D-30,
seed hiệu năng 10.000 ticket, migration 0009. 32 đột biến; mỗi đột biến chỉ chạy ở chế độ có dự đoán cho nó.

  uv run python scripts/mutation/mutate_a4.py --check            # áp mọi đột biến TRONG BỘ NHỚ + collect: không ghi file, không chạy test
  uv run python scripts/mutation/mutate_a4.py --unit             # 27 đột biến, unit — không cần Docker
  uv run python scripts/mutation/mutate_a4.py --pg               # 9 đột biến, integration — CẦN Docker (testcontainers)
  uv run python scripts/mutation/mutate_a4.py --pg I1 H14        # chỉ các mã này (dùng được cho cả --unit)

Mỗi đột biến: in dự đoán → thay đúng chuỗi, đúng 1 lần, trong đúng vùng → chạy test → so đỏ thật với dự đoán → hoàn
nguyên trong `finally` (ghi lại nguyên byte gốc giữ trong bộ nhớ, đọc lại so khớp byte). Cuối lượt so sha256 mọi file
đích trước/sau — khác thì dừng bằng AssertionError. Không ghi file nào trong repo ngoài file đích đang đột biến; junit XML
nằm trong `tempfile.TemporaryDirectory`.

Tiêu chí: DỰ ĐOÁN ⊆ ĐỎ THẬT (đỏ thêm ngoài dự đoán được in ra, không tính là sai). Dự đoán ghi bằng NODE ID ĐẦY ĐỦ
(chữ Unicode thật). Đỏ thật lấy từ `--junitxml` (classname + name → node id nguyên vẹn, kể cả khoảng trắng); hai phía
cùng chuẩn hoá: giải escape `\\uXXXX`/`\\xXX` pytest gắn vào tham số không-ASCII, rồi NFC. So khớp = bằng nhau đúng.
Bảo hiểm: số ca đỏ đọc được phải bằng failures+errors junit khai; mã thoát ≠ 0 mà không đọc được ca nào → KHÔNG KHỚP.
`--check` còn collect mọi file test và đòi từng node id dự đoán phải tồn tại (gõ sai tên → lỗi ngay, không âm thầm).
Đột biến dự đoán SỐNG (lỗ hổng đã biết, ghi rõ lý do) đạt khi KHÔNG test nào đỏ.

Nhóm: H = /api/health, probe llm/monitor, engine read-only · D = bộ quét D-30 · P = seed hiệu năng · I = migration 0009
(mỗi chỉ mục một đột biến + vị từ, downgrade, down_revision).
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path


def _repo_root() -> Path:
    """Gốc repo = `git rev-parse --show-toplevel` tính từ thư mục của script; phải có `pyproject.toml` và `backend/`."""
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).resolve().parent,
                         capture_output=True, text=True, check=True)  # fmt: skip
    root = Path(out.stdout.strip())
    if not ((root / "pyproject.toml").is_file() and (root / "backend").is_dir()):
        raise SystemExit(f"{root} không phải gốc repo (thiếu pyproject.toml hoặc backend/)")
    return root


REPO = _repo_root()
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # không sinh __pycache__ mới trong repo khi chạy test

# ---- file nguồn bị đột biến ----
HEALTH = "backend/app/api/health.py"
MAIN = "backend/app/main.py"
SESSION = "backend/app/db/session.py"
MIG9 = "backend/app/db/alembic/versions/0009_monitor_indexes.py"
SEED = "backend/tests/integration/monitor_perf_seed.py"
# ---- file test ----
U_MH = "backend/tests/unit/test_monitor_health.py"
U_H = "backend/tests/unit/test_health.py"
U_DB = "backend/tests/unit/test_monitor_dash_business.py"  # chứa CẢ bộ quét D-30 (nhóm D đột biến chính file này)
U_PS = "backend/tests/unit/test_monitor_perf_seed.py"
P_MH = "backend/tests/integration/test_monitor_health_pg.py"
P_PERF = "backend/tests/integration/test_monitor_perf_pg.py"
P_MIG = "backend/tests/integration/test_migration.py"
UNIT_FILES = [U_MH, U_H, U_DB, U_PS]

END = "\nZZZ-het-file"  # mốc cuối vùng = hết file
SURVIVES = "SONG"  # dự đoán: đột biến sống (lỗ hổng đã biết)

type Pred = str  # node id đầy đủ: "<file>::<tên test>[<id tham số>]" (chữ Unicode thật)
type Edit = tuple[str, str, str, str, str]  # (file, mốc đầu vùng, mốc cuối vùng, chuỗi gốc, chuỗi mới)


def p(file: str, test: str) -> Pred:
    """`test` = tên test + tham số nguyên vẹn, đúng như `pytest --collect-only -q` in (sau khi giải escape)."""
    return f"{file}::{test}"


def norm(nodeid: str) -> str:
    """Escape kiểu pytest (`\\u0111`, `\\xe1`) → ký tự thật, rồi NFC. Ký tự thật có sẵn đi qua nguyên vẹn."""
    return unicodedata.normalize("NFC", nodeid.encode("ascii", "backslashreplace").decode("unicode_escape"))


# Vùng
R_HEALTH = ("async def _health(", "\n@router.get(")
R_STATUS = ("def llm_status(", "\ndef _default_llm_probe(")
R_TARGETS = ("def llm_targets(", "\ndef _llm_priced(")
R_LLM_PROBE = ("def _default_llm_probe(", "\ndef _default_monitor_probe(")
R_MON_PROBE = ("def _default_monitor_probe(", "\ndef _build_auth(")
R_ENGINES = ("def create_engines(", "\nasync def ping(")
R_UP = ("def upgrade(", "\ndef downgrade(")
R_DOWN = ("def downgrade(", END)
R_HEAD = ('revision: str = "0009"', "\nAUDIT_EXIT_INDEX")
R_TABLE_NAME = ("def _table_name(", "\ndef _tables(")
R_SPLIT = ("def _split_commas(", "\ndef _table_name(")
R_RENDER = ("def _render(", "\ndef _assigned_strings(")
R_SCAN_DIR = ("def _scan_dir(", "\ndef test_d30_glob_scans_queries(")
R_SEED_TOP = ("_P = 10_007", "\n_USERS = ")
R_POINT4 = ("_AUDIT_POINT4 = f", "\n# B9 (kb_version")

AUDIT_INDEX_BLOCK = (
    "    op.create_index(\n"
    "        AUDIT_EXIT_INDEX,\n"
    '        "audit_logs",\n'
    '        ["created_at"],\n'
    "        unique=False,\n"
    '        postgresql_where=sa.text("exit_code IS NOT NULL"),\n'
    "    )\n"
)
EXITS = ("E0,24h", "E7,24h", "E9,192h", "E6,192h")
USABLE_AUDIT = [p(P_PERF, f"test_index_usable_with_seqscan_off[ix_audit_logs_exit_created_at:TICKET_EXIT_SQL[{c}]]")
                for c in EXITS]  # fmt: skip
CHOSEN_AUDIT = [p(P_PERF, f"test_index_chosen_naturally[ix_audit_logs_exit_created_at:TICKET_EXIT_SQL[{c}]]")
                for c in EXITS]  # fmt: skip
USABLE_APPR = [p(P_PERF, f"test_index_usable_with_seqscan_off[ix_approvals_ticket:{t}]")
               for t in ("automation_rate[30d]", "approval_expired_count[own]", "decided_by_distribution[own]",
                         "top_matched_rules[own]")]  # fmt: skip
TABLE = "test_llm_status_table"

# (mã, mô tả, sửa, dự đoán unit, dự đoán pg) — None = đột biến không có phần chạy ở chế độ đó
MUTATIONS: list[tuple[str, str, list[Edit], list[Pred] | str | None, list[Pred] | str | None]] = [
    # ---- H: S1 ----
    ("H1", "bỏ cache response (luôn tính lại)",
     [(HEALTH, *R_HEALTH, "        if cached is not None and now - cached[0] < HEALTH_CACHE_SECONDS:\n",
       "        if False:  # H1\n")],
     [p(U_MH, "test_two_calls_within_10s_check_each_dependency_once"), p(U_MH, "test_concurrent_calls_single_flight"),
      p(U_MH, "test_503_is_cached_too")], None),
    ("H2", "biên 10 giây: < thành <=",
     [(HEALTH, *R_HEALTH, "now - cached[0] < HEALTH_CACHE_SECONDS", "now - cached[0] <= HEALTH_CACHE_SECONDS")],
     [p(U_MH, "test_two_calls_within_10s_check_each_dependency_once"), p(U_MH, "test_503_is_cached_too")], None),
    ("H3", "bỏ khoá single-flight",
     [(HEALTH, *R_HEALTH, "    async with lock:\n", "    if True:  # H3\n")],
     [p(U_MH, "test_concurrent_calls_single_flight")], None),
    ("H4", "llm=spend_cap_reached đổi mã thành 503",
     [(HEALTH, *R_HEALTH, "code = 200 if not failed else 503",
       'code = 200 if not failed and llm != "spend_cap_reached" else 503')],
     [p(U_MH, "test_llm_never_changes_status_code[ok-200-spend_cap_reached]")], None),
    ("H5", "monitor=wrong_role đổi mã thành 503",
     [(HEALTH, *R_HEALTH, "code = 200 if not failed else 503",
       'code = 200 if not failed and monitor != "wrong_role" else 503')],
     [p(U_MH, "test_monitor_never_changes_status_code[ok-200-wrong_role]")],
     [p(P_MH, "test_health_monitor_wrong_role_with_app_rw_dsn")]),
    ("H6", "trần chi so > thay >=",
     [(MAIN, *R_STATUS, "spent_usd >= cap_usd", "spent_usd > cap_usd")],
     [p(U_MH, f"{TABLE}[đúng trần (so >=)-real-models8-38.0-spend_cap_reached]"),
      p(U_MH, "test_llm_status_covers_all_four_values"), p(U_MH, "test_llm_probe_spend_cap_reached")], None),
    ("H7", "đọc tổng chi lỗi → real:configured (không fail-closed)",
     [(MAIN, *R_STATUS, '        return "unknown"\n    return "spend_cap_reached"',
       '        return "real:configured"\n    return "spend_cap_reached"')],
     [p(U_MH, f"{TABLE}[đọc tổng chi lỗi-real-models7-None-unknown]"), p(U_MH, "test_llm_probe_spend_error_is_unknown")],
     None),
    ("H8", ("llm_targets bỏ model fallback (lỗ hổng cũ: llm.yaml thật có fallback rỗng — đã thêm test có fallback "
            "thiếu giá)"),
     [(MAIN, *R_TARGETS, "        out.extend(f.model for f in cfg.fallback[r])\n", "")],
     [p(U_MH, "test_llm_probe_fallback_missing_price")], None),
    ("H9", "kiểm scripted SAU kiểm giá/trần (scripted giá 0 → ra real:configured)",
     [(MAIN, *R_STATUS, '    if backend == "scripted":  # giá 0 → trần chi không áp (Q-3d-4)\n        return "scripted"\n',
       ""),
      (MAIN, *R_STATUS, '    return "spend_cap_reached" if spent_usd >= cap_usd else "real:configured"',
       ('    if backend == "scripted":  # H9\n        return "scripted"\n'
        '    return "spend_cap_reached" if spent_usd >= cap_usd else "real:configured"'))],
     [p(U_MH, f"{TABLE}[scripted-scripted-models1-None-scripted]"),
      p(U_MH, f"{TABLE}[scripted vượt trần-scripted-models2-99.0-scripted]"),
      p(U_MH, "test_llm_status_covers_all_four_values"), p(U_MH, "test_llm_probe_scripted_does_not_read_spend"),
      p(U_H, "test_all_ok_returns_200")], None),
    ("H10", "bỏ điều kiện 'có đích trả phí' (đích miễn phí cũng bị trần chặn)",
     [(MAIN, *R_STATUS, '    if not _llm_paid(models, pricing):\n        return "real:configured"\n', "")],
     [p(U_MH, f"{TABLE}[đích miễn phí vượt trần-real-models11-99.0-real:configured]"),
      p(U_MH, "test_llm_probe_reads_spend_only_when_needed")], None),
    ("H11", "probe monitor bỏ so current_user với app_monitor",
     [(MAIN, *R_MON_PROBE, "        if user != MONITOR_ROLE:\n", "        if False:  # H11\n")],
     [p(U_MH, "test_monitor_probe_wrong_role_logs_error")],
     [p(P_MH, "test_health_monitor_wrong_role_with_app_rw_dsn")]),
    ("H12", "bỏ log.error khi sai role",
     [(MAIN, *R_MON_PROBE, '            log.error("monitor DSN sai role: %s — M9 phải chạy bằng %s", user, MONITOR_ROLE)\n',
       "            pass  # H12\n")],
     [p(U_MH, "test_monitor_probe_wrong_role_logs_error")],
     [p(P_MH, "test_health_monitor_wrong_role_with_app_rw_dsn")]),
    ("H13", "thiếu DSN monitor → ping engines.main (rơi về app_rw)",
     [(MAIN, *R_MON_PROBE, '        except MonitorUnavailable:\n            return "not_configured"\n',
       "        except MonitorUnavailable:\n            engine = app.state.engines.main  # H13\n")],
     [p(U_MH, "test_monitor_probe_not_configured_does_not_touch_main")],
     [p(P_MH, "test_health_monitor_not_configured_without_dsn")]),
    ("H14", "engine monitor bỏ default_transaction_read_only=on",
     [(SESSION, *R_ENGINES, '            connect_args={"options": "-c default_transaction_read_only=on"},\n', "")],
     None,
     [p(P_MH, "test_monitor_engine_default_read_only"),
      p(P_MH, "test_monitor_engine_read_only_blocks_write_even_with_rw_dsn")]),
    ("H15", "probe llm tham chiếu open_llm (dựng gateway)",
     [(MAIN, *R_LLM_PROBE, '        cfg = load_llm_config(settings.config_dir / "llm.yaml")\n',
       '        cfg = load_llm_config(settings.config_dir / "llm.yaml")\n        _ = open_llm  # H15\n')],
     [p(U_MH, "test_llm_probe_never_builds_provider")], None),
    # ---- D: S2 (bộ quét D-30 nằm trong chính file test) ----
    ("D1", "bỏ tách tiền tố schema",
     [(U_DB, *R_TABLE_NAME, '    return name.replace(\'"\', "").split(".")[-1].lower()',
       '    return name.replace(\'"\', "").lower()')],
     [p(U_DB, "test_d30_catches_schema_qualified"), p(U_DB, "test_d30_catches_quoted"),
      p(U_DB, "test_d30_catches_comma_join"), p(U_DB, "test_d30_tables_helper")], None),
    ("D2", "bỏ gỡ ngoặc kép",
     [(U_DB, *R_TABLE_NAME, '    return name.replace(\'"\', "").split(".")[-1].lower()',
       '    return name.split(".")[-1].lower()')],
     [p(U_DB, "test_d30_catches_quoted"), p(U_DB, "test_d30_tables_helper")], None),
    ("D3", "chỉ xét mục đầu sau FROM (không tách dấu phẩy)",
     [(U_DB, *R_SPLIT, "    items, depth, start = [], 0, 0\n",
       "    return [segment]  # D3\n    items, depth, start = [], 0, 0\n")],
     [p(U_DB, "test_d30_catches_comma_join"), p(U_DB, "test_d30_tables_helper")], None),
    ("D4", "không giải {Name} trong f-string",
     [(U_DB, *R_RENDER, "            pieces = consts.get(part.value.id, {_EXPR})", "            pieces = {_EXPR}")],
     [p(U_DB, "test_d30_catches_fstring_name")], None),
    ("D5", "rglob → glob (sót thư mục con)",
     [(U_DB, *R_SCAN_DIR, 'for p in sorted(root.rglob("*.py"))', 'for p in sorted(root.glob("*.py"))')],
     [p(U_DB, "test_d30_catches_subdir")], None),
    ("D6", "tách dấu phẩy không theo độ sâu ngoặc",
     [(U_DB, *R_SPLIT, "    items, depth, start = [], 0, 0\n",
       '    return segment.split(",")  # D6\n    items, depth, start = [], 0, 0\n')],
     [p(U_DB, "test_d30_no_false_positive_synthetic[alias co cot ten tickets]"), p(U_DB, "test_d30_tables_helper")],
     None),
    # ---- P: S3a (seed hiệu năng) ----
    ("P1", "_TS trở lại %% (lỗi lượt (c) lần 1)",
     [(SEED, "# `ts(i)` rải đều", "\n_USERS = ", "make_interval(days => (i % {DAYS})::int",
       "make_interval(days => (i %% {DAYS})::int")],
     [p(U_PS, "test_seed_sql_has_no_double_percent_at_postgres[tickets (cha)]"),
      p(U_PS, "test_seed_sql_has_no_double_percent_at_postgres[security_events]"),
      p(U_PS, "test_timestamp_expression_keeps_modulo")], None),
    ("P2", "SALT_OVERRIDE trùng SALT_STATE",
     [(SEED, *R_SEED_TOP, "SALT_OVERRIDE = 1009", "SALT_OVERRIDE = 7919")],
     [p(U_PS, "test_mix_is_bigint_and_uses_salt")], None),
    ("P3", "SALT_OVERRIDE = 0 (mọi i rơi về 0)",
     [(SEED, *R_SEED_TOP, "SALT_OVERRIDE = 1009", "SALT_OVERRIDE = 0")],
     [p(U_PS, "test_mix_is_bigint_and_uses_salt")], None),
    ("P4", "p_method trở lại 'platt' (lỗi lượt (c) lần 2)",
     [(SEED, *R_POINT4, "(ARRAY['self_report','sampling_k5'])[1 + (i / 2) % 2]", "'platt'")],
     [p(U_PS, "test_seed_sql_satisfies_check_and_not_null[audit \u0111i\u1ec3m 4]")], None),
    ("P5", "p_method rẽ nhánh theo điều kiện khác decided_by",
     [(SEED, *R_POINT4, "CASE WHEN i % 2 = 0 THEN NULL ELSE (ARRAY['self_report'",
       "CASE WHEN i % 3 = 0 THEN NULL ELSE (ARRAY['self_report'")],
     [p(U_PS, "test_point4_combination_consistent")], None),
    ("P6", "matched_rule_id ghi cho mọi dòng (cả decided_by=llm)",
     [(SEED, *R_POINT4, "CASE WHEN i % 2 = 0 THEN 'R' || lpad((1 + (i / 2) % 20)::text, 2, '0') ELSE NULL END",
       "'R' || lpad((1 + (i / 2) % 20)::text, 2, '0')")],
     [p(U_PS, "test_point4_combination_consistent")], None),
    # ---- I: S4 (migration 0009) ----
    ("I1", "migration bỏ chỉ mục audit_logs (A) — models vẫn khai",
     [(MIG9, *R_UP, AUDIT_INDEX_BLOCK, "")],
     None,
     [p(P_MIG, "test_models_match_migration"), p(P_PERF, "test_index_definitions"),
      p(P_PERF, "test_ticket_exit_partial_index_generic_plan"), p(P_PERF, "test_migration_0009_down_up"),
      *USABLE_AUDIT, *CHOSEN_AUDIT]),
    ("I2", "migration bỏ chỉ mục approvals(ticket_id) — models vẫn khai",
     [(MIG9, *R_UP, '    op.create_index(APPROVALS_TICKET_INDEX, "approvals", ["ticket_id"], unique=False)\n', "")],
     None,
     [p(P_MIG, "test_models_match_migration"), p(P_PERF, "test_index_definitions"),
      p(P_PERF, "test_migration_0009_down_up"), *USABLE_APPR,
      p(P_PERF, "test_index_chosen_naturally[ix_approvals_ticket:automation_rate[30d]]")]),
    ("I3", "chỉ mục audit bỏ vị từ WHERE exit_code IS NOT NULL (thành chỉ mục đầy đủ)",
     [(MIG9, *R_UP, '        postgresql_where=sa.text("exit_code IS NOT NULL"),\n', "")],
     None, [p(P_PERF, "test_index_definitions")]),
    ("I4", "downgrade sót chỉ mục audit",
     [(MIG9, *R_DOWN, '    op.drop_index(AUDIT_EXIT_INDEX, table_name="audit_logs")\n', "")],
     None, [p(P_PERF, "test_migration_0009_down_up")]),
    ("I5", "down_revision = 0007 (hai head)",
     [(MIG9, "Create Date: 2026-10-13", R_HEAD[1], 'down_revision: str | None = "0008"',
       'down_revision: str | None = "0007"')],
     [p(U_DB, "test_alembic_single_head_is_0009")], None),
]


def sha(rel: str) -> str:
    return hashlib.sha256((REPO / rel).read_bytes()).hexdigest()


def mutate(src: str, start: str, end: str, old: str, new: str, code: str) -> str:
    assert src.count(start) == 1, f"{code}: mốc vùng {start!r} xuất hiện {src.count(start)} lần"
    lo = src.index(start)
    hi = src.find(end, lo + len(start))
    hi = len(src) if hi < 0 else hi
    region = src[lo:hi]
    assert region.count(old) == 1, f"{code}: chuỗi gốc xuất hiện {region.count(old)} lần trong vùng {start!r}"
    return src[:lo] + region.replace(old, new) + src[hi:]


PYTEST = ["uv", "run", "pytest", "-o", "addopts=--import-mode=importlib", "-p", "no:cacheprovider"]


def junit_nodeid(classname: str, name: str, targets: list[str]) -> str:
    """Đảo `mangle_test_address` của pytest: classname = đường dẫn file (bỏ .py, '/'→'.') [+ '.Lớp'], name = phần cuối
    node id NGUYÊN VẸN (tham số, khoảng trắng, ngoặc lồng). Ghép theo file đích đã biết để không đoán dấu '.'."""
    for f in targets:
        mod = f.removesuffix(".py").replace("/", ".")
        if classname == mod:
            return f"{f}::{name}"
        if classname.startswith(mod + "."):
            return f"{f}::{classname[len(mod) + 1:].replace('.', '::')}::{name}"
        if not classname and name == mod:  # lỗi collect cả file: node id = đường dẫn file
            return f
    return f"?{classname}::{name}"  # không ghép được → vẫn tính là đỏ, in ra để thấy


def failed_tests(targets: list[str]) -> tuple[int, set[str], str]:
    """Đỏ thật = mọi <testcase> có con <failure>/<error> trong junit XML, node id đã chuẩn hoá.
    Bảo hiểm: số con failure+error đọc được phải bằng số junit khai ở <testsuite>."""
    with tempfile.TemporaryDirectory() as d:
        xml = Path(d) / "junit.xml"
        proc = subprocess.run([*PYTEST, *targets, "-q", "--no-header", f"--junitxml={xml}"],
                              cwd=REPO, env=ENV, capture_output=True, text=True, check=False)  # fmt: skip
        tail = (proc.stdout.strip().splitlines() or [proc.stderr.strip()[-200:]])[-1]
        if not xml.exists():
            raise RuntimeError(f"pytest không ghi junit XML (rc={proc.returncode}): {tail}")
        root = ET.parse(xml).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    declared = sum(int(s.get("failures", "0")) + int(s.get("errors", "0")) for s in suites)
    failed: set[str] = set()
    seen = 0
    for case in root.iter("testcase"):
        bad = [c for c in case if c.tag in ("failure", "error")]
        if bad:
            seen += len(bad)
            failed.add(norm(junit_nodeid(case.get("classname", ""), case.get("name", ""), targets)))
    if seen != declared:
        raise RuntimeError(f"junit khai {declared} failure+error nhưng đọc được {seen} — không tin được kết quả")
    if proc.returncode != 0 and not failed:
        raise RuntimeError(f"mã thoát {proc.returncode} mà không trích được ca đỏ nào: {tail}")
    return proc.returncode, failed, tail


def hit(pred: Pred, failed: set[str]) -> bool:
    return norm(pred) in failed


def label(nodeid: str) -> str:
    """Bỏ thư mục của file cho dễ đọc; giữ nguyên test + tham số (tham số có thể chứa '/', vd `audit B3/B4`)."""
    file, sep, rest = norm(nodeid).partition("::")
    return f"{Path(file).name}{sep}{rest}"


def listing(nodeids: "list[str] | set[str]") -> str:
    """Mỗi node id một dòng, nguyên vẹn (đã chuẩn hoá), sắp xếp."""
    return "".join(f"\n      {label(n)}" for n in sorted(norm(n) for n in nodeids))


def collected(files: list[str]) -> set[str]:
    proc = subprocess.run([*PYTEST, *files, "--collect-only", "-q"], cwd=REPO, env=ENV, capture_output=True, text=True,
                          check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"collect lỗi (rc={proc.returncode}): {proc.stdout[-500:]}{proc.stderr[-500:]}")
    return {norm(ln) for ln in proc.stdout.splitlines() if "::" in ln}


def run(mode: str, code: str, desc: str, edits: list[Edit], want_unit: list[Pred] | str | None,
        want_pg: list[Pred] | str | None) -> bool | None:  # fmt: skip
    want = want_unit if mode == "unit" else want_pg
    if want is None:
        return None
    if want == SURVIVES:
        targets = UNIT_FILES if mode == "unit" else [P_MH, P_PERF, P_MIG]
        print(f"\n[{code}] {desc}\n  dự đoán: SỐNG", flush=True)
    else:
        assert isinstance(want, list)
        targets = UNIT_FILES if mode == "unit" else sorted({w.partition("::")[0] for w in want})
        print(f"\n[{code}] {desc}\n  dự đoán đỏ:{listing(want)}", flush=True)
    files = sorted({e[0] for e in edits})
    originals = {rel: (REPO / rel).read_bytes() for rel in files}  # bản gốc giữ trong bộ nhớ, không ghi file tạm
    try:
        texts = {rel: originals[rel].decode("utf-8") for rel in files}
        for rel, start, end, old, new in edits:
            texts[rel] = mutate(texts[rel], start, end, old, new, code)
        for rel, text in texts.items():
            (REPO / rel).write_text(text, encoding="utf-8")
        try:
            rc, failed, tail = failed_tests(targets)
        except RuntimeError as e:
            print(f"  LỖI ĐỌC KẾT QUẢ: {e}\n  → KHONG KHOP (không tin được)", flush=True)
            return False
        print(f"  pytest  : {tail}")
        print(f"  đỏ thật :{listing(failed) or ' (không)'}")
        if want == SURVIVES:
            ok = rc == 0 and not failed
            print(f"  → {'SONG, KHOP DU DOAN (lỗ hổng đã biết)' if ok else 'BI GIET — dự đoán SỐNG sai'}", flush=True)
            return ok
        assert isinstance(want, list)
        missing = [w for w in want if not hit(w, failed)]
        extra = {f for f in failed if not any(hit(w, {f}) for w in want)}
        if extra:
            print(f"  đỏ thêm (ngoài dự đoán):{listing(extra)}")
        if missing:
            print(f"  DỰ ĐOÁN KHÔNG ĐỎ:{listing(missing)}")
        ok = rc != 0 and not missing
        print(f"  → {'DO, KHOP DU DOAN' if ok else 'KHONG KHOP / SONG SOT!'}", flush=True)
        return ok
    finally:
        for rel, original in originals.items():
            (REPO / rel).write_bytes(original)
            assert (REPO / rel).read_bytes() == original, f"{code}: hoàn nguyên KHÔNG khớp byte — {rel}"


def check() -> int:
    """Áp từng đột biến TRONG BỘ NHỚ (không ghi file) — mọi chuỗi gốc phải khớp đúng 1 lần trong vùng của nó."""
    bad = 0
    for code, _desc, edits, _wu, _wp in MUTATIONS:
        texts: dict[str, str] = {}
        try:
            for rel, start, end, old, new in edits:
                texts.setdefault(rel, (REPO / rel).read_text(encoding="utf-8"))
                texts[rel] = mutate(texts[rel], start, end, old, new, code)
            print(f"  {code}: OK")
        except AssertionError as e:
            bad += 1
            print(f"  {code}: LỖI — {e}")
    print(f"\n{len(MUTATIONS) - bad}/{len(MUTATIONS)} đột biến áp được; không file nào bị ghi")
    preds = [w for m in MUTATIONS for want in (m[3], m[4]) if isinstance(want, list) for w in want]
    known = collected(sorted({w.partition("::")[0] for w in preds}))
    uniq = {norm(w) for w in preds}
    ghosts = sorted(uniq - known)
    for g in ghosts:
        print(f"  DỰ ĐOÁN KHÔNG TỒN TẠI (collect không có node id này): {g}")
    print(f"{len(uniq) - len(ghosts)}/{len(uniq)} node id dự đoán (khác nhau) có thật trong collect "
          f"({len(known)} node id đã collect)")
    return 1 if bad or ghosts else 0


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--check":
        return check()
    mode = {"--unit": "unit", "--pg": "pg"}.get(arg, "")
    if not mode:
        print(__doc__)
        return 2
    only = set(sys.argv[2:])
    chosen = [m for m in MUTATIONS if not only or m[0] in only]
    assert not only - {m[0] for m in chosen}, f"mã không có: {sorted(only - {m[0] for m in chosen})}"
    files = sorted({e[0] for m in chosen for e in m[2]})
    before = {f: sha(f) for f in files}
    results = {m[0]: run(mode, *m) for m in chosen}
    after = {f: sha(f) for f in files}
    assert before == after, "sha256 trước/sau KHÁC — kiểm tra hoàn nguyên"
    ran = {k: v for k, v in results.items() if v is not None}
    print(f"\n| Mã | Kết quả ({mode}) |\n|---|---|")
    for k, v in ran.items():
        print(f"| {k} | {'khop du doan' if v else 'KHONG KHOP'} |")
    print(f"\n{sum(ran.values())}/{len(ran)} khớp dự đoán; hoàn nguyên: sha256 mọi file đích trước/sau khớp")
    return 0 if all(ran.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
