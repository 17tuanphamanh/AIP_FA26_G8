"""P6 gói tuần 8 (D-67) — `scripts/sim/chay_thu_phuong_an.py` với HTTP GIẢ (`httpx.MockTransport`), không stack, không DB.

Kiểm: thứ tự PUT rule_only → hybrid → hybrid_guarded rồi đặt lại hybrid; đặt lại trong `finally` khi lỗi giữa chừng; header `X-Sim-Run`
trên MỌI yêu cầu tạo ticket; từ chối ngoài dev/test và URL không phải localhost (0 lời gọi HTTP); danh sách duyệt/xác nhận cố định;
OTP từ biến môi trường hoặc hỏi tương tác (đăng nhập lại trước MỖI PUT); không in câu chữ, token, mật khẩu, OTP; reset mock mỗi vòng.
"""

import json
from typing import Any

import httpx
import pyotp
import pytest
from tests.unit._b2review import REPO, load_script

SCRIPT = "scripts/sim/chay_thu_phuong_an.py"
PW = "mat-khau-thu-sim"
SECRET = pyotp.random_base32()
ENV = {"APP_ENV": "dev", "SIM_PASSWORD": PW, "SIM_MANAGER_TOTP_SECRET": SECRET}
# chỗ dừng giả của 8 yêu cầu (thứ tự REQUESTS): KB/allow → chờ xác nhận; cần duyệt → chờ duyệt; không luật → đã kết thúc
WAIT = ["confirm", "confirm", "confirm", "confirm", "approval", "approval", None, None]


class FakeApi:
    def __init__(self, *, fail_tickets_in_round: int | None = None, fail_reset: bool = False) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        self.puts: list[str] = []
        self.tickets: dict[str, dict[str, Any]] = {}
        self.decisions: list[tuple[str, dict[str, Any]]] = []
        self.confirms: list[tuple[int, dict[str, Any]]] = []
        self.tokens: list[str] = []
        self.otps: list[str] = []
        self.fail_round, self.fail_reset = fail_tickets_in_round, fail_reset

    def handler(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        path = req.url.path
        self.calls.append((req.method, path, body, dict(req.headers)))
        if path == "/api/auth/login":
            if "otp" in body:
                self.otps.append(body["otp"])
            token = f"tok-{body['username']}-{len(self.tokens)}"
            self.tokens.append(token)
            return httpx.Response(200, json={"access_token": token})
        if req.method == "PUT" and path == "/api/admin/strategy":
            if self.fail_reset and body["strategy"] == "hybrid" and len(self.puts) == 3:
                return httpx.Response(503, json={"detail": "x"})
            self.puts.append(body["strategy"])
            return httpx.Response(200, json={"strategy": body["strategy"]})
        if req.method == "POST" and path == "/api/tickets":
            if self.fail_round is not None and len(self.puts) - 1 == self.fail_round:
                return httpx.Response(500, json={"detail": "loi gia"})
            idx = sum(1 for t in self.tickets.values() if t["round"] == len(self.puts) - 1)
            tid = f"T{len(self.tickets)}"
            self.tickets[tid] = {"round": len(self.puts) - 1, "idx": idx, "waiting_for": WAIT[idx],
                                 "final_state": "S_ESCALATED" if WAIT[idx] is None else None, "text": body["text"]}  # fmt: skip
            return httpx.Response(202, json={"ticket_id": tid, "status": "S_NEW", "notices": []})
        if req.method == "GET" and path.startswith("/api/tickets/"):
            t = self.tickets[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"waiting_for": t["waiting_for"], "final_state": t["final_state"]})
        if req.method == "GET" and path == "/api/approvals":
            items = [{"ticket_id": tid, "approval_id": f"A{tid}"} for tid, t in self.tickets.items() if t["waiting_for"] == "approval"]
            return httpx.Response(200, json={"items": items})
        if req.method == "GET" and path.startswith("/api/approvals/"):
            return httpx.Response(200, json={})
        if req.method == "POST" and path.endswith("/decision"):
            tid = path.split("/")[3].removeprefix("A")
            self.decisions.append((tid, body))
            t = self.tickets[tid]
            t["waiting_for"], t["final_state"] = ("confirm", None) if body["decision"] == "approved" else (None, "S_REJECTED")
            return httpx.Response(202, json={})
        if req.method == "POST" and path.endswith("/confirm"):
            tid = path.split("/")[3]
            self.confirms.append((self.tickets[tid]["idx"], body))
            return httpx.Response(202, json={})
        return httpx.Response(404, json={"detail": "not_found"})


