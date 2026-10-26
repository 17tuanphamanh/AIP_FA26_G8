"""`audit_check` — kiểm 8 điểm log đủ và không lộ bí mật (Phase 4 chặng 4d — phase4 7.1 P5, 7.2; PLAN-4d mục 2.1, 4, TQ-5…8).

Chạy: `make audit-check ARGS="<ticket_id> …"` | `ARGS="--since 2026-10-01T10:00:00+07:00"` (trong container backend — DSN của compose,
máy không đọc `.env`); `python -m app.audit.check …`; vỏ `scripts/audit_check.py`. Thêm `--canary <chuỗi>` (lặp được), `--log PATH|-`.

- Điểm áp dụng theo dòng có mặt trong ticket; trường bắt buộc kiểm ĐÚNG chỗ code ghi (Q-4d-1 = A — bảng PLAN-4d mục 4, không theo chữ
  cột của 7.2: `confidence`, `query`, `success`, `action_plan_hash_matched` nằm ở `detail`; Việc treo 31).
- Bí mật: luật `kind="secret"` của `config/privacy_patterns.json` + canary, trên MỌI cột chuỗi/JSON của `audit_logs` (liệt kê từ kiểu cột
  model) và file log. Trúng mà nhóm `v` là mặt nạ (`[BÍ_MẬT_ĐÃ_ẨN]`) + CHỈ dấu câu/khoảng trắng = đã che → không tính; sau mặt nạ còn
  chữ/số → TÍNH là trúng (Q-4d-8). Không dùng luật `entropy` (hash hex 64).
- CHỈ ĐỌC: role `app_monitor` (`MONITOR_DATABASE_URL`) nếu đặt, không thì `app_rw`; cả hai trong giao dịch READ ONLY. In nhãn role,
  KHÔNG in DSN. Báo "bí mật ở cột X dòng Y (luật Z)" — KHÔNG BAO GIỜ in giá trị. Thoát 0 sạch, 1 có thiếu/bí mật, 2 tham số sai.
"""

import argparse
import asyncio
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import JSON, String, Table, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.models import AGGREGATE_STATUSES, AuditLog, Ticket
from app.guard.patterns import privacy_patterns
from app.settings import get_settings

_AUDIT: Table = AuditLog.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
# MỌI cột chuỗi/JSON của audit_logs, lấy từ kiểu cột model (thêm cột mới → tự phủ). `ticket_id` (khoá do server sinh) không quét:
# trúng ở đó thì `SecretHit.ticket_id` sẽ mang chính giá trị.
SCANNED_COLUMNS: Final = tuple(
    c.name for c in _AUDIT.columns if isinstance(c.type, (String, JSON)) and c.name != "ticket_id"
)
_P1_E1_EXEMPT: Final = frozenset({"intent_out_of_scope", "multi_intent_not_enabled"})  # detail.intent/confidence là None (b03)
_B16_PLAN_CHANGED: Final = "action_plan_changed_since_approval"  # B16 duyệt nhưng kế hoạch đã đổi (Q-4d-3) — vẫn là điểm 6
_ABSENT: Final = object()
# Dòng điểm log 4 (b12_assess `_point4`) — một nguồn cho `audit_check` và `m5_review` (phase6 7.1 P2).
POINT4_KEY: Final = ("B13/B14", "risk_decided")


@dataclass(frozen=True)
class Missing:
    """Điểm `point` của ticket thiếu `fields` (cột: tên trần; khoá detail: `detail.<khoá>`). `log_id` None = thiếu CẢ dòng (điểm 8)."""

    ticket_id: str
    point: int
    log_id: int | None
    fields: tuple[str, ...]


@dataclass(frozen=True)
class SecretHit:
    """Một chỗ trúng luật bí mật — KHÔNG mang giá trị. `column` = `"audit_logs.<cột>"` | `"log"`; `ref` = `log_id` | số dòng log (từ 1);
    `rule` = id luật `secret` | `"canary"`."""

    ticket_id: str | None
    column: str
    ref: int
    rule: str


