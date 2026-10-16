"""`tests/stack/gate2.py` (2b-4) — phần chạy được không cần stack: 3 chốt an toàn (APP_ENV của
container backend, URL chỉ 127.0.0.1, cấm xoá volume), hàm kiểm không xanh oan khi rỗng, dòng PASS/FAIL
kèm ticket_id, nguồn mật khẩu. Kịch bản thật chạy tay: `make gate2 S=…`."""

from typing import Any, cast

import pytest
from tests.fakes.demo import DEMO_PASSWORD
from tests.stack import gate2
from tests.stack.gate2 import Report, Shell, Unsafe, check_command, check_url, main

COMPOSE = "docker compose --env-file .env"


class FakeRun:
    """Thay subprocess: ghi mọi lệnh; `printenv APP_ENV` trả `app_env`."""

    def __init__(self, app_env: str = "dev", code: int = 0) -> None:
        self.app_env = app_env
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        self.calls.append(cmd)
        return (self.code, f"{self.app_env}\n" if cmd[-2:] == ["printenv", "APP_ENV"] else "")


def _main(argv: list[str], run: FakeRun, **env: str) -> tuple[int, list[str]]:
    out: list[str] = []
    code = main(argv, run=run, env={"COMPOSE": COMPOSE, **env}, echo=out.append)
    return code, out


# ---- Chốt 1: APP_ENV của container backend ---------------------------------------------------


@pytest.mark.parametrize("app_env", ["prod", "staging", "test", ""])
def test_stops_before_anything_when_backend_not_dev(app_env: str) -> None:
    run = FakeRun(app_env)
    code, out = _main(["all"], run)
    assert code == 2
    assert run.calls == [[*COMPOSE.split(), "exec", "-T", "backend", "printenv", "APP_ENV"]]
    assert any("DỪNG (chốt an toàn)" in line and repr(app_env) in line for line in out)


def test_stops_when_printenv_fails() -> None:
    run = FakeRun(code=1)  # container backend không chạy
    code, _ = _main(["preflight"], run)
    assert code == 2 and len(run.calls) == 1


def test_safety_gate_passes_on_dev() -> None:
    gate2.safety_gate(Shell(COMPOSE.split(), run=FakeRun("dev"), echo=lambda _: None))


# ---- Chốt 2: URL chỉ 127.0.0.1 ---------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://127.0.0.1:8000/"])
def test_url_localhost_ip_accepted(url: str) -> None:
    assert check_url(url) == "http://127.0.0.1:8000"


@pytest.mark.parametrize("url", [
    "http://localhost:8000", "http://0.0.0.0:8000", "https://127.0.0.1:8000", "http://10.0.0.5:8000",
    "http://127.0.0.1.evil.example:8000", "http://127.0.0.1:8000/api", "http://user@example.com:8000",
])  # fmt: skip
def test_url_other_hosts_refused(url: str) -> None:
    with pytest.raises(Unsafe):
        check_url(url)


def test_bad_url_stops_before_any_command() -> None:
    run = FakeRun()
    code, _ = _main(["preflight"], run, GATE2_URL="http://staging.example:8000")
    assert code == 2 and run.calls == []


# ---- Chốt 3: cấm xoá volume ------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [
    "docker compose down -v", "docker compose down --volumes", "docker compose down --volumes=true",
    "docker compose --env-file .env down -t 5 -v", "docker compose down -tv",
    "docker volume rm servicedesk_pgdata", "docker volume prune -f",
])  # fmt: skip
def test_volume_deleting_commands_refused(cmd: str) -> None:
    with pytest.raises(Unsafe):
        check_command(cmd.split())


@pytest.mark.parametrize("cmd", [
    "docker compose down", "docker compose restart backend", "docker compose kill -s SIGKILL backend",
    "docker compose stop worker", "docker compose start backend", "make up",
    "docker compose exec -T postgres psql -v ON_ERROR_STOP=1",  # -v của psql, không phải down
])  # fmt: skip
def test_normal_commands_allowed(cmd: str) -> None:
    check_command(cmd.split())


