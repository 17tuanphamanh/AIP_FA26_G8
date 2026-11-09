"""M9 A1 — phần thuần của `queries/business.py` (trọng số N3, hợp đồng mục 3, cửa sổ) + migration 0008 (tĩnh)."""

import ast
import dataclasses
import importlib.util
import inspect
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.monitor import views
from app.monitor.metrics import METRIC_SOURCES, N3_SENSITIVITY, N3_WEIGHTS
from app.monitor.queries import business
from app.monitor.queries.business import WeightedRate, escalation_rate_weighted, weigh

REPO = Path(__file__).resolve().parents[3]
MIGRATION = REPO / "backend" / "app" / "db" / "alembic" / "versions" / "0008_monitor_views.py"
FRM = datetime(2030, 1, 1, tzinfo=UTC)
TO = datetime(2030, 1, 2, tzinfo=UTC)
HAND = {"routine": (4, 1), "approval": (2, 1), "sensitive": (2, 2)}  # rate 0,25 / 0,5 / 1,0


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m9_0008_monitor_views", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_weigh_three_groups_hand_computed() -> None:
    assert weigh(HAND, N3_WEIGHTS) == pytest.approx(0.7 * 0.25 + 0.2 * 0.5 + 0.1 * 1.0)  # 0,375
    assert weigh(HAND, N3_SENSITIVITY["60/30/10"]) == pytest.approx(0.40)
    assert weigh(HAND, N3_SENSITIVITY["80/15/5"]) == pytest.approx(0.325)


def test_weigh_only_routine_renormalized() -> None:
    # (a) Q-M9-A1-3: chỉ có nhóm routine → weighted = rate routine, không bị kéo xuống 0,7 × 0,25
    only_routine = {"routine": (4, 1), "approval": (0, 0), "sensitive": (0, 0)}
    for weights in (N3_WEIGHTS, *N3_SENSITIVITY.values()):
        assert weigh(only_routine, weights) == pytest.approx(0.25)


def test_weigh_two_groups_renormalized() -> None:
    counts = {"routine": (2, 0), "sensitive": (1, 1)}  # thiếu khóa approval = 0 lá
    assert weigh(counts, N3_WEIGHTS) == pytest.approx((0.7 * 0 + 0.1 * 1.0) / 0.8)


def test_weigh_no_leaves_none() -> None:
    assert weigh({}, N3_WEIGHTS) is None
    assert weigh({"routine": (0, 0), "approval": (0, 0), "sensitive": (0, 0)}, N3_WEIGHTS) is None


def test_contract_signature() -> None:
    assert list(inspect.signature(escalation_rate_weighted).parameters) == ["conn", "frm", "to"]
    assert [f.name for f in dataclasses.fields(WeightedRate)] == ["raw", "weighted", "by_group", "sensitivity"]
    assert WeightedRate.__dataclass_params__.frozen  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (datetime(2030, 1, 1), TO),  # noqa: DTZ001 — cố ý naive
        (FRM, datetime(2030, 1, 2)),  # noqa: DTZ001
        (TO, FRM),
        (FRM, FRM),
    ],
)
@pytest.mark.asyncio
async def test_naive_or_inverted_window_rejected(frm: datetime, to: datetime) -> None:
    conn: Any = None  # kiểm cửa sổ trước khi chạm DB
    with pytest.raises(ValueError):
        await business.business_metrics(conn, frm, to)


def test_own_keys_subset_of_business() -> None:
    assert business.OWN_KEYS == ("approval_expired_count", "decided_by_distribution", "top_matched_rules")
    assert set(business.OWN_KEYS) <= set(business.BUSINESS_METRICS)
    assert set(business.QUERIES) == set(business.BUSINESS_METRICS)


def test_business_queries_none_iff_pending() -> None:
    """Khóa chưa có truy vấn (None) ⇔ METRIC_SOURCES ghi pending; `override_count` đã nối (4d)."""
    assert len(business.QUERIES) == 10  # quét rỗng thì đỏ, không xanh giả
    for key, query in business.QUERIES.items():
        assert (query is None) == (METRIC_SOURCES[key].status == "pending"), key
    assert business.QUERIES["override_count"] is business.override_count


BUSINESS_SRC = REPO / "backend" / "app" / "monitor" / "queries" / "business.py"
RATIO_FUNCS = ("automation_rate", "escalation_rate_raw", "deflection_rate", "escalation_rate_weighted")


def _docstrings(tree: ast.Module) -> set[int]:
    """id() của hằng chuỗi là docstring (câu đầu thân module/hàm/lớp) — văn xuôi, không phải SQL."""
    owners = [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef))]
    return {
        id(o.body[0].value)
        for o in owners
        if o.body and isinstance(o.body[0], ast.Expr) and isinstance(o.body[0].value, ast.Constant)
    }