@dataclass(frozen=True)
class Report:
    tickets: tuple[str, ...]
    missing: tuple[Missing, ...]
    secrets: tuple[SecretHit, ...]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.secrets


def required(ticket_id: str, rows: Sequence[Mapping[str, Any]], *, final_state: str | None) -> list[Missing]:
    """THUẦN: `rows` = dòng `audit_logs` của MỘT ticket (dict cột → giá trị, `detail` là dict; khoá vắng = None). `final_state` =
    `tickets.final_state` (điểm 8 chỉ khi có)."""
    approved = any((r.get("step"), r.get("event")) == ("B16", "approved") for r in rows)
    missing = []
    for row in rows:
        found = _point(row, approved=approved)
        if found is not None and found[1]:
            missing.append(Missing(ticket_id, found[0], row.get("log_id"), tuple(found[1])))
    if final_state is not None:
        missing.extend(_point8(ticket_id, rows))
    return missing


def _get(row: Mapping[str, Any], field: str) -> Any:
    """Cột: giá trị (vắng = None). `detail.a.b`: giá trị lá, khoá vắng = `_ABSENT`."""
    if not field.startswith("detail."):
        return row.get(field)
    node: Any = row.get("detail") or {}
    for part in field.split(".")[1:]:
        if not isinstance(node, Mapping) or part not in node:
            return _ABSENT
        node = node[part]
    return node


def _lacks(row: Mapping[str, Any], set_: Sequence[str], keys: Sequence[str] = ()) -> list[str]:
    """`set_`: phải ≠ null (0/False hợp lệ — không kiểm theo truthiness); `keys`: khoá detail phải CÓ (giá trị gì cũng được)."""
    out = [f for f in set_ if _get(row, f) is None or _get(row, f) is _ABSENT]
    return out + [f for f in keys if _get(row, f) is _ABSENT]


_P4_RULE: Final = ("decided_by", "policy_decision", "risk_level", "reason", "detail.route", "detail.policy_sha256")
_P4_LLM: Final = ("decided_by", "risk_level", "reason", "detail.route", "detail.policy_sha256", "raw_prob", "p_method",
                  "detail.thresholds")  # fmt: skip


def _point4_need(row: Mapping[str, Any]) -> list[str]:
    """Điểm 4 theo `decided_by` (phase6 6C P7, Q-6-8 điều kiện 1, Q-6C-3). `llm`: không đòi `policy_decision`, đòi `raw_prob`,
    `p_method`, `detail.thresholds`. NULL CHỈ hợp lệ khi ghi chú `detail.strategy == "full_auto"` ∧ `detail.route == "AUTO"`;
    `rule` + `policy_decision` NULL CHỈ khi `detail.strategy == "rule_only"` ∧ `detail.route == "HITL"`. Còn lại (kể cả NULL
    không ghi chú) → danh sách luật (thiếu `decided_by`/`policy_decision`)."""
    decided_by, strategy, route = row.get("decided_by"), _get(row, "detail.strategy"), _get(row, "detail.route")
    if decided_by == "llm":
        return list(_P4_LLM)
    if decided_by is None and strategy == "full_auto" and route == "AUTO":
        return ["detail.policy_sha256"]
    if decided_by == "rule" and row.get("policy_decision") is None and strategy == "rule_only" and route == "HITL":
        return [f for f in _P4_RULE if f != "policy_decision"]
    return list(_P4_RULE)


