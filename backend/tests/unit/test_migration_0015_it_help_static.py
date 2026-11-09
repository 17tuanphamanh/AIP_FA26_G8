"""Migration 0015 (lô Q12, ĐP 09/11 — TA chọn thêm intent + migration) — kiểm TĨNH, không cần Docker (test viết trước, DỪNG 1 phần 2).
Bản Postgres thật: `integration/test_migration_0015_it_help.py` (chờ CI / TA chạy).

- Đúng MỘT file `0015_*.py`, `revision="0015"`, `down_revision="0014"`, có `upgrade` + `downgrade`.
- Đổi CHECK `intent` của `tickets` và `audit_logs` sang `TICKET_INTENTS` (= `INTENTS` + `it_help`); `policy_rules` KHÔNG đổi (không có luật
  cho it_help). Downgrade trả về 4 loại.
- `models.py` khớp: `INTENTS` giữ 4 loại hành động (eval/monitor/policy dùng — không đổi nghĩa); `TICKET_INTENTS` mới cho 2 bảng.
`TICKET_INTENTS` đọc qua `getattr` (tên mới) để mypy của `make lint` không vỡ trước khi hiện thực.
"""

import ast
from pathlib import Path

from app.db import models
from sqlalchemy import CheckConstraint, Table

VERSIONS = Path(__file__).resolve().parents[3] / "backend" / "app" / "db" / "alembic" / "versions"
FOUR = "intent IN ('account', 'vpn', 'software', 'access')"
FIVE = "intent IN ('account', 'vpn', 'software', 'access', 'it_help')"


def _migration() -> str:
    found = sorted(VERSIONS.glob("0015_*.py"))
    assert len(found) == 1, f"cần đúng một file 0015_*.py, thấy {[p.name for p in found]}"
    return found[0].read_text(encoding="utf-8")


def _assigns(source: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign | ast.Assign):
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            if isinstance(target, ast.Name) and node.value is not None:
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return out


def _funcs(source: str) -> dict[str, str]:
    return {n.name: ast.unparse(n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


def _intent_check(table: object) -> str:
    t: Table = table  # type: ignore[assignment]
    [c] = [c for c in t.constraints if isinstance(c, CheckConstraint) and str(c.sqltext).startswith("intent IN")]
    return str(c.sqltext)


def test_0015_chains_after_0014_and_has_downgrade() -> None:
    src = _migration()
    names = _assigns(src)
    assert (names.get("revision"), names.get("down_revision")) == ("0015", "0014")
    assert {"upgrade", "downgrade"} <= set(_funcs(src))


def test_0015_changes_only_tickets_and_audit_logs_intent_checks() -> None:
    src = _migration()
    names = _assigns(src)
    # Migration là ảnh chụp cố định (khuôn 0002/0007): danh sách viết tĩnh, không import `app.db.models`
    assert "from app" not in src and "import app" not in src
    assert names.get("TABLES") == ("tickets", "audit_logs")  # → ck_tickets_intent, ck_audit_logs_intent
    assert names.get("OLD_INTENTS") == ("account", "vpn", "software", "access")
    assert names.get("NEW_INTENTS") == ("it_help",)
    body = ast.parse(src).body[1:]  # bỏ docstring; chú thích không nằm trong AST
    literals = [n.value for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any("policy_rules" in v for v in literals)  # policy_rules giữ 4 loại — không chuỗi nào nhắm bảng đó
    up, down = _funcs(src)["upgrade"], _funcs(src)["downgrade"]
    assert "NEW_INTENTS" in up and "OLD_INTENTS" in down  # lên: 5 giá trị; xuống: 4 (đọc lại định nghĩa thật ở PG test)
    assert "RuntimeError" in down  # đã có dòng it_help → dừng (append-only), khuôn 0002


def test_models_ticket_intents() -> None:
    ticket_intents = getattr(models, "TICKET_INTENTS")  # noqa: B009 — tên mới
    assert models.INTENTS == ("account", "vpn", "software", "access")  # không đổi nghĩa
    assert ticket_intents == (*models.INTENTS, "it_help")
    assert _intent_check(models.Ticket.__table__) == FIVE
    assert _intent_check(models.AuditLog.__table__) == FIVE
    assert _intent_check(models.PolicyRule.__table__) == FOUR
    assert models.KB_REQUEST_TYPES == ("account", "vpn", "software", "access", "general")  # KB không có loại it_help