MONITOR_DIR = REPO / "backend" / "app" / "monitor"
QUERIES_DIR = MONITOR_DIR / "queries"
# File bắt buộc phải được nhận là "có SQL" — quét glob mà sót file (hoặc nhận nhầm là không có SQL) thì đỏ, không xanh giả.
D30_REQUIRED = {"ai.py", "alerts.py", "business.py", "rules_data.py"}
_SQL_WORD = re.compile(r"\b(from|join|where)\b", re.IGNORECASE)
_SELECT = re.compile(r"\bselect\b", re.IGNORECASE)
_FROM_JOIN = re.compile(r"\b(?:from|join)\b", re.IGNORECASE)
# Từ khoá kết thúc danh sách bảng sau FROM/JOIN (ở độ sâu ngoặc 0). `inner/left/right/full/cross` mở JOIN kế tiếp.
_STOP = re.compile(
    r"\b(?:where|join|on|using|group|order|limit|offset|having|window|union|except|intersect|returning"
    r"|inner|left|right|full|cross|natural|for|fetch)\b",
    re.IGNORECASE,
)
_SKIP_PREFIX = re.compile(r"^(?:lateral|only)\b", re.IGNORECASE)
_IDENT = re.compile(r'^[A-Za-z_"][\w".$]*')
_WORD_CHAR = re.compile(r"\w")
_EXPR = "__expr__"  # chỗ trống cho phần f-string không giải được (không bao giờ khớp tên bảng)
_MAX_RENDER = 64  # trần số tổ hợp khi một tên có nhiều giá trị — tránh nổ tổ hợp


def _render(node: ast.expr, consts: Mapping[str, set[str]]) -> set[str]:
    """Mọi chuỗi mà một hằng/f-string có thể mang. `f"… {T} …"` với `T = "tickets"` → `"… tickets …"`;
    phần không giải được (`{x}`, `{obj.attr}`, lời gọi) → `__expr__`. Nhờ vậy `FROM {T}` bị bắt như `FROM tickets`."""
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if not isinstance(node, ast.JoinedStr):
        return set()
    out = {""}
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            pieces = {part.value}
        elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            pieces = consts.get(part.value.id, {_EXPR})
        else:
            pieces = {_EXPR}
        out = {a + b for a in out for b in pieces}
        if len(out) > _MAX_RENDER:
            return {_EXPR}
    return out


def _assigned_strings(tree: ast.Module, consts: dict[str, set[str]]) -> None:
    """Gom `NAME = "…"` / `NAME = f"…"` ở MỌI phạm vi (module, hàm, lớp) vào `consts` — hai vòng để f-string
    dùng được tên khai trước đó."""
    for pure in (True, False):
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            value = node.value
            assert value is not None
            if pure != isinstance(value, ast.Constant):
                continue
            for t in targets:
                if isinstance(t, ast.Name):
                    consts.setdefault(t.id, set()).update(_render(value, consts))


def _module_strings(sources: Mapping[str, str]) -> dict[str, dict[str, set[str]]]:
    """Hằng chuỗi của từng module (để giải tên lấy qua `from app.monitor.x import NAME`)."""
    out: dict[str, dict[str, set[str]]] = {}
    for name, src in sources.items():
        consts: dict[str, set[str]] = {}
        _assigned_strings(ast.parse(src), consts)
        out[name] = consts
    return out


def _cut(rest: str) -> str:
    """Phần danh sách bảng ngay sau FROM/JOIN: dừng ở từ khoá SQL hoặc dấu `)` đóng ra ngoài, tại độ sâu 0."""
    depth = 0
    for i, ch in enumerate(rest):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            if depth == 0:
                return rest[:i]
            depth -= 1
        elif depth == 0 and (i == 0 or not _WORD_CHAR.match(rest[i - 1])) and _STOP.match(rest, i):
            return rest[:i]
    return rest


def _split_commas(segment: str) -> list[str]:
    """Tách join bằng dấu phẩy — CHỈ dấu phẩy ở độ sâu ngoặc 0 (`unnest(a, b)`, `b(d, e)` không bị tách)."""
    items, depth, start = [], 0, 0
    for i, ch in enumerate(segment):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(segment[start:i])
            start = i + 1
    items.append(segment[start:])
    return items


def _table_name(item: str) -> str | None:
    """Tên bảng của một mục trong danh sách FROM/JOIN, đã bỏ schema và dấu ngoặc kép. Subquery, lời gọi hàm
    (`unnest(...)`) → None."""
    text = _SKIP_PREFIX.sub("", item.strip()).strip()
    m = _IDENT.match(text)
    if not m:
        return None  # `( SELECT … ) p`, `{…}` chưa giải…
    name, after = m.group(0), text[m.end() :].lstrip()
    if after.startswith("("):
        return None  # lời gọi hàm, không phải bảng
    return name.replace('"', "").split(".")[-1].lower()


def _tables(sql: str) -> list[str]:
    return [
        name
        for m in _FROM_JOIN.finditer(sql)
        for item in _split_commas(_cut(sql[m.end() :]))
        if (name := _table_name(item)) is not None
    ]