def _point(row: Mapping[str, Any], *, approved: bool) -> tuple[int, list[str]] | None:
    """Điểm 1–7 theo bảng PLAN-4d mục 4 (Q-4d-1 = A: kiểm ĐÚNG chỗ code ghi). Dòng không thuộc bảng → None."""
    step, event = row.get("step"), row.get("event")
    if (step, event) == ("B3", "intent_classified") or step == "B4":  # b03_classify `_point1`
        need = ["detail.layer"] + ([] if event in _P1_E1_EXEMPT else ["detail.intent", "detail.confidence"])
        return 1, _lacks(row, need + (["intent"] if event == "intent_classified" else []), ["detail.dropped_slot_keys"])
    if (step, event) == ("B6", "diagnosed") or step == "B7":  # b06_diagnose `_point2`
        return 2, _lacks(row, ["detail.tool_retry_count"], ["detail.tools_called", "detail.facts"])
    if (step, event) == ("B8", "retrieved"):  # b08_retrieve `point3`
        return 3, _lacks(row, ["detail.query", "detail.top_score", "kb_version"])
    if (step, event) == ("B8", "retrieval_error"):
        alias = _get(row, "detail.error_stage") == "alias"  # lỗi alias: chưa biết bản KB
        return 3, _lacks(row, ["detail.query"] + ([] if alias else ["kb_version"]))
    if (step, event) == ("B9", "no_evidence"):  # b10_route — `grounding`
        return 3, _lacks(row, ["kb_version"], ["detail.grounding.top_score"])
    if (step, event) == POINT4_KEY:  # b12_assess `_point4` + `_RISK_COLUMNS` của goto
        return 4, _lacks(row, _point4_need(row))
    if (step, event) == ("B15", "queued"):
        return 5, _lacks(row, ["approver_id", "deadline", "conflict_detected", "action_plan_hash", "detail.choice_reason"])
    if step == "B16" and event in ("approved", "rejected", "approval_timeout", _B16_PLAN_CHANGED):
        need = ["approval_result"]
        if event != "approval_timeout":
            need += ["response_time_seconds", "detail.decided_as"] + (["note"] if event == "rejected" else [])
        if event == _B16_PLAN_CHANGED:  # Q-4d-3: lần duyệt mà kế hoạch đã đổi — điểm 6 như approved + bằng chứng so hash
            need += ["detail.hash_source", "detail.action_plan_hash_matched"]
        return 6, _lacks(row, need, ["detail.decided_without_view"])
    if (step, event) in (("B18", "executed_ok"), ("B17", "exec_failed"), ("B17", "exec_interrupted")):  # b17 `_point7`
        need = ["detail.write_calls"]
        if approved and _get(row, "detail.stage") != "txlog_before_recheck":  # bước 0 dừng trước khi so hash
            need.append("detail.action_plan_hash_matched")
        return 7, _lacks(row, need, ["detail.success"])
    return None


def _point8(ticket_id: str, rows: Sequence[Mapping[str, Any]]) -> list[Missing]:
    closed = [r for r in rows if (r.get("step"), r.get("event")) == ("B20", "closed")]
    if not closed:
        return [Missing(ticket_id, 8, None, ("B20/closed",))]
    # Phase 5 T20b Q-T20b-13 = A: ticket CHA đóng bình thường (D-30) không `close_reason`/`exit_code` — đạt khi `detail.aggregate_status`
    # ∈ `AGGREGATE_STATUSES` (giá trị lạ / thiếu cả ba → vẫn thiếu), CHỈ khi ticket là CHA. "Là cha" lấy từ chính `rows` (dòng audit của
    # ticket): có dòng B5 `split_into_<n>_children` (B3/B5 tách ý — `b03_classify._split`); lá và con không bao giờ có dòng này.
    parent = any(r.get("step") == "B5" and re.fullmatch(r"split_into_\d+_children", str(r.get("event"))) for r in rows)
    lacks = [
        _lacks(r, ["final_state"]) + ([] if r.get("close_reason") is not None or r.get("exit_code") is not None
                                      or parent and _get(r, "detail.aggregate_status") in AGGREGATE_STATUSES
                                      else ["close_reason|exit_code"])
        for r in closed
    ]  # fmt: skip
    if any(not lack for lack in lacks):
        return []
    return [Missing(ticket_id, 8, closed[-1].get("log_id"), tuple(lacks[-1]))]


