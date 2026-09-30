"""Cổng 2 trên stack compose THẬT (2b-4) — `make gate2 S=<kịch bản>` sau `make up`.

Không nằm trong `make test`: cần backend + worker + Postgres của compose đang chạy, đồng hồ thật, SIGKILL
thật. Cách chạy, cách đọc từng kịch bản: `README.md` cạnh file này.

Chốt an toàn (chạy TRƯỚC mọi việc khác, kể cả trước HTTP):
1. `compose exec -T backend printenv APP_ENV` phải là `dev` — khác thì dừng, exit 2.
2. URL backend chỉ nhận `http://127.0.0.1:<cổng>`.
3. Mọi lệnh ngoài đi qua `check_command`: cấm `down -v` / `--volumes`, `volume rm|prune`.

Script không đọc `.env`: compose tự đọc (`--env-file` do Makefile truyền qua `COMPOSE`), psql chạy trong
container postgres bằng biến của chính container. Mật khẩu demo: `GATE2_PASSWORD`, không có thì hằng
`tests/fakes/demo.py` (mật khẩu công khai của mock).
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from tests.fakes.demo import DEMO_PASSWORD

SAFE_HOST = "127.0.0.1"
DEFAULT_URL = f"http://{SAFE_HOST}:8000"
E7_NOTE = "E7 do RefusingExecutor (dung toi Phase 3)"
APPROVER = "ha.lt"  # l1_01 = FAKE_APPROVER_ID — đăng nhập TRƯỚC để có dòng users (2b-3-Q4)
APPROVER_ID = "l1_01"
EMPLOYEE = "an.nv"
TICKET_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PSQL = 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

S_PENDING_APPROVAL, S_CLARIFYING, S_CONFIRMING = "S_PENDING_APPROVAL", "S_CLARIFYING", "S_CONFIRMING"
S_ESCALATED, S_RESOLVED = "S_ESCALATED", "S_RESOLVED"
WAIT_OF_PRESET = {"approval": S_PENDING_APPROVAL, "clarify": S_CLARIFYING, "confirm": S_CONFIRMING}


class Unsafe(Exception):
    """Chốt an toàn không qua — dừng hẳn, không chạy lệnh nào nữa."""


class StackError(Exception):
    """Stack không làm được việc script cần (lệnh lỗi, HTTP sai mã, chờ quá hạn)."""


# ---- Chốt an toàn ----------------------------------------------------------------------------


def check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != SAFE_HOST or parts.path not in ("", "/"):
        raise Unsafe(f"URL backend {url!r}: chỉ nhận http://{SAFE_HOST}:<cổng> (stack dev trên máy này)")
    return url.rstrip("/")


def check_command(cmd: Sequence[str]) -> None:
    """Cấm mọi lệnh xoá volume (mất dữ liệu stack — không có bản sao)."""
    args = list(cmd)
    if "down" in args:
        for arg in args[args.index("down") + 1 :]:
            short = arg.startswith("-") and not arg.startswith("--") and "v" in arg[1:]
            if arg == "--volumes" or arg.startswith("--volumes=") or short:
                raise Unsafe(f"từ chối lệnh xoá volume: {shlex.join(args)}")
    if "volume" in args and ({"rm", "prune"} & set(args[args.index("volume") + 1 :])):
        raise Unsafe(f"từ chối lệnh xoá volume: {shlex.join(args)}")


type Run = Callable[[list[str], str | None], tuple[int, str]]


def subprocess_run(cmd: list[str], stdin: str | None) -> tuple[int, str]:
    done = subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=False)
    return done.returncode, done.stdout + (done.stderr if done.returncode else "")


class Shell:
    """Điểm DUY NHẤT chạy lệnh ngoài: kiểm `check_command`, in lệnh trước khi chạy."""

    def __init__(self, compose: Sequence[str], run: Run = subprocess_run,
                 echo: Callable[[str], None] = print) -> None:  # fmt: skip
        self.compose_base = list(compose)
        self._run = run
        self._echo = echo

    def run(self, cmd: Sequence[str], *, stdin: str | None = None, shown: str | None = None) -> str:
        cmd = list(cmd)
        check_command(cmd)
        self._echo(f"$ {shown or shlex.join(cmd)}")
        code, out = self._run(cmd, stdin)
        if code != 0:
            raise StackError(f"lệnh lỗi (mã {code}): {shlex.join(cmd)}\n{out[-2000:]}")
        return out

    def compose(self, *args: str) -> str:
        return self.run([*self.compose_base, *args])

    def sql(self, query: str) -> Any:
        """Một câu SELECT trả MỘT giá trị JSON (json_agg / count…). Chạy trong container postgres."""
        one_line = " ".join(query.split())
        shown = f"{shlex.join([*self.compose_base, 'exec', '-T', 'postgres'])} psql <<< {one_line[:160]}"
        out = self.run([*self.compose_base, "exec", "-T", "postgres", "sh", "-c", PSQL],
                       stdin=query, shown=shown)  # fmt: skip
        return json.loads(out.strip() or "null")


def password_from(env: Mapping[str, str]) -> str:
    """`GATE2_PASSWORD` nếu đặt, không thì mật khẩu demo công khai của mock (hằng, không chép chuỗi)."""
    return env.get("GATE2_PASSWORD") or DEMO_PASSWORD


def safety_gate(shell: Shell) -> None:
    env = shell.compose("exec", "-T", "backend", "printenv", "APP_ENV").strip()
    if env != "dev":
        raise Unsafe(f"APP_ENV của container backend = {env!r}, không phải 'dev' — dừng")


# ---- Báo cáo: mỗi dòng PASS/FAIL kèm ticket_id -----------------------------------------------


@dataclass
class Line:
    ok: bool
    ticket: str
    name: str
    detail: str

    def render(self) -> str:
        return f"{'PASS' if self.ok else 'FAIL'} {self.ticket} {self.name}: {self.detail}"


@dataclass
class Report:
    lines: list[Line] = field(default_factory=list)
    echo: Callable[[str], None] = print

    def check(self, ticket: str, name: str, ok: bool, expected: Any, got: Any) -> bool:
        line = Line(ok, ticket, name, f"mong đợi {expected}, thấy {got}")
        self.lines.append(line)
        self.echo(line.render())
        return ok

    def eq(self, ticket: str, name: str, expected: Any, got: Any) -> bool:
        return self.check(ticket, name, expected == got, expected, got)

    def rows(self, ticket: str, name: str, rows: Sequence[Any] | None,
             pred: Callable[[Any], bool], expected: str) -> bool:  # fmt: skip
        """Mọi dòng thoả `pred` — tập RỖNG là FAIL (không xanh oan)."""
        if not rows:
            return self.check(ticket, name, False, expected, "không có dòng nào (rỗng không được tính là qua)")
        bad = [r for r in rows if not pred(r)]
        return self.check(ticket, name, not bad, expected, bad or rows)

    def absent(self, ticket: str, name: str, found: Sequence[Any] | None,
               control: Sequence[Any] | None, control_name: str) -> bool:  # fmt: skip
        """"Không có X" chỉ có nghĩa khi đối chứng "có Y" trong cùng ticket khác rỗng."""
        if not control:
            return self.check(ticket, name, False, f"0 dòng, đối chứng {control_name} có",
                              f"đối chứng {control_name} rỗng — không kết luận được")  # fmt: skip
        return self.check(ticket, name, not found, f"0 dòng (đối chứng {control_name}: có)",
                          f"{len(found or [])} dòng {found or ''}".strip())  # fmt: skip

    def fail(self, ticket: str, name: str, why: str) -> None:
        self.check(ticket, name, False, "chạy hết kịch bản", why)

    def summary(self) -> int:
        failed = [line for line in self.lines if not line.ok]
        self.echo(f"\n==== {len(self.lines) - len(failed)} PASS, {len(failed)} FAIL ====")
        for line in failed:
            self.echo(line.render())
        return 1 if failed or not self.lines else 0


# ---- HTTP + DB của một ticket ----------------------------------------------------------------


def wait_for[T](what: str, fn: Callable[[], T | None], timeout: float, interval: float = 0.5) -> T:
    """Poll có hạn (không sleep mù): trả giá trị đầu tiên khác None."""
    end = time.monotonic() + timeout
    while True:
        value = fn()
        if value is not None:
            return value
        if time.monotonic() >= end:
            raise StackError(f"quá {timeout:.0f} giây chờ {what}")
        time.sleep(interval)


def q(ticket: str) -> str:
    """ticket_id do API sinh — vẫn kiểm dạng trước khi đặt vào SQL."""
    if not TICKET_ID.fullmatch(ticket):
        raise StackError(f"ticket_id lạ: {ticket!r}")
    return f"'{ticket}'"


@dataclass
class Ctx:
    shell: Shell
    http: httpx.Client
    report: Report
    password: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    tokens: dict[str, dict[str, str]] = field(default_factory=dict)

    # -- HTTP --
    def login(self, username: str) -> dict[str, str]:
        r = self.http.post("/api/auth/login", json={"username": username, "password": self.password})
        if r.status_code != 200:
            raise StackError(f"đăng nhập {username}: HTTP {r.status_code} {r.text[:200]}")
        self.tokens[username] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return self.tokens[username]

    def login_all(self) -> None:
        self.login(APPROVER)  # trước: FAKE_APPROVER_ID phải có dòng users
        self.login(EMPLOYEE)

    @property
    def an(self) -> dict[str, str]:
        return self.tokens[EMPLOYEE]

    @property
    def l1(self) -> dict[str, str]:
        return self.tokens[APPROVER]

    def create(self, preset: str, label: str) -> str:
        text = f"[fake:{preset}] gate2 {self.run_id} {label}"
        r = self.http.post("/api/tickets", json={"text": text}, headers=self.an)
        if r.status_code != 202:
            raise StackError(f"tạo ticket {preset}: HTTP {r.status_code} {r.text[:200]}")
        ticket = str(r.json()["ticket_id"])
        q(ticket)
        return ticket

    def view(self, ticket: str) -> dict[str, Any]:
        r = self.http.get(f"/api/tickets/{ticket}", headers=self.an)
        if r.status_code != 200:
            raise StackError(f"GET ticket {ticket}: HTTP {r.status_code} {r.text[:200]}")
        return dict(r.json())

    def turn_count(self, ticket: str) -> int:
        return len(self.turns(ticket))

    def after_event(self, ticket: str, turns_before: int, timeout: float = 30,
                    interval: float = 0.5) -> dict[str, Any]:  # fmt: skip
        """Mọi request trả 202 (tạo ticket, trả lời, xác nhận, quyết định duyệt) chạy lượt NỀN: đọc trạng
        thái ngay sau 202 vẫn thấy trạng thái CŨ. Chờ tới khi có hơn `turns_before` lượt và mọi lượt đã
        đóng — đúng cả khi lượt mới dừng lại ở cùng trạng thái chờ (vd hỏi lại). Tạo ticket: `turns_before=0`
        (lượt `submit` ghi cùng transaction với dòng `tickets`). Sau phục hồi: cũng 0 — recover giữ
        `turn_id`, lượt duy nhất chỉ đóng khi worker chạy xong."""
        def done() -> bool | None:
            turns = self.turns(ticket)
            return True if len(turns) > turns_before and all(x["ended"] for x in turns) else None
        wait_for(f"lượt mới của ticket {ticket} đóng", done, timeout, interval)
        return self.view(ticket)

    def closed(self, ticket: str, timeout: float) -> dict[str, Any]:
        """Chỉ cho việc do WORKER làm (bắn hạn) — không có request 202 nào để đếm lượt."""
        def done() -> dict[str, Any] | None:
            v = self.view(ticket)
            return v if v["final_state"] is not None else None
        return wait_for(f"ticket {ticket} đóng", done, timeout)

    def post(self, path: str, body: Mapping[str, Any], headers: Mapping[str, str]) -> httpx.Response:
        return self.http.post(path, json=dict(body), headers=dict(headers))

    def health_up(self, timeout: float = 120) -> None:
        def up() -> bool | None:
            try:
                body = self.http.get("/api/health").json()
            except (httpx.HTTPError, ValueError):
                return None
            return True if body.get("runtime") == "up" else None
        wait_for("/api/health runtime=up", up, timeout, interval=1)

    # -- DB --
    def audit(self, ticket: str) -> list[dict[str, Any]]:
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(json_build_object('step', step, 'event', event, 'detail', detail) "
            f"ORDER BY log_id), '[]') FROM audit_logs WHERE ticket_id = {q(ticket)}"
        ))  # fmt: skip

    def approvals(self, ticket: str) -> list[dict[str, Any]]:
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(json_build_object('approval_id', approval_id, 'status', status, "
            "'decided_by', decided_by, 'approver_id', approver_id, 'backup_approver_id', backup_approver_id, "
            f"'conflict_detected', conflict_detected)), '[]') FROM approvals WHERE ticket_id = {q(ticket)}"
        ))  # fmt: skip

    def turns(self, ticket: str) -> list[dict[str, Any]]:
        return list(self.shell.sql(
            "SELECT coalesce(json_agg(json_build_object('turn_id', turn_id, 'ended', ended_at IS NOT NULL, "
            "'recover_attempts', recover_attempts, 'event_type', event_type) ORDER BY started_at), '[]') "
            f"FROM turns WHERE ticket_id = {q(ticket)}"
        ))  # fmt: skip

    def effects(self, ticket: str) -> list[str]:
        return list(self.shell.sql(
            f"SELECT coalesce(json_agg(kind), '[]') FROM side_effects WHERE ticket_id = {q(ticket)}"
        ))

    def escalations(self, ticket: str) -> list[str]:
        return list(self.shell.sql(
            f"SELECT coalesce(json_agg(exit_code), '[]') FROM escalations WHERE ticket_id = {q(ticket)}"
        ))

    def ticket_lock_count(self, ticket: str) -> int:
        """Khoá advisory của ĐÚNG ticket này (`pg_advisory_lock(hashtext(id))`: khoá bigint = classid
        (32 bit cao) + objid (32 bit thấp), objsubid = 1)."""
        return int(self.shell.sql(
            f"WITH k AS (SELECT hashtext({q(ticket)})::bigint AS h) SELECT count(*) FROM pg_locks, k "
            "WHERE locktype = 'advisory' AND objsubid = 1 AND granted "
            "AND classid::bigint = ((k.h >> 32) & 4294967295) AND objid::bigint = (k.h & 4294967295)"
        ))  # fmt: skip

    def push_deadline_to_past(self, ticket: str) -> int:
        return int(self.shell.sql(
            "WITH a AS (UPDATE approvals SET deadline = now() - interval '1 second' "
            f"WHERE ticket_id = {q(ticket)} AND status = 'pending' RETURNING 1), "
            "w AS (UPDATE wait_deadlines SET deadline = now() - interval '1 second' "
            f"WHERE ticket_id = {q(ticket)} AND fired_at IS NULL RETURNING 1) "
            "SELECT (SELECT count(*) FROM a) + (SELECT count(*) FROM w)"
        ))  # fmt: skip

    def worker_health(self) -> str:
        out = self.shell.compose("ps", "--format", "json", "worker").strip()
        items = _json_items(out)
        return str(items[0].get("Health", "")) if items else "không chạy"


def _json_items(out: str) -> list[dict[str, Any]]:
    """`compose ps --format json`: tuỳ bản là một mảng JSON hoặc mỗi dòng một object."""
    if not out:
        return []
    try:
        data = json.loads(out)
        return list(data) if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in out.splitlines() if line.strip()]


def events(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    return [(r["step"], r["event"]) for r in rows]


def late_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [r for r in rows if r["event"] == "late_event"]


# ---- Kịch bản --------------------------------------------------------------------------------


def preflight(ctx: Ctx) -> None:
    rep = ctx.report
    body = ctx.http.get("/api/health").json()
    rep.eq("-", "health status", "ok", body.get("status"))
    rep.eq("-", "health runtime", "up", body.get("runtime"))
    rep.eq("-", "worker healthy", "healthy", ctx.worker_health())
    ctx.login_all()
    rep.check("-", f"đăng nhập {APPROVER} rồi {EMPLOYEE}", True, "200", "200")
    t = ctx.create("clarify", "preflight")
    v = ctx.after_event(t, 0)
    if not rep.eq(t, "thẻ [fake:clarify] → chờ trả lời", S_CLARIFYING, v["status"]):
        rep.echo("  → ticket đi đường mặc định: .env chưa có FAKE_SCENARIO, hoặc chưa `make up` lại")


def _three_waits(ctx: Ctx, label: str) -> dict[str, str]:
    tickets = {p: ctx.create(p, label) for p in WAIT_OF_PRESET}
    for preset, t in tickets.items():
        v = ctx.after_event(t, 0)
        ctx.report.eq(t, f"{preset}: dừng ở trạng thái chờ", WAIT_OF_PRESET[preset], v["status"])
    return tickets


def _count_tickets(ctx: Ctx) -> int:
    return int(ctx.shell.sql("SELECT count(*) FROM tickets"))


def restart(ctx: Ctx, *, full: bool = False) -> None:
    rep = ctx.report
    ctx.login_all()
    tickets = _three_waits(ctx, "restart-all" if full else "restart")
    if full:
        before = _count_tickets(ctx)
        ctx.shell.compose("down")  # KHÔNG -v: giữ volume (check_command chặn -v)
        ctx.shell.run(["make", "up"])
        safety_gate(ctx.shell)
        after = _count_tickets(ctx)
        rep.eq("-", "số ticket trước/sau down+up", before, after)
    else:
        ctx.shell.compose("restart", "backend")
    ctx.health_up()
    ctx.login_all()

    t = tickets["approval"]
    [approval] = ctx.approvals(t)
    before = ctx.turn_count(t)
    r = ctx.post(f"/api/approvals/{approval['approval_id']}/decision", {"decision": "approved"}, ctx.l1)
    rep.eq(t, "duyệt sau restart → 202", 202, r.status_code)
    v = ctx.after_event(t, before)
    rep.eq(t, f"approval → E7 ({E7_NOTE})", (S_ESCALATED, "E7"), (v["final_state"], v["exit_code"]))
    ev = events(ctx.audit(t))
    ok = ("B16", "approved") in ev and ("B17", "execution_failed") in ev and (
        ev.index(("B16", "approved")) < ev.index(("B17", "execution_failed")))  # fmt: skip
    rep.check(t, "audit: B16 approved → B17 execution_failed (chạy tiếp đúng chỗ)", ok,
              "B16 approved trước B17 execution_failed", ev)  # fmt: skip
    rep.eq(t, "phiếu sau duyệt", [("approved", APPROVER_ID)],
           [(a["status"], a["decided_by"]) for a in ctx.approvals(t)])  # fmt: skip

    t = tickets["clarify"]
    before = ctx.turn_count(t)
    r = ctx.post(f"/api/tickets/{t}/messages", {"text": "may LAP-1"}, ctx.an)
    rep.eq(t, "trả lời sau restart → 202", 202, r.status_code)
    v = ctx.after_event(t, before)
    rep.eq(t, "clarify → chờ duyệt (không hỏi lại)", S_PENDING_APPROVAL, v["status"])
    rep.eq(t, "B11 asked đúng 1 lần", 1, events(ctx.audit(t)).count(("B11", "asked")))

    t = tickets["confirm"]
    before = ctx.turn_count(t)
    r = ctx.post(f"/api/tickets/{t}/confirm", {"confirmed": True}, ctx.an)
    rep.eq(t, "xác nhận sau restart → 202", 202, r.status_code)
    v = ctx.after_event(t, before)
    rep.eq(t, "confirm → đóng", (S_RESOLVED, "resolved_user_confirmed"), (v["final_state"], v["close_reason"]))

    for t in tickets.values():
        n = int(ctx.shell.sql(f"SELECT count(*) FROM checkpoints WHERE thread_id = {q(t)}"))
        rep.check(t, "có checkpoint trên thread = ticket_id", n > 0, "> 0", n)


def restart_all(ctx: Ctx) -> None:
    restart(ctx, full=True)


WRONG_EVENT: dict[str, tuple[str, dict[str, Any]]] = {  # preset → (route, body) KHÔNG khớp trạng thái chờ của nó
    "approval": ("messages", {"text": "x"}),
    "clarify": ("confirm", {"confirmed": True}),
    "confirm": ("messages", {"text": "x"}),
}


def late(ctx: Ctx) -> None:
    rep = ctx.report
    ctx.login_all()
    for preset, t in _three_waits(ctx, "late").items():
        route, body = WRONG_EVENT[preset]
        r = ctx.post(f"/api/tickets/{t}/{route}", body, ctx.an)
        rep.eq(t, f"{preset}: sự kiện sai loại → 409", 409, r.status_code)
        rep.eq(t, f"{preset}: trạng thái không đổi", WAIT_OF_PRESET[preset], ctx.view(t)["status"])
        rows = late_rows(ctx.audit(t))
        rep.eq(t, f"{preset}: đúng 1 late_event", 1, len(rows))
        def ok(r: Any, s: str = WAIT_OF_PRESET[preset]) -> bool:
            return bool(r["detail"].get("source") == "user" and r["detail"].get("actual_status") == s)

        rep.rows(t, f"{preset}: late_event source=user, actual_status", rows, ok, "source=user, actual_status đúng")


def expire(ctx: Ctx) -> None:
    rep = ctx.report
    ctx.login_all()
    tickets = _three_waits(ctx, "expire")
    for preset, t in tickets.items():
        rep.eq(t, f"{preset}: dời hạn về quá khứ", 1, ctx.push_deadline_to_past(t))
    expect = {"approval": (S_ESCALATED, "E6", None), "clarify": (S_ESCALATED, "E4", None),
              "confirm": (S_RESOLVED, None, "resolved_auto_timeout_48h")}  # fmt: skip
    for preset, t in tickets.items():
        v = ctx.closed(t, 45)
        rep.eq(t, f"{preset}: worker bắn hạn", expect[preset], (v["final_state"], v["exit_code"], v["close_reason"]))
    t = tickets["approval"]
    rep.eq(t, "phiếu → timeout", ["timeout"], [a["status"] for a in ctx.approvals(t)])
    audit = ctx.audit(t)
    rep.absent(t, "0 dòng audit B17 (không tự thực thi)", [r for r in audit if r["step"] == "B17"],
               [r for r in audit if (r["step"], r["event"]) == ("B16", "approval_timeout")],
               "B16 approval_timeout")  # fmt: skip
    rep.eq(t, "escalation E6", ["E6"], ctx.escalations(t))
    rep.eq(tickets["clarify"], "escalation E4", ["E4"], ctx.escalations(tickets["clarify"]))
    for preset in ("clarify", "confirm"):
        t = tickets[preset]
        fired = ctx.shell.sql(
            f"SELECT coalesce(json_agg(fired_at IS NOT NULL), '[]') FROM wait_deadlines WHERE ticket_id = {q(t)}"
        )  # fmt: skip
        rep.rows(t, f"{preset}: wait_deadlines.fired_at có", fired, bool, "mọi hạn đã bắn")


def late_click(ctx: Ctx) -> None:
    rep = ctx.report
    ctx.login_all()
    ctx.shell.compose("stop", "worker")
    try:
        t = ctx.create("approval", "late-click")
        rep.eq(t, "dừng ở chờ duyệt", S_PENDING_APPROVAL, ctx.after_event(t, 0)["status"])
        [approval] = ctx.approvals(t)
        aid = approval["approval_id"]
        rep.eq(t, "dời hạn duyệt về quá khứ", 1, ctx.push_deadline_to_past(t))
        r = ctx.post(f"/api/approvals/{aid}/decision", {"decision": "approved"}, ctx.l1)
        rep.eq(t, "bấm muộn (worker dừng) → 409", 409, r.status_code)
        rep.eq(t, "phiếu VẪN pending trước khi worker quét", ["pending"], [a["status"] for a in ctx.approvals(t)])
        rows = late_rows(ctx.audit(t))
        rep.eq(t, "late_event reason/approval_id/clicked_by",
               [("expired", str(aid), APPROVER_ID, "user")],
               [(r["detail"].get("reason"), str(r["detail"].get("approval_id")), r["detail"].get("clicked_by"),
                 r["detail"].get("source")) for r in rows])  # fmt: skip
    finally:
        ctx.shell.compose("start", "worker")  # luôn bật lại worker, kể cả khi kiểm lỗi giữa chừng
    v = ctx.closed(t, 90)
    rep.eq(t, "worker → E6", (S_ESCALATED, "E6"), (v["final_state"], v["exit_code"]))
    rep.eq(t, "phiếu → timeout", ["timeout"], [a["status"] for a in ctx.approvals(t)])
    audit = ctx.audit(t)
    rep.absent(t, "0 dòng audit B17", [r for r in audit if r["step"] == "B17"],
               [r for r in audit if (r["step"], r["event"]) == ("B16", "approval_timeout")],
               "B16 approval_timeout")  # fmt: skip
    r = ctx.post(f"/api/approvals/{aid}/decision", {"decision": "approved"}, ctx.l1)
    rep.eq(t, "bấm lại sau timeout → 409", 409, r.status_code)
    reasons = [r["detail"].get("reason") for r in late_rows(ctx.audit(t))]
    rep.eq(t, "late_event: expired rồi already_decided", ["expired", "already_decided"], reasons)


def _kill(ctx: Ctx, preset: str, sleeping: Callable[[str], bool], what: str) -> None:
    rep = ctx.report
    ctx.login_all()
    t = ctx.create(preset, preset)
    wait_for(f"ticket {t} {what}", lambda: True if sleeping(t) else None, 30)
    [turn] = ctx.turns(t)
    rep.eq(t, "lượt đang mở trước khi kill", False, turn["ended"])
    # đối chứng: truy vấn khoá tìm THẤY khoá đang giữ — không thì "nhả = 0" bên dưới xanh oan (vd tính
    # sai classid/objid)
    rep.eq(t, "khoá advisory của ticket đang giữ trước kill (đối chứng)", 1, ctx.ticket_lock_count(t))
    ctx.shell.compose("kill", "-s", "SIGKILL", "backend")
    try:
        wait_for("khoá advisory của ticket nhả", lambda: True if ctx.ticket_lock_count(t) == 0 else None, 10)
        rep.check(t, "khoá advisory nhả ≤ 10 giây sau SIGKILL", True, 0, 0)
    except StackError:
        rep.check(t, "khoá advisory nhả ≤ 10 giây sau SIGKILL", False, 0, ctx.ticket_lock_count(t))
    rep.eq(t, "lượt vẫn mở sau kill", [False], [x["ended"] for x in ctx.turns(t)])
    ctx.shell.compose("up", "-d", "backend")
    ctx.health_up()
    ctx.login_all()
    rep.echo("  … chờ worker phục hồi (lượt mở > 120 giây, quét mỗi 60 giây) — tối đa 6 phút")
    v = ctx.after_event(t, 0, 360, interval=5)  # lượt duy nhất (cùng turn_id) đóng khi phục hồi xong
    rep.eq(t, "phục hồi → chờ duyệt", S_PENDING_APPROVAL, v["status"])
    turns = ctx.turns(t)
    rep.eq(t, "1 lượt, cùng turn_id, recover_attempts=1, đã đóng",
           [(turn["turn_id"], 1, True)], [(x["turn_id"], x["recover_attempts"], x["ended"]) for x in turns])  # fmt: skip
    rep.eq(t, "1 phiếu duyệt", 1, len(ctx.approvals(t)))
    effects = Counter(ctx.effects(t))
    rep.eq(t, "side_effects approval_create/notify_approver", (1, 1),
           (effects["approval_create"], effects["notify_approver"]))  # fmt: skip
    audit = ctx.audit(t)
    dup = [e for e, n in Counter(events(audit)).items() if n > 1]
    rep.absent(t, "không (step, event) nào ghi 2 lần", dup, audit, "audit của ticket")


def kill(ctx: Ctx) -> None:
    def in_b06(t: str) -> bool:  # B3 xong → đang ngủ ở đầu b06_diagnose
        return ("B3", "intent_classified") in events(ctx.audit(t)) and not any(
            s == "B6" for s, _ in events(ctx.audit(t)))  # fmt: skip
    _kill(ctx, "kill_b06", in_b06, "ngủ ở b06_diagnose")


def kill_b15(ctx: Ctx) -> None:
    def after_create(t: str) -> bool:  # phiếu đã tạo, chưa báo người duyệt
        kinds = ctx.effects(t)
        return "approval_create" in kinds and "notify_approver" not in kinds
    _kill(ctx, "kill_b15", after_create, "ngủ sau approval_create")


def tc29(ctx: Ctx) -> None:
    rep = ctx.report
    ctx.login_all()
    bad = ctx.create("raise", "tc29")
    others = [ctx.create("approval", f"tc29-{i}") for i in range(5)]
    v = ctx.after_event(bad, 0, 60)
    rep.eq(bad, "node ném lỗi → E9", (S_ESCALATED, "E9"), (v["final_state"], v["exit_code"]))
    rows = [r for r in ctx.audit(bad) if r["event"] == "unhandled_exception"]
    rep.rows(bad, "audit unhandled_exception có traceback", rows,
             lambda r: bool((r["detail"] or {}).get("traceback")), "detail.traceback khác rỗng")  # fmt: skip
    spans = ctx.shell.sql(
        "SELECT coalesce(json_agg(s.attributes ->> 'traceback'), '[]') FROM spans s JOIN turns t "
        f"USING (turn_id) WHERE t.ticket_id = {q(bad)} AND s.status = 'error'"
    )  # fmt: skip
    rep.rows(bad, "span error có traceback", spans, bool, "attributes.traceback khác rỗng")
    for t in others:
        rep.eq(t, "ticket song song vẫn tới chờ duyệt", S_PENDING_APPROVAL, ctx.after_event(t, 0, 60)["status"])
    rep.eq("-", "worker vẫn healthy", "healthy", ctx.worker_health())


def threads(ctx: Ctx) -> None:
    """Mục thủ công của cổng 2: mỗi ticket một luồng checkpoint riêng. In bảng để người đọc."""
    rep = ctx.report
    rows = ctx.shell.sql(
        "SELECT coalesce(json_agg(json_build_object('ticket', t.ticket_id, 'threads', "
        "(SELECT count(DISTINCT c.thread_id) FROM checkpoints c WHERE c.thread_id = t.ticket_id), "
        "'checkpoints', (SELECT count(*) FROM checkpoints c WHERE c.thread_id = t.ticket_id)) "
        "ORDER BY t.created_at), '[]') FROM tickets t WHERE t.redacted_request LIKE '[fake:%] gate2 %'"
    )  # fmt: skip
    rep.echo(f"{'ticket_id':<40} threads  checkpoints")
    for r in rows or []:
        rep.echo(f"{r['ticket']:<40} {r['threads']:>7}  {r['checkpoints']:>11}")
    rep.rows("-", "mỗi ticket gate2 đúng 1 thread (thread_id = ticket_id)", rows,
             lambda r: r["threads"] == 1 and r["checkpoints"] > 0, "threads=1, checkpoints>0")  # fmt: skip
    stray = ctx.shell.sql(
        "SELECT coalesce(json_agg(DISTINCT c.thread_id), '[]') FROM checkpoints c "
        "WHERE NOT EXISTS (SELECT 1 FROM tickets t WHERE t.ticket_id = c.thread_id)"
    )  # fmt: skip
    rep.absent("-", "không thread nào lạ (không có dòng tickets)", stray, rows, "ticket gate2")


SCENARIOS: dict[str, Callable[[Ctx], None]] = {
    "preflight": preflight, "restart": restart, "restart-all": restart_all, "late": late,
    "expire": expire, "late-click": late_click, "kill": kill, "kill-b15": kill_b15, "tc29": tc29,
    "threads": threads,
}  # fmt: skip
ALL = [name for name in SCENARIOS if name != "restart-all"]


def main(argv: Sequence[str], *, run: Run = subprocess_run, env: Mapping[str, str] = os.environ,
         echo: Callable[[str], None] = print) -> int:  # fmt: skip
    names = [n for arg in argv for n in (ALL if arg == "all" else [arg])] or ["preflight"]
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        echo(f"kịch bản lạ: {unknown}; chọn trong {sorted(SCENARIOS)} hoặc all")
        return 2
    report = Report(echo=echo)
    try:
        url = check_url(env.get("GATE2_URL", DEFAULT_URL))
        shell = Shell(shlex.split(env.get("COMPOSE", "docker compose")), run=run, echo=echo)
        safety_gate(shell)
    except (Unsafe, StackError) as exc:
        echo(f"DỪNG (chốt an toàn): {exc}")
        return 2
    password = password_from(env)
    with httpx.Client(base_url=url, timeout=15) as http:
        ctx = Ctx(shell=shell, http=http, report=report, password=password)
        echo(f"gate2 run {ctx.run_id}: {names}")
        for name in names:
            echo(f"\n==== {name} ====")
            try:
                SCENARIOS[name](ctx)
            except Unsafe as exc:
                echo(f"DỪNG (chốt an toàn): {exc}")
                return 2
            except (StackError, httpx.HTTPError, KeyError, ValueError) as exc:
                report.fail("-", f"{name} dừng giữa chừng", f"{type(exc).__name__}: {exc}")
    return report.summary()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