def _d30_scan(source: str, modules: Mapping[str, str] | None = None) -> tuple[bool, list[str]]:
    """(file có SQL không, danh sách vi phạm D-30). Quét mọi hằng chuỗi và f-string đã ghép của AST (chú thích `#`
    không có trong AST), bỏ docstring; không phân biệt hoa thường.

    Siết ở A4 (review PR #30) — bắt cả: `FROM public.tickets`, `FROM "tickets"`, join bằng dấu phẩy
    (`FROM v_leaf l, tickets t`) và `FROM {T}` với `T = "tickets"` (gán trong file hoặc lấy qua
    `from app.monitor.… import T`). Vi phạm: `tickets` (đọc thẳng bảng thay vì qua `v_leaf`),
    `no_select` (có SQL mà không có SELECT nào)."""
    tree = ast.parse(source)
    # Hằng con của f-string không quét riêng: bản đã ghép của chính f-string đó mới là chuỗi SQL thật.
    skip = _docstrings(tree) | {
        id(c) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for c in ast.walk(n) if c is not n
    }
    consts: dict[str, set[str]] = {}
    if modules:
        by_module = _module_strings(modules)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in by_module:
                for alias in node.names:
                    if (values := by_module[node.module].get(alias.name)) is not None:
                        consts.setdefault(alias.asname or alias.name, set()).update(values)
    _assigned_strings(tree, consts)
    sql = [
        s
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant | ast.JoinedStr) and id(n) not in skip
        for s in _render(n, consts)
    ]
    has_sql = any(_SQL_WORD.search(s) for s in sql)
    violations = [f"tickets: {s.strip()[:80]}" for s in sql if "tickets" in _tables(s)]
    if has_sql and not any(_SELECT.search(s) for s in sql):
        violations.append("no_select")
    return has_sql, violations


def _monitor_sources() -> dict[str, str]:
    """`app.monitor.*` → mã nguồn, để giải tên hằng lấy qua import (vd `V_LEAF` của `views.py`)."""
    return {
        "app." + ".".join(p.relative_to(MONITOR_DIR.parent).with_suffix("").parts): p.read_text(encoding="utf-8")
        for p in sorted(MONITOR_DIR.rglob("*.py"))
    }


def _scan_dir(root: Path, modules: Mapping[str, str] | None = None) -> dict[str, tuple[bool, list[str]]]:
    """Quét ĐỆ QUY (`rglob`) — file trong thư mục con của `queries/` cũng bị soát."""
    return {
        str(p.relative_to(root)): _d30_scan(p.read_text(encoding="utf-8"), modules)
        for p in sorted(root.rglob("*.py"))
    }


def test_d30_glob_scans_queries() -> None:
    """D-30 ghim tĩnh cho MỌI file `monitor/queries/**.py` (P13, duyệt plan A3; `rglob` từ A4): SQL không đọc thẳng
    `tickets`; file có SQL phải có ≥ 1 SELECT."""
    scanned = _scan_dir(QUERIES_DIR, _monitor_sources())
    assert scanned, "không quét được file nào — bộ quét sai đường dẫn"
    with_sql = {name for name, (has_sql, _) in scanned.items() if has_sql}
    assert with_sql >= D30_REQUIRED
    assert {name: v for name, (_, v) in scanned.items() if v} == {}


def test_d30_scanner_catches_violations() -> None:
    """Canh chính bộ quét: đọc thẳng `tickets` và "có SQL mà không SELECT" phải bị bắt; docstring không tính là SQL."""
    assert _d30_scan('Q = "SELECT t.ticket_id FROM v_leaf t"') == (True, [])
    # f-string: thông điệp là chuỗi ĐÃ GHÉP, phần không giải được thành `__expr__` (A4)
    assert _d30_scan('Q = f"SELECT 1 FROM tickets t WHERE {x}"') == (
        True, ["tickets: SELECT 1 FROM tickets t WHERE __expr__"]
    )  # fmt: skip
    assert _d30_scan('Q = "UPDATE alerts SET status = 1 WHERE alert_id = 2"') == (True, ["no_select"])
    assert _d30_scan('"""Đọc FROM tickets."""\nX = 1') == (False, [])


# ---- A4 (review PR #30): 5 dạng bộ quét cũ còn lọt ----------------------------------------------


def test_d30_catches_schema_qualified() -> None:
    """`FROM public.tickets` — bộ quét cũ (`\\bfrom\\s+tickets\\b`) không bắt vì có tiền tố schema."""
    assert _d30_scan('Q = "SELECT 1 FROM public.tickets t"')[1] != []
    assert _d30_scan('Q = "SELECT 1 FROM public.tickets t"')[1][0].startswith("tickets: ")


def test_d30_catches_quoted() -> None:
    """Tên trong ngoặc kép, có và không có schema."""
    assert _d30_scan('Q = \'SELECT 1 FROM "tickets" t\'')[1] != []
    assert _d30_scan('Q = \'SELECT 1 FROM public."tickets"\'')[1] != []
    assert _d30_scan('Q = \'SELECT 1 FROM "public"."tickets"\'')[1] != []


def test_d30_catches_comma_join() -> None:
    """Join bằng dấu phẩy: mục đầu là view hợp lệ nên bộ quét cũ cho qua."""
    assert _d30_scan('Q = "SELECT 1 FROM v_leaf l, tickets t WHERE l.ticket_id = t.ticket_id"')[1] != []
    assert _d30_scan('Q = "SELECT 1 FROM v_leaf l, public.tickets t"')[1] != []


