"""A4 (#11) — SQL của seed hiệu năng (`tests/integration/monitor_perf_seed.py`) ở dạng Postgres THỰC NHẬN. Không Docker.

Lỗi lượt chạy thử S3a: nguồn viết `i %% 30` → `text()` escape thành `%%%%` → psycopg trả về `%%` → Postgres báo
"operator does not exist: integer %% integer". Trong `text()` phải viết MỘT dấu `%`.

Vì sao không assert trên chuỗi SQLAlchemy compile: với paramstyle `pyformat` của psycopg, SQLAlchemy escape MỌI `%`
đơn thành `%%` — câu ĐÚNG cũng chứa `%%` ở bước đó. "SQL cuối cùng" là chuỗi SAU khi psycopg đổi tham số: `%(tên)s`
→ `$n`, `%%` → `%` (luật pyformat của psycopg; đã đối chiếu với `psycopg._queries.PostgresQuery` của psycopg 3.3.6
trên cả 20 câu khi rà lỗi — test không gọi API nội bộ đó).
"""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import psycopg as pg_psycopg
from tests.integration import monitor_perf_seed as seed

_DIALECT = pg_psycopg.dialect()
_PLACEHOLDER = re.compile(r"%\(\w+\)s")
_STEPS = seed._STEPS


def postgres_sees(sql: str) -> str:
    """Chuỗi Postgres nhận: compile bằng dialect postgresql+psycopg rồi áp luật pyformat của psycopg."""
    compiled = str(text(sql).compile(dialect=_DIALECT))
    assert _DIALECT.paramstyle == "pyformat"  # luật dưới đây chỉ đúng cho pyformat
    return _PLACEHOLDER.sub("$p", compiled).replace("%%", "%")


@pytest.mark.parametrize(("name", "sql"), _STEPS, ids=[name for name, _ in _STEPS])
def test_seed_sql_has_no_double_percent_at_postgres(name: str, sql: str) -> None:
    """Không câu nào gửi `%%` tới Postgres (đủ 20 câu của `_STEPS`)."""
    final = postgres_sees(sql)
    assert "%%" not in final, f"{name}: Postgres sẽ nhận '%%' — trong text() chỉ viết một dấu %"


def test_all_twenty_statements_checked() -> None:
    """Danh sách tham số hoá ở trên không rỗng / không sót câu."""
    assert len(_STEPS) == 20


def test_rule_is_not_vacuous() -> None:
    """Canh chính phép kiểm: `%%` trong nguồn PHẢI bị bắt; `%` đơn PHẢI đi qua thành `%` (phép chia lấy dư)."""
    assert "%%" in postgres_sees("SELECT i %% 30 FROM generate_series(1, :n) AS s(i)")
    assert postgres_sees("SELECT i % 30 FROM generate_series(1, :n) AS s(i)") == (
        "SELECT i % 30 FROM generate_series(1, $p) AS s(i)"
    )


def test_timestamp_expression_keeps_modulo() -> None:
    """Biểu thức ngày/phút (`_TS`, dùng ở 3 câu) tới Postgres còn đúng một `%` mỗi chỗ."""
    final = postgres_sees(dict(_STEPS)["tickets (lá)"])
    assert f"(i % {seed.DAYS})::int" in final
    assert "((i * 7) % 1440)::int" in final


_NONDETERMINISTIC = ("random(", "setseed", "now()", "current_timestamp", "clock_timestamp", "gen_random_uuid",
                     "uuid_generate", "md5(")  # fmt: skip


@pytest.mark.parametrize(("name", "sql"), _STEPS, ids=[name for name, _ in _STEPS])
def test_seed_sql_is_deterministic(name: str, sql: str) -> None:
    """Docstring seed hứa "tất định tuyệt đối" — không hàm sinh ngẫu nhiên / đồng hồ nào trong SQL."""
    lowered = sql.lower()
    assert [f for f in _NONDETERMINISTIC if f in lowered] == [], name


def _salts() -> dict[str, int]:
    """MỌI hằng `SALT_*` của module seed — thêm salt mới thì tự được kiểm, không cần sửa test."""
    return {name: value for name, value in vars(seed).items() if name.startswith("SALT_")}


def test_mix_is_bigint_and_uses_salt() -> None:
    """`_mix` ép `bigint` (i · salt không tràn int4 khi seed lớn) và đúng công thức ((i · salt) mod P) mod k; mọi salt
    khác nhau (trùng → hai thuộc tính lại trùng nhịp, đúng lỗi phân phối của lượt (c) đầu)."""
    assert seed._mix("i", seed.SALT_STATE, 20) == f"(((i)::bigint * {seed.SALT_STATE}) % {seed._P}) % 20"
    salts = _salts()
    assert len(salts) >= 6, salts  # STATE, CODE, APPROVAL, APPROVER, REASON, OVERRIDE
    assert len(set(salts.values())) == len(salts), salts
    assert all(0 < s < seed._P for s in salts.values()), salts  # salt ≡ 0 (mod P) → mọi i rơi về 0


