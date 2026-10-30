"""P6 gói tuần 8 (D-67) — `scripts/sim/chay_thu_phuong_an.py` với HTTP GIẢ (`httpx.MockTransport`), không stack, không DB.

Kiểm: dừng TRƯỚC mọi PUT/POST khi server EVAL_MODE; thứ tự PUT rule_only → hybrid → hybrid_guarded (409 same_as_current = đã đúng, đi
tiếp); `finally` khôi phục chiến lược BAN ĐẦU chỉ khi khác (kể cả lỗi giữa chừng), không PUT thừa; header `X-Sim-Run`
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
ROUND_REASON, RESTORE_REASON = "chạy dữ liệu thử", "khôi phục sau chạy thử dữ liệu thử"
WAIT = ["confirm", "confirm", "confirm", "confirm", "approval", "approval", None, None]


class FakeApi:
    """Server giả: giữ chiến lược hiện hành (`current`), `eval_mode`; PUT trùng hiện hành → 409 `same_as_current` (như server thật)."""

    def __init__(self, *, start: str = "hybrid", eval_mode: bool = False, fail_tickets_in_round: int | None = None,
                 fail_restore: bool = False, busy_polls: int = 0, wait_by_round: dict[int, list[str | None]] | None = None,
                 e2: dict[int, set[int]] | None = None) -> None:  # fmt: skip
        self.events: list[tuple[str, str, bool]] = []  # (post|get, ticket, đã dừng?) theo thứ tự thật
        self.busy_polls, self.wait_by_round, self.e2 = busy_polls, wait_by_round or {}, e2 or {}  # e2: vòng → chỉ số ticket kết thúc E2
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        self.current, self.eval_mode = start, eval_mode
        self.attempts: list[tuple[str, str, int]] = []  # (strategy, reason, mã HTTP) của MỌI PUT
        self.tickets: dict[str, dict[str, Any]] = {}
        self.decisions: list[tuple[str, dict[str, Any]]] = []
        self.confirms: list[tuple[int, dict[str, Any]]] = []
        self.tokens: list[str] = []
        self.otps: list[str] = []
        self.fail_round, self.fail_restore = fail_tickets_in_round, fail_restore

    @property
    def round(self) -> int:
        return sum(1 for _, reason, _ in self.attempts if reason == ROUND_REASON) - 1

    def _put(self, body: dict[str, Any]) -> httpx.Response:
        if self.fail_restore and body["reason"] == RESTORE_REASON:
            self.attempts.append((body["strategy"], body["reason"], 503))
            return httpx.Response(503, json={"detail": "x"})
        status = 409 if body["strategy"] == self.current else 200
        self.attempts.append((body["strategy"], body["reason"], status))
        if status == 409:
            return httpx.Response(409, json={"detail": "same_as_current"})
        self.current = body["strategy"]
        return httpx.Response(200, json={"strategy": self.current})

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
        if path == "/api/admin/strategy":
            if req.method == "PUT":
                return self._put(body)
            return httpx.Response(200, json={"strategy": self.current, "eval_mode": self.eval_mode})
        if req.method == "POST" and path == "/api/tickets":
            if self.fail_round is not None and self.round == self.fail_round:
                return httpx.Response(500, json={"detail": "loi gia"})
            idx = sum(1 for t in self.tickets.values() if t["round"] == self.round)
            tid = f"T{len(self.tickets)}"
            wait = self.wait_by_round.get(self.round, WAIT)[idx]
            is_e2 = idx in self.e2.get(self.round, set())
            self.tickets[tid] = {"round": self.round, "idx": idx, "waiting_for": None if is_e2 else wait,
                                 "final_state": "S_ESCALATED" if wait is None or is_e2 else None, "text": body["text"],
                                 "exit_code": "E2" if is_e2 else None, "polls": 0}  # fmt: skip
            self.events.append(("post", tid, False))
            return httpx.Response(202, json={"ticket_id": tid, "status": "S_NEW", "notices": []})
        if req.method == "GET" and path.startswith("/api/tickets/"):
            tid = path.rsplit("/", 1)[1]
            t = self.tickets[tid]
            t["polls"] += 1
            if t["polls"] <= self.busy_polls:  # còn đang xử lý: chưa dừng
                self.events.append(("get", tid, False))
                return httpx.Response(200, json={"waiting_for": None, "final_state": None, "exit_code": None})
            self.events.append(("get", tid, True))
            return httpx.Response(200, json={"waiting_for": t["waiting_for"], "final_state": t["final_state"], "exit_code": t["exit_code"]})
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
    def __init__(self, monkeypatch: pytest.MonkeyPatch, api: FakeApi, env: dict[str, str] | None = None, *args: str,
                 settle_s: float = 0.0) -> None:  # fmt: skip
        self.mod = load_script(SCRIPT, monkeypatch)
        monkeypatch.setattr(self.mod, "SETTLE_S", settle_s)
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


def _rounds(api: FakeApi) -> list[tuple[str, int]]:
    return [(st, code) for st, reason, code in api.attempts if reason == ROUND_REASON]


def _restores(api: FakeApi) -> list[str]:
    return [st for st, reason, _ in api.attempts if reason == RESTORE_REASON]


def test_start_hybrid_rounds_then_restore_hybrid_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(start="hybrid")
    run = Run(monkeypatch, api)
    assert run.code == 0, run.err
    assert _rounds(api) == [("rule_only", 200), ("hybrid", 200), ("hybrid_guarded", 200)]
    assert _restores(api) == ["hybrid"] and api.current == "hybrid"
    assert run.out == ["rule_only: 8 ticket", "hybrid: 8 ticket", "hybrid_guarded: 8 ticket",
                       "đã khôi phục cách xử lý ban đầu: hybrid", "tổng: rule_only 8, hybrid 8, hybrid_guarded 8"]  # fmt: skip
    assert len(api.tickets) == 24


def test_start_rule_only_409_round_counts_then_exactly_one_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vòng 1 PUT rule_only → 409 same_as_current (đã đúng) → vẫn chạy vòng; kết thúc khôi phục rule_only đúng 1 lần."""
    api = FakeApi(start="rule_only")
    run = Run(monkeypatch, api)
    assert run.code == 0, run.err
    assert _rounds(api) == [("rule_only", 409), ("hybrid", 200), ("hybrid_guarded", 200)]
    assert _restores(api) == ["rule_only"] and api.current == "rule_only"
    assert len(api.tickets) == 24