def test_d30_catches_fstring_name() -> None:
    """`FROM {T}` với `T = "tickets"` — bộ quét cũ xét từng hằng rời nên chỉ thấy `"SELECT 1 FROM "`.
    Giải cả tên gán trong file, tên gán trong HÀM, và tên lấy qua `from app.monitor.… import T`."""
    assert _d30_scan('T = "tickets"\nQ = f"SELECT 1 FROM {T}"')[1] != []
    assert _d30_scan('def q():\n    T = "tickets"\n    return f"SELECT 1 FROM {T} t"')[1] != []
    src = "from app.monitor.views import T\nQ = f'SELECT 1 FROM {T}'"
    assert _d30_scan(src, {"app.monitor.views": 'T = "tickets"'})[1] != []
    assert _d30_scan(src, {"app.monitor.views": 'T = "v_leaf"'})[1] == []  # view thì không vi phạm
    # tên có NHIỀU giá trị: chỉ một giá trị xấu cũng đủ đỏ
    assert _d30_scan('T = "v_leaf"\nif x:\n    T = "tickets"\nQ = f"SELECT 1 FROM {T}"')[1] != []


def test_d30_catches_subdir(tmp_path: Path) -> None:
    """File trong thư mục con của `queries/` — bộ quét cũ dùng `glob("*.py")` nên bỏ qua."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.py").write_text('Q = "SELECT 1 FROM tickets t"', encoding="utf-8")
    scanned = _scan_dir(tmp_path)
    assert [name for name, (_, v) in scanned.items() if v] == [str(Path("sub") / "x.py")]


# Dạng SQL CÓ THẬT trong `queries/` (đã grep, kèm nơi dùng) — đỏ ở đây thì `test_d30_glob_scans_queries` cũng đỏ oan.
D30_REAL_SHAPES = [
    pytest.param(
        'Q = "SELECT 1 FROM unnest(CAST(:a AS timestamptz[]), CAST(:b AS timestamptz[])) AS b(d, e)"',
        id="ai.py:103 unnest + AS b(d, e)",
    ),
    pytest.param('Q = "SELECT x.n FROM (SELECT count(*) AS n FROM v_leaf t) x"', id="ai.py:104 subquery ) x"),
    pytest.param(
        'Q = "SELECT g.sev FROM (SELECT t.exit_code FROM v_leaf t) g"', id="business.py:144-147 subquery ) g"
    ),
    pytest.param(
        'Q = "SELECT p.status FROM (SELECT q.ticket_id, q.status, '
        "lead(COALESCE(q.decided_at, q.created_at)) OVER (PARTITION BY q.ticket_id ORDER BY q.created_at) "
        'AS next_start FROM approvals q) p"',
        id="rules_data.py:155-162 subquery nhieu cot + window",
    ),
    pytest.param(
        'Q = "SELECT 1 FROM approvals q LEFT JOIN LATERAL (SELECT 1 FROM audit_logs a) b ON true"',
        id="rules_data.py:164 LEFT JOIN LATERAL",
    ),
]
# Ca TỔNG HỢP — KHÔNG có trong `queries/` hôm nay (đã grep: không `EXTRACT`, `USING`, `ONLY`, `tickets_total`,
# và alias thật là `b(d, e)` chứ không phải `b(d, tickets)`). Giữ để canh nguyên tắc bóc tên bảng: SQL hợp lệ thêm
# sau này không bị đỏ oan.
D30_SYNTHETIC_SHAPES = [
    # cột trong alias ĐƯỢC PHÉP tên `tickets` — tách dấu phẩy không theo độ sâu ngoặc sẽ đỏ oan ở đây
    pytest.param('Q = "SELECT 1 FROM unnest(:a) AS b(d, tickets)"', id="alias co cot ten tickets"),
    pytest.param('Q = "SELECT tickets_total FROM v_leaf t"', id="cot co tien to tickets"),
    pytest.param('Q = "SELECT EXTRACT(epoch FROM t.created_at) FROM v_leaf t"', id="EXTRACT(... FROM ...)"),
    pytest.param('Q = "SELECT 1 FROM v_leaf t JOIN escalations e USING (ticket_id)"', id="JOIN ... USING"),
    pytest.param('Q = "SELECT 1 FROM ONLY v_leaf t"', id="FROM ONLY"),
]


@pytest.mark.parametrize("src", D30_REAL_SHAPES)
def test_d30_no_false_positive_real_shapes(src: str) -> None:
    """Dạng SQL thật trong `queries/`: dấu phẩy trong ngoặc, subquery, LATERAL — không được tính là vi phạm."""
    assert _d30_scan(src)[1] == []


@pytest.mark.parametrize("src", D30_SYNTHETIC_SHAPES)
def test_d30_no_false_positive_synthetic(src: str) -> None:
    """Ca tổng hợp (chưa có trong repo): SQL hợp lệ vẫn phải xanh."""
    assert _d30_scan(src)[1] == []


def test_d30_tables_helper() -> None:
    """Bóc tên bảng: bỏ schema và ngoặc kép, bỏ qua subquery/lời gọi hàm, tách dấu phẩy ở độ sâu 0."""
    assert _tables("SELECT 1 FROM public.tickets t JOIN v_leaf l ON true") == ["tickets", "v_leaf"]
    assert _tables('SELECT 1 FROM "tickets", v_leaf l') == ["tickets", "v_leaf"]
    assert _tables("SELECT 1 FROM (SELECT 1 FROM alerts) x") == ["alerts"]
    assert _tables("SELECT 1 FROM unnest(a, b) AS c(d, e)") == []


def test_ratio_functions_read_v_leaf() -> None:
    tree = ast.parse(BUSINESS_SRC.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name in RATIO_FUNCS}
    assert set(funcs) == set(RATIO_FUNCS)
    for name, fn in funcs.items():
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "V_LEAF" in names, name


def test_alembic_single_head_is_0009() -> None:
    """A4: chuỗi M9 không rẽ nhánh — `0009` (chỉ mục M9) nối thẳng sau `0008` (view M9). Gói 2b (U20, PLAN-2B1 G8 #6): head duy
    nhất nay là `0010` (chống spam), nối thẳng sau `0009`. GIỮ TÊN: `mutate_a4.py` mã I5 gọi test này theo tên.
    F12: head nay là 0011 (view child_notices), nối sau 0010. Notify-email: head nay là 0012 (email_outbox), nối sau 0011. D-67: head
    nay là 0013 (chiến lược M5 lúc vận hành), nối sau 0012. P3 menu ⋯: head nay là 0014 (`ticket_hidden`), nối sau 0013. Lô Q12 (D-57, ĐP
    chốt 09/11): head nay là 0015 (CHECK intent + `it_help`), nối sau 0014."""
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert script.get_heads() == ["0015"]
    assert script.get_revision("0015").down_revision == "0014"  # type: ignore[union-attr]
    assert script.get_revision("0014").down_revision == "0013"  # type: ignore[union-attr]
    assert script.get_revision("0013").down_revision == "0012"  # type: ignore[union-attr]
    assert script.get_revision("0012").down_revision == "0011"  # type: ignore[union-attr]
    assert script.get_revision("0011").down_revision == "0010"  # type: ignore[union-attr]
    assert script.get_revision("0010").down_revision == "0009"  # type: ignore[union-attr]
    assert script.get_revision("0009").down_revision == "0008"  # type: ignore[union-attr]
    assert script.get_revision("0008").down_revision == "0007"  # type: ignore[union-attr]


def test_migration_views_sql_static() -> None:
    m = load_migration()
    sql = dict(m.VIEWS)
    assert list(sql) == ["v_leaf", "v_decisions", "v_l2_queue"]
    for name, query in sql.items():
        assert "*" not in query, name  # cột tường minh
    assert "is_parent = false" in sql["v_leaf"]
    assert "a.step = 'B13/B14'" in sql["v_decisions"]
    assert "ix_tickets_leaf" not in MIGRATION.read_text(encoding="utf-8").split('"""')[2]  # không tạo lại chỉ mục
    assert m.DECISION_COLUMNS[0] == "log_id"
    assert "is_parent" not in m.LEAF_COLUMNS


# ---- F12 (#45): migration 0011 (tĩnh) + nhóm N3 của lá một nguồn ----

MIGRATION_0011 = REPO / "backend" / "app" / "db" / "alembic" / "versions" / "0011_monitor_child_notices.py"
NOTICE_COLUMNS = ("notice_id", "parent_ticket_id", "child_ticket_id", "created_at", "delivered_round", "delivered_at")


def load_migration_0011() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m9_0011_monitor_child_notices", MIGRATION_0011)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0011_static() -> None:
    """GRANT theo cột, KHÔNG cột nội dung (`body`) hay cột thừa; view qua `v_leaf` (D-30), cột tường minh; SQL tĩnh (không
    import `app.*`, quy ước 0008 :14); tên view trùng `views.V_CHILD_NOTICES`; TẠM nối sau 0009 (TODO khi gộp 0010 của 2b)."""
    m = load_migration_0011()
    assert (m.revision, m.down_revision) == ("0011", "0010")
    assert m.NOTICE_COLUMNS == NOTICE_COLUMNS
    assert not {"body", "effect_key", "kind", "needs", "source_step"} & set(m.NOTICE_COLUMNS)
    assert m.VIEW_NAME == views.V_CHILD_NOTICES == "v_child_notices"
    assert "*" not in m.VIEW_SQL
    assert "JOIN v_leaf c ON c.ticket_id = n.child_ticket_id" in m.VIEW_SQL
    code = MIGRATION_0011.read_text(encoding="utf-8").split('"""', 2)[2]
    assert "import app" not in code and "from app" not in code
    assert "TODO(F12)" in code
    assert "security_invoker = true" in code


def _monitor_trees() -> dict[str, ast.Module]:
    return {str(p.relative_to(MONITOR_DIR)): ast.parse(p.read_text(encoding="utf-8")) for p in sorted(MONITOR_DIR.rglob("*.py"))}


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def test_leaf_n3_single_source() -> None:
    """F12: nhóm N3 của LÁ chỉ gán ở MỘT chỗ — `_LEAF_N3_SEV_SQL` định nghĩa ở business.py, chỉ `escalation_rate_weighted`
    dùng (không tự viết CASE riêng); `E5_SENSITIVE_REASONS` chỉ business.py lấy dùng; `_point4_per_leaf` (chọn dòng đại
    diện cho decided_by/top_rules) KHÔNG theo quy tắc E5."""
    trees = _monitor_trees()
    defs = [
        name for name, tree in trees.items() for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_LEAF_N3_SEV_SQL" for t in n.targets)
    ]  # fmt: skip
    assert defs == [str(Path("queries") / "business.py")]
    users = {name for name, tree in trees.items() if "_LEAF_N3_SEV_SQL" in _names(tree)}
    assert users == {str(Path("queries") / "business.py")}
    e5_users = {
        name for name, tree in trees.items()
        if "E5_SENSITIVE_REASONS" in _names(tree)
        or any(isinstance(n, ast.ImportFrom) and any(a.name == "E5_SENSITIVE_REASONS" for a in n.names) for n in ast.walk(tree))
    }  # fmt: skip
    assert e5_users == {"metrics.py", str(Path("queries") / "business.py")}
    funcs = {n.name: n for n in ast.walk(trees[str(Path("queries") / "business.py")]) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    using = {name for name, fn in funcs.items() if "_LEAF_N3_SEV_SQL" in _names(fn)}
    assert using == {"escalation_rate_weighted"}
    weighted = funcs["escalation_rate_weighted"]
    assert "_SEVERITY_SQL" not in _names(weighted)  # nhánh ELSE nằm trong hằng, không viết lại
    assert not any(isinstance(c, ast.Constant) and isinstance(c.value, str) and "CASE" in c.value for c in ast.walk(weighted))
    assert "_LEAF_N3_SEV_SQL" not in _names(funcs["_point4_per_leaf"])


# ---- D13: số đếm tử/mẫu ----------------------------------------------------------------------------------------------
# Không DB: conn giả nhận diện câu SQL theo mảnh đặc trưng (`_d13_route`), trả dòng tính tay, ghi lại thứ tự câu đã chạy.

D13_RATIO_SQL = {  # nguyên văn SQL của 3 hàm tỉ lệ TRƯỚC D13 — tách mảnh FILTER ra hằng không được đổi một ký tự nào
    "automation_rate": (
        "SELECT count(*), count(*) FILTER (WHERE t.final_state = 'S_RESOLVED' AND NOT EXISTS (SELECT 1 FROM approvals a "
        "WHERE a.ticket_id = t.ticket_id) AND NOT EXISTS (SELECT 1 FROM escalations e WHERE e.ticket_id = t.ticket_id)) "
        "FROM v_leaf t WHERE t.created_at >= :frm AND t.created_at < :to AND t.final_state IS NOT NULL"
    ),
    "escalation_rate_raw": (
        "SELECT count(*), count(*) FILTER (WHERE t.exit_code IS NOT NULL) "
        "FROM v_leaf t WHERE t.created_at >= :frm AND t.created_at < :to AND t.final_state IS NOT NULL"
    ),
    "deflection_rate": (
        "SELECT count(*), count(*) FILTER (WHERE t.resolution_path = 'deflected') "
        "FROM v_leaf t WHERE t.created_at >= :frm AND t.created_at < :to AND t.final_state IS NOT NULL"
    ),
}
D13_FILTERS = {"automation_rate": "_AUTOMATED", "escalation_rate_raw": "_ESCALATED", "deflection_rate": "_DEFLECTED"}


def _d13_route(sql: str) -> str:
    """Tên câu SQL theo mảnh đặc trưng; xét theo thứ tự (câu đếm chung chứa mảnh của cả 3 tỉ lệ nên xét trước)."""
    if "resolution_path = 'deflected'" in sql and "t.exit_code IS NOT NULL" in sql:
        return "ratio_counts"
    for name, piece in (
        ("escalation_rate_weighted", "GROUP BY g.sev"), ("automation_rate", "NOT EXISTS (SELECT 1 FROM approvals"),
        ("deflection_rate", "resolution_path = 'deflected'"), ("escalation_rate_raw", "t.exit_code IS NOT NULL"),
        ("approval_expired_count", "t.exit_code = 'E6'"), ("decided_by_distribution", "GROUP BY x.decided_by"),
        ("top_matched_rules", "GROUP BY x.matched_rule_id"), ("override_count", "a.step = :step"),
        ("e1_split", "t.exit_code = 'E1'"), ("e3_cases", "t.exit_code = 'E3'"),
    ):  # fmt: skip
        if piece in sql:
            return name
    if "ap.approver_id = :approver_id" in sql:
        return "own_sample"
    raise AssertionError(f"câu SQL lạ: {sql[:80]}")


class _D13Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def one(self) -> Any:
        [row] = self.rows
        return row


class D13Conn:
    def __init__(self, rows: Mapping[str, list[Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def execute(self, clause: Any, params: dict[str, Any]) -> _D13Result:
        name = _d13_route(clause.text)
        self.calls.append((name, clause.text, params))
        return _D13Result(list(self.rows[name]))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]


# 3 lá đã kết thúc: A S_RESOLVED auto (không phiếu, không escalation), B E1, C S_RESOLVED có phiếu duyệt.
# automation: chỉ A → (num, den) = (1, 3); raw: chỉ B có exit_code → (1, 3); deflection: không lá nào deflected → (0, 3).
# Dòng tỉ lệ = (den, num); dòng ratio_counts = (den, automation, raw, deflection).
HAND_3: dict[str, list[Any]] = {
    "automation_rate": [(3, 1)], "escalation_rate_raw": [(3, 1)], "deflection_rate": [(3, 0)],
    "ratio_counts": [(3, 1, 1, 0)],
    # nhóm N3 (sev, #lá, #lá có exit_code): routine (1) 4 lá / 1 escalate; approval (2) KHÔNG có lá; sensitive (3) 2 / 2
    "escalation_rate_weighted": [(1, 4, 1), (3, 2, 2)],
    "approval_expired_count": [(0,)], "decided_by_distribution": [], "top_matched_rules": [], "override_count": [(0,)],
    "e1_split": [], "e3_cases": [], "own_sample": [(0,)],
}  # fmt: skip
EMPTY: dict[str, list[Any]] = {
    "automation_rate": [(0, 0)], "escalation_rate_raw": [(0, 0)], "deflection_rate": [(0, 0)],
    "ratio_counts": [(0, 0, 0, 0)], "escalation_rate_weighted": [],
}  # fmt: skip


@pytest.mark.asyncio
async def test_ratio_sql_unchanged() -> None:
    """Hàm tỉ lệ dùng lại hằng mảnh FILTER nhưng câu SQL gửi đi giữ NGUYÊN VĂN như trước D13 (giá trị không đổi)."""
    for name, sql in D13_RATIO_SQL.items():
        conn = D13Conn(HAND_3)
        await getattr(business, name)(conn, FRM, TO)
        assert [(n, s) for n, s, _ in conn.calls] == [(name, sql)], name


@pytest.mark.asyncio
async def test_ratio_counts_shares_filters() -> None:
    """MỘT nguồn điều kiện: mảnh FILTER của từng tỉ lệ có trong câu của hàm tỉ lệ VÀ câu đếm chung; câu đếm đọc `v_leaf`,
    cùng cửa sổ lá và cùng mẫu số (lá đã kết thúc)."""
    conn = D13Conn(HAND_3)
    await business.ratio_counts(conn, FRM, TO)  # type: ignore[arg-type]
    [(name, counts_sql, params)] = conn.calls
    assert name == "ratio_counts" and params == {"frm": FRM, "to": TO}
    for key, const in D13_FILTERS.items():
        piece = getattr(business, const)
        assert f"FILTER (WHERE {piece})" in D13_RATIO_SQL[key], key
        assert f"FILTER (WHERE {piece})" in counts_sql, key
    assert f"FROM {views.V_LEAF} t WHERE {business._LEAF_WINDOW} AND {business._DONE}" in counts_sql
    names = {n.id for n in ast.walk(_d13_func("ratio_counts")) if isinstance(n, ast.Name)}
    assert {"V_LEAF", "_AUTOMATED", "_ESCALATED", "_DEFLECTED"} <= names


def _d13_func(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(BUSINESS_SRC.read_text(encoding="utf-8"))
    [fn] = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    return fn


@pytest.mark.asyncio
async def test_counts_hand_3_done_1_auto() -> None:
    """3 lá đã kết thúc, 1 lá auto → automation (1/3); raw (1/3); deflection (0/3). Tỉ lệ == num/den từng khoá."""
    counts = await business.ratio_counts(D13Conn(HAND_3), FRM, TO)  # type: ignore[arg-type]
    assert counts == {
        "automation_rate": business.RatioCount(num=1, den=3),
        "escalation_rate_raw": business.RatioCount(num=1, den=3),
        "deflection_rate": business.RatioCount(num=0, den=3),
    }
    for key, count in counts.items():
        rate = await getattr(business, key)(D13Conn(HAND_3), FRM, TO)
        assert rate == pytest.approx(count.num / count.den), key  # 1/3, 1/3, 0/3


@pytest.mark.asyncio
async def test_counts_empty_window() -> None:
    """Mẫu 0 → tỉ lệ None (không đổi), số đếm 0/0; weighted: cỡ mẫu 0, 3 nhóm 0/0 kèm trọng số danh nghĩa."""
    counts = await business.ratio_counts(D13Conn(EMPTY), FRM, TO)  # type: ignore[arg-type]
    assert counts == dict.fromkeys(D13_FILTERS, business.RatioCount(num=0, den=0))
    for key in D13_FILTERS:
        assert await getattr(business, key)(D13Conn(EMPTY), FRM, TO) is None, key
    r = await escalation_rate_weighted(D13Conn(EMPTY), FRM, TO)  # type: ignore[arg-type]
    assert (r.raw, r.weighted) == (None, None)
    assert r.count == business.WeightedCount(
        den=0, by_group={g: business.GroupCount(num=0, den=0, weight=N3_WEIGHTS[g]) for g in N3_WEIGHTS}
    )


@pytest.mark.asyncio
async def test_weighted_counts_missing_group() -> None:
    """Nhóm thiếu lá: routine 1/4 (w 0,7), approval 0/0 (w 0,2), sensitive 2/2 (w 0,1). Cỡ mẫu = 4 + 0 + 2 = 6; KHÔNG có tử
    tổng (a/b của weighted chỉ hiện theo nhóm). weighted = (0,7·1/4 + 0,1·2/2) / (0,7 + 0,1) = 0,275 / 0,8 = 0,34375."""
    r = await escalation_rate_weighted(D13Conn(HAND_3), FRM, TO)  # type: ignore[arg-type]
    assert r.count == business.WeightedCount(
        den=6,
        by_group={
            "routine": business.GroupCount(num=1, den=4, weight=0.7),
            "approval": business.GroupCount(num=0, den=0, weight=0.2),
            "sensitive": business.GroupCount(num=2, den=2, weight=0.1),
        },
    )
    assert [f.name for f in dataclasses.fields(business.WeightedCount)] == ["den", "by_group"]
    assert r.weighted == pytest.approx(0.34375)
    assert r.raw == pytest.approx(3 / 6)  # (1 + 0 + 2) / 6 — giá trị cũ, không đổi
    assert r.by_group == {"routine": 0.25, "approval": None, "sensitive": 1.0}


@pytest.mark.asyncio
async def test_weighted_subclass_is_weightedrate() -> None:
    """Luật 1 / drift nhận lớp con: vẫn là `WeightedRate`, 4 trường giữ nguyên giá trị tính tay; `WeightedRate` vẫn 4 trường."""
    r = await escalation_rate_weighted(D13Conn(HAND_3), FRM, TO)  # type: ignore[arg-type]
    assert isinstance(r, WeightedRate) and isinstance(r, business.CountedWeightedRate)
    assert [f.name for f in dataclasses.fields(WeightedRate)] == ["raw", "weighted", "by_group", "sensitivity"]
    # 60/30/10: (0,6·0,25 + 0,1·1) / 0,7 = 0,25/0,7; 80/15/5: (0,8·0,25 + 0,05·1) / 0,85 = 0,25/0,85
    assert r.sensitivity == {"60/30/10": pytest.approx(0.25 / 0.7), "80/15/5": pytest.approx(0.25 / 0.85)}


@pytest.mark.asyncio
async def test_business_metrics_counts_all() -> None:
    """scope all: `values` như cũ (weighted là `WeightedRate` GỐC, không lộ lớp con ra response); `counts` đủ 4 khoá; câu đếm
    chung chạy đúng một lần SAU mọi truy vấn chỉ số (cùng conn = cùng snapshot ở route); không đếm cỡ mẫu own."""
    conn = D13Conn(HAND_3)
    m = await business.business_metrics(conn, FRM, TO)  # type: ignore[arg-type]
    assert tuple(m.values) == business.BUSINESS_METRICS
    assert m.values["automation_rate"] == pytest.approx(1 / 3)
    assert m.values["deflection_rate"] == 0.0
    weighted = m.values["escalation_rate_weighted"]
    assert type(weighted) is WeightedRate
    assert weighted.weighted == pytest.approx(0.34375)
    assert set(m.counts) == set(business.COUNTED_KEYS)
    assert m.counts["automation_rate"] == business.RatioCount(num=1, den=3)
    assert m.counts["escalation_rate_weighted"].den == 6
    assert m.sample is None
    assert conn.names().count("ratio_counts") == 1 and conn.names()[-1] == "ratio_counts"
    assert "own_sample" not in conn.names()


@pytest.mark.asyncio
async def test_business_metrics_own_sample() -> None:
    """scope own: 3 khoá own là SỐ ĐẾM → không có `counts`; chỉ `sample` = số lá own trong cửa sổ (5), cùng điều kiện cửa sổ +
    phiếu của người duyệt như 3 hàm own."""
    rows: dict[str, list[Any]] = {**HAND_3, "approval_expired_count": [(1,)], "decided_by_distribution": [("llm", 1), ("rule", 3)],
            "own_sample": [(5,)]}  # fmt: skip
    conn = D13Conn(rows)
    m = await business.business_metrics(conn, FRM, TO, approver_id="u-l1")  # type: ignore[arg-type]
    assert m.values == {"approval_expired_count": 1, "decided_by_distribution": {"llm": 1, "rule": 3}, "top_matched_rules": []}
    assert m.counts == {}
    assert m.sample == 5
    [(_, sql, params)] = [c for c in conn.calls if c[0] == "own_sample"]
    assert sql == f"SELECT count(*) FROM {views.V_LEAF} t WHERE {business._LEAF_WINDOW} AND {business._OWN}"
    assert params == {"frm": FRM, "to": TO, "approver_id": "u-l1"}
    assert "ratio_counts" not in conn.names()


def test_business_metrics_defaults() -> None:
    """Chỗ khác dựng `BusinessMetrics` 2 tham số (spy của test snapshot _pg) vẫn chạy: `counts` rỗng, `sample` None."""
    m = business.BusinessMetrics(values=dict.fromkeys(business.BUSINESS_METRICS), unavailable=())
    assert (m.counts, m.sample) == ({}, None)
    assert business.COUNTED_KEYS == ("automation_rate", "escalation_rate_raw", "escalation_rate_weighted", "deflection_rate")
    assert set(business.COUNTED_KEYS) <= set(business.BUSINESS_METRICS)