# ---- Ràng buộc DB: đọc từ metadata `models.py`, kiểm tĩnh từng câu INSERT ------------------------------------
#
# Lượt (c) lần 2 dừng ở câu thứ 12 vì `p_method = 'platt'` ngoài CHECK `('self_report', 'sampling_k5')`. Kiểm tĩnh ở đây
# để mọi câu cùng bị soát một lần, không chờ Postgres báo từng lỗi. Phạm vi: CHECK dạng `cột IN (…)`; cột NOT NULL
# không có giá trị mặc định phải có mặt trong danh sách cột; cột phải tồn tại. CHECK khác (khoảng xác suất,
# `rejected_needs_note`), FK và UNIQUE: lập luận trong bảng ràng buộc của PR + chạy thật trên Postgres.

_IN_CHECK = re.compile(r"^\s*(\w+)\s+IN\s*\((.*)\)\s*$", re.DOTALL)
_INSERT = re.compile(r"INSERT INTO (\w+)\s*\(([^)]*)\)\s*(SELECT|VALUES)\b(.*)", re.DOTALL | re.IGNORECASE)
_LITERAL = re.compile(r"'([^']*)'")
_WHEN_THEN = re.compile(r"\bWHEN\b.*?\bTHEN\b", re.DOTALL | re.IGNORECASE)


def check_sets(table: str) -> dict[str, set[str]]:
    """{cột: tập giá trị CHECK cho phép} của bảng, đọc từ `Base.metadata` (models.py)."""
    from app.db.models import Base
    from sqlalchemy import CheckConstraint

    out: dict[str, set[str]] = {}
    for c in Base.metadata.tables[table].constraints:
        if isinstance(c, CheckConstraint) and (m := _IN_CHECK.match(str(c.sqltext))):
            out[m.group(1)] = set(_LITERAL.findall(m.group(2)))
    return out


def required_columns(table: str) -> set[str]:
    """Cột NOT NULL không có server_default và không phải khoá số tự tăng — INSERT phải ghi."""
    from app.db.models import Base

    return {
        c.name for c in Base.metadata.tables[table].columns
        if not c.nullable and c.server_default is None
        and not (c.primary_key and c.type.python_type is int)
    }  # fmt: skip


def _split_top(s: str) -> list[str]:
    """Tách theo dấu phẩy ở độ sâu 0 (ngoặc tròn/vuông), bỏ qua phần trong nháy đơn."""
    items, depth, start, quoted = [], 0, 0, False
    for i, ch in enumerate(s):
        if ch == "'":
            quoted = not quoted
        elif quoted:
            continue
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(s[start:i])
            start = i + 1
    items.append(s[start:])
    return [x.strip() for x in items]


def _top_level_from(s: str) -> int:
    """Vị trí từ khoá FROM ở độ sâu 0 (kết thúc danh sách SELECT)."""
    depth, quoted = 0, False
    for i, ch in enumerate(s):
        if ch == "'":
            quoted = not quoted
        elif quoted:
            continue
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and re.match(r"\bFROM\b", s[i:], re.IGNORECASE) and (i == 0 or not s[i - 1].isalnum()):
            return i
    return len(s)


def value_literals(expr: str) -> list[str]:
    """Chuỗi hằng mà biểu thức có thể GHI vào cột: bỏ phần điều kiện `WHEN … THEN` của CASE (vd `fs = 'S_BLOCKED'`
    là điều kiện, không phải giá trị) và hằng có ép kiểu (`'{}'::jsonb`)."""
    e = _WHEN_THEN.sub(" ", expr)
    e = re.sub(r"'[^']*'::\w+", " ", e)
    return _LITERAL.findall(e)


def insert_rows(sql: str) -> tuple[str, list[str], list[list[str]]] | None:
    """(bảng, cột, [biểu thức mỗi cột cho từng dòng]) của một câu INSERT; None nếu không phải INSERT."""
    m = _INSERT.search(sql)
    if not m:
        return None
    table, cols, kind, body = m.group(1), _split_top(m.group(2)), m.group(3).upper(), m.group(4)
    if kind == "SELECT":
        return table, cols, [_split_top(body[: _top_level_from(body)])]
    body = re.split(r"\bON CONFLICT\b", body, flags=re.IGNORECASE)[0]
    return table, cols, [_split_top(g.strip()[1:-1]) for g in _split_top(body) if g.strip()]