class Run:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, api: FakeApi, env: dict[str, str] | None = None, *args: str) -> None:
        self.mod = load_script(SCRIPT, monkeypatch)
        monkeypatch.setattr(self.mod, "SETTLE_S", 0.0)
        self.out: list[str] = []
        self.err: list[str] = []
        self.prompts: list[str] = []
        self.resets: list[list[str]] = []
        client = httpx.Client(transport=httpx.MockTransport(api.handler), base_url="http://127.0.0.1:8000")
        self.code = self.mod.main(
            list(args), env=ENV if env is None else env, client=client, prompt=self._prompt, sleep=lambda _s: None,
            run=lambda cmd, **_kw: self.resets.append(cmd), out=self.out.append, err=self.err.append,
        )  # fmt: skip

    def _prompt(self, label: str) -> str:
        self.prompts.append(label)
        return "123456"


def test_put_order_then_reset_hybrid_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api)
    assert run.code == 0, run.err
    assert api.puts == ["rule_only", "hybrid", "hybrid_guarded", "hybrid"]
    assert all(c[2]["reason"] == "chạy dữ liệu thử" for c in api.calls if c[0] == "PUT")
    assert run.out == ["rule_only: 8 ticket", "hybrid: 8 ticket", "hybrid_guarded: 8 ticket", "đã đặt lại cách xử lý: hybrid",
                       "tổng: rule_only 8, hybrid 8, hybrid_guarded 8"]  # fmt: skip
    assert len(api.tickets) == 24


def test_same_8_requests_each_round_with_sim_header(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api)
    posts = [c for c in api.calls if c[:2] == ("POST", "/api/tickets")]
    assert len(posts) == 24
    assert all(c[3].get("x-sim-run") for c in posts)
    texts = [c[2]["text"] for c in posts]
    assert texts[:8] == texts[8:16] == texts[16:] == [r.text for r in run.mod.REQUESTS]  # không --tagged: không thẻ
    assert [r.group for r in run.mod.REQUESTS] == ["kb", "kb", "allow", "allow", "approval", "approval", "no_rule", "no_rule"]


def test_tagged_appends_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api, None, "--tagged")
    texts = [c[2]["text"] for c in api.calls if c[:2] == ("POST", "/api/tickets")][:8]
    assert texts == [f"{r.text} [fake:{r.preset}]" for r in run.mod.REQUESTS]
    assert [r.preset for r in run.mod.REQUESTS] == ["tc04", "tc05", "tc01", "tc03", "tc07", "tc17", "sim_khongluat", "sim_khongluat"]


def test_fixed_decisions_and_confirms(monkeypatch: pytest.MonkeyPatch) -> None:
    """L1 duyệt tc07, từ chối tc17 (có note); nhân viên xác nhận tc04 + tc01 Đã ổn, tc03 Chưa ổn (có note) — mỗi vòng."""
    api = FakeApi()
    Run(monkeypatch, api)
    by_idx = {api.tickets[tid]["idx"]: d for tid, d in api.decisions}
    assert len(api.decisions) == 6
    assert by_idx[4]["decision"] == "approved" and by_idx[5]["decision"] == "rejected" and by_idx[5]["note"]
    assert {(i, b["confirmed"]) for i, b in api.confirms} == {(0, True), (2, True), (3, False)}
    assert all(b.get("note") for i, b in api.confirms if i == 3)
    assert len(api.confirms) == 9
    views = [c for c in api.calls if c[0] == "GET" and c[1].startswith("/api/approvals/")]
    assert len(views) == 6  # xem phiếu trước khi quyết


