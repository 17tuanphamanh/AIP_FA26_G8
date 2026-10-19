"""G2 mốc 2 — lái stack (`app.eval.stack`) + diễn viên (`app.eval.actors`): `ScriptedUser`, `SimApprover` (P8 §5.2).

Không Docker: `Shell` chạy với `run` giả, HTTP qua `httpx.MockTransport` (`FakeApi`), DB qua `FakeDb`, đồng hồ `FakeClock`.
"""

from pathlib import Path
from typing import Any

import httpx
import pytest
from app.eval.actors import REJECT_NOTE, ScriptedUser, SimApprover
from app.eval.dataset import Scenario
from app.eval.stack import (
    READ_ONLY,
    Api,
    Clock,
    Deadline,
    ScenarioTimeout,
    Shell,
    StackError,
    Unsafe,
    check_command,
    check_url,
    quote,
    safety_gate,
    wait_for,
    wait_turn_closed,
)
from tests.fakes.demo import DEMO_PASSWORD
from tests.unit.eval.fake_stack import FakeApi, FakeClock, FakeDb, accepted, login_ok

EVAL_DIR = Path(__file__).resolve().parents[3] / "app" / "eval"
PW = "SENTINEL_PW_from_env"


def scn(turns: list[Any]) -> Scenario:
    return Scenario.model_validate({"id": "S1", "family": "F1", "requester": "an.nv", "turns": turns,
                                    "gold": {"intents": ["vpn"], "expected_route": "HITL"}})  # fmt: skip


def clock(fake: FakeClock) -> Clock:
    return Clock(monotonic=fake.monotonic, sleep=fake.sleep)


# ---- chốt an toàn -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://127.0.0.1:8000/"])
def test_check_url_ok(url: str) -> None:
    assert check_url(url) == "http://127.0.0.1:8000"


@pytest.mark.parametrize("url", ["http://localhost:8000", "https://127.0.0.1:8000", "http://127.0.0.1:8000/api",
                                 "http://10.0.0.1:8000"])  # fmt: skip
def test_check_url_refuses(url: str) -> None:
    with pytest.raises(Unsafe):
        check_url(url)


@pytest.mark.parametrize("cmd", [["docker", "compose", "down", "-v"], ["docker", "compose", "down", "--volumes"],
                                 ["docker", "volume", "rm", "x"], ["docker", "volume", "prune"]])  # fmt: skip
def test_check_command_refuses_volume_delete(cmd: list[str]) -> None:
    with pytest.raises(Unsafe):
        check_command(cmd)


@pytest.mark.parametrize("value", ["", "a'b", "a b", "x" * 65, "a;DROP"])
def test_quote_rejects(value: str) -> None:
    with pytest.raises(StackError):
        quote(value)


def test_quote_ok() -> None:
    assert quote("ha.lt") == "'ha.lt'" and quote("T-01_x") == "'T-01_x'"


# ---- Shell ------------------------------------------------------------------------------------------------------------


class FakeRun:
    def __init__(self, *outs: tuple[int, str]) -> None:
        self.outs = list(outs)
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        self.calls.append((cmd, stdin))
        return self.outs.pop(0)


def test_sql_read_only_prefix() -> None:
    run = FakeRun((0, '{"n": 1}\n'), (0, "\n"))
    sh = Shell(["docker", "compose"], run=run)
    assert sh.sql("SELECT 1") == {"n": 1}
    assert sh.sql("SELECT 2") is None  # psql không in gì → None
    for cmd, stdin in run.calls:
        assert cmd[:5] == ["docker", "compose", "exec", "-T", "postgres"]
        assert stdin is not None and stdin.startswith(READ_ONLY)
    assert READ_ONLY.strip() == "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;"