def violations(sql: str) -> list[str]:
    """Mọi vi phạm tĩnh của một câu (rỗng = thoả)."""
    parsed = insert_rows(sql)
    if parsed is None:
        return []
    table, cols, rows = parsed
    from app.db.models import Base

    known = set(Base.metadata.tables[table].columns.keys())
    out = [f"{table}.{c}: cột không tồn tại" for c in cols if c not in known]
    out += [f"{table}.{c}: NOT NULL nhưng không ghi" for c in sorted(required_columns(table) - set(cols))]
    allowed = check_sets(table)
    lengths = {c.name: n for c in Base.metadata.tables[table].columns if (n := getattr(c.type, "length", None))}
    for exprs in rows:
        assert len(exprs) == len(cols), f"{table}: {len(cols)} cột nhưng {len(exprs)} biểu thức"
        for col, expr in zip(cols, exprs, strict=True):
            literals = value_literals(expr)
            if col in allowed:
                out += [f"{table}.{col}: {v!r} ngoài CHECK {sorted(allowed[col])}"
                        for v in literals if v not in allowed[col]]  # fmt: skip
            # Độ dài: chỉ hằng chuỗi; giá trị GHÉP (`'perf-leaf-' || lpad(…)`) lập luận ở bảng ràng buộc của PR.
            if col in lengths:
                out += [f"{table}.{col}: {v!r} dài {len(v)} > {lengths[col]}" for v in literals if len(v) > lengths[col]]
    return out


def test_point4_combination_consistent() -> None:
    """Điểm log 4: `rule` → có `matched_rule_id`, KHÔNG xác suất/`p_method`; `llm` → ngược lại. Bốn cột phụ thuộc
    phải rẽ nhánh theo ĐÚNG điều kiện của `decided_by` (điều kiện khác → có dòng `rule` mang xác suất, hoặc `llm` mang
    luật khớp)."""
    parsed = insert_rows(seed._AUDIT_POINT4)
    assert parsed is not None
    _, cols, (exprs,) = parsed
    e = {c: " ".join(x.split()) for c, x in zip(cols, exprs, strict=True)}
    m = re.fullmatch(r"CASE WHEN (.+?) THEN 'rule' ELSE 'llm' END", e["decided_by"])
    assert m, e["decided_by"]
    cond = re.escape(m.group(1))
    assert re.fullmatch(rf"CASE WHEN {cond} THEN (?!NULL\b).+ ELSE NULL END", e["matched_rule_id"]), e["matched_rule_id"]
    for col in ("calibrated_prob", "raw_prob", "p_method"):
        assert re.fullmatch(rf"CASE WHEN {cond} THEN NULL ELSE (?!NULL\b).+ END", e[col]), (col, e[col])


@pytest.mark.parametrize(("name", "sql"), _STEPS, ids=[name for name, _ in _STEPS])
def test_seed_sql_satisfies_check_and_not_null(name: str, sql: str) -> None:
    """Mỗi câu: cột có CHECK `IN (…)` chỉ nhận giá trị trong tập (đọc từ models); đủ cột NOT NULL; cột tồn tại."""
    assert violations(sql) == [], name


def test_constraint_checker_is_not_vacuous() -> None:
    """Canh chính bộ kiểm: đúng lỗi của lượt (c) lần 2 PHẢI bị bắt; thiếu cột NOT NULL PHẢI bị bắt; điều kiện
    `WHEN … THEN` không bị nhầm là giá trị; và bộ kiểm thật sự soát được cột `audit_logs.p_method`."""
    platt = "INSERT INTO audit_logs (ticket_id, step, event, p_method) SELECT x, 'B13/B14', 'decided', 'platt' FROM y"
    assert violations(platt) == ["audit_logs.p_method: 'platt' ngoài CHECK ['sampling_k5', 'self_report']"]
    missing = "INSERT INTO audit_logs (ticket_id, step) SELECT x, 'B2' FROM y"
    assert violations(missing) == ["audit_logs.event: NOT NULL nhưng không ghi"]
    cond = ("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, exit_code) "
            "SELECT x, r, 'employee', q, CASE WHEN fs = 'S_BLOCKED' THEN 'E0' ELSE NULL END FROM d")  # fmt: skip
    assert violations(cond) == []  # 'S_BLOCKED' là điều kiện, không phải giá trị exit_code
    too_long = "INSERT INTO audit_logs (ticket_id, step, event, decided_by) SELECT x, 'B13/B14', 'decided', 'quyet_dinh' FROM y"
    assert "audit_logs.decided_by: 'quyet_dinh' dài 10 > 8" in violations(too_long)
    assert "p_method" in check_sets("audit_logs")
    checked = {(t, c) for _, sql in _STEPS if (p := insert_rows(sql)) for t, cols, _r in [p] for c in cols
               if c in check_sets(t)}  # fmt: skip
    assert ("audit_logs", "p_method") in checked and len(checked) >= 15, sorted(checked)