class SecretScanner:
    def __init__(self, rules: Sequence[tuple[str, re.Pattern[str]]], *, mask: str, canaries: Sequence[str] = ()) -> None:
        self._rules = tuple(rules)
        self._mask = mask
        self._canaries = tuple(c for c in canaries if c)

    @classmethod
    def from_config(cls, config_dir: Path, canaries: Sequence[str] = ()) -> "SecretScanner":
        """Luật `kind="secret"` (theo thứ tự file) + `secret_mask` của `privacy_patterns.json`."""
        patterns = privacy_patterns(config_dir)
        rules = [(r.id, r.pattern) for r in patterns.rules if r.kind == "secret" and r.pattern is not None]
        return cls(rules, mask=patterns.secret_mask, canaries=canaries)

    def hits(self, text: str) -> list[str]:
        """Id luật trúng (+ `"canary"`), mỗi id một lần, theo thứ tự luật."""
        found = [rule_id for rule_id, pattern in self._rules if any(not self._masked(m) for m in pattern.finditer(text))]
        return found + (["canary"] if any(c in text for c in self._canaries) else [])

    def _masked(self, match: re.Match[str]) -> bool:
        """Q-4d-8 = B: nhóm `v` = mặt nạ + CHỈ dấu câu/khoảng trắng = guard đã che (vd "mật khẩu là [BÍ_MẬT_ĐÃ_ẨN]." — `v` của luật
        `password` nuốt cả dấu câu dính liền). Sau mặt nạ còn chữ/số (vd `[BÍ_MẬT_ĐÃ_ẨN]abc123` — đường lách guard) → TÍNH là trúng."""
        value = match.groupdict().get("v")
        if value is None or not value.startswith(self._mask):
            return False
        return not any(ch.isalnum() for ch in value[len(self._mask) :])