def test_shell_sql_no_echo(capsys: pytest.CaptureFixture[str]) -> None:
    """Khác gate2: không echo lệnh / SQL — chế độ mặc định chỉ in số tổng hợp (M-G2-22)."""
    sh = Shell(["docker", "compose"], run=FakeRun((0, "1\n"), (0, "\x00")))
    sh.sql("SELECT 'SENTINEL_Q'")
    sh.compose("ps")
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_shell_error_hides_output() -> None:
    sh = Shell(["docker", "compose"], run=FakeRun((1, "SENTINEL_OUT")))
    with pytest.raises(StackError) as e:
        sh.sql("SELECT 'SENTINEL_Q'")
    assert "SENTINEL" not in str(e.value)


def test_shell_env() -> None:
    run = FakeRun((0, "1dev\x000\x00"))
    assert Shell(["dc"], run=run).env("backend", ["APP_ENV", "STRATEGY"]) == {"APP_ENV": "dev", "STRATEGY": None}
    assert run.calls[0][0][:4] == ["dc", "exec", "-T", "backend"]


@pytest.mark.parametrize("names", [[], ["app_env"], ["A;rm"]])
def test_shell_env_bad_names(names: list[str]) -> None:
    with pytest.raises(StackError):
        Shell(["dc"], run=FakeRun()).env("backend", names)


@pytest.mark.parametrize(("out", "ok"), [("1dev\x00", True), ("1prod\x00", False), ("0\x00", False)])
def test_safety_gate(out: str, ok: bool) -> None:
    sh = Shell(["dc"], run=FakeRun((0, out)))
    if ok:
        safety_gate(sh)
    else:
        with pytest.raises(Unsafe):
            safety_gate(sh)


# ---- hạn kịch bản -----------------------------------------------------------------------------------------------------


def test_deadline_boundary() -> None:
    """`elapsed >= timeout_s` là hết giờ — đúng bằng hạn cũng là hết."""
    fake = FakeClock(now=100.0)
    d = Deadline(clock(fake), 30)
    fake.now = 129.999
    assert not d.expired()
    fake.now = 130.0
    assert d.expired()
    with pytest.raises(ScenarioTimeout):
        d.check()


def test_wait_for_value() -> None:
    fake = FakeClock()
    values = iter([None, None, 7])
    assert wait_for(lambda: next(values), Deadline(clock(fake), 10), interval=1) == 7
    assert fake.slept == [1, 1]


def test_wait_for_timeout() -> None:
    fake = FakeClock()
    with pytest.raises(ScenarioTimeout):
        wait_for(lambda: None, Deadline(clock(fake), 3), interval=1)
    assert fake.now == 3


def test_wait_turn_closed() -> None:
    db = FakeDb()
    db.turns["T1"] = [True, False]
    fake = FakeClock()

    def close_later(seconds: float) -> None:
        FakeClock.sleep(fake, seconds)
        db.turns["T1"] = [True, True]

    wait_turn_closed(db, "T1", 1, Deadline(Clock(fake.monotonic, close_later), 10), interval=1)
    assert fake.slept == [1]


def test_wait_turn_closed_needs_new_turn() -> None:
    """Lượt cũ đã đóng nhưng chưa có lượt MỚI → còn chờ (đọc ngay sau 202 vẫn thấy trạng thái cũ)."""
    db = FakeDb()
    db.turns["T1"] = [True]
    with pytest.raises(ScenarioTimeout):
        wait_turn_closed(db, "T1", 1, Deadline(clock(FakeClock()), 2), interval=1)


# ---- Api --------------------------------------------------------------------------------------------------------------


def test_api_error_shows_template_not_id() -> None:
    fake = FakeApi()
    with fake.client() as http, pytest.raises(StackError) as e:
        Api(http).view({}, "SENTINEL_TID")
    assert "SENTINEL" not in str(e.value) and "/api/tickets/{id}" in str(e.value)


def test_api_login_without_token() -> None:
    fake = FakeApi()
    fake.on("POST", "/api/auth/login", lambda r: httpx.Response(200, json={}))
    with fake.client() as http, pytest.raises(StackError):
        Api(http).login("an.nv", PW)