def test_shell_refuses_before_running_and_echoes_before_run() -> None:
    run, log = FakeRun(), cast(list[str], [])
    shell = Shell(COMPOSE.split(), run=run, echo=log.append)
    with pytest.raises(Unsafe):
        shell.compose("down", "-v")
    assert run.calls == [] and log == []
    shell.compose("restart", "backend")
    assert log == [f"$ {COMPOSE} restart backend"] and run.calls == [[*COMPOSE.split(), "restart", "backend"]]


# ---- Hàm kiểm: không xanh oan ----------------------------------------------------------------


def _report() -> tuple[Report, list[str]]:
    out: list[str] = []
    return Report(echo=out.append), out


def test_rows_empty_is_fail() -> None:
    rep, out = _report()
    assert not rep.rows("tk-1", "phiếu", [], lambda _: True, "có phiếu")
    assert not rep.rows("tk-1", "phiếu", None, lambda _: True, "có phiếu")
    assert out[0].startswith("FAIL tk-1 phiếu:") and "rỗng" in out[0]


def test_rows_checks_every_row() -> None:
    rep, _ = _report()
    assert rep.rows("tk-1", "x", [1, 2], lambda r: r > 0, "dương")
    assert not rep.rows("tk-1", "x", [1, -2], lambda r: r > 0, "dương")


def test_absent_needs_nonempty_control() -> None:
    rep, out = _report()
    assert not rep.absent("tk-1", "0 dòng B17", [], [], "B16 approval_timeout")
    assert "đối chứng" in out[-1] and out[-1].startswith("FAIL")
    assert rep.absent("tk-1", "0 dòng B17", [], [{"step": "B16"}], "B16 approval_timeout")
    assert not rep.absent("tk-1", "0 dòng B17", [{"step": "B17"}], [{"step": "B16"}], "B16")


def test_lines_carry_ticket_id_and_summary_exit_code() -> None:
    rep, out = _report()
    rep.eq("tk-9", "trạng thái", "S_CLARIFYING", "S_CLARIFYING")
    assert out[-1] == "PASS tk-9 trạng thái: mong đợi S_CLARIFYING, thấy S_CLARIFYING"
    assert rep.summary() == 0
    rep.eq("tk-10", "trạng thái", "a", "b")
    assert rep.summary() == 1
    assert out[-1].startswith("FAIL tk-10 trạng thái")  # FAIL được liệt kê lại cuối báo cáo


def test_summary_without_any_check_is_not_green() -> None:
    rep, _ = _report()
    assert rep.summary() == 1


# ---- Linh tinh -------------------------------------------------------------------------------


def test_password_env_then_demo_constant() -> None:
    assert gate2.password_from({}) == DEMO_PASSWORD
    assert gate2.password_from({"GATE2_PASSWORD": "khac"}) == "khac"


def test_unknown_scenario_refused_without_commands() -> None:
    run = FakeRun()
    code, _ = _main(["khong-co"], run)
    assert code == 2 and run.calls == []


def test_all_excludes_restart_all() -> None:
    assert "restart-all" not in gate2.ALL and set(gate2.ALL) | {"restart-all"} == set(gate2.SCENARIOS)


@pytest.mark.parametrize("out", [
    '[{"Service": "worker", "Health": "healthy"}]', '{"Service": "worker", "Health": "healthy"}\n',
])  # fmt: skip
def test_compose_ps_json_both_formats(out: str) -> None:
    assert gate2._json_items(out)[0]["Health"] == "healthy"


def test_ticket_id_checked_before_sql() -> None:
    assert gate2.q("abc-123_x") == "'abc-123_x'"
    with pytest.raises(gate2.StackError):
        gate2.q("x'; DROP TABLE tickets; --")