def _strings(value: Any) -> Iterator[str]:
    """Từng LÁ chuỗi (cả khoá dict) — không `json.dumps` (chuỗi có `"`/`\\`/chữ có dấu bị escape thì canary trượt)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _strings(v)


def scan_rows(rows: Iterable[Mapping[str, Any]], scanner: SecretScanner) -> list[SecretHit]:
    """Mọi cột chuỗi/JSON của `AuditLog` (từ kiểu cột model); JSON đi từng lá chuỗi. Dòng cần `log_id`, `ticket_id`."""
    found = []
    for row in rows:
        for column in SCANNED_COLUMNS:
            rules: list[str] = []
            for text in _strings(row.get(column)):
                rules += [r for r in scanner.hits(text) if r not in rules]
            found += [SecretHit(row.get("ticket_id"), f"audit_logs.{column}", int(row["log_id"]), r) for r in rules]
    return found


def scan_log(lines: Iterable[str], scanner: SecretScanner) -> list[SecretHit]:
    return [SecretHit(None, "log", n, r) for n, line in enumerate(lines, 1) for r in scanner.hits(line.rstrip("\n"))]


def readonly_engine(dsn: str) -> AsyncEngine:
    """Engine mà MỌI giao dịch là READ ONLY (INSERT/UPDATE → lỗi Postgres `read_only_sql_transaction`) — Postgres ép theo phiên,
    không phụ thuộc quyền của role (app_rw CÓ quyền INSERT)."""
    return create_async_engine(dsn, connect_args={"options": "-c default_transaction_read_only=on"}, hide_parameters=True)


async def load(
    engine: AsyncEngine, *, tickets: Sequence[str] | None = None, since: datetime | None = None
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str | None]]:
    """(dòng audit theo ticket — thứ tự `log_id`, `final_state` theo ticket). `since`: ticket có dòng audit `created_at >= since`."""
    if (tickets is None) == (since is None):
        raise ValueError("load: cần đúng một trong tickets / since")
    scope: Any = (list(dict.fromkeys(tickets)) if tickets is not None
                  else select(_AUDIT.c.ticket_id).where(_AUDIT.c.created_at >= since).distinct())  # fmt: skip
    async with engine.connect() as conn:
        found = (await conn.execute(select(_AUDIT).where(_AUDIT.c.ticket_id.in_(scope)).order_by(_AUDIT.c.log_id))).mappings()
        by_ticket: dict[str, list[dict[str, Any]]] = {}
        for r in found:
            by_ticket.setdefault(r["ticket_id"], []).append(dict(r))
        finals = {
            r.ticket_id: r.final_state
            for r in await conn.execute(select(_TICKETS.c.ticket_id, _TICKETS.c.final_state).where(_TICKETS.c.ticket_id.in_(scope)))
        }  # fmt: skip
    return by_ticket, finals


async def run(
    engine: AsyncEngine,
    *,
    tickets: Sequence[str] | None = None,
    since: datetime | None = None,
    scanner: SecretScanner,
    log_lines: Iterable[str] | None = None,
) -> Report:
    by_ticket, finals = await load(engine, tickets=tickets, since=since)
    order = [*by_ticket, *(t for t in finals if t not in by_ticket)]
    missing = [m for t in order for m in required(t, by_ticket.get(t, []), final_state=finals.get(t))]
    secrets = scan_rows((r for t in order for r in by_ticket.get(t, [])), scanner)
    if log_lines is not None:
        secrets += scan_log(log_lines, scanner)
    return Report(tuple(order), tuple(missing), tuple(secrets))


def render(report: Report) -> str:
    """Bảng `| ticket | điểm thiếu | trường thiếu |`, dòng `bí mật: <column> dòng <ref> (luật <rule>)`, dòng cuối
    `KẾT LUẬN: <n> thiếu, <m> bí mật (<k> ticket)`."""
    lines = ["| ticket | điểm thiếu | trường thiếu |", "|---|---|---|"]
    for m in report.missing:
        where = f"dòng {m.log_id}" if m.log_id is not None else "không có dòng"
        lines.append(f"| {m.ticket_id} | {m.point} | {', '.join(m.fields)} ({where}) |")
    for h in report.secrets:
        lines.append(f"bí mật: {h.column} dòng {h.ref} (luật {h.rule})" + (f" — ticket {h.ticket_id}" if h.ticket_id else ""))
    lines.append(f"KẾT LUẬN: {len(report.missing)} thiếu, {len(report.secrets)} bí mật ({len(report.tickets)} ticket)")
    return "\n".join(lines)


def _since(value: str) -> datetime:
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("thiếu múi giờ")
    return at


_since.__name__ = "thời điểm ISO có múi giờ (vd 2026-10-01T10:00:00+07:00)"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit_check", description="Kiểm 8 điểm log + quét bí mật trên audit_logs (chỉ đọc).")
    parser.add_argument("tickets", nargs="*", metavar="TICKET_ID")
    parser.add_argument("--since", type=_since, help="ticket có dòng audit từ thời điểm này (ISO, có múi giờ)")
    parser.add_argument("--canary", action="append", default=[], help="chuỗi canary (lặp được) — không bao giờ in ra")
    parser.add_argument("--log", help="file log cần quét thêm; '-' = stdin")
    args = parser.parse_args(argv)
    if bool(args.tickets) == (args.since is not None):
        parser.error("cần ĐÚNG MỘT trong hai: danh sách TICKET_ID hoặc --since")
    settings = get_settings()
    role = "app_monitor" if settings.monitor_database_url else "app_rw"
    dsn = settings.monitor_database_url or settings.database_url
    scanner = SecretScanner.from_config(settings.config_dir, args.canary)
    log_lines: list[str] | None = None
    if args.log == "-":
        log_lines = sys.stdin.read().splitlines()
    elif args.log is not None:
        log_lines = Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"audit_check: nguồn {role} (READ ONLY)", file=sys.stderr)  # nhãn role — KHÔNG in DSN
    try:
        report = asyncio.run(_run(dsn, tickets=args.tickets or None, since=args.since, scanner=scanner, log_lines=log_lines))
    except Exception as exc:  # noqa: BLE001 — lỗi DB: chỉ in tên lớp (thông điệp driver có thể mang host/role)
        print(f"audit_check: không đọc được DB ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(render(report))
    return 0 if report.ok else 1


async def _run(
    dsn: str, *, tickets: Sequence[str] | None, since: datetime | None, scanner: SecretScanner, log_lines: list[str] | None
) -> Report:
    engine = readonly_engine(dsn)
    try:
        return await run(engine, tickets=tickets, since=since, scanner=scanner, log_lines=log_lines)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