def test_api_create_checks_id() -> None:
    fake = FakeApi()
    fake.on("POST", "/api/tickets", accepted(ticket_id="bad id'"))
    with fake.client() as http, pytest.raises(StackError):
        Api(http).create({}, "x")


# ---- ScriptedUser -----------------------------------------------------------------------------------------------------


def test_scripted_user_sequence() -> None:
    u = ScriptedUser(scn(["c1", "c2", "c3"]))
    assert u.first_text == "c1"
    assert [u.next_answer(), u.next_answer(), u.next_answer(), u.next_answer()] == ["c2", "c3", None, None]


def test_scripted_user_on_confirm() -> None:
    u = ScriptedUser(scn(["c1", {"text": "c2", "on_confirm": False}, {"text": "c3", "on_confirm": True}]))
    assert u.on_confirm is True  # mặc định (câu 2, 3 chưa gửi)
    u.next_answer()
    assert u.on_confirm is False
    u.next_answer()
    assert u.on_confirm is True


# ---- SimApprover ------------------------------------------------------------------------------------------------------


def approver_stack() -> tuple[FakeDb, FakeApi]:
    """Ticket T1 của `an.nv` (u_an), phiếu giao cho `ha.lt` (l1_01) — người gửi ≠ người duyệt (bắt đăng nhập nhầm người)."""
    db = FakeDb()
    db.add_ticket("T1", requester_id="u_an")
    db.approvals.append({"ticket_id": "T1", "approval_id": "A1", "approver_id": "l1_01", "status": "pending"})
    db.users.update({"l1_01": "ha.lt", "u_an": "an.nv"})
    api = FakeApi()
    api.on("POST", "/api/auth/login", login_ok("tok-l1"))
    api.on("POST", "/api/approvals/A1/decision", accepted(status="accepted"))
    return db, api


@pytest.mark.parametrize(("decision", "action", "body"), [
    ("approve", "approved", {"decision": "approved"}),
    (None, "approved", {"decision": "approved"}),  # TODO(G2-Q6): thiếu approver_decision → approve
    ("reject", "rejected", {"decision": "rejected", "note": REJECT_NOTE}),
])  # fmt: skip
def test_sim_approver_decides(decision: Any, action: str, body: dict[str, Any]) -> None:
    db, api = approver_stack()
    with api.client() as http:
        assert SimApprover(Api(http), db, PW).act("T1", decision) == action
    assert api.calls == [("POST", "/api/auth/login", {"username": "ha.lt", "password": PW}),
                         ("POST", "/api/approvals/A1/decision", body)]  # fmt: skip


def test_sim_approver_reject() -> None:
    """`rejected` thiếu `note` → 422 ở API (approvals.py:199-200): ghi chú phải có, khác rỗng."""
    db, api = approver_stack()
    with api.client() as http:
        SimApprover(Api(http), db, PW).act("T1", "reject")
    note = api.calls[-1][2]["note"]
    assert isinstance(note, str) and note.strip()


def test_sim_approver_ignore() -> None:
    db, api = approver_stack()
    with api.client() as http:
        assert SimApprover(Api(http), db, PW).act("T1", "ignore") == "ignored"
    assert api.calls == [] and db.queries == []


def test_sim_approver_no_pending() -> None:
    db, api = approver_stack()
    db.approvals[0]["status"] = "approved"
    with api.client() as http, pytest.raises(StackError):
        SimApprover(Api(http), db, PW).act("T1", "approve")


def test_sim_approver_unknown_user() -> None:
    db, api = approver_stack()
    db.users.clear()
    with api.client() as http, pytest.raises(StackError):
        SimApprover(Api(http), db, PW).act("T1", "approve")
    assert api.calls == []


def test_no_password_constant_in_app_eval() -> None:
    """Mật khẩu chỉ lấy từ `EVAL_PASSWORD` — không chép mật khẩu demo vào `app/` (Dương 18/10)."""
    sources = sorted(EVAL_DIR.glob("*.py"))
    assert sources
    assert all(DEMO_PASSWORD not in p.read_text(encoding="utf-8") for p in sources)