def test_sql_runs_psql_inside_postgres_container() -> None:
    seen: list[Any] = []

    def run(cmd: list[str], stdin: str | None) -> tuple[int, str]:
        seen.append((cmd, stdin))
        return 0, "3\n"

    shell = Shell(COMPOSE.split(), run=run, echo=lambda _: None)
    assert shell.sql("SELECT 3") == 3
    [(cmd, stdin)] = seen
    assert cmd[:-1] == [*COMPOSE.split(), "exec", "-T", "postgres", "sh", "-c"]
    assert '"$POSTGRES_USER"' in cmd[-1] and stdin == "SELECT 3"


# ---- Chờ lượt nền sau 202 (lỗi thật lần chạy `restart` đầu, 27/09/2026) -----------------------


class TurnsShell(Shell):
    """`turns` của ticket lần lượt trả từng phần tử `seq` (phần tử cuối lặp lại)."""

    def __init__(self, seq: list[list[dict[str, Any]]]) -> None:
        super().__init__(COMPOSE.split(), run=FakeRun(), echo=lambda _: None)
        self.seq = seq

    def sql(self, query: str) -> Any:
        return self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]


class FakeView:
    def get(self, path: str, headers: Any = None) -> Any:
        class R:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"status": "S_PENDING_APPROVAL"}

        return R()


def _ctx(seq: list[list[dict[str, Any]]]) -> gate2.Ctx:
    ctx = gate2.Ctx(shell=TurnsShell(seq), http=FakeView(), report=Report(echo=lambda _: None),  # type: ignore[arg-type]
                    password="x")  # fmt: skip
    ctx.tokens[gate2.EMPLOYEE] = {}
    return ctx


def test_after_event_waits_for_new_turn_to_close() -> None:
    old = {"ended": True}
    ctx = _ctx([[old], [old], [old, {"ended": False}], [old, {"ended": True}]])
    assert ctx.after_event("tk-1", 1, timeout=5, interval=0)["status"] == "S_PENDING_APPROVAL"
    assert ctx.shell.seq == [[old, {"ended": True}]]  # type: ignore[attr-defined]  # đã đọc tới lượt đóng


def test_after_event_does_not_accept_old_state() -> None:
    """Chỉ có lượt cũ (lượt nền chưa bắt đầu) → không được trả về trạng thái chờ cũ."""
    ctx = _ctx([[{"ended": True}]])
    with pytest.raises(gate2.StackError, match="lượt mới"):
        ctx.after_event("tk-1", 1, timeout=0.05, interval=0.01)