def test_start_hybrid_guarded_no_restore_put(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(start="hybrid_guarded")
    run = Run(monkeypatch, api)
    assert run.code == 0, run.err
    assert _rounds(api) == [("rule_only", 200), ("hybrid", 200), ("hybrid_guarded", 200)]
    assert _restores(api) == [] and api.current == "hybrid_guarded"  # vòng cuối đã là ban đầu → KHÔNG PUT khôi phục
    assert "cách xử lý hiện hành đã là ban đầu (hybrid_guarded) — không cần khôi phục" in run.out


def test_eval_mode_stops_before_any_put_or_post(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(start="rule_only", eval_mode=True)
    run = Run(monkeypatch, api)
    assert run.code == run.mod.EVAL_REFUSED != 0
    assert api.attempts == [] and api.tickets == {} and run.resets == []
    assert not [c for c in api.calls if c[0] in ("PUT", "POST") and c[1] != "/api/auth/login"]
    assert run.err == ["DỪNG: server đang EVAL_MODE — không chạy dữ liệu thử, không đổi gì"]


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


@pytest.mark.parametrize("start", ["rule_only", "hybrid", "hybrid_guarded"])
def test_finally_restores_start_when_round_2_fails(monkeypatch: pytest.MonkeyPatch, start: str) -> None:
    api = FakeApi(start=start, fail_tickets_in_round=1)  # vòng 2 (hybrid) lỗi khi tạo ticket
    run = Run(monkeypatch, api)
    assert run.code == 1
    assert [st for st, _ in _rounds(api)] == ["rule_only", "hybrid"]  # không sang hybrid_guarded
    assert api.current == start
    assert _restores(api) == ([] if start == "hybrid" else [start])  # đang là hybrid = ban đầu → không PUT
    assert any("DỪNG giữa chừng: tạo ticket: HTTP 500" in e for e in run.err)
    assert run.out[-1] == "tổng: rule_only 8"


def test_restore_failure_warns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(start="rule_only", fail_restore=True)
    run = Run(monkeypatch, api)
    assert run.code == 1
    assert any(e.startswith("CẢNH BÁO: chưa khôi phục được cách xử lý ban đầu rule_only (đổi cách xử lý → rule_only: HTTP 503)")
               for e in run.err)  # fmt: skip


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
    gets = [c for c in api.calls if c[:2] == ("GET", "/api/admin/strategy")]
    assert (len(api.attempts), len(gets)) == (4, 2)  # 3 vòng + 1 khôi phục; đọc lúc đầu + trong finally
    assert len(manager_logins) == 6  # đăng nhập lại trước MỖI lời gọi quản lý (PUT cần đăng nhập gần đây)
    assert run.prompts == []
    assert all(len(o) == 6 and o.isdigit() for o in api.otps)
    order = [c[1] if c[1] != "/api/auth/login" else f"login:{c[2]['username']}" for c in api.calls]
    admin = [i for i, c in enumerate(api.calls) if c[1] == "/api/admin/strategy"]
    assert all(order[i - 1] == "login:quan.tm" for i in admin)


def test_otp_prompt_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api, {k: v for k, v in ENV.items() if k != "SIM_MANAGER_TOTP_SECRET"})
    assert run.code == 0
    assert len(run.prompts) == 6 and api.otps == ["123456"] * 6


def test_mock_reset_each_round_and_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    run = Run(monkeypatch, api)
    assert run.resets == [list(run.mod.MOCK_RESET)] * 3
    api2 = FakeApi()
    run2 = Run(monkeypatch, api2, None, "--no-mock-reset")
    assert run2.resets == [] and run2.code == 0


def test_output_has_no_text_token_password_otp(monkeypatch: pytest.MonkeyPatch) -> None:
    for api, args in ((FakeApi(), ()), (FakeApi(fail_tickets_in_round=0), ()), (FakeApi(start="rule_only", fail_restore=True), ("--tagged",))):
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


# ---- tuần tự / song song ----------------------------------------------------------------------------------------------------


def _round_events(api: FakeApi, rnd: int) -> list[tuple[str, str, bool]]:
    ids = {tid for tid, t in api.tickets.items() if t["round"] == rnd}
    return [e for e in api.events if e[1] in ids]


def test_tuan_tu_mac_dinh_gui_ticket_ke_chi_sau_khi_ticket_truoc_dung(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(busy_polls=2)
    run = Run(monkeypatch, api, None, settle_s=1000.0)
    assert run.code == 0, run.err
    for rnd in range(3):
        ev = _round_events(api, rnd)
        posts = [i for i, e in enumerate(ev) if e[0] == "post"]
        assert len(posts) == 8
        for k in range(1, 8):
            before = ev[posts[k] - 1]  # sự kiện ngay trước lần gửi thứ k
            assert before[0] == "get" and before[1] == ev[posts[k - 1]][1] and before[2] is True  # ticket trước đã dừng
            assert sum(1 for e in ev[: posts[k]] if e[:2] == ("get", ev[posts[k - 1]][1])) == 3  # busy 2 lần rồi mới dừng


def test_tuan_tu_cung_nghia_voi_co_tuan_tu_tuong_minh(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = FakeApi(busy_polls=1), FakeApi(busy_polls=1)
    Run(monkeypatch, a, None, settle_s=1000.0)
    Run(monkeypatch, b, None, "--tuan-tu", settle_s=1000.0)
    assert a.events == b.events


def test_song_song_giu_hanh_vi_cu_gui_het_roi_moi_cho(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(busy_polls=2)
    run = Run(monkeypatch, api, None, "--song-song", settle_s=1000.0)
    assert run.code == 0, run.err
    for rnd in range(3):
        ev = _round_events(api, rnd)
        assert [e[0] for e in ev[:8]] == ["post"] * 8  # 8 lần gửi liền nhau, chưa có lần xem nào


def test_hai_che_do_loai_tru_nhau(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        Run(monkeypatch, FakeApi(), None, "--tuan-tu", "--song-song")


# ---- cảnh báo cuối lượt ------------------------------------------------------------------------------------------------------

NO_APPROVAL: list[str | None] = ["confirm", "confirm", "confirm", "confirm", "confirm", "confirm", None, None]


def test_mot_cach_khong_co_ticket_toi_buoc_duyet_canh_bao_ma_4_van_khoi_phuc(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(start="rule_only", wait_by_round={1: NO_APPROVAL})  # vòng 1 = hybrid
    run = Run(monkeypatch, api)
    assert run.code == 4
    assert "CẢNH BÁO: không ticket nào tới bước duyệt ở cách hybrid — dữ liệu thử không dùng được" in run.err
    assert not any("rule_only" in e or "hybrid_guarded" in e for e in run.err)  # chỉ cách có vấn đề
    assert _restores(api) == ["rule_only"] and api.current == "rule_only"  # finally vẫn khôi phục cách ban đầu, TRƯỚC khi thoát
    assert run.out[-2:] == ["đã khôi phục cách xử lý ban đầu: rule_only", "tổng: rule_only 8, hybrid 8, hybrid_guarded 8"]


def test_e2_tren_20_phan_tram_canh_bao_ma_5(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(e2={2: {0, 1}})  # vòng 2 = hybrid_guarded: 2/8 = 25% E2
    run = Run(monkeypatch, api)
    assert run.code == 5
    assert "CẢNH BÁO: ml-service/RAG lỗi ở cách hybrid_guarded, dữ liệu thử không dùng được" in run.err
    assert len(run.err) == 1 and _restores(api) == ["hybrid"] and api.current == "hybrid"


def test_e2_dung_12_5_phan_tram_van_dung_duoc(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, FakeApi(e2={0: {0}, 1: {0}, 2: {0}}))  # 1/8 mỗi cách
    assert run.code == 0 and run.err == []


def test_e2_dung_20_phan_tram_khong_vuot_nguong(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ngưỡng là "> 20%": 8 ticket thì 1 (12,5%) qua, 2 (25%) không — kiểm hàm thuần với 5 lá, 1 E2 = đúng 20%."""
    mod = load_script(SCRIPT, monkeypatch)
    ok, code = mod.unusable({"x": mod.RoundStat(5, 1, 1)})
    assert ok == [] and code == 0
    bad, code = mod.unusable({"x": mod.RoundStat(5, 1, 2)})
    assert len(bad) == 1 and code == mod.E2_HIGH


def test_e2_cao_va_khong_co_duyet_ma_5_uu_tien_va_ca_hai_canh_bao(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(e2={0: {0, 1, 2, 3, 4, 5}}, wait_by_round={0: NO_APPROVAL})
    run = Run(monkeypatch, api)
    assert run.code == 5
    assert "CẢNH BÁO: ml-service/RAG lỗi ở cách rule_only, dữ liệu thử không dùng được" in run.err
    assert "CẢNH BÁO: không ticket nào tới bước duyệt ở cách rule_only — dữ liệu thử không dùng được" in run.err


def test_du_duyet_va_e2_thap_ma_0_khong_canh_bao(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, FakeApi())
    assert run.code == 0 and run.err == []


def test_canh_bao_khong_in_cau_chu_token_mat_khau(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(e2={0: {0, 1, 2}}, wait_by_round={1: NO_APPROVAL})
    run = Run(monkeypatch, api)
    shown = "\n".join([*run.out, *run.err])
    assert run.code == 5 and PW not in shown and SECRET not in shown
    assert not any(t["text"] in shown for t in api.tickets.values()) and not any(tok in shown for tok in api.tokens)


def test_dung_giua_chung_giu_ma_1_van_bao_cac_vong_da_xong(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(fail_tickets_in_round=1, wait_by_round={0: NO_APPROVAL})
    run = Run(monkeypatch, api)
    assert run.code == 1  # lỗi chung giữ nguyên mã 1
    assert any("không ticket nào tới bước duyệt ở cách rule_only" in e for e in run.err)  # vòng 0 đã xong vẫn được báo
    assert _restores(api) == [] and api.current == "hybrid"  # đứt ở vòng hybrid = cách ban đầu → không PUT thừa


def test_khoi_phuc_loi_giu_ma_1_du_co_canh_bao(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, FakeApi(fail_restore=True, start="rule_only", e2={0: {0, 1, 2}}))
    assert run.code == 1
    assert any("chưa khôi phục được cách xử lý ban đầu" in e for e in run.err)
    assert any("ml-service/RAG lỗi ở cách rule_only" in e for e in run.err)