def test_finally_resets_hybrid_when_round_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(fail_tickets_in_round=1)  # vòng 2 (hybrid) lỗi khi tạo ticket
    run = Run(monkeypatch, api)
    assert run.code == 1
    assert api.puts == ["rule_only", "hybrid", "hybrid"]  # không sang hybrid_guarded; finally đặt lại hybrid
    assert any("DỪNG giữa chừng: tạo ticket: HTTP 500" in e for e in run.err)
    assert run.out[-2:] == ["đã đặt lại cách xử lý: hybrid", "tổng: rule_only 8"]


def test_reset_failure_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(fail_reset=True)
    run = Run(monkeypatch, api)
    assert run.code == 1
    assert any(e.startswith("CẢNH BÁO: chưa đặt lại được hybrid (đổi cách xử lý → hybrid: HTTP 503)") for e in run.err)


@pytest.mark.parametrize("env", [{**ENV, "APP_ENV": "prod"}, {**ENV, "APP_ENV": "staging"}, {k: v for k, v in ENV.items() if k != "APP_ENV"}])
def test_refuses_outside_dev_test_before_any_http(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api, env)
    assert run.code == 2 and api.calls == [] and run.resets == []
    assert run.err and run.err[0].startswith("TỪ CHỐI: APP_ENV")


@pytest.mark.parametrize("url", ["http://10.0.0.5:8000", "https://servicedesk.example.com"])
def test_refuses_non_localhost(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api, None, "--url", url)
    assert run.code == 2 and api.calls == []
    assert run.err[0].startswith("TỪ CHỐI: URL")


def test_otp_from_env_relogin_before_each_put(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api)
    manager_logins = [c for c in api.calls if c[1] == "/api/auth/login" and c[2]["username"] == "quan.tm"]
    assert len(manager_logins) == 4 == len(api.puts)  # đăng nhập lại trước MỖI PUT
    assert run.prompts == []
    assert all(len(o) == 6 and o.isdigit() for o in api.otps)
    order = [c[1] if c[1] != "/api/auth/login" else f"login:{c[2]['username']}" for c in api.calls]
    puts = [i for i, c in enumerate(api.calls) if c[0] == "PUT"]
    assert all(order[i - 1] == "login:quan.tm" for i in puts)


def test_otp_prompt_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api, {k: v for k, v in ENV.items() if k != "SIM_MANAGER_TOTP_SECRET"})
    assert run.code == 0
    assert len(run.prompts) == 4 and api.otps == ["123456"] * 4


def test_mock_reset_each_round_and_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api)
    assert run.resets == [list(run.mod.MOCK_RESET)] * 3
    api2 = FakeApi()
    run2 = Run(monkeypatch, api2, None, "--no-mock-reset")
    assert run2.resets == [] and run2.code == 0


def test_output_has_no_text_token_password_otp(monkeypatch: pytest.MonkeyPatch) -> None:
    for api, args in ((FakeApi(), ()), (FakeApi(fail_tickets_in_round=0), ()), (FakeApi(fail_reset=True), ("--tagged",))):
        run = Run(monkeypatch, api, None, *args)
        printed = "\n".join(run.out + run.err)
        assert PW not in printed and SECRET not in printed
        assert not [t for t in api.tokens if t in printed]
        assert not [o for o in api.otps if o in printed]
        assert not [r.text for r in run.mod.REQUESTS if r.text in printed]
        assert "loi gia" not in printed  # thân phản hồi lỗi không được in


def test_password_falls_back_to_seed_demo_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Không đặt `SIM_PASSWORD` → mật khẩu demo công khai của seed mock (`tests/fakes/demo.py`) — không hard-code trong script."""
    from tests.fakes.demo import DEMO_PASSWORD

    api = FakeApi()
    run = Run(monkeypatch, api, {k: v for k, v in ENV.items() if k != "SIM_PASSWORD"})
    assert run.code == 0
    assert {c[2]["password"] for c in api.calls if c[1] == "/api/auth/login"} == {DEMO_PASSWORD}
    source = (REPO / SCRIPT).read_text(encoding="utf-8")
    assert DEMO_PASSWORD not in source