def test_reads_after_202_always_wait_for_turn() -> None:
    """Mọi chỗ đọc trạng thái sau request 202 dùng `after_event`; `closed` (chờ `final_state`) chỉ cho
    việc do WORKER làm (`expire`, `late_click`); không còn cách chờ nào khác (`settled` đã bỏ)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(gate2))
    waits: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                    waits.setdefault(call.func.attr, set()).add(fn.name)
    assert not hasattr(gate2.Ctx, "settled") and "settled" not in waits
    assert waits["closed"] == {"expire", "late_click"}
    assert {"preflight", "_three_waits", "restart", "late_click", "_kill", "tc29"} <= waits["after_event"]


# ---- Chế độ giả qua khởi động lại (lỗi thật verify G=2 lượt 1, 15/10/2026) -------------------
# `up -d backend` sau SIGKILL nội suy lại `${FAKE_SCENARIO:-}` từ .env → .env không có FAKE_* là backend bị
# tạo lại chạy node thật, kill-b15 + tc29 ra S_ESCALATED.


class ModeRun(FakeRun):
    """FakeRun + lệnh đọc chế độ giả lần lượt trả từng phần tử `modes` (phần tử cuối lặp lại); psql trả 0."""

    def __init__(self, modes: list[str]) -> None:
        super().__init__()
        self.modes = modes

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        if cmd[-1] == gate2.FAKE_MODE_SH:
            self.calls.append(cmd)
            return 0, self.modes.pop(0) if len(self.modes) > 1 else self.modes[0]
        if "postgres" in cmd:
            self.calls.append(cmd)
            return 0, "0\n"
        return super().__call__(cmd, stdin)


class StubCtx(gate2.Ctx):
    """HTTP + DB đóng sẵn; chỉ lệnh compose/make đi qua Shell thật (ModeRun ghi lại)."""

    def login_all(self) -> None:
        self.tokens = {gate2.APPROVER: {}, gate2.EMPLOYEE: {}}

    def create(self, preset: str, label: str) -> str:
        return f"tk-{preset}"

    def health_up(self, timeout: float = 120) -> None:
        pass

    def after_event(self, ticket: str, turns_before: int, timeout: float = 30,
                    interval: float = 0.5) -> dict[str, Any]:  # fmt: skip
        return {"status": gate2.S_PENDING_APPROVAL, "final_state": None, "exit_code": None, "close_reason": None}

    def post(self, path: str, body: Any, headers: Any) -> Any:
        return type("R", (), {"status_code": 202})()

    def turns(self, ticket: str) -> list[dict[str, Any]]:
        return [{"turn_id": "u-1", "ended": False, "recover_attempts": 0}]

    def ticket_lock_count(self, ticket: str) -> int:
        return 0

    def approvals(self, ticket: str) -> list[dict[str, Any]]:
        return [{"approval_id": "a-1", "status": "pending", "decided_by": None}]

    def effects(self, ticket: str) -> list[str]:
        return ["approval_create"]

    def audit(self, ticket: str) -> list[dict[str, Any]]:
        return [{"step": "B3", "event": "intent_classified", "detail": {}}]


def _stub(modes: list[str]) -> tuple[StubCtx, ModeRun, list[str]]:
    run, out = ModeRun(modes), cast(list[str], [])
    ctx = StubCtx(shell=Shell(COMPOSE.split(), run=run, echo=lambda _: None), http=None,  # type: ignore[arg-type]
                  report=Report(echo=out.append), password="x")  # fmt: skip
    return ctx, run, out


@pytest.mark.parametrize("scenario", [gate2.kill, gate2.kill_b15])
def test_kill_restarts_backend_with_start_not_up(scenario: Any) -> None:
    ctx, run, out = _stub(["approval|40"])
    scenario(ctx)
    cmds = [" ".join(c) for c in run.calls]
    killed, started = f"{COMPOSE} kill -s SIGKILL backend", f"{COMPOSE} start backend"
    assert killed in cmds and started in cmds and cmds.index(killed) < cmds.index(started)
    assert not any("up -d backend" in c for c in cmds)
    assert any(line.startswith("PASS") and "chế độ giả giữ nguyên" in line for line in out)


def test_kill_reports_fake_mode_lost_after_restart() -> None:
    ctx, _, out = _stub(["approval|40", "|"])
    gate2.kill(ctx)
    assert any(line.startswith("FAIL") and "chế độ giả giữ nguyên" in line for line in out)


def test_restart_all_fails_clearly_when_make_up_drops_fake_mode() -> None:
    ctx, run, out = _stub(["approval|40", "|"])
    gate2.restart_all(ctx)
    cmds = [" ".join(c) for c in run.calls]
    assert f"{COMPOSE} down" in cmds and "make up" in cmds  # vẫn dựng lại toàn bộ
    assert any(line.startswith("FAIL") and "FAKE_SCENARIO" in line for line in out)


def test_restart_all_passes_when_fake_mode_kept() -> None:
    ctx, _, out = _stub(["approval|40"])
    gate2.restart_all(ctx)
    assert not any("FAKE_SCENARIO" in line for line in out)
    assert any(line.startswith("PASS") and "chế độ giả backend giữ nguyên" in line for line in out)
